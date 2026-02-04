#!/bin/bash
#
# Add latitude and longitude coordinate variables to processed reflectivity+z_mid files
# Uses coordinates from HRRR map file
#
# Usage: ./add_latlon_to_files.sh [-j JOBS] [output_directory]
#
#   -j JOBS    Number of parallel jobs (default: 1 for serial)
#              Recommended: 32 on login node, 64-128 on interactive node
#

# Parse arguments
jobs=1
while getopts "j:" opt; do
    case $opt in
        j) jobs=$OPTARG ;;
        *) echo "Usage: $0 [-j JOBS] [output_directory]"; exit 1 ;;
    esac
done
shift $((OPTIND-1))

# Default output directory
out_dir="${1:-/pscratch/sd/w/wcmca1/SCREAMv1-cess2/remap_conus_5min}"

# Source file for latitude/longitude coordinates
coord_file="/pscratch/sd/w/wcmca1/SCREAMv1-cess2/maps/hrrr_sfc_latlon_orog_lsm.nc"

# Check if coordinate file exists
if [ ! -f "$coord_file" ]; then
    echo "ERROR: Coordinate file not found: $coord_file"
    exit 1
fi

# Check if output directory exists
if [ ! -d "$out_dir" ]; then
    echo "ERROR: Output directory not found: $out_dir"
    exit 1
fi

# Check if GNU parallel is available when jobs > 1
if [ $jobs -gt 1 ] && ! command -v parallel &> /dev/null; then
    echo "ERROR: GNU parallel not found."
    echo "Run with -j 1 for serial processing"
    exit 1
fi

echo "========================================================================"
echo "Adding latitude/longitude coordinates to reflectivity files"
echo "========================================================================"
echo "Output directory: $out_dir"
echo "Coordinate source: $coord_file"
echo "Parallel jobs: $jobs"
echo ""

start_time=$(date +%s)

# Create temporary file list (no scanning, just list all files)
tmp_list=$(mktemp)
trap "rm -f $tmp_list" EXIT

echo "Listing all reflectivity files..."
find "$out_dir" -name "scream.diag_equiv_reflectivity.5min.*.nc" -type f > "$tmp_list"

files_to_process=$(wc -l < "$tmp_list")

echo "Found $files_to_process files to process"
echo "(Note: Files that already have coordinates will be overwritten with identical data)"
echo ""

if [ $files_to_process -eq 0 ]; then
    echo "No files found. Nothing to do."
    exit 0
fi

# Process files
if [ $jobs -gt 1 ]; then
    echo "Processing with $jobs parallel jobs..."
    # Use GNU parallel with progress bar
    parallel -j $jobs --progress --bar \
        "ncks -A -v latitude,longitude '$coord_file' {} 2>/dev/null || echo 'FAILED: {}'" \
        :::: "$tmp_list" | tee /tmp/add_latlon_errors.log
    
    # Count failures
    failed_files=$(grep -c "FAILED:" /tmp/add_latlon_errors.log 2>/dev/null || echo 0)
else
    echo "Processing serially..."
    processed=0
    failed_files=0
    while IFS= read -r file; do
        filename=$(basename "$file")
        if ncks -A -v latitude,longitude "$coord_file" "$file" 2>/dev/null; then
            processed=$((processed + 1))
            if [ $((processed % 100)) -eq 0 ]; then
                echo "  Processed $processed/$files_to_process files..."
            fi
        else
            failed_files=$((failed_files + 1))
            echo "  ERROR: Failed to process $filename"
        fi
    done < "$tmp_list"
fi

end_time=$(date +%s)
elapsed=$((end_time - start_time))

echo ""
echo "========================================================================"
echo "Summary:"
echo "  Total files processed: $files_to_process"
echo "  Failed: $failed_files"
echo "  Elapsed time: ${elapsed}s ($(printf '%d:%02d:%02d' $((elapsed/3600)) $((elapsed%3600/60)) $((elapsed%60))))"
echo "========================================================================"

if [ $files_to_process -gt 0 ]; then
    echo ""
    echo "Verification: Check a processed file"
    sample_file=$(head -1 "$tmp_list")
    if [ -f "$sample_file" ]; then
        echo "$ ncdump -h $(basename "$sample_file") | grep -E '(latitude|longitude)'"
        ncdump -h "$sample_file" | grep -E "(float latitude|float longitude)"
    fi
fi

if [ $failed_files -gt 0 ]; then
    echo ""
    echo "WARNING: $failed_files files failed to process. Check /tmp/add_latlon_errors.log"
    exit 1
fi

exit 0
