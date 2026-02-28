#!/bin/bash
#
# Submit all SCREAM 2D remapping batch jobs to SLURM
#
# Usage: ./submit_all_scream2D_batches.sh

set -e

# Configuration
BATCH_DIR="/pscratch/sd/w/wcmca1/SCREAMv1-cess2/scream2D_batches"
LOG_DIR="${BATCH_DIR}/logs"
SLURM_SCRIPT="/global/homes/f/feng045/program/scream/regrid/slurm_remap_scream2D_batch.sh"

# Create log directory
mkdir -p "$LOG_DIR"

# Count number of batch files
NUM_BATCHES=$(ls -1 "${BATCH_DIR}"/scream2D_batch_*.txt 2>/dev/null | wc -l)

if [ $NUM_BATCHES -eq 0 ]; then
    echo "ERROR: No batch files found in ${BATCH_DIR}"
    echo "Run create_scream2D_batches.py first to generate batch files"
    exit 1
fi

echo "========================================================================"
echo "Submitting SCREAM 2D Batch Processing Jobs"
echo "========================================================================"
echo "Number of batches: $NUM_BATCHES (64 workers/batch, ~768 files each)"
echo "SLURM script:      $SLURM_SCRIPT"
echo "Log directory:     $LOG_DIR"
echo "========================================================================"
echo ""

# Array to store job IDs
declare -a JOB_IDS

# Submit all batches
for batch_num in $(seq 1 $NUM_BATCHES); do
    echo "Submitting batch ${batch_num}/${NUM_BATCHES}..."

    JOB_ID=$(sbatch --parsable --job-name=sc2D$(printf '%02d' $batch_num) "$SLURM_SCRIPT" $batch_num)
    JOB_IDS+=($JOB_ID)

    echo "  Job ID: $JOB_ID (sc2D$(printf '%02d' $batch_num))"

    # Small delay to avoid overwhelming scheduler
    sleep 1
done

echo ""
echo "========================================================================"
echo "All batches submitted successfully!"
echo "========================================================================"
echo "Job IDs: ${JOB_IDS[@]}"
echo ""
echo "Monitor jobs with:"
echo "  squeue -u \$USER"
echo "  squeue -j $(IFS=,; echo "${JOB_IDS[*]}")"
echo ""
echo "Cancel all jobs if needed:"
echo "  scancel $(IFS=' '; echo "${JOB_IDS[*]}")"
echo ""
echo "Check logs in: $LOG_DIR"
echo "========================================================================"

# Save job IDs to file for reference
JOB_LIST="${LOG_DIR}/submitted_jobs_$(date +%Y%m%d_%H%M%S).txt"
for job_id in "${JOB_IDS[@]}"; do
    echo "$job_id" >> "$JOB_LIST"
done
echo "Job IDs saved to: $JOB_LIST"
