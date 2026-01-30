#!/bin/bash
#
# Fix incomplete compression/chunking for SCREAM reflectivity files
#
# This script scans for scream.diag_equiv_reflectivity files that are much larger
# than expected (indicating failed compression step) and applies the proper
# compression and chunking settings.
#
# Usage: ./fix_incomplete_compression.sh

set -e  # Exit on error

# Configuration matching remap_dbz_zmid.sh
chunk_time=1      # Chunk size for time dimension
chunk_lev=128     # Chunk size for lev dimension
chunk_lat=256     # Chunk size for lat/y dimension
chunk_lon=256     # Chunk size for lon/x dimension
deflate_level=1   # Compression level

# Directory to scan
scan_dir='/pscratch/sd/w/wcmca1/SCREAMv1-cess2/remap_conus'

# Size threshold in GB (files larger than this are considered uncompressed)
# Normal compressed files are ~6GB, uncompressed are ~22GB
# Use 10GB as threshold to be safe
size_threshold_gb=10
size_threshold_bytes=$((size_threshold_gb * 1024 * 1024 * 1024))

# Load required environment
echo "Loading E3SM environment..."
source /global/common/software/e3sm/anaconda_envs/load_latest_e3sm_unified_pm-cpu.sh

echo "========================================================================"
echo "SCREAM File Compression Fix"
echo "========================================================================"
echo "Scanning directory: $scan_dir"
echo "Size threshold: ${size_threshold_gb}GB (files larger than this will be recompressed)"
echo "Compression settings: deflate_level=${deflate_level}"
echo "Chunking: time=${chunk_time}, lev=${chunk_lev}, y=${chunk_lat}, x=${chunk_lon}"
echo "========================================================================"
echo ""

# Find all scream.diag_equiv_reflectivity files
echo "Searching for files matching pattern: scream.diag_equiv_reflectivity.5min.*.nc"
files_found=0
files_to_fix=()

# Use find to locate files and check their sizes
while IFS= read -r filepath; do
    files_found=$((files_found + 1))
    
    # Get file size in bytes
    filesize=$(stat -c%s "$filepath" 2>/dev/null || stat -f%z "$filepath" 2>/dev/null)
    filesize_gb=$(echo "scale=1; $filesize / 1024 / 1024 / 1024" | bc)
    
    # Check if file exceeds threshold
    if [ "$filesize" -gt "$size_threshold_bytes" ]; then
        echo "Found large file: $(basename "$filepath") (${filesize_gb}GB)"
        files_to_fix+=("$filepath")
    fi
done < <(find "$scan_dir" -maxdepth 1 -name "scream.diag_equiv_reflectivity.5min.*.nc" -type f)

echo ""
echo "Summary: Found ${files_found} total files, ${#files_to_fix[@]} need recompression"
echo "========================================================================"

# Exit if no files need fixing
if [ ${#files_to_fix[@]} -eq 0 ]; then
    echo "No files need fixing. Exiting."
    exit 0
fi

# Process each file that needs fixing
echo ""
echo "Processing files..."
echo ""

success_count=0
error_count=0
error_files=()

for filepath in "${files_to_fix[@]}"; do
    filename=$(basename "$filepath")
    echo "----------------------------------------------------------------------"
    echo "Processing: $filename"
    start_time=$(date +%s)
    
    # Create temporary backup name
    backup_file="${filepath}.backup"
    
    # Check if backup already exists (from previous failed run)
    if [ -f "$backup_file" ]; then
        echo "  WARNING: Backup file already exists: $backup_file"
        echo "  Skipping this file to avoid overwriting. Please investigate manually."
        error_count=$((error_count + 1))
        error_files+=("$filename (backup exists)")
        continue
    fi
    
    # Create backup by renaming original
    echo "  Creating backup..."
    mv "$filepath" "$backup_file"
    
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
    
    # Apply the full step 4 processing
    # First, rename dimensions and variables (use backup as source)
    echo "  Renaming dimensions and variables..."
    cp "$backup_file" "$filepath"
    ncrename -d .lat,y -d .lon,x "$filepath" 2>/dev/null || true
    ncrename -v .lat,latitude -v .lon,longitude "$filepath" 2>/dev/null || true
    
    # Then apply compression, chunking, and variable removal
    echo "  Applying compression and chunking..."
    if ncks -4 -L ${deflate_level} -O -C -x -v .ilev,.lat_bnds,.lon_bnds $chunk_opts \
        "$filepath" "$filepath"; then
        
        # Get new file size
        new_size=$(stat -c%s "$filepath" 2>/dev/null || stat -f%z "$filepath" 2>/dev/null)
        new_size_gb=$(echo "scale=1; $new_size / 1024 / 1024 / 1024" | bc)
        old_size=$(stat -c%s "$backup_file" 2>/dev/null || stat -f%z "$backup_file" 2>/dev/null)
        old_size_gb=$(echo "scale=1; $old_size / 1024 / 1024 / 1024" | bc)
        
        echo "  SUCCESS: Compressed from ${old_size_gb}GB to ${new_size_gb}GB"
        
        # Remove backup if successful
        echo "  Removing backup..."
        rm -f "$backup_file"
        
        success_count=$((success_count + 1))
    else
        echo "  ERROR: Compression failed!"
        echo "  Restoring from backup..."
        mv "$backup_file" "$filepath"
        error_count=$((error_count + 1))
        error_files+=("$filename (compression failed)")
    fi
    
    end_time=$(date +%s)
    elapsed=$((end_time - start_time))
    echo "  Processing time: ${elapsed}s"
done

# Final summary
echo ""
echo "========================================================================"
echo "Processing Complete"
echo "========================================================================"
echo "Successfully recompressed: $success_count files"
echo "Errors encountered: $error_count files"

if [ $error_count -gt 0 ]; then
    echo ""
    echo "Files with errors:"
    for error_file in "${error_files[@]}"; do
        echo "  - $error_file"
    done
fi

echo "========================================================================"

# Exit with error code if any files failed
if [ $error_count -gt 0 ]; then
    exit 1
fi
