#!/usr/bin/env python
"""
Generate NERSC TaskFarmer input files to compute monthly MCS rain-map statistics
for the SCREAM decadal tracking run.

Outputs written to the same directory as this script:
  tasklist_mcs_monthly_rainmap_SCREAM_decadal.txt
  slurm.submit_mcs_monthly_rainmap_SCREAM_decadal.sh

Memory note
-----------
Measured peak memory per task: ~6 GB (profiled on NERSC Perlmutter with
SCREAM ne256 monthly pixel-tracking files; see logs/log_mcs_monthly_rainmap_SCREAM_decadal.log).
Perlmutter CPU node: 512 GB / 128 cores → up to ~80 tasks/node within budget.
Default THREADS=12 is very conservative; raise to 24–48 based on available memory.

TaskFarmer usage
----------------
  module load taskfarmer   # MUST be loaded before sbatch
  sbatch slurm.submit_mcs_monthly_rainmap_SCREAM_decadal.sh

Usage examples:
  # Default range (1995-01 to 2005-12)
  python gen_scream_mcs_monthly_stats_taskfarmer.py

  # Custom range
  python gen_scream_mcs_monthly_stats_taskfarmer.py --start-date 2000-01 --end-date 2002-12

  # Adjust nodes and threads
  python gen_scream_mcs_monthly_stats_taskfarmer.py --nodes 2 --threads 8 --qos debug --time 00:30:00

Run in the pyflex26.3 environment:
  /global/common/software/m1867/python/pyflex26.3/bin/python gen_scream_mcs_monthly_stats_taskfarmer.py
"""

import argparse
import glob
import math
import os
import sys

try:
    from pyflextrkr.ft_utilities import load_config
except ImportError:
    print("ERROR: pyflextrkr not found. Run in the pyflex26.3 environment:")
    print("  source activate /global/common/software/m1867/python/pyflex26.3")
    sys.exit(1)

# ──────────────────────────────────────────────────────────────────────────────
# Paths and constants
# ──────────────────────────────────────────────────────────────────────────────

# This script lives in the config directory — use it as the output directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = SCRIPT_DIR

# Existing TaskFarmer wrapper shell script
WRAPPER = "/global/homes/f/feng045/program/scream/scripts/run_mcs_monthly_rainmap_latlon.sh"

# Output filenames
# TASKLIST_FNAME = "tasklist_mcs_monthly_rainmap_SCREAM_decadal.txt"
# SLURM_FNAME    = "slurm.submit_mcs_monthly_rainmap_SCREAM_decadal.sh"
# TASKLIST_FNAME = "tasklist_mcs_monthly_rainmap_SCREAM_ne256_ctl.txt"
# SLURM_FNAME    = "slurm.submit_mcs_monthly_rainmap_SCREAM_ne256_ctl.sh"
TASKLIST_FNAME = "tasklist_mcs_monthly_rainmap_SCREAM_ne256_tune.txt"
SLURM_FNAME    = "slurm.submit_mcs_monthly_rainmap_SCREAM_ne256_tune.sh"

# Per-year config filename pattern
# CONFIG_BASENAME = "config_mcs_tbpf_SCREAM_decadal_{year}.yml"
# CONFIG_BASENAME = "config_mcs_tbpf_SCREAM_ne256_ctl_{year}.yml"
CONFIG_BASENAME = "config_mcs_tbpf_SCREAM_ne256_tune_{year}.yml"

# Slurm log directory (created by this script)
SLURM_LOG_DIR = os.path.join(OUTPUT_DIR, "logs")


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Generate NERSC TaskFarmer tasklist + Slurm script for monthly MCS "
            "rain-map statistics (SCREAM decadal)."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--start-date",
        default="1995-01",
        metavar="YYYY-MM",
        help="First year-month to process.",
    )
    parser.add_argument(
        "--end-date",
        default="2005-12",
        metavar="YYYY-MM",
        help="Last year-month to process (inclusive).",
    )
    parser.add_argument(
        "--min-files",
        type=int,
        default=600,
        help=(
            "Minimum number of pixel-tracking files required to include a month. "
            "Months with fewer files are skipped with a warning."
        ),
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=12,
        help=(
            "TaskFarmer THREADS (concurrent tasks per node). "
            "At ~6–7 GB peak per task, 12 tasks/node leaves comfortable headroom "
            "on a 512 GB Perlmutter CPU node. Raise to 16-24 once profiling "
            "confirms Dask streaming keeps peaks below ~8 GB."
        ),
    )
    parser.add_argument(
        "--nodes",
        type=int,
        default=4,
        help=(
            "Number of Slurm nodes (-N) in the generated script. "
            "The script also prints a node count suggestion based on task count."
        ),
    )
    parser.add_argument(
        "--config-dir",
        default=SCRIPT_DIR,
        help="Directory containing the per-year config YAML files.",
    )
    parser.add_argument(
        "--qos",
        default="regular",
        help="Slurm QOS (e.g. regular, debug, premium).",
    )
    parser.add_argument(
        "--time",
        default="01:00:00",
        metavar="HH:MM:SS",
        help="Slurm walltime.",
    )
    return parser.parse_args()


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def parse_yearmonth(s):
    """Parse 'YYYY-MM' into (int year, int month); exit on bad format."""
    parts = s.split("-")
    if len(parts) != 2:
        print(f"ERROR: Expected YYYY-MM date, got: {s!r}")
        sys.exit(1)
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        print(f"ERROR: Expected YYYY-MM date, got: {s!r}")
        sys.exit(1)


def yearmonth_range(start_ym, end_ym):
    """Yield (year, month) tuples from start_ym to end_ym inclusive."""
    y, m = start_ym
    ey, em = end_ym
    while (y, m) <= (ey, em):
        yield y, m
        m += 1
        if m > 12:
            m = 1
            y += 1


def find_pixel_files(pixel_dir, year, month_str):
    """Return sorted list of pixel-tracking NetCDF files for year-month."""
    pattern = os.path.join(pixel_dir, f"mcstrack_{year}{month_str}*_*.nc")
    return sorted(glob.glob(pattern))


def write_slurm(path, tasklist_path, nodes, threads, qos, walltime):
    """Write the Slurm TaskFarmer submission script."""
    content = f"""\
#!/bin/bash
#SBATCH --job-name=MonRainSCREAM
#SBATCH -A m1867
#SBATCH --time={walltime}
#SBATCH -q {qos}
#SBATCH -C cpu
#SBATCH -N {nodes} -c 128
#SBATCH --exclusive
#SBATCH --output=logs/log_mcs_monthly_rainmap_SCREAM_decadal.log
#SBATCH --mail-type=END
#SBATCH --mail-user=zhe.feng@pnnl.gov

# ─────────────────────────────────────────────────────────────────────────────
# IMPORTANT: load the TaskFarmer module BEFORE submitting this job:
#   module load taskfarmer
# Then submit with:
#   sbatch {os.path.basename(path)}
# ─────────────────────────────────────────────────────────────────────────────

date

# Measured peak memory: ~6 GB/task (THREADS workers run concurrently per node).
# Default THREADS=12 is conservative; raise to 24–48 for faster throughput.
export THREADS={threads}

runcommands.sh {tasklist_path}

date
"""
    with open(path, "w") as fh:
        fh.write(content)
    os.chmod(path, 0o755)
    print(f"  Written : {path}")


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()

    # ── Validate date arguments ──────────────────────────────────────────────
    start_ym = parse_yearmonth(args.start_date)
    end_ym   = parse_yearmonth(args.end_date)
    if start_ym > end_ym:
        print(
            f"ERROR: --start-date ({args.start_date}) must be <= "
            f"--end-date ({args.end_date})"
        )
        sys.exit(1)

    # ── Verify the TaskFarmer wrapper shell script ───────────────────────────
    if not os.path.exists(WRAPPER):
        print(f"ERROR: TaskFarmer wrapper not found: {WRAPPER}")
        sys.exit(1)

    # ── Ensure logs dir exists (required by Slurm --output) ─────────────────
    os.makedirs(SLURM_LOG_DIR, exist_ok=True)

    print(
        f"Scanning {args.start_date} – {args.end_date} for months with "
        f">= {args.min_files} pixel files ...\n"
        f"  Config dir : {args.config_dir}\n"
        f"  Threads    : {args.threads} tasks/node\n"
        f"  Nodes      : {args.nodes}\n"
    )

    task_lines = []
    n_skip = 0
    config_cache = {}   # year -> (config_path, cfg) or None

    for year, month in yearmonth_range(start_ym, end_ym):
        month_str = f"{month:02d}"
        tag = f"{year}-{month_str}"

        # ── Load config once per year ────────────────────────────────────────
        if year not in config_cache:
            config_fname = CONFIG_BASENAME.format(year=year)
            config_path  = os.path.join(args.config_dir, config_fname)
            if not os.path.exists(config_path):
                print(
                    f"  [WARN] Config not found for {year} "
                    f"({config_path}) — skipping all months of {year}."
                )
                config_cache[year] = None
            else:
                cfg = load_config(config_path)
                config_cache[year] = (config_path, cfg)

        entry = config_cache[year]
        if entry is None:
            continue
        config_path, cfg = entry

        # ── Count pixel files ────────────────────────────────────────────────
        pixel_dir = cfg["pixeltracking_outpath"]
        files     = find_pixel_files(pixel_dir, year, month_str)
        n_files   = len(files)

        if n_files < args.min_files:
            print(
                f"  [SKIP] {tag}: {n_files} pixel file(s) found "
                f"(< {args.min_files} required)."
            )
            n_skip += 1
            continue

        print(f"  [ADD]  {tag}: {n_files} pixel file(s) → task added.")
        task_lines.append(f"{WRAPPER} {config_path} {year} {month_str}")

    # ── Write tasklist ───────────────────────────────────────────────────────
    n_tasks = len(task_lines)
    tasklist_path = os.path.join(OUTPUT_DIR, TASKLIST_FNAME)
    with open(tasklist_path, "w") as fh:
        fh.write("\n".join(task_lines))
        if task_lines:
            fh.write("\n")

    print(f"\n  Written : {tasklist_path}  ({n_tasks} task(s), {n_skip} skipped)")

    if n_tasks == 0:
        print(
            "  [WARN] Tasklist is empty — no months met the pixel-file threshold.\n"
            "         Re-run after MCS tracking has produced pixel files."
        )

    # ── Node suggestion ──────────────────────────────────────────────────────
    if n_tasks > 0:
        suggested = max(1, math.ceil(n_tasks / args.threads))
        if suggested != args.nodes:
            print(
                f"  [NOTE] {n_tasks} tasks ÷ {args.threads} threads/node "
                f"→ suggested --nodes {suggested} "
                f"(writing --nodes {args.nodes} as specified)."
            )

    # ── Write Slurm script ───────────────────────────────────────────────────
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
