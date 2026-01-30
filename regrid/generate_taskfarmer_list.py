#!/usr/bin/env python
"""
Generate TaskFarmer task list for SCREAM regridding workflow.

This script scans a directory for pairs of SCREAM output files (reflectivity and 
geopotential height) with matching timestamps and generates a task list for 
parallel processing with NERSC's TaskFarmer.

Usage:
    python generate_taskfarmer_list.py --output tasks.txt
    python generate_taskfarmer_list.py --start-date 2020-06-01 --end-date 2020-06-30 --output tasks.txt
"""

import argparse
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict


def parse_timestamp(timestamp_str):
    """
    Parse timestamp from filename format: YYYY-MM-DD-SSSSS
    
    Args:
        timestamp_str: String like "2020-06-07-07500"
    
    Returns:
        datetime object (date only, time is approximate from seconds)
    """
    parts = timestamp_str.split('-')
    if len(parts) != 4:
        return None
    
    try:
        year = int(parts[0])
        month = int(parts[1])
        day = int(parts[2])
        seconds = int(parts[3])
        
        # Create datetime with approximate time from seconds
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        
        return datetime(year, month, day, hours, minutes, secs)
    except (ValueError, IndexError):
        return None


def find_file_pairs(input_dir, start_date=None, end_date=None):
    """
    Find matching pairs of reflectivity and geopotential height files.
    
    Args:
        input_dir: Directory containing SCREAM output files
        start_date: Optional start datetime (inclusive)
        end_date: Optional end datetime (inclusive)
    
    Returns:
        List of tuples: (timestamp, refl_file, geop_file)
    """
    input_path = Path(input_dir)
    
    # Pattern to extract timestamp from filename
    refl_pattern = re.compile(r'output\.scream\.diag_equiv_reflectivity\.5min\.INSTANT\.nmins_x5\.(\d{4}-\d{2}-\d{2}-\d+)\.nc')
    geop_pattern = re.compile(r'output\.scream\.z_mid_p_mid\.5min\.INSTANT\.nmins_x5\.(\d{4}-\d{2}-\d{2}-\d+)\.nc')
    
    # Find all reflectivity and geopotential files
    refl_files = defaultdict(list)
    geop_files = defaultdict(list)
    
    print(f"Scanning directory: {input_dir}")
    
    for file in input_path.glob('output.scream.*.nc'):
        refl_match = refl_pattern.match(file.name)
        geop_match = geop_pattern.match(file.name)
        
        if refl_match:
            timestamp = refl_match.group(1)
            refl_files[timestamp].append(file.name)
        elif geop_match:
            timestamp = geop_match.group(1)
            geop_files[timestamp].append(file.name)
    
    print(f"Found {len(refl_files)} reflectivity files")
    print(f"Found {len(geop_files)} geopotential files")
    
    # Match pairs and filter by date range
    pairs = []
    matched_timestamps = sorted(set(refl_files.keys()) & set(geop_files.keys()))
    
    for timestamp in matched_timestamps:
        # Parse timestamp for date filtering
        dt = parse_timestamp(timestamp)
        
        if dt is None:
            print(f"Warning: Could not parse timestamp: {timestamp}")
            continue
        
        # Apply date filtering
        if start_date and dt < start_date:
            continue
        if end_date and dt > end_date:
            continue
        
        # Check for duplicates
        if len(refl_files[timestamp]) > 1:
            print(f"Warning: Multiple reflectivity files for {timestamp}: {refl_files[timestamp]}")
        if len(geop_files[timestamp]) > 1:
            print(f"Warning: Multiple geopotential files for {timestamp}: {geop_files[timestamp]}")
        
        refl_file = refl_files[timestamp][0]
        geop_file = geop_files[timestamp][0]
        
        pairs.append((timestamp, refl_file, geop_file))
    
    print(f"Found {len(pairs)} matching file pairs")
    
    return pairs


def generate_task_list(pairs, script_path, output_file):
    """
    Generate TaskFarmer task list file.
    
    Args:
        pairs: List of (timestamp, refl_file, geop_file) tuples
        script_path: Path to remap_dbz_zmid_5min.sh script
        output_file: Output task list filename
    """
    with open(output_file, 'w') as f:
        for timestamp, refl_file, geop_file in pairs:
            task_line = f"{script_path} {refl_file} {geop_file}\n"
            f.write(task_line)
    
    print(f"\nTask list written to: {output_file}")
    print(f"Total tasks: {len(pairs)}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate TaskFarmer task list for SCREAM regridding workflow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate task list for all files
  python generate_taskfarmer_list.py --output tasks.txt
  
  # Filter by date range
  python generate_taskfarmer_list.py --start-date 2020-06-01 --end-date 2020-06-30 --output tasks.txt
  
  # Custom input directory and script path
  python generate_taskfarmer_list.py --input-dir /path/to/data --script /path/to/script.sh --output tasks.txt
        """
    )
    
    parser.add_argument(
        '--input-dir',
        type=str,
        default='/pscratch/sd/w/wcmca1/SCREAMv1-cess2/run_conus',
        help='Directory containing SCREAM output files (default: %(default)s)'
    )
    
    parser.add_argument(
        '--script',
        type=str,
        default='/global/homes/f/feng045/program/scream/regrid/remap_dbz_zmid_5min.sh',
        help='Path to remap_dbz_zmid_5min.sh script (default: %(default)s)'
    )
    
    parser.add_argument(
        '--output',
        type=str,
        required=True,
        help='Output task list filename'
    )
    
    parser.add_argument(
        '-s',
        '--start-date',
        type=str,
        help='Start date (YYYY-MM-DD format, inclusive)'
    )
    
    parser.add_argument(
        '-e',
        '--end-date',
        type=str,
        help='End date (YYYY-MM-DD format, inclusive)'
    )
    
    args = parser.parse_args()
    
    # Parse date arguments
    start_date = None
    end_date = None
    
    if args.start_date:
        try:
            start_date = datetime.strptime(args.start_date, '%Y-%m-%d')
            print(f"Start date filter: {start_date.strftime('%Y-%m-%d')}")
        except ValueError:
            print(f"Error: Invalid start date format: {args.start_date}")
            print("Expected format: YYYY-MM-DD")
            return 1
    
    if args.end_date:
        try:
            # Set to end of day for inclusive filtering
            end_date = datetime.strptime(args.end_date, '%Y-%m-%d')
            end_date = end_date.replace(hour=23, minute=59, second=59)
            print(f"End date filter: {end_date.strftime('%Y-%m-%d')}")
        except ValueError:
            print(f"Error: Invalid end date format: {args.end_date}")
            print("Expected format: YYYY-MM-DD")
            return 1
    
    # Find file pairs
    pairs = find_file_pairs(args.input_dir, start_date, end_date)
    
    if not pairs:
        print("\nNo matching file pairs found!")
        return 1
    
    # Generate task list
    generate_task_list(pairs, args.script, args.output)
    
    print("\nTask list generated successfully!")
    print(f"\nTo run with TaskFarmer:")
    print(f"  runcommands.sh {args.output}")
    
    return 0


if __name__ == '__main__':
    exit(main())
