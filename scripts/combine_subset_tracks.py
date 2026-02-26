#!/usr/bin/env python
"""
combine_subset_tracks.py

Combine monthly cell tracking statistics files from a single data source
(SCREAM or MRMS) and subset the result by:
- initiation time and initiation location
- removing tracks that are truncated at the file boundaries (i.e. start at the first time step or end at the last time step of a file)

Usage:
    python combine_subset_tracks.py
    (edit the USER-CONFIGURABLE SETTINGS section before running)
"""

import os
import glob
import numpy as np
import pandas as pd
import xarray as xr
import warnings
warnings.filterwarnings('ignore')


# ============================================================
# USER-CONFIGURABLE SETTINGS
# ============================================================

# Choose data source: 'scream' or 'mrms'
DATA_SOURCE = 'scream'

# File paths for each data source
DIR_SCREAM = '/pscratch/sd/w/wcmca1/SCREAMv1-cess2/cell_conus/stats/'
DIR_MRMS   = '/pscratch/sd/i/iclas2/MRMS/cell_conus/stats/'

# Months to include when collecting files (1 = January, ..., 12 = December)
MONTHS = [4, 5, 6, 7, 8]

# --- Initiation time window ---
# Tracks whose first time step (initiation) falls within this window are kept.
START_DATETIME = '2020-04-01T00:00'
END_DATETIME   = '2020-08-31T23:59'

# --- Initiation location bounding box ---
# Longitudes must be in the 0-360 convention (same as the 'meanlon' variable).
#   90°W = 270°,  82°W = 278°  →  Southeast US
LON_RANGE = [270.0, 278.0]   # [lon_min, lon_max] in 0-360 degrees
LAT_RANGE = [31.0,  36.0]    # [lat_min, lat_max] in degrees North

# Output file name (written into the same directory as the input data)
t_start = pd.Timestamp(START_DATETIME).strftime('%Y%m%d')
t_end   = pd.Timestamp(END_DATETIME).strftime('%Y%m%d')

OUTPUT_FILENAME = f'subset_tracks_{t_start}_{t_end}.nc'

# ============================================================
# FUNCTIONS
# ============================================================

def open_and_subset_file(filepath, start_datetime, end_datetime,
                          lon_range, lat_range):
    """
    Open a single track-statistics file lazily (dask) and immediately subset
    it by initiation time and location.

    Opening and subsetting one file at a time keeps peak memory very low: only
    the small initiation-slice arrays (``base_time[:,0]``, ``meanlon[:,0]``,
    ``meanlat[:,0]``) are pulled into memory to build the boolean mask; the
    rest of the data stays on disk until the final ``to_netcdf`` call.

    Parameters
    ----------
    filepath : str
        Path to a single track-statistics netCDF file.
    start_datetime, end_datetime : str
        Initiation time window, e.g. ``'2025-06-01T00:00'``.
    lon_range : list of float, length 2
        ``[lon_min, lon_max]`` in 0-360 ° convention.
    lat_range : list of float, length 2
        ``[lat_min, lat_max]`` in degrees North.

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

    ds_sub = subset_tracks(ds, start_datetime, end_datetime,
                           lon_range, lat_range)

    if ds_sub.sizes['tracks'] == 0:
        ds.close()
        return None

    # Load the small subset into memory now so the file handle can be closed.
    # This makes the final xr.concat operate on plain numpy arrays instead of
    # lazy graph nodes, which is dramatically faster.
    ds_sub = ds_sub.load()
    ds.close()
    return ds_sub


def subset_tracks(ds, start_datetime, end_datetime, lon_range, lat_range):
    """
    Subset a combined cell track dataset by initiation time and location.

    Initiation is defined as the first time step of each track,
    i.e. ``ds.isel(times=0)``.  A track is retained when ALL of the
    following conditions hold:

    * initiation time is within [start_datetime, end_datetime] (inclusive)
    * initiation ``meanlon`` is within [lon_range[0], lon_range[1]]
    * initiation ``meanlat`` is within [lat_range[0], lat_range[1]]

    Parameters
    ----------
    ds : xarray.Dataset
        Combined track dataset as returned by :func:`combine_tracks_files`.
        Expected variables:

        * ``base_time``  – (tracks, times) timestamps; either numpy
          datetime64 (CF-decoded by xarray) or Unix seconds since epoch.
        * ``meanlon``    – (tracks, times) cell-centre longitude, 0–360 °.
        * ``meanlat``    – (tracks, times) cell-centre latitude, –90 to 90 °.

    start_datetime : str
        Start of the time window, e.g. ``'2025-06-01T00:00'``.
        Parsed by :class:`pandas.Timestamp`.
    end_datetime : str
        End of the time window (inclusive), e.g. ``'2025-06-30T23:59'``.
        Parsed by :class:`pandas.Timestamp`.
    lon_range : list of float, length 2
        ``[lon_min, lon_max]`` in 0-360 ° convention.
    lat_range : list of float, length 2
        ``[lat_min, lat_max]`` in degrees North.

    Returns
    -------
    ds_sub : xarray.Dataset
        Subset of *ds* containing only tracks that satisfy all criteria.
    """
    # Convert user-supplied strings to pandas Timestamps
    t_start = pd.Timestamp(start_datetime)
    t_end   = pd.Timestamp(end_datetime)
    
    # Extract initiation (times=0) times and locations for all tracks
    start_time_vals = ds['start_basetime'].values
    end_time_vals  = ds['end_basetime'].values
    init_lon = ds['meanlon'].isel(times=0).values   # shape (tracks,)
    init_lat = ds['meanlat'].isel(times=0).values   # shape (tracks,)

    # Convert to pandas DatetimeIndex – handle both datetime64 and numeric
    # (seconds since epoch) representations
    if np.issubdtype(start_time_vals.dtype, np.datetime64):
        init_times = pd.to_datetime(start_time_vals)
    else:
        init_times = pd.to_datetime(start_time_vals, unit='s')
    
    # Strip timezone info so comparisons work regardless of tz awareness
    if init_times.tz is not None:
        init_times = init_times.tz_localize(None)

    # Remove tracks that are truncated at the file boundaries:
    #   - starts at the very first timestamp in the file (truncated at month start)
    #   - ends   at the very last  timestamp in the file (truncated at month end)
    first_time_of_month = np.nanmin(start_time_vals)
    last_time_of_month  = np.nanmax(end_time_vals)
    boundary_mask = (start_time_vals != first_time_of_month) & \
                    (end_time_vals  != last_time_of_month)

    # Build boolean masks for each criterion
    time_mask = (init_times >= t_start) & (init_times <= t_end)
    lon_mask  = (init_lon  >= lon_range[0]) & (init_lon <= lon_range[1])
    lat_mask  = (init_lat  >= lat_range[0]) & (init_lat <= lat_range[1])
    loc_mask  = lon_mask & lat_mask

    combined_mask = time_mask & loc_mask & boundary_mask
    track_indices = np.where(combined_mask)[0]

    # Report filter statistics
    print(f"  Total tracks before subsetting : {ds.sizes['tracks']}")
    print(f"  Tracks passing time range filter     : {np.sum(time_mask)}")
    print(f"  Tracks passing location filter : {np.sum(loc_mask)}")
    print(f"  Tracks passing time boundary filter : {np.sum(boundary_mask)}")
    print(f"  Tracks passing all filters     : {len(track_indices)}")

    ds_sub = ds.isel(tracks=track_indices)
    return ds_sub


# ============================================================
# MAIN
# ============================================================

if __name__ == '__main__':

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
    print(f"  Lon range   : {LON_RANGE}  (0-360 °)")
    print(f"  Lat range   : {LAT_RANGE}  (° N)\n")

    subsetted = []
    for f in files:
        print(f"  Processing: {os.path.basename(f)}")
        ds_sub = open_and_subset_file(
            f,
            start_datetime=START_DATETIME,
            end_datetime=END_DATETIME,
            lon_range=LON_RANGE,
            lat_range=LAT_RANGE,
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
