#!/usr/bin/env python
"""
Find SCREAM 2D input files that did not produce all 12 expected output files,
and write a reprocessing list.

Each input file (output.scream.2D.5min.INSTANT.nmins_x5.YYYY-MM-DD-SSSSS.nc)
contains 12 timesteps at 5-minute intervals starting at SSSSS seconds since
midnight. Expected outputs: scream.2D.5min.INSTANT.nmins_x5.YYYY-MM-DD-HHMMSS.nc

Author: Zhe Feng
Date: March 2026
"""

import os
import glob
from datetime import date, timedelta

# Directories
input_dir  = '/pscratch/sd/w/wcmca1/SCREAMv1-cess2/run_conus'
output_dir = '/pscratch/sd/w/wcmca1/SCREAMv1-cess2/remap_conus_2D_5min'
out_list   = '/global/homes/f/feng045/program/scream/regrid/reprocess_scream2D.txt'

NTIMES    = 12       # timesteps per input file
INTERVAL  = 300      # seconds between timesteps (5 min)
SECS_DAY  = 86400    # seconds in a day

# -----------------------------------------------------------------------
# 1. Build set of all existing output filenames (just basenames, fast lookup)
# -----------------------------------------------------------------------
print("Scanning output directory...")
existing_outputs = set(os.listdir(output_dir))
print(f"  Found {len(existing_outputs):,} existing output files")

# -----------------------------------------------------------------------
# 2. Scan input files
# -----------------------------------------------------------------------
print("Scanning input directory...")
input_files = sorted(glob.glob(f"{input_dir}/output.scream.2D.5min.INSTANT.nmins_x5.*.nc"))
print(f"  Found {len(input_files):,} input files")

# -----------------------------------------------------------------------
# 3. For each input file, check all 12 expected outputs
# -----------------------------------------------------------------------
missing_inputs   = []   # input basenames to reprocess
total_missing    = 0
partial_count    = 0    # inputs with some (not all) outputs missing

for input_path in input_files:
    basename = os.path.basename(input_path)
    # Parse: output.scream.2D.5min.INSTANT.nmins_x5.YYYY-MM-DD-SSSSS.nc
    # Timestamp portion: YYYY-MM-DD-SSSSS
    parts = basename.rstrip('.nc').split('.')
    ts = parts[-1]                     # e.g. "2020-04-01-00300"
    date_str   = ts[:10]               # "2020-04-01"
    secs_start = int(ts[11:])          # 300

    # Parse date
    yyyy, mm, dd = int(date_str[:4]), int(date_str[5:7]), int(date_str[8:10])
    base_date = date(yyyy, mm, dd)

    # Compute the 12 expected output timestamps
    missing_this = 0
    for i in range(NTIMES):
        secs = secs_start + i * INTERVAL
        # Handle rollover past midnight
        day_offset = secs // SECS_DAY
        secs_of_day = secs % SECS_DAY
        out_date = base_date + timedelta(days=day_offset)

        hh = secs_of_day // 3600
        mm_ = (secs_of_day % 3600) // 60
        hhmmss = f"{hh:02d}{mm_:02d}00"

        expected = f"scream.2D.5min.INSTANT.nmins_x5.{out_date.strftime('%Y-%m-%d')}-{hhmmss}.nc"
        if expected not in existing_outputs:
            missing_this += 1

    if missing_this > 0:
        missing_inputs.append(os.path.basename(input_path))
        total_missing += missing_this
        partial_count += (1 if missing_this < NTIMES else 0)

# -----------------------------------------------------------------------
# 4. Write reprocessing list
# -----------------------------------------------------------------------
with open(out_list, 'w') as f:
    for fname in missing_inputs:
        f.write(fname + '\n')

# -----------------------------------------------------------------------
# 5. Summary
# -----------------------------------------------------------------------
print()
print("=" * 60)
print("Summary")
print("=" * 60)
print(f"Total input files:          {len(input_files):,}")
print(f"Input files with missing outputs: {len(missing_inputs):,}")
print(f"  - Partially missing (some of 12): {partial_count:,}")
print(f"  - Fully missing (all 12):         {len(missing_inputs) - partial_count:,}")
print(f"Total missing output files: {total_missing:,}")
print(f"Reprocessing list written:  {out_list}")
print("=" * 60)
