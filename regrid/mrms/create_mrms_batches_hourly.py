#!/usr/bin/env python
"""
Split hourly MRMS file list into batches for parallel SLURM processing.

This script selects the MRMS file closest to the hourly mark (:00 min) for
each hour and creates batch file lists to enable efficient parallel processing
of MRMS 3D reflectivity remapping to the 4-km MergedIR grid on NERSC Perlmutter.

Hourly selection: for each hour, the file with a timestamp nearest to XX:00:00
is chosen (one file per hour).  This reduces the dataset to ~1/12 the size of
the original 5-min archive.

Author: Zhe Feng
Date: February 24, 2026
"""

import os
import glob
import re
from datetime import datetime
from collections import defaultdict


import argparse

def parse_args():
    parser = argparse.ArgumentParser(
        description="Split MRMS hourly file list into batches for parallel SLURM processing. "
                    "Works for any MRMS product with hourly files.")
    parser.add_argument('--input_dir', type=str, required=True,
                        help='Input directory containing MRMS files')
    parser.add_argument('--file_pattern', type=str, required=True,
                        help='Glob pattern for MRMS files, e.g. MRMS_MergedReflectivityQC_L33_*.nc')
    parser.add_argument('--batch_dir', type=str, required=True,
                        help='Directory to save batch lists')
    parser.add_argument('--files_per_batch', type=int, default=234,
                        help='Number of files per batch (default: 234)')
    return parser.parse_args()

args = parse_args()
input_dir = args.input_dir
file_pattern = args.file_pattern
batch_dir = args.batch_dir
files_per_batch = args.files_per_batch

# Create batch directory
os.makedirs(batch_dir, exist_ok=True)

# ──────────────────────────────────────────────────────────────────────────────
# Step 1: Collect all MRMS files
# ──────────────────────────────────────────────────────────────────────────────

print(f"Scanning for MRMS files in {input_dir} matching {file_pattern} ...")
mrms_files = sorted(glob.glob(os.path.join(input_dir, file_pattern)))
total_files = len(mrms_files)

if total_files == 0:
    print(f"ERROR: No MRMS files found in {input_dir} with pattern {file_pattern}")
    exit(1)

print(f"Found {total_files:,} total MRMS files")

# ──────────────────────────────────────────────────────────────────────────────
# Step 2: Parse timestamps and group by (year, month, day, hour)

# Try to extract the prefix for batch file naming (everything before the first date block)
def extract_prefix(basename):
    m = re.match(r'(.+?)_\d{8}-\d{6}\.nc$', basename)
    if m:
        return m.group(1)
    # fallback: up to first date-like string
    m = re.match(r'(.+?)(\d{8}-\d{6})', basename)
    if m:
        return m.group(1).rstrip('_')
    return 'MRMS_UNKNOWN'

# Robust timestamp pattern: find 8 digits, dash, 6 digits, before .nc
timestamp_pattern = re.compile(r'(\d{8})-(\d{6})\.nc$')
hourly_groups = defaultdict(list)
skipped = 0

for filepath in mrms_files:
    basename = os.path.basename(filepath)
    match = timestamp_pattern.search(basename)
    if not match:
        skipped += 1
        continue
    date_str, time_str = match.groups()
    try:
        dt = datetime.strptime(f"{date_str}{time_str}", "%Y%m%d%H%M%S")
    except Exception as e:
        skipped += 1
        continue
    hour_key = (dt.year, dt.month, dt.day, dt.hour)
    seconds_from_hour = dt.minute * 60 + dt.second
    hourly_groups[hour_key].append((seconds_from_hour, filepath))

if skipped:
    print(f"  Warning: {skipped} files skipped (timestamp not parsed)")

# ──────────────────────────────────────────────────────────────────────────────
# Step 3: Select the single file closest to :00:00 for each hour
# ──────────────────────────────────────────────────────────────────────────────

print("Selecting file closest to :00:00 for each hour...")
hourly_files = []
for hour_key in sorted(hourly_groups.keys()):
    candidates = hourly_groups[hour_key]
    # Pick the file with the smallest distance from the top of the hour
    _, closest_filepath = min(candidates, key=lambda x: x[0])
    hourly_files.append(closest_filepath)

print(f"Selected {len(hourly_files):,} hourly files "
      f"(from {total_files:,} total; {total_files / max(len(hourly_files), 1):.1f}x reduction)")

# ──────────────────────────────────────────────────────────────────────────────
# Step 4: Split into batches and write batch file lists
# ──────────────────────────────────────────────────────────────────────────────

num_batches = (len(hourly_files) + files_per_batch - 1) // files_per_batch
print(f"\nSplitting into {num_batches} batches ({files_per_batch} files per batch)")

# Use prefix for batch file naming
prefix = extract_prefix(os.path.basename(hourly_files[0])) if hourly_files else 'MRMS_UNKNOWN'

for batch_num in range(num_batches):
    start_idx = batch_num * files_per_batch
    end_idx = min(start_idx + files_per_batch, len(hourly_files))
    batch_files = hourly_files[start_idx:end_idx]

    # Write batch file list — basenames only (shell script prepends directory)
    batch_file = f"{batch_dir}/{prefix}_batch_{batch_num + 1:02d}.txt"
    with open(batch_file, 'w') as f:
        for filepath in batch_files:
            f.write(f"{os.path.basename(filepath)}\n")

    # Estimate wall-clock time (empirical: ~35 s/file, 32 workers)
    files_per_worker = len(batch_files) / 32
    estimated_minutes = (files_per_worker * 35) / 60
    print(f"  Batch {batch_num + 1:02d}: {len(batch_files):,} files -> {batch_file}  "
          f"(~{estimated_minutes:.1f} min with 32 workers)")

print(f"\nBatch files created in: {batch_dir}")
print(f"\nNext steps:")
print(f"  1. Review batch files in {batch_dir}")
print(f"  2. Submit a single job:  sbatch slurm_remap_mrms_batch_hourly.sh <batch_number>")
print(f"  3. Submit all batches:   ./submit_all_mrms_batches_hourly.sh")
