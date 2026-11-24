"""Writing and checking the output netCDF files: netCDF4 with deflate and shuffle, CF attributes, ``_FillValue`` 1e20.

All monthly and climatology files of the product are written here, so they share the layout:

* native grids: dimensions ``(time, ncol)`` with coordinate variables ``lat(ncol)``, ``lon(ncol)``, or ``(time, lat, lon)`` for regular grids;
* ``time`` in days since 1850-01-01 with ``time_bnds``, in the calendar of the dataset;
* data variables float32, deflated (default level 4) and shuffled, chunked as one time step.
"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import netCDF4
import numpy as np

from .timeaxis import TIME_UNITS

FILL = np.float32(1.0e20)
# Variables with fewer elements than this are not checked for compression (bounds, tiny axes)
MIN_CHECK_SIZE = 10000


def write_env_file(path, grid, fields, meta, times, global_attrs, deflate=4, extra=None):
    """Write one file of environment fields, atomically (a temporary name that is renamed when the file is complete).

    Args:
        path: output file.
        grid: dict with ``kind`` (``"ncol"`` or ``"latlon"``), ``lat`` and ``lon`` (1-D arrays).
        fields: dict name -> array shaped (nt, ncol) or (nt, nlat, nlon); NaN = missing.
        meta: dict name -> dict of variable attributes (long_name, standard_name, units, ...).
        times: dict with ``values`` (nt floats in days since 1850-01-01), ``calendar``, and optional ``bounds`` (nt, 2).
        global_attrs: dict of global attributes.
        deflate: deflate level 1-9 (default 4).
        extra: optional dict name -> (array (nt,), attributes) of integer variables along time (e.g. ``month``, ``nmonths``).

    Returns:
        path (str).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name("." + path.name + ".part")
    nt = len(times["values"])
    try:
        with netCDF4.Dataset(part, "w", format="NETCDF4") as ds:
            # Dimensions and coordinate variables of the grid
            ds.createDimension("time", nt)
            if grid["kind"] == "ncol":
                ds.createDimension("ncol", grid["lat"].size)
                dims, space = ("time", "ncol"), ("ncol",)
                chunks = (1, grid["lat"].size)
                for name, vals, units, std in (("lat", grid["lat"], "degrees_north", "latitude"), ("lon", grid["lon"], "degrees_east", "longitude")):
                    v = ds.createVariable(name, "f8", ("ncol",), zlib=True, complevel=deflate, shuffle=True)
                    v.units, v.standard_name = units, std
                    v[:] = vals
            else:
                ds.createDimension("lat", grid["lat"].size)
                ds.createDimension("lon", grid["lon"].size)
                dims, space = ("time", "lat", "lon"), ("lat", "lon")
                chunks = (1, grid["lat"].size, grid["lon"].size)
                for name, vals, units, std, axis in (("lat", grid["lat"], "degrees_north", "latitude", "Y"),
                                                     ("lon", grid["lon"], "degrees_east", "longitude", "X")):
                    v = ds.createVariable(name, "f8", (name,))
                    v.units, v.standard_name, v.axis = units, std, axis
                    v[:] = vals
            # Time axis with bounds
            tv = ds.createVariable("time", "f8", ("time",))
            tv.units, tv.calendar, tv.standard_name, tv.axis = TIME_UNITS, times["calendar"], "time", "T"
            tv[:] = np.asarray(times["values"], dtype=np.float64)
            if times.get("bounds") is not None:
                ds.createDimension("nbnd", 2)
                tv.bounds = "time_bnds"
                bv = ds.createVariable("time_bnds", "f8", ("time", "nbnd"))
                bv[:] = np.asarray(times["bounds"], dtype=np.float64)
            # Extra integer variables along time
            for name, (arr, attrs) in (extra or {}).items():
                ev = ds.createVariable(name, "i4", ("time",))
                ev.setncatts(attrs)
                ev[:] = np.asarray(arr, dtype=np.int32)
            # Data variables: float32, deflate + shuffle, one time step per chunk, missing = _FillValue
            for name, arr in fields.items():
                arr = np.asarray(arr, dtype=np.float32)
                if arr.shape[0] != nt or arr.shape[1:] != tuple(len(ds.dimensions[d]) for d in space):
                    raise ValueError(f"{name}: shape {arr.shape} does not match the grid {space} and {nt} time steps")
                v = ds.createVariable(name, "f4", dims, zlib=True, complevel=deflate, shuffle=True, chunksizes=chunks, fill_value=FILL)
                v.setncatts({k: x for k, x in meta[name].items() if x is not None})
                v.missing_value = FILL
                v[:] = np.where(np.isfinite(arr), arr, FILL)
            ds.setncatts({"Conventions": "CF-1.8", **{k: x for k, x in global_attrs.items() if x is not None},
                          "date_created": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
        os.replace(part, path)
    finally:
        if part.exists():
            part.unlink()
    return str(path)


def check_compression(path, names=None, min_size=MIN_CHECK_SIZE):
    """Problems with the compression of a netCDF file (empty list = all good).

    Every variable named in ``names`` and every variable with at least ``min_size`` elements must be stored with deflate (level > 0) and
    shuffle. A classic-format file (no compression possible) is a problem as well.

    Args:
        path: netCDF file.
        names: variable names that must be checked in any case (default None).
        min_size: variables with at least this many elements are checked too (default 10000).

    Returns:
        list of problem strings.
    """
    problems = []
    with netCDF4.Dataset(path) as ds:
        if ds.data_model == "NETCDF3_CLASSIC" or ds.data_model.startswith("NETCDF3"):
            return [f"{path}: classic netCDF format, no compression possible"]
        for name, var in ds.variables.items():
            size = int(np.prod(var.shape)) if var.shape else 1
            if name not in (names or []) and size < min_size:
                continue
            f = var.filters()
            if not (f.get("zlib") and f.get("complevel", 0) > 0 and f.get("shuffle")):
                problems.append(f"{Path(path).name}: variable {name} is not deflated + shuffled (filters {f})")
    return problems
