#!/usr/bin/env python
"""
combine_subset_tracks.py

Combine monthly cell tracking statistics files from a single data source
(SCREAM or MRMS) and produce a compact subsetted NetCDF retaining only tracks
that satisfy all of the following criteria:

  1. Initiation time (start_basetime) falls within [START, END].
  2. Initiation location falls within the chosen US-state region
     (geopandas spatial join against Census TIGER state boundaries).
  3. Track is not truncated at a file boundary (i.e. does not start at the
     first timestamp or end at the last timestamp of a monthly file).

Output filename is auto-derived as::

    subset_tracks_<YYYYMMDD>_<YYYYMMDD>_<REGION>.nc

and written into the same directory as the input data.

Usage
-----
Required arguments:
    --source {scream,mrms}  Input data source.
    --region REGION         Region key (SE | NE | SGP | NGP) or 'none' to skip
                            the location filter.

Optional arguments:
    --months M [M ...]      Month numbers to scan for files (default: 4 5 6 7 8).
    --start DATETIME        Start of initiation time window, ISO 8601
                            (default: 2020-04-01T00:00).
    --end DATETIME          End of initiation time window, inclusive, ISO 8601
                            (default: 2020-08-31T23:59).

Examples
--------
# SE region, default time window
python combine_subset_tracks.py --source scream --region SE

# NGP region, custom months and time window
python combine_subset_tracks.py --source mrms --region NGP --months 6 7 8 \\
    --start 2021-06-01T00:00 --end 2021-08-31T23:59

# No location filter
python combine_subset_tracks.py --source scream --region none

# Show full help
python combine_subset_tracks.py --help
"""

import argparse
import os
import glob
import numpy as np
import pandas as pd
import xarray as xr
import geopandas as gpd
from shapely.geometry import Point
import warnings
warnings.filterwarnings('ignore')


# ============================================================
# CONSTANTS  (edit to add new data sources or regions)
# ============================================================

# File paths for each data source
DIR_SCREAM = '/pscratch/sd/w/wcmca1/SCREAMv1-cess2/cell_conus/stats/'
DIR_MRMS   = '/pscratch/sd/i/iclas2/MRMS/cell_conus/stats/'

# --- Initiation location: regions defined as lists of US state abbreviations ---
REGIONS = {
    'SE':  ["LA", "MS", "AL", "GA", "SC", "NC", "TN"],
    'NE':  ["KY", "OH", "MI", "WV", "VA", "PA", "MD", "DE", "NJ", "NY", "CT", "VT", "NH", "MA", "RI", "ME"],
    'SGP': ["TX", "OK", "AR", "NM"],
    'NGP': ["KS", "NE", "SD", "ND", "MN", "IA", "MO", "WI", "IL", "IN"],
}

# ============================================================
# FUNCTIONS
# ============================================================

# Module-level cache so the shapefile is downloaded only once per run
_states_gdf_cache = None


def load_us_states_gdf():
    """
    Load US state boundaries from the Census TIGER shapefile (20 m resolution).
    Caches the result in a module-level variable so the file is only fetched
    once per Python process.

    Returns
    -------
    geopandas.GeoDataFrame or None
        State boundaries with an 'STUSPS' column containing two-letter state
        abbreviations.  Returns *None* if the download or load fails.
    """
    global _states_gdf_cache
    if _states_gdf_cache is not None:
        return _states_gdf_cache

    url = "https://www2.census.gov/geo/tiger/GENZ2021/shp/cb_2021_us_state_20m.zip"
    try:
        _states_gdf_cache = gpd.read_file(url)
        print(f"  Loaded US state boundaries: {len(_states_gdf_cache)} states/territories")
    except Exception as exc:
        print(f"  Warning: could not load state boundaries ({exc}). "
              "Location filter will be skipped.")
        _states_gdf_cache = None
    return _states_gdf_cache


def open_and_subset_file(filepath, start_datetime, end_datetime, regions):
    """
    Open a single track-statistics file lazily and immediately subset
    it by initiation time and location.

    Opening and subsetting one file at a time keeps peak memory very low: only
    the small initiation-slice arrays (``start_basetime``, ``meanlon[:,0]``,
    ``meanlat[:,0]``) are pulled into memory to build the boolean mask; the
    rest of the data stays on disk until the final ``to_netcdf`` call.

    Parameters
    ----------
    filepath : str
        Path to a single track-statistics netCDF file.
    start_datetime, end_datetime : str
        Initiation time window, e.g. ``'2025-06-01T00:00'``.
    regions : dict or None
        Mapping of region label → list of US state abbreviations used by
        :func:`subset_tracks`.  Pass *None* to skip the location filter.

    Returns
    -------
    ds_sub : xarray.Dataset or None
        Subset of the file's tracks that satisfy all criteria, with the
        ``tracks`` coordinate reset to ``0..N-1`` and the original track
        numbers stored in ``original_tracks``.  Returns *None* when no tracks
        pass the filters.
    """
    # ds = xr.open_dataset(filepath, chunks={})
    ds = xr.open_dataset(filepath)

    # Preserve original track numbers before resetting the coordinate
    ds['original_tracks'] = ds['tracks'].astype(int)
    ds['original_tracks'].attrs['long_name'] = (
        'Original track number from individual monthly file'
    )
    ds['original_tracks'].attrs['description'] = (
        'Track numbers before renumbering for the combined dataset'
    )
    # ds = ds.assign_coords(tracks=np.arange(ds.sizes['tracks']))

    ds_sub = subset_tracks(ds, start_datetime, end_datetime, regions)

    if ds_sub.sizes['tracks'] == 0:
        ds.close()
        return None

    # Load the small subset into memory now so the file handle can be closed.
    # This makes the final xr.concat operate on plain numpy arrays instead of
    # lazy graph nodes, which is dramatically faster.
    ds_sub = ds_sub.load()
    ds.close()
    return ds_sub


def subset_tracks(ds, start_datetime, end_datetime, regions):
    """
    Subset a combined cell track dataset by initiation time and location.

    Initiation is defined as the first time step of each track,
    i.e. ``start_basetime``.  A track is retained when ALL of the
    following conditions hold:

    * initiation time is within [start_datetime, end_datetime] (inclusive)
    * initiation location falls within one of the states defined in *regions*
      (geopandas spatial join against Census TIGER state boundaries)
    * track does not start at the file's first timestamp (not truncated at
      the beginning of the month)
    * track does not end at the file's last timestamp (not truncated at the
      end of the month)

    Parameters
    ----------
    ds : xarray.Dataset
        Track dataset opened by :func:`open_and_subset_file`.
    start_datetime : str
        Start of the time window, e.g. ``'2025-06-01T00:00'``.
    end_datetime : str
        End of the time window (inclusive), e.g. ``'2025-06-30T23:59'``.
    regions : dict or None
        Mapping of region label → list of US state abbreviations, e.g.
        ``{'SE': ['LA', 'MS', ...], ...}``.  Pass *None* to skip the
        location filter.

    Returns
    -------
    ds_sub : xarray.Dataset
        Subset of *ds* containing only tracks that satisfy all criteria.
    """
    # Convert user-supplied strings to pandas Timestamps
    t_start = pd.Timestamp(start_datetime)
    t_end   = pd.Timestamp(end_datetime)

    # Extract initiation times and locations
    start_time_vals = ds['start_basetime'].values
    end_time_vals   = ds['end_basetime'].values
    init_lon = ds['meanlon'].isel(times=0).values   # shape (tracks,), 0-360 °
    init_lat = ds['meanlat'].isel(times=0).values   # shape (tracks,)

    # Convert to pandas DatetimeIndex – handle both datetime64 and Unix seconds
    if np.issubdtype(start_time_vals.dtype, np.datetime64):
        init_times = pd.to_datetime(start_time_vals)
    else:
        init_times = pd.to_datetime(start_time_vals, unit='s')

    # Strip timezone info so comparisons work regardless of tz awareness
    if init_times.tz is not None:
        init_times = init_times.tz_localize(None)

    # ------------------------------------------------------------------
    # Time-range mask
    # ------------------------------------------------------------------
    time_mask = (init_times >= t_start) & (init_times <= t_end)

    # ------------------------------------------------------------------
    # Boundary mask: remove tracks truncated at file start / end
    # ------------------------------------------------------------------
    first_time_of_month = np.nanmin(start_time_vals)
    last_time_of_month  = np.nanmax(end_time_vals)
    boundary_mask = ((start_time_vals != first_time_of_month) &
                     (end_time_vals   != last_time_of_month))

    # ------------------------------------------------------------------
    # Location mask: geopandas spatial join against state boundaries
    # ------------------------------------------------------------------
    if regions is not None:
        states_gdf = load_us_states_gdf()
    else:
        states_gdf = None

    if regions is not None and states_gdf is not None:
        # Normalise longitude to [-180, 180] for geopandas.
        # Tracking files may store longitude as 0-360 or already as -180/180;
        # the modular formula handles both conventions without data corruption:
        #   e.g.  270 → -90  (0-360 input)
        #   e.g.  -90 → -90  (-180/180 input, unchanged)
        lon_180 = ((init_lon + 180.0) % 360.0) - 180.0

        # Build a GeoDataFrame of track initiation points
        points_gdf = gpd.GeoDataFrame(
            {'track_idx': np.arange(len(init_lon))},
            geometry=gpd.points_from_xy(lon_180, init_lat),
            crs='EPSG:4326',
        )

        # Union of all states across all regions
        all_states = [s for state_list in regions.values() for s in state_list]
        states_subset = states_gdf[states_gdf['STUSPS'].isin(all_states)]
        states_union  = states_subset.unary_union

        loc_mask = points_gdf.geometry.within(states_union).values
    else:
        # No location filter
        loc_mask = np.ones(ds.sizes['tracks'], dtype=bool)

    # ------------------------------------------------------------------
    # Combine and apply
    # ------------------------------------------------------------------
    combined_mask = time_mask & boundary_mask & loc_mask
    track_indices = np.where(combined_mask)[0]

    print(f"  Total tracks before subsetting      : {ds.sizes['tracks']}")
    print(f"  Tracks passing time range filter    : {int(np.sum(time_mask))}")
    print(f"  Tracks passing boundary filter      : {int(np.sum(boundary_mask))}")
    print(f"  Tracks passing location filter      : {int(np.sum(loc_mask))}")
    print(f"  Tracks passing all filters          : {len(track_indices)}")

    return ds.isel(tracks=track_indices)


# ============================================================
# MAIN
# ============================================================

if __name__ == '__main__':

    # ------------------------------------------------------------------
    # 0. Parse command-line arguments
    # ------------------------------------------------------------------
    parser = argparse.ArgumentParser(
        description='Combine and subset monthly cell tracking statistics files.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        '--source',
        required=True,
        choices=['scream', 'mrms'],
        dest='data_source',
        metavar='SOURCE',
        help="Input data source: 'scream' or 'mrms'.",
    )
    parser.add_argument(
        '--region',
        required=True,
        choices=list(REGIONS.keys()) + ['none'],
        metavar='REGION',
        help=(
            "Region key from the REGIONS dict (e.g. 'SE', 'NGP'), or "
            "'none' to skip the location filter entirely."
        ),
    )
    parser.add_argument(
        '--months',
        nargs='+',
        type=int,
        default=[4, 5, 6, 7, 8],
        metavar='M',
        help='Month numbers to include when scanning for files (1=Jan … 12=Dec).',
    )
    parser.add_argument(
        '--start',
        default='2020-04-01T00:00',
        dest='start_datetime',
        metavar='DATETIME',
        help='Start of the initiation time window (ISO 8601 format).',
    )
    parser.add_argument(
        '--end',
        default='2020-08-31T23:59',
        dest='end_datetime',
        metavar='DATETIME',
        help='End of the initiation time window, inclusive (ISO 8601 format).',
    )
    args = parser.parse_args()

    DATA_SOURCE    = args.data_source
    REGION         = None if args.region.lower() == 'none' else args.region
    MONTHS         = args.months
    START_DATETIME = args.start_datetime
    END_DATETIME   = args.end_datetime

    # Derive output filename from parsed arguments
    t_start         = pd.Timestamp(START_DATETIME).strftime('%Y%m%d')
    t_end           = pd.Timestamp(END_DATETIME).strftime('%Y%m%d')
    _region_tag     = REGION if REGION is not None else 'all'
    OUTPUT_FILENAME = f'subset_tracks_{t_start}_{t_end}_{_region_tag}.nc'

    # ------------------------------------------------------------------
    # 1. Select directory and label based on DATA_SOURCE
    # ------------------------------------------------------------------
    source = DATA_SOURCE.strip().lower()
    if source == 'scream':
        data_dir     = DIR_SCREAM
        source_label = 'SCREAM'
    elif source == 'mrms':
        data_dir     = DIR_MRMS
        source_label = 'MRMS'
    else:
        raise ValueError(
            f"Unknown DATA_SOURCE '{DATA_SOURCE}'. Choose 'scream' or 'mrms'."
        )

    # Output path lives in the same directory as the input data
    OUTPUT_FILE = os.path.join(data_dir, OUTPUT_FILENAME)

    # Resolve selected region to a single-entry dict (or None)
    if REGION is not None:
        if REGION not in REGIONS:
            raise ValueError(
                f"REGION '{REGION}' not found in REGIONS. "
                f"Valid keys: {list(REGIONS.keys())}"
            )
        regions_filter = {REGION: REGIONS[REGION]}
    else:
        regions_filter = None

    # ------------------------------------------------------------------
    # 2. Collect files
    # ------------------------------------------------------------------
    files = []
    for month in MONTHS:
        pattern = os.path.join(data_dir, f'trackstats_20??{month:02d}*.nc')
        files += sorted(glob.glob(pattern))

    print(f"Found {len(files)} {source_label} file(s).")
    if len(files) == 0:
        raise FileNotFoundError(
            f"No files found in '{data_dir}'. "
            "Check DATA_SOURCE, the directory path, and MONTHS."
        )

    # ------------------------------------------------------------------
    # 3. Open each file, subset immediately, collect results
    # ------------------------------------------------------------------
    print(f"\nOpening and subsetting {source_label} files …")
    print(f"  Time window : {START_DATETIME}  →  {END_DATETIME}")
    if regions_filter:
        selected_states = REGIONS[REGION]
        print(f"  Region      : {REGION}")
        print(f"  States      : {selected_states}")
    else:
        print(f"  Location filter: disabled")
    print()

    subsetted = []
    for f in files:
        print(f"  Processing: {os.path.basename(f)}")
        ds_sub = open_and_subset_file(
            f,
            start_datetime=START_DATETIME,
            end_datetime=END_DATETIME,
            regions=regions_filter,
        )
        if ds_sub is not None:
            subsetted.append(ds_sub)

    # ------------------------------------------------------------------
    # 4. Combine the already-subsetted datasets
    # ------------------------------------------------------------------
    if len(subsetted) == 0:
        print("\nNo tracks passed the filters across all files. Exiting.")
        raise SystemExit(0)

    print(f"\nCombining {len(subsetted)} non-empty subsetted dataset(s) …")
    ds_subset = xr.concat(
        subsetted,
        dim='tracks',
        compat='override',
        coords='minimal',
        data_vars='all',
    )
    # Renumber tracks globally from 0
    ds_subset = ds_subset.assign_coords(tracks=np.arange(ds_subset.sizes['tracks']))

    # Record filtering criteria as global attributes
    ds_subset.attrs['subset_start_datetime'] = START_DATETIME
    ds_subset.attrs['subset_end_datetime']   = END_DATETIME
    if regions_filter is not None:
        ds_subset.attrs['subset_region']        = REGION
        ds_subset.attrs['subset_region_states'] = ', '.join(REGIONS[REGION])
    else:
        ds_subset.attrs['subset_region']        = 'all'
        ds_subset.attrs['subset_region_states'] = 'no location filter applied'

    print(f"\nSubset dataset: {ds_subset.sizes['tracks']} track(s) retained.")
    print(ds_subset)

    # ------------------------------------------------------------------
    # 5. Optionally save to disk
    # ------------------------------------------------------------------
    if OUTPUT_FILE is not None:
        print(f"\nSaving subset to: {OUTPUT_FILE}")

        # Build per-variable encoding with compression and dimension-aware chunking.
        #
        # Chunk strategy (optimised for this dataset's primary use cases):
        #   - Lifetime statistics (e.g. max over times): requires reading all
        #     300 time steps for each track → set times chunk = full times dim.
        #   - Monthly grouping (~20 k tracks/month): tracks chunk of 1000 gives
        #     ~20 sequential chunks per month, keeping I/O efficient.
        #   - At float32 each 2-D chunk is 1000 × 300 × 4 B ≈ 1.2 MB — a good
        #     size for both NetCDF4 and Zarr back-ends.
        ntimes = ds_subset.sizes.get('times', 300)
        CHUNK_TRACKS = 1000

        comp = {'zlib': True, 'complevel': 1}
        encoding = {}
        for var in ds_subset.data_vars:
            dims = ds_subset[var].dims
            if dims == ('tracks', 'times'):
                chunksizes = (CHUNK_TRACKS, ntimes)
            elif dims == ('tracks',):
                chunksizes = (CHUNK_TRACKS,)
            else:
                chunksizes = None   # scalar or unexpected shape – let library decide

            enc = dict(comp)
            if chunksizes is not None:
                enc['chunksizes'] = chunksizes
            encoding[var] = enc

        ds_subset.to_netcdf(OUTPUT_FILE, encoding=encoding)
        print("Done.")
