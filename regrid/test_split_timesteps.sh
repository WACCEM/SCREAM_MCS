#!/bin/bash
#
# Test script to split SCREAM reflectivity files into individual time snapshots
# Uses actual time variable values to compute output filenames
#
# Usage: ./test_split_timesteps.sh [input_file]
# If no input file specified, processes all scream.diag_equiv_reflectivity.5min.*.nc files

set -e  # Exit on error

# Configuration
in_dir='/pscratch/sd/w/wcmca1/SCREAMv1-cess2/remap_conus'
out_dir='/pscratch/sd/w/wcmca1/SCREAMv1-cess2/remap_conus_5min'
mkdir -p "$out_dir"

# Compression settings (matching remap_dbz_zmid.sh)
chunk_lev=128
chunk_lat=256
chunk_lon=256
deflate_level=1

# Load required environment
echo "Loading E3SM environment..."
source /global/common/software/e3sm/anaconda_envs/load_latest_e3sm_unified_pm-cpu.sh

# Load CDO for time handling
echo "Loading CDO..."
module load climate-utils

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

echo "========================================================================"
echo "SCREAM Time Splitting Test"
echo "========================================================================"
echo "Input directory:  $in_dir"
echo "Output directory: $out_dir"
echo "Compression: deflate_level=${deflate_level}, chunking=(1,${chunk_lev},${chunk_lat},${chunk_lon})"
echo "========================================================================"
echo ""

# Process files
if [ $# -eq 1 ]; then
    # Process single file specified as argument
    input_files=("$1")
    if [ ! -f "$1" ]; then
        echo "ERROR: File not found: $1"
        exit 1
    fi
else
    # Process all matching files
    input_files=("$in_dir"/scream.diag_equiv_reflectivity.5min.*.nc)
fi

total_files=${#input_files[@]}
echo "Found ${total_files} file(s) to process"
echo ""

start_total=$(date +%s)
total_timesteps=0

for input_file in "${input_files[@]}"; do
    filename=$(basename "$input_file")
    echo "----------------------------------------------------------------------"
    echo "Processing: $filename"
    start_file=$(date +%s)
    
    # Get number of time steps
    ntimes=$(ncdump -h "$input_file" | grep "time = " | grep -oP '\d+' | head -1)
    echo "  Time steps: $ntimes"
    
    # Use CDO to get full timestamps for each timestep
    # showtimestamp returns YYYY-MM-DDTHH:MM:SS for each time
    timestamps_raw=$(cdo -s showtimestamp "$input_file" 2>/dev/null)
    
    # Convert to array
    IFS=' ' read -r -a timestamps <<< "$timestamps_raw"
    
    echo "  Extracted ${#timestamps[@]} timestamps using CDO"
    
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
        timestamp="${date_str}-${hhmmss}"
        
        # Create output filename
        out_file="${out_dir}/scream.diag_equiv_reflectivity.5min.INSTANT.nmins_x5.${timestamp}.nc"
        
        # Extract this time step with compression and chunking in one step
        ncks -4 -L ${deflate_level} -O \
            $chunk_opts \
            -d time,${itime},${itime} \
            "$input_file" "$out_file"
        
        if [ $((itime % 4)) -eq 0 ] || [ $itime -eq $((ntimes - 1)) ]; then
            echo "    Timestep ${itime}/${ntimes}: $timestamp"
        fi
        
        total_timesteps=$((total_timesteps + 1))
    done
    
    end_file=$(date +%s)
    elapsed_file=$((end_file - start_file))
    echo "  File processing time: ${elapsed_file}s"
    echo ""
done

end_total=$(date +%s)
elapsed_total=$((end_total - start_total))

echo "========================================================================"
echo "Processing Complete"
echo "========================================================================"
echo "Processed ${total_files} file(s), split into ${total_timesteps} timestep files"
echo "Output directory: $out_dir"
# Format total time as HH:MM:SS
hours=$((elapsed_total / 3600))
minutes=$(((elapsed_total % 3600) / 60))
seconds=$((elapsed_total % 60))
echo "Total time: ${elapsed_total}s (${hours}:$(printf '%02d' $minutes):$(printf '%02d' $seconds))"
echo "========================================================================"

# Show sample output
echo ""
echo "Sample output files (first 5):"
ls -lh "$out_dir"/scream.diag_equiv_reflectivity.5min.*.nc | head -5

echo ""
echo "Sample file header:"
first_output=$(ls "$out_dir"/scream.diag_equiv_reflectivity.5min.*.nc | head -1)
ncdump -h "$first_output" | head -40
