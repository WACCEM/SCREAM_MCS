#!/usr/bin/env python
"""
Generate NERSC TaskFarmer input files to compute monthly valid-data counts
from IMERG Combined 10km hourly data.

Outputs written to the same directory as this script:
  tasklist_mergir_missing_data.txt
  slurm.submit_mergir_missing_data.sh

Usage examples:
  # Default range (1998-01 to 2024-12)
  python gen_mergir_missing_data_taskfarmer.py

  # Custom range
  python gen_mergir_missing_data_taskfarmer.py --start-date 2000-01 --end-date 2002-12

  # Adjust slurm settings
  python gen_mergir_missing_data_taskfarmer.py --nodes 2 --threads 12 --qos debug --time 00:30:00
"""

import argparse
import glob
import math
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR  = SCRIPT_DIR

DATADIR_TMPL   = "/pscratch/sd/w/wcmca1/GPM/IR_IMERG_Combined_V07B/{year}/"
WRAPPER        = "/global/homes/f/feng045/program/scream/scripts/run_mergir_missing_data.sh"
TASKLIST_FNAME = "tasklist_mergir_missing_data.txt"
SLURM_FNAME    = "slurm.submit_mergir_missing_data.sh"
SLURM_LOG_DIR  = os.path.join(OUTPUT_DIR, "logs")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate NERSC TaskFarmer tasklist + Slurm script for IMERG valid-data counts.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--start-date", default="1998-01", metavar="YYYY-MM",
                        help="First year-month to process.")
    parser.add_argument("--end-date",   default="2024-12", metavar="YYYY-MM",
                        help="Last year-month to process (inclusive).")
    parser.add_argument("--min-files", type=int, default=600,
                        help="Minimum hourly files per month to include a month.")
    parser.add_argument("--threads", type=int, default=24,
                        help="TaskFarmer THREADS (concurrent tasks per node).")
    parser.add_argument("--nodes",   type=int, default=4,
                        help="Number of Slurm nodes (-N).")
    parser.add_argument("--qos",   default="debug",
                        help="Slurm QOS (e.g. regular, debug, premium).")
    parser.add_argument("--time",  default="00:30:00", metavar="HH:MM:SS",
                        help="Slurm walltime.")
    return parser.parse_args()


def parse_yearmonth(s):
    parts = s.split("-")
    if len(parts) != 2:
        sys.exit(f"ERROR: Expected YYYY-MM date, got: {s!r}")
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        sys.exit(f"ERROR: Expected YYYY-MM date, got: {s!r}")


def yearmonth_range(start_ym, end_ym):
    y, m = start_ym
    ey, em = end_ym
    while (y, m) <= (ey, em):
        yield y, m
        m += 1
        if m > 12:
            m = 1
            y += 1


def find_data_files(year, month_str):
    datadir = DATADIR_TMPL.format(year=year)
    pattern = os.path.join(datadir, f"merg_{year}{month_str}????_10km-pixel.nc")
    return sorted(glob.glob(pattern))


def write_slurm(path, tasklist_path, nodes, threads, qos, walltime):
    content = f"""\
#!/bin/bash
#SBATCH --job-name=MerGIRMissing
#SBATCH -A m1867
#SBATCH --time={walltime}
#SBATCH -q {qos}
#SBATCH -C cpu
#SBATCH -N {nodes} -c 128
#SBATCH --exclusive
#SBATCH --output=logs/log_mergir_missing_data.log
#SBATCH --mail-type=END
#SBATCH --mail-user=zhe.feng@pnnl.gov

# ─────────────────────────────────────────────────────────────────────────────
# IMPORTANT: load the TaskFarmer module BEFORE submitting this job:
#   module load taskfarmer
# Then submit with:
#   sbatch {os.path.basename(path)}
# ─────────────────────────────────────────────────────────────────────────────

date

export THREADS={threads}

runcommands.sh {tasklist_path}

date
"""
    with open(path, "w") as fh:
        fh.write(content)
    os.chmod(path, 0o755)
    print(f"  Written : {path}")


def main():
    args = parse_args()

    start_ym = parse_yearmonth(args.start_date)
    end_ym   = parse_yearmonth(args.end_date)
    if start_ym > end_ym:
        sys.exit(
            f"ERROR: --start-date ({args.start_date}) must be <= --end-date ({args.end_date})"
        )

    if not os.path.exists(WRAPPER):
        sys.exit(f"ERROR: Wrapper script not found: {WRAPPER}")

    os.makedirs(SLURM_LOG_DIR, exist_ok=True)

    print(
        f"Scanning {args.start_date} – {args.end_date} for months with "
        f">= {args.min_files} hourly files ...\n"
        f"  Threads : {args.threads} tasks/node\n"
        f"  Nodes   : {args.nodes}\n"
    )

    task_lines = []
    n_skip = 0

    for year, month in yearmonth_range(start_ym, end_ym):
        month_str = f"{month:02d}"
        tag = f"{year}-{month_str}"

        files   = find_data_files(year, month_str)
        n_files = len(files)

        if n_files < args.min_files:
            print(f"  [SKIP] {tag}: {n_files} file(s) found (< {args.min_files} required).")
            n_skip += 1
            continue

        print(f"  [ADD]  {tag}: {n_files} file(s) → task added.")
        task_lines.append(f"{WRAPPER} {year} {month_str}")

    # Write tasklist
    n_tasks = len(task_lines)
    tasklist_path = os.path.join(OUTPUT_DIR, TASKLIST_FNAME)
    with open(tasklist_path, "w") as fh:
        fh.write("\n".join(task_lines))
        if task_lines:
            fh.write("\n")
    print(f"\n  Written : {tasklist_path}  ({n_tasks} task(s), {n_skip} skipped)")

    if n_tasks == 0:
        print(
            "  [WARN] Tasklist is empty — no months met the file threshold.\n"
            "         Check that the data directory is accessible."
        )

    # Node suggestion
    if n_tasks > 0:
        suggested = max(1, math.ceil(n_tasks / args.threads))
        if suggested != args.nodes:
            print(
                f"  [NOTE] {n_tasks} tasks ÷ {args.threads} threads/node "
                f"→ suggested --nodes {suggested} "
                f"(writing --nodes {args.nodes} as specified)."
            )

    # Write Slurm script
    slurm_path = os.path.join(OUTPUT_DIR, SLURM_FNAME)
    write_slurm(
        slurm_path,
        tasklist_path=tasklist_path,
        nodes=args.nodes,
        threads=args.threads,
        qos=args.qos,
        walltime=args.time,
    )

    print(
        f"\nDone.  {n_tasks} task(s) generated, {n_skip} month(s) skipped.\n"
        "\nTo submit:\n"
        "  module load taskfarmer\n"
        f"  sbatch {slurm_path}"
    )


if __name__ == "__main__":
    main()
