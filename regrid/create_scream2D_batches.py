#!/usr/bin/env python
"""
Split SCREAM 2D file list into batches for parallel SLURM processing.

This script creates batch file lists to enable efficient parallel processing
of SCREAM 2D variable remapping on NERSC Perlmutter.

Sizing rationale:
  - Each file takes ~3-5 min to remap (ncremap + frac_b masking + ncks split)
  - 64 parallel workers per node
  - 2-hour walltime target
  - Files per batch: 1500 (23.4 files/worker × ~4 min = ~94 min, fits in 2h)

Author: Zhe Feng
Date: February 2026
"""

import os
import glob

# Configuration
input_dir = '/pscratch/sd/w/wcmca1/SCREAMv1-cess2/run_conus'
batch_dir = '/pscratch/sd/w/wcmca1/SCREAMv1-cess2/scream2D_batches'
files_per_batch = 768   # 768 / 64 workers × ~5 min/file = 60 min per job (fits in 1h walltime)

# Create batch directory
os.makedirs(batch_dir, exist_ok=True)

# Get all SCREAM 2D files
print("Scanning for SCREAM 2D files...")
scream_files = sorted(glob.glob(f"{input_dir}/output.scream.2D.5min.INSTANT.nmins_x5.*.nc"))
total_files = len(scream_files)

if total_files == 0:
    print(f"ERROR: No SCREAM 2D files found in {input_dir}")
    exit(1)

print(f"Found {total_files:,} SCREAM 2D files")

# Calculate number of batches
num_batches = (total_files + files_per_batch - 1) // files_per_batch
print(f"Splitting into {num_batches} batches (~{files_per_batch} files per batch, ~60 min each)")

# Split files into batches
for batch_num in range(num_batches):
    start_idx = batch_num * files_per_batch
    end_idx = min(start_idx + files_per_batch, total_files)
    batch_files = scream_files[start_idx:end_idx]

    # Write batch file list (just basenames — remap script prepends input dir)
    batch_file = f"{batch_dir}/scream2D_batch_{batch_num+1:02d}.txt"
    with open(batch_file, 'w') as f:
        for filepath in batch_files:
            f.write(f"{os.path.basename(filepath)}\n")

    # Estimate processing time (using 5 min/file)
    files_per_worker = len(batch_files) / 64
    estimated_minutes = files_per_worker * 5
    print(f"  Batch {batch_num+1:02d}: {len(batch_files):,} files -> {batch_file}")
    print(f"             Estimated time: {estimated_minutes:.0f} min with 64 workers")

print(f"\nBatch files created in: {batch_dir}")
print(f"\nNext steps:")
print(f"  1. Submit all batches: ./submit_all_scream2D_batches.sh")
print(f"  2. Or submit one:      sbatch slurm_remap_scream2D_batch.sh 1")
