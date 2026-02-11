#!/bin/bash
# Create a small test batch (100 files) for debug queue testing
# This allows testing 32 workers with minimal time

BATCH_DIR="/pscratch/sd/i/iclas2/MRMS/batches"
INPUT_DIR="/pscratch/sd/i/iclas2/meng/mrms/conus_2025_netcdf/MRMS_MergedReflectivityQC_L33/"

mkdir -p "$BATCH_DIR"

# Get first 100 files for testing (use find to avoid argument list too long)
find "${INPUT_DIR}" -maxdepth 1 -name "MRMS_MergedReflectivityQC_L33_*.nc" -type f | head -100 | xargs -n1 basename > "${BATCH_DIR}/mrms_batch_test.txt"

NUM_FILES=$(wc -l < "${BATCH_DIR}/mrms_batch_test.txt")
echo "Created test batch with ${NUM_FILES} files:"
echo "  ${BATCH_DIR}/mrms_batch_test.txt"
echo ""
echo "Estimated time with 32 workers:"
echo "  Per worker: 3-4 files × 35s = ~2 minutes"
echo "  Total: ~2-3 minutes (includes overhead)"
echo ""
echo "Submit test with:"
echo "  sbatch --qos=debug --time=00:30:00 slurm_remap_mrms_batch.sh test"
