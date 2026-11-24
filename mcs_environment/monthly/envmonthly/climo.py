"""Step 3 of the product: the 12-month climatology of a dataset from its 1 degree monthly files.

The climatology of a calendar month is the unweighted mean over the years of the monthly means (the same file layout as the MCS rain-map
climatology of ``calc_mcs_rainmap_climo_from_monthly.py``: ``time`` has 12 steps, in the year 2000, plus ``month`` and ``nmonths``). A dataset
that covers only part of the year more than once (Cess2: March to July once, August to February twice) is handled by ``nmonths``.
"""

from __future__ import annotations

import netCDF4
import numpy as np

from .runner import MAX_FAILED_FRACTION
from .timeaxis import time_axis_values
from .writer import check_compression, write_env_file

# Variable attributes that describe one month and make no sense for a climatology
MONTH_ATTRS = ("n_records", "n_records_expected")


def build_climatology(ds_cfg, start, end):
    """Write the 12-month climatology file of a dataset.

    Args:
        ds_cfg: ``config.Dataset``.
        start, end: first and last month as (year, month) tuples (the months of the climatology).

    Returns:
        dict with ``path`` (the climatology file), ``nmonths`` (files used per calendar month, list of 12), ``missing`` (months without a
        1 degree file that are NOT listed as ``known_missing_months`` in the config) and ``known_missing`` (the listed ones that have no file).
        Raises ``RuntimeError`` when more than 5 % of the months are unexpectedly missing or a calendar month has no file at all.
    """
    months = ds_cfg.months(start, end)
    names = ds_cfg.output_names()
    total = {n: None for n in names}
    count = {n: None for n in names}
    nmonths, missing, meta, grid, gattrs = np.zeros(12, dtype=int), [], None, None, {}
    # Sum and count of the valid values per calendar month, month file by month file
    for year, month in months:
        path = ds_cfg.latlon_path(year, month)
        if not path.exists():
            missing.append((year, month))
            continue
        with netCDF4.Dataset(path) as ds:
            if grid is None:
                grid = {"kind": "latlon", "lat": np.asarray(ds["lat"][:], dtype=np.float64), "lon": np.asarray(ds["lon"][:], dtype=np.float64)}
                meta = {n: {k: ds[n].getncattr(k) for k in ds[n].ncattrs() if k not in ("_FillValue", "missing_value") + MONTH_ATTRS} for n in names}
                gattrs = {k: ds.getncattr(k) for k in ds.ncattrs() if k in ("dataset", "source_grid", "regrid_method", "regrid_map")}
            for n in names:
                x = np.ma.filled(ds[n][0].astype(np.float64), np.nan)
                x[np.abs(x) > 1e19] = np.nan
                if total[n] is None:
                    total[n], count[n] = np.zeros((12,) + x.shape), np.zeros((12,) + x.shape, dtype=np.int64)
                total[n][month - 1] += np.where(np.isfinite(x), x, 0.0)
                count[n][month - 1] += np.isfinite(x)
        nmonths[month - 1] += 1
    # Sanity limits: not too many missing months, every calendar month of the period has data
    known = [m for m in missing if m in ds_cfg.known_missing]
    missing = [m for m in missing if m not in ds_cfg.known_missing]
    if len(missing) > MAX_FAILED_FRACTION * len(months):
        raise RuntimeError(f"{len(missing)} of {len(months)} monthly files are missing (first: {missing[:3]}); run regrid_monthly.py first")
    in_period = sorted({m for _, m in months})
    if any(nmonths[m - 1] == 0 for m in in_period):
        raise RuntimeError(f"calendar months without any file: {[m for m in in_period if nmonths[m - 1] == 0]}")
    # Mean per calendar month: NaN where no valid value; calendar months outside the period are all NaN
    fields = {}
    for n in names:
        with np.errstate(all="ignore"):
            fields[n] = np.where(count[n] > 0, total[n] / np.maximum(count[n], 1), np.nan)
    # Time axis: the 12 months of the year 2000 (standard calendar)
    mids = [time_axis_values(2000, m, "standard") for m in range(1, 13)]
    times = {"values": [t[0] for t in mids], "bounds": [t[1] for t in mids], "calendar": "standard"}
    gattrs.update({"title": f"{ds_cfg.label}: monthly climatology of the environment fields, 1 degree grid, {start[0]}-{start[1]:02d} to {end[0]}-{end[1]:02d}",
                   "climatology_method": "unweighted mean over the years of the monthly means of each calendar month (the time axis is the year 2000)",
                   "period": f"{start[0]}-{start[1]:02d} to {end[0]}-{end[1]:02d}", "missing_months": ", ".join(f"{y}-{m:02d}" for y, m in sorted(missing + known)) or None,
                   "history": "written by calc_env_climo.py (scream/mcs_environment/monthly)"})
    extra = {"month": (np.arange(1, 13), {"long_name": "Calendar month (1 = January)", "units": "1"}),
             "nmonths": (nmonths, {"long_name": "Number of monthly files in the mean of the calendar month", "units": "1"})}
    out = ds_cfg.climo_path(start, end)
    write_env_file(out, grid, fields, meta, times, gattrs, deflate=ds_cfg.common.deflate, extra=extra)
    problems = check_compression(out, names=names)
    if problems:
        raise RuntimeError("; ".join(problems))
    return {"path": str(out), "nmonths": nmonths.tolist(), "missing": missing, "known_missing": known}
