#!/usr/bin/env python
"""Extract environmental variables averaged in circles that follow MCS tracks (SCREAM, E3SM, ERA5).

For every MCS track of a source the circle (several diameters) stays at the MCS start location for the 24 h before the start and follows the track
centroid afterwards. Rows sit on a nominal relative-time grid (offsets k * step from the start, the same for every track); the environment is the
nearest snapshot (within half a step). All variables of the source come from the same job; one Parquet file per year is written to
``<out-dir>/<source>/mcs_env_<source>_<year>.parquet`` with units and attributes (zstd).

Example (one year of the 3-km CTL on one node)::

    python extract_mcs_env.py --source 3km_CTL --years 1996 1996 --nproc 128 --out-dir $SCRATCH/mcs_env

Sources, paths, variable names and units are in ``config/sources.yaml``. See README.md for the method and the output schema.
"""

# The netCDF library must not lock files on the parallel file systems, and every worker must be single-threaded
import os

os.environ.setdefault("HDF5_USE_FILE_LOCKING", "FALSE")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import argparse  # noqa: E402
import sys  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pyarrow.parquet as pq  # noqa: E402

from mcsenv.config import load_config, validate_source  # noqa: E402
from mcsenv.extract import log, run_source  # noqa: E402


def main():
    """Parse the command line, load the source configuration and run the extraction."""
    here = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description="Environmental variables averaged in circles that follow MCS tracks.")
    parser.add_argument("--source", required=True, help="source name in the configuration (OBS, 3km_CTL, 3km_TUNE, 25km, 100km, ...)")
    parser.add_argument("--config", default=os.path.join(here, "config", "sources.yaml"), help="sources.yaml (default: config/sources.yaml)")
    parser.add_argument("--years", nargs=2, type=int, metavar=("Y0", "Y1"), default=None,
                        help="first and last period (year) to process, each year gives one file (default: all periods of the track file)")
    parser.add_argument("--diameters-km", nargs="+", type=float, default=None, help="circle diameters in km (default: the configuration, 200 400 600)")
    parser.add_argument("--step-hours", type=float, default=None, help="nominal row step in hours (default: the configuration, normally the finest stream)")
    parser.add_argument("--max-missing-fraction", type=float, default=None, help="largest share of rows without a snapshot in the primary group")
    parser.add_argument("--nproc", type=int, default=max(1, int(os.environ.get("SLURM_CPUS_ON_NODE", os.cpu_count() or 2)) // 2),
                        help="worker processes (default: half of the logical CPUs of the node = the physical cores)")
    parser.add_argument("--out-dir", default=os.path.join(os.environ.get("SCRATCH", "."), "mcs_env"), help="output folder (default: $SCRATCH/mcs_env)")
    parser.add_argument("--start-date", default=None, help="only tracks that start on or after this date (YYYY-MM-DD, UTC; for tests)")
    parser.add_argument("--end-date", default=None, help="only tracks that start on or before this date (YYYY-MM-DD, UTC; for tests)")
    args = parser.parse_args()

    # Configuration of the source, with the command-line overrides
    src = load_config(args.config, args.source)
    if args.diameters_km is not None:
        src["diameters_km"] = args.diameters_km
    if args.step_hours is not None:
        src["step_hours"] = args.step_hours
    if args.max_missing_fraction is not None:
        src["max_missing_fraction"] = args.max_missing_fraction
    validate_source(src)

    # Years: the requested range, or every period in the track file
    if args.years:
        years = list(range(args.years[0], args.years[1] + 1))
    else:
        years = sorted({int(p) for p in pq.read_table(src["tracks"], columns=["period"]).column("period").to_pylist()})
    log(f"extract_mcs_env: source {args.source}, years {years[0]}..{years[-1]}, out {args.out_dir}")
    run_source(src, years, args.out_dir, nproc=args.nproc, start_date=args.start_date, end_date=args.end_date)


if __name__ == "__main__":
    main()
