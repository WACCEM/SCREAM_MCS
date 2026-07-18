#!/usr/bin/env python3
"""
Generalized MRMS batch and SLURM script generator for hourly files.

- Selects the MRMS file closest to the top of each hour.
- Splits into batches for parallel SLURM processing.
- Auto-generates a per-batch SLURM script and a submission script in the batch_dir.

Usage example:
  Remap MRMS QPE hourly files to HRRR grid:
  python create_mrms_slurm_batches_hourly.py \
    --input_dir /pscratch/sd/i/iclas2/meng/mrms/conus_2025_netcdf/MultiSensor_QPE_01H_Pass2_00.00 \
    --file_pattern 'MRMS_MultiSensor_QPE_01H_Pass2_00.00_*.nc' \
    --batch_dir /pscratch/sd/i/iclas2/MRMS/batches_hourly_qpe \
    --remap_script /global/homes/f/feng045/program/scream/regrid/mrms/remap_mrms_QPE_to_hrrr.sh \
    --out_dir /pscratch/sd/i/iclas2/MRMS/remap_QPE1H_hrrr \
    --tmp_dir /pscratch/sd/i/iclas2/MRMS/tmp \
    --weight_file /pscratch/sd/w/wcmca1/SCREAMv1-cess2/maps/MRMS_to_HRRR_conserve.nc \
    --files_per_batch 234 \
    --workers 64

  Remap MRMS reflectivity hourly files to MergedIR grid:
  python create_mrms_slurm_batches_hourly.py \
    --input_dir /pscratch/sd/i/iclas2/meng/mrms/conus_2025_netcdf/MRMS_MergedReflectivityQC_L33 \
    --file_pattern 'MRMS_MergedReflectivityQC_L33_*.nc' \
    --batch_dir /pscratch/sd/i/iclas2/MRMS/batches_hourly_reflectivity \
    --remap_script /global/homes/f/feng045/program/scream/regrid/mrms/remap_mrms_QPE_to_hrrr.sh \
    --out_dir /pscratch/sd/i/iclas2/MRMS/remap_mergedir \
    --tmp_dir /pscratch/sd/i/iclas2/MRMS/tmp \
    --weight_file /pscratch/sd/w/wcmca1/SCREAMv1-cess2/maps/MRMS_to_MergedIR_bilinear.nc \
    --files_per_batch 234 \
    --wall_clock 01:00:00 \
    --workers 32

Author: Zhe Feng
Date: March 27, 2026
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
                        help='Input directory containing MRMS files (also exported to remap script as IN_DIR)')
    parser.add_argument('--file_pattern', type=str, required=True,
                        help='Glob pattern for MRMS files, e.g. MRMS_MergedReflectivityQC_L33_*.nc')
    parser.add_argument('--batch_dir', type=str, required=True,
                        help='Directory to save batch lists and scripts')
    parser.add_argument('--files_per_batch', type=int, default=234,
                        help='Number of files per batch (default: 234)')
    parser.add_argument('--workers', type=int, default=32,
                        help='Number of parallel workers per batch job (default: 32)')
    parser.add_argument('--remap_script', type=str, required=True,
                        help='Path to the remap shell script')
    parser.add_argument('--out_dir', type=str, default='/pscratch/sd/i/iclas2/MRMS/remap_QPE1H_hrrr',
                        help='Output directory for remapped files')
    parser.add_argument('--tmp_dir', type=str, default='/pscratch/sd/i/iclas2/MRMS/tmp',
                        help='Temporary directory for intermediate files')
    parser.add_argument('--weight_file', type=str,
                        default='/pscratch/sd/w/wcmca1/SCREAMv1-cess2/maps/MRMS_to_HRRR_conserve.nc',
                        help='Path to conservative remapping weight file')
    parser.add_argument('--wall_clock', type=str, default='00:30:00',
                        help='Wall clock time for SLURM jobs (default: 00:30:00)')
    return parser.parse_args()

args = parse_args()
input_dir = args.input_dir
file_pattern = args.file_pattern
batch_dir = args.batch_dir.rstrip('/')
files_per_batch = args.files_per_batch
workers = args.workers
remap_script = args.remap_script
wall_clock = args.wall_clock

os.makedirs(batch_dir, exist_ok=True)

print(f"Scanning for MRMS files in {input_dir} matching {file_pattern} ...")
mrms_files = sorted(glob.glob(os.path.join(input_dir, file_pattern)))
total_files = len(mrms_files)

if total_files == 0:
    print(f"ERROR: No MRMS files found in {input_dir} with pattern {file_pattern}")
    exit(1)

print(f"Found {total_files:,} total MRMS files")

def extract_prefix(basename):
    m = re.match(r'(.+?)_\d{8}-\d{6}\.nc$', basename)
    if m:
        return m.group(1)
    m = re.match(r'(.+?)(\d{8}-\d{6})', basename)
    if m:
        return m.group(1).rstrip('_')
    return 'MRMS_UNKNOWN'

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
    except Exception:
        skipped += 1
        continue
    hour_key = (dt.year, dt.month, dt.day, dt.hour)
    seconds_from_hour = dt.minute * 60 + dt.second
    hourly_groups[hour_key].append((seconds_from_hour, filepath))
if skipped:
    print(f"  Warning: {skipped} files skipped (timestamp not parsed)")

print("Selecting file closest to :00:00 for each hour...")
hourly_files = []
for hour_key in sorted(hourly_groups.keys()):
    candidates = hourly_groups[hour_key]
    _, closest_filepath = min(candidates, key=lambda x: x[0])
    hourly_files.append(closest_filepath)

print(f"Selected {len(hourly_files):,} hourly files "
      f"(from {total_files:,} total; {total_files / max(len(hourly_files), 1):.1f}x reduction)")

num_batches = (len(hourly_files) + files_per_batch - 1) // files_per_batch
print(f"\nSplitting into {num_batches} batches ({files_per_batch} files per batch)")

prefix = extract_prefix(os.path.basename(hourly_files[0])) if hourly_files else 'MRMS_UNKNOWN'

for batch_num in range(num_batches):
    start_idx = batch_num * files_per_batch
    end_idx = min(start_idx + files_per_batch, len(hourly_files))
    batch_files = hourly_files[start_idx:end_idx]
    batch_file = f"{batch_dir}/{prefix}_batch_{batch_num + 1:02d}.txt"
    with open(batch_file, 'w') as f:
        for filepath in batch_files:
            f.write(f"{os.path.basename(filepath)}\n")
    files_per_worker = len(batch_files) / workers
    estimated_minutes = (files_per_worker * 35) / 60
    print(f"  Batch {batch_num + 1:02d}: {len(batch_files):,} files -> {batch_file}  (~{estimated_minutes:.1f} min with {workers} workers)")
print(f"\nBatch files created in: {batch_dir}")

# Write SLURM scripts if batches exist
if hourly_files:
    submit_script = os.path.join(batch_dir, f"submit_all_{prefix}_batches.sh")
    slurm_script = os.path.join(batch_dir, f"slurm_remap_{prefix}_batch.sh")

    with open(slurm_script, 'w') as f:
        f.write(f"""#!/bin/bash
#SBATCH --account=m1657
#SBATCH --qos=regular
#SBATCH --time={wall_clock}
#SBATCH --nodes=1
#SBATCH --constraint=cpu
#SBATCH --mail-type=END
#SBATCH --mail-user=zhe.feng@pnnl.gov
#SBATCH --output={batch_dir}/logs/{prefix}_%j.log
#SBATCH --error={batch_dir}/logs/{prefix}_%j.err

# Auto-generated SLURM script for {prefix} batch processing
# Usage: sbatch {os.path.basename(slurm_script)} <batch_number>

if [ $# -ne 1 ]; then
    echo "ERROR: Batch number required"
    echo "Usage: sbatch $0 <batch_number>"
    exit 1
fi
BATCH_NUM=$1
BATCH_DIR="{batch_dir}"
BATCH_FILE="$BATCH_DIR/{prefix}_batch_$(printf '%02d' $BATCH_NUM).txt"
LOG_DIR="$BATCH_DIR/logs"
NUM_WORKERS={workers}
REMAP_SCRIPT="{remap_script}"
mkdir -p "$LOG_DIR"
if [ ! -f "$BATCH_FILE" ]; then
    echo "ERROR: Batch file not found: $BATCH_FILE"
    exit 1
fi
if [ ! -f "$REMAP_SCRIPT" ]; then
    echo "ERROR: Remap script not found: $REMAP_SCRIPT"
    exit 1
fi
NUM_FILES=$(wc -l < "$BATCH_FILE")
echo "Start: $(date)"
echo "Processing $NUM_FILES files in $BATCH_FILE"
source /global/common/software/e3sm/anaconda_envs/load_latest_e3sm_unified_pm-cpu.sh
export IN_DIR="{input_dir}"
export OUT_DIR="{args.out_dir}"
export TMP_DIR="{args.tmp_dir}"
export WEIGHT_FILE="{args.weight_file}"
cat "$BATCH_FILE" | parallel --jobs $NUM_WORKERS --bar \\\n    --joblog "$LOG_DIR/batch_${{BATCH_NUM}}_joblog.txt" \\\n    --halt soon,fail=1 bash "$REMAP_SCRIPT" {{}} \\\n    || {{ echo "ERROR: parallel job failed, check $LOG_DIR/batch_${{BATCH_NUM}}_joblog.txt"; exit 1; }}
echo "Done: $(date)"
""")
    os.chmod(slurm_script, 0o755)

    with open(submit_script, 'w') as f:
        f.write(f"""#!/bin/bash
set -e
BATCH_DIR="{batch_dir}"
LOG_DIR="$BATCH_DIR/logs"
SLURM_SCRIPT="{slurm_script}"
mkdir -p "$LOG_DIR"
NUM_BATCHES=$(ls -1 "$BATCH_DIR"/{prefix}_batch_*.txt 2>/dev/null | wc -l)
if [ $NUM_BATCHES -eq 0 ]; then
    echo "ERROR: No batch files found in $BATCH_DIR"
    exit 1
fi
declare -a JOB_IDS
for batch_num in $(seq 1 $NUM_BATCHES); do
    echo "Submitting batch $batch_num/$NUM_BATCHES..."
    JOB_ID=$(sbatch --parsable --job-name=batch_$(printf '%02d' $batch_num) "$SLURM_SCRIPT" "$batch_num")
    JOB_IDS+=($JOB_ID)
    echo "  Job ID: $JOB_ID (batch_$(printf '%02d' $batch_num))"
    sleep 1
done
echo "All batches submitted! Job IDs: ${{JOB_IDS[@]}}"
JOB_LIST="$LOG_DIR/submitted_jobs_$(date +%Y%m%d_%H%M%S).txt"
for job_id in "${{JOB_IDS[@]}}"; do
    echo "$job_id" >> "$JOB_LIST"
done
echo "Job IDs saved to: $JOB_LIST"
""")
    os.chmod(submit_script, 0o755)
    print(f"\nAuto-generated SLURM scripts:")
    print(f"  Per-batch: {slurm_script}")
    print(f"  Submit all: {submit_script}")
    print(f"\nTo submit all batches: {submit_script}")
