#!/usr/bin/env python3
r"""Average SCREAM snapshots in time, retaining the original spatial grid.

Times use the input model calendar: start inclusive, end exclusive.
Frequencies: hourly, daily, monthly, or CFTime offsets such as 6h, 2D, MS.
Basenames are literal filename prefixes. Each input must contain one snapshot
and end in YYYY-MM-DD-HHMMSS.nc. Missing records are reported, and means use
each cell's valid samples. Only related grid/coordinate metadata is copied;
unused vertical and spectral dimensions are omitted.

Examples (from /global/homes/f/feng045/program/scream)::

    # Allocate a CPU node before a large run.
    salloc -A m1657 -C cpu -q interactive -N 1 -t 04:00:00
    srun -n 1 -c 256 --cpu-bind=cores \
      /global/common/software/m1867/python/pyflex26.3/bin/python \
      scripts/calc_scream_time_average.py \
      --start-datetime 2020-06-01T00:00:00 \
      --end-datetime 2020-09-01T00:00:00 --frequency monthly \
      --variables T_2m precip_total_surf_mass_flux --workers 128

    # All time-dependent numeric variables, custom prefixes and directories.
    python scripts/calc_scream_time_average.py \
      --input_dir /path/to/snapshots --output_dir /path/to/daily \
      --input_basename scream.2D.5min.INSTANT.nmins_x5. \
      --output_basename scream_daily --frequency daily \
      --start-datetime 2020-06-01 --end-datetime 2020-06-03

    # Smaller graphs and explicit per-worker RAM.
    python scripts/calc_scream_time_average.py \
      --start-datetime 2020-06-01 --end-datetime 2020-06-02 \
      --frequency hourly --variables T_2m --workers 8 \
      --batch-size 144 --memory-limit 4GiB

Outputs: <output_basename>_<frequency>_<YYYYMMDDTHHMMSS>.nc, one per nonempty
bin. time labels the calendar bin start; time_bnds gives the requested portion
of the bin. ntimes, expected_ntimes, coverage_fraction, and <var>_valid_count
describe coverage. Existing outputs are refused. Precipitation is converted
to mm/h according to its units; temperature remains in K.

Defaults: all numeric time-dependent variables; 288 files/batch; five-minute
cadence unless SCREAM metadata specifies otherwise; physical available cores
inside Slurm, one worker outside; 80% of allocated RAM divided among workers;
Dask temporary files under $SCRATCH (or the system temporary directory).
Dependencies: xarray, dask[distributed], netCDF4, numpy, cftime, psutil.
"""

import argparse
import bisect
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from functools import partial
import logging
import math
import os
from pathlib import Path
import re
import tempfile
import threading
import time
import uuid

# Prevent numerical libraries from adding threads to single-threaded workers.
for _thread_variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                         "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_thread_variable] = "1"

import dask
from dask.distributed import Client, LocalCluster
from distributed.system import MEMORY_LIMIT
import numpy as np
import psutil
import xarray as xr
from xarray.coding.cftime_offsets import get_date_type, to_offset

LOGGER = logging.getLogger("scream_time_average")
INPUT_DIR = "/pscratch/sd/w/wcmca1/SCREAMv1-cess2/remap_conus_2D_5min"
OUTPUT_DIR = "/pscratch/sd/w/wcmca1/SCREAMv1-cess2/remap_conus_monthly"
INPUT_BASENAME = "scream.2D.5min.INSTANT.nmins_x5."
TIMESTAMP = re.compile(r"(\d{4})-(\d{2})-(\d{2})-(\d{2})(\d{2})(\d{2})\.nc$")
FREQUENCIES = {"hourly": "h", "daily": "D", "monthly": "MS"}
CF_CODER = xr.coders.CFDatetimeCoder(use_cftime=True)


def parse_args(argv=None):
    """Return CLI arguments; argv=None reads the process command line."""
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input_dir", "--input-dir", default=INPUT_DIR,
                        help="Input directory (default: %(default)s)")
    parser.add_argument("--output_dir", "--output-dir", default=OUTPUT_DIR,
                        help="Output directory (default: %(default)s)")
    parser.add_argument("--input_basename", default=INPUT_BASENAME,
                        help="Literal input filename prefix (default: %(default)s)")
    parser.add_argument("--output_basename", default="scream_time_mean",
                        help="Literal output filename prefix (default: %(default)s)")
    parser.add_argument("--start-datetime", required=True, help="Inclusive ISO model time")
    parser.add_argument("--end-datetime", required=True, help="Exclusive ISO model time")
    parser.add_argument("--frequency", default="monthly",
                        help="hourly, daily, monthly, or a CFTime offset (default: %(default)s)")
    parser.add_argument("--variables", nargs="+", default=None,
                        help="Default: all numeric time-dependent fields")
    parser.add_argument("--workers", type=int, default=None,
                        help="Default: allocated physical cores, or 1 outside Slurm")
    parser.add_argument("--batch-size", type=int, default=288,
                        help="Maximum files per batch (default: %(default)s)")
    parser.add_argument("--memory-limit", default=None,
                        help="Per-worker RAM, e.g. 4GiB; default: 80%% of allocated RAM / workers")
    parser.add_argument("--scratch-dir", default=os.environ.get("SCRATCH", tempfile.gettempdir()),
                        help="Dask scratch parent (default: $SCRATCH or system temporary directory)")
    return parser.parse_args(argv)


def model_datetime(value, calendar):
    """Return an ISO timestamp as a cftime datetime using calendar.

    Naive strings represent model time; aware strings are converted to UTC.
    Invalid dates in the model calendar raise ValueError.
    """
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    date_type = get_date_type(calendar)
    return date_type(parsed.year, parsed.month, parsed.day, parsed.hour,
                     parsed.minute, parsed.second, parsed.microsecond)


def filename_time(path, calendar):
    """Return the model-calendar timestamp at the end of path's filename."""
    match = TIMESTAMP.search(Path(path).name)
    if match is None:
        raise ValueError(f"Input filename must end in YYYY-MM-DD-HHMMSS.nc: {path}")
    return get_date_type(calendar)(*(int(part) for part in match.groups()))


def precipitation_factor(units):
    """Return the multiplier from declared units to mm/h; reject unknown units.

    Water-equivalent mass rates use 1 kg m-2 = 1 mm. Missing units have no
    default. This conversion applies to precip_*_surf_mass_flux fields.
    """
    unit = str(units).lower().strip().replace("**", "^")
    unit = re.sub(r"[\s(){}^]", "", unit)
    rates = {
        "m/s": 3_600_000.0, "ms-1": 3_600_000.0,
        "mm/s": 3600.0, "mms-1": 3600.0,
        "mm/h": 1.0, "mmh-1": 1.0, "mm/hr": 1.0, "mmhr-1": 1.0,
        "mm/hour": 1.0, "mmhour-1": 1.0,
        "kg/m2/s": 3600.0, "kg/m2s": 3600.0, "kgm-2s-1": 3600.0,
        "kgm-2/s": 3600.0, "kg/m2s-1": 3600.0,
    }
    if unit not in rates:
        raise ValueError(f"Unsupported precipitation units: {units!r}")
    return rates[unit]


def is_precipitation(name):
    """Return whether name identifies a SCREAM surface precipitation flux."""
    return name.startswith("precip_") and name.endswith("_surf_mass_flux")


def discover_inputs(input_dir, input_basename):
    """Return sorted .nc paths with the literal filename prefix in input_dir."""
    if not input_basename or Path(input_basename).name != input_basename or "/" in input_basename:
        raise ValueError("input_basename must be a nonempty filename prefix without directories")
    files = sorted(p for p in Path(input_dir).iterdir()
                   if p.name.startswith(input_basename) and p.name.endswith(".nc") and p.is_file())
    if not files:
        raise ValueError(f"No input files with prefix {input_basename!r} in {input_dir}")
    return files


def retain_related_variables(ds, variables):
    """Return ds restricted to variables and their coordinate/metadata dependencies.

    variables is an iterable of requested field names. Keep dimension
    coordinates, CF references (from attrs or encoding), SCREAM horizontal
    geometry, and 1D static coefficients on used axes. Drop other fields and
    the dimensions that become unused. No array values are loaded.
    """
    requested = set(variables)
    missing = requested.difference(ds.variables)
    if missing:
        raise ValueError(f"Variables not present: {', '.join(sorted(missing))}")
    used_dims = {dim for name in requested for dim in ds[name].dims}
    keep = set(requested)

    # SCREAM geometry is sometimes stored without explicit CF coordinates links.
    for name in ("latitude", "longitude", "lat", "lon", "area"):
        if name in ds and ds[name].dims and set(ds[name].dims).issubset(used_dims):
            keep.add(name)
    for name, value in ds.variables.items():
        if len(value.dims) == 1 and "time" not in value.dims and value.dims[0] in used_dims:
            keep.add(name)

    # Follow metadata transitively, so bounds/helper axes survive only if needed.
    references = ("coordinates", "bounds", "climatology", "grid_mapping",
                  "cell_measures", "formula_terms", "ancillary_variables",
                  "geometry", "node_coordinates", "node_count", "part_node_count")
    pending = list(keep)
    while pending:
        name = pending.pop()
        value = ds[name]
        dependencies = {dim for dim in value.dims if dim in ds.variables}
        for key in references:
            text = value.attrs.get(key, value.encoding.get(key, ""))
            if isinstance(text, str):
                if key in ("cell_measures", "formula_terms"):
                    dependencies.update(re.findall(r"(?:^|\s)\S+:\s*(\S+)", text))
                else:
                    dependencies.update(text.replace(":", " ").split())
        for dependency in dependencies:
            if dependency in ds.variables and dependency not in keep:
                keep.add(dependency)
                pending.append(dependency)
    return ds.drop_vars([name for name in ds.variables if name not in keep])


def sample_interval(attrs):
    """Return SCREAM's metadata cadence as timedelta; default is five minutes."""
    units = {"nsecs": 1, "nmins": 60, "nhours": 3600, "ndays": 86400,
             "seconds": 1, "minutes": 60, "hours": 3600, "days": 86400}
    scale = units.get(str(attrs.get("averaging_frequency_units", "")))
    seconds = float(attrs.get("averaging_frequency", 5)) * scale if scale else 300
    if seconds <= 0:
        raise ValueError("Input sample cadence must be positive")
    return timedelta(seconds=seconds)


def period_bins(start, end, frequency):
    """Yield (label, clipped_start, clipped_end) for calendar bins in [start,end).

    frequency accepts hourly/daily/monthly aliases or CFTime offsets.
    Bins are left-closed; their bounds are clipped to the requested range.
    """
    offset = FREQUENCIES.get(frequency, frequency)
    delta = to_offset(offset)
    if start + delta <= start:
        raise ValueError("Frequency must be positive")
    markers = xr.DataArray([0, 0], dims="time",
                           coords={"time": xr.CFTimeIndex([start, end - timedelta(microseconds=1)])})
    labels = markers.resample(time=offset, closed="left", label="left",
                              origin="start_day").count().time.values
    for label in labels:
        yield label, max(start, label), min(end, label + delta)


def preprocess_snapshot(ds, variables, sizes, units, calendar):
    """Validate one snapshot and return selected variables, still lazy.

    sizes and units describe the first snapshot; calendar is its time calendar.
    Require one timestamp matching the filename and an unchanged field schema.
    """
    source = ds.encoding.get("source", "unknown")
    if ds.sizes.get("time") != 1:
        raise ValueError(f"Expected one time record per input: {source}")
    expected = filename_time(source, calendar)
    actual = ds.time.values[0]
    if abs((actual - expected).total_seconds()) > 0.001:
        raise ValueError(f"Filename/time-coordinate mismatch in {source}: {actual}")
    for name in variables:
        if name not in ds or ds[name].dims != sizes[name][0]:
            raise ValueError(f"Missing variable or changed dimensions for {name}: {source}")
        if tuple(ds[name].shape[1:]) != sizes[name][1]:
            raise ValueError(f"Changed grid shape for {name}: {source}")
        if ds[name].attrs.get("units") != units[name]:
            raise ValueError(f"Changed units for {name}: {source}")
    return ds[variables]


def reduce_batch(files, variables, sizes, units, calendar, drop_variables, parallel=False):
    """Return computed float64 sums and int64 valid counts for a bounded batch.

    files are one-snapshot paths; remaining schema arguments describe them.
    parallel=False uses synchronous Dask for small tests; True uses the active
    distributed client. Science fields are lazy until these reductions compute.
    """
    preprocess = partial(preprocess_snapshot, variables=variables, sizes=sizes,
                         units=units, calendar=calendar)
    # A complete 2D field is about 8 MB. Whole-field chunks avoid subdividing
    # compressed source chunks and keep each read large enough to be efficient.
    with xr.open_mfdataset([str(p) for p in files], engine="netcdf4",
                           combine="nested", concat_dim="time", chunks={"time": 1, "y": -1, "x": -1},
                           preprocess=preprocess, drop_variables=drop_variables,
                           data_vars="minimal", coords="minimal", compat="override", join="exact",
                           parallel=parallel, decode_times=CF_CODER) as ds:
        sums = ds.sum("time", skipna=True, dtype=np.float64, keep_attrs=True)
        counts = ds.count("time", keep_attrs=False)
        context = nullcontext() if parallel else dask.config.set(scheduler="synchronous")
        with context:
            return dask.compute(sums, counts)


def configure_worker():
    """Bound the current process's Xarray cache to eight handles; return None."""
    xr.set_options(file_cache_maxsize=8)


def worker_resources(requested_workers=None, requested_memory=None):
    """Return (workers, per_worker_RAM) respecting Slurm CPU and memory limits.

    None workers chooses allocated physical cores inside Slurm, one otherwise.
    None memory divides 80% of detected Slurm/cgroup/host RAM among workers.
    RAM overrides accept Dask byte strings such as '4GiB'.
    """
    logical = psutil.cpu_count(logical=True) or 1
    physical = psutil.cpu_count(logical=False) or logical
    available = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else logical
    cores = max(1, available * physical // logical)
    workers = requested_workers if requested_workers is not None else (
        cores if os.environ.get("SLURM_JOB_ID") else 1)
    if workers < 1:
        raise ValueError("workers must be positive")
    budget = min(psutil.virtual_memory().total, MEMORY_LIMIT)
    slurm_mib = int(os.environ.get("SLURM_MEM_PER_NODE", "0"))
    if slurm_mib > 0:
        budget = min(budget, slurm_mib * 1024 ** 2)
    return workers, requested_memory or int(budget * 0.8 / workers)


class ResourceMonitor:
    """Log process-tree RSS every interval seconds (default 30), tracking peak.

    RSS includes driver, workers, and nannies; shared pages count in each
    process. phase describes current work. peak_gib records the sampled peak.
    """

    def __init__(self, interval=30):
        """Initialize with interval seconds; leave the sampler thread stopped."""
        self.interval = interval
        self.phase = "initializing"
        self.peak_gib = 0.0
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _sample(self):
        """Return summed process-tree RSS in GiB and update its sampled peak."""
        process = psutil.Process()
        total = 0
        for child in [process] + process.children(recursive=True):
            try:
                total += child.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        gib = total / 1024 ** 3
        self.peak_gib = max(self.peak_gib, gib)
        return gib

    def _run(self):
        """Sample and log until stop is set; return None."""
        while not self.stop.wait(self.interval):
            rss = self._sample()
            LOGGER.info("Heartbeat: %s; process-tree RSS %.2f GiB; sampled peak %.2f GiB",
                        self.phase, rss, self.peak_gib)

    def __enter__(self):
        """Start background sampling and return this monitor."""
        self._sample()
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Stop sampling and log peak RSS; leave exceptions unsuppressed."""
        self.stop.set()
        self.thread.join()
        self._sample()
        LOGGER.info("Peak sampled process-tree RSS: %.2f GiB", self.peak_gib)


def write_output(output, target, calendar, time_units):
    """Write output atomically to new target, preserving calendar and time_units.

    A hard link publishes the finished file without overwriting any target.
    Remove only this invocation's private temporary file on exit.
    """
    temporary = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
    encoding = {}
    for name in output.variables:
        value = output[name]
        fill = value.encoding.get("_FillValue")
        value.encoding = {}
        if name in ("time", "time_bnds"):
            encoding[name] = {"units": time_units, "calendar": calendar, "dtype": "float64",
                              "_FillValue": None}
        else:
            encoding[name] = {"zlib": True, "complevel": 1, "shuffle": True,
                              "dtype": value.dtype, "_FillValue": fill}
            if np.issubdtype(value.dtype, np.floating) and fill is None:
                encoding[name]["_FillValue"] = np.nan
    try:
        output.to_netcdf(temporary, engine="netcdf4", format="NETCDF4", encoding=encoding)
        os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def run_averaging(args, parallel=False, monitor=None):
    """Run averaging and return created output Paths.

    args comes from parse_args. parallel=False computes synchronously for
    small tests; True uses the active Dask client. monitor=None disables phase
    updates; a ResourceMonitor receives the current batch/write description.
    """
    if args.batch_size < 1:
        raise ValueError("batch-size must be positive")
    if not args.output_basename or Path(args.output_basename).name != args.output_basename:
        raise ValueError("output_basename must be a nonempty filename prefix without directories")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.frequency):
        raise ValueError("frequency must be an alias or CFTime offset without path separators")

    # Discover timestamps before opening science arrays.
    files = discover_inputs(args.input_dir, args.input_basename)
    with xr.open_dataset(files[0], engine="netcdf4", decode_times=CF_CODER) as header:
        calendar = header.time.encoding.get("calendar", "standard")
        time_units = header.time.encoding.get("units", "days since 1970-01-01 00:00:00")
    start = model_datetime(args.start_datetime, calendar)
    end = model_datetime(args.end_datetime, calendar)
    if start >= end:
        raise ValueError("end-datetime must be later than start-datetime")
    dated = sorted((filename_time(p, calendar), p) for p in files)
    if any(a[0] == b[0] for a, b in zip(dated, dated[1:])):
        raise ValueError("Duplicate input timestamps")
    anchor = dated[0][0]
    selected = [(t, p) for t, p in dated if start <= t < end]
    if not selected:
        raise ValueError("No input records within the requested time range")
    times, files = map(list, zip(*selected))

    # Copy only static metadata needed by selected fields, keeping science arrays lazy.
    with xr.open_dataset(files[0], engine="netcdf4", decode_times=CF_CODER) as source:
        dynamic = [name for name in source.data_vars if "time" in source[name].dims]
        numeric = [name for name in dynamic if np.issubdtype(source[name].dtype, np.number)]
        variables = list(dict.fromkeys(args.variables)) if args.variables is not None else numeric
        if not variables or any(name not in numeric for name in variables):
            raise ValueError(f"Select numeric time-dependent variables from: {', '.join(numeric)}")
        if any(source[name].dims[0] != "time" for name in variables):
            raise ValueError("Selected fields must have time as their first dimension")
        sizes = {name: (source[name].dims, source[name].shape[1:]) for name in variables}
        units = {name: source[name].attrs.get("units") for name in variables}
        attrs = {name: dict(source[name].attrs) for name in variables}
        factors = {name: precipitation_factor(units[name]) if is_precipitation(name) else 1.0
                   for name in variables}
        cadence = sample_interval(source.attrs)
        related = retain_related_variables(source, variables)
        template = related.drop_vars([name for name in dynamic + ["time"] if name in related]).load()
        drop_variables = [name for name in source.variables if name not in variables + ["time"]]

    # Preflight all targets so an existing file fails before period processing.
    output_dir = Path(args.output_dir)
    plans = [(label, lower, upper, output_dir /
              f"{args.output_basename}_{args.frequency}_{label.strftime('%Y%m%dT%H%M%S')}.nc")
             for label, lower, upper in period_bins(start, end, args.frequency)]
    for _, _, _, target in plans:
        if target.exists():
            raise FileExistsError(f"Refusing existing output: {target}")
    output_dir.mkdir(parents=True, exist_ok=True)
    LOGGER.info("Selected %d files, variables=%s, calendar=%s, cadence=%s, spatial sizes=%s",
                len(files), variables, calendar, cadence, dict(template.sizes))
    for name in variables:
        if is_precipitation(name):
            LOGGER.info("Precipitation conversion: %s [%s] * %g -> mm/h", name, units[name], factors[name])

    outputs = []
    for label, lower, upper, target in plans:
        left, right = bisect.bisect_left(times, lower), bisect.bisect_left(times, upper)
        expected = max(0, math.ceil((upper - anchor) / cadence) - math.ceil((lower - anchor) / cadence))
        nrecords = right - left
        if nrecords == 0:
            LOGGER.warning("Skipping empty period [%s, %s); expected %d records", lower, upper, expected)
            continue
        if nrecords != expected:
            LOGGER.warning("Incomplete coverage [%s, %s): %d/%d records", lower, upper, nrecords, expected)
        period_start = time.monotonic()
        total_sums, total_counts = None, None
        batches = math.ceil(nrecords / args.batch_size)

        # Accumulate sums/counts; a mean of batch means would bias gap periods.
        for batch_number, begin in enumerate(range(left, right, args.batch_size), start=1):
            batch = files[begin:min(begin + args.batch_size, right)]
            phase = f"{label} batch {batch_number}/{batches} ({len(batch)} files)"
            if monitor is not None:
                monitor.phase = phase
            batch_start = time.monotonic()
            sums, counts = reduce_batch(batch, variables, sizes, units, calendar,
                                        drop_variables, parallel=parallel)
            if total_sums is None:
                total_sums, total_counts = sums, counts
            else:
                for name in variables:
                    total_sums[name].data += sums[name].data
                    total_counts[name].data += counts[name].data
            if monitor is not None:
                monitor._sample()
            LOGGER.info("Completed %s in %.1fs; period elapsed %.1fs", phase,
                        time.monotonic() - batch_start, time.monotonic() - period_start)

        # Attach means, unchanged grid fields, CF time bounds, and coverage.
        output = template.copy(deep=False).assign_coords(time=xr.CFTimeIndex([label]))
        for name in variables:
            mean = (total_sums[name] / total_counts[name].where(total_counts[name] > 0)) * factors[name]
            mean = mean.astype(np.float32).expand_dims(time=output.time)
            mean.attrs = attrs[name].copy()
            old_methods = mean.attrs.get("cell_methods", "")
            mean.attrs["cell_methods"] = re.sub(r"\btime:\s*\w+", "time: mean", old_methods) \
                if "time:" in old_methods else (old_methods + " time: mean").strip()
            if "latitude" in output and "longitude" in output:
                mean.attrs["coordinates"] = "latitude longitude"
            if is_precipitation(name):
                mean.attrs.update(units="mm/h", original_units=units[name],
                                  unit_conversion_factor=factors[name])
                mean.attrs.pop("standard_name", None)
            output[name] = mean
            output[f"{name}_valid_count"] = total_counts[name].expand_dims(time=output.time)
            output[f"{name}_valid_count"].attrs = {
                "long_name": f"Valid samples contributing to {name}", "units": "1"}
        output["ntimes"] = ("time", [nrecords], {"long_name": "Number of input snapshots", "units": "1"})
        output["expected_ntimes"] = ("time", [expected], {
            "long_name": "Expected snapshots within requested time bounds", "units": "1"})
        output["coverage_fraction"] = ("time", [nrecords / expected if expected else np.nan], {
            "long_name": "Available / expected snapshots", "units": "1"})
        output["time_bnds"] = (("time", "bnds"), np.array([[lower, upper]], dtype=object))
        output.time.attrs = {"standard_name": "time", "bounds": "time_bnds"}
        for key in ("averaging_frequency", "averaging_frequency_units",
                    "max_snapshots_per_file", "file_max_storage_type"):
            output.attrs.pop(key, None)
        output.attrs.update(title="SCREAM time averages on the original spatial grid",
                            averaging_type="AVERAGE", time_averaging_frequency=args.frequency,
                            source_time_step_seconds=cadence.total_seconds(),
                            time_coverage_start=lower.isoformat(), time_coverage_end=upper.isoformat(),
                            input_directory=str(Path(args.input_dir).resolve()),
                            input_basename=args.input_basename,
                            missing_records_policy="average available valid samples")
        output.attrs["history"] = (f"{datetime.now(timezone.utc).isoformat()}: time mean; "
                                   f"{nrecords} snapshots; float64 sums, per-cell valid counts\n" +
                                   output.attrs.get("history", ""))
        if monitor is not None:
            monitor.phase = f"writing {target.name}"
        write_output(output, target, calendar, time_units)
        outputs.append(target)
        LOGGER.info("Saved %s (%d records, coverage %.6f), period elapsed %.1fs", target,
                    nrecords, nrecords / expected if expected else np.nan, time.monotonic() - period_start)
    return outputs


def main(argv=None):
    """Run the CLI with argv (default process arguments); return None."""
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    workers, memory = worker_resources(args.workers, args.memory_limit)
    LOGGER.info("Starting %d process workers, one thread each, per-worker memory=%s", workers, memory)
    started = time.monotonic()
    scratch = Path(args.scratch_dir)
    scratch.mkdir(parents=True, exist_ok=True)
    # Isolate Dask spills and communication files in an automatically cleaned directory.
    with ResourceMonitor() as monitor, tempfile.TemporaryDirectory(
            prefix="scream_time_average_", dir=scratch) as work:
        with dask.config.set({"distributed.worker.memory.target": 0.6,
                              "distributed.worker.memory.spill": 0.7,
                              "distributed.worker.memory.pause": 0.85}):
            with LocalCluster(n_workers=workers, threads_per_worker=1, processes=True,
                              memory_limit=memory, local_directory=work, dashboard_address=None,
                              silence_logs=logging.ERROR, death_timeout=300) as cluster:
                with Client(cluster, timeout="300s") as client:
                    client.run(configure_worker)
                    configure_worker()
                    outputs = run_averaging(args, parallel=True, monitor=monitor)
    LOGGER.info("Finished %d output files in %.1fs", len(outputs), time.monotonic() - started)


if __name__ == "__main__":
    main()

