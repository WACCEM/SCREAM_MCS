"""Running the months of a dataset with a process pool, progress lines, the CSV report and the failure limit (shared by steps 1 and 2)."""

from __future__ import annotations

import concurrent.futures as cf
import csv
import datetime as dt
import logging
import multiprocessing as mp
import os
import time
from pathlib import Path

from .native import MonthResult
from .ncotools import THREAD_ENV

log = logging.getLogger("envmonthly")
# Largest share of failed months before the run reports an error (the data-gap sanity limit)
MAX_FAILED_FRACTION = 0.05


def _init_worker():
    """Pool initializer: single-threaded native libraries, no HDF5 file locks."""
    os.environ.update(THREAD_ENV)


def run_months(task, cfg_path, months, workers, overwrite):
    """Run ``task(cfg_path, year, month, overwrite)`` for every month with ``workers`` processes.

    Args:
        task: top-level function (picklable) returning a ``MonthResult``.
        cfg_path: dataset YAML file (each task loads it itself).
        months: list of (year, month).
        workers: number of processes (1 = serial in this process).
        overwrite: passed to the task.

    Returns:
        list of ``MonthResult`` in the order of ``months``. A worker that dies gives a failed result for its month. A progress line is logged
        every 10 months and at least every 60 s.
    """
    n, results, done = len(months), [None] * len(months), 0
    t_start = t_last = time.time()

    def progress(force=False):
        """Log count, rate and ETA."""
        nonlocal t_last
        now = time.time()
        if force or done % 10 == 0 or now - t_last >= 60:
            rate = done / max(now - t_start, 1e-9)
            log.info("%d/%d months done (%.1f months/min, ETA %.1f min)", done, n, rate * 60, (n - done) / rate / 60 if rate > 0 else float("inf"))
            t_last = now

    os.environ.update(THREAD_ENV)
    # Serial run
    if workers <= 1 or n <= 1:
        for i, (y, m) in enumerate(months):
            results[i] = task(cfg_path, y, m, overwrite)
            done += 1
            progress()
        progress(True)
        return results
    # Process pool (forkserver: cheap workers with numpy and netCDF4 preloaded)
    ctx = mp.get_context("forkserver")
    ctx.set_forkserver_preload(["numpy", "netCDF4"])
    with cf.ProcessPoolExecutor(max_workers=workers, mp_context=ctx, initializer=_init_worker) as pool:
        futures = {pool.submit(task, cfg_path, y, m, overwrite): i for i, (y, m) in enumerate(months)}
        for fut in cf.as_completed(futures):
            i = futures[fut]
            try:
                results[i] = fut.result()
            except Exception as exc:  # noqa: BLE001 - the worker died (out of memory)
                results[i] = MonthResult(months[i][0], months[i][1], "failed", f"worker died: {type(exc).__name__}: {exc}")
            done += 1
            progress()
    progress(True)
    return results


def write_report(root, step, results):
    """Write one row per month to ``<root>/_reports/<step>_<UTC time>.csv`` and return the path (str)."""
    folder = Path(root) / "_reports"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{step}_{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%SZ}.csv"
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["month", "status", "seconds", "message", "warnings", "nan_fraction"])
        for r in results:
            w.writerow([f"{r.year:04d}-{r.month:02d}", r.status, f"{r.seconds:.1f}", r.message, " | ".join(r.warnings),
                        " ".join(f"{k}={v:.4f}" for k, v in r.nan_fraction.items())])
    return str(path)


def summarize(results, seconds):
    """Text summary of a run: counts, failures with their reasons, warnings. Returns (text, exit_code): exit code 1 when more than
    ``MAX_FAILED_FRACTION`` of the months failed (or any month failed and none was written), else 0."""
    failed = [r for r in results if r.status == "failed"]
    lines = [f"{sum(r.status == 'written' for r in results)} months written, {sum(r.status == 'skipped' for r in results)} skipped (exist), "
             f"{len(failed)} failed, {seconds:.0f} s"]
    for r in failed[:20]:
        lines.append(f"  FAILED {r.year}-{r.month:02d}: {r.message}")
    for r in [r for r in results if r.warnings][:10]:
        lines.append(f"  warning {r.year}-{r.month:02d}: {'; '.join(r.warnings)}")
    too_many = len(failed) > MAX_FAILED_FRACTION * max(len(results), 1)
    if too_many:
        lines.append(f"  more than {100 * MAX_FAILED_FRACTION:.0f} % of the months failed: check the inputs")
    return "\n".join(lines), int(too_many)
