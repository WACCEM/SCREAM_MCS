#!/bin/bash
#
# Remap MRMS 3D reflectivity data to HRRR grid using conservative remapping
#
# Usage: ./remap_mrms_to_hrrr.sh <mrms_file>
#
# Example:
#   ./remap_mrms_to_hrrr.sh MRMS_MergedReflectivityQC_L33_20250930-223040.nc

set -e  # Exit on error

# Check for required arguments
if [ $# -ne 1 ]; then
    echo "ERROR: Requires exactly 1 argument"
    echo "Usage: $0 <mrms_filename>"
    exit 1
fi

# Input directory
in_dir='/global/cfs/cdirs/m1657/meng/share/mrms/'

# Input file (just filename, prepend directory)
mrms_file="${in_dir}$1"

# Check if input file exists
if [ ! -f "$mrms_file" ]; then
    echo "ERROR: MRMS file not found: $mrms_file"
    exit 1
fi

# Load required environment
echo "Loading E3SM environment..."
source /global/common/software/e3sm/anaconda_envs/load_latest_e3sm_unified_pm-cpu.sh

# Start total timer
start_time=$(date +%s)

# Chunking and compression settings for netCDF4 output
# Optimized for 3D reflectivity data (time, height, y, x)
chunk_time=1          # Chunk size for time dimension (1 = one timestep per chunk)
chunk_height=33       # Chunk size for heightAboveSea dimension (33 = full dimension)
chunk_lat=256         # Chunk size for lat/y dimension (256 for HRRR grid)
chunk_lon=256         # Chunk size for lon/x dimension (256 for HRRR grid)
deflate_level=1       # Compression level (1 = fast compression)

# Define weight file
map_conserve='/pscratch/sd/w/wcmca1/SCREAMv1-cess2/maps/MRMS_to_HRRR_conserve.nc'

# Output directories
tmp_dir='/pscratch/sd/i/iclas2/MRMS/tmp'
out_dir='/pscratch/sd/i/iclas2/MRMS/remap_hrrr'
mkdir -p "$tmp_dir"
mkdir -p "$out_dir"

# Extract base filename for output naming
mrms_basename=$(basename "$mrms_file")
# Extract date-time portion (e.g., "20250930-223040")
timestamp=$(echo "$mrms_basename" | grep -oP '\d{8}-\d{6}')

# Define temporary and output filenames
tmp_remap="${tmp_dir}/tmp_remap_${timestamp}.nc"
out_file="${out_dir}/MRMS_Reflectivity_HRRR_${timestamp}.nc"

echo "========================================================================"
echo "MRMS to HRRR Remapping"
echo "========================================================================"
echo "Input file:"
echo "  MRMS:          $mrms_file"
echo ""
echo "Weight file:"
echo "  Conservative:  $map_conserve"
echo ""
echo "Output directory: $out_dir"
echo "========================================================================"

# Step 1: Remap MRMS reflectivity to HRRR grid using conservative method
echo ""
echo "Step 1: Remapping MRMS reflectivity to HRRR grid..."
step1_start=$(date +%s)
# No compression for temporary file (faster writing)
ncremap --no_stdin --mss_val=-999 -m "$map_conserve" "$mrms_file" "$tmp_remap"
step1_end=$(date +%s)
step1_time=$((step1_end - step1_start))
echo "  Done: $tmp_remap (temporary file, no compression)"
echo "  Step 1 time: ${step1_time}s"

# Step 2: Rename dimensions, variable, and apply compression
echo ""
echo "Step 2: Renaming dimensions, variable, and applying compression..."
step2_start=$(date +%s)
# Rename dimensions from lat/lon to y/x
ncrename -d .latitude,y -d .longitude,x "$tmp_remap"
# Rename variable "unknown" to "Reflectivity"
# ncrename -v unknown,Reflectivity "$tmp_remap"
# Apply compression with chunking optimized for 3D data
ncks -4 -L ${deflate_level} -O \
    --cnk_dmn time,${chunk_time} --cnk_dmn heightAboveSea,${chunk_height} \
    --cnk_dmn y,${chunk_lat} --cnk_dmn x,${chunk_lon} \
    "$tmp_remap" "$out_file"
step2_end=$(date +%s)
step2_time=$((step2_end - step2_start))
echo "  Done: $out_file (variable renamed, compressed)"
echo "  Step 2 time: ${step2_time}s"

# Step 3: Clean up temporary files
echo ""
echo "Step 3: Cleaning up temporary files..."
step3_start=$(date +%s)
rm -f "$tmp_remap"
step3_end=$(date +%s)
step3_time=$((step3_end - step3_start))
echo "  Removed: $tmp_remap"
echo "  Step 3 time: ${step3_time}s"

# Calculate total time
end_time=$(date +%s)
total_time=$((end_time - start_time))

echo ""
echo "========================================================================"
echo "Processing completed successfully!"
echo "========================================================================"
echo "Output file: $out_file"
echo "  Variable: Reflectivity (conservative remapping)"
echo "  Format: netCDF4 with compression (deflate_level=${deflate_level})"
echo "  Chunking: (${chunk_time}, ${chunk_height}, ${chunk_lat}, ${chunk_lon})"
echo "========================================================================"
echo "Total processing time: ${total_time}s ($(printf '%d:%02d:%02d' $((total_time/3600)) $((total_time%3600/60)) $((total_time%60))))"
echo "========================================================================"

# Show output file info
echo ""
echo "Output file header:"
ncdump -h "$out_file" | head -60
