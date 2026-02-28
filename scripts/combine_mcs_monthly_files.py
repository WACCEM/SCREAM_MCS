import numpy as np
import glob
import xarray as xr

rootdir = "/pscratch/sd/w/wcmca1/"

dir_map = {
    # 'obs': 'IMERGv7',
    # 'm1': 'icon_d3hp003',
    'm2': 'SCREAMv1-cess2',
}
zoom = 'hp8'

# Loop over each source
for model in dir_map.keys():
    # Set input/output directories and files
    indir = f"{rootdir}{dir_map[model]}/mcs/stats/monthly/"
    outdir = indir
    outfile = f"{outdir}mcs_monthly_rainmap_{zoom}.nc"
    infiles = sorted(glob.glob(f"{indir}mcs_monthly_rainmap_{zoom}_20*.nc"))

    # Skip if no files found
    if len(infiles) == 0:
        print(f"No files found for {dir_map[model]}, skipping...")
        continue
    else:
        # Read and concatenate data
        print(f"Processing {len(infiles)} files for {model}...")
        ds = xr.open_mfdataset(infiles, concat_dim='time', combine='nested')
        
        fillvalue = np.nan
        # Set encoding/compression for all variables
        comp = dict(zlib=True, _FillValue=fillvalue, dtype='float32')
        encoding = {var: comp for var in ds.data_vars}
        
        # Write to NetCDF - THIS IS WHERE COMPUTATION ACTUALLY HAPPENS!
        print("Writing to NetCDF...")
        ds.to_netcdf(path=outfile, mode='w', format='NETCDF4', unlimited_dims='time', encoding=encoding)
        print(f"Output written to: {outfile}")
