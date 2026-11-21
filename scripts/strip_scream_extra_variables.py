#!/usr/bin/env python3
r"""Strip unrelated metadata from existing SCREAM means, backing up originals.

This script copies existing arrays without computing averages. Requested fields,
their valid counts, time coverage statistics, and related coordinate/grid metadata
are retained. All retained raw values and attributes are checked before moving
the original into a backup directory and publishing its replacement.

Example (from /global/homes/f/feng045/program/scream)::

    /global/common/software/m1867/python/pyflex26.3/bin/python \
      scripts/strip_scream_extra_variables.py \
      --variables T_2m precip_total_surf_mass_flux --dry-run

    /global/common/software/m1867/python/pyflex26.3/bin/python \
      scripts/strip_scream_extra_variables.py \
      --variables T_2m precip_total_surf_mass_flux

Defaults: the remap_conus_monthly directory and scream_time_mean_monthly_ prefix.
--backup_dir optionally names a directory on the same filesystem; otherwise a
unique backup_before_strip_<UTC timestamp> directory is created beside the files.
Existing backups are never replaced. A failed publication restores the original
if its pathname is still free. Copies use bounded slabs, preserving compression,
data types, fill values, calendar, and all retained attributes.
"""

import argparse
from datetime import datetime, timezone
import logging
import math
import os
from pathlib import Path
import uuid

import netCDF4
import numpy as np
import xarray as xr

from calc_scream_time_average import OUTPUT_DIR, retain_related_variables

LOGGER = logging.getLogger("strip_scream_extra_variables")
STATISTICS = ("ntimes", "expected_ntimes", "coverage_fraction")


def selection(path, variables):
    """Return retained variable names and removed dimensions for path.

    variables names the requested means. Include their valid counts, existing
    coverage statistics, and transitive metadata dependencies. Read headers only.
    """
    with xr.open_dataset(path, decode_cf=False, engine="netcdf4") as ds:
        roots = list(variables) + [name for name in STATISTICS if name in ds]
        roots += [f"{name}_valid_count" for name in variables if f"{name}_valid_count" in ds]
        related = retain_related_variables(ds, roots)
        return list(related.variables), sorted(set(ds.sizes).difference(related.sizes))


def blocks(variable, max_bytes=16 * 1024 ** 2):
    """Yield slab indices for variable, targeting max_bytes (default 16 MiB).

    At least one row is read even when a single row exceeds the target size.
    Scalars yield Ellipsis. No values are read by this generator.
    """
    if not variable.shape:
        yield Ellipsis
        return
    row_bytes = max(1, math.prod(variable.shape[1:]) * variable.dtype.itemsize)
    rows = max(1, max_bytes // row_bytes)
    for begin in range(0, variable.shape[0], rows):
        yield (slice(begin, min(begin + rows, variable.shape[0])),) + (
            slice(None),) * (variable.ndim - 1)


def copy_selected(source_path, temporary, keep):
    """Copy keep variables from source_path into new temporary; return None.

    Transfer raw values in bounded slabs, preserving attributes and storage
    settings. Neither decoding, unit conversion, nor time averaging is applied.
    """
    with netCDF4.Dataset(source_path) as source, netCDF4.Dataset(
            temporary, "w", format=source.data_model) as target:
        source.set_auto_maskandscale(False)
        source.set_auto_chartostring(False)
        used_dims = {dim for name in keep for dim in source[name].dimensions}
        for name, dimension in source.dimensions.items():
            if name in used_dims:
                target.createDimension(name, None if dimension.isunlimited() else len(dimension))
        target.setncatts({name: source.getncattr(name) for name in source.ncattrs()})

        # Recreate the retained schema, then copy already-encoded array values.
        for name in keep:
            original = source[name]
            attributes = {key: original.getncattr(key) for key in original.ncattrs()}
            fill_value = attributes.pop("_FillValue", False)
            filters = original.filters() or {}
            options = {key: filters[key] for key in ("zlib", "complevel", "shuffle", "fletcher32")
                       if key in filters}
            chunking = original.chunking()
            if isinstance(chunking, (list, tuple)):
                options["chunksizes"] = tuple(chunking)
            elif original.ndim and not any(dim in target.dimensions and
                                            target.dimensions[dim].isunlimited()
                                            for dim in original.dimensions):
                options["contiguous"] = True
            if original.dtype.kind in "iuf":
                options["endian"] = original.endian()
            copied = target.createVariable(name, original.datatype, original.dimensions,
                                           fill_value=fill_value, **options)
            copied.setncatts(attributes)
            copied.set_auto_maskandscale(False)
            copied.set_auto_chartostring(False)
            for slab in blocks(original):
                copied[slab] = original[slab]


def arrays_equal(first, second):
    """Return exact element equality, treating NaNs as equal for floating arrays."""
    floating = np.asarray(first).dtype.kind in "fc"
    return np.array_equal(first, second, equal_nan=floating)


def validate_copy(source_path, temporary, keep):
    """Assert retained raw arrays, attributes, dimensions, and encodings match.

    source_path is the unchanged original, temporary its staged replacement,
    and keep the expected variable names. Raise AssertionError on any mismatch.
    """
    with netCDF4.Dataset(source_path) as source, netCDF4.Dataset(temporary) as target:
        source.set_auto_maskandscale(False)
        source.set_auto_chartostring(False)
        target.set_auto_maskandscale(False)
        target.set_auto_chartostring(False)
        assert set(target.variables) == set(keep), "Unexpected variables"
        used_dims = {dim for name in keep for dim in source[name].dimensions}
        assert set(target.dimensions) == used_dims, "Unexpected dimensions"
        assert set(target.ncattrs()) == set(source.ncattrs()), "Changed global attributes"
        for attribute in source.ncattrs():
            assert arrays_equal(source.getncattr(attribute), target.getncattr(attribute)), attribute
        for name in used_dims:
            assert len(source.dimensions[name]) == len(target.dimensions[name]), name
            assert source.dimensions[name].isunlimited() == target.dimensions[name].isunlimited(), name

        # Compare every retained value; no sampling of the science fields.
        for name in keep:
            original, copied = source[name], target[name]
            assert original.dimensions == copied.dimensions, name
            assert original.dtype == copied.dtype, name
            assert original.chunking() == copied.chunking(), name
            assert original.filters() == copied.filters(), name
            assert set(original.ncattrs()) == set(copied.ncattrs()), name
            for attribute in original.ncattrs():
                assert arrays_equal(original.getncattr(attribute), copied.getncattr(attribute)), (name, attribute)
            for slab in blocks(original):
                assert arrays_equal(original[slab], copied[slab]), f"Changed data: {name}"


def strip_file(path, variables, backup_dir):
    """Strip one path, move its original to backup_dir, and return the backup Path.

    variables names the requested means. backup_dir must share the filesystem.
    Return None if nothing needs removing. Never replace an existing backup.
    """
    path, backup_dir = Path(path), Path(backup_dir)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Expected a regular, nonsymlink input file: {path}")
    keep, removed_dims = selection(path, variables)
    with netCDF4.Dataset(path) as source:
        removed = sorted(set(source.variables).difference(keep))
    if not removed and not removed_dims:
        LOGGER.info("Already stripped: %s", path)
        return None
    backup = backup_dir / path.name
    if backup.exists():
        raise FileExistsError(f"Refusing existing backup: {backup}")
    backup_dir.mkdir(parents=True, exist_ok=True)
    if path.stat().st_dev != backup_dir.stat().st_dev:
        raise ValueError("Backup directory must be on the same filesystem as the input")
    before = path.stat()
    temporary = path.parent / f".{path.name}.strip-{uuid.uuid4().hex}.tmp"
    try:
        # Finish and validate the copy while the original remains in place.
        copy_selected(path, temporary, keep)
        validate_copy(path, temporary, keep)
        after = path.stat()
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_ino, after.st_size, after.st_mtime_ns):
            raise RuntimeError(f"Input changed while being copied: {path}")
        temporary.chmod(before.st_mode & 0o777)
        path.rename(backup)
        try:
            os.link(temporary, path)
        except BaseException:
            if not path.exists():
                backup.rename(path)
            raise
        LOGGER.info("Replaced %s; backup=%s; removed variables=%s; removed dimensions=%s",
                    path, backup, removed, removed_dims)
    finally:
        temporary.unlink(missing_ok=True)
    return backup


def main(argv=None):
    """Run stripping with argv (default process arguments); return None."""
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input_dir", default=OUTPUT_DIR)
    parser.add_argument("--input_basename", default="scream_time_mean_monthly_",
                        help="Literal filename prefix")
    parser.add_argument("--variables", nargs="+", required=True, help="Requested mean variable names")
    parser.add_argument("--backup_dir", default=None)
    parser.add_argument("--dry-run", action="store_true", help="Show removals without writing or moving files")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    root = Path(args.input_dir).resolve(strict=True)
    if not args.input_basename or Path(args.input_basename).name != args.input_basename:
        parser.error("input_basename must be a nonempty literal prefix without directories")
    files = sorted(path for path in root.iterdir() if path.name.startswith(
        args.input_basename) and path.name.endswith(".nc") and path.is_file())
    if not files:
        parser.error(f"No matching NetCDF files in {root}")
    backup_dir = Path(args.backup_dir).resolve() if args.backup_dir else root / (
        "backup_before_strip_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") +
        "_" + uuid.uuid4().hex[:8])

    # Check the complete file list before changing the first original.
    for path in files:
        keep, removed_dims = selection(path, args.variables)
        with netCDF4.Dataset(path) as source:
            removed = sorted(set(source.variables).difference(keep))
        if (backup_dir / path.name).exists():
            raise FileExistsError(f"Refusing existing backup: {backup_dir / path.name}")
        LOGGER.info("%s: remove variables=%s; remove dimensions=%s", path.name, removed, removed_dims)
    if args.dry_run:
        return
    for path in files:
        strip_file(path, args.variables, backup_dir)
    LOGGER.info("Finished; originals backed up under %s", backup_dir)


if __name__ == "__main__":
    main()

