"""Readers: one small class per input layout. A reader reads the grid of a file and one record of one variable as a 1-D array over all cells.

The extraction only talks to this interface, so a new kind of input (for example HEALPix Zarr) is one more class and one word in the configuration:

* ``ncol``          variables ``(time, ncol)`` on an unstructured grid (SCREAM, E3SM: the cubed-sphere ne30pg2, ne120pg2, ne1024pg2 files);
* ``latlon``        variables ``(time, lat, lon)`` on a regular grid (ERA5 surface files);
* ``latlon_level``  variables ``(time, level, lat, lon)`` (ERA5 pressure-level files); the level is picked by value.

Values come back as float32 with NaN for fill values. The netCDF library is used directly (no xarray, no dask): every worker process opens its own files.
"""

from __future__ import annotations

import numpy as np

# Values with a larger magnitude are fill values that were not flagged in the file
FILL_LIMIT = 1.0e30


def _to_float32(values):
    """Masked or plain array to float32 with NaN for masked cells and for fill values (|x| > 1e30)."""
    out = np.ma.filled(np.ma.asarray(values).astype(np.float32), np.nan)
    out[np.abs(out) > FILL_LIMIT] = np.nan
    return out


def _to_degrees(lat, lon):
    """Latitude and longitude in degrees from arrays that are in degrees or radians (decided by the magnitude, not by the ``units`` attribute).

    The SCREAM files label degrees as ``rad``. Values whose latitude stays below pi/2 and longitude below 2 pi are taken as radians, which is safe
    for global grids (a global grid in degrees has |lat| up to nearly 90).
    """
    lat, lon = np.asarray(lat, dtype=np.float64), np.asarray(lon, dtype=np.float64)
    if np.nanmax(np.abs(lat)) <= np.pi / 2 + 1e-6 and np.nanmax(np.abs(lon)) <= 2 * np.pi + 1e-6:
        return np.degrees(lat), np.degrees(lon)
    return lat, lon


class BaseReader:
    """Common behaviour of the readers.

    Args:
        stream_cfg: configuration dictionary of the stream (reader specific keys, see the subclasses).

    Attributes:
        uses_level: True when ``read`` selects a pressure level from the file (ERA5 pressure-level files).
    """

    uses_level = False

    def __init__(self, stream_cfg=None):
        """Keep the stream configuration (stream_cfg: dictionary of the stream, default None = empty)."""
        self.cfg = dict(stream_cfg or {})

    def open(self, path):
        """Open a file (the caller closes it).

        Args:
            path: netCDF file.

        Returns:
            ``netCDF4.Dataset``.
        """
        import netCDF4

        return netCDF4.Dataset(path)

    def read_grid(self, path, grid_cfg):
        """Cell centres and weights of the grid of a file (implemented by the subclasses)."""
        raise NotImplementedError

    def read(self, ds, var, rec, level_hpa=None):
        """One record of one variable on all cells (implemented by the subclasses)."""
        raise NotImplementedError


class NcolReader(BaseReader):
    """Variables ``(time, ncol)`` on an unstructured grid.

    Grid configuration (``grids:`` entry): ``lat`` and ``lon`` (names of the 1-D coordinate variables, default ``lat`` and ``lon``) and ``area``
    (name of the cell-area variable, ``cos_lat`` for cos(latitude) weights, or null for equal weights).
    """

    def read_grid(self, path, grid_cfg):
        """Cell centres (degrees) and cell areas of an unstructured grid file.

        Args:
            path: a file of the stream.
            grid_cfg: grid configuration (see the class docstring).

        Returns:
            dictionary with ``lat_deg``, ``lon_deg`` (1-D float64) and ``area`` (1-D float64 or None).
        """
        with self.open(path) as ds:
            lat, lon = _to_degrees(ds.variables[grid_cfg.get("lat", "lat")][:], ds.variables[grid_cfg.get("lon", "lon")][:])
            area_name = grid_cfg.get("area")
            if area_name is None:
                area = None
            elif area_name == "cos_lat":
                area = np.cos(np.radians(lat))
            else:
                area = np.asarray(ds.variables[area_name][:], dtype=np.float64)
        return {"lat_deg": lat, "lon_deg": lon, "area": area}

    def read(self, ds, var, rec, level_hpa=None):
        """One record of a ``(time, ncol)`` variable.

        Args:
            ds: open dataset.
            var: variable name.
            rec: record (time index) in the file.
            level_hpa: ignored (the pressure level is part of the variable name in these files).

        Returns:
            1-D float32 array of all cells, NaN where masked.
        """
        variable = ds.variables[var]
        if variable.ndim != 2:
            raise ValueError(f"{var} has dimensions {variable.dimensions}; the ncol reader needs (time, cell)")
        return _to_float32(variable[rec, :])


class LatLonReader(BaseReader):
    """Variables ``(time, lat, lon)`` on a regular grid; cells are numbered ``ilat * nlon + ilon``.

    Grid configuration: ``lat`` and ``lon`` (names of the 1-D coordinate variables, default ``latitude`` and ``longitude``); ``area`` is ``cos_lat``
    (default) or null. Stream configuration: ``chunk_cache_max_mb`` (default 512) bounds the HDF5 chunk cache set for chunked variables.
    """

    def open(self, path):
        """Open a file and give every chunked variable an HDF5 chunk cache that holds all chunks of one time block.

        Without it the chunks of a full lat-lon field would be decompressed again for every access. Args: path (netCDF file). Returns: dataset.
        """
        ds = super().open(path)
        limit = int(float(self.cfg.get("chunk_cache_max_mb", 512)) * 1e6)
        for variable in ds.variables.values():
            chunks = variable.chunking() if variable.ndim >= 3 else "contiguous"
            if chunks != "contiguous":
                # Size of all chunks that one full spatial field of one time touches (the first dimension is time)
                chunk_bytes = int(np.prod(chunks)) * variable.dtype.itemsize
                n_spatial = int(np.prod([int(np.ceil(n / c)) for n, c in zip(variable.shape[1:], chunks[1:])]))
                variable.set_var_chunk_cache(size=min(limit, int(chunk_bytes * n_spatial * 1.1)), nelems=1009, preemption=0.75)
        return ds

    def read_grid(self, path, grid_cfg):
        """Cell centres (degrees) and weights of a regular grid file (flattened latitude-major).

        Args:
            path: a file of the stream.
            grid_cfg: grid configuration (see the class docstring).

        Returns:
            dictionary with ``lat_deg``, ``lon_deg`` (1-D float64, length nlat * nlon) and ``area`` (cos latitude or None).
        """
        with self.open(path) as ds:
            lat1 = np.asarray(ds.variables[grid_cfg.get("lat", "latitude")][:], dtype=np.float64)
            lon1 = np.asarray(ds.variables[grid_cfg.get("lon", "longitude")][:], dtype=np.float64)
        lat2, lon2 = np.meshgrid(lat1, lon1, indexing="ij")
        area = np.cos(np.radians(lat2)).ravel() if grid_cfg.get("area", "cos_lat") == "cos_lat" else None
        return {"lat_deg": lat2.ravel(), "lon_deg": lon2.ravel(), "area": area}

    def read(self, ds, var, rec, level_hpa=None):
        """One record of a ``(time, lat, lon)`` variable.

        Args:
            ds: open dataset.
            var: variable name.
            rec: record (time index) in the file.
            level_hpa: ignored.

        Returns:
            1-D float32 array (nlat * nlon).
        """
        variable = ds.variables[var]
        if variable.ndim != 3:
            raise ValueError(f"{var} has dimensions {variable.dimensions}; the latlon reader needs (time, lat, lon)")
        return _to_float32(variable[rec, :, :]).ravel()


class LatLonLevelReader(LatLonReader):
    """Variables ``(time, level, lat, lon)``; the level is chosen by value from the level coordinate (``level_dim``, default ``level``)."""

    uses_level = True

    def read(self, ds, var, rec, level_hpa=None):
        """One level of one record of a ``(time, level, lat, lon)`` variable.

        Args:
            ds: open dataset.
            var: variable name.
            rec: record (time index) in the file.
            level_hpa: pressure level in hPa (must exist in the level coordinate).

        Returns:
            1-D float32 array (nlat * nlon).
        """
        variable = ds.variables[var]
        if variable.ndim != 4:
            raise ValueError(f"{var} has dimensions {variable.dimensions}; the latlon_level reader needs (time, level, lat, lon)")
        if level_hpa is None:
            raise ValueError(f"{var}: a level_hpa is needed for pressure-level files")
        levels = np.asarray(ds.variables[self.cfg.get("level_dim", "level")][:], dtype=np.float64)
        matches = np.flatnonzero(np.isclose(levels, float(level_hpa)))
        if matches.size != 1:
            raise ValueError(f"level {level_hpa} hPa not found exactly once in {levels.tolist()}")
        return _to_float32(variable[rec, int(matches[0]), :, :]).ravel()


READERS = {"ncol": NcolReader, "latlon": LatLonReader, "latlon_level": LatLonLevelReader}


def make_reader(stream_cfg):
    """Reader object of a stream configuration.

    Args:
        stream_cfg: stream dictionary with the key ``reader`` (``ncol``, ``latlon`` or ``latlon_level``).

    Returns:
        reader instance.
    """
    kind = stream_cfg.get("reader")
    if kind not in READERS:
        raise ValueError(f"unknown reader '{kind}' (available: {sorted(READERS)})")
    return READERS[kind](stream_cfg)
