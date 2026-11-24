#!/usr/bin/env python
"""Step 2: regrid the native monthly files of one dataset to the global 1 degree grid.

Applies the bilinear weight file of the dataset's source grid (made by ``make_weights.py``) to every native monthly file and writes
``<data_root>/<dataset>/latlon_1deg/env_<dataset>_1deg_<YYYYMM>.nc`` (compressed netCDF4). Source cells that are NaN (below ground) are left out
of the weighted mean as long as ``valid_weight_fraction`` of the destination cell's weight is valid (see config/grids.yaml); destination cells
without weights are missing. Existing months are skipped.

Example (on a compute node):
    python regrid_monthly.py --config config/3km_CTL.yaml --nproc 32
"""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from envmonthly.config import load_dataset  # noqa: E402
from envmonthly.ncotools import default_workers  # noqa: E402
from envmonthly.regrid import regrid_task  # noqa: E402
from envmonthly.runner import run_months, summarize, write_report  # noqa: E402
from envmonthly.timeaxis import parse_month  # noqa: E402


def main():
    """Parse the command line, regrid the months, print the summary and write the report."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True, help="dataset YAML file (config/<dataset>.yaml)")
    ap.add_argument("--start", default=None, help="first month YYYY-MM (default: the period of the config)")
    ap.add_argument("--end", default=None, help="last month YYYY-MM (default: the period of the config)")
    ap.add_argument("--nproc", type=int, default=None, help="worker processes (default: from cores and memory)")
    ap.add_argument("--overwrite", action="store_true", help="replace existing 1 degree files")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    # The months to process and the number of workers (a worker holds the weights, about 100 MB, and one field)
    ds = load_dataset(args.config)
    months = ds.months(parse_month(args.start) if args.start else None, parse_month(args.end) if args.end else None)
    workers = args.nproc or default_workers(2.0)
    print(f"{ds.name}: {len(months)} months {months[0]} .. {months[-1]}, {workers} workers, output {ds.root() / 'latlon_1deg'}")

    # Run, report and exit code
    t0 = time.time()
    results = run_months(regrid_task, ds.path, months, workers, args.overwrite)
    text, code = summarize(results, time.time() - t0)
    print(text)
    print("report:", write_report(ds.root(), "regrid", results))
    sys.exit(code)


if __name__ == "__main__":
    main()
