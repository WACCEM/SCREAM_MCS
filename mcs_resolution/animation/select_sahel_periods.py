#!/usr/bin/env python
"""
Rank 7-day periods of every source by the large, long-lived MCSs over the Sahel, to choose the period of each animation.

The same rules for all sources:
  1. Qualifying MCS: track lifetime >= --min-duration hours and largest cold cloud area of its life >= --min-area km2.
  2. Only the time steps of qualifying MCSs whose center is in the core box (sahel_sources.yaml), May to September.
  3. Score of a window of `ndays` days = area-time integral: the sum of the cold cloud area (km2) of those hourly time steps.
     Windows start at 00 UTC of any day and lie within the months of one year.
  4. The --top best windows that do not overlap are listed. For each, the pixel-level files are checked: hours without a file
     and the fraction of missing Tb in the map box (every 6th frame). `usable` = no hour missing and little missing Tb.

The ranking reads the combined global Parquet of each source (the files the analysis notebooks are made from). The models are
free-running, so every source gets its own dates. Writes one CSV per source and all_sources.csv; the chosen start days are
written by hand into sahel_sources.yaml.

Usage (compute node):
    python select_sahel_periods.py                      # all sources
    python select_sahel_periods.py --sources obs e3sm25 --top 8
"""
import argparse
import os

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

import sahel_common as common_tools

# Columns of the combined Parquet that the ranking needs
COLUMNS = ['local_track', 'base_time', 'meanlat', 'meanlon', 'ccs_area', 'track_duration_h']


def parse_args(argv=None):
    """
    Command line.

    Args:
        argv: list of str (default: None = sys.argv[1:])

    Returns:
        args: argparse.Namespace
    """
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--config', default=common_tools.DEFAULT_SOURCES, help='source file (default: %(default)s)')
    p.add_argument('--sources', nargs='+', default=None, help='source keys (default: all)')
    p.add_argument('--min-duration', type=float, default=12.0, help='shortest lifetime of a qualifying MCS [h] (default: %(default)s)')
    p.add_argument('--min-area', type=float, default=1.0e5,
                   help='smallest lifetime-maximum cold cloud area of a qualifying MCS [km2] (default: %(default)s)')
    p.add_argument('--top', type=int, default=5, help='number of non-overlapping windows listed per source (default: %(default)s)')
    p.add_argument('--max-tb-missing', type=float, default=2.0,
                   help='largest mean fraction of missing Tb in the map box of a usable window [%%] (default: %(default)s)')
    p.add_argument('--outdir', default=None, help='folder of the CSV files (default: <outdir of the source file>/period_selection)')
    p.add_argument('--no-file-check', action='store_true', help='rank only, do not read the pixel-level files')
    return p.parse_args(argv)


def qualifying_steps(table, core_box, months, min_duration, min_area):
    """
    Hourly time steps of qualifying MCSs inside the core box.

    Args:
        table: pandas.DataFrame
            Columns COLUMNS; one row per track and time step (all of the tracks' time steps).
        core_box: dict
            lon_min, lon_max, lat_min, lat_max.
        months: list of int
            Months that are kept.
        min_duration: float
            Shortest lifetime [h].
        min_area: float
            Smallest lifetime-maximum cold cloud area [km2].

    Returns:
        steps: pandas.DataFrame
            Rows of `table` of qualifying tracks inside the box and the months, with `time` (no time zone) and `day`.
    """
    # Tracks that pass the lifetime and size rules (size: the largest area of the whole life, not only inside the box)
    max_area = table.groupby('local_track')['ccs_area'].transform('max')
    keep = (table['track_duration_h'] >= min_duration) & (max_area >= min_area)
    # Time steps with the center inside the core box
    keep &= table['meanlon'].between(core_box['lon_min'], core_box['lon_max'])
    keep &= table['meanlat'].between(core_box['lat_min'], core_box['lat_max'])
    steps = table[keep].copy()
    # Times without time zone, then the month rule
    time = pd.to_datetime(steps['base_time'])
    steps['time'] = time.dt.tz_localize(None) if time.dt.tz is not None else time
    steps = steps[steps['time'].dt.month.isin(months)]
    steps['day'] = steps['time'].dt.normalize()
    return steps


def window_scores(steps, ndays, months):
    """
    Area-time integral of every window of `ndays` days that lies within the months of one year.

    Args:
        steps: pandas.DataFrame
            Output of qualifying_steps.
        ndays: int
            Length of a window [days].
        months: list of int
            Consecutive months, e.g. [5, 6, 7, 8, 9].

    Returns:
        scores: pandas.Series
            Score [km2 h] of every window, indexed by its first day, best first.
    """
    daily = steps.groupby('day')['ccs_area'].sum()
    scores = []
    # Loop over the years: a continuous daily series over the season (days without an MCS count as zero)
    for year in sorted(daily.index.year.unique()):
        first = pd.Timestamp(year, min(months), 1)
        last = pd.Timestamp(year, max(months), 1) + pd.offsets.MonthEnd(0)
        series = daily.reindex(pd.date_range(first, last, freq='D'), fill_value=0.0)
        # Sum over the window that STARTS on each day; windows that run past the season are dropped
        total = series.rolling(ndays).sum().shift(-(ndays - 1)).dropna()
        scores.append(total)
    if not scores:
        return pd.Series(dtype=float)
    return pd.concat(scores).sort_values(ascending=False, kind='stable')


def best_windows(scores, ndays, top):
    """
    The best windows that do not overlap each other.

    Args:
        scores: pandas.Series
            Output of window_scores (best first).
        ndays: int
            Length of a window [days].
        top: int
            Number of windows.

    Returns:
        starts: list of pandas.Timestamp
            First days of the chosen windows, best first.
    """
    starts = []
    # Walk down the ranking and keep a window if it shares no day with a window already kept
    for start in scores.index:
        if all(abs((start - other).days) >= ndays for other in starts):
            starts.append(start)
        if len(starts) == top:
            break
    return starts


def window_metrics(steps, start, ndays):
    """
    Numbers that describe the MCSs of one window (core box only).

    Args:
        steps: pandas.DataFrame
            Output of qualifying_steps.
        start: pandas.Timestamp
            First day of the window.
        ndays: int
            Length [days].

    Returns:
        metrics: dict
            ati_1e6km2h, n_mcs, n_inbox_ge18h, longest_inbox_h, largest_area_1e5km2, n_westward, n_eastward.
    """
    t0, t1 = common_tools.period_of(start, ndays)
    window = steps[(steps['time'] >= t0) & (steps['time'] <= t1)].sort_values(['local_track', 'time'])
    per_track = window.groupby('local_track').agg(hours=('time', 'size'), lon_first=('meanlon', 'first'), lon_last=('meanlon', 'last'),
                                                  area=('ccs_area', 'max'))
    # Zonal displacement of each MCS between its first and last hour in the box: 5 degrees or more counts as a direction
    shift = per_track['lon_last'] - per_track['lon_first']
    return {'ati_1e6km2h': window['ccs_area'].sum() / 1e6,
            'n_mcs': len(per_track),
            'n_inbox_ge18h': int((per_track['hours'] >= 18).sum()),
            'longest_inbox_h': int(per_track['hours'].max()) if len(per_track) else 0,
            'largest_area_1e5km2': per_track['area'].max() / 1e5 if len(per_track) else np.nan,
            'n_westward': int((shift <= -5).sum()),
            'n_eastward': int((shift >= 5).sum())}


def missing_tb_percent(files, map_box, every=6):
    """
    Mean fraction of missing Tb in the map box, from a sample of the frames.

    Args:
        files: pandas.Series
            Pixel files of the window.
        map_box: dict
            lon_min, lon_max, lat_min, lat_max.
        every: int (default: 6)
            Read every n-th frame.

    Returns:
        percent: float
            Mean percentage of missing (NaN) Tb pixels; the largest value of a sampled frame.
        largest: float
    """
    import netCDF4

    values = []
    window = None
    # Loop over the sampled frames: read only the Tb pixels of the map box
    for path in files.iloc[::every]:
        with netCDF4.Dataset(path) as ds:
            if window is None:
                lat, lon = np.asarray(ds['lat'][:]), np.asarray(ds['lon'][:])
                jj = np.flatnonzero((lat >= map_box['lat_min']) & (lat <= map_box['lat_max']))
                ii = np.flatnonzero((lon >= map_box['lon_min']) & (lon <= map_box['lon_max']))
                window = (0, slice(jj[0], jj[-1] + 1), slice(ii[0], ii[-1] + 1))
            tb = np.ma.filled(np.ma.asarray(ds['tb'][window], dtype=float), np.nan)
        values.append(100.0 * np.mean(~np.isfinite(tb)))
    if not values:
        return float('nan'), float('nan')
    return float(np.mean(values)), float(np.max(values))


def rank_source(key, source, common, args):
    """
    Ranking table of one source.

    Args:
        key: str
            Source key.
        source: dict
            Settings of the source.
        common: dict
            Shared settings.
        args: argparse.Namespace
            Command line (thresholds, top, file check).

    Returns:
        table: pandas.DataFrame
            One row per listed window, best first.
    """
    ndays = common['ndays']
    # All time steps of the combined file (all years of the source), then the qualifying ones in the core box
    data = pq.read_table(source['selection_parquet'], columns=COLUMNS).to_pandas()
    steps = qualifying_steps(data, common['core_box'], common['months'], args.min_duration, args.min_area)
    del data
    scores = window_scores(steps, ndays, common['months'])

    rows, indexes = [], {}
    # Loop over the best windows: describe the MCSs, then check the pixel-level files of the window
    for rank, start in enumerate(best_windows(scores, ndays, args.top), start=1):
        row = {'source': key, 'rank': rank, 'start': start.strftime('%Y-%m-%d'), **window_metrics(steps, start, ndays)}
        if not args.no_file_check:
            paths = common_tools.source_paths(source, start.year)
            if paths['pixel_path'] not in indexes:
                indexes[paths['pixel_path']] = common_tools.index_pixel_files(paths['pixel_path'])
            t0, t1 = common_tools.period_of(start, ndays)
            files, missing = common_tools.files_of_period(indexes[paths['pixel_path']], t0, t1)
            mean_missing, max_missing = missing_tb_percent(files, common['map_box'])
            row.update({'missing_hours': len(missing), 'tb_missing_mean_pct': mean_missing, 'tb_missing_max_pct': max_missing,
                        'usable': bool(len(missing) == 0 and mean_missing <= args.max_tb_missing)})
        rows.append(row)
    return pd.DataFrame(rows)


def main(argv=None):
    """
    Rank the windows of the chosen sources and write the CSV files.

    Args:
        argv: list of str (default: None = sys.argv[1:])
    """
    args = parse_args(argv)
    common, sources = common_tools.load_sources(args.config)
    keys = args.sources or list(sources)
    outdir = args.outdir or os.path.join(common['outdir'], 'period_selection')
    os.makedirs(outdir, exist_ok=True)

    tables = []
    # Loop over the sources: rank, print and save one table each
    for key in keys:
        table = rank_source(key, sources[key], common, args)
        table.to_csv(os.path.join(outdir, f'{key}.csv'), index=False, float_format='%.2f')
        print(f"\n===== {key}: {sources[key]['label']}")
        print(table.drop(columns='source').to_string(index=False, float_format=lambda v: f'{v:.1f}'), flush=True)
        tables.append(table)
    pd.concat(tables, ignore_index=True).to_csv(os.path.join(outdir, 'all_sources.csv'), index=False, float_format='%.2f')
    print(f'\nCSV files in {outdir}')


if __name__ == '__main__':
    main()
