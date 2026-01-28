#!/bin/bash
#
# Remap SCREAM reflectivity and geopotential height files and combine them
#
# Usage: ./remap_and_combine.sh <reflectivity_file> <geopotential_height_file>
#
# Example:
#   ./remap_and_combine.sh \
#     output.scream.diag_equiv_reflectivity.5min.INSTANT.nmins_x5.2020-06-06-79500.nc \
#     output.scream.z_mid_p_mid.5min.INSTANT.nmins_x5.2020-06-07-00300.nc

set -e  # Exit on error

# Check for required arguments
if [ $# -ne 2 ]; then
    echo "ERROR: Requires exactly 2 arguments"
    echo "Usage: $0 <reflectivity_filename> <geopotential_height_filename>"
    exit 1
fi

# Input directory
in_dir='/pscratch/sd/w/wcmca1/SCREAMv1-cess2/run_conus/'

# Input files (just filenames, prepend directory)
refl_file="${in_dir}$1"
geop_file="${in_dir}$2"

# Check if input files exist
if [ ! -f "$refl_file" ]; then
    echo "ERROR: Reflectivity file not found: $refl_file"
    exit 1
fi

if [ ! -f "$geop_file" ]; then
    echo "ERROR: Geopotential height file not found: $geop_file"
    exit 1
fi

# Load required environment
echo "Loading E3SM environment..."
source /global/common/software/e3sm/anaconda_envs/load_latest_e3sm_unified_pm-cpu.sh

# Start total timer
start_time=$(date +%s)

# Chunking and compression settings for netCDF4 output
# Optimized for column-wise operations (vertical max, echo-top) and horizontal gradients
chunk_time=1      # Chunk size for time dimension (1 = one timestep per chunk, 0 = no chunking)
chunk_lev=128     # Chunk size for lev dimension (128 = full dimension, optimal for column ops)
chunk_lat=256     # Chunk size for lat/y dimension (0 = no chunking)
chunk_lon=256     # Chunk size for lon/x dimension (0 = no chunking)
deflate_level=1   # Compression level (0 = no compression, 1-9 = compression level)
# Note: To test with no chunking/compression, set deflate_level=0, chunk_time=0, chunk_lat=0, chunk_lon=0

# Define weight files
map_neareststod='/pscratch/sd/w/wcmca1/SCREAMv1-cess2/maps/SCREAM_CONUS_ne1024_to_HRRR_neareststod.nc'
map_bilinear='/pscratch/sd/w/wcmca1/SCREAMv1-cess2/maps/SCREAM_CONUS_ne1024_to_HRRR_bilinear.nc'

# Output directory
out_dir='/pscratch/sd/w/wcmca1/SCREAMv1-cess2/remap_conus'
mkdir -p "$out_dir"

# Extract base filename from reflectivity file for output naming
refl_basename=$(basename "$refl_file")
# Extract date and seconds portion (e.g., "2020-06-06-79500")
timestamp=$(echo "$refl_basename" | grep -oP '\d{4}-\d{2}-\d{2}-\d+')
# Extract date (YYYY-MM-DD) and seconds separately
date_part=$(echo "$timestamp" | grep -oP '\d{4}-\d{2}-\d{2}')
seconds_part=$(echo "$timestamp" | grep -oP '\d+$')
# Convert seconds to HHMMSS format
hours=$((seconds_part / 3600))
minutes=$(((seconds_part % 3600) / 60))
secs=$((seconds_part % 60))
hhmmss=$(printf "%02d%02d%02d" $hours $minutes $secs)
# Create new timestamp with HHMMSS format
timestamp_hhmmss="${date_part}-${hhmmss}"

# Define output filenames
tmp_refl="${out_dir}/tmp_refl_${timestamp}.nc"
tmp_geop="${out_dir}/tmp_geop_${timestamp}.nc"
out_geop="${out_dir}/scream.z_mid_p_mid.5min.INSTANT.nmins_x5.${timestamp_hhmmss}.nc"
out_combined="${out_dir}/scream.diag_equiv_reflectivity.5min.INSTANT.nmins_x5.${timestamp_hhmmss}.nc"

echo "========================================================================"
echo "SCREAM Remapping and Combining"
echo "========================================================================"
echo "Input files:"
echo "  Reflectivity:  $refl_file"
echo "  Geopotential:  $geop_file"
echo ""
echo "Weight files:"
echo "  Neareststod:   $map_neareststod"
echo "  Bilinear:      $map_bilinear"
echo ""
echo "Output files:"
echo "  Temp refl:     $tmp_refl"
echo "  Geopotential:  $out_geop"
echo "  Combined:      $out_combined"
echo "========================================================================"

# Step 1: Remap reflectivity using neareststod
echo ""
echo "Step 1: Remapping reflectivity with neareststod method..."
step1_start=$(date +%s)
# No compression for temporary file (faster writing)
ncremap -P eamxx --no_stdin -m "$map_neareststod" "$refl_file" "$tmp_refl"
step1_end=$(date +%s)
step1_time=$((step1_end - step1_start))
echo "  Done: $tmp_refl (temporary file, no compression for speed)"
echo "  Step 1 time: ${step1_time}s"

# Step 2: Remap geopotential height using bilinear
echo ""
echo "Step 2: Remapping geopotential height with bilinear method..."
step2_start=$(date +%s)
# Remap to temporary file
tmp_geop="${out_dir}/tmp_geop_${timestamp}.nc"
ncremap -P eamxx --no_stdin -m "$map_bilinear" "$geop_file" "$tmp_geop"
# Apply compression and save to final output (keeping both z_mid and p_mid)
ncks -4 -L ${deflate_level} -O \
    --cnk_dmn time,${chunk_time} --cnk_dmn lev,${chunk_lev} --cnk_dmn lat,${chunk_lat} --cnk_dmn lon,${chunk_lon} \
    "$tmp_geop" "$out_geop"
step2_end=$(date +%s)
step2_time=$((step2_end - step2_start))
echo "  Done: $out_geop (contains z_mid and p_mid, compressed)"
echo "  Step 2 time: ${step2_time}s"

# Step 3: Combine variables from both files (no compression yet)
echo ""
echo "Step 3: Combining diag_equiv_reflectivity and z_mid variables..."
step3_start=$(date +%s)
# Extract diag_equiv_reflectivity from reflectivity file (use it as base)
ncks -O -v diag_equiv_reflectivity "$tmp_refl" "$out_combined"
# Append only z_mid from geopotential height file (not p_mid)
ncks -A -v z_mid "$out_geop" "$out_combined"
step3_end=$(date +%s)
step3_time=$((step3_end - step3_start))
echo "  Done: $out_combined (temporary, uncompressed)"
echo "  Step 3 time: ${step3_time}s"

# Step 4: Rename, remove unwanted variables, and apply compression/chunking
echo ""
echo "Step 4: Renaming variables/dimensions, removing unwanted variables, and applying compression..."
step4_start=$(date +%s)
# Rename dimensions: lat -> y, lon -> x (optional if already renamed)
ncrename -d .lat,y -d .lon,x "$out_combined"
# Rename variables: lat -> latitude, lon -> longitude (optional if already renamed)
ncrename -v .lat,latitude -v .lon,longitude "$out_combined"
# Remove unwanted variables AND apply netCDF4, compression, and chunking in one operation
# -C flag allows excluding coordinate variables, . prefix makes variables optional
# Build chunking options conditionally
chunk_opts=""
if [ $chunk_time -gt 0 ]; then
    chunk_opts="$chunk_opts --cnk_dmn time,$chunk_time"
fi
if [ $chunk_lev -gt 0 ] && [ $chunk_lev -lt 128 ]; then
    chunk_opts="$chunk_opts --cnk_dmn lev,$chunk_lev"
fi
if [ $chunk_lat -gt 0 ]; then
    chunk_opts="$chunk_opts --cnk_dmn y,$chunk_lat"
fi
if [ $chunk_lon -gt 0 ]; then
    chunk_opts="$chunk_opts --cnk_dmn x,$chunk_lon"
fi
ncks -4 -L ${deflate_level} -O -C -x -v .ilev,.lat_bnds,.lon_bnds $chunk_opts \
    "$out_combined" "$out_combined"
step4_end=$(date +%s)
step4_time=$((step4_end - step4_start))
echo "  Renamed: lat->y, lon->x (dims); lat->latitude, lon->longitude (vars)"
echo "  Removed: ilev, lat_bnds, lon_bnds (if present)"
echo "  Applied: netCDF4 format, deflate level ${deflate_level}, chunking (${chunk_time},${chunk_lev},${chunk_lat},${chunk_lon})"
echo "  Step 4 time: ${step4_time}s"

# Step 5: Clean up temporary files
echo ""
echo "Step 5: Cleaning up temporary files..."
step5_start=$(date +%s)
rm -f "$tmp_refl" "$tmp_geop"
step5_end=$(date +%s)
step5_time=$((step5_end - step5_start))
echo "  Removed: $tmp_refl"
echo "  Removed: $tmp_geop"
echo "  Kept: $out_geop (contains z_mid and p_mid)"
echo "  Step 5 time: ${step5_time}s"

# Calculate total time
end_time=$(date +%s)
total_time=$((end_time - start_time))

echo ""
echo "========================================================================"
echo "Processing completed successfully!"
echo "========================================================================"
echo "Output file: $out_combined"
echo "  Variables: diag_equiv_reflectivity (neareststod), z_mid (bilinear)"
echo "========================================================================"
echo "Total processing time: ${total_time}s ($(printf '%d:%02d:%02d' $((total_time/3600)) $((total_time%3600/60)) $((total_time%60))))"
echo "========================================================================"

# Print file info
echo ""
echo "Output file information:"
ncdump -h "$out_combined" | head -50
