#!/usr/bin/env python
"""Step 3: the 12-month climatology of one dataset from its 1 degree monthly files.

Writes ``<data_root>/<dataset>/climo/env_<dataset>_1deg_monthly_climo_<YYYYMM>_<YYYYMM>.nc``: every variable with ``time`` = 12 calendar months
(year 2000), the unweighted mean over the years of the monthly means, plus ``month`` and ``nmonths`` (files used per calendar month). The
months of the period must exist (run regrid_monthly.py first); more than 5 % missing files is an error.

Example:
    python calc_env_climo.py --config config/3km_CTL.yaml
    python calc_env_climo.py --config config/ERA5.yaml --start 2007-01 --end 2017-12
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from envmonthly.climo import build_climatology  # noqa: E402
from envmonthly.config import load_dataset  # noqa: E402
from envmonthly.timeaxis import parse_month  # noqa: E402


def main():
    """Parse the command line, build the climatology and print where it is and how many months went into each calendar month."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True, help="dataset YAML file (config/<dataset>.yaml)")
    ap.add_argument("--start", default=None, help="first month YYYY-MM (default: the period of the config)")
    ap.add_argument("--end", default=None, help="last month YYYY-MM (default: the period of the config)")
    args = ap.parse_args()
    ds = load_dataset(args.config)
    start, end = (parse_month(args.start) if args.start else ds.start), (parse_month(args.end) if args.end else ds.end)
    result = build_climatology(ds, start, end)
    print(f"{ds.name}: {result['path']}")
    print("   files per calendar month:", result["nmonths"])
    if result["known_missing"]:
        print(f"   months without a file that the config lists as known gaps: {result['known_missing']}")
    if result["missing"]:
        print(f"   WARNING: {len(result['missing'])} months without a 1 degree file that are not known gaps: {result['missing']}")


if __name__ == "__main__":
    main()
