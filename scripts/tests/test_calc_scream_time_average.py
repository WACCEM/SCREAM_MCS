"""Numerical and CLI regression tests using tiny synthetic SCREAM snapshots.

Run with the existing project environment:
    /global/common/software/m1867/python/pyflex26.3/bin/python \
      -m unittest discover -s scripts/tests -p test_calc_scream_time_average.py -v
"""
from datetime import timedelta
import sys
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import cftime
import numpy as np
import xarray as xr

# Load the standalone script without requiring a package installation.
SCRIPT = Path(__file__).resolve().parents[1] / "calc_scream_time_average.py"
sys.path.insert(0, str(SCRIPT.parent))
import calc_scream_time_average as average
import strip_scream_extra_variables as strip
PRECIP = "precip_total_surf_mass_flux"


class AveragingTests(unittest.TestCase):
    """Exercise means, metadata, calendar bins, and failure behavior."""

    def setUp(self):
        """Create isolated small input/output directories for each test."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.inputs = self.root / "input files"
        self.outputs = self.root / "output files"
        self.inputs.mkdir()
        self.prefix = "input.[literal]."
        self.base = cftime.DatetimeNoLeap(2020, 6, 1)
        self.snapshots = []

    def make_snapshots(self, times=None, units="m/s"):
        """Write tiny snapshots at times (default 00,05,15,20 minutes).

        units sets precipitation units (default m/s); return snapshot paths.
        Grid values include float64 geometry and a permanently masked cell.
        """
        if times is None:
            times = [self.base + timedelta(minutes=value) for value in [0, 5, 15, 20]]
        values = [1.0, 3.0, 9.0, 11.0]
        for index, stamp in enumerate(times):
            temperature = np.array([[270 + values[index % 4], np.nan],
                                    [np.nan, 270 + values[index % 4]]], dtype="float32")
            if index in (1, 2):
                temperature[0, 1] = 280 + index * 3
            precipitation = np.array([[1e-6 * (index + 1), np.nan],
                                      [np.nan, 0]], dtype="float32")
            latitude = np.array([[30.123456789123, 30.987654321987],
                                 [31.123456789123, 31.987654321987]], dtype="float64")
            longitude = latitude - 130.123456789
            area = np.array([[1e-8, 2e-8], [np.nan, 4e-8]], dtype="float64")
            ds = xr.Dataset({
                "T_2m": (("time", "y", "x"), temperature[None], {
                    "units": "K", "cell_methods": "time: point", "long_name": "2 meter air temperature"}),
                PRECIP: (("time", "y", "x"), precipitation[None], {
                    "units": units, "cell_methods": "time: point"}),
                "extra": (("time", "y", "x"), np.full((1, 2, 2), index, dtype="int32")),
                "latitude": (("y", "x"), latitude, {"units": "degrees_north", "bounds": "lat_bnds"}),
                "longitude": (("y", "x"), longitude, {"units": "degrees_east", "bounds": "lon_bnds"}),
                "lat_bnds": (("y", "x", "nvertices"), np.repeat(latitude[..., None], 4, axis=2)),
                "lon_bnds": (("y", "x", "nvertices"), np.repeat(longitude[..., None], 4, axis=2)),
                "area": (("y", "x"), area, {"units": "steradian"}),
                "hyam": ("lev", np.array([0.1234567, 0.9876543], dtype="float32")),
                "hyai": ("ilev", np.array([0, 0.5, 1], dtype="float32")),
                "hybi": ("ilev", np.array([1, 0.5, 0], dtype="float32")),
                "swband_bounds": (("swband", "dim2"), np.ones((2, 2), dtype="float32")),
            }, coords={"time": [stamp], "y": np.array([1, 2], dtype="int32"),
                       "x": np.array([4, 6], dtype="int32"), "lev": [1, 2]},
                attrs={"averaging_type": "INSTANT", "averaging_frequency_units": "nmins",
                       "averaging_frequency": 5, "history": "synthetic input"})
            path = self.inputs / f"{self.prefix}{stamp.strftime('%Y-%m-%d-%H%M%S')}.nc"
            ds.to_netcdf(path, engine="netcdf4",
                         encoding={"time": {"calendar": "noleap", "units": "days since 2019-08-01"}})
            self.snapshots.append(path)
        return self.snapshots

    def arguments(self, *extra):
        """Return CLI arguments with custom paths/prefixes and supplied overrides."""
        return average.parse_args([
            "--input_dir", str(self.inputs), "--output_dir", str(self.outputs),
            "--input_basename", self.prefix, "--output_basename", "custom_average",
            "--start-datetime", "2020-06-01", "--end-datetime", "2020-06-01T00:25:00",
            "--frequency", "hourly", "--batch-size", "3", *extra])

    def run_small(self, *extra):
        """Run synchronous averaging with CLI overrides; return output paths."""
        with self.assertLogs(average.LOGGER, level="WARNING"):
            return average.run_averaging(self.arguments(*extra))

    def test_means_gaps_masks_units_and_grid_roundtrip(self):
        """Verify weighted batch combination, exact geometry, and coverage."""
        self.make_snapshots()
        outputs = self.run_small("--variables", "T_2m", PRECIP)
        self.assertEqual(outputs[0].name, "custom_average_hourly_20200601T000000.nc")
        with xr.open_dataset(outputs[0], decode_times=average.CF_CODER) as result:
            self.assertEqual(result.sizes["time"], 1)
            self.assertEqual(result.T_2m.dtype, np.dtype("float32"))
            np.testing.assert_allclose(result.T_2m.values[0, 0, 0], 276)
            np.testing.assert_allclose(result.T_2m.values[0, 0, 1], 284.5)
            self.assertTrue(np.isnan(result.T_2m.values[0, 1, 0]))
            np.testing.assert_array_equal(result.T_2m_valid_count.values[0], [[4, 2], [0, 4]])
            np.testing.assert_allclose(result[PRECIP].values[0, 0, 0], 9, rtol=1e-6)
            self.assertEqual(result[PRECIP].attrs["units"], "mm/h")
            self.assertEqual(result.T_2m.attrs["units"], "K")
            self.assertEqual(result.T_2m.attrs["cell_methods"], "time: mean")
            self.assertEqual(result.ntimes.item(), 4)
            self.assertEqual(result.expected_ntimes.item(), 5)
            self.assertAlmostEqual(result.coverage_fraction.item(), 0.8)
            self.assertEqual(result.time.encoding["calendar"], "noleap")
            self.assertEqual(result.time_bnds.values[0, 1], self.base + timedelta(minutes=25))
            self.assertNotIn("extra", result)
            self.assertEqual(set(result.sizes), {"time", "y", "x", "nvertices", "bnds"})
            for unused in ["hyam", "hyai", "hybi", "swband_bounds", "lev", "ilev", "swband", "dim2"]:
                self.assertNotIn(unused, result)
            with xr.open_dataset(self.snapshots[0]) as original:
                for name in ["latitude", "longitude", "area", "lat_bnds", "lon_bnds", "y", "x"]:
                    np.testing.assert_array_equal(result[name].values, original[name].values)
                    self.assertEqual(result[name].dtype, original[name].dtype)

    def test_default_all_variables(self):
        """Default selection includes all numeric time-dependent fields."""
        self.make_snapshots()
        outputs = self.run_small()
        with xr.open_dataset(outputs[0]) as result:
            self.assertIn("extra", result)
            np.testing.assert_allclose(result.extra.values, 1.5)

    def test_end_exclusive(self):
        """A snapshot exactly at end belongs to the following interval."""
        self.make_snapshots()
        outputs = self.run_small("--end-datetime", "2020-06-01T00:20:00", "--variables", "T_2m")
        with xr.open_dataset(outputs[0]) as result:
            self.assertEqual(result.ntimes.item(), 3)
            np.testing.assert_allclose(result.T_2m.values[0, 0, 0], 270 + 13 / 3, rtol=1e-7)

    def test_daily_monthly_and_custom_frequency_bins(self):
        """Calendar periods remain correct across month and noleap boundaries."""
        start = average.model_datetime("2020-02-28", "noleap")
        end = average.model_datetime("2020-03-01", "noleap")
        daily = list(average.period_bins(start, end, "daily"))
        self.assertEqual(len(daily), 1)
        self.assertEqual(daily[0][2] - daily[0][1], timedelta(days=1))
        june = average.model_datetime("2020-06-01", "noleap")
        september = average.model_datetime("2020-09-01", "noleap")
        monthly = list(average.period_bins(june, september, "monthly"))
        self.assertEqual([int((hi - lo) / timedelta(minutes=5)) for _, lo, hi in monthly],
                         [8640, 8928, 8928])
        self.assertEqual(len(list(average.period_bins(june, june + timedelta(days=1), "6h"))), 4)
        with self.assertRaises(ValueError):
            average.model_datetime("2020-02-29", "noleap")

    def test_empty_periods_are_skipped(self):
        """A completely empty bin warns and creates no misleading output."""
        self.make_snapshots([self.base, self.base + timedelta(hours=2)])
        outputs = self.run_small("--end-datetime", "2020-06-01T03:00:00", "--variables", "T_2m")
        self.assertEqual(len(outputs), 2)

    def test_precipitation_mass_units_and_unsupported_units(self):
        """Support water-equivalent mass units and refuse unknown rates."""
        for units in ["kg m-2 s-1", "kg/(m^2)/s", "(kg/(m^2))/s", "kg m**-2 s**-1"]:
            self.assertEqual(average.precipitation_factor(units), 3600)
        self.assertEqual(average.precipitation_factor("mm h-1"), 1)
        self.assertEqual(average.precipitation_factor("m s^-1"), 3_600_000)
        with self.assertRaises(ValueError):
            average.precipitation_factor("mm")
        self.make_snapshots(units="kg m-2 s-1")
        outputs = self.run_small("--variables", PRECIP)
        with xr.open_dataset(outputs[0]) as result:
            np.testing.assert_allclose(result[PRECIP].values[0, 0, 0], 0.009, rtol=1e-6)

    def test_existing_outputs_are_not_overwritten(self):
        """Preflight refuses existing output and leaves its bytes unchanged."""
        self.make_snapshots()
        outputs = self.run_small("--variables", "T_2m")
        before = outputs[0].read_bytes()
        with self.assertRaises(FileExistsError):
            average.run_averaging(self.arguments("--variables", "T_2m"))
        self.assertEqual(outputs[0].read_bytes(), before)

    def test_invalid_selection_dates_and_empty_range(self):
        """Fail clearly on bad variables, inverted dates, or no selected input."""
        self.make_snapshots()
        for extra in [("--variables", "unknown"),
                      ("--variables", "latitude"),
                      ("--end-datetime", "2020-05-01"),
                      ("--start-datetime", "2020-06-02", "--end-datetime", "2020-06-03"),
                      ("--batch-size", "0")]:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                average.run_averaging(self.arguments(*extra))

    def test_duplicate_and_mismatched_times(self):
        """Reject duplicate timestamps and incorrect filename time coordinates."""
        self.make_snapshots()
        duplicate = self.inputs / f"{self.prefix}duplicate.2020-06-01-000000.nc"
        duplicate.write_bytes(self.snapshots[0].read_bytes())
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            average.run_averaging(self.arguments())
        duplicate.unlink()
        with xr.open_dataset(self.snapshots[0], decode_times=average.CF_CODER) as source:
            wrong = source.load().assign_coords(time=[self.base + timedelta(minutes=1)])
        wrong.to_netcdf(self.snapshots[0], mode="w")
        with self.assertRaisesRegex(ValueError, "Filename/time-coordinate"):
            average.run_averaging(self.arguments())

    def test_unreadable_input(self):
        """An unreadable selected snapshot fails instead of being skipped."""
        self.make_snapshots()
        bad = self.inputs / f"{self.prefix}2020-06-01-002500.nc"
        bad.write_text("not a netCDF file")
        with self.assertRaises(OSError):
            average.run_averaging(self.arguments("--end-datetime", "2020-06-01T00:30:00"))

    def test_vertical_dependencies_and_unrelated_spatial_field(self):
        """Keep used vertical axes and CF links while dropping unrelated fields."""
        source = xr.Dataset({
            "profile": (("time", "ilev", "y", "x"), np.ones((1, 3, 2, 2)),
                        {"grid_mapping": "crs", "ancillary_variables": "quality"}),
            "hyai": ("ilev", [0.0, 0.5, 1.0]),
            "hybi": ("ilev", [1.0, 0.5, 0.0]),
            "hyam": ("lev", [0.25, 0.75]),
            "latitude": (("y", "x"), np.ones((2, 2)), {"bounds": "lat_bnds"}),
            "lat_bnds": (("y", "x", "nvertices"), np.ones((2, 2, 4))),
            "quality": (("y", "x"), np.zeros((2, 2))),
            "unrelated_map": (("y", "x"), np.zeros((2, 2))),
            "crs": ((), 1),
        }, coords={"time": [self.base], "ilev": [0, 1, 2], "lev": [1, 2]})
        source.profile.encoding["coordinates"] = "latitude"
        selected = average.retain_related_variables(source, ["profile"])
        for name in ["profile", "hyai", "hybi", "ilev", "latitude", "lat_bnds", "quality", "crs"]:
            self.assertIn(name, selected)
        self.assertNotIn("hyam", selected)
        self.assertNotIn("lev", selected.sizes)
        self.assertNotIn("unrelated_map", selected)

    def existing_output(self):
        """Create a compressed old-style file with extra axes; return its Path."""
        self.make_snapshots()
        with xr.open_dataset(self.snapshots[0], decode_cf=False) as source:
            output = source.load()
        output["ntimes"] = ("time", [1])
        output["expected_ntimes"] = ("time", [1])
        output["coverage_fraction"] = ("time", [1.0])
        output["T_2m_valid_count"] = (("time", "y", "x"),
                                     np.isfinite(output.T_2m.values).astype("int64"))
        raw_time = output.time.item()
        output["time_bnds"] = (("time", "bnds"), [[raw_time, raw_time + 5 / 1440]])
        output.time.attrs["bounds"] = "time_bnds"
        output.time_bnds.attrs.update(units=output.time.attrs["units"], calendar="noleap")
        path = self.root / "existing.nc"
        output.to_netcdf(path, engine="netcdf4", encoding={
            name: {"zlib": True, "complevel": 1} for name in output.variables})
        return path

    def test_strip_preserves_values_encoding_and_original_backup(self):
        """Smoke-test stripping an old file, exact data checks, and its backup."""
        path = self.existing_output()
        original_bytes = path.read_bytes()
        backup_dir = self.root / "backup"
        backup = strip.strip_file(path, ["T_2m", PRECIP], backup_dir)
        self.assertEqual(backup.read_bytes(), original_bytes)
        keep, _ = strip.selection(backup, ["T_2m", PRECIP])
        strip.validate_copy(backup, path, keep)
        with xr.open_dataset(path, decode_cf=False) as cleaned:
            self.assertEqual(set(cleaned.sizes), {"time", "y", "x", "nvertices", "bnds"})
            self.assertIn("T_2m_valid_count", cleaned)
            self.assertIn("coverage_fraction", cleaned)
            self.assertNotIn("extra", cleaned)
            self.assertNotIn("hyai", cleaned)
            self.assertNotIn("hyam", cleaned)
        self.assertIsNone(strip.strip_file(path, ["T_2m", PRECIP], backup_dir))

    def test_strip_validation_failure_leaves_original_in_place(self):
        """A failed staged validation must not move or change the original."""
        path = self.existing_output()
        original_bytes = path.read_bytes()
        backup_dir = self.root / "backup"
        with mock.patch.object(strip, "validate_copy", side_effect=AssertionError("invalid copy")):
            with self.assertRaises(AssertionError):
                strip.strip_file(path, ["T_2m", PRECIP], backup_dir)
        self.assertEqual(path.read_bytes(), original_bytes)
        self.assertFalse((backup_dir / path.name).exists())
        self.assertFalse(list(self.root.glob("*.tmp")))

    def test_strip_publication_failure_restores_original(self):
        """Restore the backed-up original if publishing its replacement fails."""
        path = self.existing_output()
        original_bytes = path.read_bytes()
        backup_dir = self.root / "backup"
        with mock.patch.object(strip.os, "link", side_effect=OSError("publication failed")):
            with self.assertRaises(OSError):
                strip.strip_file(path, ["T_2m", PRECIP], backup_dir)
        self.assertEqual(path.read_bytes(), original_bytes)
        self.assertFalse((backup_dir / path.name).exists())

    def test_strip_refuses_existing_backup(self):
        """Never overwrite an existing backup or modify its corresponding input."""
        path = self.existing_output()
        original_bytes = path.read_bytes()
        backup_dir = self.root / "backup"
        backup_dir.mkdir()
        existing_backup = backup_dir / path.name
        existing_backup.write_bytes(b"existing backup")
        with self.assertRaises(FileExistsError):
            strip.strip_file(path, ["T_2m", PRECIP], backup_dir)
        self.assertEqual(path.read_bytes(), original_bytes)
        self.assertEqual(existing_backup.read_bytes(), b"existing backup")


if __name__ == "__main__":
    unittest.main()

