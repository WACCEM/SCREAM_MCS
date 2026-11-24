"""Step 1 of the product: the monthly native-grid file of one month of one dataset.

For every stream of the dataset: find the file(s) of the month and check that they cover it; for every variable read it (direct), pick its
level (plev_select) or interpolate it to the level (interpolate); convert units (scale, offset); set pressure-level variables with
``mask_below_ground`` to NaN where the surface pressure is below the level; write one file with all output variables on the native grid.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import netCDF4
import numpy as np

from . import readers, vertical
from .config import load_dataset
from .timeaxis import time_axis_values
from .writer import write_env_file

# A month whose hourly inputs have fewer records than this fraction of the expected number is reported as failed (data-gap sanity limit)
MIN_RECORD_FRACTION = 0.95


@dataclass
class MonthResult:
    """Outcome of one month: ``status`` is written | skipped | failed; ``nan_fraction`` per output variable; ``warnings`` list of strings."""

    year: int
    month: int
    status: str
    message: str = ""
    seconds: float = 0.0
    nan_fraction: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)


def _method_text(spec, stream):
    """Sentence that says how an output variable was obtained (written to the variable attribute ``method``)."""
    if spec.method == "direct":
        return f"read from {spec.raw}" + (" (mean over all records of the month)" if stream.layout == "latlon" else "")
    if spec.method == "plev_select":
        return f"level {spec.plev_hpa:g} hPa of {spec.raw} (mean over all records of the month; no vertical interpolation)"
    how = f"the level pressure field {stream.pressure['field']}" if "field" in stream.pressure else "hybrid sigma-pressure (a * p0 + b * ps)"
    return (f"{spec.raw} interpolated to {spec.plev_hpa:g} hPa, linear in ln(p), with {how}; the monthly-mean field is interpolated on the "
            f"monthly-mean pressure, which is not the monthly mean of the daily interpolated field")


def process_month(ds_cfg, year, month, overwrite=False):
    """Make the native-grid file of one month. Never raises for data problems: a failure comes back as ``status="failed"`` with the reason.

    Args:
        ds_cfg: ``config.Dataset``.
        year, month: the month.
        overwrite: True replaces an existing file (default False: an existing file is skipped).

    Returns:
        ``MonthResult``.
    """
    t0 = time.time()
    out = ds_cfg.native_path(year, month)
    if out.exists() and not overwrite:
        return MonthResult(year, month, "skipped", "file exists", time.time() - t0)
    try:
        values, info, grid, sources = {}, {}, None, {}
        # 1. Read every variable of every stream
        for stream in ds_cfg.streams:
            files = readers.find_files(stream, year, month, ds_cfg.calendar)
            sources[stream.name] = f"{len(files)} file(s) {stream.root}/{stream.pattern}"
            # Grid of the stream: all streams must share it
            g = readers.read_grid(stream, files[0])
            if grid is None:
                grid = g
            elif g["lat"].shape != grid["lat"].shape or g["lon"].shape != grid["lon"].shape or not np.allclose(g["lat"], grid["lat"], atol=1e-3):
                raise ValueError(f"stream {stream.name}: grid differs from the grid of the first stream")
            # The level pressure of an ncol stream is read once for all its interpolate variables
            pres = None
            for spec in stream.variables:
                if stream.layout == "ncol":
                    if spec.method == "interpolate" and pres is None:
                        with netCDF4.Dataset(files[0]) as nc_ds:
                            pres = readers.ncol_pressure(nc_ds, stream)
                    values[spec.name], info[spec.name] = readers.read_ncol_variable(stream, files[0], spec, pres)
                else:
                    values[spec.name], info[spec.name] = readers.read_latlon_variable(stream, files, spec, year, month, ds_cfg.calendar)
        # 2. Units: value * scale + offset
        for spec in ds_cfg.variables:
            values[spec.name] = values[spec.name] * spec.scale + spec.offset
        # 3. Below-ground mask of pressure-level variables with the monthly-mean surface pressure
        for spec in ds_cfg.variables:
            if spec.mask_below_ground:
                values[spec.name] = vertical.mask_below_ground(values[spec.name], values[spec.mask_below_ground], spec.plev_hpa)
        # 4. Incomplete hourly inputs: a sanity limit (the months with fewer records are failed, the others carry the counts)
        warnings = []
        for spec in ds_cfg.variables:
            n, n_exp = info[spec.name]["n_records"], info[spec.name].get("n_records_expected")
            if n_exp and n < MIN_RECORD_FRACTION * n_exp:
                raise ValueError(f"{spec.name}: only {n} of {n_exp} expected records")
            if n_exp and n < n_exp:
                warnings.append(f"{spec.name}: {n} of {n_exp} records")
        # 5. Variable attributes: the dictionary of the CMIP names + how the variable was made
        stream_of = {s.name: s for s in ds_cfg.streams}
        meta, fields = {}, {}
        for spec in ds_cfg.variables:
            d = ds_cfg.dictionary[spec.name]
            meta[spec.name] = {"long_name": d["long_name"], "standard_name": d["standard_name"], "units": d["units"],
                               "method": _method_text(spec, stream_of[spec.stream]), "source_variable": spec.raw,
                               "source_units": info[spec.name]["units"] or None, "source_stream": spec.stream,
                               "scale_applied": spec.scale if spec.scale != 1.0 else None, "offset_applied": spec.offset or None,
                               "level_hPa": spec.plev_hpa, "n_records": info[spec.name]["n_records"],
                               "n_records_expected": info[spec.name].get("n_records_expected"),
                               "masked_below_ground_with": spec.mask_below_ground}
            fields[spec.name] = values[spec.name][None]
        # 6. Write the file
        mid, bounds = time_axis_values(year, month, ds_cfg.calendar)
        times = {"values": [mid], "bounds": [bounds], "calendar": ds_cfg.calendar}
        gattrs = {"title": f"{ds_cfg.label}: monthly-mean environment fields, native grid, {year}-{month:02d}", "dataset": ds_cfg.name,
                  "source_grid": ds_cfg.grid, "month": f"{year}-{month:02d}", "config_file": ds_cfg.path,
                  "history": "written by make_monthly_native.py (scream/mcs_environment/monthly)",
                  **{f"source_{k}": v for k, v in sources.items()}}
        write_env_file(out, grid, fields, meta, times, gattrs, deflate=ds_cfg.common.deflate)
        nan_fraction = {n: float(np.mean(~np.isfinite(a))) for n, a in fields.items()}
        return MonthResult(year, month, "written", "", time.time() - t0, nan_fraction, warnings)
    except Exception as exc:  # noqa: BLE001 - one bad month must not stop the run
        text = (str(exc).strip().splitlines() or [""])[0]
        return MonthResult(year, month, "failed", f"{type(exc).__name__}: {text}", time.time() - t0)


def native_task(cfg_path, year, month, overwrite):
    """Pool task of step 1: load the dataset configuration and process one month (see ``process_month``).

    Args:
        cfg_path: dataset YAML file.
        year, month: the month.
        overwrite: replace an existing file.

    Returns:
        ``MonthResult``.
    """
    return process_month(load_dataset(cfg_path), year, month, overwrite)
