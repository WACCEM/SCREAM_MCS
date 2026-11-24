#!/usr/bin/env python
"""Step 1: monthly-mean fields of one dataset on its native grid (prw, hus850, hur500, wap500, ps).

For every month of the period of the dataset config: find the input files, read / select the level / interpolate the variables as the config
says, convert the units and write ``<data_root>/<dataset>/native/env_<dataset>_native_<YYYYMM>.nc`` (compressed netCDF4). Existing months are
skipped. Months with missing inputs are reported as failed in ``<data_root>/<dataset>/_reports`` and the run goes on; the exit code is 1 when
more than 5 % of the months failed.

Example (on a compute node):
    python make_monthly_native.py --config config/3km_CTL.yaml --nproc 32
    python make_monthly_native.py --config config/ERA5.yaml --start 2007-01 --end 2007-03
"""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from envmonthly.config import load_dataset  # noqa: E402
from envmonthly.native import native_task  # noqa: E402
from envmonthly.ncotools import default_workers  # noqa: E402
from envmonthly.runner import run_months, summarize, write_report  # noqa: E402
from envmonthly.timeaxis import parse_month  # noqa: E402


def main():
    """Parse the command line, run the months, print the summary and write the report."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True, help="dataset YAML file (config/<dataset>.yaml)")
    ap.add_argument("--start", default=None, help="first month YYYY-MM (default: the period of the config)")
    ap.add_argument("--end", default=None, help="last month YYYY-MM (default: the period of the config)")
    ap.add_argument("--nproc", type=int, default=None, help="worker processes (default: from cores and memory)")
    ap.add_argument("--overwrite", action="store_true", help="replace existing monthly files")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    # The months to process and the number of workers (an ERA5 month needs about 4 GB, a model month up to 6 GB)
    ds = load_dataset(args.config)
    months = ds.months(parse_month(args.start) if args.start else None, parse_month(args.end) if args.end else None)
    workers = args.nproc or default_workers(6.0)
    print(f"{ds.name}: {len(months)} months {months[0]} .. {months[-1]}, {workers} workers, output {ds.root() / 'native'}")

    # Run, report and exit code
    t0 = time.time()
    results = run_months(native_task, ds.path, months, workers, args.overwrite)
    text, code = summarize(results, time.time() - t0)
    print(text)
    print("report:", write_report(ds.root(), "native", results))
    sys.exit(code)


if __name__ == "__main__":
    main()
