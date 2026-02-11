#!/usr/bin/env python
"""
Split MRMS file list into batches for parallel SLURM processing.

This script creates batch file lists to enable efficient parallel processing
of MRMS 3D reflectivity remapping on NERSC Perlmutter.

Author: Zhe Feng
Date: February 9, 2026
"""

import os
import glob
from pathlib import Path

# Configuration
input_dir = '/pscratch/sd/i/iclas2/meng/mrms/conus_2025_netcdf/MRMS_MergedReflectivityQC_L33/'
batch_dir = '/pscratch/sd/i/iclas2/MRMS/batches'
files_per_batch = 2816  # Conservative: ~50 min per job with 32 workers (88 files/worker × 35s)

# Create batch directory
os.makedirs(batch_dir, exist_ok=True)

# Get all MRMS files
print("Scanning for MRMS files...")
mrms_files = sorted(glob.glob(f"{input_dir}/MRMS_MergedReflectivityQC_L33_*.nc"))
total_files = len(mrms_files)

if total_files == 0:
    print(f"ERROR: No MRMS files found in {input_dir}")
    exit(1)

print(f"Found {total_files:,} MRMS files")

# Calculate number of batches
num_batches = (total_files + files_per_batch - 1) // files_per_batch
print(f"\nSplitting into {num_batches} batches ({files_per_batch} files per batch)")

# Split files into batches
for batch_num in range(num_batches):
    start_idx = batch_num * files_per_batch
    end_idx = min(start_idx + files_per_batch, total_files)
    batch_files = mrms_files[start_idx:end_idx]
    
    # Write batch file list (just basenames for the shell script)
    batch_file = f"{batch_dir}/mrms_batch_{batch_num+1:02d}.txt"
    with open(batch_file, 'w') as f:
        for filepath in batch_files:
            basename = os.path.basename(filepath)
            f.write(f"{basename}\n")
    
    print(f"  Batch {batch_num+1:02d}: {len(batch_files):,} files -> {batch_file}")
    
    # Estimate processing time
    files_per_worker = len(batch_files) / 32  # Assuming 32 workers
    time_per_worker = files_per_worker * 35  # 35 seconds per file
    estimated_minutes = time_per_worker / 60
    print(f"             Estimated time: {estimated_minutes:.1f} min with 100 workers")

print(f"\nBatch files created in: {batch_dir}")
print(f"\nNext steps:")
print(f"  1. Review batch files in {batch_dir}")
print(f"  2. Submit SLURM jobs using: sbatch remap_mrms_batch.slurm <batch_number>")
print(f"  3. Example: sbatch remap_mrms_batch.slurm 1")
