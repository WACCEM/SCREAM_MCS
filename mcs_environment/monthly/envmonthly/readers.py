"""Readers of the input files: one function per layout, all returning plain numpy arrays of one month.

* ``ncol``    files with a ``ncol`` dimension (SCREAM, E3SM): one file per month with one time record (the monthly mean), variables
              ``(time, ncol)``, ``(time, ncol, lev)`` (SCREAM) or ``(time, lev, ncol)`` (E3SM). 3-D fields are returned as (level, cell).
* ``latlon``  regular lat-lon files (ERA5): one or many files of the month, any number of time records; the result is the MEAN over all records
              (a monthly file has one record, an hourly file 744). Pressure-level variables ``(time, level, lat, lon)`` give one level.
              Latitude is returned ascending (ERA5 stores it descending).

Values come back as float64 with NaN for fill values. The netCDF library is used directly (no xarray / dask): every worker process opens
its own files. A new layout is one more function and one more word in ``config.LAYOUTS``.
"""

from __future__ import annotations

import glob
import os

import netCDF4
import numpy as np

from . import vertical
from .timeaxis import check_file_month, days_in_month

# Values with a larger magnitude are fill values that are not flagged in the file
FILL_LIMIT = 1.0e30
# Records are averaged in blocks of this many time steps (memory: one block of a 0.25 degree field is about 8 MB per record)
RECORD_BLOCK = 12

# Default names per layout; a stream can override them with the keys lat_name, lon_name, level_dim, ncol_dim, lev_dim
DEFAULT_NAMES = {
    "ncol": {"lat_name": "lat", "lon_name": "lon", "ncol_dim": "ncol", "lev_dim": "lev"},
    "latlon": {"lat_name": "latitude", "lon_name": "longitude", "level_dim": "level"},
}


class MissingInput(Exception):
    """An input file of the month does not exist, or it does not cover the month (the month is reported as failed)."""


def _name(stream, key):
    """Name of a coordinate / dimension of a stream: its own option, else the default of the layout."""
    return stream.options.get(key, DEFAULT_NAMES[stream.layout].get(key))


def _filled(values):
    """Masked or plain array as float64 with NaN for masked cells and for fill values (|x| > 1e30)."""
    out = np.ma.filled(np.ma.asarray(values).astype(np.float64), np.nan)
    out[np.abs(out) > FILL_LIMIT] = np.nan
    return out


def find_files(stream, year, month, calendar):
    """Files of a stream for one month, verified to cover that month.

    Args:
        stream: ``StreamSpec``.
        year, month: the month.
        calendar: calendar of the dataset.

    Returns:
        sorted list of file paths. Raises ``MissingInput`` when there is none (or, for layout ncol, not exactly one) or when a file covers
        another month (``timeaxis.check_file_month``).
    """
    # Files by the pattern of the stream (a pattern may contain *)
    pattern = os.path.join(stream.root, stream.pattern.format(yyyy=f"{year:04d}", mm=f"{month:02d}"))
    files = sorted(glob.glob(pattern))
    if not files:
        raise MissingInput(f"stream {stream.name}: no file matches {pattern}")
    if stream.layout == "ncol" and len(files) != 1:
        raise MissingInput(f"stream {stream.name}: {len(files)} files match {pattern}, expected one")
    # Every file must cover the month (a wrong month is a data problem, reported like a missing file)
    for path in files:
        with netCDF4.Dataset(path) as ds:
            try:
                check_file_month(ds, year, month, calendar)
            except ValueError as exc:
                raise MissingInput(str(exc)) from None
    return files


def read_grid(stream, path):
    """Coordinates of the grid of a file.

    Args:
        stream: ``StreamSpec`` (supplies the coordinate names).
        path: a file of the stream.

    Returns:
        dict with ``kind`` (``"ncol"`` or ``"latlon"``), ``lat`` and ``lon`` (degrees; 1-D over cells for ncol, 1-D axes for latlon with
        ascending latitude).
    """
    with netCDF4.Dataset(path) as ds:
        lat = _filled(ds[_name(stream, "lat_name")][:])
        lon = _filled(ds[_name(stream, "lon_name")][:])
    # Latitude ascending for a regular grid (the data are flipped in the same way when they are read)
    if stream.layout == "latlon":
        if lat[0] > lat[-1]:
            lat = lat[::-1].copy()
        if not np.all(np.diff(lon) > 0):
            raise ValueError(f"{path}: longitude must increase")
    if np.nanmax(np.abs(lat)) > 90.0 + 1e-6:
        raise ValueError(f"{path}: latitude outside +-90 (is it in degrees?)")
    return {"kind": stream.layout, "lat": lat, "lon": lon}


# --------------------------------------------------------------------------------------------------------------------------------
# Layout ncol
# --------------------------------------------------------------------------------------------------------------------------------
def _ncol_read(ds, stream, raw):
    """One variable of an ncol file as a float64 array: (cell,) for 2-D variables, (level, cell) for 3-D variables.

    Args:
        ds: open dataset.
        stream: ``StreamSpec`` (dimension names).
        raw: variable name.

    Returns:
        (array, units).
    """
    var = ds[raw]
    dims = var.dimensions
    ncol_dim, lev_dim = _name(stream, "ncol_dim"), _name(stream, "lev_dim")
    # One monthly record: the file must not hold several times
    if dims[0] != "time" or len(ds.dimensions["time"]) != 1:
        raise ValueError(f"{ds.filepath()}: {raw}{dims} is not a single monthly record")
    values = _filled(var[0])
    # Remaining dimensions: (ncol), (ncol, lev) or (lev, ncol)
    rest = dims[1:]
    if rest == (ncol_dim,):
        return values, getattr(var, "units", "")
    if rest == (ncol_dim, lev_dim):
        return values.T.copy(), getattr(var, "units", "")
    if rest == (lev_dim, ncol_dim):
        return values, getattr(var, "units", "")
    raise ValueError(f"{ds.filepath()}: {raw}{dims}: unsupported dimension order")


def ncol_pressure(ds, stream):
    """Pressure of the model levels of an ncol file, from the stream's ``pressure`` description.

    ``{field: p_mid}`` reads the stored (monthly-mean) level pressure; ``{hybrid: {ps, a, b, p0}}`` forms ``a * p0 + b * ps`` (``p0`` is a
    variable name or a number).

    Returns:
        pressure in Pa, float64 array (level, cell), increasing with the level index (checked).
    """
    spec = stream.pressure
    if "field" in spec:
        pres, _ = _ncol_read(ds, stream, spec["field"])
    else:
        h = spec["hybrid"]
        p0 = float(ds[h["p0"]][...]) if isinstance(h["p0"], str) else float(h["p0"])
        ps, _ = _ncol_read(ds, stream, h["ps"])
        pres = vertical.hybrid_pressure(ds[h["a"]][:], ds[h["b"]][:], p0, ps)
    vertical.check_pressure_order(pres)
    return pres


def read_ncol_variable(stream, path, spec, pres=None):
    """One output variable of an ncol file, before scale and offset.

    Args:
        stream: ``StreamSpec``.
        path: the file of the month.
        spec: ``VarSpec`` (method direct or interpolate).
        pres: level pressure (level, cell) for interpolate; None reads it from the file.

    Returns:
        (values (cell,), info): ``info`` has ``units`` (of the raw variable) and ``n_records`` (1).
    """
    with netCDF4.Dataset(path) as ds:
        values, units = _ncol_read(ds, stream, spec.raw)
        if spec.method == "direct":
            return values, {"units": units, "n_records": 1}
        # Model-level field: interpolate to the level with the pressure of the levels
        pressure = pres if pres is not None else ncol_pressure(ds, stream)
        return vertical.interp_to_plev(values, pressure, spec.plev_hpa * 100.0), {"units": units, "n_records": 1}


# --------------------------------------------------------------------------------------------------------------------------------
# Layout latlon
# --------------------------------------------------------------------------------------------------------------------------------
def read_latlon_variable(stream, files, spec, year, month, calendar):
    """Mean over all records of the month of one variable (optionally at one pressure level) of regular lat-lon files.

    Args:
        stream: ``StreamSpec`` (names, ``expected_records_per_day``).
        files: the files of the month.
        spec: ``VarSpec`` (method direct or plev_select; ``plev_hpa`` picks the level).
        year, month, calendar: the month, for the expected number of records.

    Returns:
        (mean (lat, lon) with ascending latitude, info) where ``info`` has ``units``, ``n_records`` (records used) and
        ``n_records_expected`` (None when the stream has no ``expected_records_per_day``).
    """
    lev_dim = _name(stream, "level_dim")
    total, count, n_records, units, flip = None, None, 0, "", False
    for path in files:
        with netCDF4.Dataset(path) as ds:
            var = ds[spec.raw]
            units = getattr(var, "units", units)
            # The level index of a pressure-level variable (the level must exist, exact value)
            k = None
            if spec.method == "plev_select":
                levels = np.asarray(ds[lev_dim][:], dtype=np.float64)
                hit = np.where(np.abs(levels - spec.plev_hpa) < 1e-6)[0]
                if hit.size != 1:
                    raise ValueError(f"{path}: level {spec.plev_hpa} hPa is not in {lev_dim} = {levels.tolist()}")
                k = int(hit[0])
            lat = np.asarray(ds[_name(stream, "lat_name")][:], dtype=np.float64)
            flip = bool(lat[0] > lat[-1])
            # Sum and count of the valid values over the records, block by block
            nt = len(ds.dimensions["time"])
            for t0 in range(0, nt, RECORD_BLOCK):
                block = var[t0:t0 + RECORD_BLOCK] if k is None else var[t0:t0 + RECORD_BLOCK, k]
                block = _filled(block)
                if total is None:
                    total, count = np.zeros(block.shape[1:]), np.zeros(block.shape[1:], dtype=np.int64)
                total += np.nansum(block, axis=0)
                count += np.isfinite(block).sum(axis=0)
            n_records += nt
    # Mean of the valid records; cells without any valid record are NaN
    with np.errstate(all="ignore"):
        mean = np.where(count > 0, total / np.maximum(count, 1), np.nan)
    if flip:
        mean = mean[::-1].copy()
    per_day = stream.options.get("expected_records_per_day")
    expected = int(per_day * days_in_month(year, month, calendar)) if per_day else None
    return mean, {"units": units, "n_records": n_records, "n_records_expected": expected}
