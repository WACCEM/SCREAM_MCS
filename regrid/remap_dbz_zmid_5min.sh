#!/bin/bash
#
# Remap SCREAM reflectivity and geopotential height files, combine them, 
# and split into individual 5-minute timestep files
#
# Usage: ./remap_dbz_zmid_5min.sh <reflectivity_file> <geopotential_height_file>
#
# Example:
#   ./remap_dbz_zmid_5min.sh \
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

# Load CDO for time handling
echo "Loading CDO..."
module load climate-utils

# Start total timer
start_time=$(date +%s)

# Chunking and compression settings for netCDF4 output
# Optimized for column-wise operations (vertical max, echo-top) and horizontal gradients
chunk_time=1      # Chunk size for time dimension (1 = one timestep per chunk, 0 = no chunking)
chunk_lev=128     # Chunk size for lev dimension (128 = full dimension, optimal for column ops)
chunk_lat=256     # Chunk size for lat/y dimension (0 = no chunking)
chunk_lon=256     # Chunk size for lon/x dimension (0 = no chunking)
deflate_level=1   # Compression level (0 = no compression, 1-9 = compression level)

# Define weight files
map_neareststod='/pscratch/sd/w/wcmca1/SCREAMv1-cess2/maps/SCREAM_CONUS_ne1024_to_HRRR_neareststod.nc'
map_bilinear='/pscratch/sd/w/wcmca1/SCREAMv1-cess2/maps/SCREAM_CONUS_ne1024_to_HRRR_bilinear.nc'

# Output directories
tmp_dir='/pscratch/sd/w/wcmca1/SCREAMv1-cess2/remap_conus'
out_dir='/pscratch/sd/w/wcmca1/SCREAMv1-cess2/remap_conus_5min'
mkdir -p "$tmp_dir"
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

# Define temporary filenames
tmp_refl="${tmp_dir}/tmp_refl_${timestamp}.nc"
tmp_geop="${tmp_dir}/tmp_geop_${timestamp}.nc"
tmp_combined="${tmp_dir}/tmp_combined_${timestamp}.nc"
out_geop="${tmp_dir}/scream.z_mid_p_mid.5min.INSTANT.nmins_x5.${timestamp_hhmmss}.nc"

echo "========================================================================"
echo "SCREAM Remapping, Combining, and Splitting to 5-minute Files"
echo "========================================================================"
echo "Input files:"
echo "  Reflectivity:  $refl_file"
echo "  Geopotential:  $geop_file"
echo ""
echo "Weight files:"
echo "  Neareststod:   $map_neareststod"
echo "  Bilinear:      $map_bilinear"
echo ""
echo "Output directory: $out_dir"
echo "========================================================================"

# Step 1: Remap reflectivity using neareststod
echo ""
echo "Step 1: Remapping reflectivity with neareststod method..."
step1_start=$(date +%s)
# No compression for temporary file (faster writing)
ncremap -P eamxx --no_stdin -m "$map_neareststod" "$refl_file" "$tmp_refl"
# Rename dimensions and variables BEFORE combining to ensure consistency
ncrename -d .lat,y -d .lon,x "$tmp_refl"
ncrename -v .lat,latitude -v .lon,longitude "$tmp_refl"
step1_end=$(date +%s)
step1_time=$((step1_end - step1_start))
echo "  Done: $tmp_refl (temporary file, renamed, no compression for speed)"
echo "  Step 1 time: ${step1_time}s"

# Step 2: Remap geopotential height using bilinear
echo ""
echo "Step 2: Remapping geopotential height with bilinear method..."
step2_start=$(date +%s)
# Remap to temporary file
ncremap -P eamxx --no_stdin -m "$map_bilinear" "$geop_file" "$tmp_geop"
# Rename dimensions and variables BEFORE compression to avoid HDF5 errors
ncrename -d .lat,y -d .lon,x "$tmp_geop"
ncrename -v .lat,latitude -v .lon,longitude "$tmp_geop"
# Apply compression and save to final output (keeping both z_mid and p_mid)
ncks -4 -L ${deflate_level} -O \
    --cnk_dmn time,${chunk_time} --cnk_dmn lev,${chunk_lev} --cnk_dmn y,${chunk_lat} --cnk_dmn x,${chunk_lon} \
    "$tmp_geop" "$out_geop"
step2_end=$(date +%s)
step2_time=$((step2_end - step2_start))
echo "  Done: $out_geop (contains z_mid and p_mid, renamed, compressed)"
echo "  Step 2 time: ${step2_time}s"

# Step 3: Combine variables from both files (no compression yet)
echo ""
echo "Step 3: Combining diag_equiv_reflectivity and z_mid variables..."
step3_start=$(date +%s)
# Extract diag_equiv_reflectivity AND coordinate variables from reflectivity file (use it as base)
ncks -O -v diag_equiv_reflectivity,latitude,longitude "$tmp_refl" "$tmp_combined"
# Append only z_mid from geopotential height file (not p_mid)
ncks -A -v z_mid "$out_geop" "$tmp_combined"
step3_end=$(date +%s)
step3_time=$((step3_end - step3_start))
echo "  Done: $tmp_combined (temporary, uncompressed)"
echo "  Step 3 time: ${step3_time}s"

# Step 4: Split into individual 5-minute files with processing
echo ""
echo "Step 4: Splitting into individual 5-minute timestep files..."
step4_start=$(date +%s)

# Get number of time steps
ntimes=$(ncdump -h "$tmp_combined" | grep "time = " | grep -oP '\d+' | head -1)
echo "  Time steps: $ntimes"

# Use CDO to get full timestamps for each timestep
# showtimestamp returns YYYY-MM-DDTHH:MM:SS for each time
timestamps_raw=$(cdo -s showtimestamp "$tmp_combined" 2>/dev/null)

# Convert to array
IFS=' ' read -r -a timestamps <<< "$timestamps_raw"

echo "  Extracted ${#timestamps[@]} timestamps using CDO"

# Build chunking options
chunk_opts="--cnk_dmn time,1"
if [ $chunk_lev -gt 0 ]; then
    chunk_opts="$chunk_opts --cnk_dmn lev,$chunk_lev"
fi
if [ $chunk_lat -gt 0 ]; then
    chunk_opts="$chunk_opts --cnk_dmn y,$chunk_lat"
fi
if [ $chunk_lon -gt 0 ]; then
    chunk_opts="$chunk_opts --cnk_dmn x,$chunk_lon"
fi

# Process each time step
for (( itime=0; itime<ntimes; itime++ )); do
    # Get timestamp for this timestep (format: YYYY-MM-DDTHH:MM:SS)
    timestamp_iso="${timestamps[$itime]}"
    
    # Parse ISO format: YYYY-MM-DDTHH:MM:SS
    date_str="${timestamp_iso%%T*}"  # Everything before 'T'
    time_str="${timestamp_iso##*T}"  # Everything after 'T'
    
    # Convert time HH:MM:SS to HHMMSS (remove colons and round to nearest minute)
    IFS=':' read -r hours minutes seconds <<< "$time_str"
    # Round seconds to nearest minute
    # Force decimal interpretation with 10# prefix to avoid octal issues
    if [ "${seconds%%.*}" -ge 30 ]; then
        minutes=$((10#$minutes + 1))
        if [ $minutes -ge 60 ]; then
            minutes=0
            hours=$((10#$hours + 1))
            if [ $hours -ge 24 ]; then
                hours=0
                # Increment date by 1 day - use date command
                date_str=$(date -d "$date_str + 1 day" +%Y-%m-%d)
            fi
        fi
    fi
    hhmmss=$(printf "%02d%02d00" $((10#$hours)) $((10#$minutes)))
    
    # Create timestamp YYYY-MM-DD-HHMMSS
    timestamp_out="${date_str}-${hhmmss}"
    
    # Create output filename
    out_file="${out_dir}/scream.diag_equiv_reflectivity.5min.INSTANT.nmins_x5.${timestamp_out}.nc"
    
    # Create temporary file for this timestep
    tmp_timestep="${tmp_dir}/tmp_timestep_${timestamp_out}.nc"
    
    # Extract this time step and apply processing in one step
    # Remove unwanted variables AND apply netCDF4, compression, and chunking
    # -C flag allows excluding coordinate variables, . prefix makes variables optional
    # Dimensions/variables already renamed in Steps 1&2, no need to rename again
    ncks -4 -L ${deflate_level} -O -C -x -v .ilev,.lat_bnds,.lon_bnds \
        -d time,${itime},${itime} \
        $chunk_opts \
        "$tmp_combined" "$out_file"
    
    if [ $((itime % 4)) -eq 0 ] || [ $itime -eq $((ntimes - 1)) ]; then
        echo "    Timestep ${itime}/${ntimes}: $timestamp_out"
    fi
done

step4_end=$(date +%s)
step4_time=$((step4_end - step4_start))
echo "  Created ${ntimes} individual 5-minute files"
echo "  Applied: dimension/variable renaming, removed ilev/lat_bnds/lon_bnds"
echo "  Applied: netCDF4 format, deflate level ${deflate_level}, chunking (1,${chunk_lev},${chunk_lat},${chunk_lon})"
echo "  Step 4 time: ${step4_time}s"

# Step 5: Clean up temporary files
echo ""
echo "Step 5: Cleaning up temporary files..."
step5_start=$(date +%s)
rm -f "$tmp_refl" "$tmp_geop" "$tmp_combined"
step5_end=$(date +%s)
step5_time=$((step5_end - step5_start))
echo "  Removed: $tmp_refl"
echo "  Removed: $tmp_geop"
echo "  Removed: $tmp_combined"
echo "  Kept: $out_geop (contains z_mid and p_mid)"
echo "  Step 5 time: ${step5_time}s"

# Calculate total time
end_time=$(date +%s)
total_time=$((end_time - start_time))

echo ""
echo "========================================================================"
echo "Processing completed successfully!"
echo "========================================================================"
echo "Created ${ntimes} output files in: $out_dir"
echo "  Variables: diag_equiv_reflectivity (neareststod), z_mid (bilinear)"
echo "  Format: scream.diag_equiv_reflectivity.5min.INSTANT.nmins_x5.YYYY-MM-DD-HHMMSS.nc"
echo "========================================================================"
echo "Total processing time: ${total_time}s ($(printf '%d:%02d:%02d' $((total_time/3600)) $((total_time%3600/60)) $((total_time%60))))"
echo "========================================================================"

# # Show sample output files
# echo ""
# echo "Sample output files (first 3):"
# ls -lh "$out_dir"/scream.diag_equiv_reflectivity.5min.*.nc | head -3

# echo ""
# echo "Sample file header:"
# first_output=$(ls "$out_dir"/scream.diag_equiv_reflectivity.5min.*.nc | tail -1)
# ncdump -h "$first_output" | head -40
