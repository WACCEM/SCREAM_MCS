"""The extraction job: streams and groups, tasks, part files, assembly.

Flow of one source and one year (``period``):

1. the sample table of the tracks of that year (``tracks.build_samples``): one row per (track, nominal time), with the circle centre;
2. the streams of the source are indexed (``FileIndex``) and **grouped** by (grid, step, phase of the time axis): the streams of one group share one
   circle search per time step (ERA5: pressure-level and surface streams; SCREAM-decadal: the 3-hourly and the 6-hourly streams are two groups);
3. every sample is assigned, per group, the environment snapshot nearest to its nominal time (``fileindex.nearest_time``, accepted only within half a
   step, otherwise the frame is missing and the values stay NaN);
4. **tasks** (group, one calendar day of snapshots) run in a ``fork`` process pool; each task reads the variables of its snapshots, builds the circles
   of all samples that use the snapshot, computes the weighted means for all diameters and writes ONE part file (Parquet allows one writer per file, so
   parallelism is one file per task; finished parts are skipped when a job is started again);
5. the parent assembles the parts by sample id into the long table (track, time, diameter) and writes the final Parquet file with metadata.

For a noleap source (SCREAM, E3SM) all time arithmetic runs on the model axis without 29 February (``modelcal``); the output carries calendar labels.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from . import __version__
from .config import LONG_NAMES, ConfigError, variable_order
from .derive import compute_variable, mask_below_ground, raw_names
from .fileindex import FileIndex, nearest_time
from .grid import GridSearch, weighted_mean
from .modelcal import leap_day_labels_present, to_labels, to_model_axis
from .outputs import timestamp_array, write_mcs_env
from .readers import make_reader
from .tracks import build_samples, load_tracks

# The job that the forked workers inherit (set before the pool is created, so nothing large is pickled)
_JOB = None


def log(message):
    """Print a time-stamped message and flush (the jobs write to log files)."""
    print(f"{time.strftime('%H:%M:%S')} {message}", flush=True)


def _iso(epoch_s):
    """ISO string (UTC) of an epoch second."""
    return datetime.fromtimestamp(int(epoch_s), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _day_label(epoch_s):
    """``YYYYMMDD`` (UTC) of an epoch second (used in part file names)."""
    return time.strftime("%Y%m%d", time.gmtime(int(epoch_s)))


# ----------------------------------------------------------------------------------------------------------------------------------
# Streams, grids and groups
# ----------------------------------------------------------------------------------------------------------------------------------
def build_streams(src, index_dir=None, nproc=1):
    """Index every stream of a source and create its reader.

    Args:
        src: merged source configuration.
        index_dir: folder for the cached file indexes (default None = no cache).
        nproc: processes for scanning files (default 1).

    Returns:
        dictionary stream name -> namespace(name, cfg, reader, index).
    """
    states = {}
    for name, cfg in src["streams"].items():
        cache = os.path.join(index_dir, f"{src['name']}_{name}.index.pkl") if index_dir else None
        index = FileIndex.build(cfg["root"], cfg["pattern"], time_var=cfg.get("time_var", src["time_var"]), nproc=nproc, cache_path=cache, log=log)
        if index.times_s.size < 2 or index.step_s <= 0:
            raise ConfigError(f"stream {name}: fewer than two times found ({index.times_s.size}); cannot determine the time step")
        states[name] = SimpleNamespace(name=name, cfg=cfg, reader=make_reader(cfg), index=index)
    return states


def source_calendar(src, states):
    """The calendar of a source: ``noleap`` or ``standard``, the same for all its streams.

    Args:
        src: merged source configuration.
        states: result of ``build_streams``.

    Returns:
        ``"noleap"`` or ``"standard"`` (a source whose streams disagree is a configuration error).
    """
    kinds = {state.index.calendar for state in states.values()}
    if len(kinds) != 1:
        raise ConfigError(f"source {src['name']}: the streams use different calendars {sorted(map(str, kinds))}; the tracks can only follow one")
    return kinds.pop()


def build_grids(src, states):
    """Read the cell centres of every grid of the source from the first file of its stream and build the KD-trees.

    Args:
        src: merged source configuration.
        states: result of ``build_streams``.

    Returns:
        dictionary grid name -> ``GridSearch``.
    """
    grids = {}
    for name, gcfg in src["grids"].items():
        state = states[gcfg["stream"]]
        info = state.reader.read_grid(str(state.index.paths[0]), gcfg)
        grids[name] = GridSearch(info["lat_deg"], info["lon_deg"], info["area"] if src["weighting"] == "area" else None, src["earth_radius_km"])
        log(f"  grid {name}: {grids[name].n_cells} cells from {os.path.basename(str(state.index.paths[0]))}")
    return grids


def build_groups(src, states, grids, calendar="standard"):
    """Group the streams by (grid, step, phase of the time axis) and align every stream to the group's time axis.

    Args:
        src: merged source configuration.
        states: result of ``build_streams``.
        grids: result of ``build_grids``.
        calendar: ``"noleap"`` or ``"standard"``, the calendar of the source; for noleap the group axis is the model axis (default ``"standard"``).

    Returns:
        list of group namespaces, the finest step first (group 0 is the *primary* group): gid, name, grid_name, grid, step_s, axis (union of the
        stream times on the model axis), axis_label (the same times as calendar labels, used to locate the files), streams (each with ``paths`` and ``recs`` per axis time and ``needed`` = raw (name, level) pairs to read), variables
        (list of (standard name, spec, stream)).
    """
    # Streams that can share a circle search: same grid, same step, same phase of the axis within the step
    keyed = {}
    for state in states.values():
        step = int(state.index.step_s)
        keyed.setdefault((state.cfg["grid"], step, int(state.index.times_s[0] % step)), []).append(state)
    order = sorted(keyed.items(), key=lambda kv: (kv[0][1], list(states).index(kv[1][0].name)))
    ps_cfg = src.get("ps")
    groups = []
    for gid, ((grid_name, step_s, _phase), members) in enumerate(order):
        axis_label = np.unique(np.concatenate([s.index.times_s for s in members]))
        axis = to_model_axis(axis_label, calendar)
        variables = []
        for state in members:
            state.paths, state.recs = state.index.lookup(axis_label)
            variables += [(std, spec, state) for std, spec in state.cfg["variables"].items()]
        # Raw (name, level) pairs each stream has to read for its variables, plus the surface pressure where it lives
        for state in members:
            needed = set()
            for _std, spec, st in variables:
                if st is state:
                    level = spec.get("level_hpa") if state.reader.uses_level else None
                    needed.update((name, level) for name in raw_names(spec))
            if ps_cfg and ps_cfg["stream"] == state.name:
                needed.add((ps_cfg["var"], None))
            state.needed = sorted(needed, key=lambda item: (item[0], -1.0 if item[1] is None else float(item[1])))
        groups.append(SimpleNamespace(gid=gid, name=members[0].name, grid_name=grid_name, grid=grids[grid_name], step_s=step_s,
                                      axis=axis, axis_label=axis_label, streams=members, variables=variables))
    # The surface pressure must be in the same group as every variable that is masked with it (same cells, same snapshot)
    if ps_cfg:
        ps_group = next(g.gid for g in groups if any(s.name == ps_cfg["stream"] for s in g.streams))
        for group in groups:
            for std, spec, _state in group.variables:
                if "level_hpa" in spec and group.gid != ps_group:
                    raise ConfigError(f"variable {std} is masked with the surface pressure of stream {ps_cfg['stream']}, which is on another grid or "
                                      f"time axis; set ps to null or move the variable")
    return groups


# ----------------------------------------------------------------------------------------------------------------------------------
# Environment frames per sample and the tasks
# ----------------------------------------------------------------------------------------------------------------------------------
def assign_frames(group, samples):
    """Assign every sample its environment snapshot in a group and cut the work into tasks (one calendar day of snapshots each).

    Args:
        group: group namespace (modified: ``env_row``, ``env_dt_s``, ``order``, ``urows``, ``ustart``, ``uend``, ``tasks`` are set).
        samples: ``Samples`` of the year.

    Returns:
        None.
    """
    # Nearest snapshot within half a step (-1 = missing frame); the shift is snapshot time minus nominal time
    group.env_row, group.env_dt_s = nearest_time(group.axis, samples.data_time, group.step_s)
    valid = np.flatnonzero(group.env_row >= 0)
    # Samples ordered by snapshot, so that the samples of one snapshot are one slice; unique snapshots with the slice bounds
    group.order = valid[np.argsort(group.env_row[valid], kind="stable")]
    group.urows, group.ustart = np.unique(group.env_row[group.order], return_index=True)
    group.uend = np.r_[group.ustart[1:], group.order.size]
    # One task per calendar day of snapshots
    days = group.axis[group.urows] // 86400
    day_first = np.r_[0, np.flatnonzero(np.diff(days)) + 1] if days.size else np.zeros(0, dtype=np.int64)
    day_last = np.r_[day_first[1:], days.size] if days.size else np.zeros(0, dtype=np.int64)
    group.tasks = [(group.gid, int(a), int(b)) for a, b in zip(day_first, day_last)]


def _read_group_slice(job, group, axis_row, handles):
    """Values of all standard variables of a group at one snapshot, masked below ground.

    Args:
        job: job namespace.
        group: group namespace.
        axis_row: index of the snapshot in the group's time axis.
        handles: dictionary path -> open dataset (files stay open for the whole task).

    Returns:
        array (n_cells, n_variables) float64, NaN where a variable is invalid or its stream has no frame at this time.
    """
    # Step 1: read every raw (name, level) that each stream needs; a stream without a frame at this time contributes nothing
    arrays = {}
    for state in group.streams:
        record = int(state.recs[axis_row])
        if record < 0:
            continue
        path = str(state.paths[axis_row])
        if path not in handles:
            handles[path] = state.reader.open(path)
        for name, level in state.needed:
            values = state.reader.read(handles[path], name, record, level)
            if values.size != group.grid.n_cells:
                raise ValueError(f"{path}: {name} has {values.size} cells, the grid {group.grid_name} has {group.grid.n_cells}")
            arrays[(state.name, name, level)] = values
    ps_cfg = job.cfg.get("ps")
    ps = arrays.get((ps_cfg["stream"], ps_cfg["var"], None)) if ps_cfg else None
    # Step 2: standard variables: derive, convert, mask below ground
    out = np.full((group.grid.n_cells, len(group.variables)), np.nan)
    for j, (_std, spec, state) in enumerate(group.variables):
        level = spec.get("level_hpa") if state.reader.uses_level else None
        raw = {name: arrays.get((state.name, name, level)) for name in raw_names(spec)}
        if any(values is None for values in raw.values()):
            continue
        value = compute_variable(spec, raw)
        if ps_cfg and "level_hpa" in spec:
            # Without a surface pressure at this time the level cannot be trusted: the whole field stays NaN
            value = mask_below_ground(value, ps if ps is not None else np.full(value.shape, np.nan), spec["level_hpa"])
        out[:, j] = value
    return out


def _run_task(spec):
    """Worker: compute one task (a group and a range of its snapshots) and write its part file.

    Args:
        spec: (group id, first snapshot, end snapshot) indices into the group's unique snapshots.

    Returns:
        (spec, status, rows): status ``"done"`` or ``"skipped"`` (part exists), and the number of rows written.
    """
    job = _JOB
    gid, lo, hi = spec
    group = job.groups[gid]
    part = os.path.join(job.parts_dir, f"g{gid}_{_day_label(group.axis_label[group.urows[lo]])}.parquet")
    if os.path.exists(part):
        return spec, "skipped", 0
    names = [std for std, _spec, _state in group.variables]
    nd, nv = len(job.diameters), len(names)
    sids, ncells, means, fracs = [], [], [], []
    handles = {}
    try:
        # Loop over the snapshots of the task (one calendar day): read once, serve all samples that use the snapshot
        for u in range(lo, hi):
            sid = group.order[group.ustart[u]:group.uend[u]]
            values = _read_group_slice(job, group, int(group.urows[u]), handles)
            # The circles of all samples of this snapshot (one search for all diameters) and the area-weighted means
            matrices, n_cells = group.grid.circle_weights(job.samples.center_lat[sid], job.samples.center_lon[sid], job.diameters, job.cfg["empty_circle"])
            mean = np.empty((sid.size, nd, nv))
            frac = np.empty((sid.size, nd, nv))
            for d, matrix in enumerate(matrices):
                mean[:, d, :], frac[:, d, :] = weighted_mean(matrix, values)
            sids.append(sid), ncells.append(n_cells), means.append(mean), fracs.append(frac)
    finally:
        for dataset in handles.values():
            dataset.close()
    # One part table: a row per (sample, diameter), sample-major
    sid_all = np.concatenate(sids)
    mean_all = np.concatenate(means).reshape(-1, nv)
    frac_all = np.concatenate(fracs).reshape(-1, nv)
    columns = {"sample_id": pa.array(np.repeat(sid_all, nd)), "diam_idx": pa.array(np.tile(np.arange(nd, dtype=np.int8), sid_all.size)),
               "n_cells": pa.array(np.concatenate(ncells).reshape(-1).astype(np.int32))}
    for j, name in enumerate(names):
        columns[name] = pa.array(mean_all[:, j].astype(np.float32))
        columns[f"{name}_validfrac"] = pa.array(frac_all[:, j].astype(np.float32))
    tmp = f"{part}.tmp{os.getpid()}"
    pq.write_table(pa.table(columns), tmp, compression="zstd")
    os.replace(tmp, part)
    return spec, "done", sid_all.size * nd


def run_tasks(job, nproc, tasks):
    """Run all tasks, in a process pool when ``nproc`` > 1.

    Args:
        job: job namespace (inherited by the workers through ``fork``).
        nproc: number of worker processes (1 = run in this process).
        tasks: list of task specs.

    Returns:
        None. An exception in a task stops the job.
    """
    global _JOB
    _JOB = job
    done, started = 0, time.time()
    report_every = max(1, len(tasks) // 20)
    if nproc <= 1:
        results = (_run_task(t) for t in tasks)
        pool = None
    else:
        pool = mp.get_context("fork").Pool(nproc)
        results = pool.imap_unordered(_run_task, tasks, chunksize=1)
    try:
        for _spec, _status, _rows in results:
            done += 1
            if done % report_every == 0 or done == len(tasks):
                log(f"  tasks {done}/{len(tasks)} ({time.time() - started:.0f} s)")
        if pool is not None:
            pool.close()
    except BaseException:
        # A failed task must stop the job at once, not after the remaining queued tasks have run
        if pool is not None:
            pool.terminate()
        raise
    finally:
        if pool is not None:
            pool.join()
        _JOB = None


# ----------------------------------------------------------------------------------------------------------------------------------
# Assembly and metadata
# ----------------------------------------------------------------------------------------------------------------------------------
def _git_hash(path):
    """Git commit hash of the repository that holds ``path`` (``"unknown"`` when it cannot be determined)."""
    try:
        result = subprocess.run(["git", "-C", path, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _library_versions():
    """Versions of the libraries behind the numbers (stored in the file metadata)."""
    import netCDF4
    import scipy

    return {"python": sys.version.split()[0], "numpy": np.__version__, "scipy": scipy.__version__, "pyarrow": pa.__version__, "netCDF4": netCDF4.__version__}


def _variable_meta(std, spec, state, group, has_ps):
    """Column metadata of one standard variable (units, long name, source variables, conversion)."""
    conversion = {key: spec[key] for key in ("derive", "scale", "offset", "level_hpa", "rh_units") if key in spec}
    if "inputs" in spec:
        conversion["inputs"] = spec["inputs"]
    return {"units": spec.get("units", ""), "long_name": spec.get("long_name", LONG_NAMES.get(std, std)),
            "source_variables": ",".join(raw_names(spec)), "stream": state.name, "grid": group.grid_name,
            "conversion": json.dumps(conversion), "masked_below_ground": str(bool(has_ps and "level_hpa" in spec))}


def assemble(job):
    """Combine the part files into the final long table and its metadata.

    Args:
        job: job namespace after all tasks ran.

    Returns:
        (columns, column_meta, file_meta) for ``outputs.write_mcs_env``.
    """
    samples, nd, ns = job.samples, len(job.diameters), len(job.samples)
    rep = lambda a: np.repeat(a, nd)  # noqa: E731  (each sample once per diameter, sample-major)
    # Step 1: results per group, placed by sample id and diameter index (NaN / 0 where a group has no frame for a sample)
    results, ncell_by_grid, dt_by_group, group_meta = {}, {}, {}, []
    for group in job.groups:
        mean = {std: np.full((ns, nd), np.nan, dtype=np.float32) for std, _s, _st in group.variables}
        frac = {std: np.full((ns, nd), np.nan, dtype=np.float32) for std, _s, _st in group.variables}
        ncell = ncell_by_grid.setdefault(group.grid_name, np.zeros((ns, nd), dtype=np.int32))
        files = sorted(f for f in os.listdir(job.parts_dir) if f.startswith(f"g{group.gid}_") and f.endswith(".parquet"))
        if files:
            table = pa.concat_tables([pq.read_table(os.path.join(job.parts_dir, f)) for f in files])
            sid, di = table["sample_id"].to_numpy(), table["diam_idx"].to_numpy().astype(np.int64)
            ncell[sid, di] = table["n_cells"].to_numpy()
            for std in mean:
                mean[std][sid, di] = table[std].to_numpy()
                frac[std][sid, di] = table[f"{std}_validfrac"].to_numpy()
        for std in mean:
            results[std] = (mean[std], frac[std])
        dt_by_group[group.gid] = np.where(group.env_row >= 0, group.env_dt_s / 3600.0, np.nan).astype(np.float32)
        missing = np.flatnonzero(group.env_row < 0)
        group_meta.append({
            "name": group.name, "grid": group.grid_name, "step_hours": group.step_s / 3600.0, "streams": [s.name for s in group.streams],
            "axis_first": _iso(group.axis_label[0]), "axis_last": _iso(group.axis_label[-1]),
            "n_samples_with_frame": int(ns - missing.size), "n_samples_without_frame": int(missing.size),
            "samples_without_frame_fraction": float(missing.size / max(ns, 1)),
            "nominal_times_without_frame_first200": [_iso(t) for t in to_labels(np.unique(samples.data_time[missing])[:200], job.calendar)],
        })
    # Step 2: columns in a fixed order, every sample repeated for each diameter
    primary_grid = job.groups[0].grid_name
    d_is_int = all(float(d).is_integer() for d in job.diameters)
    columns = {
        "period": pa.array(rep(samples.period.astype(str))).dictionary_encode(),
        "local_track": pa.array(rep(samples.local_track)),
        "time_offset_hours": pa.array(rep(samples.time_offset_hours)),
        "data_time": timestamp_array(rep(to_labels(samples.data_time, job.calendar))),
        "track_time": timestamp_array(rep(to_labels(samples.track_time, job.calendar))),
        "track_dt_hours": pa.array(rep(samples.track_dt_hours)),
        "center_lat": pa.array(rep(samples.center_lat).astype(np.float32)),
        "center_lon": pa.array(rep(samples.center_lon).astype(np.float32)),
        "diameter_km": pa.array(np.tile(np.asarray(job.diameters).astype(np.int16 if d_is_int else np.float32), ns)),
    }
    meta = {
        "time_offset_hours": {"units": "h", "long_name": "nominal offset from the track start (k * step), the same grid for every track (composite axis)"},
        "data_time": {"units": "UTC", "long_name": "nominal time = track start + time_offset_hours"},
        "track_time": {"units": "UTC", "long_name": "time of the track point used as circle centre (join key to base_time of the MCS track file)"},
        "track_dt_hours": {"units": "h", "long_name": "nominal time (clamped to the track) minus track_time; 0 unless the track has no valid point at that time"},
        "center_lat": {"units": "degrees_north", "long_name": "circle centre latitude (track meanlat)"},
        "center_lon": {"units": "degrees_east", "long_name": "circle centre longitude (track meanlon, as in the track file)"},
        "diameter_km": {"units": "km", "long_name": "circle diameter"},
    }
    for group in job.groups:
        suffix = "" if group.gid == 0 else f"_{group.name}"
        columns[f"env_dt_hours{suffix}"] = pa.array(rep(dt_by_group[group.gid]))
        meta[f"env_dt_hours{suffix}"] = {"units": "h", "long_name": f"environment snapshot time minus nominal time, stream group {group.name} (NaN = frame missing)"}
    for grid_name, ncell in ncell_by_grid.items():
        suffix = "" if grid_name == primary_grid else f"_{grid_name}"
        columns[f"n_cells{suffix}"] = pa.array(ncell.reshape(-1))
        meta[f"n_cells{suffix}"] = {"units": "1", "long_name": f"cells of grid {grid_name} inside the circle (nearest cell when empty; 0 = no frame)"}
    has_ps = bool(job.cfg.get("ps"))
    for std, _sname, _spec in variable_order(job.cfg):
        group = next(g for g in job.groups for s, _sp, _st in g.variables if s == std)
        spec, state = next((sp, st) for s, sp, st in group.variables if s == std)
        columns[std] = pa.array(results[std][0].reshape(-1))
        columns[f"{std}_validfrac"] = pa.array(results[std][1].reshape(-1))
        meta[std] = _variable_meta(std, spec, state, group, has_ps)
        meta[f"{std}_validfrac"] = {"units": "1", "long_name": f"fraction of the circle weight with valid {std}"}
    # Step 3: the file-level document
    file_meta = {
        "package": "mcsenv", "version": __version__, "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_hash": _git_hash(os.path.dirname(os.path.abspath(__file__))), "libraries": _library_versions(),
        "source": job.cfg["name"], "label": job.cfg.get("label", job.cfg["name"]), "period": job.period, "calendar": job.calendar,
        "tracks_file": job.cfg["tracks"], "track_start_range": [job.start_date, job.end_date], "n_tracks": samples.n_tracks, "n_tracks_without_position": samples.n_tracks_skipped,
        "n_track_rows_dropped_nan_position": samples.n_rows_dropped, "n_samples": ns, "n_rows": ns * nd,
        "diameters_km": [float(d) for d in job.diameters], "step_hours": samples.step_s / 3600.0, "pre_start_hours": job.cfg["pre_start_hours"],
        "weighting": job.cfg["weighting"], "empty_circle": job.cfg["empty_circle"], "earth_radius_km": job.cfg["earth_radius_km"],
        "rules": ("rows at nominal offsets k*step from the track start (same for every track; for calendar noleap the arithmetic skips 29 February, as the "
                  "model does); circle centre = valid track point nearest to the "
                  "nominal time clamped to the track (ties: earlier), the start position before the start; environment = nearest snapshot within half "
                  "a step (ties: earlier), NaN when missing; circle = cell centres within diameter/2 (great circle), area-weighted mean over valid cells"),
        "groups": group_meta,
        "streams": {s.name: {"root": s.cfg["root"], "pattern": s.cfg["pattern"], "n_files": len(s.index.files), "n_times": int(s.index.times_s.size),
                             "step_hours": s.index.step_s / 3600.0, "first": _iso(s.index.times_s[0]), "last": _iso(s.index.times_s[-1]),
                             "empty_files": [os.path.basename(f) for f in s.index.empty_files][:50],
                             "unreadable_files": {os.path.basename(k): v for k, v in list(s.index.unreadable.items())[:50]},
                             "duplicate_times": s.index.n_duplicates} for g in job.groups for s in g.streams},
        "config": job.cfg,
    }
    return columns, meta, file_meta


# ----------------------------------------------------------------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------------------------------------------------------------
def _signature(job):
    """Fingerprint of everything that decides the content of the part files (stale parts of another setup are discarded)."""
    payload = json.dumps({"v": __version__, "cfg": job.cfg, "diameters": list(job.diameters), "n": len(job.samples), "period": job.period,
                          "step_s": job.samples.step_s, "t": [int(job.samples.data_time[0]), int(job.samples.data_time[-1])]},
                         sort_keys=True, default=str)
    return hashlib.sha1(payload.encode()).hexdigest()


def run_source(src, years, out_dir, nproc=1, start_date=None, end_date=None, index_dir=None, tracks=None, index_nproc=None):
    """Run the extraction of one source for the given years and write one Parquet file per year.

    Args:
        src: merged source configuration (``config.load_config``), possibly with ``diameters_km`` etc. overridden.
        years: list of ``period`` years to process (each gives its own file).
        out_dir: output folder; the files go to ``<out_dir>/<source>/mcs_env_<source>_<year>.parquet``.
        nproc: worker processes (default 1).
        start_date, end_date: keep only tracks that start in this range (testing; the file name gets the dates; default None).
        index_dir: folder for the cached file indexes (default ``<out_dir>/<source>/_index``).
        tracks: DataFrame of tracks (as ``load_tracks`` returns) instead of reading ``src['tracks']`` (tests; default None).
        index_nproc: processes for scanning files (default ``nproc``).

    Returns:
        list of the written file paths.
    """
    t_start = time.time()
    source_dir = os.path.join(out_dir, src["name"])
    index_dir = index_dir or os.path.join(source_dir, "_index")
    log(f"source {src['name']}: years {list(years)}, diameters {src['diameters_km']} km, nproc {nproc}")
    # Streams, grids, groups: once for all years
    states = build_streams(src, index_dir, index_nproc or nproc)
    grids = build_grids(src, states)
    calendar = source_calendar(src, states)
    groups = build_groups(src, states, grids, calendar)
    log(f"  calendar {calendar}")
    step_hours = float(src["step_hours"]) if src["step_hours"] is not None else groups[0].step_s / 3600.0
    if abs(step_hours - round(step_hours)) > 1e-9 or step_hours < 1:
        raise ConfigError(f"the nominal step must be a whole number of hours (the tracks are hourly), not {step_hours}")
    for group in groups:
        log(f"  group {group.name}: grid {group.grid_name}, step {group.step_s / 3600:g} h, {group.axis.size} times {_iso(group.axis_label[0])} .. "
            f"{_iso(group.axis_label[-1])}, streams {[s.name for s in group.streams]}")
    written = []
    for year in years:
        # Tracks of the year and the sample table
        if tracks is None:
            tr = load_tracks(src["tracks"], periods=[year], start_date=start_date, end_date=end_date)
        else:
            tr = tracks[tracks["period"] == str(year)].reset_index(drop=True)
        if len(tr) == 0:
            log(f"year {year}: no tracks, skipped")
            continue
        # A noleap model has no 29 February: the track times must not have one either, and all arithmetic runs on the model axis
        if calendar == "noleap":
            if leap_day_labels_present(tr["t"].to_numpy()):
                raise ConfigError(f"source {src['name']}: the track file has times on 29 February but the environment files use a noleap calendar")
            tr = tr.assign(t=to_model_axis(tr["t"].to_numpy(), calendar))
        samples = build_samples(tr, step_hours, src["pre_start_hours"])
        log(f"year {year}: {samples.n_tracks} tracks ({samples.n_tracks_skipped} without a position), {len(samples)} samples, "
            f"{len(samples) * len(src['diameters_km'])} rows, step {step_hours:g} h")
        # Frames per group and the guard against too many missing frames in the primary group (fail before any work)
        for group in groups:
            assign_frames(group, samples)
            share = float((group.env_row < 0).mean())
            log(f"  group {group.name}: {int((group.env_row < 0).sum())} of {len(samples)} samples ({100 * share:.2f} %) without a snapshot, {len(group.tasks)} tasks")
            if group.gid == 0 and share > src["max_missing_fraction"]:
                raise RuntimeError(f"{100 * share:.2f} % of the samples have no snapshot in the primary group {group.name}, more than max_missing_fraction "
                                   f"{src['max_missing_fraction']}; nothing is written (wrong paths or time axis?)")
        tasks = [t for group in groups for t in group.tasks]
        if not tasks:
            raise RuntimeError("no environment snapshot covers any sample")
        suffix = f"_{start_date}_{end_date}".replace("-", "") if (start_date or end_date) else ""
        job = SimpleNamespace(cfg=src, samples=samples, groups=groups, diameters=[float(d) for d in src["diameters_km"]], period=str(year), calendar=calendar,
                              start_date=start_date, end_date=end_date, parts_dir=os.path.join(source_dir, "_parts", f"{year}{suffix}"))
        # Parts of an earlier run are reused only when everything that decides their content is unchanged
        signature = _signature(job)
        marker = os.path.join(job.parts_dir, "signature.txt")
        if os.path.isdir(job.parts_dir) and not (os.path.exists(marker) and open(marker).read() == signature):
            log("  parts of an earlier run with other settings found: removed")
            shutil.rmtree(job.parts_dir)
        os.makedirs(job.parts_dir, exist_ok=True)
        with open(marker, "w") as handle:
            handle.write(signature)
        run_tasks(job, nproc, tasks)
        columns, meta, file_meta = assemble(job)
        path = os.path.join(source_dir, f"mcs_env_{src['name']}_{year}{suffix}.parquet")
        write_mcs_env(path, columns, meta, file_meta)
        shutil.rmtree(job.parts_dir)
        log(f"year {year}: wrote {path} ({os.path.getsize(path) / 1e6:.1f} MB, {len(samples) * len(job.diameters)} rows)")
        written.append(path)
    log(f"done in {time.time() - t_start:.0f} s")
    return written
