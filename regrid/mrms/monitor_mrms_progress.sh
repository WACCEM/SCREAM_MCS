#!/bin/bash
#
# Monitor MRMS batch processing progress
#
# Usage: ./monitor_mrms_progress.sh

# Configuration
BATCH_DIR="/pscratch/sd/i/iclas2/MRMS/batches"
OUT_DIR="/pscratch/sd/i/iclas2/MRMS/remap_hrrr"
LOG_DIR="${BATCH_DIR}/logs"

# ANSI color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "========================================================================"
echo "MRMS Batch Processing Monitor"
echo "========================================================================"
echo ""

# Count batch files and expected total files
NUM_BATCHES=$(ls -1 "${BATCH_DIR}"/mrms_batch_*.txt 2>/dev/null | wc -l)
if [ $NUM_BATCHES -eq 0 ]; then
    echo "${RED}ERROR: No batch files found${NC}"
    exit 1
fi

TOTAL_FILES=0
for batch_file in "${BATCH_DIR}"/mrms_batch_*.txt; do
    count=$(wc -l < "$batch_file")
    TOTAL_FILES=$((TOTAL_FILES + count))
done

echo -e "${BLUE}Batch Configuration:${NC}"
echo "  Number of batches: $NUM_BATCHES"
echo "  Total input files: $TOTAL_FILES"
echo ""

# Check SLURM jobs
echo -e "${BLUE}SLURM Job Status:${NC}"
squeue -u $USER -o "%.18i %.9P %.30j %.8T %.10M %.6D %R" | grep -E "JOBID|mrms_remap" || echo "  No active jobs found"
echo ""

# Count completed output files
NUM_OUTPUT=$(ls -1 "$OUT_DIR"/MRMS_Reflectivity_HRRR_*.nc 2>/dev/null | wc -l)
PERCENT_COMPLETE=$(echo "scale=2; 100 * $NUM_OUTPUT / $TOTAL_FILES" | bc)

echo -e "${BLUE}Processing Progress:${NC}"
echo "  Completed files: $NUM_OUTPUT / $TOTAL_FILES (${PERCENT_COMPLETE}%)"

# Progress bar
BAR_WIDTH=50
FILLED=$(echo "scale=0; $BAR_WIDTH * $NUM_OUTPUT / $TOTAL_FILES" | bc)
EMPTY=$((BAR_WIDTH - FILLED))
printf "  Progress: ["
printf "${GREEN}%${FILLED}s${NC}" | tr ' ' '='
printf "%${EMPTY}s" | tr ' ' '-'
printf "]\n"
echo ""

# Check for recent completions (last 5 minutes)
RECENT_FILES=$(find "$OUT_DIR" -name "MRMS_Reflectivity_HRRR_*.nc" -mmin -5 2>/dev/null | wc -l)
if [ $RECENT_FILES -gt 0 ]; then
    echo -e "${GREEN}Recent activity:${NC} $RECENT_FILES files completed in last 5 minutes"
    RATE_PER_MIN=$(echo "scale=1; $RECENT_FILES / 5" | bc)
    REMAINING=$((TOTAL_FILES - NUM_OUTPUT))
    ETA_MIN=$(echo "scale=0; $REMAINING / $RATE_PER_MIN" | bc 2>/dev/null || echo "N/A")
    if [ "$ETA_MIN" != "N/A" ]; then
        ETA_HOURS=$((ETA_MIN / 60))
        ETA_MIN_REM=$((ETA_MIN % 60))
        echo "  Processing rate: ${RATE_PER_MIN} files/min"
        echo "  Estimated time remaining: ${ETA_HOURS}h ${ETA_MIN_REM}m"
    fi
fi
echo ""

# Check for job logs and errors
echo -e "${BLUE}Job Log Summary:${NC}"
if [ -d "$LOG_DIR" ]; then
    NUM_LOGS=$(ls -1 "$LOG_DIR"/mrms_batch_*.log 2>/dev/null | wc -l)
    NUM_ERRS=$(ls -1 "$LOG_DIR"/mrms_batch_*.err 2>/dev/null | wc -l)
    echo "  Log files: $NUM_LOGS"
    echo "  Error files: $NUM_ERRS"
    
    # Check for non-empty error files
    ERROR_COUNT=0
    for err_file in "$LOG_DIR"/mrms_batch_*.err; do
        if [ -f "$err_file" ] && [ -s "$err_file" ]; then
            ERROR_COUNT=$((ERROR_COUNT + 1))
        fi
    done
    
    if [ $ERROR_COUNT -gt 0 ]; then
        echo -e "  ${RED}WARNING: $ERROR_COUNT error files contain output${NC}"
        echo "  Check with: ls -lh ${LOG_DIR}/*.err"
    fi
    
    # Show most recent log entries
    LATEST_LOG=$(ls -t "$LOG_DIR"/mrms_batch_*.log 2>/dev/null | head -1)
    if [ -f "$LATEST_LOG" ]; then
        echo ""
        echo "  Latest log file: $(basename $LATEST_LOG)"
        LAST_LINE=$(tail -1 "$LATEST_LOG" 2>/dev/null | grep -o "completed successfully\|failed\|processing" || echo "")
        if [ -n "$LAST_LINE" ]; then
            echo "  Status: $LAST_LINE"
        fi
    fi
else
    echo "  Log directory not found: $LOG_DIR"
fi

echo ""
echo "========================================================================"
echo "Refresh this display with: $0"
echo "Watch mode: watch -n 30 $0"
echo "========================================================================"
