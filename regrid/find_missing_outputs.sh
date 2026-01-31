#!/bin/bash
#
# Find input files from a tasklist that have incomplete output
# Updated for remap_dbz_zmid_5min.sh workflow
#
# Usage: ./find_missing_outputs.sh <tasklist.txt>
#

if [ $# -ne 1 ]; then
    echo "ERROR: Requires exactly 1 argument"
    echo "Usage: $0 <tasklist.txt>"
    exit 1
fi

tasklist="$1"

if [ ! -f "$tasklist" ]; then
    echo "ERROR: Tasklist file not found: $tasklist"
    exit 1
fi

in_dir='/pscratch/sd/w/wcmca1/SCREAMv1-cess2/run_conus'
out_dir='/pscratch/sd/w/wcmca1/SCREAMv1-cess2/remap_conus_5min'
missing_list="${tasklist%.txt}_missing.txt"

# Load CDO for timestamp extraction
module load climate-utils

echo "Checking for missing output files from tasklist..."
echo "Tasklist: $tasklist"
echo "Output directory: $out_dir"
echo ""

# Clear the missing list
> "$missing_list"

# Counter
total_input=0
incomplete_input=0
total_missing=0

# Read each line from the tasklist
while IFS= read -r line; do
    # Skip empty lines or comments
    [[ -z "$line" || "$line" =~ ^# ]] && continue
    
    # Extract the reflectivity filename from the tasklist line
    # Format: /path/to/script refl_file.nc zmid_file.nc
    refl_file=$(echo "$line" | awk '{print $2}')
    
    # Build full path
    if [[ "$refl_file" =~ ^/ ]]; then
        # Already absolute path
        input_file="$refl_file"
    else
        # Relative filename, prepend input directory
        input_file="${in_dir}/${refl_file}"
    fi
    
    if [ ! -f "$input_file" ]; then
        echo "WARNING: Input file not found: $input_file"
        continue
    fi
    
    total_input=$((total_input + 1))
    filename=$(basename "$input_file")
    
    # Get timestamps for this file
    timestamps_raw=$(cdo -s showtimestamp "$input_file" 2>/dev/null)
    IFS=' ' read -r -a timestamps <<< "$timestamps_raw"
    
    ntimes=${#timestamps[@]}
    missing_count=0
    
    # Check if all output files exist for this input
    for (( i=0; i<ntimes; i++ )); do
        timestamp_iso="${timestamps[$i]}"
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
        timestamp="${date_str}-${hhmmss}"
        
        expected_output="$out_dir/scream.diag_equiv_reflectivity.5min.INSTANT.nmins_x5.${timestamp}.nc"
        
        if [ ! -f "$expected_output" ]; then
            missing_count=$((missing_count + 1))
        fi
    done
    
    # If any outputs are missing, add the original tasklist line
    if [ $missing_count -gt 0 ]; then
        echo "$line" >> "$missing_list"
        incomplete_input=$((incomplete_input + 1))
        total_missing=$((total_missing + missing_count))
        echo "Missing $missing_count/$ntimes outputs from: $filename"
    fi
done < "$tasklist"

echo ""
echo "========================================================================"
echo "Summary:"
echo "  Total input files checked: $total_input"
echo "  Input files with missing outputs: $incomplete_input"
echo "  Total missing output files: $total_missing (expected: $((total_input * 12)))"
echo "  Missing tasklist saved to: $missing_list"
echo "========================================================================"

if [ $incomplete_input -gt 0 ]; then
    echo ""
    echo "To reprocess the missing files, run:"
    echo "  module load taskfarmer"
    echo "  export OMP_NUM_THREADS=1"
    echo "  runcommands.sh $missing_list"
    echo ""
    echo "Or with GNU parallel:"
    echo "  parallel -j 16 < $missing_list"
fi
