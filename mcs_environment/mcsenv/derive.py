"""Derived variables, unit conversion and the below-ground mask.

A *variable spec* is the dictionary of one standard variable inside a stream of ``config/sources.yaml``::

    rh850: {from: RelativeHumidity_at_850hPa, scale: 100, level_hpa: 850, units: "%"}
    q850:  {derive: q_from_rh, inputs: {rh: RelativeHumidity_at_850hPa, t: T_mid_at_850hPa}, level_hpa: 850, units: "kg kg-1"}
    pr:    {derive: sum, inputs: [precip_liq_surf_mass_flux, precip_ice_surf_mass_flux], scale: 3.6e6, units: "mm h-1"}

The value of a spec is ``derived * scale + offset`` (defaults 1 and 0). ``level_hpa`` is the pressure level of the variable: it selects the level
of pressure-level files (ERA5), is the pressure of the formulas, and switches on the below-ground mask when the source defines a surface pressure.
"""

from __future__ import annotations

import numpy as np

# Ratio of the gas constants of dry air and water vapour (Rd / Rv), as used by the atmosphere models
EPS = 0.622


def esat_liquid(t_k):
    """Saturation vapour pressure over liquid water (Murphy and Koop 2005).

    Args:
        t_k: temperature in K (array or scalar, NaN allowed).

    Returns:
        saturation vapour pressure in Pa (float64, same shape as the input).
    """
    # Work in float64 and ignore the warnings that NaN or non-physical temperatures would raise
    t = np.asarray(t_k, dtype=np.float64)
    with np.errstate(all="ignore"):
        return np.exp(54.842763 - 6763.22 / t - 4.210 * np.log(t) + 0.000367 * t
                      + np.tanh(0.0415 * (t - 218.8)) * (53.878 - 1331.22 / t - 9.44523 * np.log(t) + 0.014025 * t))


def qsat_liquid(t_k, p_pa):
    """Saturation specific humidity over liquid water, ``eps * es / (p - (1 - eps) * es)``.

    Args:
        t_k: temperature in K.
        p_pa: pressure in Pa (scalar or array broadcastable to ``t_k``).

    Returns:
        saturation specific humidity in kg/kg (float64).
    """
    es = esat_liquid(t_k)
    with np.errstate(all="ignore"):
        return EPS * es / (np.asarray(p_pa, dtype=np.float64) - (1.0 - EPS) * es)


def q_from_rh(rh_fraction, t_k, p_pa):
    """Specific humidity from relative humidity, with RH defined as ``q / qsat`` (as CAM, EAM and EAMxx do).

    Args:
        rh_fraction: relative humidity as a fraction (1 = saturated).
        t_k: temperature in K.
        p_pa: pressure in Pa.

    Returns:
        specific humidity in kg/kg (float64).
    """
    return np.asarray(rh_fraction, dtype=np.float64) * qsat_liquid(t_k, p_pa)


def rh_from_q(q_kgkg, t_k, p_pa):
    """Relative humidity (fraction, ``q / qsat``) from specific humidity.

    Args:
        q_kgkg: specific humidity in kg/kg.
        t_k: temperature in K.
        p_pa: pressure in Pa.

    Returns:
        relative humidity as a fraction (float64).
    """
    with np.errstate(all="ignore"):
        return np.asarray(q_kgkg, dtype=np.float64) / qsat_liquid(t_k, p_pa)


def raw_names(spec):
    """Names of the raw file variables a variable spec needs.

    Args:
        spec: variable spec (dictionary, see the module docstring).

    Returns:
        list of raw variable names (a ``from`` spec has one, a ``derive`` spec the values of ``inputs``).
    """
    # A plain variable reads one raw name; a derived variable reads every input (a list for ``sum``, a role dictionary for the formulas)
    if "from" in spec:
        return [spec["from"]]
    inputs = spec.get("inputs")
    if isinstance(inputs, dict):
        return list(inputs.values())
    if isinstance(inputs, (list, tuple)):
        return list(inputs)
    raise ValueError(f"variable spec has neither 'from' nor 'inputs': {spec}")


def compute_variable(spec, raw):
    """Value of one standard variable from the raw arrays of one time step.

    Args:
        spec: variable spec (``from`` or ``derive`` + ``inputs``, optional ``scale``, ``offset``, ``level_hpa``, ``rh_units``).
        raw: dictionary raw variable name -> 1-D array (all cells), NaN where invalid.

    Returns:
        1-D float64 array of the standard variable in its output units.
    """
    # Step 1: the derived value in the units of the raw files
    derive = spec.get("derive")
    if derive is None:
        value = np.asarray(raw[spec["from"]], dtype=np.float64)
    elif derive == "sum":
        # Sum of all inputs (NaN in any input gives NaN)
        value = np.sum([np.asarray(raw[n], dtype=np.float64) for n in spec["inputs"]], axis=0)
    elif derive == "q_from_rh":
        # Specific humidity from RH and T at the pressure level of the variable (RH given as a fraction unless rh_units is percent)
        rh = np.asarray(raw[spec["inputs"]["rh"]], dtype=np.float64)
        if spec.get("rh_units", "fraction") == "percent":
            rh = rh / 100.0
        value = q_from_rh(rh, raw[spec["inputs"]["t"]], _level_pa(spec))
    elif derive == "rh_from_q":
        # RH (fraction) from specific humidity and T at the pressure level of the variable
        value = rh_from_q(raw[spec["inputs"]["q"]], raw[spec["inputs"]["t"]], _level_pa(spec))
    else:
        raise ValueError(f"unknown derive rule '{derive}'")
    # Step 2: conversion to the output units
    return value * float(spec.get("scale", 1.0)) + float(spec.get("offset", 0.0))


def _level_pa(spec):
    """Pressure of a spec in Pa from ``level_hpa`` (error when the spec has none)."""
    if "level_hpa" not in spec:
        raise ValueError(f"derive rule '{spec.get('derive')}' needs level_hpa: {spec}")
    return float(spec["level_hpa"]) * 100.0


def mask_below_ground(value, ps_pa, level_hpa):
    """Set a pressure-level field to NaN where the surface pressure is below the level (the level lies under the ground).

    Args:
        value: 1-D array of the variable on all cells.
        ps_pa: 1-D array of the surface pressure in Pa on the same cells (NaN = unknown, which also masks).
        level_hpa: pressure level of the variable in hPa.

    Returns:
        copy of ``value`` with NaN where ``ps < level`` or ``ps`` is not finite.
    """
    # Cells with a surface pressure smaller than the level, or without a surface pressure, cannot be trusted at this level
    out = np.array(value, dtype=np.float64, copy=True)
    out[~(np.asarray(ps_pa, dtype=np.float64) >= float(level_hpa) * 100.0)] = np.nan
    return out
