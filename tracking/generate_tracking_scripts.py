#!/usr/bin/env python
"""
Script to generate config and slurm files for PyFLEXTRKR tracking for multiple months.

This script creates monthly config and slurm job files from templates and optionally
submits them to the SLURM scheduler.
"""

import os
import argparse
from datetime import datetime
from dateutil.relativedelta import relativedelta
import subprocess


def generate_files(start_date, end_date, config_template, slurm_template, 
                   output_dir, make_scripts=True, submit_jobs=False):
    """
    Generate config and slurm files for each month in the date range.
    
    Parameters:
    -----------
    start_date : str
        Start date in YYYY-MM format (e.g., '2025-05')
    end_date : str
        End date in YYYY-MM format (e.g., '2025-07')
    config_template : str
        Path to config template file
    slurm_template : str
        Path to slurm template file
    output_dir : str
        Directory to save output files
    make_scripts : bool
        Whether to create the script files (default: True)
    submit_jobs : bool
        Whether to submit the jobs to SLURM (default: False)
    """
    
    # Parse dates
    start = datetime.strptime(start_date, "%Y-%m")
    end = datetime.strptime(end_date, "%Y-%m")
    
    # Read templates
    print(f"Reading templates...")
    print(f"  Config: {config_template}")
    print(f"  Slurm:  {slurm_template}")
    
    with open(config_template, 'r') as f:
        config_content = f.read()
    
    with open(slurm_template, 'r') as f:
        slurm_content = f.read()
    
    # Extract base names from templates for output file naming
    config_base, config_ext = os.path.splitext(os.path.basename(config_template))
    slurm_base, slurm_ext = os.path.splitext(os.path.basename(slurm_template))
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(os.path.join(output_dir, 'logs'), exist_ok=True)  # For log files
    
    # Iterate through months
    current = start
    job_files = []
    
    print(f"\nGenerating files from {start_date} to {end_date}...")
    print("=" * 70)
    
    while current <= end:
        # Format date strings
        yyyymm = current.strftime("%Y%m")
        next_month = current + relativedelta(months=1)
        
        # For config file dates (format: YYYYMMDD.HHMM)
        startdate_str = current.strftime("%Y%m%d.0000")
        enddate_str = next_month.strftime("%Y%m%d.0000")
        
        print(f"\nMonth: {current.strftime('%Y-%m')} ({yyyymm})")
        print(f"  Period: {startdate_str} to {enddate_str}")
        
        if make_scripts:
            # Generate config file
            config_new = config_content.replace('STARTDATE', startdate_str)
            config_new = config_new.replace('ENDDATE', enddate_str)
            
            config_filename = f"{config_base}_{yyyymm}{config_ext}"
            config_path = os.path.join(output_dir, config_filename)
            config_abspath = os.path.abspath(config_path)
            
            with open(config_path, 'w') as f:
                f.write(config_new)
            print(f"  ✓ Created config: {config_filename}")
            
            # Generate slurm file
            slurm_new = slurm_content.replace('DATE', yyyymm)
            # Update the config file path in the slurm script to point to actual output location
            slurm_new = slurm_new.replace(
                'CONFIG_TEMPLATE',
                config_abspath
            )
            
            slurm_filename = f"{slurm_base}_{yyyymm}{slurm_ext}"
            slurm_path = os.path.join(output_dir, slurm_filename)
            
            with open(slurm_path, 'w') as f:
                f.write(slurm_new)
            
            # Make slurm script executable
            os.chmod(slurm_path, 0o755)
            print(f"  ✓ Created slurm:  {slurm_filename}")
            
            job_files.append((slurm_path, yyyymm))
        else:
            # Just collect existing files for submission
            slurm_filename = f"{slurm_base}_{yyyymm}{slurm_ext}"
            slurm_path = os.path.join(output_dir, slurm_filename)
            if os.path.exists(slurm_path):
                job_files.append((slurm_path, yyyymm))
            else:
                print(f"  ⚠ Warning: {slurm_filename} not found")
        
        # Move to next month
        current += relativedelta(months=1)
    
    # Submit jobs if requested
    if submit_jobs:
        print("\n" + "=" * 70)
        print("Submitting jobs to SLURM...")
        print("=" * 70)
        
        if not job_files:
            print("  ⚠ No job files to submit!")
        else:
            for job_file, yyyymm in job_files:
                cmd = f"sbatch {job_file}"
                print(f"\n  Submitting {yyyymm}:")
                print(f"    $ {cmd}")
                
                try:
                    result = subprocess.run(cmd, shell=True, capture_output=True, 
                                          text=True, check=True)
                    print(f"    ✓ {result.stdout.strip()}")
                except subprocess.CalledProcessError as e:
                    print(f"    ✗ Error: {e.stderr.strip()}")
    
    print("\n" + "=" * 70)
    print(f"Summary: Generated files for {len(job_files)} month(s)")
    if make_scripts:
        print(f"  Output directory: {output_dir}")
    if submit_jobs:
        print(f"  Jobs submitted: {len(job_files)}")


def main():
    parser = argparse.ArgumentParser(
        description='Generate config and slurm files for tracking jobs over multiple months.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate files for May-July 2025
  %(prog)s --start 2025-05 --end 2025-07 \\
           --config-template scream/tracking/config_celltracking_3km_MRMS.yaml \\
           --slurm-template scream/tracking/slurm_MRMS_conus_celltracking_dask.sh
  
  # Generate and submit jobs
  %(prog)s --start 2025-05 --end 2025-07 \\
           --config-template scream/tracking/config_celltracking_3km_MRMS.yaml \\
           --slurm-template scream/tracking/slurm_MRMS_conus_celltracking_dask.sh \\
           --submit
  
  # Only submit already-existing files (skip generation)
  %(prog)s --start 2025-05 --end 2025-07 \\
           --config-template scream/tracking/config_celltracking_3km_MRMS.yaml \\
           --slurm-template scream/tracking/slurm_MRMS_conus_celltracking_dask.sh \\
           --no-make --submit
  
  # Use custom output directory
  %(prog)s --start 2025-05 --end 2025-07 \\
           --config-template /path/to/config.yaml \\
           --slurm-template /path/to/slurm.sh \\
           --output-dir /path/to/output
        """
    )
    
    parser.add_argument('-s', '--start', required=True, 
                       help='Start date in YYYY-MM format (e.g., 2025-05)')
    parser.add_argument('-e', '--end', required=True,
                       help='End date in YYYY-MM format (e.g., 2025-07)')
    parser.add_argument('-c', '--config-template', required=True,
                       help='Path to config template file')
    parser.add_argument('-l', '--slurm-template', required=True,
                       help='Path to slurm template file')
    parser.add_argument('-o', '--output-dir', 
                       default='scream/tracking',
                       help='Directory to save output files (default: %(default)s)')
    parser.add_argument('--make', dest='make_scripts', 
                       action='store_true', default=True,
                       help='Create script files (default: enabled)')
    parser.add_argument('--no-make', dest='make_scripts', 
                       action='store_false',
                       help='Skip creating script files')
    parser.add_argument('--submit', dest='submit_jobs', 
                       action='store_true',
                       help='Submit jobs to SLURM after creating files (default: disabled)')
    
    args = parser.parse_args()
    
    # Validate dates
    try:
        datetime.strptime(args.start, "%Y-%m")
        datetime.strptime(args.end, "%Y-%m")
    except ValueError as e:
        parser.error(f"Invalid date format: {e}")
    
    # Check template files exist
    if args.make_scripts:
        if not os.path.exists(args.config_template):
            parser.error(f"Config template not found: {args.config_template}")
        if not os.path.exists(args.slurm_template):
            parser.error(f"Slurm template not found: {args.slurm_template}")
    
    generate_files(
        start_date=args.start,
        end_date=args.end,
        config_template=args.config_template,
        slurm_template=args.slurm_template,
        output_dir=args.output_dir,
        make_scripts=args.make_scripts,
        submit_jobs=args.submit_jobs
    )
    
    print("\n✓ Done!")


if __name__ == '__main__':
    main()
