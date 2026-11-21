"""Source definitions: where the data are, which raw variable becomes which standard variable, in which units.

``config/sources.yaml`` has a ``defaults`` block and a ``sources`` block. A source (for example ``3km_CTL``) has::

    tracks:   MCS track Parquet file
    ps:       null, or {stream: <stream>, var: <raw name>}: surface pressure in Pa used to mask pressure-level variables below the ground
    grids:    name -> {stream: <stream whose first file defines the grid>, lat, lon, area}
    streams:  name -> {root, pattern, reader, grid, variables: {standard name: variable spec}}

A variable spec is described in ``derive.py``. Raw variable names appear only here, so a model with other names needs only another block.
Keys with the value ``null`` switch an option off (no flag-and-value pairs).
"""

from __future__ import annotations

import copy

import yaml

from .derive import raw_names
from .readers import READERS

# Values used when neither the source nor the defaults block sets a key
BUILTIN_DEFAULTS = {
    "diameters_km": [200, 400, 600],   # circle diameters in km
    "pre_start_hours": 24,             # hours before the MCS start that get rows (circle fixed at the start position)
    "step_hours": None,                # nominal row step; null = the step of the finest stream of the source
    "weighting": "area",               # area-weighted means ("none" = plain means)
    "empty_circle": "nearest_cell",    # a circle without a cell centre takes the nearest cell ("nan" = leave it empty)
    "max_missing_fraction": 0.05,      # largest share of rows without a frame in the primary stream group before the job stops
    "earth_radius_km": 6371.0,         # Earth radius for the circle radius
    "time_var": "time",                # name of the time variable in the files
}

# Long names of the standard variables (a spec can override them with ``long_name``)
LONG_NAMES = {
    "prw": "Total column water vapor",
    "q850": "Specific humidity at 850 hPa",
    "q500": "Specific humidity at 500 hPa",
    "rh850": "Relative humidity at 850 hPa",
    "rh500": "Relative humidity at 500 hPa",
    "omega850": "Pressure velocity at 850 hPa (positive downward)",
    "omega500": "Pressure velocity at 500 hPa (positive downward)",
    "pr": "Surface precipitation rate (instantaneous)",
}

_DERIVE_RULES = (None, "sum", "q_from_rh", "rh_from_q")


class ConfigError(ValueError):
    """The configuration is inconsistent (message names the source and the key)."""


def load_config(path, source):
    """Load ``sources.yaml`` and return the merged configuration of one source.

    Args:
        path: YAML file (``config/sources.yaml``).
        source: source name, for example ``"3km_CTL"``.

    Returns:
        dictionary of the source: built-in defaults, overridden by the ``defaults`` block, overridden by the source block; plus the key ``name``.
    """
    with open(path) as handle:
        raw = yaml.safe_load(handle)
    sources = raw.get("sources", {})
    if source not in sources:
        raise ConfigError(f"source '{source}' not in {path} (available: {sorted(sources)})")
    # Defaults first, then the source block on top
    merged = copy.deepcopy(BUILTIN_DEFAULTS)
    merged.update(copy.deepcopy(raw.get("defaults") or {}))
    merged.update(copy.deepcopy(sources[source]))
    merged["name"] = source
    validate_source(merged)
    return merged


def validate_source(src):
    """Check the configuration of one source and raise ``ConfigError`` with the key that is wrong.

    Args:
        src: merged source dictionary (``load_config``).

    Returns:
        None.
    """
    name = src.get("name", "?")

    def fail(message):
        """Raise a ConfigError that names the source (message: what is wrong)."""
        raise ConfigError(f"source {name}: {message}")

    # Required blocks
    for key in ("tracks", "grids", "streams"):
        if not src.get(key):
            fail(f"missing '{key}'")
    # Options
    if not src["diameters_km"] or any(float(d) <= 0 for d in src["diameters_km"]):
        fail("diameters_km must be a non-empty list of positive numbers")
    if src["weighting"] not in ("area", "none"):
        fail("weighting must be 'area' or 'none'")
    if src["empty_circle"] not in ("nearest_cell", "nan"):
        fail("empty_circle must be 'nearest_cell' or 'nan'")
    if src["step_hours"] is not None and float(src["step_hours"]) <= 0:
        fail("step_hours must be null or positive")
    # Grids and streams
    streams, grids = src["streams"], src["grids"]
    for gname, grid in grids.items():
        if grid.get("stream") not in streams:
            fail(f"grid '{gname}' names the stream '{grid.get('stream')}' which does not exist")
    seen = {}
    for sname, stream in streams.items():
        for key in ("root", "pattern", "reader", "grid"):
            if not stream.get(key):
                fail(f"stream '{sname}' is missing '{key}'")
        # A stream may have no variables of its own (the ERA5 surface-pressure stream only serves the below-ground mask)
        if not isinstance(stream.get("variables"), dict):
            fail(f"stream '{sname}' needs a 'variables' dictionary (it may be empty)")
        if stream["reader"] not in READERS:
            fail(f"stream '{sname}': unknown reader '{stream['reader']}' (available: {sorted(READERS)})")
        if stream["grid"] not in grids:
            fail(f"stream '{sname}' uses the grid '{stream['grid']}' which does not exist")
        for std, spec in stream["variables"].items():
            if std in seen:
                fail(f"standard variable '{std}' is defined in the streams '{seen[std]}' and '{sname}'")
            seen[std] = sname
            if spec.get("derive") not in _DERIVE_RULES:
                fail(f"variable '{std}': unknown derive rule '{spec.get('derive')}'")
            try:
                raw_names(spec)
            except ValueError as exc:
                fail(f"variable '{std}': {exc}")
            if spec.get("derive") in ("q_from_rh", "rh_from_q") and "level_hpa" not in spec:
                fail(f"variable '{std}': derive rule '{spec['derive']}' needs level_hpa")
            if stream["reader"] == "latlon_level" and "level_hpa" not in spec:
                fail(f"variable '{std}': pressure-level files need level_hpa")
    if not seen:
        fail("no variable is defined in any stream")
    # Surface pressure used for the below-ground mask
    ps = src.get("ps")
    if ps is not None and (ps.get("stream") not in streams or not ps.get("var")):
        fail("ps must be null or {stream: <existing stream>, var: <raw name>}")


def variable_order(src):
    """Standard variable names in the order of the configuration (streams in file order, variables inside each stream in file order).

    Args:
        src: merged source dictionary.

    Returns:
        list of (standard name, stream name, spec).
    """
    return [(std, sname, spec) for sname, stream in src["streams"].items() for std, spec in stream["variables"].items()]
