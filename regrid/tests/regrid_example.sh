#!/bin/sh

# Import needed modules 
module load climate-utils
alias loade3sm='source /global/common/software/e3sm/anaconda_envs/load_latest_e3sm_unified_pm-cpu.sh'
module loade3sm

# Need to comment the lines 27, 31, 32 in the NCLtomakeSCRIP.ncl script so that it accepts the command-line options for the gridname, inputdir, and latlonfile variables.
# Generate input SCRIP
# Need to run the below command twice, one for each of the SCRIP files you want to generate 
# Change the three variables to point to your own directories and choose your own gridname 
ncl NCLtomakeSCRIP.ncl 'gridname="ERA5-025"' 'inputdir="/pscratch/sd/s/smheflin/pyflex_era5_20/mcstracking/20200101.0000_20201231.0000/"' 'latlonfile="mcstrack_20200701_100000.nc"'  

# Generate output SCRIP 
# Change the three variables to point to your own directories and choose your own gridname 
ncl NCLtomakeSCRIP.ncl 'gridname="IMERG-01"' 'inputdir="/pscratch/sd/f/feng045/waccem/mcs_global/mcstracking_orig/20200101.0000_20210101.0000/"' 'latlonfile="mcstrack_20200701_1030.nc"'

# NOTE: The latlonfiles above do not need to be identical or the desired files for regridding, they just need to have the same latitude and longitude grids as the files used in the regridding process

# NOTE: The below remapping step should take a minute or two

# Create a conservative set of remapping weights, can specify weight type by changing 'conserve' to other commands, see https://acme-climate.atlassian.net/wiki/spaces/DOC/pages/754286611/Regridding+E3SM+Data+with+ncremap (bilinear, aave etc.)
# Use SCRIP files generated above as source (-s) and destination (-d) 
# Specify path for weight file (-w) 
ESMF_RegridWeightGen --64bit_offset --check --ignore_degenerate --ignore_unmapped -s '/pscratch/sd/s/smheflin/esmf/SCRIP_IMERG-01.nc' -d '/pscratch/sd/s/smheflin/esmf/SCRIP_ERA5-025.nc' -w '/pscratch/sd/s/smheflin/test_weights.nc' -m conserve

# These files may have FillValue attributes as "NaN" which can throw off the results
# Change input file _FillValues to normal IEEE floats  
# Note that in order for this step to work, first file path should be file you want to regrid, and the second should point to where you want to store a version of this file with a changed FillValue attribute
ncatted -a _FillValue,precipitation,m,f,1.0e36 /pscratch/sd/f/feng045/waccem/mcs_global/mcstracking_orig/20200101.0000_20210101.0000/mcstrack_20200701_1030.nc /pscratch/sd/s/smheflin/mcstrack_20200701_1030_noNAN.nc 

# Remap precipitation variable for a single file
# ncremap --no_stdin -v precipitation -m $weight_map $drc_in $drc_pr 
# Note that here, only the 'precipitation' variable is selected for regridding, can remove this field to regrid entire file 
ncremap --no_stdin -v precipitation -m '/pscratch/sd/s/smheflin/test_weights.nc' "/pscratch/sd/s/smheflin/mcstrack_20200701_1030_noNAN.nc" '/pscratch/sd/s/smheflin/test_regrid025/mcstrack_20200701_1030.nc'