#!/bin/bash
# These environment variables are used by the remapping scripts to locate input files, 
# specify output locations, and define remapping parameters. 
# To use these variables, source this script in your shell before running the remapping scripts:
#   source env_vars.sh

# Environment variables for remapping MRMS reflectivity to MergedIR grid
export IN_DIR=/pscratch/sd/i/iclas2/meng/mrms/conus_2025_netcdf/MRMS_MergedReflectivityQC_L33
export OUT_DIR=/pscratch/sd/i/iclas2/MRMS/remap_mergedir
export TMP_DIR=/pscratch/sd/i/iclas2/MRMS/tmp
export WEIGHT_FILE=/pscratch/sd/w/wcmca1/SCREAMv1-cess2/maps/MRMS_to_MergedIR_bilinear.nc
export OUT_PREFIX=MRMS_MergedReflectivityQC_L33

# # Environment variables for remapping MRMS QPE to MergedIR grid
# export IN_DIR=/pscratch/sd/i/iclas2/meng/mrms/conus_2025_netcdf/MultiSensor_QPE_01H_Pass2_00.00
# export OUT_DIR=/pscratch/sd/i/iclas2/MRMS/remap_QPE1H_mergedir
# export TMP_DIR=/pscratch/sd/i/iclas2/MRMS/tmp
# export WEIGHT_FILE=/pscratch/sd/w/wcmca1/SCREAMv1-cess2/maps/MRMS_to_MergedIR_conserve.nc
# export OUT_PREFIX=MRMS_MultiSensor_QPE_01H_Pass2_00.00