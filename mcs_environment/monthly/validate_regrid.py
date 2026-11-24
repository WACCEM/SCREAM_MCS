#!/usr/bin/env python
"""Checks of the regridding of one dataset and month: are the weights applied right, and do the 1 degree fields keep the native ones?

Checks (a failed one makes the exit code 1):
  1. numpy against NCO: the fields without missing values are regridded with ``ncremap -m`` and with ``regrid.Remapper``; they must agree
     (relative difference <= 1e-5) where ncremap has weights. This checks the weight file, its index convention and the numpy application.
  2. analytic field: f = cos(lat) * cos(lon) on the source cells regridded and compared with f on the 1 degree grid (rms <= 2e-3, between
     60S and 60N): this checks that the cell centres of the source grid file are the ones of the data.
  3. data: area-mean (60S-60N) of every variable native vs 1 degree (difference <= 2 % of the rms of the field), pattern correlation (>= 0.99), and the
     share of missing cells before and after (below-ground cells at 850 hPa; the ring added by the stencil is reported, not judged).

Example (compute node):
    python validate_regrid.py --config config/100km.yaml --month 2009-01
"""

import argparse
import sys
import tempfile
from pathlib import Path

import netCDF4
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from envmonthly.config import load_dataset  # noqa: E402
from envmonthly.ncotools import apply_map, read_grid_centres  # noqa: E402
from envmonthly.regrid import Remapper, _source_grid_file, target_grid_file  # noqa: E402
from envmonthly.timeaxis import parse_month  # noqa: E402


def load(path, name):
    """Variable ``name`` (first record) of a file as float64 with NaN for fill values."""
    with netCDF4.Dataset(path) as ds:
        x = np.ma.filled(ds[name][0].astype(np.float64), np.nan)
    x[np.abs(x) > 1e19] = np.nan
    return x


def area_stats(field, lat, weight):
    """Area-weighted mean and rms of a field over the finite cells between 60S and 60N.

    Args:
        field: values per cell (any shape).
        lat: latitude of every cell, same shape.
        weight: area weight of every cell, same shape.

    Returns:
        (mean, rms) as floats.
    """
    use = np.isfinite(field) & (np.abs(lat) <= 60.0)
    w = weight[use]
    return float((field[use] * w).sum() / w.sum()), float(np.sqrt((field[use] ** 2 * w).sum() / w.sum()))


def source_area(src_grid, lat):
    """Cell areas of the source grid: ``grid_area`` of the SCRIP file when it has it, else cos(latitude) of the cell centres."""
    with netCDF4.Dataset(src_grid) as g:
        if "grid_area" in g.variables:
            return np.asarray(g["grid_area"][:], dtype=np.float64)
    return np.cos(np.deg2rad(lat))


def main():
    """Run the three checks for one dataset and month and print a table."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--month", default=None, help="YYYY-MM (default: the first month of the period)")
    args = ap.parse_args()
    ds = load_dataset(args.config)
    year, month = parse_month(args.month) if args.month else ds.start
    native, latlon = ds.native_path(year, month), ds.latlon_path(year, month)
    remapper = Remapper(ds.map_path(), target_grid_file(ds), ds.common.valid_weight_fraction)
    problems = []
    lat2d = np.repeat(remapper.lat[:, None], remapper.lon.size, axis=1)

    # 1. numpy against ncremap on the variables without missing values (ncremap leaves cells without weights at zero: compare cells with weights)
    with tempfile.TemporaryDirectory(dir=ds.root(), prefix=".validate_") as tmp:
        out = apply_map(ds.map_path(), native, Path(tmp) / "nco.nc", ds.output_names(), ds.common.deflate)
        print(f"{ds.name} {year}-{month:02d}")
        print("1. numpy vs ncremap (variables without missing values)")
        has_weight = (remapper.total > 0).reshape(remapper.shape)
        for name in ds.output_names():
            nat = load(native, name)
            if np.isnan(nat).any():
                print(f"   {name:7s} has missing source cells: not compared (ncremap handles them differently)")
                continue
            ours, nco = remapper.apply(nat), load(out, name)
            diff = float(np.abs(ours - nco)[has_weight].max())
            scale = float(np.abs(nco[has_weight]).max())
            print(f"   {name:7s} max |numpy - ncremap| = {diff:.3e}  ({diff / max(scale, 1e-30):.1e} of the largest value)")
            if diff / max(scale, 1e-30) > 1e-5:
                problems.append(f"{name}: numpy and ncremap differ")

    # 2. analytic field through the weights
    s_lat, s_lon = read_grid_centres(_source_grid_file(ds))
    f_src = np.cos(np.deg2rad(s_lat)) * np.cos(np.deg2rad(s_lon))
    f_dst = np.cos(np.deg2rad(lat2d)) * np.cos(np.deg2rad(remapper.lon))[None, :]
    band = np.abs(lat2d) <= 60.0
    rms = float(np.sqrt(np.nanmean((remapper.apply(f_src) - f_dst)[band] ** 2)))
    print(f"2. analytic field cos(lat)cos(lon): rms error on the 1 degree grid (60S-60N) = {rms:.2e}")
    if not rms <= 2e-3:
        problems.append("the analytic field is not reproduced (cell centres of the source grid file are not those of the data?)")

    # 3. the data: area mean, pattern correlation, missing cells (differences are measured against the rms of the field: the mean of omega is ~0)
    print("3. data (60S-60N)           native mean   1 deg mean   diff / rms   pattern corr   missing native -> 1 deg")
    w_src = source_area(_source_grid_file(ds), s_lat)
    w_dst = np.cos(np.deg2rad(lat2d))
    for name in ds.output_names():
        nat, reg = load(native, name).ravel(), load(latlon, name)
        (m_nat, rms_nat), (m_reg, _) = area_stats(nat, s_lat, w_src), area_stats(reg, lat2d, w_dst)
        # Pattern correlation on the 1 degree grid: the native field regridded with the same weights is the reference
        ref = remapper.apply(nat)
        both = np.isfinite(ref) & np.isfinite(reg) & band
        corr = float(np.corrcoef(ref[both], reg[both])[0, 1]) if both.sum() > 10 else float("nan")
        rel = (m_reg - m_nat) / rms_nat
        print(f"   {name:7s} {m_nat:20.6g} {m_reg:12.6g} {100 * rel:9.2f} % {corr:13.5f}   {100 * np.isnan(nat).mean():5.2f} % -> {100 * np.isnan(reg).mean():5.2f} %")
        if abs(rel) > 0.02 or not corr >= 0.99:
            problems.append(f"{name}: 1 degree field differs from the native one (diff/rms {rel:.3f}, corr {corr:.4f})")
    print("PROBLEMS:" if problems else "all checks passed", *problems, sep="\n  " if problems else " ")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
