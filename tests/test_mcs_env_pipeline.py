"""End-to-end tests of ``mcs_environment``: synthetic input files with the quirks of the real data, compared row by row with a brute-force version.

The brute force (plain Python loops, haversine distances, no KD-tree, no vectorised sample table) re-implements the rules independently:

* rows at nominal offsets k * step from the track start, the same for every track; the pre-start rows use the start position;
* circle centre = valid track point nearest to the nominal time clamped to the track (ties: earlier point);
* environment = nearest snapshot within half a step (ties: earlier; +step/2 rejected), NaN when missing;
* circle = cell centres within diameter / 2, area-weighted mean over valid cells, pressure-level variables masked below the ground.

Run from the scream folder:  python -m pytest tests/test_mcs_env_pipeline.py
"""

import copy
import shutil
import sys
from pathlib import Path

import netCDF4
import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1] / "mcs_environment"
sys.path.insert(0, str(ROOT))

from mcsenv import derive, extract  # noqa: E402
from mcsenv.config import BUILTIN_DEFAULTS  # noqa: E402
from mcsenv.grid import haversine_km  # noqa: E402
from mcsenv.outputs import read_mcs_env  # noqa: E402

H = 3600
D0 = int(pd.Timestamp("2000-01-01", tz="UTC").timestamp())
DIAMETERS = [300, 1500, 3000, 6000]     # km: on the coarse test grids these hold 0 (nearest-cell fallback), about 5, 7-20 and about 80 cells


# ---------------------------------------------------------------------------------------------------------------------------------
# synthetic data
# ---------------------------------------------------------------------------------------------------------------------------------
def random_grid(n, seed):
    """Random cell centres (float32 values, as the files store them) and random areas."""
    rng = np.random.default_rng(seed)
    lat = np.degrees(np.arcsin(rng.uniform(-1, 1, n))).astype(np.float32).astype(np.float64)
    lon = rng.uniform(0, 360, n).astype(np.float32).astype(np.float64)
    return lat, lon, rng.uniform(0.5, 1.5, n)


# Analytic fields of the synthetic world (all float32 in the files); t is epoch seconds
def f_rh(lat, lon, t):
    """Relative humidity (fraction) of the synthetic world. Args: lat, lon in degrees, t epoch seconds. Returns: array shaped like lat."""
    return 0.6 + 0.3 * np.sin(np.radians(lat)) * np.cos(np.radians(lon)) + 0.02 * np.sin((t - D0) / 86400.0 * 2.0)


def f_t(lat, lon, t):
    """Temperature (K) of the synthetic world (same arguments and return as f_rh)."""
    return 285.0 + 15.0 * np.cos(np.radians(lat)) + 3.0 * np.sin(np.radians(lon)) + (t - D0) / 86400.0 * 0.5


def f_liq(lat, lon, t):
    """Liquid precipitation flux (m/s) of the synthetic world (same arguments and return as f_rh)."""
    return 1e-8 * (1.5 + np.sin(np.radians(lat * 2 + lon)) + (t - D0) / 86400.0 * 0.1)


def f_ice(lat, lon, t):
    """Ice precipitation flux (m/s) of the synthetic world (same arguments and return as f_rh)."""
    return 2e-9 * (1.5 + np.cos(np.radians(lon)))


def f_ps(lat, lon, t):
    """Surface pressure (Pa) of the synthetic world; about half of the cells lie below 850 hPa (same arguments and return as f_rh)."""
    return 85000.0 + 9000.0 * np.sin(np.radians(lat)) * np.cos(np.radians(lon)) + 100.0 * (t - D0) / 86400.0


def f_prw(lat, lon, t):
    """Column water vapor (kg/m2) of the synthetic world (same arguments and return as f_rh)."""
    return 30.0 + 20.0 * np.cos(np.radians(lat)) + (t - D0) / H * 0.1


def f_prw2(lat, lon, t):
    """Column water vapor on the second grid of the synthetic world (same arguments and return as f_rh)."""
    return 10.0 + 5.0 * np.sin(np.radians(lon)) + (t - D0) / H * 0.05


def write_ncol(path, times, lat, lon, area, fields, fmt="NETCDF3_CLASSIC", time_values=None):
    """One (time, ncol) file; the coordinate attributes say 'rad' although the values are degrees (as in the SCREAM files).

    ``times`` are what the field functions receive (epoch seconds, or model hours in the leap-day test); ``time_values`` (default None) are the values of the
    time variable in days since 2000-01-01 of a noleap calendar (default: derived from ``times`` as epoch seconds).
    """
    with netCDF4.Dataset(path, "w", format=fmt) as ds:
        ds.createDimension("time", None)
        ds.createDimension("ncol", lat.size)
        tv = ds.createVariable("time", "f8", ("time",))
        tv.units, tv.calendar = "days since 2000-01-01 00:00:00", "noleap"
        for name, values in (("lat", lat), ("lon", lon), ("area", area)):
            v = ds.createVariable(name, "f4", ("ncol",))
            v.units = "rad" if name != "area" else "rad*rad"
            v[:] = values
        variables = {name: ds.createVariable(name, "f4", ("time", "ncol"), fill_value=np.float32(3.4e33)) for name in fields}
        for i, t in enumerate(times):
            tv[i] = (t - D0) / 86400.0 if time_values is None else time_values[i]
            for name, fn in fields.items():
                variables[name][i, :] = fn(lat, lon, t).astype(np.float32)


def build_world(tmp_path):
    """Three streams in SCREAM-style layouts: 3-hourly (shifted starts, an empty day, a backup copy), 6-hourly, and a short 3-hourly one on a second grid."""
    lat_a, lon_a, area_a = random_grid(1500, 11)
    lat_b, lon_b, area_b = random_grid(400, 12)
    roots = {n: tmp_path / n for n in ("inst3h", "inst6h", "coarse3h")}
    for r in roots.values():
        r.mkdir()
    times = {"inst3h": [], "inst6h": [], "coarse3h": []}
    fields3 = {"RH850": f_rh, "T850": f_t, "LIQ": f_liq, "ICE": f_ice, "PS": f_ps}
    for d in range(8):
        # inst3h: day 0 starts at 00:00, later days at 03:00 and end with the next-day 00:00; Jan 4 (d = 3) is an empty file
        hours = range(0, 24, 3) if d == 0 else range(3, 27, 3)
        stamps = [D0 + d * 86400 + h * H for h in hours]
        name = f"x3.INSTANT.nhours_x3.2000-01-{d + 1:02d}-{'00000' if d == 0 else '10800'}.nc"
        if d == 3:
            write_ncol(roots["inst3h"] / name, [], lat_a, lon_a, area_a, fields3)
        else:
            write_ncol(roots["inst3h"] / name, stamps, lat_a, lon_a, area_a, fields3)
            times["inst3h"] += stamps
        # inst6h: 4 records per file, NETCDF4
        hours6 = range(0, 24, 6) if d == 0 else range(6, 30, 6)
        stamps6 = [D0 + d * 86400 + h * H for h in hours6]
        write_ncol(roots["inst6h"] / f"x6.INSTANT.nhours_x6.2000-01-{d + 1:02d}-{'00000' if d == 0 else '21600'}.nc", stamps6, lat_a, lon_a, area_a,
                   {"PRW": f_prw}, fmt="NETCDF4")
        times["inst6h"] += stamps6
        # coarse3h on grid B: only the first six days exist
        if d < 6:
            write_ncol(roots["coarse3h"] / f"x3.INSTANT.nhours_x3.2000-01-{d + 1:02d}-{'00000' if d == 0 else '10800'}.nc", stamps, lat_b, lon_b, area_b,
                       {"PRW2": f_prw2})
            times["coarse3h"] += stamps
    # A backup copy and a restart file that must never be read
    shutil.copy(roots["inst3h"] / "x3.INSTANT.nhours_x3.2000-01-02-10800.nc", roots["inst3h"] / "x3.INSTANT.nhours_x3.2000-01-02-10800.nc~")
    write_ncol(roots["inst3h"] / "x3.rhist.INSTANT.ndays_x5.2000-01-05-00000.nc", [D0 + 99 * H], lat_a, lon_a, area_a, fields3)
    return dict(roots=roots, times={k: np.array(sorted(v)) for k, v in times.items()}, A=(lat_a, lon_a, area_a), B=(lat_b, lon_b, area_b))


def make_cfg(world, max_missing=0.9):
    """Source configuration of the synthetic world (the same keys as sources.yaml)."""
    cfg = copy.deepcopy(BUILTIN_DEFAULTS)
    cfg.update({
        "name": "synth", "label": "synthetic", "tracks": "unused", "diameters_km": DIAMETERS, "max_missing_fraction": max_missing,
        "ps": {"stream": "inst3h", "var": "PS"},
        "grids": {"gridA": {"stream": "inst3h", "lat": "lat", "lon": "lon", "area": "area"},
                  "gridB": {"stream": "coarse3h", "lat": "lat", "lon": "lon", "area": "area"}},
        "streams": {
            "inst3h": {"root": str(world["roots"]["inst3h"]), "pattern": "x3.INSTANT.nhours_x3.????-??-??-?????.nc", "reader": "ncol", "grid": "gridA",
                       "variables": {
                           "rh850": {"from": "RH850", "scale": 100.0, "level_hpa": 850, "units": "%"},
                           "q850": {"derive": "q_from_rh", "inputs": {"rh": "RH850", "t": "T850"}, "level_hpa": 850, "units": "kg kg-1"},
                           "pr": {"derive": "sum", "inputs": ["LIQ", "ICE"], "scale": 3600000.0, "units": "mm h-1"}}},
            "inst6h": {"root": str(world["roots"]["inst6h"]), "pattern": "x6.INSTANT.nhours_x6.????-??-??-?????.nc", "reader": "ncol", "grid": "gridA",
                       "variables": {"prw": {"from": "PRW", "units": "kg m-2"}}},
            "coarse3h": {"root": str(world["roots"]["coarse3h"]), "pattern": "x3.INSTANT.nhours_x3.????-??-??-?????.nc", "reader": "ncol", "grid": "gridB",
                         "variables": {"prw2": {"from": "PRW2", "units": "kg m-2"}}},
        },
    })
    return cfg


def make_tracks():
    """Six tracks with the situations of the real data: every start hour, a gap, a NaN position, record start, an empty env day, record end."""
    def track(local, start, hours, drop=(), nan=()):
        """One hourly track of the test set (arguments as make_track in test_mcs_env_core.py; returns a DataFrame)."""
        return pd.DataFrame([dict(period="2000", local_track=local, t=start + h * H, lat=np.nan if h in nan else -30.0 + 10 * local + 2 * h,
                                  lon=20.0 + 50 * local + 9 * h) for h in range(hours) if h not in drop])
    return pd.concat([
        track(1, D0 + 2 * 86400 + 14 * H, 10),
        track(2, D0 + 2 * 86400 + 15 * H, 7, drop=(3,)),
        track(3, D0 + 2 * 86400 + 16 * H, 5, nan=(0,)),
        track(4, D0 + 6 * H, 6),                         # the pre-start window lies before the start of the environment record
        track(5, D0 + 3 * 86400 + 9 * H, 8),             # starts inside the empty env day
        track(6, D0 + 6 * 86400 + 22 * H, 8),            # runs past the end of the short stream
    ], ignore_index=True)


# ---------------------------------------------------------------------------------------------------------------------------------
# brute force
# ---------------------------------------------------------------------------------------------------------------------------------
def nearest_env(stamps, s, step):
    """Nearest stamp within -step/2 <= stamp - s < step/2, ties to the earlier one (None when there is none)."""
    best = None
    for t in stamps:
        shift = t - s
        if -step / 2 <= shift < step / 2 and (best is None or (abs(shift), t) < (abs(best - s), best)):
            best = t
    return best


def circle_stats(grid, values, clat, clon, diameter):
    """(mean, valid fraction, n cells) of a circle by brute force; an empty circle takes the nearest cell."""
    lat, lon, area = grid
    dist = haversine_km(clat, clon, lat, lon)
    inside = dist <= diameter / 2
    if not inside.any():
        inside[np.argmin(dist)] = True
    w, v = area[inside], values[inside]
    ok = np.isfinite(v)
    mean = (v[ok] * w[ok]).sum() / w[ok].sum() if ok.any() else np.nan
    return mean, w[ok].sum() / w.sum(), int(inside.sum())


def field32(fn, grid, t):
    """A field on a grid as float32 (what the file stores), then float64."""
    return fn(grid[0], grid[1], t).astype(np.float32).astype(np.float64)


def brute_force(world, tracks, step_h, variables):
    """Expected rows: dict (local_track, offset_h, diameter) -> dict of values. ``variables`` maps a name to (stream, function(t) -> field on its grid)."""
    out = {}
    step = step_h * H
    for local, tr in tracks.groupby("local_track"):
        t, lat, lon = tr["t"].to_numpy(), tr["lat"].to_numpy(), tr["lon"].to_numpy()
        valid = [i for i in range(t.size) if np.isfinite(lat[i]) and np.isfinite(lon[i])]
        t0, tn = t[0], t[-1]
        for k in range(-24 * H // step, (tn - t0) // step + 1):
            s = t0 + k * step
            sc = min(max(s, t0), tn)
            m = sorted(valid, key=lambda i: (abs(t[i] - sc), t[i]))[0]
            row = {"center_lat": lat[m], "center_lon": lon[m], "track_time": t[m]}
            for name, (stream, grid_name, group_step, fn) in variables.items():
                env = nearest_env(world["times"][stream], s, group_step)
                row[f"{name}_dt"] = np.nan if env is None else (env - s) / H
                for d in DIAMETERS:
                    if env is None:
                        row[(name, d)] = (np.nan, np.nan, 0)
                    else:
                        row[(name, d)] = circle_stats(world["A" if grid_name == "gridA" else "B"], fn(env), lat[m], lon[m], d)
            out[(int(local), float(k * step_h), None)] = row
    return out


def world_variables(world):
    """The standard variables of the synthetic world as brute-force functions of the snapshot time."""
    grid = world["A"]
    mask = lambda t: field32(f_ps, grid, t) < 85000.0  # noqa: E731

    def rh850(t):
        """Brute-force rh850 (%) on grid A at epoch time t, masked where the surface pressure is below 850 hPa."""
        v = field32(f_rh, grid, t) * 100.0
        v[mask(t)] = np.nan
        return v

    def q850(t):
        """Brute-force q850 (kg/kg) on grid A at epoch time t from RH and T, masked where the surface pressure is below 850 hPa."""
        v = derive.q_from_rh(field32(f_rh, grid, t), field32(f_t, grid, t), 85000.0)
        v[mask(t)] = np.nan
        return v

    pr = lambda t: (field32(f_liq, grid, t) + field32(f_ice, grid, t)) * 3600000.0  # noqa: E731
    prw = lambda t: field32(f_prw, grid, t)  # noqa: E731
    prw2 = lambda t: field32(f_prw2, world["B"], t)  # noqa: E731
    return {"rh850": ("inst3h", "gridA", 3 * H, rh850), "q850": ("inst3h", "gridA", 3 * H, q850), "pr": ("inst3h", "gridA", 3 * H, pr),
            "prw": ("inst6h", "gridA", 6 * H, prw), "prw2": ("coarse3h", "gridB", 3 * H, prw2)}


def compare(df, expected, variables, groups):
    """Every output row against the brute force; returns the number of finite values compared."""
    n_compared = 0
    assert len(df) == len(expected) * len(DIAMETERS)
    for rec in df.itertuples(index=False):
        row = expected[(int(rec.local_track), float(rec.time_offset_hours), None)]
        assert rec.center_lat == pytest.approx(row["center_lat"], abs=1e-4) and rec.center_lon == pytest.approx(row["center_lon"], abs=1e-4)
        assert int(pd.Timestamp(rec.track_time).timestamp()) == row["track_time"]
        for name in variables:
            mean, frac, n_cells = row[(name, rec.diameter_km)]
            got = getattr(rec, name)
            if np.isnan(mean):
                assert np.isnan(got), (name, rec)
            else:
                assert got == pytest.approx(mean, rel=2e-5), (name, rec)
                n_compared += 1
            fgot = getattr(rec, f"{name}_validfrac")
            assert (np.isnan(fgot) and np.isnan(frac)) or fgot == pytest.approx(frac, rel=1e-5, abs=1e-6), (name, "validfrac", rec)
        for group, columns in groups.items():
            ref = row[f"{columns['var']}_dt"]
            got = getattr(rec, columns["dt"])
            assert (np.isnan(got) and np.isnan(ref)) or got == pytest.approx(ref), (group, rec)
    return n_compared


# ---------------------------------------------------------------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """The synthetic input files (built once)."""
    return build_world(tmp_path_factory.mktemp("synth_world"))


def run(world, tmp_path, nproc=1, max_missing=0.9, cfg=None):
    """Run the extraction of the synthetic world and return the output DataFrame."""
    cfg = cfg or make_cfg(world, max_missing)
    files = extract.run_source(cfg, [2000], str(tmp_path / "out"), nproc=nproc, tracks=make_tracks())
    return read_mcs_env(files[0]), files[0]


def test_all_rows_equal_the_brute_force(world, tmp_path):
    """Rows, centres, snapshots, weighted means, valid fractions, masks, missing frames and the second grid agree with the independent version."""
    df, _ = run(world, tmp_path)
    variables = world_variables(world)
    expected = brute_force(world, make_tracks(), 3, variables)
    groups = {"inst3h": {"var": "rh850", "dt": "env_dt_hours"}, "inst6h": {"var": "prw", "dt": "env_dt_hours_inst6h"},
              "coarse3h": {"var": "prw2", "dt": "env_dt_hours_coarse3h"}}
    n = compare(df, expected, list(variables), groups)
    assert n > 500
    # The composite axis: every track has exactly the offsets k * 3 h and a row at 0 and at -24 h
    for local, part in df.groupby("local_track"):
        off = np.sort(part["time_offset_hours"].unique())
        assert (off % 3 == 0).all() and 0 in off and off.min() == -24
    # Things the real data have: NaN for tracks over the empty day and the record start, masked cells, circles with fallback cells
    assert df.loc[df.local_track == 5, "rh850"].isna().any() and df.loc[df.local_track == 4, "pr"].isna().any()
    # n_cells belongs to the grid: it is filled by any group on that grid and is 0 only where no group on grid A has a snapshot
    with_frame = df["env_dt_hours"].notna() | df["env_dt_hours_inst6h"].notna()
    assert (df["rh850_validfrac"] < 1).any() and df.loc[with_frame, "n_cells"].min() >= 1 and (df.loc[~with_frame, "n_cells"] == 0).all()
    assert (df["n_cells"] == 1).any() and df["n_cells"].max() > 10
    assert df.loc[df.local_track == 6, "prw2"].isna().any() and df.loc[df.local_track == 1, "prw2"].notna().all()


def test_metadata_units_and_columns(world, tmp_path):
    """Units, long names, source variables and the document of the file."""
    df, path = run(world, tmp_path)
    meta = df.attrs["mcs_env"]
    assert df.attrs["units"]["q850"] == "kg kg-1" and df.attrs["units"]["pr"] == "mm h-1" and df.attrs["units"]["diameter_km"] == "km"
    assert meta["n_samples"] * len(DIAMETERS) == len(df) and meta["diameters_km"] == [float(d) for d in DIAMETERS] and meta["step_hours"] == 3.0
    assert [g["name"] for g in meta["groups"]] == ["inst3h", "coarse3h", "inst6h"] or [g["name"] for g in meta["groups"]][0] == "inst3h"
    primary = meta["groups"][0]
    assert primary["n_samples_without_frame"] > 0 and primary["nominal_times_without_frame_first200"]
    assert meta["streams"]["inst3h"]["empty_files"] and meta["streams"]["inst3h"]["n_files"] == 8
    assert "n_cells_gridB" in df.columns and "env_dt_hours_inst6h" in df.columns and "env_dt_hours_coarse3h" in df.columns
    assert df.attrs["long_name"]["rh850"].startswith("Relative humidity")


def test_parallel_equals_serial(world, tmp_path):
    """Two worker processes give exactly the table of the serial run."""
    serial, _ = run(world, tmp_path / "a", nproc=1)
    parallel, _ = run(world, tmp_path / "b", nproc=2)
    pd.testing.assert_frame_equal(serial, parallel, check_exact=True)


def test_restart_reuses_finished_parts_and_discards_stale_ones(world, tmp_path, monkeypatch):
    """Finished parts are kept (not recomputed), a deleted part is recomputed, parts of another setting are discarded."""
    keep = lambda *a, **k: None  # noqa: E731  (keep the parts after the run)
    monkeypatch.setattr(extract.shutil, "rmtree", keep)
    first, _ = run(world, tmp_path)
    parts = sorted((tmp_path / "out" / "synth" / "_parts" / "2000").glob("g*.parquet"))
    assert len(parts) > 5
    before = {p: p.stat().st_mtime_ns for p in parts}
    victim = parts[2]
    victim.unlink()
    second, _ = run(world, tmp_path)
    assert victim.exists() and all(p.stat().st_mtime_ns == before[p] for p in parts if p != victim)
    pd.testing.assert_frame_equal(first, second, check_exact=True)
    # Another diameter list changes the signature: the old parts must not be reused
    cfg = make_cfg(world)
    cfg["diameters_km"] = [2000]
    monkeypatch.undo()
    third, _ = run(world, tmp_path, cfg=cfg)
    assert sorted(third["diameter_km"].unique()) == [2000] and not (tmp_path / "out" / "synth" / "_parts" / "2000").exists()


def test_missing_frame_guard_stops_before_writing(world, tmp_path):
    """More rows without a snapshot than max_missing_fraction stops the job before anything is written."""
    with pytest.raises(RuntimeError, match="max_missing_fraction"):
        run(world, tmp_path, max_missing=1e-4)
    assert not list((tmp_path / "out").rglob("*.parquet"))


def test_surface_pressure_must_share_the_group(world, tmp_path):
    """A masked variable whose surface-pressure stream sits on another grid is a configuration error, not a silent mistake."""
    cfg = make_cfg(world)
    cfg["ps"] = {"stream": "coarse3h", "var": "PRW2"}
    with pytest.raises(Exception, match="surface pressure"):
        run(world, tmp_path, cfg=cfg)


# ---------------------------------------------------------------------------------------------------------------------------------
# ERA5-style layout: pressure levels, hourly daily files, a chunked monthly surface-pressure file, tracks at :30
# ---------------------------------------------------------------------------------------------------------------------------------
LEVELS = np.array([1000.0, 850.0, 500.0, 300.0])


def era5_q(level, lat, lon, t):
    """Specific humidity (kg/kg) of the ERA5-style test world. Args: level in hPa, lat, lon in degrees, t epoch seconds. Returns: array shaped like lat."""
    return 0.012 * (level / 1000.0) * (1 + 0.5 * np.cos(np.radians(lat))) + 1e-5 * np.sin(np.radians(lon)) + 1e-6 * (t - D0) / H


def era5_sp(lat, lon, t):
    """Surface pressure (Pa) of the ERA5-style test world. Args: lat, lon in degrees, t epoch seconds. Returns: array shaped like lat."""
    return 84000.0 + 12000.0 * np.sin(np.radians(lat * 2)) * np.cos(np.radians(lon)) + 20.0 * (t - D0) / H


def write_latlon(path, times, lat1, lon1, level_field=None, sp_field=None):
    """An ERA5-like file: hours since 1900 (standard calendar), zlib-compressed and chunked like the real files."""
    base = int(pd.Timestamp("1900-01-01", tz="UTC").timestamp())
    with netCDF4.Dataset(path, "w", format="NETCDF4") as ds:
        ds.createDimension("time", len(times))
        ds.createDimension("latitude", lat1.size)
        ds.createDimension("longitude", lon1.size)
        tv = ds.createVariable("time", "i4", ("time",))
        tv.units, tv.calendar = "hours since 1900-01-01 00:00:00", "gregorian"
        tv[:] = [(t - base) // H for t in times]
        for name, values in (("latitude", lat1), ("longitude", lon1)):
            ds.createVariable(name, "f8", (name,))[:] = values
        lat2, lon2 = np.meshgrid(lat1, lon1, indexing="ij")
        if level_field:
            ds.createDimension("level", LEVELS.size)
            ds.createVariable("level", "f8", ("level",))[:] = LEVELS
            q = ds.createVariable("Q", "f4", ("time", "level", "latitude", "longitude"), zlib=True, chunksizes=(1, LEVELS.size, lat1.size, lon1.size))
            for i, t in enumerate(times):
                for j, lev in enumerate(LEVELS):
                    q[i, j] = level_field(lev, lat2, lon2, t).astype(np.float32)
        if sp_field:
            sp = ds.createVariable("SP", "f4", ("time", "latitude", "longitude"), zlib=True, chunksizes=(4, 5, 7))
            for i, t in enumerate(times):
                sp[i] = sp_field(lat2, lon2, t).astype(np.float32)


def test_era5_style_layout(tmp_path):
    """Pressure-level selection, chunked monthly surface pressure, cos(lat) weights, :30 tracks (tie -> earlier hour, shift -0.5 h), mask below the ground."""
    lat1, lon1 = np.arange(90.0, -90.1, -15.0), np.arange(0.0, 360.0, 15.0)
    pl, sfc = tmp_path / "pl", tmp_path / "sfc"
    pl.mkdir(), sfc.mkdir()
    for d in range(4):
        write_latlon(pl / f"e5.oper.an.pl.128_133_q.ll025sc.200001{d + 1:02d}00_200001{d + 1:02d}23.nc", [D0 + d * 86400 + h * H for h in range(24)], lat1, lon1,
                     level_field=era5_q)
    write_latlon(sfc / "e5.oper.an.sfc.128_134_sp.ll025sc.2000010100_2000013123.nc", [D0 + h * H for h in range(96)], lat1, lon1, sp_field=era5_sp)
    lat2, lon2 = np.meshgrid(lat1, lon1, indexing="ij")
    cfg = copy.deepcopy(BUILTIN_DEFAULTS)
    cfg.update({
        "name": "era5like", "tracks": "unused", "diameters_km": DIAMETERS, "ps": {"stream": "sp", "var": "SP"},
        "grids": {"era5": {"stream": "q", "lat": "latitude", "lon": "longitude", "area": "cos_lat"}},
        "streams": {
            "q": {"root": str(pl), "pattern": "*.nc", "reader": "latlon_level", "grid": "era5",
                  "variables": {"q850": {"from": "Q", "level_hpa": 850, "units": "kg kg-1"}, "q500": {"from": "Q", "level_hpa": 500, "units": "kg kg-1"}}},
            "sp": {"root": str(sfc), "pattern": "*.nc", "reader": "latlon", "grid": "era5", "variables": {}}},
    })
    # Tracks at :30 (as the OBS tracks), one starting at 06:30 on Jan 2 (pre-start rows reach back to Jan 1 06:30)
    tracks = pd.DataFrame([dict(period="2000", local_track=1, t=D0 + 86400 + 6 * H + 1800 + h * H, lat=-20.0 + 5 * h, lon=60.0 + 12 * h) for h in range(9)])
    files = extract.run_source(cfg, [2000], str(tmp_path / "out"), nproc=1, tracks=tracks)
    df = read_mcs_env(files[0])
    grid = (lat2.ravel(), lon2.ravel(), np.cos(np.radians(lat2.ravel())))
    stamps = np.array([D0 + h * H for h in range(96)])
    n_checked = 0
    for rec in df.itertuples(index=False):
        s = D0 + 86400 + 6 * H + 1800 + int(rec.time_offset_hours) * H
        env = nearest_env(stamps, s, H)
        assert env == s - 1800 and rec.env_dt_hours == pytest.approx(-0.5)         # the tie between :00 and :00 + 1 h goes to the earlier hour
        m = min(max(int(rec.time_offset_hours), 0), 8)
        assert rec.center_lat == pytest.approx(-20.0 + 5 * m, abs=1e-4)
        sp = era5_sp(lat2, lon2, env).astype(np.float32).astype(np.float64).ravel()
        for var, level in (("q850", 850.0), ("q500", 500.0)):
            q = era5_q(level, lat2, lon2, env).astype(np.float32).astype(np.float64).ravel()
            q[sp < level * 100] = np.nan
            mean, frac, _n = circle_stats(grid, q, rec.center_lat, rec.center_lon, rec.diameter_km)
            got = getattr(rec, var)
            assert (np.isnan(got) and np.isnan(mean)) or got == pytest.approx(mean, rel=2e-5)
            n_checked += int(np.isfinite(mean))
    assert n_checked > 60 and df["q850_validfrac"].lt(1).any()
    assert sorted(df["time_offset_hours"].unique())[0] == -24 and df.attrs["mcs_env"]["streams"]["q"]["step_hours"] == 1.0


# ---------------------------------------------------------------------------------------------------------------------------------
# a noleap model around 29 February 2000 (a leap year): time runs on the model axis, with an index-based brute force
# ---------------------------------------------------------------------------------------------------------------------------------
def test_noleap_leap_day_is_skipped_in_model_time(tmp_path):
    """Snapshots, tracks that cross the leap day and tracks that start on 1 March agree with a brute force that counts model hours (no dates)."""
    import datetime as dt

    start = dt.datetime(2000, 2, 26)

    def label(i):
        """Calendar label of model hour ``i`` counted from 26 February 00:00: the hour after 28 February 23:00 is 1 March 00:00."""
        t = start + dt.timedelta(hours=i)
        return t + dt.timedelta(days=1) if t >= dt.datetime(2000, 2, 29) else t

    def epoch(i):
        return int(pd.Timestamp(label(i), tz="UTC").timestamp())

    # Environment: 3-hourly snapshots every 3rd model hour, one file per model day (8 records), time values counted in noleap days since 1 January
    lat, lon, area = random_grid(900, 21)
    root = tmp_path / "leap"
    root.mkdir()
    field = lambda la, lo, i: 0.5 + 0.3 * np.sin(np.radians(la)) * np.cos(np.radians(lo)) + 0.001 * i  # noqa: E731  (i = model hour index)
    for day in range(8):
        idx = [24 * day + h for h in range(0, 24, 3)]
        write_ncol(root / f"x.INSTANT.nhours_x3.2000-02-{26 + day:02d}-00000.nc", idx, lat, lon, area, {"RH": field}, time_values=[56 + i / 24.0 for i in idx])
    # Tracks as model-hour indices: 1 crosses the leap day, 2 starts on 1 March 03:00, 3 is far from it
    spec = {1: (68, 12), 2: (75, 6), 3: (36, 3)}
    rows = []
    for local, (i0, n) in spec.items():
        rows += [dict(period="2000", local_track=local, t=epoch(i0 + h), lat=-20.0 + 3 * local + 1.5 * h, lon=30.0 + 40 * local + 2.0 * h) for h in range(n)]
    tracks = pd.DataFrame(rows)
    cfg = copy.deepcopy(BUILTIN_DEFAULTS)
    cfg.update({"name": "leap", "tracks": "unused", "diameters_km": [1500, 3000], "max_missing_fraction": 0.9, "ps": None,
                "grids": {"g": {"stream": "s", "lat": "lat", "lon": "lon", "area": "area"}},
                "streams": {"s": {"root": str(root), "pattern": "x.INSTANT.nhours_x3.????-??-??-?????.nc", "reader": "ncol", "grid": "g",
                                  "variables": {"rh": {"from": "RH", "scale": 100.0, "units": "%"}}}}})
    df = read_mcs_env(extract.run_source(cfg, [2000], str(tmp_path / "out"), tracks=tracks)[0])
    assert df.attrs["mcs_env"]["calendar"] == "noleap"
    # Brute force on model hours: nominal hour = start + 3k (clamped to the track for the centre), snapshot = nearest multiple of 3 hours, value from the index
    n_rows = 0
    for local, (i0, n) in spec.items():
        last = i0 + n - 1
        for k in range(-8, (last - i0) // 3 + 1):
            nominal = i0 + 3 * k
            point = min(max(nominal, i0), last)
            h = point - i0
            clat, clon = -20.0 + 3 * local + 1.5 * h, 30.0 + 40 * local + 2.0 * h
            env = (nominal // 3) * 3 if nominal - (nominal // 3) * 3 <= (nominal // 3) * 3 + 3 - nominal else (nominal // 3) * 3 + 3
            for d in (1500, 3000):
                got = df[(df.local_track == local) & (df.time_offset_hours == 3 * k) & (df.diameter_km == d)]
                assert len(got) == 1, (local, k, d)
                got = got.iloc[0]
                assert pd.Timestamp(got["data_time"]) == pd.Timestamp(label(nominal), tz="UTC") if nominal >= 0 else True
                assert pd.Timestamp(got["track_time"]) == pd.Timestamp(label(point), tz="UTC")
                if nominal < 0:
                    assert np.isnan(got["rh"])                                   # before the start of the environment record
                    continue
                values = 100.0 * field(lat, lon, env).astype(np.float32).astype(np.float64)
                mean, _frac, n_cells = circle_stats((lat, lon, area), values, clat, clon, d)
                assert got["rh"] == pytest.approx(mean, rel=2e-5) and got["env_dt_hours"] == pytest.approx(env - nominal) and got["n_cells"] == n_cells
                n_rows += 1
    assert n_rows >= 40
    # No row is ever named 29 February, and the crossing track has no stretch: 12 hours = offsets 0, 3, 6, 9
    shown = pd.to_datetime(df["data_time"])
    assert not ((shown.dt.month == 2) & (shown.dt.day == 29)).any()
    assert sorted(df.loc[(df.local_track == 1) & (df.diameter_km == 1500), "time_offset_hours"].tolist())[-4:] == [0, 3, 6, 9]


def test_noleap_source_refuses_tracks_on_29_february(tmp_path, world):
    """A track file with a 29 February time cannot belong to a noleap model: the job stops with a clear message instead of misplacing the rows."""
    tracks = make_tracks()
    tracks.loc[tracks.index[0], "t"] = int(pd.Timestamp("2000-02-29 06:00", tz="UTC").timestamp())
    cfg = make_cfg(world)
    with pytest.raises(Exception, match="29 February"):
        extract.run_source(cfg, [2000], str(tmp_path / "out"), tracks=tracks)


def _slow_or_fail(spec):
    """Task stand-in for the fail-fast test: the first task raises, every other one takes 3 seconds (module level so that the pool can pickle it)."""
    import time as _time

    if spec[1] == 0:
        raise RuntimeError("boom")
    _time.sleep(3)
    return spec, "done", 0


def test_a_failing_task_stops_the_parallel_job_at_once(monkeypatch):
    """An exception in one task ends the job immediately; the queued tasks (here 40 x 3 s on 2 workers = 60 s) are not run first."""
    import time
    import types

    monkeypatch.setattr(extract, "_run_task", _slow_or_fail)
    started = time.time()
    with pytest.raises(RuntimeError, match="boom"):
        extract.run_tasks(types.SimpleNamespace(), 2, [(0, i, i + 1) for i in range(40)])
    assert time.time() - started < 20
