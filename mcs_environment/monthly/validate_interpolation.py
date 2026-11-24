#!/usr/bin/env python
"""Checks of the vertical interpolation and of the ERA5 monthly files, against independent data (like validate_humidity_formulas.py).

A. Models: the 3-D fields of the monthly files are interpolated with the code of the product and compared with the diagnostics at the same
   pressure level that the models store (computed online, every time step, then averaged):
     100km     OMEGA (3-D, hybrid levels)      -> 500 hPa  vs  OMEGA500
     3km_CTL   omega (3-D, p_mid levels)       -> 500 hPa  vs  omega_at_500hPa;  T_mid -> 850 hPa vs T_mid_at_850hPa
     3km_TUNE  the same
   The two differ a little by construction (the product interpolates monthly means on monthly-mean pressure, the model interpolates every step).
   The table gives the area-mean difference, the rms difference and the correlation for all cells, for cells with a surface pressure of at least
   700 hPa, and for ocean / lowland cells (at least 950 hPa), which are the cells that are judged. Measured 2026-11-23: over the ocean and the
   lowlands the interpolation reproduces the stored diagnostic (SCREAM omega at 500 hPa: rms difference 0.0003 over the ocean, 0.0016 over land with
   ps > 950 hPa, against an rms of 0.04 Pa/s; T_mid at 850 hPa: 0.13 K), but over high terrain (ps < 800 hPa) the SCREAM omega differs by 0.04
   Pa/s (corr 0.93): the SCREAM monthly files exist only on ne30pg2, coarsened from 3 km, and interpolating coarsened fields on the
   monthly-mean pressure is not the coarsened online interpolation where the surface is steep. E3SM, whose grid is the native one, agrees
   everywhere (100 km: corr 0.99997).
B. ERA5: Q at 850 hPa and R at 500 hPa of the monthly pressure-level files against the mean of the 6-hourly (00, 06, 12, 18 UTC) snapshots of
   the hourly files of the same month (pscratch copy): is the "monthly" file a monthly mean?

Example (compute node):
    python validate_interpolation.py
"""

import glob
import sys
from pathlib import Path

import netCDF4
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from envmonthly import readers, vertical  # noqa: E402
from envmonthly.config import load_dataset  # noqa: E402

CONFIG = Path(__file__).resolve().parent / "config"
# (dataset, month, [(raw 3-D variable, level hPa, stored 2-D diagnostic at that level)])
MODEL_CASES = [("100km", (2009, 1), [("OMEGA", 500, "OMEGA500")]),
               ("3km_CTL", (1995, 1), [("omega", 500, "omega_at_500hPa"), ("T_mid", 850, "T_mid_at_850hPa")]),
               ("3km_TUNE", (2019, 8), [("omega", 500, "omega_at_500hPa"), ("T_mid", 850, "T_mid_at_850hPa")])]
ERA5_MONTH = (2007, 1)


def compare(label, ours, ref, weight, ps):
    """Print the comparison rows of one pair of fields: all cells, cells with a surface pressure of at least 700 hPa, and ocean / lowland cells
    (at least 950 hPa), where the interpolation is judged.

    Args:
        ours, ref: fields on the same cells (NaN = missing).
        weight: cell areas.
        ps: surface pressure in Pa on the same cells.

    Returns:
        True when, over the ocean / lowland cells, the correlation is at least 0.995 and the area-mean difference is below 2 % of the rms of
        the reference (the correlation limit was set after the first measurements: SCREAM omega 0.9985 / 0.9991, E3SM 0.99998).
    """
    both = np.isfinite(ours) & np.isfinite(ref)
    ok = True
    for tag, use in (("all cells", both), ("ps >= 700 hPa", both & (ps >= 70000.0)), ("ps >= 950 hPa (judged)", both & (ps >= 95000.0))):
        w = weight[use]
        d = ours[use] - ref[use]
        rms_ref = np.sqrt((ref[use] ** 2 * w).sum() / w.sum())
        mean_diff = (d * w).sum() / w.sum()
        corr = float(np.corrcoef(ours[use], ref[use])[0, 1])
        print(f"   {label:34s} {tag:22s} mean diff {mean_diff:11.4g}  rms diff {np.sqrt((d ** 2 * w).sum() / w.sum()):10.4g}  "
              f"rms of reference {rms_ref:9.4g}  corr {corr:.5f}  cells {use.sum()}")
        if tag.endswith("(judged)"):
            ok = corr >= 0.995 and abs(mean_diff) <= 0.02 * rms_ref
    return ok


def models():
    """Part A. Returns True when every comparison passes."""
    ok = True
    for name, (year, month), cases in MODEL_CASES:
        ds_cfg = load_dataset(CONFIG / f"{name}.yaml")
        stream = ds_cfg.streams[0]
        path = readers.find_files(stream, year, month, ds_cfg.calendar)[0]
        print(f"A. {name} {year}-{month:02d}")
        with netCDF4.Dataset(path) as ds:
            pres = readers.ncol_pressure(ds, stream)
            # Cell areas and surface pressure of the dataset (area variable of the file if there is one, else equal areas)
            area = np.asarray(ds["area"][:], dtype=np.float64) if "area" in ds.variables else np.ones(pres.shape[1])
            ps, _ = readers._ncol_read(ds, stream, next(v.raw for v in ds_cfg.variables if v.name == "ps"))
            for raw, level, stored in cases:
                field, _ = readers._ncol_read(ds, stream, raw)
                ours = vertical.interp_to_plev(field, pres, level * 100.0)
                ref, _ = readers._ncol_read(ds, stream, stored)
                ok &= compare(f"{raw} -> {level} hPa vs {stored}", ours, ref, area, ps)
    return ok


def era5():
    """Part B. Returns True when both comparisons pass."""
    ds_cfg = load_dataset(CONFIG / "ERA5.yaml")
    year, month = ERA5_MONTH
    streams = {s.name: s for s in ds_cfg.streams}
    ok = True
    print(f"B. ERA5 monthly file vs the mean of the 6-hourly snapshots, {year}-{month:02d}")
    for stream_name, family, raw, level in (("q_monthly", "128_133_q", "Q", 850), ("r_monthly", "128_157_r", "R", 500)):
        # The monthly file
        monthly_file = readers.find_files(streams[stream_name], year, month, ds_cfg.calendar)[0]
        with netCDF4.Dataset(monthly_file) as ds:
            k = int(np.where(np.abs(ds["level"][:] - level) < 1e-6)[0][0])
            lat = np.asarray(ds["latitude"][:], dtype=np.float64)
            monthly = np.ma.filled(ds[raw][0, k].astype(np.float64), np.nan)
        # The hourly daily files of the same month (the folder of the W stream, another variable family), hours 0, 6, 12, 18
        w = streams["w_hourly"]
        pattern = str(Path(w.root) / w.pattern.format(yyyy=f"{year:04d}", mm=f"{month:02d}")).replace("128_135_w", family)
        files = sorted(glob.glob(pattern))
        total, n = np.zeros_like(monthly), 0
        for path in files:
            with netCDF4.Dataset(path) as ds:
                kk = int(np.where(np.abs(ds["level"][:] - level) < 1e-6)[0][0])
                for hour in (0, 6, 12, 18):
                    total += np.ma.filled(ds[raw][hour, kk].astype(np.float64), np.nan)
                    n += 1
        six_hourly = total / max(n, 1)
        band = np.abs(lat) <= 60.0
        weight = np.broadcast_to(np.cos(np.deg2rad(lat))[:, None], monthly.shape).copy()
        weight[~band] = 0.0
        ok &= compare(f"{raw} {level} hPa: monthly vs {n} snapshots", monthly, six_hourly, weight, np.full(monthly.shape, 1.0e5))
    return ok


def main():
    """Run parts A and B; exit code 1 when a comparison fails."""
    ok_a = models()
    ok_b = era5()
    print("all checks passed" if ok_a and ok_b else "SOME CHECKS FAILED")
    sys.exit(0 if ok_a and ok_b else 1)


if __name__ == "__main__":
    main()
