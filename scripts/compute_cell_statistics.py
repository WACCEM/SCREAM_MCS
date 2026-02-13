#!/usr/bin/env python
"""
Compute cell statistics from convective cell identification snapshots.

This script processes cloudid_*.nc files in parallel to extract statistics
for each identified convective cell, then saves results to a Parquet file.

Usage:
    python compute_cell_statistics.py -s START -e END -o OUTPUT [OPTIONS]

Example:
    python compute_cell_statistics.py -s 2020-04-01T00:00:00 -e 2020-04-30T23:59:59 \
        -o cell_statistics_april2020.parquet \
        --config /global/homes/f/feng045/program/scream/tracking/config_cellid_3km_GridRad.yaml \
        --parallel 1 --workers 64
"""

import os
import sys
import argparse
import glob
from pathlib import Path
from datetime import datetime
import numpy as np
import pandas as pd
import xarray as xr
import yaml
import warnings
warnings.filterwarnings('ignore')

# Dask for parallel processing
from dask.distributed import Client, LocalCluster
import dask.bag as db

# PyFLEXTRKR utilities
from pyflextrkr.ft_utilities import load_config, subset_files_timerange

def read_config(config_file):
    """Read YAML configuration file and extract pixel_radius."""
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
    return config.get('pixel_radius', 3.0)  # Default 3.0 km if not found


def process_single_file(filepath, pixel_radius):
    """
    Process a single cloudid file and compute statistics for all cells.
    
    Parameters
    ----------
    filepath : str
        Path to the cloudid netCDF file
    pixel_radius : float
        Pixel radius in km (from config file)
    
    Returns
    -------
    pandas.DataFrame
        DataFrame with statistics for all cells in this snapshot
    """
    try:
        # Open the dataset
        with xr.open_dataset(filepath) as ds:
            # Extract time
            time_value = pd.to_datetime(ds['time'].values[0], unit='s')
            
            # Get number of features
            nfeatures = int(ds['nfeatures'].values[0])
            
            # If no features, return empty DataFrame
            if nfeatures == 0:
                return pd.DataFrame()
            
            # Extract 2D arrays as xarray DataArrays (squeeze time dimension)
            # Keep as DataArrays for efficient subsetting
            lon = ds['longitude'].squeeze()
            lat = ds['latitude'].squeeze()
            conv_mask = ds['conv_mask'].squeeze()
            dbz_comp = ds['dbz_comp'].squeeze()
            dbz_lowlevel = ds['dbz_lowlevel'].squeeze()
            echotop10 = ds['echotop10'].squeeze()
            echotop20 = ds['echotop20'].squeeze()
            echotop30 = ds['echotop30'].squeeze()
            echotop40 = ds['echotop40'].squeeze()
            echotop50 = ds['echotop50'].squeeze()
           
            # Get unique cell IDs (excluding 0 which is background)
            cell_ids = np.unique(conv_mask.values[conv_mask.values > 0])
            
            # Initialize lists to store results
            results = []
            
            # Calculate pixel area (km²)
            pixel_area = pixel_radius ** 2
            
            # Process each cell
            for cell_id in cell_ids:
                # Use xarray's where with drop=True to get only the bounding box of this cell
                # This significantly reduces memory and computation by working with smaller arrays
                cell_mask = conv_mask.where(conv_mask == cell_id, drop=True)
                
                # Number of pixels
                npixels = int((cell_mask == cell_id).sum().values)
                
                # Skip if no pixels (shouldn't happen, but safety check)
                if npixels == 0:
                    continue
                
                # Cell area
                area = npixels * pixel_area
                
                # Cell equivalent circular diameter
                diameter = 2 * np.sqrt(area / np.pi)
                
                # Subset all variables to the cell's bounding box using the same indices
                lon_cell = lon.where(conv_mask == cell_id, drop=True)
                lat_cell = lat.where(conv_mask == cell_id, drop=True)
                dbz_comp_cell = dbz_comp.where(conv_mask == cell_id, drop=True)
                dbz_lowlevel_cell = dbz_lowlevel.where(conv_mask == cell_id, drop=True)
                echotop10_cell = echotop10.where(conv_mask == cell_id, drop=True)
                echotop20_cell = echotop20.where(conv_mask == cell_id, drop=True)
                echotop30_cell = echotop30.where(conv_mask == cell_id, drop=True)
                echotop40_cell = echotop40.where(conv_mask == cell_id, drop=True)
                echotop50_cell = echotop50.where(conv_mask == cell_id, drop=True)
                
                # Cell center (mean lat/lon of pixels belonging to this cell)
                center_lon = float(lon_cell.mean().values)
                center_lat = float(lat_cell.mean().values)
                
                # Max values for reflectivity fields (using xarray's max which handles NaN)
                max_dbz_comp = float(dbz_comp_cell.max().values)
                max_dbz_lowlevel = float(dbz_lowlevel_cell.max().values)
                
                # Max echo-top heights
                max_echotop10 = float(echotop10_cell.max().values)
                max_echotop20 = float(echotop20_cell.max().values)
                max_echotop30 = float(echotop30_cell.max().values)
                max_echotop40 = float(echotop40_cell.max().values)
                max_echotop50 = float(echotop50_cell.max().values)
                
                # Store results
                results.append({
                    'time': time_value,
                    'cell_id': int(cell_id),
                    'filename': os.path.basename(filepath),
                    'npixels': int(npixels),
                    'area': float(area),
                    'diameter': float(diameter),
                    'center_lon': float(center_lon),
                    'center_lat': float(center_lat),
                    'max_dbz_comp': float(max_dbz_comp) if not np.isnan(max_dbz_comp) else np.nan,
                    'max_dbz_lowlevel': float(max_dbz_lowlevel) if not np.isnan(max_dbz_lowlevel) else np.nan,
                    'max_echotop10': float(max_echotop10) if not np.isnan(max_echotop10) else np.nan,
                    'max_echotop20': float(max_echotop20) if not np.isnan(max_echotop20) else np.nan,
                    'max_echotop30': float(max_echotop30) if not np.isnan(max_echotop30) else np.nan,
                    'max_echotop40': float(max_echotop40) if not np.isnan(max_echotop40) else np.nan,
                    'max_echotop50': float(max_echotop50) if not np.isnan(max_echotop50) else np.nan,
                })
            
            # Convert to DataFrame
            df = pd.DataFrame(results)
            
            return df
    
    except Exception as e:
        print(f"Error processing {filepath}: {str(e)}")
        return pd.DataFrame()


def process_files_serial(filepaths, pixel_radius):
    """
    Process multiple files serially and combine results.
    
    Parameters
    ----------
    filepaths : list
        List of file paths to process
    pixel_radius : float
        Pixel radius in km
    
    Returns
    -------
    pandas.DataFrame
        Combined DataFrame with all cell statistics
    """
    print(f"Processing {len(filepaths)} files serially...")
    
    results = []
    for i, filepath in enumerate(filepaths):
        df = process_single_file(filepath, pixel_radius)
        if not df.empty:
            results.append(df)
        
        # Progress update every 100 files
        if (i + 1) % 100 == 0:
            print(f"  Processed {i + 1}/{len(filepaths)} files...")
    
    print(f"  Processed {len(filepaths)}/{len(filepaths)} files.")
    
    # Combine all results
    if results:
        df_combined = pd.concat(results, ignore_index=True)
        print(f"\nTotal cells found: {len(df_combined)}")
        return df_combined
    else:
        print("\nNo cells found in any files.")
        return pd.DataFrame()


def process_files_parallel(filepaths, pixel_radius, nworkers=32):
    """
    Process multiple files in parallel using Dask and combine results.
    
    Parameters
    ----------
    filepaths : list
        List of file paths to process
    pixel_radius : float
        Pixel radius in km
    nworkers : int
        Number of parallel workers
    
    Returns
    -------
    pandas.DataFrame
        Combined DataFrame with all cell statistics
    """
    print(f"Processing {len(filepaths)} files using {nworkers} workers (Dask)...")
    
    # Set up Dask LocalCluster
    cluster = LocalCluster(n_workers=nworkers, threads_per_worker=1, processes=True)
    client = Client(cluster)
    
    print(f"Dask dashboard available at: {client.dashboard_link}")
    
    try:
        # Create Dask bag from filepaths
        bag = db.from_sequence(filepaths, npartitions=nworkers*2)
        
        # Map processing function
        results_bag = bag.map(lambda fp: process_single_file(fp, pixel_radius))
        
        # Compute results
        results = results_bag.compute()
        
        # Filter out empty DataFrames
        results = [df for df in results if not df.empty]
        
        print(f"  Processed {len(filepaths)}/{len(filepaths)} files.")
        
        # Combine all results
        if results:
            df_combined = pd.concat(results, ignore_index=True)
            print(f"\nTotal cells found: {len(df_combined)}")
            return df_combined
        else:
            print("\nNo cells found in any files.")
            return pd.DataFrame()
    
    finally:
        # Clean up Dask cluster
        client.close()
        cluster.close()


def main():
    """Main function to process command-line arguments and run the analysis."""
    parser = argparse.ArgumentParser(
        description='Compute cell statistics from cloudid snapshot files.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process files in parallel (default)
  python compute_cell_statistics.py -s 2020-04-01T00:00:00 -e 2020-04-30T23:59:59 
  
  # Process serially
  python compute_cell_statistics.py -s 2020-04-01T00:00:00 -e 2020-04-30T23:59:59 \
      -p 0
  
  # Use custom config and more workers
  python compute_cell_statistics.py -s 2020-04-01T00:00:00 -e 2020-04-30T23:59:59 \
      -c config.yaml -p 1 --workers 64
        """
    )
    
    parser.add_argument("-s", "--start", 
                        help="first time in time series to process, format=YYYY-mm-ddTHH:MM:SS", required=True)
    parser.add_argument("-e", "--end", 
                        help="last time in time series to process, format=YYYY-mm-ddTHH:MM:SS", required=True)
    parser.add_argument('-c', '--config', type=str,
                        default='/global/homes/f/feng045/program/scream/tracking/config_cellid_3km_GridRad.yaml',
                        help='Path to config YAML file (default: GridRad 3km config)')
    parser.add_argument('-p','--parallel', type=int, choices=[0, 1], default=1,
                        help='Processing mode: 0=serial, 1=parallel (default: 1)')
    parser.add_argument('-w', '--workers', type=int, default=64,
                        help='Number of parallel workers for parallel mode (default: 64)')
    
    args = parser.parse_args()

    # Convert datetime string to Pandas Timestamp
    start_time = pd.to_datetime(args.start)
    end_time = pd.to_datetime(args.end)
    # Convert Pandas Timestamp to Epoch time (base time)
    start_basetime = start_time.timestamp()
    end_basetime = end_time.timestamp()
    
    # Read parameters from config
    print(f"Reading configuration from: {args.config}")
    # pixel_radius = read_config(args.config)
    config = load_config(args.config)
    pixel_radius = config.get('pixel_radius')
    cloudid_filebase = config.get('cloudid_filebase')
    output_dir = config.get('stats_outpath')
    tracking_outpath = config.get('tracking_outpath')
    print(f"Pixel radius: {pixel_radius} km")
    print(f"Pixel area: {pixel_radius**2} km²")

    # Define output file path based on config and time range
    output_path = os.path.join(output_dir, f"cell_stats_{start_time.strftime('%Y%m%d')}_{end_time.strftime('%Y%m%d')}.parquet")
    print(f"Output file will be: {output_path}")


    # Search for files within the specified time range
    datafiles_all, \
    datafiles_basetime, \
    datafiles_datestring, \
    datafiles_timestring = subset_files_timerange(
        tracking_outpath,
        cloudid_filebase,
        start_basetime,
        end_basetime,
        time_format='yyyymodd_hhmmss',
    )

    # Filter files to only keep hourly snapshots
    # Hourly snapshots have basetime divisible by 3600 (seconds per hour)
    # hourly_indices = [i for i, bt in enumerate(datafiles_basetime) if bt % 3600 == 0]

    # window in seconds (3 minutes)
    window = 180 
    # Dictionary to store { hour_timestamp: (index, absolute_difference) }
    closest_map = {}

    for i, bt in enumerate(datafiles_basetime):
        remainder = bt % 3600
        # Calculate how far this is from the nearest hour (0 to 1800)
        diff = remainder if remainder <= 1800 else 3600 - remainder
        
        # Only consider if within 3-minute window
        if diff <= window:
            # Round the timestamp to the exact hour mark to use as a key
            hour_key = (bt // 3600) * 3600 if remainder <= 1800 else ((bt // 3600) + 1) * 3600
            
            # Keep this index if it's the first for this hour, or if it's closer than the previous find
            if hour_key not in closest_map or diff < closest_map[hour_key][1]:
                closest_map[hour_key] = (i, diff)

    # Extract only the indices
    hourly_indices = sorted([val[0] for val in closest_map.values()])

    
    datafiles_all = [datafiles_all[i] for i in hourly_indices]
    datafiles_basetime = [datafiles_basetime[i] for i in hourly_indices]
    datafiles_datestring = [datafiles_datestring[i] for i in hourly_indices]
    datafiles_timestring = [datafiles_timestring[i] for i in hourly_indices]
    
    print(f"Filtered to {len(datafiles_all)} hourly snapshots")

    ntimes = len(datafiles_all)
    print(f"Number of files within time range: {ntimes}")
    
    if ntimes == 0:
        print(f"ERROR: No files found within time range")
        sys.exit(1)
    
    print(f"\nFound {len(datafiles_all)} files to process")
    print(f"First file: {os.path.basename(datafiles_all[0])}")
    print(f"Last file:  {os.path.basename(datafiles_all[-1])}")
    
    # Process files
    start_time = datetime.now()
    if args.parallel == 1:
        df_stats = process_files_parallel(datafiles_all, pixel_radius, args.workers)
    else:
        df_stats = process_files_serial(datafiles_all, pixel_radius)
    elapsed = datetime.now() - start_time
    
    if df_stats.empty:
        print("\nNo statistics to save (no cells found).")
        return
    
    # Sort by time and cell_id
    df_stats = df_stats.sort_values(['time', 'cell_id']).reset_index(drop=True)
    
    # Check and convert echotop units if needed
    # If max echotop > 100, assume units are in meters and convert to km
    echotop_columns = ['max_echotop10', 'max_echotop20', 'max_echotop30', 'max_echotop40', 'max_echotop50']
    echotop_max = df_stats[echotop_columns].max().max()
    
    if echotop_max > 100:
        print(f"\nDetected echotop unit in meters (max value: {echotop_max:.1f} m). Converting to km...")
        for col in echotop_columns:
            df_stats[col] = df_stats[col] / 1000.0
        echotop_unit = 'km'
    else:
        print(f"\nEchotop unit appears to be in km (max value: {echotop_max:.1f} km).")
        echotop_unit = 'km'
    
    # Print summary statistics
    print("\n" + "="*70)
    print("SUMMARY STATISTICS")
    print("="*70)
    print(f"Total snapshots processed: {len(datafiles_all)}")
    print(f"Total cells: {len(df_stats)}")
    print(f"Time range: {df_stats['time'].min()} to {df_stats['time'].max()}")
    print(f"Snapshots with cells: {df_stats['filename'].nunique()}")
    print(f"\nCells per snapshot:")
    print(f"  Mean: {len(df_stats) / df_stats['filename'].nunique():.1f}")
    print(f"  Min:  {df_stats.groupby('filename').size().min()}")
    print(f"  Max:  {df_stats.groupby('filename').size().max()}")
    print(f"\nCell area (km²):")
    print(f"  Mean: {df_stats['area'].mean():.2f}")
    print(f"  Median: {df_stats['area'].median():.2f}")
    print(f"  Min: {df_stats['area'].min():.2f}")
    print(f"  Max: {df_stats['area'].max():.2f}")
    print(f"\nCell diameter (km):")
    print(f"  Mean: {df_stats['diameter'].mean():.2f}")
    print(f"  Median: {df_stats['diameter'].median():.2f}")
    print(f"  Min: {df_stats['diameter'].min():.2f}")
    print(f"  Max: {df_stats['diameter'].max():.2f}")
    print(f"\nMax composite reflectivity (dBZ):")
    print(f"  Mean: {df_stats['max_dbz_comp'].mean():.2f}")
    print(f"  Max: {df_stats['max_dbz_comp'].max():.2f}")
    print(f"\nEcho-top heights ({echotop_unit}):")
    for threshold in [10, 20, 30, 40, 50]:
        col = f'max_echotop{threshold}'
        print(f"  {threshold} dBZ - Mean: {df_stats[col].mean():.2f}, Max: {df_stats[col].max():.2f}")
    
    # Save to Parquet
    print(f"\nSaving results to: {output_path}")
    df_stats.to_parquet(output_path, index=False, compression='snappy')
    
    # Get file size
    file_size_mb = os.path.getsize(output_path) / (1024**2)
    print(f"Output file size: {file_size_mb:.2f} MB")
    print(f"Processing time: {elapsed}")
    print("\nDone!")
    
    # Show first few rows
    print("\nFirst 10 rows of output:")
    print(df_stats.head(10).to_string())


if __name__ == '__main__':
    main()
