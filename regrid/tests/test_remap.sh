#!/bin/sh

# Import needed modules 
# module load climate-utils
# alias loade3sm='source /global/common/software/e3sm/anaconda_envs/load_latest_e3sm_unified_pm-cpu.sh'
# module loade3sm
source /global/common/software/e3sm/anaconda_envs/load_latest_e3sm_unified_pm-cpu.sh

# mapfile='/pscratch/sd/w/wcmca1/SCREAMv1-cess2/maps/SCREAM_CONUS_ne1024_to_HRRR_neareststod.nc'
mapfile='/pscratch/sd/w/wcmca1/SCREAMv1-cess2/maps/SCREAM_CONUS_ne1024_to_HRRR_bilinear.nc'
# mapfile='/pscratch/sd/w/wcmca1/SCREAMv1-cess2/maps/SCREAM_CONUS_ne1024_to_HRRR_conserve.nc'
# mapfile='/pscratch/sd/w/wcmca1/SCREAMv1-cess2/maps/SCREAM_CONUS_ne1024_to_HRRR_conserve.nc'
# in_file="/pscratch/sd/w/wcmca1/SCREAMv1-cess2/run_conus/output.scream.2D.5min.INSTANT.nmins_x5.2020-06-07-00300.nc"
# in_file="/pscratch/sd/w/wcmca1/SCREAMv1-cess2/run_conus/output.scream.diag_equiv_reflectivity.5min.INSTANT.nmins_x5.2020-06-06-79500.nc"
# out_file="/pscratch/sd/w/wcmca1/SCREAMv1-cess2/remap_conus/scream.diag_equiv_reflectivity.5min.INSTANT.nmins_x5.2020-06-06-79500_bilinear.nc"

in_file="/pscratch/sd/w/wcmca1/SCREAMv1-cess2/run_conus/output.scream.z_mid_p_mid.5min.INSTANT.nmins_x5.2020-06-07-00300.nc"
out_file="/pscratch/sd/w/wcmca1/SCREAMv1-cess2/remap_conus/scream.z_mid_p_mid.5min.INSTANT.nmins_x5.2020-06-07-00300.nc"

# Remap precipitation variable for a single file
# ncremap --no_stdin -v precipitation -m $weight_map $drc_in $drc_pr 
# Note that here, only the 'precipitation' variable is selected for regridding, can remove this field to regrid entire file 
# ncremap --no_stdin -v diag_equiv_reflectivity -m '/pscratch/sd/w/wcmca1/SCREAMv1-cess2/maps/SCREAM_CONUS_ne1024_to_HRRR_neareststod.nc' "/pscratch/sd/w/wcmca1/SCREAMv1-cess2/run_conus/output.scream.diag_equiv_reflectivity.5min.INSTANT.nmins_x5.2020-06-06-79500.nc" '/pscratch/sd/w/wcmca1/SCREAMv1-cess2/remap_conus/scream.diag_equiv_reflectivity.5min.INSTANT.nmins_x5.2020-06-06-79500.nc'
# ncremap --no_stdin -v LW_flux_up_at_model_top -R '--rgr lat_nm_in=lat --rgr lon_nm_out=lon' -m $mapfile $in_file $out_file
ncremap -P eamxx --no_stdin -m $mapfile $in_file $out_file