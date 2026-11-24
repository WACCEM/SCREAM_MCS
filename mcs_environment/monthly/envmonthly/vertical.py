"""Vertical interpolation of model-level fields to a pressure level, and the below-ground mask.

``interp_to_plev`` is the algorithm of ``e3sm_polun/scripts/interp_to_plev.py`` (``interp_column_logp``): linear in ln(p), NaN where the target
pressure lies above the highest or below the lowest model level, written for one record shaped (level, cell) instead of (time, level, cell).
The tests compare the two on random columns.
"""

from __future__ import annotations

import numpy as np


def hybrid_pressure(a, b, p0, ps):
    """Pressure of hybrid sigma-pressure levels, ``p = a * p0 + b * ps``.

    Args:
        a, b: hybrid coefficients (hyam, hybm) as 1-D arrays of the levels.
        p0: reference pressure in Pa (scalar).
        ps: surface pressure in Pa, 1-D over the cells.

    Returns:
        pressure in Pa, float64 array (level, cell). With the monthly-mean ``ps`` this is exactly the monthly mean of the pressure of the level.
    """
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    return a[:, None] * float(p0) + b[:, None] * np.asarray(ps, dtype=np.float64)[None, :]


def check_pressure_order(pres):
    """Raise ``ValueError`` unless the pressure increases from the first level (top) to the last (bottom).

    Args:
        pres: pressure (level, cell).
    """
    # The mean over the cells of the first and last level decides (NaN cells are ignored)
    top, bottom = np.nanmean(pres[0]), np.nanmean(pres[-1])
    if not top < bottom:
        raise ValueError(f"pressure must increase with the level index (mean of the first level {top:.1f} Pa, of the last {bottom:.1f} Pa)")


def interp_to_plev(var, pres, plev_pa):
    """Interpolate a field to one pressure level, linearly in ln(p).

    Args:
        var: field (level, cell) on model levels; NaN where missing.
        pres: pressure of the levels in Pa (level, cell), increasing with the level index.
        plev_pa: target pressure in Pa.

    Returns:
        1-D float64 array over the cells: the field at ``plev_pa``; NaN where the target is above the first level or below the last level
        (below the ground), or where one of the two bracketing values is NaN.
    """
    var = np.asarray(var, dtype=np.float64)
    pres = np.asarray(pres, dtype=np.float64)
    nk, nc = var.shape
    # Index of the level just above the target (lower pressure): k = (number of levels with p < target) - 1
    k = np.sum(pres < plev_pa, axis=0) - 1
    valid = (k >= 0) & (k < nk - 1)
    kc = np.clip(k, 0, nk - 2)
    cells = np.arange(nc)
    # The two bracketing levels of every cell
    p1, p2 = pres[kc, cells], pres[kc + 1, cells]
    v1, v2 = var[kc, cells], var[kc + 1, cells]
    # Linear in ln(p): weight of the lower level
    with np.errstate(all="ignore"):
        w = (np.log(plev_pa) - np.log(p1)) / (np.log(p2) - np.log(p1))
        res = v1 + w * (v2 - v1)
    return np.where(valid, res, np.nan)


def mask_below_ground(value, ps_pa, plev_hpa):
    """Set a pressure-level field to NaN where the surface pressure is below the level (the level lies under the ground).

    Same rule as ``mcsenv.derive.mask_below_ground``.

    Args:
        value: field of any shape.
        ps_pa: surface pressure in Pa on the same shape (NaN = unknown, which also masks).
        plev_hpa: pressure level in hPa.

    Returns:
        float64 copy of ``value`` with NaN where ``ps < level`` or ``ps`` is not finite.
    """
    out = np.array(value, dtype=np.float64, copy=True)
    out[~(np.asarray(ps_pa, dtype=np.float64) >= float(plev_hpa) * 100.0)] = np.nan
    return out
