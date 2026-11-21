"""Tests of the building blocks of ``mcs_environment`` (derive, grid, tracks, file index, outputs, configuration).

Run from the scream folder:  python -m pytest tests/test_mcs_env_core.py
"""

import os
import sys
import time
from pathlib import Path

import netCDF4
import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1] / "mcs_environment"
sys.path.insert(0, str(ROOT))

from mcsenv import derive, outputs  # noqa: E402
from mcsenv.config import ConfigError, load_config, validate_source  # noqa: E402
from mcsenv.fileindex import FileIndex, days_from_civil, nearest_time, times_to_epoch_s  # noqa: E402
from mcsenv.grid import GridSearch, haversine_km, weighted_mean  # noqa: E402
from mcsenv.modelcal import leap_day_labels_present, to_labels, to_model_axis  # noqa: E402
from mcsenv.tracks import build_samples  # noqa: E402

H = 3600


# ---------------------------------------------------------------------------------------------------------------------------------
# derive
# ---------------------------------------------------------------------------------------------------------------------------------
def test_saturation_values_are_physical():
    """es(300 K) is about 3.5 kPa and qsat(300 K, 1000 hPa) about 22 g/kg."""
    assert derive.esat_liquid(300.0) == pytest.approx(3536.0, rel=0.01)
    assert derive.qsat_liquid(300.0, 100000.0) == pytest.approx(0.0223, rel=0.02)


def test_q_rh_round_trip_and_nan():
    """q from RH and back gives the RH; NaN propagates."""
    t = np.array([280.0, 295.0, np.nan])
    rh = np.array([0.4, 0.9, 0.5])
    q = derive.q_from_rh(rh, t, 85000.0)
    back = derive.rh_from_q(q, t, 85000.0)
    assert np.allclose(back[:2], rh[:2]) and np.isnan(back[2])


def test_compute_variable_rules():
    """from + scale, sum, q_from_rh with percent input, rh_from_q + scale."""
    raw = {"a": np.array([1.0, 2.0]), "b": np.array([0.5, np.nan]), "t": np.array([290.0, 290.0]), "r": np.array([50.0, 100.0])}
    assert np.allclose(derive.compute_variable({"from": "a", "scale": 100.0}, raw), [100.0, 200.0])
    out = derive.compute_variable({"derive": "sum", "inputs": ["a", "b"], "scale": 2.0}, raw)
    assert out[0] == 3.0 and np.isnan(out[1])
    q = derive.compute_variable({"derive": "q_from_rh", "inputs": {"rh": "r", "t": "t"}, "level_hpa": 850, "rh_units": "percent"}, raw)
    assert q[1] == pytest.approx(derive.qsat_liquid(290.0, 85000.0)) and q[0] == pytest.approx(q[1] / 2)
    rh = derive.compute_variable({"derive": "rh_from_q", "inputs": {"q": "a", "t": "t"}, "level_hpa": 500, "scale": 100.0}, {"a": q, "t": raw["t"]})
    assert derive.raw_names({"derive": "q_from_rh", "inputs": {"rh": "r", "t": "t"}}) == ["r", "t"]
    with pytest.raises(ValueError):
        derive.compute_variable({"derive": "q_from_rh", "inputs": {"rh": "r", "t": "t"}}, raw)  # no level_hpa
    assert rh.shape == (2,)


def test_mask_below_ground():
    """Cells whose surface pressure is below the level (or unknown) become NaN."""
    out = derive.mask_below_ground(np.array([1.0, 2.0, 3.0, 4.0]), np.array([90000.0, 84000.0, 85000.0, np.nan]), 850)
    assert out[0] == 1.0 and np.isnan(out[1]) and out[2] == 3.0 and np.isnan(out[3])


# ---------------------------------------------------------------------------------------------------------------------------------
# grid
# ---------------------------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def sphere_grid():
    """A random grid of 3000 cells with random areas, and its ``GridSearch``."""
    rng = np.random.default_rng(1)
    n = 3000
    lat = np.degrees(np.arcsin(rng.uniform(-1, 1, n)))
    lon = rng.uniform(0, 360, n)
    area = rng.uniform(0.5, 1.5, n)
    return lat, lon, area, GridSearch(lat, lon, area)


def test_circle_membership_matches_haversine(sphere_grid):
    """Cells in the circles equal the brute-force haversine selection, also near the poles, for unwrapped longitudes and a centre on a cell centre."""
    lat, lon, _area, grid = sphere_grid
    rng = np.random.default_rng(2)
    clat = np.r_[rng.uniform(-90, 90, 25), 89.95, -89.95, lat[11]]
    clon = np.r_[rng.uniform(-200, 210, 25), 10.0, 200.0, lon[11] + 360.0]
    diameters = [200, 400, 600, 2500]
    matrices, n_cells = grid.circle_weights(clat, clon, diameters, empty_circle="nan")
    for k, d in enumerate(diameters):
        for i in range(clat.size):
            inside = haversine_km(clat[i], clon[i], lat, lon) <= d / 2
            got = np.zeros(lat.size, dtype=bool)
            got[matrices[k][i].indices] = True
            assert (inside == got).all() and n_cells[i, k] == inside.sum()
    assert n_cells[-1, 0] >= 1                                        # the centre that sits on a cell centre contains that cell (distance exactly 0)


def test_weighted_mean_with_nan_cells(sphere_grid):
    """The mean uses only valid cells, weighted by area; the valid fraction is the valid weight over the total weight."""
    lat, lon, area, grid = sphere_grid
    values = np.random.default_rng(3).normal(size=(lat.size, 2))
    values[::3, 0] = np.nan
    matrices, _ = grid.circle_weights([10.0, -40.0], [100.0, 300.0], [1500])
    mean, frac = weighted_mean(matrices[0], values)
    for i, (la, lo) in enumerate([(10.0, 100.0), (-40.0, 300.0)]):
        inside = haversine_km(la, lo, lat, lon) <= 750
        v, w = values[inside, 0], area[inside]
        ok = np.isfinite(v)
        assert mean[i, 0] == pytest.approx((v[ok] * w[ok]).sum() / w[ok].sum())
        assert frac[i, 0] == pytest.approx(w[ok].sum() / w.sum())
        assert mean[i, 1] == pytest.approx((values[inside, 1] * w).sum() / w.sum()) and frac[i, 1] == pytest.approx(1.0)


def test_empty_circle_rules(sphere_grid):
    """A circle without a cell centre takes the nearest cell by default and stays empty with ``nan``; an all-NaN circle gives NaN."""
    _lat, _lon, _area, grid = sphere_grid
    _m, n_cells = grid.circle_weights([0.0], [0.0], [10], empty_circle="nearest_cell")
    assert n_cells[0, 0] == 1
    matrices, n_cells = grid.circle_weights([0.0], [0.0], [10], empty_circle="nan")
    assert n_cells[0, 0] == 0
    mean, frac = weighted_mean(matrices[0], np.ones((grid.n_cells, 1)))
    assert np.isnan(mean[0, 0]) and np.isnan(frac[0, 0])


def test_grid_rejects_radians_like_latitudes():
    """A latitude beyond 90 degrees is an error (wrong units)."""
    with pytest.raises(ValueError):
        GridSearch([95.0, 0.0], [0.0, 1.0])


# ---------------------------------------------------------------------------------------------------------------------------------
# tracks: the nominal relative-time grid
# ---------------------------------------------------------------------------------------------------------------------------------
def make_track(period, local, start_s, hours, drop=(), nan=(), lat0=10.0):
    """One hourly track: rows at ``start_s + h * 3600`` for h in range(hours) except ``drop``; NaN positions for the hours in ``nan``."""
    rows = [dict(period=period, local_track=local, t=start_s + h * H, lat=np.nan if h in nan else lat0 + h, lon=100.0 + 10 * h)
            for h in range(hours) if h not in drop]
    return pd.DataFrame(rows)


@pytest.mark.parametrize("step", [1, 3, 6])
@pytest.mark.parametrize("half_hour", [0, 1800])
def test_every_track_is_on_the_same_relative_grid(step, half_hour):
    """Tracks that start at every hour of the day (:00 or :30) get offsets that are exact multiples of the step, a row at 0 and at -24 h."""
    base = int(pd.Timestamp("2001-03-04", tz="UTC").timestamp()) + half_hour
    tracks = pd.concat([make_track("2001", h + 1, base + h * H, 5 + h % 7) for h in range(24)], ignore_index=True)
    samples = build_samples(tracks, step, 24)
    off = samples.time_offset_hours
    assert (np.mod(off, step) == 0).all()
    for local in range(1, 25):
        mine = off[samples.local_track == local]
        assert mine.min() == -24 and 0 in mine and (np.diff(mine) == step).all()
    # With a regular environment axis of the same step but any phase the snapshot shift is within half a step and constant per track
    axis = np.arange(base - 3 * 86400, base + 3 * 86400, step * H) + 11 * H % (step * H)
    row, shift = nearest_time(axis, samples.data_time, step * H)
    assert (row >= 0).all() and (shift >= -step * H / 2).all() and (shift < step * H / 2).all()
    for local in range(1, 25):
        assert np.unique(shift[samples.local_track == local]).size == 1


def test_track_point_rules():
    """Pre-start rows use the start position; a missing hour uses the nearest existing point (ties: earlier); NaN positions are skipped."""
    t0 = int(pd.Timestamp("2001-03-04 14:00", tz="UTC").timestamp())
    tracks = pd.concat([
        make_track("2001", 1, t0, 8),                                  # complete
        make_track("2001", 2, t0, 8, drop=(3,)),                       # the 3-h point (t0 + 3 h) is missing: nearest existing points are +2 h and +4 h
        make_track("2001", 3, t0, 6, nan=(0,)),                        # first position is NaN: the start position is the first valid point
        make_track("2001", 4, t0, 3, nan=(0, 1, 2)),                   # no valid position at all: no samples
    ], ignore_index=True)
    s = build_samples(tracks, 3, 24)
    assert s.n_tracks == 4 and s.n_tracks_skipped == 1 and s.n_rows_dropped == 4
    assert 4 not in set(s.local_track)
    one = {int(k): (la, tt, dt) for k, la, tt, dt in zip(s.k[s.local_track == 1], s.center_lat[s.local_track == 1], s.track_time[s.local_track == 1],
                                                        s.track_dt_hours[s.local_track == 1])}
    assert one[-8] == (10.0, t0, 0.0) and one[0] == (10.0, t0, 0.0) and one[1] == (13.0, t0 + 3 * H, 0.0)       # pre-start rows: the start position
    two = {int(k): (tt - t0) / H for k, tt in zip(s.k[s.local_track == 2], s.track_time[s.local_track == 2])}
    assert two[1] == 2.0 and (s.track_dt_hours[(s.local_track == 2) & (s.k == 1)] == 1.0).all()                  # tie between +2 and +4 h -> earlier (+2 h)
    three = {int(k): (tt - t0) / H for k, tt in zip(s.k[s.local_track == 3], s.track_time[s.local_track == 3])}
    assert three[0] == 1.0 and three[-1] == 1.0                                                                   # first valid point at +1 h


def test_track_keys_must_be_unique_and_sorted():
    """Rows of one track must be contiguous and increasing."""
    a = make_track("2001", 1, 1000000, 4)
    b = make_track("2001", 2, 1000000, 4)
    with pytest.raises(ValueError):
        build_samples(pd.concat([a, b, a], ignore_index=True), 3, 24)
    with pytest.raises(ValueError):
        build_samples(a.iloc[::-1].reset_index(drop=True), 3, 24)
    with pytest.raises(ValueError):
        build_samples(a, 5, 24)                                         # 24 h is not a multiple of 5 h


def test_nearest_time_rules():
    """Ties go to the earlier time, a shift of exactly +step/2 is rejected, frames farther than half a step are missing."""
    axis = np.array([0, 3, 6, 12]) * H                                 # the 9 h frame is missing
    row, shift = nearest_time(axis, np.array([1.5, 4.5, 7.5, 9, 10.5, 13.5, -1.4, -1.6]) * H, 3 * H)
    # 1.5 h: tie between 0 and 3 h -> 0 (shift -1.5 h, accepted); 4.5 h: tie 3 and 6 -> 3; 7.5 h: 6 h (shift -1.5 h);
    # 9 h: 6 h and 12 h are both 3 h away -> the earlier one, rejected (more than half a step); 10.5 h: the 12 h frame is +1.5 h away = +step/2 -> rejected;
    # 13.5 h: 12 h at -1.5 h -> accepted; -1.4 h: 0 at +1.4 h -> accepted; -1.6 h: 0 at +1.6 h -> rejected
    assert list(row) == [0, 1, 2, -1, -1, 3, 0, -1]
    assert shift[0] == -1.5 * H and shift[1] == -1.5 * H and shift[4] == 1.5 * H


# ---------------------------------------------------------------------------------------------------------------------------------
# file index
# ---------------------------------------------------------------------------------------------------------------------------------
def write_times_file(path, epoch_times, calendar="noleap", base="2000-01-01 00:00:00", unit="days", fmt="NETCDF3_CLASSIC"):
    """A netCDF file with only a time axis (``epoch_times`` in epoch seconds; none = a file without records)."""
    base_s = pd.Timestamp(base, tz="UTC").timestamp()
    div = {"days": 86400.0, "hours": 3600.0}[unit]
    with netCDF4.Dataset(path, "w", format=fmt) as ds:
        ds.createDimension("time", None)
        var = ds.createVariable("time", "f8", ("time",))
        var.units, var.calendar = f"{unit} since {base}", calendar
        for i, t in enumerate(epoch_times):
            var[i] = (t - base_s) / div


def test_days_from_civil_and_calendar_conversion():
    """days_from_civil equals numpy for random dates; float day values of an hourly noleap axis convert to exact seconds; ERA5-style hours work."""
    rng = np.random.default_rng(4)
    y, m, d = rng.integers(1900, 2100, 500), rng.integers(1, 13, 500), rng.integers(1, 29, 500)
    expected = np.array([np.datetime64(f"{a:04d}-{b:02d}-{c:02d}", "D").astype(np.int64) for a, b, c in zip(y, m, d)])
    assert (days_from_civil(y, m, d) == expected).all()
    hourly = 1.0 + np.arange(24) / 24.0                                 # days since 2009-01-01, hourly (float64 fractions like 1.0416666666666667)
    got = times_to_epoch_s(hourly, "days since 2009-01-01 00:00:00", "noleap")
    assert (np.diff(got) == 3600).all() and got[0] == int(pd.Timestamp("2009-01-02", tz="UTC").timestamp())
    assert times_to_epoch_s([1052000.0], "hours since 1900-01-01 00:00:00", "standard")[0] == int(pd.Timestamp("1900-01-01", tz="UTC").timestamp()) + 1052000 * H
    # a noleap year has no 29 February: day 59 after 1 January is 1 March
    assert times_to_epoch_s([59.0], "days since 2001-01-01 00:00:00", "noleap")[0] == int(pd.Timestamp("2001-03-01", tz="UTC").timestamp())
    with pytest.raises(NotImplementedError):
        times_to_epoch_s([1.0], "days since 2001-01-01", "360_day")


def build_layout(tmp_path):
    """Files of one stream with the quirks of the SCREAM output: shifted starts, an empty file, a backup copy and a restart file."""
    day0 = int(pd.Timestamp("2000-01-01", tz="UTC").timestamp())
    d = tmp_path / "stream"
    d.mkdir()
    # Day 1 starts at 00:00 (records 00..21), later days start at 03:00 (records 03..24 = next day 00:00), day 4 is an empty file
    write_times_file(d / "x.INSTANT.nhours_x3.2000-01-01-00000.nc", [day0 + h * H for h in range(0, 24, 3)])
    write_times_file(d / "x.INSTANT.nhours_x3.2000-01-02-10800.nc", [day0 + 86400 + h * H for h in range(3, 27, 3)])
    write_times_file(d / "x.INSTANT.nhours_x3.2000-01-03-10800.nc", [day0 + 2 * 86400 + h * H for h in range(3, 27, 3)])
    write_times_file(d / "x.INSTANT.nhours_x3.2000-01-04-10800.nc", [])
    write_times_file(d / "x.INSTANT.nhours_x3.2000-01-05-10800.nc", [day0 + 4 * 86400 + h * H for h in range(3, 27, 3)])
    write_times_file(d / "x.INSTANT.nhours_x3.2000-01-02-10800.nc~", [day0 + 999 * H])               # backup copy: never matched
    write_times_file(d / "x.rhist.INSTANT.ndays_x5.2000-01-05-00000.nc", [day0 + 777 * H])            # restart file: never matched
    return d, day0


def test_file_index_layouts_cache_and_lookup(tmp_path):
    """Any layout becomes one time axis; empty files and backups are handled; the cache re-reads only changed files; lookups are exact."""
    d, day0 = build_layout(tmp_path)
    cache = str(tmp_path / "index.pkl")
    index = FileIndex.build(str(d), "x.INSTANT.nhours_x3.????-??-??-?????.nc", cache_path=cache)
    assert index.step_s == 3 * H and len(index.files) == 5 and len(index.empty_files) == 1 and index.n_duplicates == 0
    expected = sorted({day0 + h * H for h in range(0, 24, 3)} | {day0 + 86400 + h * H for h in range(3, 27, 3)} | {day0 + 2 * 86400 + h * H for h in range(3, 27, 3)}
                      | {day0 + 4 * 86400 + h * H for h in range(3, 27, 3)})
    assert list(index.times_s) == expected
    paths, recs = index.lookup(np.array([day0, day0 + 86400 + 3 * H, day0 + 3 * 86400 + 3 * H, day0 + 5 * 86400]))   # day 4 is empty and 1 Jan 5 00:00 exists in file 4
    assert os.path.basename(paths[0]).startswith("x.INSTANT.nhours_x3.2000-01-01") and recs[0] == 0
    assert os.path.basename(paths[1]).endswith("2000-01-02-10800.nc") and recs[1] == 0
    assert paths[2] == "" and recs[2] == -1                                                       # inside the empty file: missing
    assert os.path.basename(paths[3]).endswith("2000-01-04-10800.nc") is False and recs[3] >= 0 or recs[3] == -1
    # Cache: a second build reads nothing; touching one file re-reads exactly that file
    messages = []
    FileIndex.build(str(d), "x.INSTANT.nhours_x3.????-??-??-?????.nc", cache_path=cache, log=messages.append)
    assert "5 from cache, 0 to scan" in messages[0]
    time.sleep(0.02)
    write_times_file(d / "x.INSTANT.nhours_x3.2000-01-04-10800.nc", [day0 + 3 * 86400 + h * H for h in range(3, 27, 3)])    # the empty day is filled
    messages.clear()
    index2 = FileIndex.build(str(d), "x.INSTANT.nhours_x3.????-??-??-?????.nc", cache_path=cache, log=messages.append)
    assert "4 from cache, 1 to scan" in messages[0] and len(index2.empty_files) == 0 and index2.times_s.size == index.times_s.size + 8


def test_file_index_duplicates_unreadable_and_parallel_scan(tmp_path):
    """A time in two files keeps the file modified last; unreadable files are reported, not fatal; a pool scan equals the serial scan."""
    d = tmp_path / "dup"
    d.mkdir()
    base = int(pd.Timestamp("2000-01-01", tz="UTC").timestamp())
    write_times_file(d / "a_1.nc", [base, base + 3 * H])
    time.sleep(0.02)
    write_times_file(d / "a_2.nc", [base + 3 * H, base + 6 * H])
    (d / "a_3.nc").write_bytes(b"not a netcdf file")
    for k in range(10):
        write_times_file(d / f"b_{k:02d}.nc", [base + (10 + k) * H])
    serial = FileIndex.build(str(d), "a_*.nc")
    assert serial.n_duplicates == 1 and os.path.basename(serial.paths[1]) == "a_2.nc" and list(serial.unreadable) == [str(d / "a_3.nc")]
    s2, p2 = FileIndex.build(str(d), "b_*.nc", nproc=1), FileIndex.build(str(d), "b_*.nc", nproc=3)
    assert list(s2.times_s) == list(p2.times_s) and list(s2.paths) == list(p2.paths)
    with pytest.raises(FileNotFoundError):
        FileIndex.build(str(d), "nothing_*.nc")


# ---------------------------------------------------------------------------------------------------------------------------------
# outputs and configuration
# ---------------------------------------------------------------------------------------------------------------------------------
def test_output_round_trip_with_metadata(tmp_path):
    """Columns, units, long names and the file document survive a write and read; times are UTC milliseconds; compression is zstd."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    columns = {"period": pa.array(["2000", "2000"]).dictionary_encode(), "local_track": pa.array(np.array([1, 2], dtype=np.int64)),
               "diameter_km": pa.array(np.array([200, 400], dtype=np.int16)), "time_offset_hours": pa.array(np.array([-3.0, 0.0], dtype=np.float32)),
               "data_time": outputs.timestamp_array([946684800, 946695600]), "prw": pa.array(np.array([30.5, np.nan], dtype=np.float32))}
    meta = {"prw": {"units": "kg m-2", "long_name": "Total column water vapor"}, "diameter_km": {"units": "km"}}
    path = str(tmp_path / "o.parquet")
    outputs.write_mcs_env(path, columns, meta, {"source": "test", "n": 2})
    df = outputs.read_mcs_env(path)
    assert df.attrs["mcs_env"]["source"] == "test" and df.attrs["units"]["prw"] == "kg m-2" and df.attrs["long_name"]["prw"].startswith("Total")
    assert str(df["data_time"].dtype).startswith("datetime64[ms") and df["data_time"].iloc[0] == pd.Timestamp("2000-01-01", tz="UTC")
    assert pq.ParquetFile(path).metadata.row_group(0).column(0).compression == "ZSTD"
    frame = outputs.to_variable_frame(df, "prw")
    assert list(frame.columns) == ["track_id", "radius", "time_offset_hours", "data_time", "mean"] and frame["track_id"].iloc[0] == 2000 * 10_000_000 + 1


def test_real_configuration_is_valid():
    """Every source of config/sources.yaml loads and validates (paths, keys, variable specs)."""
    path = str(ROOT / "config" / "sources.yaml")
    for name in ("OBS", "3km_CTL", "3km_TUNE", "25km", "100km"):
        src = load_config(path, name)
        assert src["diameters_km"] == [200, 400, 600] and src["name"] == name
    with pytest.raises(ConfigError):
        load_config(path, "no_such_source")


def test_configuration_errors_are_reported():
    """Typical mistakes give a ConfigError that names the key."""
    good = load_config(str(ROOT / "config" / "sources.yaml"), "25km")
    for mutate, text in [
        (lambda s: s["streams"]["h1"].update(reader="nope"), "unknown reader"),
        (lambda s: s["streams"]["h1"]["variables"]["rh500"].pop("level_hpa"), "needs level_hpa"),
        (lambda s: s["streams"]["h1"]["variables"].update(prw2={"from": "X", "derive": "wrong"}), "unknown derive"),
        (lambda s: s.update(ps={"stream": "missing", "var": "PS"}), "ps must be"),
        (lambda s: s.update(diameters_km=[0, 100]), "diameters_km"),
    ]:
        import copy
        bad = copy.deepcopy(good)
        mutate(bad)
        with pytest.raises(ConfigError, match=text):
            validate_source(bad)


# ---------------------------------------------------------------------------------------------------------------------------------
# noleap calendars: the model axis has no 29 February
# ---------------------------------------------------------------------------------------------------------------------------------
def noleap_hour_labels(year, first_day, last_day):
    """Epoch-second labels of every hour from ``first_day`` 00:00 to ``last_day`` 23:00 (dates as ``MM-DD``) of a year, without 29 February."""
    labels = pd.date_range(f"{year}-{first_day}", f"{year}-{last_day} 23:00", freq="h", tz="UTC")
    labels = labels[~((labels.month == 2) & (labels.day == 29))]
    return labels.tz_localize(None).astype("datetime64[s]").astype(np.int64)


def test_model_axis_is_contiguous_over_the_leap_day_and_invertible():
    """Around 29 February the model axis advances by one hour per hour; the inverse returns the labels; the standard calendar is the identity."""
    labels = noleap_hour_labels(2000, "02-26", "03-03")                    # 2000 is a leap year
    axis = to_model_axis(labels, "noleap")
    assert (np.diff(axis) == H).all() and (np.diff(labels) == H).sum() == labels.size - 2 and (np.diff(labels) == 25 * H).sum() == 1
    assert (to_labels(axis, "noleap") == labels).all()
    assert (to_model_axis(labels, "standard") == labels).all() and (to_labels(axis, "standard") == axis).all()
    # Years without a leap day (1900, 2001, 2100) and with one (1996, 2000, 2004) over a century of random labels
    rng = np.random.default_rng(5)
    random_labels = pd.to_datetime(rng.integers(int(pd.Timestamp("1900-01-01").timestamp()), int(pd.Timestamp("2100-12-31").timestamp()), 20000), unit="s", utc=True)
    random_labels = random_labels[~((random_labels.month == 2) & (random_labels.day == 29))].tz_localize(None).astype("datetime64[s]").astype(np.int64)
    assert (to_labels(to_model_axis(random_labels, "noleap"), "noleap") == random_labels).all()
    # Two labels 25 h apart across a leap day are 1 h apart on the model axis; the same hours in 2001 (no leap day) are unchanged
    leap_pair, plain_pair = [int(pd.Timestamp(x, tz="UTC").timestamp()) for x in ("2004-02-28 23:00", "2004-03-01 00:00")], [int(pd.Timestamp(x, tz="UTC").timestamp()) for x in ("2001-02-28 23:00", "2001-03-01 00:00")]
    assert np.diff(to_model_axis(leap_pair, "noleap"))[0] == H and np.diff(to_model_axis(plain_pair, "noleap"))[0] == H


def test_leap_day_labels_are_detected():
    """A label on 29 February is refused for a noleap source (it cannot exist); other labels are fine."""
    on_leap_day = int(pd.Timestamp("2004-02-29 12:00", tz="UTC").timestamp())
    assert leap_day_labels_present([on_leap_day]) and not leap_day_labels_present(noleap_hour_labels(2004, "02-27", "03-02"))
    assert not leap_day_labels_present([int(pd.Timestamp("2003-03-01", tz="UTC").timestamp())])


def test_samples_follow_model_time_across_the_leap_day():
    """On the model axis a track that crosses the leap day is not stretched, and the 24 h before 1 March reach 28 February (never 29 February)."""
    labels = noleap_hour_labels(2000, "02-26", "03-04")
    pos = lambda i: dict(lat=10.0 + 0.1 * i, lon=100.0 + 0.2 * i)  # noqa: E731
    def track(local, start_index, hours):
        return pd.DataFrame([dict(period="2000", local_track=local, t=int(labels[start_index + h]), **pos(start_index + h)) for h in range(hours)])
    tracks = pd.concat([track(1, 68, 12), track(2, 75, 6)], ignore_index=True)           # 1: 28 Feb 20:00 -> 1 Mar 07:00; 2: 1 Mar 03:00 -> 08:00
    tracks["t"] = to_model_axis(tracks["t"].to_numpy(), "noleap")
    s = build_samples(tracks, 3, 24)
    one = s.local_track == 1
    assert list(s.time_offset_hours[one]) == [-24 + 3 * k for k in range(8)] + [0, 3, 6, 9]                         # 12 hours -> offsets 0 .. 9, no stretch
    assert (s.track_dt_hours[one] == 0).all()                                                                       # every nominal time has its exact track point
    shown = pd.to_datetime(to_labels(s.data_time, "noleap"), unit="s", utc=True)
    assert not ((shown.month == 2) & (shown.day == 29)).any()
    two_first = s.data_time[(s.local_track == 2) & (s.k == -8)][0]
    assert pd.to_datetime(int(to_labels(two_first, "noleap")), unit="s", utc=True) == pd.Timestamp("2000-02-28 03:00", tz="UTC")      # 24 h before 1 Mar 03:00


def test_file_index_calendar_kind_and_mixed_calendars(tmp_path):
    """The index knows the calendar of its files; a stream that mixes calendars is refused."""
    base = int(pd.Timestamp("2000-01-01", tz="UTC").timestamp())
    for name, calendar in (("a_noleap.nc", "noleap"), ("b_noleap.nc", "365_day"), ("c_std.nc", "standard"), ("d_greg.nc", "gregorian")):
        write_times_file(tmp_path / name, [base, base + 3 * H], calendar=calendar)
    assert FileIndex.build(str(tmp_path), "[ab]_*.nc").calendar == "noleap"
    assert FileIndex.build(str(tmp_path), "[cd]_*.nc").calendar == "standard"
    with pytest.raises(ValueError, match="different calendars"):
        FileIndex.build(str(tmp_path), "*.nc")
