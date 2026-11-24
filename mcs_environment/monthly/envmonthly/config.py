"""Dataset configuration of the monthly environment product.

One YAML file per dataset (``config/ERA5.yaml``, ``config/3km_CTL.yaml``, ...) plus two shared files in the same folder: ``grids.yaml`` (folders,
target grid, source grids, regridding method) and ``variables.yaml`` (the CMIP names with their units). Raw variable names, file patterns
and unit conversions appear only in the dataset file, so a new dataset with a similar layout is a copy of an existing file.

A variable of a stream is listed in one of three groups, which says how it is obtained::

    direct       a 2-D variable that exists in the files (or a 2-D variable averaged over the records of the month)
    plev_select  a 3-D variable already on pressure levels: the level is picked, nothing is interpolated
    interpolate  a 3-D variable on model levels: log-pressure interpolation to ``plev_hpa`` with the stream's ``pressure``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from .timeaxis import CALENDARS, month_range, parse_month

METHODS = ("direct", "plev_select", "interpolate")
LAYOUTS = ("ncol", "latlon")


class ConfigError(ValueError):
    """The configuration is inconsistent (the message names the dataset and the key)."""


@dataclass(frozen=True)
class VarSpec:
    """One output variable of a stream.

    ``name`` CMIP name (key of variables.yaml); ``stream`` stream name; ``method`` direct | plev_select | interpolate; ``raw`` variable name in
    the files; ``plev_hpa`` level (None for direct); ``scale`` / ``offset`` conversion (value * scale + offset); ``mask_below_ground`` name of
    the output variable holding the surface pressure used to set the variable to NaN where the surface pressure is below the level.
    """

    name: str
    stream: str
    method: str
    raw: str
    plev_hpa: Optional[float] = None
    scale: float = 1.0
    offset: float = 0.0
    mask_below_ground: Optional[str] = None


@dataclass(frozen=True)
class StreamSpec:
    """One family of input files: ``root`` + ``pattern`` (``{yyyy}`` ``{mm}``, ``*`` allowed), the file ``layout`` (ncol | latlon), the
    ``pressure`` description of model levels, optional ``options`` (dimension / coordinate names, expected_records_per_day) and its variables."""

    name: str
    root: str
    pattern: str
    layout: str
    pressure: Optional[dict]
    options: dict
    variables: tuple


@dataclass
class Common:
    """Shared settings of ``grids.yaml``: folders, regridding method, deflate level, the target grid and the source grids."""

    data_root: str
    maps_dir: str
    method: str
    weight_options: str
    deflate: int
    target: dict
    sources: dict
    valid_weight_fraction: float = 0.5
    path: str = ""


@dataclass
class Dataset:
    """A validated dataset: names, period, calendar, source grid, streams and the CMIP dictionary entries of its variables."""

    name: str
    label: str
    calendar: str
    start: tuple
    end: tuple
    grid: str
    streams: tuple
    dictionary: dict
    common: Common
    path: str = ""
    variables: tuple = field(default=())
    known_missing: frozenset = frozenset()

    def months(self, start=None, end=None):
        """List of (year, month) of the period, or of ``start`` .. ``end`` (tuples) when given (default: the configured period)."""
        return month_range(start or self.start, end or self.end)

    def root(self):
        """Output folder of the dataset: ``<data_root>/<name>``."""
        return Path(self.common.data_root) / self.name

    def native_path(self, year, month):
        """Native-grid monthly file of a month."""
        return self.root() / "native" / f"env_{self.name}_native_{year:04d}{month:02d}.nc"

    def latlon_path(self, year, month):
        """1-degree monthly file of a month."""
        return self.root() / "latlon_1deg" / f"env_{self.name}_1deg_{year:04d}{month:02d}.nc"

    def climo_path(self, start, end):
        """12-month climatology file of the period ``start`` .. ``end`` (tuples)."""
        return self.root() / "climo" / f"env_{self.name}_1deg_monthly_climo_{start[0]:04d}{start[1]:02d}_{end[0]:04d}{end[1]:02d}.nc"

    def map_path(self):
        """Weight file of the dataset's source grid to the target grid."""
        return Path(self.common.maps_dir) / f"map_{self.grid}_to_{self.common.target['name']}_{self.common.method}.nc"

    def expected_months(self, start=None, end=None):
        """The months of the period that are expected to have files: ``months()`` without the ``known_missing_months`` of the config."""
        return [m for m in self.months(start, end) if m not in self.known_missing]

    def output_names(self):
        """CMIP names of all output variables, in the order of the streams."""
        return [v.name for v in self.variables]


def load_common(path):
    """Read ``grids.yaml``.

    Args:
        path: the YAML file.

    Returns:
        ``Common``. Raises ``ConfigError`` for a missing key.
    """
    with open(path) as handle:
        raw = yaml.safe_load(handle)
    # Required keys
    for key in ("data_root", "maps_dir", "method", "target", "sources"):
        if key not in raw:
            raise ConfigError(f"{path}: '{key}' is missing")
    if "name" not in raw["target"] or "generate" not in raw["target"]:
        raise ConfigError(f"{path}: target needs 'name' and 'generate'")
    for gname, grid in raw["sources"].items():
        if ("scrip" in grid) == ("generate" in grid):
            raise ConfigError(f"{path}: source grid '{gname}' needs exactly one of 'scrip' and 'generate'")
    fraction = float(raw.get("valid_weight_fraction", 0.5))
    if not 0.0 < fraction <= 1.0:
        raise ConfigError(f"{path}: valid_weight_fraction must be in (0, 1]")
    return Common(str(raw["data_root"]), str(raw["maps_dir"]), str(raw["method"]), str(raw.get("weight_options", "")),
                  int(raw.get("deflate", 4)), dict(raw["target"]), dict(raw["sources"]), fraction, str(path))


def load_dictionary(path):
    """Read ``variables.yaml`` (CMIP name -> long_name, standard_name, units, optional plev_hpa and valid_range)."""
    with open(path) as handle:
        return yaml.safe_load(handle)


def load_dataset(path, common_path=None, variables_path=None):
    """Read and validate one dataset configuration.

    Args:
        path: dataset YAML file.
        common_path: ``grids.yaml`` (default: the one in the folder of ``path``).
        variables_path: ``variables.yaml`` (default: the one in the folder of ``path``).

    Returns:
        ``Dataset``. Raises ``ConfigError`` naming the dataset and the key that is wrong.
    """
    path = Path(path)
    common = load_common(common_path or path.parent / "grids.yaml")
    dictionary = load_dictionary(variables_path or path.parent / "variables.yaml")
    with open(path) as handle:
        raw = yaml.safe_load(handle)
    name = str(raw.get("name", path.stem))

    def fail(message):
        """Raise a ConfigError that names the dataset (message: what is wrong)."""
        raise ConfigError(f"dataset {name} ({path.name}): {message}")

    # Top-level keys
    for key in ("name", "period", "calendar", "grid", "streams"):
        if key not in raw:
            fail(f"'{key}' is missing")
    if raw["calendar"] not in CALENDARS:
        fail(f"calendar must be one of {CALENDARS}")
    if raw["grid"] not in common.sources:
        fail(f"grid '{raw['grid']}' is not in grids.yaml (available: {sorted(common.sources)})")
    try:
        start, end = parse_month(raw["period"]["start"]), parse_month(raw["period"]["end"])
    except (KeyError, ValueError, TypeError) as exc:
        fail(f"period needs start and end as YYYY-MM ({exc})")
    if end < start:
        fail("period end is before period start")
    # Streams and their variables
    streams, variables, seen = [], [], {}
    for sname, s in raw["streams"].items():
        for key in ("root", "pattern", "layout"):
            if key not in s:
                fail(f"stream '{sname}': '{key}' is missing")
        if s["layout"] not in LAYOUTS:
            fail(f"stream '{sname}': layout must be one of {LAYOUTS}")
        if "{yyyy}" not in s["pattern"] or "{mm}" not in s["pattern"]:
            fail(f"stream '{sname}': pattern needs {{yyyy}} and {{mm}}")
        pressure = s.get("pressure")
        if pressure is not None and not ("field" in pressure or "hybrid" in pressure):
            fail(f"stream '{sname}': pressure must have 'field' or 'hybrid'")
        specs = []
        for method in METHODS:
            for std, v in (s.get(method) or {}).items():
                if std not in dictionary:
                    fail(f"stream '{sname}': '{std}' is not a CMIP name of variables.yaml (available: {sorted(dictionary)})")
                if std in seen:
                    fail(f"output variable '{std}' is defined in the streams '{seen[std]}' and '{sname}'")
                seen[std] = sname
                if "raw" not in v:
                    fail(f"stream '{sname}' variable '{std}': 'raw' is missing")
                plev = v.get("plev_hpa")
                # Level rules of the three groups
                if method == "direct" and plev is not None:
                    fail(f"stream '{sname}' variable '{std}': a direct variable has no plev_hpa")
                if method != "direct":
                    if plev is None:
                        fail(f"stream '{sname}' variable '{std}': {method} needs plev_hpa")
                    if dictionary[std].get("plev_hpa") != plev:
                        fail(f"stream '{sname}' variable '{std}': plev_hpa {plev} differs from the {dictionary[std].get('plev_hpa')} hPa of the name")
                if method == "plev_select" and s["layout"] != "latlon":
                    fail(f"stream '{sname}' variable '{std}': plev_select needs layout latlon")
                if method == "interpolate" and pressure is None:
                    fail(f"stream '{sname}' variable '{std}': interpolate needs a 'pressure' description of the stream")
                if method == "interpolate" and s["layout"] != "ncol":
                    fail(f"stream '{sname}' variable '{std}': interpolate needs layout ncol")
                specs.append(VarSpec(std, sname, method, str(v["raw"]), float(plev) if plev is not None else None,
                                     float(v.get("scale", 1.0)), float(v.get("offset", 0.0)), v.get("mask_below_ground")))
        if not specs:
            fail(f"stream '{sname}' has no variable")
        options = {k: s[k] for k in s if k not in ("root", "pattern", "layout", "pressure") + METHODS}
        streams.append(StreamSpec(sname, str(s["root"]), str(s["pattern"]), s["layout"], pressure, options, tuple(specs)))
        variables += specs
    # A mask variable must be defined and must be a direct variable
    for v in variables:
        if v.mask_below_ground:
            if v.mask_below_ground not in seen:
                fail(f"variable '{v.name}': mask_below_ground '{v.mask_below_ground}' is not an output variable of the dataset")
            if next(x for x in variables if x.name == v.mask_below_ground).method != "direct":
                fail(f"variable '{v.name}': mask_below_ground '{v.mask_below_ground}' must be a direct variable")
    # Months that are known to have no usable input (documented data gaps)
    try:
        known = frozenset(parse_month(m) for m in raw.get("known_missing_months") or [])
    except ValueError as exc:
        fail(f"known_missing_months: {exc}")
    return Dataset(name, str(raw.get("label", name)), raw["calendar"], start, end, raw["grid"], tuple(streams),
                   {k: dictionary[k] for k in seen}, common, str(path), tuple(variables), known)
