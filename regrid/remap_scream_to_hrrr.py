"""
Remap E3SM SCREAM spectral element grid data to HRRR Lambert Conformal grid.

This script uses xESMF to remap SCREAM outputs (~3.25 km unstructured grid) 
to the HRRR grid (~3 km structured grid) over CONUS using bilinear interpolation.

Author: Generated for SCREAM to HRRR remapping
Date: 2026-01-26
"""

import xarray as xr
import xesmf as xe
import numpy as np
from pathlib import Path
import sys
import time
import psutil
import os
import argparse

# Input/Output file paths
SCREAM_FILE = '/pscratch/sd/w/wcmca1/SCREAMv1-cess2/run_conus/output.scream.diag_equiv_reflectivity.5min.INSTANT.nmins_x5.2020-06-06-79500.nc'
HRRR_GRID_FILE = '/global/cfs/cdirs/m1657/zfeng/SEUS/hrrr_sfc_latlon.nc'
OUTPUT_DIR = '/pscratch/sd/w/wcmca1/SCREAMv1-cess2/remap_conus'
WEIGHT_DIR = '/pscratch/sd/w/wcmca1/SCREAMv1-cess2/maps'


def load_scream_grid(scream_file):
    """
    Load SCREAM data and prepare grid for xESMF.
    Convert lat/lon from radians to degrees.
    
    Parameters
    ----------
    scream_file : str
        Path to SCREAM output file
        
    Returns
    -------
    ds : xarray.Dataset
        SCREAM dataset with lat/lon in degrees
    grid_in : xarray.Dataset
        Source grid for xESMF (lat, lon in degrees)
    """
    print(f"Loading SCREAM data from: {scream_file}")
    ds = xr.open_dataset(scream_file)
    
    # Extract lat/lon (already in degrees)
    lat_deg = ds['lat'].values
    lon_deg = ds['lon'].values
    
    # Create source grid dataset for xESMF
    # For unstructured grids, xESMF expects 1D lat/lon arrays
    grid_in = xr.Dataset({
        'lat': (['ncol'], lat_deg),
        'lon': (['ncol'], lon_deg)
    })
    
    print(f"  SCREAM grid: ncol={len(ds.ncol)}, lev={len(ds.lev)}, time={len(ds.time)}")
    print(f"  Lat range: {lat_deg.min():.2f} to {lat_deg.max():.2f} degrees")
    print(f"  Lon range: {lon_deg.min():.2f} to {lon_deg.max():.2f} degrees")
    
    print_memory_usage("After loading SCREAM")
    
    return ds, grid_in


def load_hrrr_grid(hrrr_grid_file):
    """
    Load HRRR grid.
    
    Parameters
    ----------
    hrrr_grid_file : str
        Path to HRRR grid file with lat/lon
        
    Returns
    -------
    grid_out : xarray.Dataset
        Target grid for xESMF
    """
    print(f"\nLoading HRRR grid from: {hrrr_grid_file}")
    ds_hrrr = xr.open_dataset(hrrr_grid_file)
    
    # For structured grids, xESMF expects 2D lat/lon arrays
    grid_out = xr.Dataset({
        'lat': (['y', 'x'], ds_hrrr['latitude'].values),
        'lon': (['y', 'x'], ds_hrrr['longitude'].values)
    })
    
    print(f"  HRRR grid: y={len(ds_hrrr.y)}, x={len(ds_hrrr.x)}")
    print(f"  Lat range: {ds_hrrr['latitude'].min().values:.2f} to {ds_hrrr['latitude'].max().values:.2f} degrees")
    print(f"  Lon range: {ds_hrrr['longitude'].min().values:.2f} to {ds_hrrr['longitude'].max().values:.2f} degrees")
    
    print_memory_usage("After loading HRRR")
    
    return grid_out


def print_memory_usage(label=""):
    """Print current memory usage."""
    process = psutil.Process()
    mem_gb = process.memory_info().rss / 1024**3
    mem_percent = process.memory_percent()
    print(f"  [{label}] Memory usage: {mem_gb:.2f} GB ({mem_percent:.1f}%)")
    
    # System memory
    vm = psutil.virtual_memory()
    sys_mem_gb = vm.used / 1024**3
    sys_mem_total_gb = vm.total / 1024**3
    sys_mem_percent = vm.percent
    print(f"  [{label}] System memory: {sys_mem_gb:.2f} / {sys_mem_total_gb:.2f} GB ({sys_mem_percent:.1f}%)")


def create_regridder(grid_in, grid_out, weight_file, method='bilinear', parallel=True):
    """
    Create xESMF regridder object.
    
    Parameters
    ----------
    grid_in : xarray.Dataset
        Source grid
    grid_out : xarray.Dataset
        Target grid
    weight_file : str
        Path to save/load weights file
    method : str, optional
        Interpolation method (default: 'bilinear')
    parallel : bool, optional
        Whether to use parallel weight generation (default: True)
        
    Returns
    -------
    regridder : xesmf.Regridder
        Regridder object
    """
    print(f"\nCreating xESMF regridder with {method} interpolation...")
    print_memory_usage("Before regridder")
    
    # Check if weights file exists
    weight_path = Path(weight_file)
    if weight_path.exists():
        print(f"  Reusing existing weights from: {weight_file}")
        reuse_weights = True
        use_parallel = False  # Parallel not used when reusing weights
    else:
        print(f"  Computing new weights, will save to: {weight_file}")
        print(f"  Parallel weight generation: {parallel}")
        print(f"  Number of CPUs available: {os.cpu_count()}")
        reuse_weights = False  # Must be False to compute new weights
        use_parallel = parallel
    
    # Ensure output directory exists
    weight_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Create regridder
    print(f"  Grid sizes: source={len(grid_in.lat)}, target={len(grid_out.lat.values.flatten())}")
    start_time = time.time()
    import pdb; pdb.set_trace()
    try:
        if weight_path.exists():
            # Use pre-existing weight file (e.g., from ESMF_RegridWeightGen)
            print(f"  Loading existing weight file at {time.strftime('%Y-%m-%d %H:%M:%S')}")
            regridder = xe.Regridder(
                grid_in, 
                grid_out, 
                method=method,
                weights=str(weight_file)  # Use pre-computed weights
            )
        else:
            # Generate new weights
            print(f"  Starting weight generation at {time.strftime('%Y-%m-%d %H:%M:%S')}")
            regridder = xe.Regridder(
                grid_in, 
                grid_out, 
                method=method,
                filename=weight_file,
                reuse_weights=False,  # Must be False to compute new weights
                periodic=False,  # Not periodic in longitude for regional domain
                ignore_degenerate=True,  # Handle degenerate cells
                parallel=use_parallel,  # Use parallel weight generation
                unmapped_to_nan=True  # Set unmapped points to NaN
            )
        
        elapsed = time.time() - start_time
        if weight_path.exists():
            print(f"  Weight file loaded in {elapsed:.1f} seconds")
        else:
            print(f"  Weight generation completed in {elapsed:.1f} seconds ({elapsed/60:.1f} minutes)")
        print_memory_usage("After regridder")
        
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"  ERROR: Weight generation failed after {elapsed:.1f} seconds")
        print_memory_usage("At failure")
        raise e
    
    print("  Regridder created successfully")
    return regridder


def remap_variable(ds_scream, regridder, var_name='diag_equiv_reflectivity'):
    """
    Remap a 3D variable (time, ncol, lev) to the target grid.
    
    Parameters
    ----------
    ds_scream : xarray.Dataset
        SCREAM dataset
    regridder : xesmf.Regridder
        Regridder object
    var_name : str, optional
        Variable name to remap
        
    Returns
    -------
    ds_out : xarray.Dataset
        Remapped dataset
    """
    print(f"\nRemapping variable: {var_name}")
    
    var_data = ds_scream[var_name]
    print(f"  Input shape: {var_data.shape}")
    print(f"  Dimensions: {var_data.dims}")
    
    # xESMF can handle 3D data (time, ncol, lev)
    # It will remap the ncol dimension while preserving time and lev
    var_remapped = regridder(var_data, keep_attrs=True)
    
    print(f"  Output shape: {var_remapped.shape}")
    print(f"  Output dimensions: {var_remapped.dims}")
    
    # Create output dataset
    ds_out = xr.Dataset({
        var_name: var_remapped
    })
    
    # Copy time and lev coordinates
    ds_out['time'] = ds_scream['time']
    ds_out['lev'] = ds_scream['lev']
    
    # Add global attributes
    ds_out.attrs['title'] = 'SCREAM data remapped to HRRR grid'
    ds_out.attrs['source'] = str(SCREAM_FILE)
    ds_out.attrs['target_grid'] = str(HRRR_GRID_FILE)
    ds_out.attrs['regridding_method'] = regridder.method
    ds_out.attrs['created_with'] = 'xESMF'
    
    return ds_out


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Remap E3SM SCREAM data to HRRR grid using xESMF',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Available interpolation methods:
  bilinear       - Bilinear interpolation (default, most accurate but memory intensive)
  conservative   - Conservative remapping (preserves integrals)
  nearest_s2d    - Nearest neighbor (fast, less memory, less accurate)
  nearest_d2s    - Nearest neighbor destination to source
  patch          - Higher order patch recovery

Examples:
  python remap_scream_to_hrrr.py
  python remap_scream_to_hrrr.py --method nearest_s2d
  python remap_scream_to_hrrr.py --method bilinear --no-parallel
        """
    )
    
    parser.add_argument(
        '--method', '-m',
        type=str,
        default='bilinear',
        choices=['bilinear', 'conservative', 'nearest_s2d', 'nearest_d2s', 'patch'],
        help='Interpolation method (default: bilinear)'
    )
    
    parser.add_argument(
        '--parallel', '-p',
        action='store_true',
        default=True,
        help='Use parallel weight generation (default: True)'
    )
    
    parser.add_argument(
        '--no-parallel',
        action='store_false',
        dest='parallel',
        help='Disable parallel weight generation'
    )
    
    return parser.parse_args()


def main():
    """Main execution function."""
    # Parse command line arguments
    args = parse_arguments()
    
    # Set up file paths based on method
    method = args.method
    # weight_file = Path(WEIGHT_DIR) / f'weights_scream_to_hrrr_{method}.nc'
    weight_file = Path(WEIGHT_DIR) / f'SCREAM_CONUS_ne1024_to_HRRR_{method}.nc'
    output_file = Path(OUTPUT_DIR) / f'scream_reflectivity_hrrr_grid_{method}.nc'
    
    print("="*70)
    print("SCREAM to HRRR Grid Remapping")
    print("="*70)
    print(f"  Interpolation method: {method}")
    print(f"  Parallel processing: {args.parallel}")
    print(f"  Weight file: {weight_file}")
    print(f"  Output file: {output_file}")
    print("="*70)
    
    # Check if input files exist
    if not Path(SCREAM_FILE).exists():
        print(f"ERROR: SCREAM file not found: {SCREAM_FILE}")
        sys.exit(1)
    if not Path(HRRR_GRID_FILE).exists():
        print(f"ERROR: HRRR grid file not found: {HRRR_GRID_FILE}")
        sys.exit(1)
    
    # Ensure output directories exist
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    Path(WEIGHT_DIR).mkdir(parents=True, exist_ok=True)
    
    # Load grids
    ds_scream, grid_in = load_scream_grid(SCREAM_FILE)
    grid_out = load_hrrr_grid(HRRR_GRID_FILE)

    # Create regridder
    regridder = create_regridder(grid_in, grid_out, str(weight_file), method=method, parallel=args.parallel)
    
    # Remap the reflectivity variable
    ds_out = remap_variable(ds_scream, regridder, var_name='diag_equiv_reflectivity')
    
    print_memory_usage("After remapping")
    
    # Save output
    print(f"\nSaving remapped data to: {output_file}")
    encoding = {
        'diag_equiv_reflectivity': {
            'zlib': True,
            'complevel': 4,
            'dtype': 'float32'
        }
    }
    ds_out.to_netcdf(str(output_file), encoding=encoding)
    print("  Done!")
    
    # Close datasets
    ds_scream.close()
    ds_out.close()
    
    print("\n" + "="*70)
    print("Remapping completed successfully!")
    print(f"  Method: {method}")
    print(f"  Output file: {output_file}")
    print(f"  Weight file: {weight_file}")
    print("="*70)


if __name__ == '__main__':
    main()
