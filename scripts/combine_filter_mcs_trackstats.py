#!/usr/bin/env python
"""
combine_filter_mcs_trackstats.py

Filter and flatten MCS track statistics files for one data source into a
single tidy Parquet file.

For each yearly NetCDF file:
  1. Filter tracks whose lifetime-mean location falls inside the region box.
  2. Flatten the jagged (tracks x times) arrays to a tidy DataFrame
     (one row per valid time step, clipped to each track's real duration).
  3. Assign a globally-unique local_track index across all files.
  4. Tag each row with its source-year ('period' column).

All filtered + flattened frames are concatenated and written to a single
compressed Parquet file.  This eliminates the slow xr.concat(join='outer')
step that used to happen inside the notebook: with time_resolution=1 h and
mean track_duration ~18 steps, ~96% of the raw (tracks x times) array is
fill padding.  Flattening per-file first means that padding is never read.

Output filename (auto-derived):
    {outdir}/mcs_tracks_final_combined_{region}_{start_year}_{end_year}.parquet

Usage
-----
SCREAM, tropics, 1995-2005:
    python combine_filter_mcs_trackstats.py \\
        --indir /pscratch/sd/f/feng045/SCREAM-decadal/ne1024/stats \\
        --region tropics --start-year 1995 --end-year 2005

IMERG, tropics, 1998-2024, custom outdir:
    python combine_filter_mcs_trackstats.py \\
        --indir /pscratch/sd/f/feng045/waccem/mcs_global_v3/MCSMIP/stats \\
        --pattern 'mcsmip_mcs_tracks_final_*.nc' \\
        --region tropics --start-year 1998 --end-year 2024 \\
        --outdir /pscratch/sd/f/feng045/waccem/mcs_global_v3/MCSMIP/stats

Custom bounding box (override region defaults):
    python combine_filter_mcs_trackstats.py \\
        --indir /path/to/stats --region tropics \\
        --latmin -30 --latmax 30
"""

import argparse
import glob
import os
import re
import time
import warnings

import numpy as np
import pandas as pd
import xarray as xr

warnings.filterwarnings('ignore')


# ============================================================
# REGIONS  (lon/lat bounding boxes; extend to add new regions)
# ============================================================
REGIONS = {
    'tropics': dict(lonmin=-180.0, lonmax=180.0, latmin=-20.0, latmax=20.0),
    'global':  dict(lonmin=-180.0, lonmax=180.0, latmin=-90.0, latmax=90.0),
}

# Variables with shape (tracks, times, mergers):
#   _DISCARD     — cloud-number arrays (meaningless after track concatenation)
#   _SUM_MERGERS — area arrays to be summed across the mergers dimension
_DISCARD     = {'merge_cloudnumber', 'split_cloudnumber'}
_SUM_MERGERS = {'merge_ccs_area', 'split_ccs_area'}


# ============================================================
# CORE FUNCTIONS
# ============================================================

def _extract_year(fpath):
    """
    Extract the start year from a yearly track-stats filename.

    Matches the pattern  *_{YYYY}0101.????_*  in the basename.

    Examples
    --------
    mcs_tracks_final_19950101.0000_19960101.0000.nc         -> '1995'
    mcsmip_mcs_tracks_final_20000101.0000_20010101.0000.nc  -> '2000'
    """
    m = re.search(r'_(\d{4})0101\.\d+_', os.path.basename(fpath))
    return m.group(1) if m else 'unknown'


def filter_tracks_by_region(ds, lonmin, lonmax, latmin, latmax):
    """
    Return positional indices of tracks whose lifetime-mean location is
    inside the bounding box.

    Reads ``meanlat`` / ``meanlon`` in a single ``.values`` call (avoids
    lazy chunk-by-chunk overhead on compressed netCDF variables).

    Parameters
    ----------
    ds                             : xr.Dataset
    lonmin, lonmax, latmin, latmax : float

    Returns
    -------
    np.ndarray of int  — positional (not coordinate) indices of kept tracks
    """
    meanlat = ds['meanlat'].values.astype(float)   # (tracks, times)
    meanlon = ds['meanlon'].values.astype(float)

    # Mask fill values (< -900)
    meanlat = np.where(meanlat < -900, np.nan, meanlat)
    meanlon = np.where(meanlon < -900, np.nan, meanlon)

    track_mean_lat = np.nanmean(meanlat, axis=1)   # (tracks,)
    track_mean_lon = np.nanmean(meanlon, axis=1)

    keep = (
        (track_mean_lat >= latmin) & (track_mean_lat <= latmax) &
        (track_mean_lon >= lonmin) & (track_mean_lon <= lonmax)
    )
    return np.where(keep)[0]


def ds_to_dataframe(ds, keep_indices, time_res_h=1.0):
    """
    Convert a MCS track stats xr.Dataset to a tidy Pandas DataFrame.

    One row per valid (track, time-step); padded fill entries beyond each
    track's real ``track_duration`` are never materialised.

    Dimension handling
    ------------------
    Shape                      Treatment
    (tracks,)                  broadcast to all valid steps for that track
    (tracks, times)            fancy-index [orig_track_idx, time_idx]
    (tracks, times, nmaxpf)    clip to max real duration, take index 0 (largest PF)
    (tracks, times, mergers)   _DISCARD -> skip; _SUM_MERGERS -> sum axis=2; others -> skip

    Parameters
    ----------
    ds           : xr.Dataset  — raw, non-isel'd dataset (single file)
    keep_indices : np.ndarray  — positional indices from filter_tracks_by_region
    time_res_h   : float       — time resolution in hours (default 1.0)

    Returns
    -------
    pd.DataFrame with columns:
        local_track       0-based index within keep_indices (offset by caller)
        relative_step     0-based time step from track initiation
        relative_time_h   relative_step x time_res_h
        track_duration_h  track_duration x time_res_h
        <physics vars>    one column per data variable (fill -> NaN)
    Note: 'source' and 'period' columns are NOT added here;
          they are assigned by the caller.
    """
    if keep_indices is None:
        keep_indices = np.arange(ds.sizes['tracks'])
    n_tracks = len(keep_indices)

    # 1-D read: track_duration for kept tracks only
    track_duration = ds['track_duration'].values[keep_indices].astype(int)

    # Build flat row index arrays
    local_idx      = np.repeat(np.arange(n_tracks), track_duration)
    orig_track_idx = keep_indices[local_idx]       # into original (unfiltered) ds
    time_idx       = np.concatenate([np.arange(d) for d in track_duration])

    # Clip 3-D reads to the maximum real duration (avoid reading padding entirely)
    max_time    = int(track_duration.max())
    times_total = ds.sizes.get('times', max_time)
    if max_time < times_total:
        print(f'    times clip: {times_total} -> {max_time} '
              f'(saves {(times_total - max_time) / times_total:.0%} on 3-D reads)')

    data        = {'local_track': local_idx, 'relative_step': time_idx}
    fill_values = {}

    for v in ds.data_vars:
        dims = tuple(ds[v].dims)
        fv   = ds[v].attrs.get('_FillValue', None)

        if dims == ('tracks',):
            data[v] = ds[v].values[orig_track_idx]
            if fv is not None:
                fill_values[v] = fv

        elif dims == ('tracks', 'times'):
            data[v] = ds[v].values[orig_track_idx, time_idx]
            if fv is not None:
                fill_values[v] = fv

        elif dims == ('tracks', 'times', 'nmaxpf'):
            arr     = ds[v].values[:, :max_time, 0]   # largest PF
            data[v] = arr[orig_track_idx, time_idx]
            if fv is not None:
                fill_values[v] = fv

        elif dims == ('tracks', 'times', 'mergers'):
            if v in _DISCARD:
                continue
            if v in _SUM_MERGERS:
                arr = np.nan_to_num(
                    ds[v].values[:, :max_time, :].astype(float),
                    nan=0.0, posinf=0.0, neginf=0.0,
                )
                arr     = np.clip(arr, 0, None)
                data[v] = arr.sum(axis=2)[orig_track_idx, time_idx]
                if fv is not None:
                    fill_values[v] = fv
            # other merger-dimension variables: skip

        # unrecognised dimension shapes: skip

    df = pd.DataFrame(data)

    # Fill values -> NaN (cast to float first so int columns can hold NaN)
    for col, fv in fill_values.items():
        if col in df.columns:
            df[col] = df[col].astype(float).where(df[col] != fv)

    # Decode Epoch-time columns to datetime (UTC)
    for col in ('base_time', 'start_basetime', 'end_basetime'):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], unit='s', errors='coerce', utc=True)

    df['relative_time_h']  = df['relative_step'] * time_res_h
    df['track_duration_h'] = df['track_duration'] * time_res_h
    return df


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        '--indir', required=True,
        help='Directory containing yearly mcs_tracks_final_*.nc files.',
    )
    parser.add_argument(
        '--pattern', default='*mcs_tracks_final_*.nc',
        help='Glob pattern to match input files '
             '(default: *mcs_tracks_final_*.nc).',
    )
    parser.add_argument(
        '--region', default='tropics', choices=list(REGIONS),
        help='Named region for lat/lon filter box (default: tropics).',
    )
    parser.add_argument('--lonmin', type=float, default=None,
                        help='Override region lonmin.')
    parser.add_argument('--lonmax', type=float, default=None,
                        help='Override region lonmax.')
    parser.add_argument('--latmin', type=float, default=None,
                        help='Override region latmin.')
    parser.add_argument('--latmax', type=float, default=None,
                        help='Override region latmax.')
    parser.add_argument(
        '--start-year', type=int, default=None,
        help='First year to include (inclusive). Default: all files found.',
    )
    parser.add_argument(
        '--end-year', type=int, default=None,
        help='Last year to include (inclusive). Default: all files found.',
    )
    parser.add_argument(
        '--outdir', default=None,
        help='Output directory for the Parquet file (default: --indir).',
    )
    args = parser.parse_args()

    # ── Resolve region bounding box ─────────────────────────────────────────
    box = dict(REGIONS[args.region])
    if args.lonmin is not None: box['lonmin'] = args.lonmin
    if args.lonmax is not None: box['lonmax'] = args.lonmax
    if args.latmin is not None: box['latmin'] = args.latmin
    if args.latmax is not None: box['latmax'] = args.latmax

    outdir = args.outdir or args.indir
    os.makedirs(outdir, exist_ok=True)

    # ── Discover files ───────────────────────────────────────────────────────
    all_files = sorted(glob.glob(os.path.join(args.indir, args.pattern)))
    if not all_files:
        raise FileNotFoundError(
            f'No files matching {args.pattern!r} found in {args.indir}')

    # Filter by year range
    selected   = []
    years_seen = []
    for f in all_files:
        yr_str = _extract_year(f)
        if yr_str == 'unknown':
            warnings.warn(
                f'Could not parse year from {os.path.basename(f)} — skipping.')
            continue
        yr = int(yr_str)
        if args.start_year is not None and yr < args.start_year:
            continue
        if args.end_year is not None and yr > args.end_year:
            continue
        selected.append(f)
        years_seen.append(yr)

    if not selected:
        raise ValueError(
            f'No files matched year range '
            f'{args.start_year}–{args.end_year} in {args.indir}')

    print(f'Region : {args.region}  '
          f'lon=[{box["lonmin"]}, {box["lonmax"]}]  '
          f'lat=[{box["latmin"]}, {box["latmax"]}]')
    print(f'Files  : {len(selected)} selected '
          f'(years {min(years_seen)}–{max(years_seen)})')
    print()

    # ── Process each file ────────────────────────────────────────────────────
    dfs          = []
    track_offset = 0
    t_total      = time.time()

    for i, fpath in enumerate(selected):
        yr_str   = _extract_year(fpath)
        t0       = time.time()

        ds       = xr.open_dataset(fpath, mask_and_scale=False, decode_times=False)
        ntracks  = ds.sizes['tracks']
        ntimes   = ds.sizes.get('times', '?')
        time_res = float(ds.attrs.get('time_resolution_hour', 1.0))

        keep     = filter_tracks_by_region(
            ds, box['lonmin'], box['lonmax'], box['latmin'], box['latmax'])
        n_kept   = len(keep)

        df_yr    = ds_to_dataframe(ds, keep, time_res_h=time_res)
        ds.close()

        # Make local_track globally unique across all files in this run
        df_yr['local_track'] += track_offset
        track_offset = int(df_yr['local_track'].max()) + 1

        df_yr['period'] = yr_str   # provenance: which source-year this row came from

        dfs.append(df_yr)
        elapsed = time.time() - t0
        print(f'  [{i+1:02d}/{len(selected):02d}]  '
              f'year={yr_str}  times={ntimes}  '
              f'kept={n_kept:,}/{ntracks:,} tracks  '
              f'rows={len(df_yr):,}  ({elapsed:.1f} s)')

    # ── Concatenate and write ────────────────────────────────────────────────
    print(f'\nCombining {len(dfs)} DataFrames ...')
    combined = pd.concat(dfs, ignore_index=True)
    y0, y1   = min(years_seen), max(years_seen)
    outname  = f'mcs_tracks_final_combined_{args.region}_{y0}_{y1}.parquet'
    outpath  = os.path.join(outdir, outname)

    combined.to_parquet(outpath, engine='pyarrow', compression='zstd', index=False)

    elapsed_total = time.time() - t_total
    print(f'\nDone  ({elapsed_total:.1f} s total)')
    print(f'  Tracks  : {combined["local_track"].nunique():,}')
    print(f'  Rows    : {len(combined):,}')
    print(f'  Columns : {combined.shape[1]}')
    print(f'  Output  : {outpath}')
    print(f'  Size    : {os.path.getsize(outpath) / 1e6:.1f} MB')


if __name__ == '__main__':
    main()
