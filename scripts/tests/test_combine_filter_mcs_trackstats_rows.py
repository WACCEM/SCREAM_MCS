"""Tests of combine_filter_mcs_trackstats.py: the row-table route gives the same table as the dense netCDF route.

A small synthetic dense stats file (six tracks, fill values, merge / split fragments, PF variables) is converted to row tables with
pyflextrkr.rowstats; both routes must give identical DataFrames (values, dtypes, NaN), and main() must write the same Parquet file
from the .nc file and from the .rows folder. Needs the pyflex26.3 environment (pyflextrkr.rowstats).

Run with:
    /global/common/software/m1867/python/pyflex26.3/bin/python \
      -m unittest discover -s scripts/tests -p test_combine_filter_mcs_trackstats_rows.py -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd
import xarray as xr

# Load the standalone script without requiring a package installation.
SCRIPT = Path(__file__).resolve().parents[1] / "combine_filter_mcs_trackstats.py"
sys.path.insert(0, str(SCRIPT.parent))
import combine_filter_mcs_trackstats as combine

try:
    from pyflextrkr import rowstats
except ImportError:  # pragma: no cover - the row route needs PyFLEXTRKR
    rowstats = None

EPOCH0 = 1262304000.0   # 2010-01-01 00:00 UTC [s]
NTRACKS, NTIMES, NSLOTS, NPF = 6, 7, 3, 2
DURATION = np.array([3, 5, 2, 7, 4, 1], dtype=np.int32)
# Lifetime-mean location of every track: tracks 0, 2, 4, 5 are inside the tropics box (|lat| <= 20), 1 and 3 outside
LAT0 = np.array([10.0, 35.0, -15.0, 25.0, 0.0, -19.9])
LON0 = np.array([30.0, -100.0, 150.0, 10.0, -170.0, 60.0])


def make_dense():
    """
    Synthetic dense stats Dataset in the layout of mcs_tracks_final_*.nc (opened with mask_and_scale=False).

    Padding after the end of a track holds the constant fill of the variable (NaN for floats, -9999 for integers); the fill
    attributes are in `attrs` as in the raw file. base_time has an attribute fill of -9999 but NaN padding, like the real files;
    mcs_status has -9999 inside the valid entries too (not an MCS); one merge fragment has a negative area.

    Returns:
        ds: xarray.Dataset
            Dense dataset with dims tracks, times, mergers, nmaxpf.
    """
    rng = np.random.default_rng(0)
    valid = np.arange(NTIMES)[None, :] < DURATION[:, None]                      # [tracks, times]

    def padded(values, fill):
        """Values where the entry exists, the fill elsewhere."""
        return np.where(valid, values, fill)

    start = EPOCH0 + 86400.0 * np.arange(NTRACKS)
    base_time = padded(start[:, None] + 3600.0 * np.arange(NTIMES)[None, :], np.nan)
    meanlat = padded(LAT0[:, None] + rng.normal(0, 0.2, (NTRACKS, NTIMES)), np.nan).astype(np.float32)
    meanlon = padded(LON0[:, None] + rng.normal(0, 0.2, (NTRACKS, NTIMES)), np.nan).astype(np.float32)
    ccs_area = padded(rng.uniform(1e4, 1e5, (NTRACKS, NTIMES)), np.nan).astype(np.float32)
    speed = padded(rng.uniform(0, 20, (NTRACKS, NTIMES)), np.nan).astype(np.float32)
    cloudnumber = padded(rng.integers(1, 500, (NTRACKS, NTIMES)), -9999).astype(np.int32)
    # mcs_status: 1 at some entries, the fill (-9999) at the others, also inside the valid entries
    mcs_status = padded(np.where(rng.random((NTRACKS, NTIMES)) > 0.5, 1, -9999), -9999).astype(np.int16)
    # PF variable [tracks, times, nmaxpf]: both PF of every valid entry, NaN elsewhere
    pf_area = np.where(valid[:, :, None], rng.uniform(100, 900, (NTRACKS, NTIMES, NPF)), np.nan).astype(np.float32)
    # Fragments [tracks, times, mergers]: a few merges and splits
    merge_cn = np.full((NTRACKS, NTIMES, NSLOTS), -9999, dtype=np.int32)
    merge_area = np.full((NTRACKS, NTIMES, NSLOTS), np.nan, dtype=np.float32)
    split_cn = np.full((NTRACKS, NTIMES, NSLOTS), -9999, dtype=np.int32)
    split_area = np.full((NTRACKS, NTIMES, NSLOTS), np.nan, dtype=np.float32)
    for (t, k, s, cn, area) in ((0, 1, 0, 7, 120.5), (0, 1, 1, 8, 30.0), (4, 2, 0, 9, 10.0), (3, 6, 2, 4, -5.0)):
        merge_cn[t, k, s], merge_area[t, k, s] = cn, area
    for (t, k, s, cn, area) in ((2, 0, 0, 3, 55.25), (0, 2, 1, 6, 77.0)):
        split_cn[t, k, s], split_area[t, k, s] = cn, area

    def var(dims, values, fill=None):
        """A variable with the raw fill value as attribute (None: no attribute)."""
        attrs = {} if fill is None else {'_FillValue': fill}
        return (dims, values, attrs)

    ds = xr.Dataset(
        {
            # per-track variables
            'track_duration': var(('tracks',), DURATION),
            'start_status': var(('tracks',), np.array([1, 3, 2, 1, 3, 2], dtype=np.int32), -9999),
            'end_status': var(('tracks',), np.array([1, 1, 2, 3, 3, 2], dtype=np.int32), -9999),
            'start_basetime': var(('tracks',), start, -9999.0),
            'end_basetime': var(('tracks',), start + 3600.0 * (DURATION - 1), -9999.0),
            'start_split_cloudnumber': var(('tracks',), np.array([-9999, 5, -9999, -9999, 3, -9999], dtype=np.int32), -9999),
            'end_merge_cloudnumber': var(('tracks',), np.array([-9999, -9999, 2, -9999, -9999, 1], dtype=np.int32), -9999),
            'pbc_flag': var(('tracks',), np.array([0, 0, 1, 0, 0, 0], dtype=np.int32)),
            'mcs_duration': var(('tracks',), DURATION.astype(np.int64) * 2),
            'pf_lifetime': var(('tracks',), np.array([2, 4, 1, 6, 3, 0], dtype=np.float32), np.nan),
            # [tracks, times] variables
            'base_time': var(('tracks', 'times'), base_time, -9999.0),
            'meanlat': var(('tracks', 'times'), meanlat, np.nan),
            'meanlon': var(('tracks', 'times'), meanlon, np.nan),
            'cloudnumber': var(('tracks', 'times'), cloudnumber, -9999),
            'mcs_status': var(('tracks', 'times'), mcs_status, -9999),
            'ccs_area': var(('tracks', 'times'), ccs_area, np.nan),
            'movement_speed': var(('tracks', 'times'), speed, np.nan),
            # [tracks, times, nmaxpf] PF variable
            'pf_area': var(('tracks', 'times', 'nmaxpf'), pf_area, np.nan),
            # [tracks, times, mergers] fragment variables
            'merge_cloudnumber': var(('tracks', 'times', 'mergers'), merge_cn, -9999),
            'merge_ccs_area': var(('tracks', 'times', 'mergers'), merge_area, np.nan),
            'split_cloudnumber': var(('tracks', 'times', 'mergers'), split_cn, -9999),
            'split_ccs_area': var(('tracks', 'times', 'mergers'), split_area, np.nan),
        },
        coords={'tracks': np.arange(NTRACKS), 'times': np.arange(NTIMES), 'mergers': np.arange(NSLOTS), 'nmaxpf': np.arange(NPF)},
        attrs={'time_resolution_hour': 1.0},
    )
    return ds


def write_dense_netcdf(ds, path):
    """Write the raw dataset as netCDF: the _FillValue attributes become encodings (xarray does not allow them in attrs)."""
    out = ds.copy(deep=True)
    for name in out.data_vars:
        fill = out[name].attrs.pop('_FillValue', None)
        if fill is not None:
            out[name].encoding['_FillValue'] = fill
    out.to_netcdf(path)


@unittest.skipIf(rowstats is None, "pyflextrkr.rowstats is not available (use the pyflex26.3 environment)")
class RowsRouteTests(unittest.TestCase):
    """The rows route equals the dense route."""

    BOX = dict(lonmin=-180.0, lonmax=180.0, latmin=-20.0, latmax=20.0)

    def setUp(self):
        """Create the synthetic dense Dataset, its netCDF file and its row folder in a temporary folder."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.ds = make_dense()
        # Folders named like the pipeline's files: yearly, 2010
        self.name = 'mcs_tracks_final_20100101.0000_20110101.0000'
        self.nc = self.root / 'nc' / f'{self.name}.nc'
        self.rows = self.root / 'rows' / f'{self.name}.rows'
        self.nc.parent.mkdir()
        self.rows.parent.mkdir()
        write_dense_netcdf(self.ds, self.nc)
        rowstats.write_rows(rowstats.dense_to_rows(self.ds), str(self.rows))

    def dense_frame(self):
        """The tidy frame of the dense route (kept tracks of the box)."""
        keep = combine.filter_tracks_by_region(self.ds, **self.BOX)
        return combine.ds_to_dataframe(self.ds, keep, 1.0)

    def test_region_keeps_the_same_tracks(self):
        """Both routes keep tracks 0, 2, 4 and 5 (the other two have a lifetime-mean latitude beyond 20 degrees)."""
        _, n_dense, kept_dense = combine.read_dense_file(str(self.nc), self.BOX)
        _, n_rows, kept_rows = combine.read_rows_file(str(self.rows), self.BOX)
        self.assertEqual((n_dense, kept_dense), (NTRACKS, 4))
        self.assertEqual((n_rows, kept_rows), (NTRACKS, 4))

    def test_tables_are_identical(self):
        """Values, NaN positions and dtypes of every column are the same; only the column order may differ."""
        dense = self.dense_frame()
        rows, _, _ = combine.read_rows_file(str(self.rows), self.BOX)
        self.assertEqual(sorted(dense.columns), sorted(rows.columns))
        pd.testing.assert_frame_equal(dense[sorted(dense.columns)], rows[sorted(rows.columns)], check_dtype=True)

    def test_fill_values_become_nan_and_integers_stay(self):
        """The -9999 of mcs_status and of the per-track integers is NaN (float64); track_duration and pbc_flag stay integers."""
        rows, _, _ = combine.read_rows_file(str(self.rows), self.BOX)
        self.assertEqual(rows['mcs_status'].dtype, np.float64)
        self.assertTrue(rows['mcs_status'].isna().any())
        self.assertFalse((rows['mcs_status'] == -9999).any())
        self.assertEqual(rows['start_split_cloudnumber'].dtype, np.float64)
        self.assertEqual(str(rows['track_duration'].dtype), 'int32')
        self.assertEqual(str(rows['pbc_flag'].dtype), 'int32')
        self.assertEqual(str(rows['base_time'].dtype), 'datetime64[ms, UTC]')

    def test_merge_and_split_areas(self):
        """Merge / split areas are the sums of the fragments of each entry (a negative area counts as 0, no fragment is 0)."""
        rows, _, _ = combine.read_rows_file(str(self.rows), self.BOX)
        # Track 0 is local track 0: two merges at k=1 (120.5 + 30.0) and a split at k=2 (77.0)
        t0 = rows[rows['local_track'] == 0].set_index('relative_step')
        self.assertEqual(t0.loc[1, 'merge_ccs_area'], 150.5)
        self.assertEqual(t0.loc[2, 'split_ccs_area'], 77.0)
        self.assertEqual(t0.loc[0, 'merge_ccs_area'], 0.0)
        # Track 2 is local track 1: a split of 55.25 at k=0
        self.assertEqual(rows[(rows['local_track'] == 1) & (rows['relative_step'] == 0)]['split_ccs_area'].iloc[0], 55.25)

    def test_conform_columns_fills_missing_columns_and_rejects_extra_ones(self):
        """The columns come in the order of UNIFIED_COLUMNS; a missing column is NaN (float64), an extra column is an error."""
        with mock.patch.object(combine, 'UNIFIED_COLUMNS', ['b', 'a']):
            out = combine.conform_columns(pd.DataFrame({'a': [1], 'b': [2]}), 'x')
            self.assertEqual(list(out.columns), ['b', 'a'])
            # A file without column b (an older PyFLEXTRKR): b is NaN, a keeps its values, and the message names b
            with mock.patch('builtins.print') as printed:
                filled = combine.conform_columns(pd.DataFrame({'a': [1, 2]}), '/path/old_file.nc')
            self.assertEqual(list(filled.columns), ['b', 'a'])
            self.assertTrue(filled['b'].isna().all())
            self.assertEqual(filled['b'].dtype, np.float64)
            self.assertEqual(filled['a'].tolist(), [1, 2])
            self.assertIn("['b']", str(printed.call_args))
            with self.assertRaises(ValueError):
                combine.conform_columns(pd.DataFrame({'a': [1], 'b': [2], 'c': [3]}), 'x')

    def test_period_is_the_start_year_of_the_track(self):
        """period is the calendar year of the start time of each track (one file can span several years)."""
        df = pd.DataFrame({'start_basetime': pd.to_datetime([EPOCH0, EPOCH0 + 400 * 86400.0], unit='s', utc=True)})
        self.assertEqual(combine.add_period(df)['period'].tolist(), ['2010', '2011'])
        with self.assertRaises(ValueError):
            combine.add_period(pd.DataFrame({'start_basetime': pd.to_datetime([EPOCH0, None], unit='s', utc=True)}))

    def test_extract_year_accepts_any_start_date(self):
        """The year of a file name comes from its start date, whatever the day (a 19-month run starts on 3 August)."""
        for name, year in (('mcs_tracks_final_19950101.0000_19960101.0000.nc', '1995'),
                           ('mcsmip_mcs_tracks_final_20000101.0000_20010101.0000.nc', '2000'),
                           ('mcs_tracks_final_20190803.0000_20210306.0000.nc', '2019'),
                           ('/x/y/mcs_tracks_final_20100101.0000_20110101.0000.rows/', '2010'),
                           ('mcs_tracks_final_combined_tropics_1995_2005.parquet', 'unknown')):
            self.assertEqual(combine._extract_year(name), year, name)

    def run_main(self, indir, pattern, outdir):
        """Run main() on a folder of the synthetic files with the synthetic column set as UNIFIED_COLUMNS."""
        columns = list(self.dense_frame().columns) + ['period']
        argv = ['combine', '--indir', str(indir), '--pattern', pattern, '--region', 'tropics', '--outdir', str(outdir)]
        with mock.patch.object(combine, 'UNIFIED_COLUMNS', columns), mock.patch.object(sys, 'argv', argv):
            combine.main()
        return sorted(Path(outdir).glob('*.parquet'))

    def test_main_writes_the_same_parquet_from_nc_and_rows(self):
        """The Parquet files from the .nc and from the .rows folder are identical, with the name from the periods."""
        out_nc = self.run_main(self.nc.parent, '*mcs_tracks_final_*.nc', self.root / 'out_nc')
        out_rows = self.run_main(self.rows.parent, '*mcs_tracks_final_*.rows', self.root / 'out_rows')
        self.assertEqual([p.name for p in out_nc], ['mcs_tracks_final_combined_tropics_2010_2010.parquet'])
        self.assertEqual([p.name for p in out_rows], [out_nc[0].name])
        a, b = pd.read_parquet(out_nc[0]), pd.read_parquet(out_rows[0])
        pd.testing.assert_frame_equal(a, b, check_dtype=True)
        self.assertEqual(a['local_track'].nunique(), 4)
        self.assertEqual(set(a['period']), {'2010'})


if __name__ == '__main__':
    unittest.main()
