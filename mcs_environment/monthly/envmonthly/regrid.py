"""Step 2 of the product: native-grid monthly files -> the 1 degree grid, with the ESMF bilinear weights of ``make_weights.py``.

The weights are made by ``ncremap`` (step 0) and applied here with numpy, because the product needs explicit rules that ncremap does not give:

* source cells that are NaN (below the ground at 850 hPa) are left out and the destination value is the weighted mean of the VALID source
  cells if their weights add up to at least ``valid_weight_fraction`` of the destination cell's weight (default 0.5), otherwise it is missing;
* destination cells without any weight (the two polar rows for the ne30pg2 source) are missing, not zero.

``ncotools.apply_map`` (``ncremap -m``) is the independent NCO result that the tests compare this with on fields without missing values.
"""

from __future__ import annotations

import time
from pathlib import Path

import netCDF4
import numpy as np

from .config import load_dataset
from .native import MonthResult
from .ncotools import read_grid_centres, read_map
from .writer import check_compression, write_env_file

# Largest accepted difference [degrees] between the coordinates of a native file and the cell centres of the source grid file of the map.
# The SCREAM ne30pg2 files carry centres that differ from the SCRIP file by up to 0.09 degree (same cell order); anything larger is a
# different grid or a different cell order.
SOURCE_COORD_TOL = {"ncol": 0.15, "latlon": 1e-4}


class Remapper:
    """Apply an ESMF weight file to fields on the source grid.

    Args:
        map_path: weight file (``read_map``).
        dst_grid: SCRIP file of the regular destination grid (supplies the 1-D axes).
        valid_fraction: a destination cell is valid when the weights of the valid source cells add up to at least this fraction of its total
            weight (default 0.5).

    Attributes:
        lat, lon: 1-D destination axes; shape = (lat.size, lon.size).
    """

    def __init__(self, map_path, dst_grid, valid_fraction=0.5):
        """Read the weights and the destination axes (cell index = ilat * nlon + ilon)."""
        self.m = read_map(map_path)
        self.valid_fraction = float(valid_fraction)
        # Destination axes from the SCRIP centres of a regular grid
        with netCDF4.Dataset(dst_grid) as g:
            nlon, nlat = (int(x) for x in g["grid_dims"][:])
        d_lat, d_lon = read_grid_centres(dst_grid)
        self.lat, self.lon = d_lat.reshape(nlat, nlon)[:, 0], d_lon.reshape(nlat, nlon)[0, :]
        if self.m["n_b"] != nlat * nlon:
            raise ValueError(f"{map_path}: {self.m['n_b']} destination cells, the destination grid has {nlat * nlon}")
        # Total weight of every destination cell (0 = no weights: the cell is missing)
        self.total = np.bincount(self.m["row"], weights=self.m["S"], minlength=self.m["n_b"])

    @property
    def shape(self):
        """Shape (nlat, nlon) of a regridded field."""
        return self.lat.size, self.lon.size

    def apply(self, field):
        """Regrid one field.

        Args:
            field: values on the source cells, any shape with ``n_a`` elements (NaN = missing).

        Returns:
            float64 array (nlat, nlon): the weighted mean of the valid source values (NaN where too little weight is valid, or no weight).
        """
        x = np.asarray(field, dtype=np.float64).ravel()
        if x.size != self.m["n_a"]:
            raise ValueError(f"the field has {x.size} cells, the map expects {self.m['n_a']}")
        valid = np.isfinite(x)
        row, col, weight = self.m["row"], self.m["col"], self.m["S"]
        n_b = self.m["n_b"]
        # Weighted sum and weight sum of the valid source cells of every destination cell
        num = np.bincount(row, weights=weight * np.where(valid, x, 0.0)[col], minlength=n_b)
        den = np.bincount(row, weights=weight * valid[col], minlength=n_b)
        with np.errstate(all="ignore"):
            # den == 0 covers both a destination cell without weights and one whose source cells are all missing
            out = np.where((den > 0) & (den >= self.valid_fraction * self.total), num / den, np.nan)
        return out.reshape(self.shape)


def check_source_grid(grid, src_grid, kind):
    """Verify that the coordinates of a native file are those of the source grid file of the map (same cells, same order).

    Args:
        grid: dict from ``readers.read_grid`` (``lat``, ``lon``; 1-D per cell for ncol, axes for latlon).
        src_grid: SCRIP file of the source grid.
        kind: ``"ncol"`` or ``"latlon"``.

    Returns:
        None. Raises ``ValueError`` when the largest coordinate difference exceeds ``SOURCE_COORD_TOL``.
    """
    s_lat, s_lon = read_grid_centres(src_grid)
    # A regular grid: expand the axes to the cell list (latitude slowest)
    lat, lon = (grid["lat"], grid["lon"]) if kind == "ncol" else (np.repeat(grid["lat"], grid["lon"].size), np.tile(grid["lon"], grid["lat"].size))
    if lat.size != s_lat.size:
        raise ValueError(f"the native file has {lat.size} cells, the source grid file {s_lat.size}")
    dlat = float(np.abs(lat - s_lat).max())
    dlon = float(np.abs((lon - s_lon + 180.0) % 360.0 - 180.0).max())
    if max(dlat, dlon) > SOURCE_COORD_TOL[kind]:
        raise ValueError(f"native coordinates differ from the source grid file by {dlat:.4f} (lat) / {dlon:.4f} (lon) degrees")


def regrid_month(ds_cfg, remapper, year, month, overwrite=False):
    """Regrid the native file of one month to the 1 degree grid. Never raises for data problems (``status="failed"`` with the reason).

    Args:
        ds_cfg: ``config.Dataset``.
        remapper: ``Remapper`` of the dataset's map.
        year, month: the month.
        overwrite: replace an existing file (default False: skipped).

    Returns:
        ``MonthResult`` (``nan_fraction`` per variable of the 1 degree file).
    """
    t0 = time.time()
    src, out = ds_cfg.native_path(year, month), ds_cfg.latlon_path(year, month)
    if out.exists() and not overwrite:
        return MonthResult(year, month, "skipped", "file exists", time.time() - t0)
    try:
        if not src.exists():
            raise FileNotFoundError(f"native file {src.name} does not exist (run make_monthly_native.py first)")
        fields, meta = {}, {}
        with netCDF4.Dataset(src) as nat:
            # 1. The native file must be on the source grid of the map
            kind = "ncol" if "ncol" in nat.dimensions else "latlon"
            check_source_grid({"lat": np.asarray(nat["lat"][:], dtype=np.float64), "lon": np.asarray(nat["lon"][:], dtype=np.float64)},
                              _source_grid_file(ds_cfg), kind)
            # 2. Every output variable: NaN for missing, regrid, keep the attributes
            for name in ds_cfg.output_names():
                x = np.ma.filled(nat[name][0].astype(np.float64), np.nan)
                x[np.abs(x) > 1e19] = np.nan
                fields[name] = remapper.apply(x)[None]
                meta[name] = {k: nat[name].getncattr(k) for k in nat[name].ncattrs() if k not in ("_FillValue", "missing_value")}
            time_value, bounds = float(nat["time"][0]), [float(b) for b in nat["time_bnds"][0]]
            calendar = nat["time"].calendar
            gattrs = {k: nat.getncattr(k) for k in nat.ncattrs() if k not in ("Conventions", "date_created")}
        # 3. Write the 1 degree file
        gattrs["title"] = gattrs.get("title", "").replace("native grid", f"{ds_cfg.common.target['name']} 1 degree grid")
        gattrs["regrid_method"] = (f"ESMF {ds_cfg.common.method} weights made with ncremap and applied with numpy; destination cells with at least "
                                   f"{ds_cfg.common.valid_weight_fraction:g} of their weight on valid source cells are the weighted mean of those cells, "
                                   f"others (and cells without weights) are missing")
        gattrs["regrid_map"] = ds_cfg.map_path().name
        gattrs["native_file"] = src.name
        gattrs["history"] = "written by regrid_monthly.py (scream/mcs_environment/monthly)"
        write_env_file(out, {"kind": "latlon", "lat": remapper.lat, "lon": remapper.lon}, fields, meta,
                       {"values": [time_value], "bounds": [bounds], "calendar": calendar}, gattrs, deflate=ds_cfg.common.deflate)
        problems = check_compression(out, names=list(fields))
        if problems:
            raise RuntimeError("; ".join(problems))
        nan_fraction = {n: float(np.mean(~np.isfinite(a))) for n, a in fields.items()}
        return MonthResult(year, month, "written", "", time.time() - t0, nan_fraction)
    except Exception as exc:  # noqa: BLE001 - one bad month must not stop the run
        text = (str(exc).strip().splitlines() or [""])[0]
        return MonthResult(year, month, "failed", f"{type(exc).__name__}: {text}", time.time() - t0)


def _source_grid_file(ds_cfg):
    """SCRIP file of the dataset's source grid: the configured file, or the generated ``grid_<name>.nc`` in the maps folder."""
    spec = ds_cfg.common.sources[ds_cfg.grid]
    return spec["scrip"] if "scrip" in spec else str(Path(ds_cfg.common.maps_dir) / f"grid_{ds_cfg.grid}.nc")


def target_grid_file(ds_cfg):
    """SCRIP file of the target grid in the maps folder (made by ``make_weights.py``)."""
    return str(Path(ds_cfg.common.maps_dir) / f"grid_{ds_cfg.common.target['name']}.nc")


# One Remapper per worker process (loading the weights takes about a second): created on first use
_REMAPPERS = {}


def regrid_task(cfg_path, year, month, overwrite):
    """Pool task of step 2: load the dataset configuration (and the weights once per process) and regrid one month.

    Args:
        cfg_path: dataset YAML file.
        year, month: the month.
        overwrite: replace an existing file.

    Returns:
        ``MonthResult``.
    """
    ds_cfg = load_dataset(cfg_path)
    key = (cfg_path, str(ds_cfg.map_path()))
    if key not in _REMAPPERS:
        _REMAPPERS[key] = Remapper(ds_cfg.map_path(), target_grid_file(ds_cfg), ds_cfg.common.valid_weight_fraction)
    return regrid_month(ds_cfg, _REMAPPERS[key], year, month, overwrite)
