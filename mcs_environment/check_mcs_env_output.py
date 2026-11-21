#!/usr/bin/env python
"""Check an output file of ``extract_mcs_env.py`` by its contents (not by the exit status of the job).

Structural checks (always):

* the key (period, local_track, time_offset_hours, diameter_km) is unique and every track of the track file that has a position is present;
* the number of rows of every track equals the expected number computed from the track file (rows at k * step, ``24 h / step`` before the start);
* the composite axis: only multiples of the step occur, every track has a row at 0 and at -24 h, and the count in every time-offset bin equals the
  number of tracks that are alive in that bin (what ``groupby('time_offset_hours')`` of a composite sees);
* the circle centre of every row is the track position at ``track_time`` of the track file (join on period, local_track, track_time);
* the share of NaN of every variable before the start and during the track (a variable that is 100 % NaN fails), NaN exactly where the snapshot is
  missing, value ranges, the distribution of ``n_cells`` and of the valid fraction, the missing-frame counts recorded in the file.

Independent recomputation (``--brute-force N``): N random rows are recomputed from the input files with plain netCDF4 and haversine distances (no
KD-tree, no sparse matrices, no readers of the package) and compared with the file.

Example:  python check_mcs_env_output.py $SCRATCH/mcs_env/3km_CTL/mcs_env_3km_CTL_1996.parquet --brute-force 40
"""

import os

os.environ.setdefault("HDF5_USE_FILE_LOCKING", "FALSE")

import argparse  # noqa: E402
import sys  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

from mcsenv.config import load_config  # noqa: E402
from mcsenv.derive import compute_variable, mask_below_ground, raw_names  # noqa: E402
from mcsenv.fileindex import FileIndex  # noqa: E402
from mcsenv.grid import haversine_km  # noqa: E402
from mcsenv.modelcal import to_labels, to_model_axis  # noqa: E402
from mcsenv.outputs import read_mcs_env  # noqa: E402

# Generous physical bounds per standard variable (name prefix -> (low, high)); values outside them fail the check
BOUNDS = {"rh": (0.0, 130.0), "prw": (0.0, 120.0), "q": (0.0, 0.05), "omega": (-30.0, 30.0), "pr": (0.0, 1000.0)}


class Report:
    """Collects the lines of the report and the failed checks."""

    def __init__(self):
        """Start with no failed checks."""
        self.failures = []

    def line(self, text):
        """Print one line of the report."""
        print(text, flush=True)

    def check(self, ok, text):
        """Print a PASS or FAIL line and remember failures."""
        print(("PASS  " if ok else "FAIL  ") + text, flush=True)
        if not ok:
            self.failures.append(text)


def expected_from_tracks(tracks_path, period, step_s, pre_s, start_date=None, end_date=None, calendar="standard"):
    """Expected rows per track and the alive count of every offset, from the track file (independent of the sample builder).

    Args:
        tracks_path: MCS track Parquet file.
        period: the period (year string) of the output file.
        step_s: step in seconds; pre_s: pre-start window in seconds.
        start_date, end_date: the track-start filter the file was made with (None = none).
        calendar: ``noleap`` or ``standard``; for noleap all durations are measured on the model axis without 29 February (default ``standard``).

    Returns:
        (per_track, track_table): Series of the expected number of samples per (period, local_track), and the track table (with ``t`` seconds).
    """
    tr = pq.read_table(tracks_path, columns=["period", "local_track", "base_time", "meanlat", "meanlon"], filters=[("period", "=", str(period))]).to_pandas()
    tr["t"] = tr["base_time"].astype("datetime64[s]").astype("int64") if tr["base_time"].dt.tz is None else tr["base_time"].dt.tz_convert("UTC").dt.tz_localize(None).astype("datetime64[s]").astype("int64")
    tr["t"] = to_model_axis(tr["t"].to_numpy(), calendar)
    tr["ok"] = tr["meanlat"].notna() & tr["meanlon"].notna()
    keys = ["period", "local_track"]
    span = tr.groupby(keys)["t"].agg(["min", "max"])
    has_position = tr.groupby(keys)["ok"].any()
    span = span[has_position.reindex(span.index).to_numpy()]
    # The same selection of tracks as the extraction (first time of the track within [start_date, end_date])
    for bound, keep in ((start_date, lambda x, b: x >= b), (end_date, lambda x, b: x <= b)):
        if bound is not None:
            span = span[keep(span["min"], int(to_model_axis(int(pd.Timestamp(bound, tz="UTC").timestamp()), calendar))).to_numpy()]
    tr = tr.merge(span.index.to_frame(index=False), on=["period", "local_track"])
    per_track = pre_s // step_s + (span["max"] - span["min"]) // step_s + 1
    return per_track, tr, span


def structural_checks(df, tracks_path, report):
    """All structural checks of the module docstring on a DataFrame of ``read_mcs_env``."""
    meta = df.attrs["mcs_env"]
    period, step_h, pre_h = meta["period"], meta["step_hours"], meta["pre_start_hours"]
    step_s, pre_s = int(round(step_h * 3600)), int(round(pre_h * 3600))
    diameters = sorted(df["diameter_km"].unique())
    report.line(f"file: source {meta['source']}, calendar {meta.get('calendar', 'standard')}, period {period}, {len(df)} rows, {meta['n_samples']} samples, diameters {[float(d) for d in diameters]}, step {step_h} h, track start range {meta.get('track_start_range')}")
    # 1. key and diameters
    keys = ["period", "local_track", "time_offset_hours", "diameter_km"]
    report.check(not df.duplicated(keys).any(), "key (period, local_track, time_offset_hours, diameter_km) is unique")
    report.check(len(diameters) == len(meta["diameters_km"]) and len(df) == meta["n_samples"] * len(diameters), "row count = samples x diameters")
    # 2. rows per track against the track file
    start_date, end_date = meta.get("track_start_range") or (None, None)
    calendar = meta.get("calendar", "standard")
    per_track, tr, span = expected_from_tracks(tracks_path, period, step_s, pre_s, start_date, end_date, calendar)
    got = df.groupby(["period", "local_track"], observed=True).size() // len(diameters)
    got.index = got.index.set_levels(got.index.levels[0].astype(str), level=0)
    same = got.reindex(per_track.index).fillna(-1).astype(np.int64).equals(per_track.astype(np.int64)) and len(got) == len(per_track)
    report.check(same, f"every track has the expected number of rows ({len(per_track)} tracks with a position; first mismatch listed if not)")
    if not same:
        bad = (got.reindex(per_track.index).fillna(-1) != per_track).to_numpy()
        report.line("      " + str(pd.DataFrame({"got": got.reindex(per_track.index), "expected": per_track})[bad].head(5).to_dict()))
    # 3. the composite axis
    off = df.loc[df["diameter_km"] == diameters[0], "time_offset_hours"].to_numpy()
    report.check(bool(np.all(np.mod(off, step_h) == 0)), f"all time offsets are multiples of the step ({step_h} h)")
    first_d = df[df["diameter_km"] == diameters[0]]
    has0 = first_d[first_d["time_offset_hours"] == 0].groupby(["period", "local_track"], observed=True).size()
    hasm = first_d[first_d["time_offset_hours"] == -pre_h].groupby(["period", "local_track"], observed=True).size()
    report.check(len(has0) == len(per_track) and len(hasm) == len(per_track), "every track has a row at offset 0 and at -24 h")
    alive = (span["max"] - span["min"]) // step_s                       # last k of every track
    counts = first_d.groupby("time_offset_hours").size()
    k = np.round(counts.index.to_numpy() / step_h).astype(np.int64)
    expected_counts = np.array([len(alive) if kk < 0 else int((alive >= kk).sum()) for kk in k])
    report.check(bool(np.array_equal(counts.to_numpy(), expected_counts)), f"composite bins: the count of every one of the {len(counts)} offset bins equals the number of live tracks")
    # 4. join to the track file: the circle centre is the track position at track_time
    tr_keys = tr[tr["ok"]].assign(track_time=tr["base_time"])
    tr_keys["period"] = tr_keys["period"].astype(str)
    left = first_d[["period", "local_track", "track_time", "center_lat", "center_lon"]].drop_duplicates(["period", "local_track", "track_time"])
    left["period"] = left["period"].astype(str)
    joined = left.merge(tr_keys[["period", "local_track", "track_time", "meanlat", "meanlon"]], on=["period", "local_track", "track_time"], how="left")
    report.check(bool(joined["meanlat"].notna().all()), f"every track_time is a valid point of the track file (join of {len(left)} points)")
    report.check(bool((np.abs(joined["center_lat"] - joined["meanlat"]) < 1e-3).all() and (np.abs(joined["center_lon"] - joined["meanlon"]) < 1e-3).all()),
                 "circle centres equal the track positions")
    # 5. variables: NaN share before the start and in the track, NaN where the snapshot is missing, ranges
    groups = {g["name"]: g for g in meta["groups"]}
    dt_columns = {name: ("env_dt_hours" if i == 0 else f"env_dt_hours_{name}") for i, name in enumerate(groups)}
    variables = [c[: -len("_validfrac")] for c in df.columns if c.endswith("_validfrac")]
    pre = df["time_offset_hours"] < 0
    for var in variables:
        spec = meta["config"]["streams"]
        stream = next(s for s, v in spec.items() if var in v["variables"])
        group = next(n for n, g in groups.items() if stream in g["streams"])
        nan_all, nan_pre, nan_in = df[var].isna().mean(), df.loc[pre, var].isna().mean(), df.loc[~pre, var].isna().mean()
        # A variable that is all NaN fails, unless its whole stream group has no snapshot in this period (recorded in the file, for example the
        # 3-km TUNE prw after 2020-04-10), which is a known data gap and only a warning
        known_gap = groups[group]["n_samples_with_frame"] == 0
        text = f"{var:9s} [{group}] NaN share all {nan_all:6.1%}, before start {nan_pre:6.1%}, in track {nan_in:6.1%}"
        if nan_all == 1.0 and known_gap:
            report.line(f"WARN  {text}: the group {group} has no snapshot in this period (known data gap, recorded in the file)")
        else:
            report.check(nan_all < 1.0, text)
        no_frame = df[dt_columns[group]].isna()
        report.check(bool(df.loc[no_frame, var].isna().all()), f"{var:9s} is NaN wherever the snapshot of its group is missing ({int(no_frame.sum())} rows)")
        lo, hi = next(b for p, b in BOUNDS.items() if var.startswith(p))
        values = df[var].dropna()
        report.check(bool(((values >= lo) & (values <= hi)).all()), f"{var:9s} within [{lo:g}, {hi:g}] (min {values.min():.4g}, mean {values.mean():.4g}, max {values.max():.4g})")
    # 6. circles
    for col in [c for c in df.columns if c.startswith("n_cells")]:
        report.line(f"      {col}: mean cells per diameter {df.groupby('diameter_km', observed=True)[col].mean().round(2).to_dict()}, share with one cell "
                    f"{df.groupby('diameter_km', observed=True)[col].apply(lambda s: round(float((s == 1).mean()), 3)).to_dict()}")
    # 7. what the file says about missing frames
    for g in meta["groups"]:
        report.line(f"      group {g['name']}: {g['n_samples_without_frame']} of {meta['n_samples']} samples without a snapshot ({100 * g['samples_without_frame_fraction']:.2f} %); "
                    f"first nominal times: {g['nominal_times_without_frame_first200'][:3]}")


def brute_force_checks(df, src, n_rows, seed, index_dir, report):
    """Recompute random rows from the input files with plain netCDF4 and haversine distances and compare them with the file."""
    import netCDF4

    meta = df.attrs["mcs_env"]
    rng = np.random.default_rng(seed)
    rows = df.iloc[rng.choice(len(df), size=min(n_rows, len(df)), replace=False)]
    cache = {}                                                           # stream -> FileIndex, grid -> arrays

    def index_of(stream):
        """FileIndex of a stream (built once, reusing the cache of the extraction run). Args: stream name. Returns: FileIndex."""
        if stream not in cache:
            cfg = src["streams"][stream]
            cache[stream] = FileIndex.build(cfg["root"], cfg["pattern"], time_var=cfg.get("time_var", src["time_var"]), cache_path=os.path.join(index_dir, f"{src['name']}_{stream}.index.pkl"))
        return cache[stream]

    def grid_of(name):
        """Cell latitude, longitude (degrees) and weights of a grid read with plain netCDF4. Args: grid name. Returns: (lat, lon, weights)."""
        if ("grid", name) not in cache:
            gcfg, stream = src["grids"][name], src["streams"][src["grids"][name]["stream"]]
            path = str(index_of(src["grids"][name]["stream"]).paths[0])
            with netCDF4.Dataset(path) as ds:
                lat, lon = np.asarray(ds[gcfg.get("lat", "lat")][:], float), np.asarray(ds[gcfg.get("lon", "lon")][:], float)
                if stream["reader"] != "ncol":
                    lat, lon = np.meshgrid(lat, lon, indexing="ij")
                    lat, lon = lat.ravel(), lon.ravel()
                elif np.abs(lat).max() <= np.pi / 2 + 1e-6:
                    lat, lon = np.degrees(lat), np.degrees(lon)
                area = gcfg.get("area")
                weights = np.cos(np.radians(lat)) if area == "cos_lat" else (np.ones(lat.size) if area is None else np.asarray(ds[area][:], float))
            cache[("grid", name)] = (lat, lon, weights)
        return cache[("grid", name)]

    def raw(stream, name, level, when):
        """One raw field at an epoch time, read straight from the file (levels by value)."""
        paths, recs = index_of(stream).lookup(np.array([when]))
        if recs[0] < 0:
            return None
        with netCDF4.Dataset(paths[0]) as ds:
            v = ds.variables[name]
            if src["streams"][stream]["reader"] == "latlon_level":
                levels = np.asarray(ds.variables[src["streams"][stream].get("level_dim", "level")][:], float)
                a = v[int(recs[0]), int(np.flatnonzero(np.isclose(levels, level))[0]), :, :]
            else:
                a = v[int(recs[0]), ...]
        a = np.ma.filled(np.ma.asarray(a).astype(np.float32), np.nan).ravel()
        a[np.abs(a) > 1e30] = np.nan
        return a

    n_compared = n_bad = 0
    ps_cfg = src.get("ps")
    for rec in rows.itertuples(index=False):
        calendar = meta.get("calendar", "standard")
        nominal = int(to_model_axis(int(pd.Timestamp(rec.data_time).timestamp()), calendar))        # arithmetic on the model axis
        for stream, scfg in src["streams"].items():
            group = next(g for g in meta["groups"] if stream in g["streams"])
            dt_col = "env_dt_hours" if group is meta["groups"][0] else f"env_dt_hours_{group['name']}"
            dt = getattr(rec, dt_col)
            if np.isnan(dt):
                continue
            when = int(to_labels(nominal + int(round(dt * 3600)), calendar))                                 # back to the label that names the file record
            lat, lon, weights = grid_of(scfg["grid"])
            dist = haversine_km(rec.center_lat, rec.center_lon, lat, lon)
            inside = dist <= rec.diameter_km / 2
            if not inside.any():
                inside[np.argmin(dist)] = True
            ps = raw(ps_cfg["stream"], ps_cfg["var"], None, when) if ps_cfg else None
            for std, spec in scfg["variables"].items():
                level = spec.get("level_hpa")
                fields = {n: raw(stream, n, level, when) for n in raw_names(spec)}
                if any(f is None for f in fields.values()):
                    continue
                value = compute_variable(spec, fields)
                if ps_cfg and level is not None:
                    value = mask_below_ground(value, ps if ps is not None else np.full(value.shape, np.nan), level)
                w, v = weights[inside], value[inside]
                ok = np.isfinite(v)
                expected = (v[ok] * w[ok]).sum() / w[ok].sum() if ok.any() else np.nan
                got = getattr(rec, std)
                good = (np.isnan(expected) and np.isnan(got)) or (np.isfinite(expected) and np.isfinite(got) and abs(got - expected) <= 2e-5 * abs(expected) + 1e-9)
                n_compared += 1
                if not good:
                    n_bad += 1
                    report.line(f"      MISMATCH {std}: file {got!r} vs recomputed {expected!r} (track {rec.local_track}, offset {rec.time_offset_hours}, d {rec.diameter_km})")
    report.check(n_bad == 0 and n_compared > 0, f"independent recomputation: {n_compared} values of {len(rows)} random rows, {n_bad} mismatches")


def main():
    """Run the checks on one output file and exit with status 1 when a check failed."""
    here = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description="Check an extract_mcs_env.py output file by its contents.")
    parser.add_argument("file", help="output Parquet file")
    parser.add_argument("--config", default=os.path.join(here, "config", "sources.yaml"), help="sources.yaml (default: config/sources.yaml)")
    parser.add_argument("--brute-force", type=int, default=0, metavar="N", help="recompute N random rows from the input files (default 0 = off)")
    parser.add_argument("--seed", type=int, default=0, help="random seed of the row selection (default 0)")
    args = parser.parse_args()
    report = Report()
    df = read_mcs_env(args.file)
    meta = df.attrs["mcs_env"]
    src = load_config(args.config, meta["source"])
    src.update({k: meta["config"][k] for k in ("streams", "grids", "ps", "diameters_km") if k in meta["config"]})      # the settings the file was made with
    structural_checks(df, meta["tracks_file"], report)
    if args.brute_force:
        brute_force_checks(df, src, args.brute_force, args.seed, os.path.join(os.path.dirname(os.path.abspath(args.file)), "_index"), report)
    print(f"\n{'ALL CHECKS PASSED' if not report.failures else str(len(report.failures)) + ' CHECKS FAILED'}")
    sys.exit(1 if report.failures else 0)


if __name__ == "__main__":
    main()
