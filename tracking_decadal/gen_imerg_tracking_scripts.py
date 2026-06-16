#!/usr/bin/env python
"""
Generate IMERGv7 MCS tracking config YAML files and Slurm job scripts
from templates, with an option to submit the Slurm jobs.

Usage examples:
    # Write both config + slurm files for default year range (1998–2025)
    python gen_imerg_tracking_scripts.py

    # Write for a custom year range
    python gen_imerg_tracking_scripts.py --start-year 2000 --end-year 2002

    # Write only config files
    python gen_imerg_tracking_scripts.py --no-write_slurm

    # Write files AND submit all jobs
    python gen_imerg_tracking_scripts.py --submit

    # Submit without re-writing files (files must already exist)
    python gen_imerg_tracking_scripts.py --no-write_config --no-write_slurm --submit
"""

import argparse
import glob
import os
import subprocess
import sys

# ──────────────────────────────────────────────────────────────────────────────
# Paths and constants
# ──────────────────────────────────────────────────────────────────────────────

# Flat directory containing all input files (no sub-folders)
INPUT_DATA_DIR = "/pscratch/sd/w/wcmca1/GPM/IR_IMERG_Combined_V07B"

# This script lives inside the config directory — use it as the output directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = SCRIPT_DIR

# Template file paths
CONFIG_TEMPLATE = os.path.join(SCRIPT_DIR, "config_mcs_tbpf_IMERGv7_mcsmip_template.yml")
SLURM_TEMPLATE  = os.path.join(SCRIPT_DIR, "slurm_mcs_IMERGv7_mcsmip_template.sh")

# Slurm log directory (must exist before jobs are submitted)
SLURM_LOG_DIR = os.path.join(SCRIPT_DIR, "slurm", "log")

# Prefix of input files used to glob by year
FILE_PREFIX = "merg_"


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Generate IMERGv7 MCS tracking config YAML and Slurm job scripts "
            "from templates, and optionally submit the jobs."
        )
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=1998,
        help="First year to process (default: 1998)",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=2025,
        help="Last year to process (default: 2025)",
    )
    parser.add_argument(
        "--write_config",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write config YAML files (default: True; use --no-write_config to skip)",
    )
    parser.add_argument(
        "--write_slurm",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write Slurm job scripts (default: True; use --no-write_slurm to skip)",
    )
    parser.add_argument(
        "--submit",
        action="store_true",
        default=False,
        help="Submit Slurm jobs with sbatch after writing the scripts (default: False)",
    )
    return parser.parse_args()


def read_template(path):
    with open(path, "r") as fh:
        return fh.read()


def write_file(path, content):
    with open(path, "w") as fh:
        fh.write(content)
    print(f"  Written : {path}")


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()

    if not (args.write_config or args.write_slurm or args.submit):
        print("Nothing to do — pass --write_config, --write_slurm, or --submit.")
        sys.exit(0)

    if args.start_year > args.end_year:
        print(f"ERROR: --start-year ({args.start_year}) must be <= --end-year ({args.end_year})")
        sys.exit(1)

    # Create the Slurm log directory so the --output path in the script is valid
    os.makedirs(SLURM_LOG_DIR, exist_ok=True)

    # Read templates once
    config_template = read_template(CONFIG_TEMPLATE)
    slurm_template  = read_template(SLURM_TEMPLATE)

    print(f"Processing years {args.start_year}–{args.end_year}\n")
    n_processed = 0

    for year in range(args.start_year, args.end_year + 1):

        # ── Count input files for this year ──────────────────────────────────
        pattern = os.path.join(INPUT_DATA_DIR, f"{year}/{FILE_PREFIX}{year}*.nc")
        files   = sorted(glob.glob(pattern))
        n_files = len(files)
        print(f"{year}: {n_files} file(s) found")

        if n_files == 0:
            print(f"  [ERROR] No input files found for {year}, skipping.\n")
            continue

        # ── Date bounds (year boundaries) ────────────────────────────────────
        startdate = f"{year}0101.0000"
        enddate   = f"{year + 1}0101.0000"

        # ── Output file paths ────────────────────────────────────────────────
        config_fname = f"config_mcs_tbpf_IMERGv7_mcsmip_{year}.yml"
        slurm_fname  = f"slurm_mcs_IMERGv7_mcsmip_{year}.sh"
        config_path  = os.path.join(OUTPUT_DIR, config_fname)
        slurm_path   = os.path.join(OUTPUT_DIR, slurm_fname)

        # ── Config substitution ──────────────────────────────────────────────
        # Replace STARTDATE / ENDDATE before YEAR to avoid partial matches
        config_text = (
            config_template
            .replace("STARTDATE", startdate)
            .replace("ENDDATE",   enddate)
            .replace("YEAR",      str(year))
        )

        # ── Slurm substitution ───────────────────────────────────────────────
        slurm_text = slurm_template.replace("YEAR", str(year))

        # ── Write files ──────────────────────────────────────────────────────
        if args.write_config:
            write_file(config_path, config_text)

        if args.write_slurm:
            write_file(slurm_path, slurm_text)
            os.chmod(slurm_path, 0o755)

        # ── Submit ───────────────────────────────────────────────────────────
        if args.submit:
            if not os.path.exists(slurm_path):
                print(
                    f"  [SKIP submit] {slurm_fname} does not exist — "
                    "run with --write_slurm first"
                )
            else:
                result = subprocess.run(
                    ["sbatch", slurm_path],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    print(f"  Submitted: {result.stdout.strip()}")
                else:
                    print(f"  [ERROR] sbatch failed: {result.stderr.strip()}")

        n_processed += 1

    print(f"\nDone. Processed {n_processed} year(s).")


if __name__ == "__main__":
    main()
