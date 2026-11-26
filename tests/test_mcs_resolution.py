"""
Tests of the Sahel MCS animation tools in mcs_resolution/animation (no data of the study is needed).
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest
import xarray as xr

ANIMATION = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'mcs_resolution', 'animation')
sys.path.insert(0, ANIMATION)

import sahel_common as common_tools  # noqa: E402
import select_sahel_periods as select  # noqa: E402

KEYS = ['obs', 'scream3_ctl', 'scream3_tune', 'scream13_ctl', 'scream13_tune', 'e3sm25', 'e3sm100']
CORE = {'lon_min': -18.0, 'lon_max': 35.0, 'lat_min': 5.0, 'lat_max': 20.0}


def test_source_file_has_all_sources_and_keys():
    """The seven sources of the study, each with every setting that the two tools read."""
    common, sources = common_tools.load_sources()
    assert list(sources) == KEYS
    for source in sources.values():
        for key in ('label', 'title', 'config_file', 'trackstats_file', 'pixel_path', 'selection_parquet', 'start'):
            assert key in source
    assert common['ndays'] == 7


def test_paths_fill_year_and_resolve_repository_files():
    """{year} / {next} are filled, a relative config file is a file of the repository."""
    _, sources = common_tools.load_sources()
    paths = common_tools.source_paths(sources['scream13_ctl'], 2000)
    assert paths['trackstats_file'].endswith('mcs_tracks_final_20000101.0000_20010101.0000.nc')
    assert paths['pixel_path'].endswith('/20000101.0000_20010101.0000/')
    assert paths['config_file'].startswith(common_tools.REPO)


@pytest.mark.parametrize('key', ['scream3_tune', 'e3sm25', 'e3sm100'])
def test_tracked_config_copies_exist(key):
    """The configs that are copies in the repository exist (the per-year decadal configs are git-ignored)."""
    _, sources = common_tools.load_sources()
    year = 2020 if key == 'scream3_tune' else 2010
    assert os.path.isfile(common_tools.source_paths(sources[key], year)['config_file'])


def test_period_includes_the_last_half_hour(tmp_path):
    """A 2-day period holds 48 hourly files stamped hh:30; a missing hour is reported."""
    times = pd.date_range('2010-08-01 00:30', periods=49, freq='h')
    for time in times.delete(5):
        (tmp_path / f'mcstrack_{time:%Y%m%d_%H%M%S}.nc').touch()
    t0, t1 = common_tools.period_of('2010-08-01', 2)
    files, missing = common_tools.files_of_period(common_tools.index_pixel_files(str(tmp_path)), t0, t1)
    assert len(files) == 47
    assert list(missing) == [pd.Timestamp('2010-08-01 05:00')]


def make_table():
    """Three tracks: a large long one in the box, a small one, and a large long one outside the box."""
    rows = []
    for track, day, lat, area, hours in [(1, '2000-07-10', 12.0, 3.0e5, 30), (2, '2000-08-01', 12.0, 5.0e4, 30),
                                         (3, '2000-08-20', 40.0, 9.0e5, 30)]:
        for step, time in enumerate(pd.date_range(day, periods=hours, freq='h', tz='UTC')):
            rows.append((track, time, lat, 10.0 - 0.5 * step, area, float(hours)))
    return pd.DataFrame(rows, columns=select.COLUMNS)


def test_ranking_keeps_only_large_long_mcs_in_the_box():
    """Only track 1 qualifies, so every scoring window contains 10 or 11 July."""
    steps = select.qualifying_steps(make_table(), CORE, [5, 6, 7, 8, 9], 12, 1.0e5)
    assert set(steps['local_track']) == {1}
    scores = select.window_scores(steps, 7, [5, 6, 7, 8, 9])
    assert scores.iloc[0] == pytest.approx(30 * 3.0e5)
    assert scores.index.min() == pd.Timestamp('2000-05-01')
    assert scores.index.max() == pd.Timestamp('2000-09-24')
    starts = select.best_windows(scores, 7, 3)
    assert all(abs((a - b).days) >= 7 for i, a in enumerate(starts) for b in starts[:i])
    metrics = select.window_metrics(steps, starts[0], 7)
    assert metrics['n_mcs'] == 1 and metrics['longest_inbox_h'] == 30 and metrics['n_westward'] == 1


def test_pairing_check_accepts_the_own_statistics_and_rejects_another(tmp_path):
    """Pixel masks numbered after the rows of one statistics file fail against a file with the rows in another order."""
    lat, lon = np.arange(0.05, 20, 0.1), np.arange(0.05, 20, 0.1)
    times = pd.date_range('2000-08-01 01:00', periods=6, freq='h')
    centers = [(5.0, 5.0), (15.0, 12.0)]
    files = []
    # One pixel file per hour with a square mask around each center, numbered 1 and 2
    for time in times:
        mask = np.zeros((lat.size, lon.size), dtype='int64')
        for number, (clat, clon) in enumerate(centers, start=1):
            mask[np.ix_(np.abs(lat - clat) < 1, np.abs(lon - clon) < 1)] = number
        path = tmp_path / f'mcstrack_{time:%Y%m%d_%H%M%S}.nc'
        xr.Dataset({'cloudtracknumber': (('time', 'lat', 'lon'), mask[None]), 'base_time': ('time', [time.timestamp()])},
                   coords={'lat': lat, 'lon': lon}).to_netcdf(path)
        files.append(str(path))
    files = pd.Series(files, index=times)
    base = np.array([[t.timestamp() for t in times]] * 2)
    # The right file, and one whose two rows are swapped
    for name, order, expected in [('right.nc', [0, 1], True), ('swapped.nc', [1, 0], False)]:
        stats = xr.Dataset({'base_time': (('tracks', 'times'), base),
                            'meanlat': (('tracks', 'times'), np.array([[centers[i][0]] * 6 for i in order])),
                            'meanlon': (('tracks', 'times'), np.array([[centers[i][1]] * 6 for i in order]))})
        stats.to_netcdf(tmp_path / name)
        assert common_tools.check_pairing(files, str(tmp_path / name))['ok'] is expected
