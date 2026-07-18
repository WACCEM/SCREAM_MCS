#!/bin/bash
# Quick test script for debug queue
# Usage: ./test_mrms_debug.sh <batch_number>

BATCH_NUM=${1:-1}

echo "Submitting batch ${BATCH_NUM} to debug queue for testing..."
echo "  Queue: debug"
echo "  Time: 30 minutes"
echo "  Workers: 32"
echo ""

sbatch --qos=debug --time=00:30:00 slurm_remap_mrms_batch.sh ${BATCH_NUM}
