#!/bin/bash
#
# Remap MRMS QPE data to HRRR grid using pre-computed remapping weight file
#
# Usage: ./remap_mrms_QPE_to_hrrr.sh <mrms_filepath>
#
# The script accepts a full path or just a filename.
# If just a filename, IN_DIR must be set as an environment variable.
#
# Environment variables (all have defaults, override as needed):
#   IN_DIR        - Input directory (used if $1 is a bare filename)
#   OUT_DIR       - Output directory for remapped files
#   TMP_DIR       - Temporary directory for intermediate files
#   WEIGHT_FILE   - Path to remapping weight file
#   OUT_PREFIX    - Output filename prefix (default: MRMS_QPE_01H_Pass2_00.00)
#   DEFLATE_LEVEL - Compression level (default: 1)
#   CHUNK_TIME    - Chunk size for time dimension (default: 1)
#   CHUNK_HEIGHT  - Chunk size for height dimension (default: 33)
#   CHUNK_LAT     - Chunk size for y dimension (default: 256)
#   CHUNK_LON     - Chunk size for x dimension (default: 256)
#
# Examples:
#   # With full path:
#   ./remap_mrms_QPE_to_hrrr.sh /path/to/MRMS_MultiSensor_QPE_01H_Pass2_00.00_20250101-000000.nc
#
#   # With bare filename + IN_DIR:
#   export IN_DIR=/pscratch/sd/i/iclas2/meng/mrms/conus_2025_netcdf/MultiSensor_QPE_01H_Pass2_00.00
#   ./remap_mrms_QPE_to_hrrr.sh MRMS_MultiSensor_QPE_01H_Pass2_00.00_20250101-000000.nc
#
#   # Override output directory:
#   OUT_DIR=/my/output ./remap_mrms_QPE_to_hrrr.sh /path/to/file.nc

set -e

# ---------------------------------------------------------------------------
# Argument check
# ---------------------------------------------------------------------------
if [ $# -ne 1 ]; then
    echo "ERROR: Requires exactly 1 argument"
    echo "Usage: $0 <mrms_filepath_or_filename>"
    exit 1
fi

# ---------------------------------------------------------------------------
# Resolve input file — accept full path or bare filename
# ---------------------------------------------------------------------------
if [[ "$1" == /* ]]; then
    # Absolute path provided directly
    mrms_file="$1"
else
    # Bare filename — require IN_DIR
    IN_DIR="${IN_DIR:?ERROR: IN_DIR must be set when passing a bare filename}"
    mrms_file="${IN_DIR}/$1"
fi

if [ ! -f "$mrms_file" ]; then
    echo "ERROR: MRMS file not found: $mrms_file"
    exit 1
fi

# ---------------------------------------------------------------------------
# Configuration — environment variables with defaults
# ---------------------------------------------------------------------------
OUT_DIR="${OUT_DIR:-/pscratch/sd/i/iclas2/MRMS/remap_QPE1H_hrrr}"
TMP_DIR="${TMP_DIR:-/pscratch/sd/i/iclas2/MRMS/tmp}"
WEIGHT_FILE="${WEIGHT_FILE:-/pscratch/sd/w/wcmca1/SCREAMv1-cess2/maps/MRMS_to_HRRR_conserve.nc}"
OUT_PREFIX="${OUT_PREFIX:-MRMS_QPE_01H_Pass2_00.00}"
DEFLATE_LEVEL="${DEFLATE_LEVEL:-1}"
CHUNK_TIME="${CHUNK_TIME:-1}"
CHUNK_HEIGHT="${CHUNK_HEIGHT:-33}"
CHUNK_LAT="${CHUNK_LAT:-256}"
CHUNK_LON="${CHUNK_LON:-256}"

mkdir -p "$TMP_DIR" "$OUT_DIR"

# ---------------------------------------------------------------------------
# Validate weight file
# ---------------------------------------------------------------------------
if [ ! -f "$WEIGHT_FILE" ]; then
    echo "ERROR: Weight file not found: $WEIGHT_FILE"
    exit 1
fi

# ---------------------------------------------------------------------------
# Derive output filenames from input
# ---------------------------------------------------------------------------
mrms_basename=$(basename "$mrms_file")
timestamp=$(echo "$mrms_basename" | grep -oP '\d{8}-\d{6}')

if [ -z "$timestamp" ]; then
    echo "ERROR: Could not extract timestamp from filename: $mrms_basename"
    exit 1
fi

tmp_remap="${TMP_DIR}/tmp_remap_QPE_${timestamp}.nc"
out_file="${OUT_DIR}/${OUT_PREFIX}_${timestamp}.nc"

# Skip if output already exists
if [ -f "$out_file" ]; then
    echo "SKIP: Output already exists: $out_file"
    exit 0
fi

# ---------------------------------------------------------------------------
# Load environment
# ---------------------------------------------------------------------------
source /global/common/software/e3sm/anaconda_envs/load_latest_e3sm_unified_pm-cpu.sh

# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------
start_time=$(date +%s)

echo "========================================================================"
echo "MRMS to HRRR Remapping"
echo "========================================================================"
echo "  Input:      $mrms_file"
echo "  Weights:    $WEIGHT_FILE"
echo "  Output:     $out_file"
echo "  Tmp:        $tmp_remap"
echo "========================================================================"

# Step 1: Remap
echo ""
echo "Step 1: Remapping to HRRR grid..."
step1_start=$(date +%s)
ncremap --no_stdin --mss_val=-999 -m "$WEIGHT_FILE" "$mrms_file" "$tmp_remap"
step1_end=$(date +%s)
echo "  Done ($(( step1_end - step1_start ))s)"

# Step 2: Rename dimensions and compress
echo ""
echo "Step 2: Renaming dimensions and applying compression..."
step2_start=$(date +%s)
ncrename -d .latitude,y -d .longitude,x "$tmp_remap"
ncks -4 -L ${DEFLATE_LEVEL} -O \
    --cnk_dmn time,${CHUNK_TIME} \
    --cnk_dmn heightAboveSea,${CHUNK_HEIGHT} \
    --cnk_dmn y,${CHUNK_LAT} \
    --cnk_dmn x,${CHUNK_LON} \
    "$tmp_remap" "$out_file"
step2_end=$(date +%s)
echo "  Done ($(( step2_end - step2_start ))s): $out_file"

# Step 3: Cleanup
echo ""
echo "Step 3: Cleaning up..."
rm -f "$tmp_remap"
echo "  Removed: $tmp_remap"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
end_time=$(date +%s)
total_time=$(( end_time - start_time ))
echo ""
echo "========================================================================"
echo "Complete: $out_file"
echo "  Format:   netCDF4, deflate=${DEFLATE_LEVEL}"
echo "  Chunking: (${CHUNK_TIME}, ${CHUNK_HEIGHT}, ${CHUNK_LAT}, ${CHUNK_LON})"
echo "  Total:    ${total_time}s ($(printf '%d:%02d:%02d' \
    $((total_time/3600)) $((total_time%3600/60)) $((total_time%60))))"
echo "========================================================================"
echo ""
echo "Output file header:"
ncdump -h "$out_file" | head -60