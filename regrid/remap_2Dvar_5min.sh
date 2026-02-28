#!/bin/bash
#
# Remap a single SCREAM 2D file to the HRRR grid using conservative remapping,
# rename dimensions/variables, apply chunking and compression,
# and split into individual 5-minute timestep files
#
# Usage: ./remap_2Dvar_5min.sh <2D_file>
#
# Example:
#   ./remap_2Dvar_5min.sh \
#     output.scream.2D.5min.INSTANT.nmins_x5.2020-04-02-07500.nc

set -e  # Exit on error

# Check for required arguments
if [ $# -ne 1 ]; then
    echo "ERROR: Requires exactly 1 argument"
    echo "Usage: $0 <2D_filename>"
    exit 1
fi

# Input directory
in_dir='/pscratch/sd/w/wcmca1/SCREAMv1-cess2/run_conus/'

# Input file (just filename, prepend directory)
in_file="${in_dir}$1"

# Check if input file exists
if [ ! -f "$in_file" ]; then
    echo "ERROR: Input file not found: $in_file"
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
# Optimized for 2D (no vertical dimension)
chunk_time=1      # Chunk size for time dimension (1 = one timestep per chunk)
chunk_lat=256     # Chunk size for lat/y dimension
chunk_lon=256     # Chunk size for lon/x dimension
deflate_level=1   # Compression level (0 = no compression, 1-9 = compression level)

# Conservative remap weight file
map_conserve='/pscratch/sd/w/wcmca1/SCREAMv1-cess2/maps/SCREAM_CONUS_ne1024_to_HRRR_conserve.nc'

# Output directories
tmp_dir='/pscratch/sd/w/wcmca1/SCREAMv1-cess2/remap_conus'
out_dir='/pscratch/sd/w/wcmca1/SCREAMv1-cess2/remap_conus_2D_5min'
mkdir -p "$tmp_dir"
mkdir -p "$out_dir"

# Extract base filename for output naming
in_basename=$(basename "$in_file")
# Extract date and seconds portion (e.g., "2020-04-02-07500")
timestamp=$(echo "$in_basename" | grep -oP '\d{4}-\d{2}-\d{2}-\d+')
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

# Define temporary filename
tmp_remapped="${tmp_dir}/tmp_2D_${timestamp}.nc"

echo "========================================================================"
echo "SCREAM 2D Remapping and Splitting to 5-minute Files"
echo "========================================================================"
echo "Input file:       $in_file"
echo ""
echo "Weight file:"
echo "  Conservative:   $map_conserve"
echo ""
echo "Output directory: $out_dir"
echo "========================================================================"

# Step 1: Remap 2D file using conservative method
echo ""
echo "Step 1: Remapping 2D variables with conservative method..."
step1_start=$(date +%s)
# Remap to temporary file (no compression for speed)
ncremap -P eamxx --no_stdin -m "$map_conserve" "$in_file" "$tmp_remapped"
# Rename dimensions and variables for consistency
ncrename -d .lat,y -d .lon,x "$tmp_remapped"
ncrename -v .lat,latitude -v .lon,longitude "$tmp_remapped"

# Mask destination cells with no source coverage.
# ESMF_RegridWeightGen has no option for this — masking must be applied here.
# frac_b in the weight file records coverage fraction per destination cell (0=no coverage).
# Zero-coverage cells receive 0 from the sparse matrix multiply in ncremap regardless
# of --rnr_thr, so we must mask them explicitly using frac_b from the map file.
echo "  Masking zero-coverage cells using frac_b from map file..."
ny=$(ncdump -h "$tmp_remapped" | grep -oP '(?<=\ty = )\d+')
nx=$(ncdump -h "$tmp_remapped" | grep -oP '(?<=\tx = )\d+')
e3sm_python='/global/common/software/e3sm/anaconda_envs/e3smu_1_12_0/pm-cpu/conda/envs/e3sm_unified_1.12.0_login/bin/python'
tmp_mask="${tmp_dir}/tmp_mask_${timestamp}.nc"
"$e3sm_python" - "$map_conserve" "$tmp_mask" "$ny" "$nx" <<'PYEOF'
import sys
import netCDF4 as nc
import numpy as np
map_file, tmp_mask, ny, nx = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
with nc.Dataset(map_file) as ds:
    frac_b = ds['frac_b'][:]
frac_2d = frac_b.reshape(ny, nx)
with nc.Dataset(tmp_mask, 'w') as ds:
    ds.createDimension('y', ny)
    ds.createDimension('x', nx)
    v = ds.createVariable('frac_2d', 'f4', ('y', 'x'))
    v[:] = frac_2d.astype(np.float32)
PYEOF
ncks -A -v frac_2d "$tmp_mask" "$tmp_remapped"
rm -f "$tmp_mask"
# Build mask expression for all variables with y and x dimensions
vars_to_mask=$(ncdump -h "$tmp_remapped" | grep -P '^\s+\w+ \w+\(' | grep '\by\b' | grep '\bx\b' | grep -vP 'frac_2d|latitude|longitude' | grep -oP '(?<=\s)\w+(?=\()' | tr '\n' ' ')
mask_expr=""
for var in $vars_to_mask; do
    mask_expr="${mask_expr}where(frac_2d==0.0){${var}=${var}.get_miss();}; "
done
if [ -n "$mask_expr" ]; then
    ncap2 -O -s "$mask_expr" "$tmp_remapped" "$tmp_remapped"
fi
# Remove frac_2d — not needed in output
ncks -O -x -v frac_2d "$tmp_remapped" "$tmp_remapped"
step1_end=$(date +%s)
step1_time=$((step1_end - step1_start))
echo "  Done: $tmp_remapped (zero-coverage cells set to _FillValue)"
echo "  Step 1 time: ${step1_time}s"

# Step 2: Split into individual 5-minute files with processing
echo ""
echo "Step 2: Splitting into individual 5-minute timestep files..."
step2_start=$(date +%s)

# Get number of time steps
ntimes=$(ncdump -h "$tmp_remapped" | grep "time = " | grep -oP '\d+' | head -1)
echo "  Time steps: $ntimes"

# Use CDO to get full timestamps for each timestep
timestamps_raw=$(cdo -s showtimestamp "$tmp_remapped" 2>/dev/null)
IFS=' ' read -r -a timestamps <<< "$timestamps_raw"
echo "  Extracted ${#timestamps[@]} timestamps using CDO"

# Build chunking options (no lev dimension for 2D data)
chunk_opts="--cnk_dmn time,1"
if [ $chunk_lat -gt 0 ]; then
    chunk_opts="$chunk_opts --cnk_dmn y,$chunk_lat"
fi
if [ $chunk_lon -gt 0 ]; then
    chunk_opts="$chunk_opts --cnk_dmn x,$chunk_lon"
fi

# Process each time step
for (( itime=0; itime<ntimes; itime++ )); do
    timestamp_iso="${timestamps[$itime]}"
    date_str="${timestamp_iso%%T*}"
    time_str="${timestamp_iso##*T}"
    IFS=':' read -r hours minutes seconds <<< "$time_str"
    if [ "${seconds%%.*}" -ge 30 ]; then
        minutes=$((10#$minutes + 1))
        if [ $minutes -ge 60 ]; then
            minutes=0
            hours=$((10#$hours + 1))
            if [ $hours -ge 24 ]; then
                hours=0
                date_str=$(date -d "$date_str + 1 day" +%Y-%m-%d)
            fi
        fi
    fi
    hhmmss=$(printf "%02d%02d00" $((10#$hours)) $((10#$minutes)))
    timestamp_out="${date_str}-${hhmmss}"
    out_file="${out_dir}/scream.2D.5min.INSTANT.nmins_x5.${timestamp_out}.nc"

    ncks -4 -L ${deflate_level} -O -C -x -v .lat_bnds,.lon_bnds \
        -d time,${itime},${itime} \
        $chunk_opts \
        "$tmp_remapped" "$out_file"

    if [ $((itime % 4)) -eq 0 ] || [ $itime -eq $((ntimes - 1)) ]; then
        echo "    Timestep ${itime}/${ntimes}: $timestamp_out"
    fi
done

step2_end=$(date +%s)
step2_time=$((step2_end - step2_start))
echo "  Created ${ntimes} individual 5-minute files"
echo "  Applied: netCDF4 format, deflate level ${deflate_level}, chunking (1,${chunk_lat},${chunk_lon})"
echo "  Step 2 time: ${step2_time}s"

# Step 3: Clean up temporary files
echo ""
echo "Step 3: Cleaning up temporary files..."
step3_start=$(date +%s)
rm -f "$tmp_remapped"
step3_end=$(date +%s)
step3_time=$((step3_end - step3_start))
echo "  Removed: $tmp_remapped"
echo "  Step 3 time: ${step3_time}s"

# Calculate total time
end_time=$(date +%s)
total_time=$((end_time - start_time))

echo ""
echo "========================================================================"
echo "Processing completed successfully!"
echo "========================================================================"
echo "Created ${ntimes} output files in: $out_dir"
echo "  Variables: all 2D variables (conservative remap, unmapped→_FillValue)"
echo "  Format: scream.2D.5min.INSTANT.nmins_x5.YYYY-MM-DD-HHMMSS.nc"
echo "========================================================================"
echo "Total processing time: ${total_time}s ($(printf '%d:%02d:%02d' $((total_time/3600)) $((total_time%3600/60)) $((total_time%60))))"
echo "========================================================================"
