"""Tests of the building blocks of ``mcs_environment/monthly`` (vertical interpolation, time axes, configuration, readers, writer, remapper).

Run from the scream folder:  python -m pytest tests/test_env_monthly_core.py
"""

import copy
import importlib.util
import sys
from pathlib import Path

import netCDF4
import numpy as np
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1] / "mcs_environment" / "monthly"
sys.path.insert(0, str(ROOT))

from envmonthly import readers, timeaxis, vertical  # noqa: E402
from envmonthly.config import ConfigError, load_dataset  # noqa: E402
from envmonthly.regrid import Remapper, check_source_grid  # noqa: E402
from envmonthly.writer import FILL, check_compression, write_env_file  # noqa: E402

CONFIG = ROOT / "config"
ORIGINAL_SCRIPT = Path("/global/u1/f/feng045/program/e3sm_polun/scripts/interp_to_plev.py")


# ---------------------------------------------------------------------------------------------------------------------------------
# vertical
# ---------------------------------------------------------------------------------------------------------------------------------
def _columns(n_lev=20, n_col=30, seed=0):
    """Random sigma-level columns (``p = b * ps``): pressure (level, cell) increasing with the level index, and the surface pressures."""
    ps = np.random.default_rng(seed).uniform(60000.0, 102000.0, n_col)
    return vertical.hybrid_pressure(np.zeros(n_lev), np.linspace(0.02, 1.0, n_lev), 1e5, ps), ps


def test_interp_is_exact_for_a_field_linear_in_ln_p():
    """A field a + b ln(p) is reproduced exactly at any level between the first and the last."""
    pres, _ = _columns()
    field = 3.0 + 2.0 * np.log(pres)
    out = vertical.interp_to_plev(field, pres, 85000.0)
    ok = np.isfinite(out)
    assert ok.sum() >= 10 and not ok.all()                 # columns with the ground above 850 hPa are NaN
    assert np.allclose(out[ok], 3.0 + 2.0 * np.log(85000.0), rtol=0, atol=1e-10)


def test_interp_is_nan_above_the_top_and_below_the_bottom():
    """NaN where the target is lower in pressure than the first level or higher than the last (below the ground)."""
    pres = np.array([[100.0, 100.0], [500.0, 500.0], [1000.0, 800.0]])
    field = np.array([[1.0, 1.0], [2.0, 2.0], [3.0, 3.0]])
    assert np.isfinite(vertical.interp_to_plev(field, pres, 700.0)).tolist() == [True, True]
    assert np.isfinite(vertical.interp_to_plev(field, pres, 900.0)).tolist() == [True, False]     # second column: 900 > lowest level 800
    assert np.isnan(vertical.interp_to_plev(field, pres, 50.0)).all()                              # above the first level


def test_interp_propagates_nan_of_a_bracketing_value():
    """A NaN in one of the two bracketing levels gives NaN, NaN elsewhere in the column does not matter."""
    pres = np.array([[100.0], [500.0], [1000.0]])
    assert np.isnan(vertical.interp_to_plev(np.array([[1.0], [np.nan], [3.0]]), pres, 700.0)).all()
    assert np.isfinite(vertical.interp_to_plev(np.array([[np.nan], [2.0], [3.0]]), pres, 700.0)).all()


@pytest.mark.skipif(not ORIGINAL_SCRIPT.exists(), reason="e3sm_polun/scripts/interp_to_plev.py not available")
def test_interp_equals_the_original_script():
    """The product's interpolation gives the same numbers as ``interp_column_logp`` of e3sm_polun/scripts/interp_to_plev.py."""
    spec = importlib.util.spec_from_file_location("interp_to_plev_original", ORIGINAL_SCRIPT)
    original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    pres, _ = _columns(n_lev=30, n_col=50, seed=3)
    field = np.random.default_rng(4).normal(size=pres.shape)
    for plev in (50000.0, 85000.0):
        old = original.interp_column_logp(field[None], pres[None], np.array([plev]))[0, 0]
        assert np.allclose(vertical.interp_to_plev(field, pres, plev), old, equal_nan=True, rtol=0, atol=1e-12)


def test_monthly_mean_pressure_is_the_mean_of_the_pressures():
    """With the monthly-mean surface pressure the hybrid pressure is exactly the monthly mean of the instantaneous pressures."""
    a, b = np.linspace(0.0, 0.2, 10), np.linspace(0.01, 1.0, 10)
    ps_t = np.random.default_rng(1).uniform(95000.0, 103000.0, (30, 4))
    mean_of_p = np.mean([vertical.hybrid_pressure(a, b, 1e5, ps) for ps in ps_t], axis=0)
    assert np.allclose(vertical.hybrid_pressure(a, b, 1e5, ps_t.mean(axis=0)), mean_of_p, rtol=1e-12)


def test_pressure_order_is_checked():
    """Pressure that decreases with the level index is refused."""
    pres = np.array([[100.0], [500.0], [1000.0]])
    vertical.check_pressure_order(pres)
    with pytest.raises(ValueError):
        vertical.check_pressure_order(pres[::-1])


def test_below_ground_mask():
    """The level is masked where the surface pressure is below it, or unknown."""
    out = vertical.mask_below_ground(np.array([1.0, 2.0, 3.0, 4.0]), np.array([90000.0, 80000.0, 85000.0, np.nan]), 850.0)
    assert np.isfinite(out).tolist() == [True, False, True, False]


# ---------------------------------------------------------------------------------------------------------------------------------
# timeaxis
# ---------------------------------------------------------------------------------------------------------------------------------
def test_month_helpers():
    """Month lists, parsing and the number of days of February in the two calendars."""
    assert timeaxis.month_range((2008, 11), (2009, 2)) == [(2008, 11), (2008, 12), (2009, 1), (2009, 2)]
    assert timeaxis.parse_month("1995-01") == (1995, 1)
    for bad in ("1995", "1995-13", "x-y"):
        with pytest.raises(ValueError):
            timeaxis.parse_month(bad)
    assert timeaxis.days_in_month(2008, 2, "noleap") == 28
    assert timeaxis.days_in_month(2008, 2, "standard") == 29


def test_time_axis_values_follow_the_calendar():
    """The bounds of a month are one month apart in days of the calendar; the value is the mid-point."""
    mid, (b0, b1) = timeaxis.time_axis_values(1995, 2, "noleap")
    assert b1 - b0 == 28 and mid == pytest.approx(0.5 * (b0 + b1))
    assert timeaxis.time_axis_values(1996, 2, "standard")[1][1] - timeaxis.time_axis_values(1996, 2, "standard")[1][0] == 29


def _time_file(path, units, calendar, values, bounds=None):
    """Tiny file with a time axis (and bounds) for the month checks."""
    with netCDF4.Dataset(path, "w") as ds:
        ds.createDimension("time", len(values))
        t = ds.createVariable("time", "f8", ("time",))
        t.units, t.calendar = units, calendar
        t[:] = values
        if bounds is not None:
            ds.createDimension("nbnd", 2)
            ds.createVariable("time_bnds", "f8", ("time", "nbnd"))[:] = bounds
    return path


def test_check_file_month_with_bounds(tmp_path):
    """Averaged output: the window must start on the first day of the month and end on the first day of the next one."""
    units = "days since 1994-10-01 00:00:00"
    good = _time_file(tmp_path / "good.nc", units, "noleap", [123.0], [[92.0, 123.0]])          # 1995-01-01 .. 1995-02-01
    off = _time_file(tmp_path / "off.nc", units, "noleap", [92.0], [[61.0, 92.0]])              # 1994-12-01 .. 1995-01-01
    with netCDF4.Dataset(good) as ds:
        assert timeaxis.check_file_month(ds, 1995, 1, "noleap") == 1
        with pytest.raises(ValueError):
            timeaxis.check_file_month(ds, 1995, 2, "noleap")
    with netCDF4.Dataset(off) as ds, pytest.raises(ValueError):
        timeaxis.check_file_month(ds, 1995, 1, "noleap")


def test_check_file_month_without_bounds(tmp_path):
    """Instantaneous records: all of them inside the month (a monthly file stamped on the first hour passes, a day of the next month fails)."""
    units = "hours since 1900-01-01 00:00:00"
    first_hour = 937944.0                                                       # 2007-01-01 00:00
    inside = _time_file(tmp_path / "in.nc", units, "gregorian", first_hour + np.arange(0, 744))
    leak = _time_file(tmp_path / "leak.nc", units, "gregorian", first_hour + np.arange(0, 744 + 24))
    with netCDF4.Dataset(inside) as ds:
        assert timeaxis.check_file_month(ds, 2007, 1, "standard") == 744
    with netCDF4.Dataset(leak) as ds, pytest.raises(ValueError):
        timeaxis.check_file_month(ds, 2007, 1, "standard")


def test_check_file_month_refuses_an_empty_file(tmp_path):
    """A file with no time record (the empty SCREAM months) is refused with a message that says so."""
    empty = _time_file(tmp_path / "empty.nc", "days since 1994-10-01 00:00:00", "noleap", [], np.zeros((0, 2)))
    with netCDF4.Dataset(empty) as ds, pytest.raises(ValueError, match="no time record"):
        timeaxis.check_file_month(ds, 1995, 8, "noleap")


# ---------------------------------------------------------------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["ERA5", "3km_CTL", "3km_TUNE", "25km", "100km"])
def test_the_shipped_configs_load(name):
    """Every dataset config of the product is valid and defines the expected CMIP names."""
    ds = load_dataset(CONFIG / f"{name}.yaml")
    assert set(ds.output_names()) == {"prw", "hus850", "hur500", "wap500", "ps"}
    assert ds.map_path().name == f"map_{ds.grid}_to_g1deg_bilinear.nc"
    assert ds.months()[0] == ds.start and ds.months()[-1] == ds.end


def test_known_missing_months_are_part_of_the_config():
    """The empty CTL months are listed as known gaps and left out of the expected months; a bad entry is refused."""
    ds = load_dataset(CONFIG / "3km_CTL.yaml")
    assert (1995, 8) in ds.known_missing and len(ds.known_missing) == 5
    assert (1995, 8) in ds.months() and (1995, 8) not in ds.expected_months() and len(ds.expected_months()) == len(ds.months()) - 5
    assert load_dataset(CONFIG / "100km.yaml").known_missing == frozenset()


def test_the_groups_say_how_a_variable_is_obtained():
    """direct / interpolate / plev_select are kept as the method of each variable."""
    methods = {v.name: v.method for v in load_dataset(CONFIG / "25km.yaml").variables}
    assert methods == {"prw": "direct", "ps": "direct", "hus850": "interpolate", "hur500": "interpolate", "wap500": "interpolate"}
    assert {v.name: v.method for v in load_dataset(CONFIG / "100km.yaml").variables}["wap500"] == "direct"
    assert {v.name: v.method for v in load_dataset(CONFIG / "ERA5.yaml").variables}["wap500"] == "plev_select"


def _edited_config(tmp_path, edit):
    """Copy of the 3km_CTL config (with the shared files) in tmp_path after ``edit(dict)``; returns the path."""
    for f in ("grids.yaml", "variables.yaml"):
        (tmp_path / f).write_text((CONFIG / f).read_text())
    raw = yaml.safe_load((CONFIG / "3km_CTL.yaml").read_text())
    edit(raw)
    (tmp_path / "x.yaml").write_text(yaml.safe_dump(raw))
    return tmp_path / "x.yaml"


@pytest.mark.parametrize("edit, text", [
    (lambda r: r["streams"]["monthly"]["direct"].update({"notacmipname": {"raw": "x"}}), "not a CMIP name"),
    (lambda r: r["streams"]["monthly"]["interpolate"]["hus850"].update({"plev_hpa": 700}), "differs from"),
    (lambda r: r["streams"]["monthly"]["direct"]["prw"].update({"plev_hpa": 850}), "no plev_hpa"),
    (lambda r: r["streams"]["monthly"].pop("pressure"), "needs a 'pressure'"),
    (lambda r: r["streams"]["monthly"]["interpolate"].update({"prw": {"raw": "x", "plev_hpa": 850}}), "differs from|defined in"),
    (lambda r: r.update({"calendar": "julian"}), "calendar"),
    (lambda r: r.update({"grid": "nogrid"}), "not in grids.yaml"),
    (lambda r: r["period"].update({"end": "1990-01"}), "before"),
    (lambda r: r["streams"]["monthly"].update({"pattern": "file.nc"}), "pattern needs"),
    (lambda r: r["streams"]["monthly"]["interpolate"]["hur500"].update({"mask_below_ground": "nothing"}), "mask_below_ground"),
    (lambda r: r.update({"known_missing_months": ["1995-13"]}), "known_missing_months"),
])
def test_config_errors_name_the_problem(tmp_path, edit, text):
    """A wrong configuration is refused with a message that names the dataset and the key."""
    with pytest.raises(ConfigError, match=text):
        load_dataset(_edited_config(tmp_path, edit))


# ---------------------------------------------------------------------------------------------------------------------------------
# readers
# ---------------------------------------------------------------------------------------------------------------------------------
def _stream(layout, **options):
    """A StreamSpec with the given layout and options (the readers only use names and options)."""
    from envmonthly.config import StreamSpec

    return StreamSpec("s", "/", "x_{yyyy}{mm}.nc", layout, None, options, ())


def test_ncol_reader_handles_both_dimension_orders_and_fill_values(tmp_path):
    """(time, ncol, lev) and (time, lev, ncol) both come back as (level, cell); fill values become NaN."""
    values = np.arange(12, dtype="f4").reshape(3, 4)                       # (lev, ncol)
    path = tmp_path / "a.nc"
    with netCDF4.Dataset(path, "w") as ds:
        ds.createDimension("time", 1)
        ds.createDimension("ncol", 4)
        ds.createDimension("lev", 3)
        ds.createVariable("t", "f4", ("time",))[:] = 0.0
        for name, dims, data in (("a", ("time", "ncol", "lev"), values.T[None]), ("b", ("time", "lev", "ncol"), values[None]),
                                 ("c", ("time", "ncol"), values[0][None])):
            v = ds.createVariable(name, "f4", dims, fill_value=np.float32(3.4e33))
            v.units = "kg/kg"
            v[:] = data
        ds["b"][0, 1, 2] = np.ma.masked
    stream = _stream("ncol")
    with netCDF4.Dataset(path) as ds:
        # The file has no 'time' coordinate attribute check here: the readers only need the variable dimensions
        a, units = readers._ncol_read(ds, stream, "a")
        b, _ = readers._ncol_read(ds, stream, "b")
        c, _ = readers._ncol_read(ds, stream, "c")
    assert units == "kg/kg" and a.shape == b.shape == (3, 4) and c.shape == (4,)
    assert np.array_equal(a, values)
    assert np.isnan(b[1, 2]) and np.isfinite(b).sum() == 11


def test_latlon_reader_means_all_records_selects_the_level_and_flips_latitude(tmp_path):
    """Mean over the records of all files of the month, the right level, ascending latitude, counts of the records."""
    lat = np.array([30.0, 0.0, -30.0])                                   # descending, as ERA5 stores it
    lon = np.array([0.0, 90.0, 180.0, 270.0])
    files = []
    for i, offset in enumerate((0.0, 10.0)):
        path = tmp_path / f"w_{i}.nc"
        with netCDF4.Dataset(path, "w") as ds:
            ds.createDimension("time", 2)
            ds.createDimension("level", 2)
            ds.createDimension("latitude", 3)
            ds.createDimension("longitude", 4)
            ds.createVariable("latitude", "f8", ("latitude",))[:] = lat
            ds.createVariable("longitude", "f8", ("longitude",))[:] = lon
            ds.createVariable("level", "f8", ("level",))[:] = [500.0, 850.0]
            v = ds.createVariable("W", "f4", ("time", "level", "latitude", "longitude"))
            v.units = "Pa s-1"
            for t in range(2):
                v[t] = np.stack([np.full((3, 4), offset + t), np.full((3, 4), 100.0 + offset + t)])
            if i == 0:
                v[0, 0, 0, 0] = 40.0                          # record 0, 500 hPa, lat 30, lon 0
        files.append(str(path))
    from envmonthly.config import VarSpec

    stream = _stream("latlon", expected_records_per_day=1)
    spec = VarSpec("wap500", "s", "plev_select", "W", 500.0)
    mean, info = readers.read_latlon_variable(stream, files, spec, 2007, 1, "standard")
    assert mean.shape == (3, 4)
    # The 500 hPa level of the four records is (0, 1, 10, 11) everywhere: mean 5.5; the cell at lat 30, lon 0 has 40 instead of 0 in record 0
    assert np.allclose(mean[:2], 5.5) and np.allclose(mean[2, 1:], 5.5) and mean[2, 0] == pytest.approx(15.5)
    assert info["n_records"] == 4 and info["n_records_expected"] == 31 and info["units"] == "Pa s-1"
    # Latitude is returned ascending: the grid and the data are flipped together (lat 30 is the last row)
    assert readers.read_grid(stream, files[0])["lat"].tolist() == [-30.0, 0.0, 30.0]
    with pytest.raises(ValueError):
        readers.read_latlon_variable(stream, files, VarSpec("x", "s", "plev_select", "W", 700.0), 2007, 1, "standard")


# ---------------------------------------------------------------------------------------------------------------------------------
# writer
# ---------------------------------------------------------------------------------------------------------------------------------
def _write_small(path, shape=(1, 150, 120)):
    """Write a file with one variable through the product's writer."""
    grid = {"kind": "latlon", "lat": np.linspace(-89, 89, shape[1]), "lon": np.linspace(0, 359, shape[2])}
    field = np.random.default_rng(0).normal(size=shape).astype("f4")
    field[0, 0, :5] = np.nan
    meta = {"prw": {"long_name": "x", "units": "kg m-2"}}
    write_env_file(path, grid, {"prw": field}, meta, {"values": [100.0], "bounds": [[90.0, 110.0]], "calendar": "noleap"}, {"title": "t"}, deflate=4)
    return field


def test_writer_compresses_sets_fill_and_attributes(tmp_path):
    """The file is netCDF4 with deflate + shuffle, NaN is stored as the fill value, the time axis has its calendar and bounds."""
    path = tmp_path / "f.nc"
    field = _write_small(path)
    assert check_compression(path, names=["prw"]) == []
    with netCDF4.Dataset(path) as ds:
        assert ds["prw"].filters()["zlib"] and ds["prw"].filters()["shuffle"] and ds["prw"].filters()["complevel"] == 4
        assert ds["time"].calendar == "noleap" and ds["time"].bounds == "time_bnds" and ds.Conventions.startswith("CF")
        raw = ds["prw"][:]
        assert np.ma.is_masked(raw[0, 0, 0]) and int(np.ma.getmaskarray(raw).sum()) == 5
        assert np.allclose(np.ma.filled(raw, np.nan), field, equal_nan=True)
    assert not list(tmp_path.glob(".*.part"))


def test_compression_check_catches_an_uncompressed_file(tmp_path):
    """A variable stored without deflate, and a classic-format file, are reported."""
    path = tmp_path / "raw.nc"
    with netCDF4.Dataset(path, "w", format="NETCDF4") as ds:
        ds.createDimension("x", 200)
        ds.createDimension("y", 100)
        ds.createVariable("v", "f4", ("x", "y"))[:] = 1.0
    assert "not deflated" in check_compression(path)[0]
    classic = tmp_path / "classic.nc"
    with netCDF4.Dataset(classic, "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("x", 3)
        ds.createVariable("v", "f4", ("x",))[:] = 1.0
    assert "classic" in check_compression(classic)[0]


def test_writer_refuses_a_wrong_shape(tmp_path):
    """Fields that do not match the grid are refused and leave no file behind."""
    grid = {"kind": "latlon", "lat": np.arange(3.0), "lon": np.arange(4.0)}
    with pytest.raises(ValueError):
        write_env_file(tmp_path / "bad.nc", grid, {"prw": np.zeros((1, 3, 5))}, {"prw": {}}, {"values": [0.0], "calendar": "standard"}, {})
    assert not list(tmp_path.iterdir())


# ---------------------------------------------------------------------------------------------------------------------------------
# Remapper
# ---------------------------------------------------------------------------------------------------------------------------------
def _toy_map(tmp_path):
    """A map of 4 source cells to 2 x 2 destination cells: cell 0 = 0.5 a + 0.5 b, cell 1 = c, cell 2 = a, cell 3 without weights."""
    m = tmp_path / "map.nc"
    with netCDF4.Dataset(m, "w") as ds:
        ds.createDimension("n_a", 4)
        ds.createDimension("n_b", 4)
        ds.createDimension("n_s", 4)
        ds.createVariable("row", "i4", ("n_s",))[:] = [1, 1, 2, 3]
        ds.createVariable("col", "i4", ("n_s",))[:] = [1, 2, 3, 1]
        ds.createVariable("S", "f8", ("n_s",))[:] = [0.5, 0.5, 1.0, 1.0]
        ds.createVariable("frac_b", "f8", ("n_b",))[:] = [1.0, 1.0, 1.0, 0.0]
    g = tmp_path / "dst.nc"
    with netCDF4.Dataset(g, "w") as ds:
        ds.createDimension("grid_size", 4)
        ds.createDimension("grid_rank", 2)
        ds.createVariable("grid_dims", "i4", ("grid_rank",))[:] = [2, 2]
        ds.createVariable("grid_center_lat", "f8", ("grid_size",))[:] = [-10.0, -10.0, 10.0, 10.0]
        ds.createVariable("grid_center_lon", "f8", ("grid_size",))[:] = [0.0, 20.0, 0.0, 20.0]
    return m, g


def test_remapper_weights_nan_rule_and_unmapped_cells(tmp_path):
    """Weighted means, NaN-aware with the valid-weight fraction, cells without weights missing."""
    m, g = _toy_map(tmp_path)
    r = Remapper(m, g, valid_fraction=0.5)
    assert r.lat.tolist() == [-10.0, 10.0] and r.lon.tolist() == [0.0, 20.0]
    out = r.apply(np.array([2.0, 4.0, 6.0, 8.0]))
    assert out.shape == (2, 2) and out[0, 0] == pytest.approx(3.0) and out[0, 1] == pytest.approx(6.0) and out[1, 0] == pytest.approx(2.0)
    assert np.isnan(out[1, 1])                                            # no weights
    # One of the two sources of cell 0 missing: exactly half of the weight is valid -> valid with the other value; both missing -> missing
    assert r.apply(np.array([2.0, np.nan, 6.0, 8.0]))[0, 0] == pytest.approx(2.0)
    assert np.isnan(r.apply(np.array([np.nan, np.nan, 6.0, 8.0]))[0, 0])
    # A stricter fraction blanks the half-valid cell
    assert np.isnan(Remapper(m, g, valid_fraction=0.75).apply(np.array([2.0, np.nan, 6.0, 8.0]))[0, 0])
    with pytest.raises(ValueError):
        r.apply(np.zeros(5))


def test_source_grid_check(tmp_path):
    """Coordinates within the tolerance pass, a shifted or reordered grid is refused."""
    src = tmp_path / "src.nc"
    with netCDF4.Dataset(src, "w") as ds:
        ds.createDimension("grid_size", 4)
        ds.createVariable("grid_center_lat", "f8", ("grid_size",))[:] = [0.0, 0.0, 10.0, 10.0]
        ds.createVariable("grid_center_lon", "f8", ("grid_size",))[:] = [0.0, 20.0, 0.0, 20.0]
    same = {"lat": np.array([0.0, 0.0, 10.0, 10.0]) + 0.05, "lon": np.array([0.0, 20.0, 0.0, 20.0]) - 0.05}
    check_source_grid(same, str(src), "ncol")
    with pytest.raises(ValueError):
        check_source_grid({"lat": same["lat"][::-1], "lon": same["lon"][::-1]}, str(src), "ncol")
    with pytest.raises(ValueError):
        check_source_grid({"lat": same["lat"][:3], "lon": same["lon"][:3]}, str(src), "ncol")
