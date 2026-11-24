"""End-to-end tests of ``mcs_environment/monthly`` on small synthetic data with known answers.

* an ERA5-like lat-lon dataset (monthly pressure-level file, hourly files in several pieces) goes through step 1 (native), step 2 (regrid with
  real ``ncremap`` weights) and step 3 (climatology); the values are compared with the analytic fields;
* SCREAM-like (``(time, ncol, lev)`` with a stored level pressure) and E3SM-like (``(time, lev, ncol)`` with hybrid coefficients) datasets go
  through step 1: the interpolated field is linear in ln(p), so the answer is exact.

The weights need NCO / ESMF (E3SM-unified); those tests are skipped when the programs are not found.
Run from the scream folder:  python -m pytest tests/test_env_monthly_pipeline.py
"""

import shutil
import subprocess
import sys
from pathlib import Path

import netCDF4
import numpy as np
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1] / "mcs_environment" / "monthly"
sys.path.insert(0, str(ROOT))

from envmonthly.climo import build_climatology  # noqa: E402
from envmonthly.config import load_dataset  # noqa: E402
from envmonthly.native import process_month  # noqa: E402
from envmonthly.ncotools import DEFAULT_NCO_BIN, check_weights, make_grid_file, make_weights  # noqa: E402
from envmonthly.regrid import Remapper, regrid_month, target_grid_file  # noqa: E402
from envmonthly.writer import check_compression  # noqa: E402

HAS_NCO = (Path(DEFAULT_NCO_BIN) / "ncremap").exists() or shutil.which("ncremap") is not None
needs_nco = pytest.mark.skipif(not HAS_NCO, reason="NCO / ESMF programs not found")

# 5 degree source grid with latitude points on the poles (like ERA5), 10 degree target grid
SRC_LAT = np.linspace(90.0, -90.0, 37)         # descending, as ERA5 stores it
SRC_LON = np.arange(0.0, 360.0, 5.0)
HOURS_2007_01 = 937944.0                       # hours since 1900-01-01 of 2007-01-01 00:00
HOURS_2007_02 = HOURS_2007_01 + 744.0
LEVELS = [500.0, 850.0, 1000.0]


def _write_yaml(path, data):
    """Write a dictionary as YAML."""
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


def _latlon_file(path, name, data, time_hours, level=None, units=""):
    """Write a lat-lon file with one variable ``name``: data shaped (time, [level,] lat, lon), time in hours since 1900-01-01."""
    with netCDF4.Dataset(path, "w") as ds:
        ds.createDimension("time", len(time_hours))
        ds.createDimension("latitude", SRC_LAT.size)
        ds.createDimension("longitude", SRC_LON.size)
        dims = ["time", "latitude", "longitude"]
        if level is not None:
            ds.createDimension("level", len(level))
            ds.createVariable("level", "f8", ("level",))[:] = level
            dims.insert(1, "level")
        t = ds.createVariable("time", "f8", ("time",))
        t.units, t.calendar = "hours since 1900-01-01 00:00:00", "gregorian"
        t[:] = time_hours
        ds.createVariable("latitude", "f8", ("latitude",))[:] = SRC_LAT
        ds.createVariable("longitude", "f8", ("longitude",))[:] = SRC_LON
        v = ds.createVariable(name, "f4", dims, fill_value=np.float32(9.999e20))
        v.units = units
        v[:] = data


def _era5_like_inputs(folder):
    """Synthetic inputs of two months: Q on 3 levels (monthly), SP and TCWV hourly in two pieces (2 records each)."""
    lat2d = SRC_LAT[:, None] * np.ones(SRC_LON.size)[None, :]
    for month, t0 in ((1, HOURS_2007_01), (2, HOURS_2007_02)):
        scale = 1.0 + 0.1 * month
        # Q: (k + 1) * 1e-3 * (2 + cos(lat)) * scale, for the levels 500, 850, 1000 hPa
        q = np.stack([(k + 1) * 1e-3 * (2.0 + np.cos(np.deg2rad(lat2d))) * scale for k in range(3)])[None]
        _latlon_file(folder / f"q_2007{month:02d}.nc", "Q", q, [t0], level=LEVELS, units="kg kg**-1")
        # SP: 100000 Pa, 80000 Pa poleward of 80 degrees (below the 850 hPa level); records offset by 0, 100, 200, 300 Pa
        sp0 = np.where(np.abs(lat2d) > 80.0, 80000.0, 100000.0)
        for piece, offsets in (("a", (0.0, 100.0)), ("b", (200.0, 300.0))):
            hours = [t0 + (0 if piece == "a" else 2) + i for i in range(2)]
            _latlon_file(folder / f"sp_2007{month:02d}_{piece}.nc", "SP", np.stack([sp0 + o for o in offsets]), hours, units="Pa")
            tc = np.stack([30.0 * np.cos(np.deg2rad(lat2d)) * scale + o / 100.0 for o in offsets])
            _latlon_file(folder / f"tcwv_2007{month:02d}_{piece}.nc", "TCWV", tc, hours, units="kg m**-2")


def _era5_like_config(tmp, expected_records_per_day=0.125):
    """Write grids.yaml, variables.yaml and the dataset config of the ERA5-like test dataset; returns the dataset config path."""
    tmp.mkdir(exist_ok=True)
    (tmp / "variables.yaml").write_text((ROOT / "config" / "variables.yaml").read_text())
    _write_yaml(tmp / "grids.yaml", {
        "data_root": str(tmp / "data"), "maps_dir": str(tmp / "maps"), "method": "bilinear", "weight_options": "--no_log --ignore_unmapped --netcdf4",
        "valid_weight_fraction": 0.5, "deflate": 4,
        "target": {"name": "tgt", "generate": "latlon=18,36#lat_typ=uni#lon_typ=180_wst"},
        "sources": {"tiny": {"generate": "latlon=37,72#lat_typ=cap#lon_typ=Grn_ctr"}}})
    inp = tmp / "in"
    inp.mkdir(exist_ok=True)
    _era5_like_inputs(inp)
    return _write_yaml(tmp / "tiny.yaml", {
        "name": "tiny", "label": "tiny ERA5-like", "period": {"start": "2007-01", "end": "2007-02"}, "calendar": "standard", "grid": "tiny",
        "streams": {
            "q": {"root": str(inp), "pattern": "q_{yyyy}{mm}.nc", "layout": "latlon",
                  "plev_select": {"hus850": {"raw": "Q", "plev_hpa": 850, "mask_below_ground": "ps"}}},
            "sp": {"root": str(inp), "pattern": "sp_{yyyy}{mm}_*.nc", "layout": "latlon", "expected_records_per_day": expected_records_per_day,
                   "direct": {"ps": {"raw": "SP"}}},
            "tcwv": {"root": str(inp), "pattern": "tcwv_{yyyy}{mm}_*.nc", "layout": "latlon", "direct": {"prw": {"raw": "TCWV"}}}}})


@pytest.fixture(scope="module")
def era5_like(tmp_path_factory):
    """The ERA5-like dataset with its grids and weights made (needs NCO); returns the loaded Dataset."""
    cfg = _era5_like_config(tmp_path_factory.mktemp("era5like"))
    ds = load_dataset(cfg)
    c = ds.common
    dst = make_grid_file(c.target["generate"], Path(c.maps_dir) / "grid_tgt.nc")
    src = make_grid_file(c.sources["tiny"]["generate"], Path(c.maps_dir) / "grid_tiny.nc")
    make_weights(src, dst, ds.map_path(), c.method, c.weight_options)
    return ds


# ---------------------------------------------------------------------------------------------------------------------------------
# step 0: weights
# ---------------------------------------------------------------------------------------------------------------------------------
@needs_nco
def test_weights_pass_their_checks(era5_like):
    """The generated bilinear weights cover the globe, the row sums are 1, nothing is unmapped."""
    c = era5_like.common
    problems, info = check_weights(era5_like.map_path(), Path(c.maps_dir) / "grid_tiny.nc", Path(c.maps_dir) / "grid_tgt.nc")
    assert problems == [] and "0 without weights" in info[0]


# ---------------------------------------------------------------------------------------------------------------------------------
# step 1 -> 3 on the ERA5-like data
# ---------------------------------------------------------------------------------------------------------------------------------
@needs_nco
def test_native_file_values_masks_and_attributes(era5_like):
    """Level pick, mean over the records of several files, below-ground mask, units, attributes, compression, ascending latitude."""
    res = process_month(era5_like, 2007, 1)
    assert res.status == "written", res.message
    with netCDF4.Dataset(era5_like.native_path(2007, 1)) as ds:
        assert ds["lat"][:].tolist() == sorted(ds["lat"][:].tolist()) and ds["lat"][0] == -90.0
        lat = ds["lat"][:][:, None] * np.ones(SRC_LON.size)[None, :]
        # hus850 is the level index 1: 2e-3 * (2 + cos(lat)) * 1.1, NaN where the mean surface pressure (80150 Pa) is below 850 hPa
        hus = np.ma.filled(ds["hus850"][0], np.nan)
        assert np.allclose(hus[np.abs(lat) <= 80], 2e-3 * (2.0 + np.cos(np.deg2rad(lat[np.abs(lat) <= 80]))) * 1.1, rtol=1e-6)
        assert np.isnan(hus[np.abs(lat) > 80]).all()
        # ps: mean of the offsets 0, 100, 200, 300 = 150 Pa on top of the base pressure; prw: mean of the offsets / 100 = 1.5
        ps = ds["ps"][0]
        assert np.allclose(ps[np.abs(lat) <= 80], 100150.0) and np.allclose(ps[np.abs(lat) > 80], 80150.0)
        assert np.allclose(ds["prw"][0], 30.0 * np.cos(np.deg2rad(lat)) * 1.1 + 1.5, atol=1e-4)
        assert ds["hus850"].units == "1" and ds["ps"].units == "Pa" and ds["prw"].standard_name == "atmosphere_mass_content_of_water_vapor"
        assert ds["ps"].n_records == 4 and "no vertical interpolation" in ds["hus850"].method and ds["hus850"].masked_below_ground_with == "ps"
        assert ds["time"][0] == pytest.approx(0.5 * (ds["time_bnds"][0, 0] + ds["time_bnds"][0, 1])) and ds["time"].calendar == "standard"
    assert check_compression(era5_like.native_path(2007, 1), names=era5_like.output_names()) == []


@needs_nco
def test_regrid_climatology_and_a_second_run(era5_like):
    """Step 2 and 3 on the two months: values near the analytic fields, polar rows masked, climatology time axis, nothing is redone."""
    for month in (1, 2):
        assert process_month(era5_like, 2007, month).status in ("written", "skipped")
        remapper = Remapper(era5_like.map_path(), target_grid_file(era5_like), era5_like.common.valid_weight_fraction)
        assert regrid_month(era5_like, remapper, 2007, month).status == "written"
    assert regrid_month(era5_like, remapper, 2007, 2).status == "skipped"                         # an existing file is not redone
    with netCDF4.Dataset(era5_like.latlon_path(2007, 1)) as ds:
        lat = ds["lat"][:]
        assert lat.size == 18 and ds["lon"][0] == -175.0 and lat[0] == -85.0
        hus = np.ma.filled(ds["hus850"][0], np.nan)
        inner = np.abs(lat) <= 55
        # The target cell centres are source grid nodes (5 degree source, 10 degree target shifted by half a cell): bilinear is exact there
        assert np.allclose(hus[inner], (2e-3 * (2.0 + np.cos(np.deg2rad(lat[inner]))) * 1.1)[:, None] * np.ones(36), atol=1e-6)
        assert np.isnan(hus[np.abs(lat) >= 85]).all() and np.isfinite(hus[np.abs(lat) <= 75]).all()
        prw = ds["prw"][0]
        assert np.allclose(prw, (30.0 * np.cos(np.deg2rad(lat)) * 1.1 + 1.5)[:, None] * np.ones(36), atol=1e-3)
    assert check_compression(era5_like.latlon_path(2007, 1), names=era5_like.output_names()) == []
    # Climatology of the two months: January and February have one file, the other calendar months are empty (NaN)
    result = build_climatology(era5_like, (2007, 1), (2007, 2))
    assert result["nmonths"] == [1, 1] + [0] * 10 and result["missing"] == []
    with netCDF4.Dataset(result["path"]) as c, netCDF4.Dataset(era5_like.latlon_path(2007, 2)) as feb:
        times = netCDF4.num2date(c["time"][:], c["time"].units, c["time"].calendar)
        assert [t.year for t in times] == [2000] * 12 and [t.month for t in times] == list(range(1, 13))
        assert c["month"][:].tolist() == list(range(1, 13)) and c["nmonths"][:].tolist() == result["nmonths"]
        assert np.allclose(np.ma.filled(c["prw"][1], np.nan), np.ma.filled(feb["prw"][0], np.nan), equal_nan=True)
        assert np.ma.getmaskarray(c["prw"][5]).all()
    assert check_compression(result["path"], names=era5_like.output_names()) == []


def _check_script(config):
    """Run check_env_monthly.py on a dataset config; returns (exit code, output text)."""
    proc = subprocess.run([sys.executable, str(ROOT / "check_env_monthly.py"), "--config", str(config)], capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


@needs_nco
def test_check_script_passes_flags_an_unexpected_gap_and_accepts_a_declared_one(era5_like):
    """check_env_monthly.py: all good -> exit 0; a missing 1 degree file -> exit 1 naming the month; declared in known_missing_months -> exit 0."""
    remapper = Remapper(era5_like.map_path(), target_grid_file(era5_like), era5_like.common.valid_weight_fraction)
    for month in (1, 2):
        process_month(era5_like, 2007, month)
        regrid_month(era5_like, remapper, 2007, month)
    build_climatology(era5_like, (2007, 1), (2007, 2))
    code, text = _check_script(era5_like.path)
    assert code == 0 and "all checks passed" in text, text
    feb = era5_like.latlon_path(2007, 2)
    feb.rename(feb.with_suffix(".saved"))
    try:
        code, text = _check_script(era5_like.path)
        assert code == 1 and "1 degree: 1 of 2 monthly files are missing: 2007-02" in text, text
        # The same config with the month declared as a known gap
        declared = Path(era5_like.path).with_name("tiny_gap.yaml")
        raw = yaml.safe_load(Path(era5_like.path).read_text())
        raw["known_missing_months"] = ["2007-02"]
        _write_yaml(declared, raw)
        code, text = _check_script(declared)
        assert code == 0 and "1 known gaps" in text, text
    finally:
        feb.with_suffix(".saved").rename(feb)


def test_missing_month_wrong_month_and_incomplete_records_are_failed_not_crashes(tmp_path):
    """A month without files, a file of another month, and hourly inputs with too few records come back as ``failed`` with the reason."""
    cfg = _era5_like_config(tmp_path / "a")
    ds = load_dataset(cfg)
    res = process_month(ds, 2007, 3)                                    # no files of March
    assert res.status == "failed" and "no file matches" in res.message
    # The February Q file stamped with the first hour of January: refused
    inp = tmp_path / "a" / "in"
    shutil.copy(inp / "q_200701.nc", inp / "q_200703.nc")
    for piece in "ab":
        shutil.copy(inp / f"sp_200702_{piece}.nc", inp / f"sp_200703_{piece}.nc")
        shutil.copy(inp / f"tcwv_200702_{piece}.nc", inp / f"tcwv_200703_{piece}.nc")
    res = process_month(ds, 2007, 3)
    assert res.status == "failed" and "not inside 2007-03" in res.message
    # Four records where 24 per day are expected: more than 5 % missing
    strict = load_dataset(_era5_like_config(tmp_path / "b", expected_records_per_day=24))
    res = process_month(strict, 2007, 1)
    assert res.status == "failed" and "only 4 of 744" in res.message
    assert not strict.native_path(2007, 1).exists()


# ---------------------------------------------------------------------------------------------------------------------------------
# model-like ncol files
# ---------------------------------------------------------------------------------------------------------------------------------
N_COL, N_LEV = 4, 12


def _model_dataset(tmp, hybrid):
    """A SCREAM-like (stored pressure, (time, ncol, lev)) or E3SM-like (hybrid, (time, lev, ncol)) dataset of one month, noleap calendar.

    The humidity field is 0.01 * ln(p / 1e4) (linear in ln p), the relative humidity (a fraction in the SCREAM-like file, per cent in the
    E3SM-like one) is 0.5 at all levels, and the last column has a surface pressure of 78000 Pa (850 hPa below the ground). Returns the Dataset."""
    tmp.mkdir(exist_ok=True)
    (tmp / "variables.yaml").write_text((ROOT / "config" / "variables.yaml").read_text())
    _write_yaml(tmp / "grids.yaml", {"data_root": str(tmp / "data"), "maps_dir": str(tmp / "maps"), "method": "bilinear",
                                     "target": {"name": "tgt", "generate": "latlon=18,36#lat_typ=uni#lon_typ=180_wst"},
                                     "sources": {"ne30pg2": {"scrip": "/none.nc"}}})
    ps = np.array([101000.0, 99000.0, 95000.0, 78000.0])
    b = np.linspace(0.01, 1.0, N_LEV)
    a = np.zeros(N_LEV)
    p = a[:, None] * 1e5 + b[:, None] * ps[None, :]                                 # (lev, ncol)
    qv = 0.01 * np.log(p / 1e4)
    with netCDF4.Dataset(tmp / "model_199501.nc", "w") as ds:
        ds.createDimension("time", 1)
        ds.createDimension("nbnd", 2)
        ds.createDimension("ncol", N_COL)
        ds.createDimension("lev", N_LEV)
        t = ds.createVariable("time", "f8", ("time",))
        t.units, t.calendar, t.bounds = "days since 1994-10-01 00:00:00", "noleap", "time_bnds"
        t[:] = 123.0
        ds.createVariable("time_bnds", "f8", ("time", "nbnd"))[:] = [[92.0, 123.0]]
        for name, vals in (("lat", [-30.0, -10.0, 10.0, 30.0]), ("lon", [0.0, 90.0, 180.0, 270.0])):
            ds.createVariable(name, "f8", ("ncol",))[:] = vals
        order = ("time", "lev", "ncol") if hybrid else ("time", "ncol", "lev")
        arr = (lambda x: x[None]) if hybrid else (lambda x: x.T[None])
        pairs = [("Q" if hybrid else "qv", qv, "kg/kg"), ("RELHUM" if hybrid else "RelativeHumidity", np.full_like(qv, 50.0 if hybrid else 0.5), "percent" if hybrid else "1")]
        if not hybrid:
            pairs.append(("p_mid", p, "Pa"))
        for name, vals, units in pairs:
            v = ds.createVariable(name, "f4", order)
            v.units = units
            v[:] = arr(vals)
        for name, vals, units in (("TMQ" if hybrid else "VapWaterPath", [10.0, 20.0, 30.0, 40.0], "kg/m2"), ("PS" if hybrid else "ps", ps, "Pa"),
                                  ("OMEGA500" if hybrid else "omega_at_500hPa", [0.1, -0.1, 0.2, -0.2], "Pa/s")):
            v = ds.createVariable(name, "f4", ("time", "ncol"))
            v.units = units
            v[0] = vals
        if hybrid:
            ds.createVariable("hyam", "f8", ("lev",))[:] = a
            ds.createVariable("hybm", "f8", ("lev",))[:] = b
            ds.createVariable("P0", "f8", ())[...] = 1e5
    pressure = {"hybrid": {"ps": "PS", "a": "hyam", "b": "hybm", "p0": "P0"}} if hybrid else {"field": "p_mid"}
    raw = (lambda e3sm, scream: e3sm if hybrid else scream)
    cfg = _write_yaml(tmp / "model.yaml", {
        "name": "model", "label": "model-like", "period": {"start": "1995-01", "end": "1995-01"}, "calendar": "noleap", "grid": "ne30pg2",
        "streams": {"m": {"root": str(tmp), "pattern": "model_{yyyy}{mm}.nc", "layout": "ncol", "pressure": pressure,
                          "direct": {"prw": {"raw": raw("TMQ", "VapWaterPath")}, "ps": {"raw": raw("PS", "ps")}, "wap500": {"raw": raw("OMEGA500", "omega_at_500hPa")}},
                          "interpolate": {"hus850": {"raw": raw("Q", "qv"), "plev_hpa": 850},
                                          "hur500": ({"raw": "RELHUM", "plev_hpa": 500} if hybrid else {"raw": "RelativeHumidity", "plev_hpa": 500, "scale": 100.0})}}}})
    return load_dataset(cfg)


@pytest.mark.parametrize("hybrid", [False, True], ids=["scream-like", "e3sm-like"])
def test_ncol_model_month_is_interpolated_exactly(tmp_path, hybrid):
    """Both layouts: direct fields as stored, interpolated fields exact (they are linear in ln p), 850 hPa NaN below the ground, RH in per cent."""
    ds = _model_dataset(tmp_path, hybrid)
    res = process_month(ds, 1995, 1)
    assert res.status == "written", res.message
    with netCDF4.Dataset(ds.native_path(1995, 1)) as out:
        hus = np.ma.filled(out["hus850"][0], np.nan)
        assert np.allclose(hus[:3], 0.01 * np.log(85000.0 / 1e4), rtol=1e-6) and np.isnan(hus[3])      # column 3: lowest level 78000 Pa
        assert np.allclose(out["hur500"][0], 50.0) and out["hur500"].units == "%"
        assert np.allclose(out["prw"][0], [10, 20, 30, 40]) and np.allclose(out["wap500"][0], [0.1, -0.1, 0.2, -0.2])
        assert out["lat"][:].tolist() == [-30.0, -10.0, 10.0, 30.0]
        assert "linear in ln(p)" in out["hus850"].method and out["hus850"].source_variable == ("Q" if hybrid else "qv")
        assert out["time"][0] == pytest.approx(0.5 * (out["time_bnds"][0, 0] + out["time_bnds"][0, 1]))
    assert check_compression(ds.native_path(1995, 1), names=ds.output_names()) == []


def test_ncol_model_month_of_the_wrong_name_is_refused(tmp_path):
    """A file whose averaging window is another month than the file name says is refused (the off-by-one month guard)."""
    ds = _model_dataset(tmp_path, hybrid=False)
    (tmp_path / "model_199502.nc").write_bytes((tmp_path / "model_199501.nc").read_bytes())          # January data under the February name
    res = process_month(load_dataset(tmp_path / "model.yaml"), 1995, 2)
    assert res.status == "failed" and "starts" in res.message
