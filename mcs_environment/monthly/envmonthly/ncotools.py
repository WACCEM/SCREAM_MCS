"""NCO / ESMF helpers: grid files, bilinear weights, applying a weight file, weight checks, worker counts.

The small utilities (``find_tool``, ``run_tool``, the worker-count helpers) are copied from ``e3sm_polun/regrid/remap_e3sm.py`` so that this
folder does not depend on another repository. ``ncremap`` is a script that calls ``ncks`` by name, so the folder of the program is put first on
PATH, and stdin is closed because ncremap otherwise waits for EOF on a piped stdin.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Sequence

import netCDF4
import numpy as np

# E3SM-unified's NCO / ESMF programs (the folder the other NERSC remap scripts of this project use)
DEFAULT_NCO_BIN = "/global/common/software/e3sm/anaconda_envs/e3smu_1_13_0/pm-cpu/pixi_login/.pixi/envs/default/bin"
# Native libraries must not start thread teams in every worker; HDF5 file locks fail on some Lustre mounts
THREAD_ENV = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
              "HDF5_USE_FILE_LOCKING": "FALSE", "TERM": "dumb"}


def find_tool(name, nco_bin=DEFAULT_NCO_BIN):
    """Path of an NCO / ESMF program.

    Args:
        name: program name, for example ``"ncremap"``.
        nco_bin: folder searched first (default: E3SM-unified bin); PATH is the second choice.

    Returns:
        full path (str). Raises ``FileNotFoundError`` with a hint when the program is nowhere.
    """
    # The configured folder first, then PATH
    cand = Path(nco_bin) / name
    if cand.exists():
        return str(cand)
    found = shutil.which(name)
    if not found:
        raise FileNotFoundError(f"{name} not found in {nco_bin} or on PATH (on NERSC use the E3SM-unified bin folder)")
    return found


def run_tool(cmd, env_extra=None, cwd=None):
    """Run one command with stdin closed and its own folder first on PATH.

    Args:
        cmd: list of command words (the first is the full path of the program).
        env_extra: dictionary of extra environment variables (default None).
        cwd: working directory (default None = current).

    Returns:
        stdout (str). Raises ``RuntimeError`` with the tail of the output when the exit code is not zero.
    """
    # The environment: thread limits, and the program's folder first on PATH (ncremap calls ncks by name)
    env = dict(os.environ, **THREAD_ENV, **(env_extra or {}))
    env["PATH"] = str(Path(cmd[0]).resolve().parent) + os.pathsep + env.get("PATH", "")
    proc = subprocess.run([str(c) for c in cmd], stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env,
                          cwd=str(cwd) if cwd else None)
    if proc.returncode != 0:
        raise RuntimeError(f"{Path(cmd[0]).name} failed ({proc.returncode}): {(proc.stderr or proc.stdout).strip()[-1200:]}")
    return proc.stdout or ""


def node_kind():
    """``"compute"`` inside a Slurm allocation, else ``"login"`` (a shared login node: keep heavy work off it)."""
    return "compute" if "SLURM_JOB_ID" in os.environ else "login"


def physical_cores():
    """Physical cores this process may use (logical CPUs of the affinity mask divided by the SMT width)."""
    # Logical CPUs of the affinity mask
    try:
        logical = len(os.sched_getaffinity(0))
    except AttributeError:
        logical = os.cpu_count() or 1
    # SMT width from the sibling list of cpu0
    try:
        siblings = Path("/sys/devices/system/cpu/cpu0/topology/thread_siblings_list").read_text().strip()
        width = sum((int(p.split("-")[1]) - int(p.split("-")[0]) + 1) if "-" in p else 1 for p in siblings.split(","))
        return max(logical // max(width, 1), 1)
    except (OSError, ValueError, IndexError):
        return logical


def memory_gb():
    """Memory this job may use in GB: the Slurm allocation if given, else the total of the machine (an exclusive node)."""
    env = os.environ
    if env.get("SLURM_MEM_PER_NODE", "").isdigit():
        return int(env["SLURM_MEM_PER_NODE"]) / 1024.0
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) / 1024.0 / 1024.0
    except OSError:
        pass
    return 8.0


def default_workers(gb_per_worker=3.0):
    """Worker processes from cores and memory: ``min(cores, 0.8 * memory / gb_per_worker)``, at most 4 on a login node.

    Args:
        gb_per_worker: memory one worker needs in GB (default 3.0).

    Returns:
        number of workers (int >= 1).
    """
    n = max(1, min(physical_cores(), int(0.8 * memory_gb() / max(gb_per_worker, 0.1))))
    return min(n, 4) if node_kind() == "login" else n


# --------------------------------------------------------------------------------------------------------------------------------
# Grid files and weights
# --------------------------------------------------------------------------------------------------------------------------------
def make_grid_file(generate, out, nco_bin=DEFAULT_NCO_BIN):
    """Write a SCRIP grid file of a regular lat-lon grid with ``ncremap -G``.

    Args:
        generate: ncremap grid string, for example ``"latlon=180,360#lat_typ=uni#lon_typ=180_wst"``.
        out: output SCRIP file.
        nco_bin: folder of the NCO programs.

    Returns:
        path of the file (str); an existing file is kept.
    """
    # An existing grid file is reused
    out = Path(out)
    if out.exists():
        return str(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Written under a temporary name and renamed when complete
    part = out.with_name(out.name + ".part")
    try:
        run_tool([find_tool("ncremap", nco_bin), "--no_stdin", "-G", f"ttl={out.stem}#{generate}", "-g", str(part)])
        os.replace(part, out)
    finally:
        if part.exists():
            part.unlink()
    return str(out)


def make_weights(src_grid, dst_grid, map_out, method="bilinear", options="--no_log --ignore_unmapped --netcdf4", nco_bin=DEFAULT_NCO_BIN):
    """Build an ESMF weight file from two SCRIP grid files with ``ncremap``.

    Args:
        src_grid, dst_grid: SCRIP grid files of the source and the destination.
        map_out: weight file to write; an existing file is kept.
        method: ESMF method (default ``"bilinear"``).
        options: ESMF_RegridWeightGen options passed with ``-W``; the destination is global, so no ``--dst_regional``.
        nco_bin: folder of the NCO programs.

    Returns:
        path of the weight file (str).
    """
    map_out = Path(map_out)
    if map_out.exists():
        return str(map_out)
    map_out.parent.mkdir(parents=True, exist_ok=True)
    part = map_out.with_name(map_out.name + ".part")
    try:
        # ESMF drops PET log files into the working directory: run it in a temporary one
        with tempfile.TemporaryDirectory(dir=map_out.parent, prefix=".weights_") as tmp:
            cmd = [find_tool("ncremap", nco_bin), "--no_stdin", "-a", method, "-s", str(Path(src_grid).resolve()),
                   "-g", str(Path(dst_grid).resolve()), "-m", str(part), "--devnull=No", "-W", options]
            run_tool(cmd, env_extra={"TMPDIR": tmp}, cwd=tmp)
        os.replace(part, map_out)
    finally:
        if part.exists():
            part.unlink()
    return str(map_out)


def read_map(path):
    """Weights of a map file as numpy arrays.

    Args:
        path: ESMF weight file.

    Returns:
        dict with ``row`` (destination cell) and ``col`` (source cell) as 0-based indices, ``S`` weights, ``frac_b``, and the sizes
        ``n_a`` (source cells) and ``n_b`` (destination cells).
    """
    with netCDF4.Dataset(path) as m:
        return {"row": np.asarray(m["row"][:], dtype=np.int64) - 1, "col": np.asarray(m["col"][:], dtype=np.int64) - 1,
                "S": np.asarray(m["S"][:], dtype=np.float64), "frac_b": np.asarray(m["frac_b"][:], dtype=np.float64),
                "n_a": len(m.dimensions["n_a"]), "n_b": len(m.dimensions["n_b"])}


def read_grid_centres(path):
    """Cell centres of a SCRIP grid file.

    Args:
        path: SCRIP file.

    Returns:
        (lat, lon): 1-D centre arrays in degrees, one value per cell (cell index = ilat * nlon + ilon for a regular grid).
    """
    with netCDF4.Dataset(path) as g:
        return (np.asarray(g["grid_center_lat"][:], dtype=np.float64), np.asarray(g["grid_center_lon"][:], dtype=np.float64))


def check_weights(map_path, src_grid, dst_grid, bilinear=True):
    """Quality checks of a bilinear weight file.

    Checks: the map sizes equal the two grids; every destination cell with weights has weights that add up to 1 (``bilinear``); destination
    cells without weights ("unmapped") are only allowed beyond the outermost source cell centre (the polar rows of a 1 degree grid for the
    ne30pg2 source); every source column index is valid.

    Args:
        map_path: weight file.
        src_grid, dst_grid: SCRIP files of the grids the map was made from.
        bilinear: True checks that the row sums are 1.

    Returns:
        (problems, info): list of problem strings (empty = all good) and a list of information lines.
    """
    # Sizes of the map against the grid files
    m = read_map(map_path)
    s_lat, _ = read_grid_centres(src_grid)
    d_lat, _ = read_grid_centres(dst_grid)
    problems, info = [], []
    if m["n_a"] != s_lat.size:
        problems.append(f"map source has {m['n_a']} cells, the source grid {s_lat.size}")
    if m["n_b"] != d_lat.size:
        problems.append(f"map destination has {m['n_b']} cells, the destination grid {d_lat.size}")
    # Row sums of the weights and the destination cells without any weight
    rowsum = np.bincount(m["row"], weights=m["S"], minlength=m["n_b"])
    has = np.bincount(m["row"], minlength=m["n_b"]) > 0
    unmapped = ~has
    info.append(f"{m['S'].size} weights, {m['n_b']} destination cells, {int(unmapped.sum())} without weights, "
                f"row sums of the others {rowsum[has].min():.6f} .. {rowsum[has].max():.6f}")
    if bilinear and has.any() and float(np.abs(rowsum[has] - 1.0).max()) > 1e-6:
        problems.append("the weights of some destination cells do not add up to 1")
    if m["col"].size and (m["col"].min() < 0 or m["col"].max() >= m["n_a"]):
        problems.append("a weight points to a source cell that does not exist")
    # Unmapped cells must lie beyond the source cell centres (poles), not in the interior
    if unmapped.any():
        limit = float(np.abs(s_lat).max())
        inside = unmapped & (np.abs(d_lat) < limit)
        info.append(f"unmapped destination cells at |lat| >= {np.abs(d_lat[unmapped]).min():.2f} (outermost source centre {limit:.2f})")
        if inside.any():
            problems.append(f"{int(inside.sum())} unmapped destination cells lie inside the source coverage (|lat| < {limit:.2f})")
    return problems, info


# --------------------------------------------------------------------------------------------------------------------------------
# Applying a weight file
# --------------------------------------------------------------------------------------------------------------------------------
def apply_map(map_path, infile, outfile, variables, deflate=4, nco_bin=DEFAULT_NCO_BIN):
    """Regrid the variables of a file with a weight file using ``ncremap -m``, writing netCDF4 with deflate.

    The product itself applies the weights with numpy (``regrid.Remapper``: explicit NaN handling, unmapped cells missing); this function is the
    independent NCO result that the tests and ``validate_regrid.py`` compare it with. It is only exact for fields without missing values:
    ncremap fills destination cells without weights with zero, and handles missing source values in its own way.

    Args:
        map_path: weight file.
        infile: native-grid file.
        outfile: regridded file (written under a temporary name and renamed when complete).
        variables: list of variable names to regrid (``time_bnds`` is added).
        deflate: deflate level 1-9 (default 4).
        nco_bin: folder of the NCO programs.

    Returns:
        path of the regridded file (str).
    """
    outfile = Path(outfile)
    outfile.parent.mkdir(parents=True, exist_ok=True)
    part = outfile.with_name("." + outfile.name + ".part")
    try:
        # A private temporary directory: ncremap writes its working files there
        with tempfile.TemporaryDirectory(dir=outfile.parent, prefix=".ncremap_") as tmp:
            cmd = [find_tool("ncremap", nco_bin), "--no_stdin", "--no_cll_msr", "-t", "1", "--fl_fmt=netcdf4", "-L", str(int(deflate)),
                   "-m", str(map_path), "-v", ",".join(list(variables) + ["time_bnds"]), str(infile), str(part)]
            run_tool(cmd, env_extra={"TMPDIR": tmp}, cwd=tmp)
        os.replace(part, outfile)
    finally:
        if part.exists():
            part.unlink()
    return str(outfile)
