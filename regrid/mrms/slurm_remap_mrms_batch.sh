#!/bin/bash
#SBATCH --account=m1657
#SBATCH --qos=regular
#SBATCH --time=02:00:00
#SBATCH --nodes=1
#SBATCH --constraint=cpu
#SBATCH --output=logs/mrms_batch_%A_%a.log
#SBATCH --error=logs/mrms_batch_%A_%a.err

#==============================================================================
# Parallel MRMS to HRRR remapping using GNU parallel
#
# Usage: sbatch slurm_remap_mrms_batch.sh <batch_number>
#
# Examples:
#   sbatch slurm_remap_mrms_batch.sh 1
#   sbatch slurm_remap_mrms_batch.sh 2
#   
# Or submit all batches at once:
#   for i in {1..19}; do sbatch slurm_remap_mrms_batch.sh $i; done
#
# Performance:
#   - 1 node = 128 CPU cores
#   - Using 32 workers (optimal for I/O and memory)
#   - ~2,800 files per batch
#   - Processing rate: ~24 files/min (measured)
#   - Target: ~2 hours per batch (120 min wallclock)
#
# Author: Zhe Feng
# Date: February 9, 2026
#==============================================================================

set -e  # Exit on error

# Get batch number from command line argument
if [ $# -ne 1 ]; then
    echo "ERROR: Batch number required"
    echo "Usage: sbatch $0 <batch_number>"
    exit 1
fi

BATCH_NUM=$1

# Configuration
BATCH_DIR="/pscratch/sd/i/iclas2/MRMS/batches"
BATCH_FILE="${BATCH_DIR}/mrms_batch_$(printf '%02d' ${BATCH_NUM}).txt"
SCRIPT_DIR="/global/homes/f/feng045/program/scream/regrid/mrms"
REMAP_SCRIPT="${SCRIPT_DIR}/remap_mrms_to_hrrr.sh"
LOG_DIR="${BATCH_DIR}/logs"
NUM_WORKERS=32  # Number of parallel workers (optimal for I/O and memory constraints)

# Create log directory
mkdir -p "$LOG_DIR"

# Check if batch file exists
if [ ! -f "$BATCH_FILE" ]; then
    echo "ERROR: Batch file not found: $BATCH_FILE"
    echo "Run create_mrms_batches.py first to generate batch files"
    exit 1
fi

# Check if remap script exists
if [ ! -f "$REMAP_SCRIPT" ]; then
    echo "ERROR: Remap script not found: $REMAP_SCRIPT"
    exit 1
fi

# Count files in this batch
NUM_FILES=$(wc -l < "$BATCH_FILE")

echo "========================================================================"
echo "MRMS Batch Processing - Batch ${BATCH_NUM}"
echo "========================================================================"
echo "Job ID:         $SLURM_JOB_ID"
echo "Node:           $SLURM_NODELIST"
echo "Batch file:     $BATCH_FILE"
echo "Number of files: $NUM_FILES"
echo "Parallel workers: $NUM_WORKERS"
echo "Start time:     $(date)"
echo "========================================================================"

# Load required environment
echo "Loading E3SM environment..."
source /global/common/software/e3sm/anaconda_envs/load_latest_e3sm_unified_pm-cpu.sh

# Start timer
START_TIME=$(date +%s)

# Process files in parallel using GNU parallel
# --jobs: number of parallel workers
# --bar: show progress bar
# --joblog: log file for each job
# --halt: stop if any job fails with exit code 1-255
echo ""
echo "Starting parallel processing with ${NUM_WORKERS} workers..."
echo "----------------------------------------------------------------------"

cat "$BATCH_FILE" | parallel --jobs ${NUM_WORKERS} \
    --bar \
    --joblog "${LOG_DIR}/batch_${BATCH_NUM}_joblog.txt" \
    --halt soon,fail=1 \
    bash "$REMAP_SCRIPT" {}

# Check exit status
PARALLEL_EXIT=$?
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))
ELAPSED_MIN=$((ELAPSED / 60))
ELAPSED_SEC=$((ELAPSED % 60))

echo ""
echo "========================================================================"
if [ $PARALLEL_EXIT -eq 0 ]; then
    echo "Batch ${BATCH_NUM} completed successfully!"
    echo "========================================================================"
    echo "Files processed: $NUM_FILES"
    echo "Elapsed time:    ${ELAPSED_MIN}m ${ELAPSED_SEC}s"
    echo "Average time:    $(echo "scale=2; $ELAPSED / $NUM_FILES" | bc)s per file"
    echo "End time:        $(date)"
    echo "========================================================================"
    
    # Count successful outputs
    OUT_DIR="/pscratch/sd/i/iclas2/MRMS/remap_hrrr"
    NUM_OUTPUT=$(ls -1 "$OUT_DIR"/MRMS_Reflectivity_HRRR_*.nc 2>/dev/null | wc -l)
    echo "Total output files: $NUM_OUTPUT"
    
else
    echo "ERROR: Batch ${BATCH_NUM} failed with exit code $PARALLEL_EXIT"
    echo "========================================================================"
    echo "Check job log for details:"
    echo "  ${LOG_DIR}/batch_${BATCH_NUM}_joblog.txt"
    exit 1
fi
