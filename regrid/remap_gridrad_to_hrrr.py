#!/usr/bin/env python
"""
Remap GridRad 3D radar reflectivity data to HRRR grid using xESMF.

This script processes GridRad data and remaps it to the HRRR grid using
conservative or bilinear remapping with xESMF. It supports both serial
and parallel processing using Dask.

Updated for 2026 with modern xESMF/xarray/Dask
Based on: xesmf_gridding.py (2018)
"""

import numpy as np
import xarray as xr
import xesmf as xe
import gridrad
import glob
import os
import sys
import argparse
from pathlib import Path
import time
from datetime import datetime
from dask.distributed import Client, LocalCluster
from dask.diagnostics import ProgressBar
import warnings
warnings.filterwarnings('ignore')


# Configuration
HRRR_GRID_FILE = '/pscratch/sd/i/iclas2/GridRad/maps/hrrr_sfc_latlon_orog_lsm.nc'
GRIDRAD_DATA_DIR = '/pscratch/sd/i/iclas2/GridRad'
OUTPUT_DIR = '/pscratch/sd/i/iclas2/GridRad/regrid_hrrr'
WEIGHT_DIR = '/pscratch/sd/i/iclas2/GridRad/weights'

# Processing options
REMAP_METHOD = 'bilinear'  # 'conservative' or 'bilinear' (bilinear recommended for curvilinear grids)
RUN_PARALLEL = True
N_WORKERS = 32
LOG_ZH = True  # Convert to linear units before remapping


def idbz(field):
    """Convert dBZ to linear units (mm^6/m^3)."""
    if LOG_ZH:
        return np.power(10, field / 10.0)
    else:
        return field


def dbz(field, missing_value=-9999.0):
    """Convert linear units back to dBZ, handling zeros and invalid values."""
    if LOG_ZH:
        # Mask out zeros and negative values to avoid -inf and nan
        mask = (field > 0) & np.isfinite(field)
        result = np.full_like(field, missing_value, dtype=np.float32)
        result[mask] = 10 * np.log10(field[mask])
        return result
    else:
        return field


def load_hrrr_grid(hrrr_file, method='bilinear'):
    """
    Load HRRR grid lat/lon coordinates.
    
    Parameters
    ----------
    hrrr_file : str
        Path to HRRR grid file with latitude/longitude
    method : str
        Remapping method ('bilinear' or 'conservative')
        
    Returns
    -------
    xr.Dataset
        HRRR grid as xarray Dataset with optional bounds for conservative remapping
    """
    ds = xr.open_dataset(hrrr_file)
    
    lat_center = ds['latitude'].values
    lon_center = ds['longitude'].values
    
    # Create destination grid for xESMF
    dest_grid = xr.Dataset({
        'lat': (['y', 'x'], lat_center),
        'lon': (['y', 'x'], lon_center)
    })
    
    # Only add bounds if using conservative method
    # Note: Conservative remapping with curvilinear grids can have issues
    # Bilinear is recommended for HRRR grid
    if method == 'conservative':
        print("  WARNING: Conservative remapping with curvilinear HRRR grid may fail")
        print("  Consider using bilinear method instead with -m bilinear")
        
        ny, nx = lat_center.shape
        
        # Estimate grid cell bounds from centers
        lat_b = np.zeros((ny+1, nx+1))
        lon_b = np.zeros((ny+1, nx+1))
        
        # Interior points: average of surrounding centers
        lat_b[1:-1, 1:-1] = 0.25 * (lat_center[:-1, :-1] + lat_center[:-1, 1:] + 
                                     lat_center[1:, :-1] + lat_center[1:, 1:])
        lon_b[1:-1, 1:-1] = 0.25 * (lon_center[:-1, :-1] + lon_center[:-1, 1:] + 
                                     lon_center[1:, :-1] + lon_center[1:, 1:])
        
        # Edges: extrapolate from interior (fix dimension matching)
        lat_b[0, 1:-1] = 2*lat_center[0, :-1] - lat_b[1, 1:-1]
        lat_b[-1, 1:-1] = 2*lat_center[-1, :-1] - lat_b[-2, 1:-1]
        lat_b[1:-1, 0] = 2*lat_center[:-1, 0] - lat_b[1:-1, 1]
        lat_b[1:-1, -1] = 2*lat_center[:-1, -1] - lat_b[1:-1, -2]
        
        lon_b[0, 1:-1] = 2*lon_center[0, :-1] - lon_b[1, 1:-1]
        lon_b[-1, 1:-1] = 2*lon_center[-1, :-1] - lon_b[-2, 1:-1]
        lon_b[1:-1, 0] = 2*lon_center[:-1, 0] - lon_b[1:-1, 1]
        lon_b[1:-1, -1] = 2*lon_center[:-1, -1] - lon_b[1:-1, -2]
        
        # Corners: extrapolate
        lat_b[0, 0] = 2*lat_center[0, 0] - lat_b[1, 1]
        lat_b[0, -1] = 2*lat_center[0, -1] - lat_b[1, -2]
        lat_b[-1, 0] = 2*lat_center[-1, 0] - lat_b[-2, 1]
        lat_b[-1, -1] = 2*lat_center[-1, -1] - lat_b[-2, -2]
        
        lon_b[0, 0] = 2*lon_center[0, 0] - lon_b[1, 1]
        lon_b[0, -1] = 2*lon_center[0, -1] - lon_b[1, -2]
        lon_b[-1, 0] = 2*lon_center[-1, 0] - lon_b[-2, 1]
        lon_b[-1, -1] = 2*lon_center[-1, -1] - lon_b[-2, -2]
        
        dest_grid['lat_b'] = (['y_b', 'x_b'], lat_b)
        dest_grid['lon_b'] = (['y_b', 'x_b'], lon_b)
    
    return dest_grid


def gridrad_to_xarray(gridrad_file, method='bilinear'):
    """
    Read GridRad file and convert to xarray Dataset.
    
    Parameters
    ----------
    gridrad_file : str
        Path to GridRad NetCDF file
    method : str
        Remapping method ('bilinear' or 'conservative')
        
    Returns
    -------
    xr.Dataset
        GridRad data as xarray Dataset with 3D variables [height, lat, lon]
    """
    # Read GridRad data using the gridrad library
    data = gridrad.read_file(gridrad_file)
    
    # Extract coordinates
    lon = data['x']['values'] - 360.0  # Convert to -180 to 180
    lat = data['y']['values']
    height = data['z']['values']
    analysis_time = data['Analysis_time']
    
    # Extract 3D variables
    # Convert reflectivity to linear units if LOG_ZH is True
    zh_values = idbz(data['Z_H']['values'])
    nobs = data['nobs']
    necho = data['necho']
    wvalues = data['Z_H']['wvalues']
    
    # Create 2D lat/lon grids for xESMF
    lon_2d, lat_2d = np.meshgrid(lon, lat)
    
    # Create xarray Dataset with proper coordinates
    ds = xr.Dataset(
        {
            'zh': (['height', 'lat', 'lon'], zh_values),
            'nobs': (['height', 'lat', 'lon'], nobs),
            'necho': (['height', 'lat', 'lon'], necho),
            'wvalues': (['height', 'lat', 'lon'], wvalues),
        },
        coords={
            'lat': (['lat', 'lon'], lat_2d),
            'lon': (['lat', 'lon'], lon_2d),
            'height': height,
        },
        attrs={'analysis_time': analysis_time}
    )
    
    # Only add bounds if using conservative method
    if method == 'conservative':
        # Calculate grid cell bounds (required for conservative remapping)
        # GridRad uses regular lat/lon grid, so we can calculate bounds from centers
        dlon = float(data['x']['delta'])
        dlat = float(data['y']['delta'])
        
        # Create 1D bounds
        lon_b = np.concatenate([lon - dlon/2, [lon[-1] + dlon/2]])
        lat_b = np.concatenate([lat - dlat/2, [lat[-1] + dlat/2]])
        
        # Create 2D bounds for xESMF
        lon_b_2d, lat_b_2d = np.meshgrid(lon_b, lat_b)
        
        ds['lat_b'] = (['lat_b', 'lon_b'], lat_b_2d)
        ds['lon_b'] = (['lat_b', 'lon_b'], lon_b_2d)
    
    return ds


def get_weight_file(source_grid, dest_grid, method, weight_dir):
    """
    Generate or load existing weight file for regridding.
    
    Parameters
    ----------
    source_grid : xr.Dataset
        Source grid (GridRad)
    dest_grid : xr.Dataset
        Destination grid (HRRR)
    method : str
        Regridding method ('conservative' or 'bilinear')
    weight_dir : str
        Directory to store weight files
        
    Returns
    -------
    str
        Path to weight file
    """
    os.makedirs(weight_dir, exist_ok=True)
    
    # Create weight file name based on grid dimensions and method
    ny_src, nx_src = source_grid['lat'].shape
    ny_dst, nx_dst = dest_grid['lat'].shape
    weight_file = os.path.join(
        weight_dir, 
        f'gridrad_{ny_src}x{nx_src}_to_hrrr_{ny_dst}x{nx_dst}_{method}.nc'
    )
    
    return weight_file


def remap_gridrad_file(gridrad_file, dest_grid, method='conservative', 
                       output_dir=OUTPUT_DIR, weight_dir=WEIGHT_DIR):
    """
    Remap a single GridRad file to HRRR grid.
    
    Parameters
    ----------
    gridrad_file : str
        Path to GridRad NetCDF file
    dest_grid : xr.Dataset
        HRRR destination grid
    method : str
        Regridding method ('conservative' or 'bilinear')
    output_dir : str
        Output directory for remapped files
    weight_dir : str
        Directory for weight files
        
    Returns
    -------
    str
        Path to output file
    """
    print(f"Processing: {os.path.basename(gridrad_file)}")
    start_time = time.time()
    
    try:
        # Read GridRad data
        source_ds = gridrad_to_xarray(gridrad_file, method)
    except Exception as e:
        print(f"  ERROR reading GridRad file: {e}")
        raise
    
    # Get or create weight file
    weight_file = get_weight_file(source_ds, dest_grid, method, weight_dir)
    
    # Check if weight file exists
    weights_exist = os.path.isfile(weight_file)
    if weights_exist:
        print(f"  Using existing weight file: {os.path.basename(weight_file)}")
    else:
        print(f"  Creating weight file: {os.path.basename(weight_file)}")
    
    # Create regridder (creates or reuses weights based on file existence)
    regridder = xe.Regridder(
        source_ds, 
        dest_grid, 
        method,
        periodic=False,
        filename=weight_file,
        reuse_weights=weights_exist
    )
    
    # Extract number of heights
    n_heights = len(source_ds['height'])
    
    # Initialize output arrays
    missing_value = -999.
    ny_dst, nx_dst = dest_grid['lat'].shape
    zh_regrid = np.zeros((n_heights, ny_dst, nx_dst), dtype=np.float32)
    nobs_regrid = np.zeros((n_heights, ny_dst, nx_dst), dtype=np.int16)
    necho_regrid = np.zeros((n_heights, ny_dst, nx_dst), dtype=np.int16)
    wvalues_regrid = np.zeros((n_heights, ny_dst, nx_dst), dtype=np.float32)
    
    # Remap each height level
    for k in range(n_heights):
        # Remap reflectivity (in linear units)
        zh_regrid[k, :, :] = regridder(source_ds['zh'].isel(height=k))
        
        # Remap nobs, necho, wvalues
        nobs_regrid[k, :, :] = np.ceil(regridder(source_ds['nobs'].isel(height=k))).astype(np.int16)
        necho_regrid[k, :, :] = np.ceil(regridder(source_ds['necho'].isel(height=k))).astype(np.int16)
        wvalues_regrid[k, :, :] = regridder(source_ds['wvalues'].isel(height=k))
    
    # Convert reflectivity back to dBZ, using missing_value for missing/invalid values
    zh_regrid_dbz = dbz(zh_regrid, missing_value=missing_value)
    
    # Extract time information from analysis_time string
    analysis_time = source_ds.attrs['analysis_time']
    # Format: "2020-06-15 19:00:00Z" or "2020-06-15 19:00:00"
    time_str = analysis_time.replace(' ', 'T').replace(':', '').replace('-', '').replace('Z', '')
    
    # Get base_time (seconds since epoch)
    # Remove trailing 'Z' if present (UTC timezone indicator)
    analysis_time_clean = analysis_time.rstrip('Z').strip()
    dt = datetime.strptime(analysis_time_clean, '%Y-%m-%d %H:%M:%S')
    base_time = int(dt.timestamp())
    
    # Create output dataset
    ds_out = xr.Dataset(
        {
            'Reflectivity': (['time', 'height', 'y', 'x'], zh_regrid_dbz[np.newaxis, :, :, :]),
            'Nradobs': (['time', 'height', 'y', 'x'], nobs_regrid[np.newaxis, :, :, :]),
            'Nradecho': (['time', 'height', 'y', 'x'], necho_regrid[np.newaxis, :, :, :]),
            'wReflectivity': (['time', 'height', 'y', 'x'], wvalues_regrid[np.newaxis, :, :, :]),
        },
        coords={
            'base_time': (['time'], [base_time]),
            'latitude': (['y', 'x'], dest_grid['lat'].values),
            'longitude': (['y', 'x'], dest_grid['lon'].values),
            'height': source_ds['height'].values,
        },
        attrs={
            'title': 'GridRad reflectivity remapped to HRRR grid',
            'analysis_time': analysis_time,
            'remapping_method': method,
            'contact': 'Zhe Feng zhe.feng@pnnl.gov',
            'created_on': time.ctime(time.time()),
        }
    )
    
    # Add variable attributes
    ds_out['base_time'].attrs = {
        'long_name': 'Base time in Epoch',
        'units': 'seconds since 1970-01-01 00:00:00'
    }
    ds_out['longitude'].attrs = {
        'long_name': 'Longitude',
        'units': 'degrees_east'
    }
    ds_out['latitude'].attrs = {
        'long_name': 'Latitude',
        'units': 'degrees_north'
    }
    ds_out['height'].attrs = {
        'long_name': 'Height above sea level',
        'units': 'km'
    }
    ds_out['Reflectivity'].attrs = {
        'long_name': 'Radar Reflectivity',
        'units': 'dBZ',
        'missing_value': missing_value
    }
    ds_out['wReflectivity'].attrs = {
        'long_name': 'Reflectivity Bin Weights',
        'units': 'dimensionless'
    }
    ds_out['Nradobs'].attrs = {
        'long_name': 'Number of radar observations in grid box',
        'units': 'counts'
    }
    ds_out['Nradecho'].attrs = {
        'long_name': 'Number of radar echoes in grid box',
        'units': 'counts'
    }
    
    # Create output filename
    basename = os.path.basename(gridrad_file)
    # Extract timestamp: nexrad_3d_v4_2_20200615T190000Z.nc
    timestamp = basename.split('_')[-1].replace('.nc', '')
    output_file = os.path.join(output_dir, f'GridRad_HRRR_{timestamp}.nc')
    
    # Encoding for compression
    encoding = {
        'Reflectivity': {'zlib': True, 'complevel': 1, '_FillValue': missing_value, 'dtype': 'float32'},
        'Nradobs': {'zlib': True, 'complevel': 1, '_FillValue': 0, 'dtype': 'int16'},
        'Nradecho': {'zlib': True, 'complevel': 1, '_FillValue': 0, 'dtype': 'int16'},
        'wReflectivity': {'zlib': True, 'complevel': 1, '_FillValue': 0, 'dtype': 'float32'},
        'longitude': {'zlib': True, 'complevel': 1},
        'latitude': {'zlib': True, 'complevel': 1},
    }
    
    # Write output
    ds_out.to_netcdf(
        output_file,
        mode='w',
        format='NETCDF4',
        unlimited_dims='time',
        encoding=encoding
    )
    
    elapsed = time.time() - start_time
    print(f"  Completed in {elapsed:.1f}s: {os.path.basename(output_file)}")
    
    # Clean up
    regridder.clean_weight_file()
    del source_ds, ds_out, regridder
    
    return output_file


def process_files_serial(file_list, dest_grid, method, output_dir, weight_dir):
    """Process files in serial mode."""
    output_files = []
    for gridrad_file in file_list:
        try:
            out_file = remap_gridrad_file(
                gridrad_file, dest_grid, method, output_dir, weight_dir
            )
            output_files.append(out_file)
        except Exception as e:
            print(f"ERROR processing {gridrad_file}: {e}")
            continue
    return output_files


def process_files_parallel(file_list, dest_grid, method, output_dir, weight_dir, n_workers):
    """Process files in parallel using Dask."""
    print(f"\nStarting Dask cluster with {n_workers} workers...")
    
    # Create Dask cluster
    cluster = LocalCluster(
        n_workers=n_workers,
        threads_per_worker=1,
        memory_limit='8GB',
        silence_logs=False
    )
    client = Client(cluster)
    print(f"Dask dashboard: {client.dashboard_link}")
    
    # Submit tasks to Dask
    futures = []
    for gridrad_file in file_list:
        future = client.submit(
            remap_gridrad_file,
            gridrad_file,
            dest_grid,
            method,
            output_dir,
            weight_dir
        )
        futures.append(future)
    
    # Gather results with progress
    print(f"\nProcessing {len(futures)} files...")
    with ProgressBar():
        output_files = client.gather(futures)
    
    # Close cluster
    client.close()
    cluster.close()
    
    return output_files


def main():
    """Main processing function."""
    parser = argparse.ArgumentParser(
        description='Remap GridRad 3D reflectivity to HRRR grid using xESMF'
    )
    parser.add_argument(
        'input_pattern',
        help='Input file pattern (e.g., "/path/to/nexrad_3d*.nc" or single file)'
    )
    parser.add_argument(
        '-o', '--output-dir',
        default=OUTPUT_DIR,
        help=f'Output directory (default: {OUTPUT_DIR})'
    )
    parser.add_argument(
        '-m', '--method',
        default=REMAP_METHOD,
        choices=['conservative', 'bilinear'],
        help=f'Remapping method (default: {REMAP_METHOD})'
    )
    parser.add_argument(
        '-w', '--weight-dir',
        default=WEIGHT_DIR,
        help=f'Weight file directory (default: {WEIGHT_DIR})'
    )
    parser.add_argument(
        '-p', '--parallel',
        action='store_true',
        default=RUN_PARALLEL,
        help='Run in parallel using Dask'
    )
    parser.add_argument(
        '-s', '--serial',
        action='store_true',
        help='Run in serial mode (overrides --parallel)'
    )
    parser.add_argument(
        '-n', '--n-workers',
        type=int,
        default=N_WORKERS,
        help=f'Number of Dask workers (default: {N_WORKERS})'
    )
    parser.add_argument(
        '--hrrr-grid',
        default=HRRR_GRID_FILE,
        help=f'HRRR grid file (default: {HRRR_GRID_FILE})'
    )
    
    args = parser.parse_args()
    
    # Create output directories
    os.makedirs(args.output_dir, exist_ok=True)
    os.makedirs(args.weight_dir, exist_ok=True)
    
    # Get list of input files
    if os.path.isfile(args.input_pattern):
        file_list = [args.input_pattern]
    else:
        file_list = sorted(glob.glob(args.input_pattern))
    
    if len(file_list) == 0:
        print(f"ERROR: No files found matching: {args.input_pattern}")
        sys.exit(1)
    
    print("=" * 80)
    print("GridRad to HRRR Remapping")
    print("=" * 80)
    print(f"Input files: {len(file_list)}")
    print(f"HRRR grid: {args.hrrr_grid}")
    print(f"Remapping method: {args.method}")
    print(f"Output directory: {args.output_dir}")
    print(f"Weight directory: {args.weight_dir}")
    print(f"Parallel mode: {args.parallel and not args.serial}")
    if args.parallel and not args.serial:
        print(f"Number of workers: {args.n_workers}")
    print("=" * 80)
    
    # Load HRRR grid
    print("\nLoading HRRR grid...")
    dest_grid = load_hrrr_grid(args.hrrr_grid, args.method)
    print(f"  HRRR grid shape: {dest_grid['lat'].shape}")
    
    # Process files
    start_time = time.time()
    
    if args.serial or not args.parallel:
        print("\nProcessing files in SERIAL mode...")
        output_files = process_files_serial(
            file_list, dest_grid, args.method, args.output_dir, args.weight_dir
        )
    else:
        print("\nProcessing files in PARALLEL mode...")
        output_files = process_files_parallel(
            file_list, dest_grid, args.method, args.output_dir, args.weight_dir, args.n_workers
        )
    
    elapsed = time.time() - start_time
    
    print("\n" + "=" * 80)
    print(f"Processing complete!")
    print(f"Successfully processed: {len(output_files)} / {len(file_list)} files")
    print(f"Total time: {elapsed:.1f}s ({elapsed/60:.1f} min)")
    if len(output_files) > 0:
        print(f"Average time per file: {elapsed/len(output_files):.1f}s")
    print("=" * 80)


if __name__ == '__main__':
    main()
