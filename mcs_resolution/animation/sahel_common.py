"""
Shared helpers of the Sahel MCS animation tools: read sahel_sources.yaml, resolve the paths of a source for one year, list the
hourly pixel-level files of a period, and check that the track numbers of the pixel files belong to the track statistics file.

Used by: select_sahel_periods.py and make_mcs_animation_sahel.py.
"""
import os
import re

import numpy as np
import pandas as pd
import yaml

# Folder of this file and the top folder of the scream repository (relative config paths in the YAML are relative to it)
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DEFAULT_SOURCES = os.path.join(HERE, 'sahel_sources.yaml')
# Pixel-level file names: mcstrack_YYYYMMDD_hhmmss.nc
PIXEL_NAME = re.compile(r'^mcstrack_(\d{8}_\d{6})\.nc$')


def load_sources(path=DEFAULT_SOURCES):
    """
    Read the source file of the animations.

    Args:
        path: str (default: sahel_sources.yaml next to this file)

    Returns:
        common: dict
            Shared settings (ndays, months, map_box, core_box, outdir).
        sources: dict
            Source key -> settings of the source, in the order of the file.
    """
    with open(path) as stream:
        data = yaml.safe_load(stream)
    return data['common'], data['sources']


def source_paths(source, year):
    """
    Paths of one source for one year.

    Args:
        source: dict
            One entry of `sources` (config_file, trackstats_file, pixel_path).
        year: int
            Year that replaces {year} in the paths ({next} becomes year + 1).

    Returns:
        paths: dict
            config_file, trackstats_file, pixel_path (absolute; pixel_path ends with '/').
    """
    paths = {key: source[key].format(year=year, next=year + 1) for key in ('config_file', 'trackstats_file', 'pixel_path')}
    # A relative config file is a file of the repository
    if not os.path.isabs(paths['config_file']):
        paths['config_file'] = os.path.join(REPO, paths['config_file'])
    paths['pixel_path'] = paths['pixel_path'].rstrip('/') + '/'
    return paths


def period_of(start, ndays):
    """
    First and last time of a period of whole days.

    Args:
        start: str or date
            First day (YYYY-MM-DD).
        ndays: int
            Number of days.

    Returns:
        t0: pandas.Timestamp
            Start day at 00:00.
        t1: pandas.Timestamp
            Last day at 23:59 (files stamped hh:30, such as the OBS ones, are inside the period up to 23:30).
    """
    t0 = pd.Timestamp(str(start)).normalize()
    t1 = t0 + pd.Timedelta(days=ndays) - pd.Timedelta(minutes=1)
    return t0, t1


def index_pixel_files(pixel_path):
    """
    Times of all pixel-level files of a folder.

    Args:
        pixel_path: str
            Folder with mcstrack_*.nc files.

    Returns:
        files: pandas.Series
            File path of every pixel file, indexed by its time (sorted). Empty if the folder has none.
    """
    times, names = [], []
    # Loop over the folder entries and keep the files named like pixel-level files
    with os.scandir(pixel_path) as entries:
        for entry in entries:
            match = PIXEL_NAME.match(entry.name)
            if match:
                times.append(match.group(1))
                names.append(entry.path)
    index = pd.to_datetime(times, format='%Y%m%d_%H%M%S')
    return pd.Series(names, index=index, dtype=object).sort_index()


def files_of_period(index, t0, t1):
    """
    Pixel files of a period and the hours that have no file.

    Args:
        index: pandas.Series
            Output of index_pixel_files.
        t0, t1: pandas.Timestamp
            First and last time of the period (period_of).

    Returns:
        files: pandas.Series
            The files within [t0, t1].
        missing: pandas.DatetimeIndex
            Hours of the period (start of the hour) without a file.
    """
    files = index[(index.index >= t0) & (index.index <= t1)]
    hours = pd.date_range(t0, t1, freq='h')
    missing = hours.difference(files.index.floor('h'))
    return files, missing


def check_pairing(files, trackstats_file, nsample=4, min_fraction=0.9, max_offset=1.0):
    """
    Check that the track numbers of the pixel files belong to the track statistics file.

    In a pixel file the mask `cloudtracknumber` has the value N over the MCS of row N-1 of the statistics file. For a few frames,
    every mask must have a time step in its statistics row at the time of the frame, and the center of the mask must be close to
    the center (meanlat, meanlon) of that time step. A statistics file of another run fails this test.

    Args:
        files: pandas.Series
            Pixel files of the period (files_of_period).
        trackstats_file: str
            Yearly final MCS statistics (dense netCDF file or row folder).
        nsample: int (default: 4)
            Number of frames, spread over the period.
        min_fraction: float (default: 0.9)
            Smallest accepted fraction of masks with a statistics time step at the frame time.
        max_offset: float (default: 1.0)
            Largest accepted median distance between mask center and statistics center [degrees].

    Returns:
        result: dict
            ok (bool), masks (int), matched (int), fraction (float), median_offset (float).
    """
    import netCDF4
    from pyflextrkr.rowstats import load_trackstats

    # Track times (seconds since 1970) and centers of all tracks of the statistics file
    stats = load_trackstats(trackstats_file, variables=['base_time', 'meanlat', 'meanlon'], fragments=False)
    base_time = stats['base_time'].values
    if np.issubdtype(base_time.dtype, np.datetime64):
        base_time = np.where(np.isnat(base_time), np.nan, base_time.astype('datetime64[s]').astype('float64'))
    mean_lat, mean_lon = stats['meanlat'].values, stats['meanlon'].values

    nmasks, nmatched, offsets = 0, 0, []
    # Loop over frames spread over the period (the first and the last frame of a period are not special)
    for position in np.linspace(0, len(files) - 1, nsample + 2).astype(int)[1:-1]:
        with netCDF4.Dataset(files.iloc[position]) as ds:
            mask = np.ma.filled(ds['cloudtracknumber'][0], 0)
            time = float(ds['base_time'][0])
            lat, lon = np.asarray(ds['lat'][:]), np.asarray(ds['lon'][:])
        # Pixels of all masks of the frame, grouped by track number
        jj, ii = np.nonzero(mask > 0)
        pixels = pd.DataFrame({'number': mask[jj, ii].astype(int), 'lat': lat[jj], 'lon': lon[ii]})
        # Loop over the masks: find the statistics time step at the frame time and measure the center distance
        for number, group in pixels.groupby('number'):
            nmasks += 1
            if number - 1 >= base_time.shape[0]:
                continue
            step = np.flatnonzero(np.abs(base_time[number - 1] - time) < 60)
            if step.size == 0:
                continue
            nmatched += 1
            # A mask that crosses the date line has no simple mean longitude: it counts for the time match only
            if np.ptp(group['lon'].values) <= 180:
                offsets.append(np.hypot(group['lat'].mean() - mean_lat[number - 1, step[0]],
                                        group['lon'].mean() - mean_lon[number - 1, step[0]]))
    fraction = nmatched / nmasks if nmasks else 0.0
    median_offset = float(np.median(offsets)) if offsets else float('nan')
    ok = bool(fraction >= min_fraction and median_offset <= max_offset)
    return {'ok': ok, 'masks': nmasks, 'matched': nmatched, 'fraction': fraction, 'median_offset': median_offset}
