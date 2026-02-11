#!/usr/bin/env python

import os
from glob import glob 
import subprocess as sp 
import pandas as pd 
import xarray as xr 
import multiprocessing as mp
from functools import partial 
import json 
import argparse 
import warnings
warnings.filterwarnings("ignore")


parser = argparse.ArgumentParser()
parser.add_argument("--offset", type=int, default=0)
parser.add_argument("--count", type=int, default=30)
parser.add_argument("--nproc", type=int, default=12)
args = parser.parse_args()

def convert_grib2_to_netcdf(time, workdir, outdir, heights):
    outpath = os.path.join(outdir, f'MRMS_MergedReflectivityQC_L33_{time}.nc')
    if os.path.exists(outpath):
        print(f"{outpath} already exists, skipping.")
        return
    else:
        uncompressed_files = [glob(f'{workdir}/MergedReflectivityQC_{z}/MRMS_MergedReflectivityQC_{z}_{time[:-2]}??.grib2')[0] for z in heights]
        uncompress = [sp.run(f"gunzip {f}.gz", shell=True) for f in uncompressed_files if not os.path.exists(f)]
        infiles = [f for f in uncompressed_files]
        
        # Read and combine files
        # Note: requires Xarray to have cfgrib engine installed
        ds = xr.open_mfdataset(infiles, concat_dim='heightAboveSea', combine='nested')     
        ds = ds.rename({'unknown': 'Reflectivity'})

        ds['Reflectivity'] = ds['Reflectivity'].expand_dims('time') 
        ds['Reflectivity'].attrs['_NoEchoValue'] = -99.
        ds['Reflectivity'].attrs['units'] = 'dBZ'
        ds['Reflectivity'].attrs['long_name'] = 'MergedReflectivityQC' 
        ds['Reflectivity'].attrs['standard_name'] = 'MergedReflectivityQC'
        attrs_to_remove = [attr for attr in ds['Reflectivity'].attrs if attr.startswith('GRIB')]
        for attr in attrs_to_remove:
            del ds['Reflectivity'].attrs[attr]
            
        ds['time'] = [pd.to_datetime(time, format='%Y%m%d-%H%M%S')]
        dsout = ds.drop_vars([v for v in ds.coords if v not in ['time', 'longitude', 'latitude', 'heightAboveSea']])

        comp = {'_FillValue': -999, 'zlib': True, 'complevel': 1, 'shuffle': True}
        encoding = {var: comp for var in dsout.variables}        
        dsout.to_netcdf(outpath, encoding=encoding, unlimited_dims='time') 
        print(f"Saved {outpath}") 


case ='CONUS_2025'
workdir = '/pscratch/sd/i/iclas2/meng/mrms'
heights = [
    '00.50', '00.75', '01.00', '01.25', '01.50', '01.75', '02.00', '02.25', '02.50', '02.75', 
    '03.00', '03.50', '04.00', '04.50', '05.00', '05.50', '06.00', '06.50', '07.00', '07.50',
    '08.00', '08.50', '09.00', '10.00', '11.00', '12.00', '13.00', '14.00', '15.00', '16.00',
    '17.00', '18.00', '19.00'
]

with open(f'{workdir}/{case}/MergedReflectivityQC_{heights[0]}/keys.json') as f:
    items = json.load(f)
files = items[args.offset:args.offset+args.count]
times = [os.path.basename(f)[-24:-9] for f in files] 
outdir = os.path.join(f'{workdir}/{case.lower()}_netcdf', 'tmp') #
os.makedirs(outdir, exist_ok=True) 

worker_func = partial(convert_grib2_to_netcdf, workdir=f'{workdir}/{case}', heights=heights, outdir=outdir)
num_workers = args.nproc  #mp.cpu_count()//2 
with mp.Pool(num_workers) as pool:
    pool.imap(worker_func, times)
    pool.close()
    pool.join() 