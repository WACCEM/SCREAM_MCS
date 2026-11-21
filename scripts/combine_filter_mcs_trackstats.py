#!/usr/bin/env python
"""
combine_filter_mcs_trackstats.py

Filter and flatten MCS track statistics files for one data source into a
single tidy Parquet file: one row per track and valid time step, the same
69 columns for every source (UNIFIED_COLUMNS), so that observations, SCREAM
and E3SM can be concatenated in an analysis notebook.

Two kinds of input files are read:
  * dense netCDF files   mcs_tracks_final_<start>_<end>.nc    (old pipeline)
  * row-table folders    mcs_tracks_final_<start>_<end>.rows  (PyFLEXTRKR
    stats_format: rows; tracks.parquet + entries.parquet + fragments.parquet
    + meta.json). Both give identical tables (tests/test_combine_filter_*).
    The row folders are read with pyflextrkr.rowstats.RowStats, so that route
    needs the pyflex26.3 environment (PyFLEXTRKR with rowstats.py, branch
    perf-workflow); the dense route needs only xarray.

For each input file:
  1. Filter tracks whose lifetime-mean location falls inside the region box.
  2. Flatten to a tidy DataFrame (one row per valid time step, clipped to each
     track's real duration).
  3. Assign a globally-unique local_track index across all files.
  4. Tag each row with its 'period': the calendar year in which the track starts.

All filtered + flattened frames are concatenated and written to a single
compressed Parquet file.  This eliminates the slow xr.concat(join='outer')
step that used to happen inside the notebook: with time_resolution=1 h and
mean track_duration ~18 steps, ~96% of the raw (tracks x times) array is
fill padding.  Flattening per-file first means that padding is never read.

Output filename (auto-derived from the years in the 'period' column):
    {outdir}/mcs_tracks_final_combined_{region}_{first_year}_{last_year}.parquet

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

E3SM (row-table folders collected by symbolic links in <root>/stats/):
    python combine_filter_mcs_trackstats.py \\
        --indir /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/stats \\
        --pattern '*mcs_tracks_final_*.rows' --region tropics

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

# The columns of every combined Parquet file, in this order (the format of the
# OBS and SCREAM files). A column that a file does not have (a variable that a
# newer PyFLEXTRKR added) is filled with NaN and reported; a column that is not
# listed here is an error, so that all sources stay concatenable: add a column
# here only together with all sources.
UNIFIED_COLUMNS = [
    'local_track', 'relative_step', 'track_duration', 'start_status', 'end_status', 'start_basetime', 'end_basetime',
    'start_split_cloudnumber', 'end_merge_cloudnumber', 'pbc_flag', 'base_time', 'meanlat', 'meanlon', 'area',
    'cloudnumber', 'track_status', 'track_interruptions', 'core_area', 'cold_area', 'corecold_mintb',
    'corecold_meantb', 'core_meantb', 'lat_mintb', 'lon_mintb', 'meanlon_smooth', 'meanlat_smooth', 'mcs_duration',
    'mcs_status', 'ccs_area', 'merge_ccs_area', 'split_ccs_area', 'pf_npf', 'pf_lon', 'pf_lat', 'pf_area',
    'pf_rainrate', 'pf_skewness', 'pf_majoraxis', 'pf_minoraxis', 'pf_aspectratio', 'pf_orientation',
    'pf_perimeter', 'pf_eccentricity', 'pf_lon_centroid', 'pf_lat_centroid', 'pf_lon_weightedcentroid',
    'pf_lat_weightedcentroid', 'pf_lon_maxrainrate', 'pf_lat_maxrainrate', 'pf_maxrainrate', 'pf_accumrain',
    'pf_accumrainheavy', 'pf_landfrac', 'total_rain', 'total_heavyrain', 'total_volrain', 'total_heavyvolrain',
    'rainrate_heavyrain', 'rainrate_p95', 'pf_lifetime', 'pf_mcsstatus', 'movement_distance', 'movement_speed',
    'movement_theta', 'movement_distance_x', 'movement_distance_y', 'relative_time_h', 'track_duration_h', 'period',
]

# Epoch-time columns (seconds since 1970-01-01), stored as datetime64[ms, UTC]
_TIME_COLUMNS = ('base_time', 'start_basetime', 'end_basetime')


# ============================================================
# CORE FUNCTIONS
# ============================================================

def _extract_year(fpath):
    """
    Extract the start year from a track-statistics file name.

    Matches the start date of the pattern  *_{YYYYMMDD}.{HHMM}_*  in the
    basename (any start date, so a file that does not begin on 1 January, such
    as a 19-month run, is found too).

    Examples
    --------
    mcs_tracks_final_19950101.0000_19960101.0000.nc         -> '1995'
    mcsmip_mcs_tracks_final_20000101.0000_20010101.0000.nc  -> '2000'
    mcs_tracks_final_20190803.0000_20210306.0000.nc         -> '2019'
    mcs_tracks_final_20100101.0000_20110101.0000.rows       -> '2010'
    """
    m = re.search(r'_(\d{4})\d{4}\.\d+_', os.path.basename(os.path.normpath(fpath)))
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
    Note: the 'period' column is NOT added here; it is assigned by the caller
          (add_period).
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
    for col in _TIME_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], unit='s', errors='coerce', utc=True).astype('datetime64[ms, UTC]')

    df['relative_time_h']  = df['relative_step'] * time_res_h
    df['track_duration_h'] = df['track_duration'] * time_res_h
    return df


def rows_to_dataframe(rs, keep_tracks, time_res_h=1.0):
    """
    Convert the row tables of a MCS track stats folder to the tidy DataFrame of ds_to_dataframe.

    The three tables are joined: the per-track variables of ``tracks`` are repeated on every row of
    their track, the [tracks, times] variables are the columns of ``entries`` (the small
    [tracks, times, nmaxpf] PF variables as their first column ``name__0``, the largest PF), and the
    merge / split areas are the sums of ``fragments.ccs_area`` over the fragments of each entry.
    Fill values and data types follow the rules of ds_to_dataframe, so both routes give the same table.

    Parameters
    ----------
    rs          : pyflextrkr.rowstats.RowStats — the opened row folder
    keep_tracks : array-like of int            — track numbers (the ``tracks`` column) to keep
    time_res_h  : float                        — time resolution in hours (default 1.0)

    Returns
    -------
    pd.DataFrame with the columns and dtypes of ds_to_dataframe (no 'period' column).
    """
    meta = rs.meta
    # Tables of the kept tracks only
    tracks = rs.to_pandas('tracks').set_index('tracks').loc[keep_tracks]
    entries = rs.to_pandas('entries')
    entries = entries[entries['track'].isin(keep_tracks)].reset_index(drop=True)
    fragments = rs.to_pandas('fragments')
    fragments = fragments[fragments['track'].isin(keep_tracks)]

    # One row per kept entry; local_track numbers the kept tracks 0..n-1 in file order (entries are sorted by track)
    codes, _ = pd.factorize(entries['track'])
    data = {'local_track': codes.astype('int64'), 'relative_step': entries['k'].to_numpy().astype('int64')}
    # Per-track variables, repeated on every row of the track
    per_track = tracks.reindex(entries['track'].to_numpy())
    for name in tracks.columns:
        data[name] = per_track[name].to_numpy()
    # [tracks, times] variables, and the largest PF (first slot) of the small [tracks, times, nmaxpf] variables
    for name in meta['vars_2d']:
        data[name] = entries[name].to_numpy()
    for name in meta.get('vars_entry3d', {}):
        data[name] = entries[f'{name}__0'].to_numpy()
    # Merge / split areas: the sum over the fragments of every entry (NaN and negative values count as 0, as in the dense route)
    area = np.clip(np.nan_to_num(fragments['ccs_area'].to_numpy(dtype=float), nan=0.0, posinf=0.0, neginf=0.0), 0, None)
    sums = (fragments.assign(area=area).groupby(['track', 'k', 'kind'])['area'].sum().unstack('kind', fill_value=0.0))
    keyed = entries[['track', 'k']].join(sums, on=['track', 'k'])
    for kind, name in ((0, 'merge_ccs_area'), (1, 'split_ccs_area')):
        data[name] = keyed[kind].fillna(0.0).to_numpy() if kind in keyed.columns else np.zeros(len(entries))
    df = pd.DataFrame(data)

    # Fill values -> NaN with the _FillValue attribute of each variable (as ds_to_dataframe); a variable with an attribute becomes float64
    for col in df.columns:
        fv = meta['attrs'].get(col, {}).get('_FillValue')
        if col in ('local_track', 'relative_step') or fv is None:
            continue
        values = df[col].astype(float)
        df[col] = values if np.isnan(fv) else values.where(values != fv)

    # Decode Epoch-time columns to datetime (UTC)
    for col in _TIME_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], unit='s', errors='coerce', utc=True).astype('datetime64[ms, UTC]')

    df['relative_time_h']  = df['relative_step'] * time_res_h
    df['track_duration_h'] = df['track_duration'] * time_res_h
    return df


def add_period(df):
    """
    Add the 'period' column: the calendar year (string) in which each track starts.

    For a yearly tracking run this is the year of the file; for a file that spans several years
    (for example a 19-month run) it is the year of each track.

    Parameters
    ----------
    df : pd.DataFrame — tidy frame with the 'start_basetime' column (datetime, UTC)

    Returns
    -------
    pd.DataFrame — the same frame with 'period' added.

    Raises
    ------
    ValueError : a track has no start time.
    """
    start = df['start_basetime']
    if start.isna().any():
        raise ValueError('start_basetime is missing for some tracks; cannot assign the period')
    df['period'] = start.dt.year.astype(str)
    return df


def conform_columns(df, source):
    """
    Put the columns in the order of UNIFIED_COLUMNS.

    A column of UNIFIED_COLUMNS that the file does not have is a variable that a newer PyFLEXTRKR added (for example
    total_volrain and total_heavyvolrain are not in the SCREAM Cess2 file of January 2026): it is added as NaN (float64)
    and listed in a message, so that every source has the same columns. A column that is not in UNIFIED_COLUMNS is an
    error (the sources could not be concatenated).

    Parameters
    ----------
    df     : pd.DataFrame — tidy frame of one input file
    source : str           — file name, for the messages

    Returns
    -------
    pd.DataFrame with exactly UNIFIED_COLUMNS.

    Raises
    ------
    ValueError : the frame has a column that is not in UNIFIED_COLUMNS.
    """
    extra = [c for c in df.columns if c not in UNIFIED_COLUMNS]
    if extra:
        raise ValueError(f'{source}: columns that are not in UNIFIED_COLUMNS: {extra}')
    missing = [c for c in UNIFIED_COLUMNS if c not in df.columns]
    if missing:
        print(f'  WARNING {os.path.basename(os.path.normpath(source))}: not in the file, filled with NaN: {missing}')
        df = df.assign(**{c: np.nan for c in missing})
    return df[UNIFIED_COLUMNS]


def read_dense_file(fpath, box):
    """
    Read a dense netCDF stats file: filter by region and flatten.

    Parameters
    ----------
    fpath : str  — mcs_tracks_final_*.nc
    box   : dict — lonmin, lonmax, latmin, latmax

    Returns
    -------
    df      : pd.DataFrame — tidy frame of the kept tracks (empty if none), without 'period'
    ntracks : int          — tracks in the file
    n_kept  : int          — tracks inside the box
    """
    ds       = xr.open_dataset(fpath, mask_and_scale=False, decode_times=False)
    ntracks  = ds.sizes['tracks']
    time_res = float(ds.attrs.get('time_resolution_hour', 1.0))
    keep     = filter_tracks_by_region(ds, box['lonmin'], box['lonmax'], box['latmin'], box['latmax'])
    n_kept   = len(keep)
    df       = ds_to_dataframe(ds, keep, time_res_h=time_res) if n_kept > 0 else pd.DataFrame()
    ds.close()
    return df, ntracks, n_kept


def read_rows_file(fpath, box):
    """
    Read a row-table folder: filter by region and flatten.

    The lifetime-mean location of every track is the mean of its ``meanlat`` / ``meanlon`` entries (NaN skipped), the
    same rule as filter_tracks_by_region.

    Parameters
    ----------
    fpath : str  — mcs_tracks_final_*.rows
    box   : dict — lonmin, lonmax, latmin, latmax

    Returns
    -------
    df      : pd.DataFrame — tidy frame of the kept tracks (empty if none), without 'period'
    ntracks : int          — tracks in the folder
    n_kept  : int          — tracks inside the box
    """
    from pyflextrkr.rowstats import RowStats   # only the row route needs PyFLEXTRKR (pyflex26.3)
    rs       = RowStats.open(fpath)
    ntracks  = len(rs.duration)
    time_res = float(rs.meta['global_attrs'].get('time_resolution_hour', 1.0))
    # Lifetime-mean location of every track from the entries table (read only the location columns)
    loc = rs.to_pandas('entries', variables=['meanlat', 'meanlon'])
    mean = loc[['meanlat', 'meanlon']].astype(float).groupby(loc['track']).mean()
    inside = ((mean['meanlat'] >= box['latmin']) & (mean['meanlat'] <= box['latmax']) &
              (mean['meanlon'] >= box['lonmin']) & (mean['meanlon'] <= box['lonmax']))
    keep = mean.index[inside.to_numpy()].to_numpy()
    n_kept = len(keep)
    df = rows_to_dataframe(rs, keep, time_res_h=time_res) if n_kept > 0 else pd.DataFrame()
    return df, ntracks, n_kept


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
        help='Directory containing the mcs_tracks_final_* files (.nc or .rows).',
    )
    parser.add_argument(
        '--pattern', default='*mcs_tracks_final_*.nc',
        help='Glob pattern to match input files: *.nc for dense netCDF files, '
             '*.rows for row-table folders (default: *mcs_tracks_final_*.nc).',
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
        help='First start year of the files to include (inclusive). Default: all files found.',
    )
    parser.add_argument(
        '--end-year', type=int, default=None,
        help='Last start year of the files to include (inclusive). Default: all files found.',
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

    # Filter by the start year of each file
    selected   = []
    years_seen = []
    for f in all_files:
        yr_str = _extract_year(f)
        if yr_str == 'unknown':
            warnings.warn(
                f'Could not parse the start date from {os.path.basename(f)} — skipping.')
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
          f'(start years {min(years_seen)}–{max(years_seen)})')
    print()

    # ── Process each file ────────────────────────────────────────────────────
    dfs          = []
    track_offset = 0
    t_total      = time.time()

    for i, fpath in enumerate(selected):
        t0     = time.time()
        reader = read_rows_file if os.path.normpath(fpath).endswith('.rows') else read_dense_file
        df_yr, ntracks, n_kept = reader(fpath, box)
        if n_kept == 0:
            print(f'  [{i+1:02d}/{len(selected):02d}]  {os.path.basename(fpath)}  '
                  f'no track inside the region (0/{ntracks:,}) — skipped')
            continue

        # Period tag, the fixed column set, and a globally unique local_track
        df_yr = conform_columns(add_period(df_yr), fpath)
        df_yr['local_track'] += track_offset
        track_offset = int(df_yr['local_track'].max()) + 1

        dfs.append(df_yr)
        elapsed = time.time() - t0
        print(f'  [{i+1:02d}/{len(selected):02d}]  {os.path.basename(fpath)}  '
              f'kept={n_kept:,}/{ntracks:,} tracks  '
              f'rows={len(df_yr):,}  ({elapsed:.1f} s)')

    if not dfs:
        raise ValueError('No track inside the region in any file.')

    # ── Concatenate and write ────────────────────────────────────────────────
    print(f'\nCombining {len(dfs)} DataFrames ...')
    combined = pd.concat(dfs, ignore_index=True)
    y0, y1   = int(combined['period'].min()), int(combined['period'].max())
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
