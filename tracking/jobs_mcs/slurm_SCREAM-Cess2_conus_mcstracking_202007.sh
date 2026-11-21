#!/bin/bash
#SBATCH -A m1657
#SBATCH -J MCSSCREAM202007
#SBATCH --qos=regular
#SBATCH --nodes=1
#SBATCH -C cpu
#SBATCH --time=16:00:00
#SBATCH --exclusive
#SBATCH --mail-user=zhe.feng@pnnl.gov
#SBATCH --mail-type=END,FAIL
#SBATCH --output=logs/log_SCREAM-Cess2_conus_mcstracking_202007.log
date

module load python
source activate /global/common/software/m1867/python/pyflex26.3

# SCREAM input: 128 levels, about 600 MB per 5-minute frame (MRMS: 33 levels), 8,640-8,928 frames per month.
# Time per step (minutes, one node, 64 workers, input read from scratch, measured 2026-10-11 on 1 and 3 days) and the
# estimate for a 31-day month (8,928 frames). The month is an extrapolation, not a measured run.
#
#   step          1 day (288)   3 days (864)   month: linear   month: power law of the 1- and 3-day points
#   ------------  ------------  -------------  --------------  ------------------------------------------
#   idfeature         5.4           14.2           2.4 h           2.4 h   (1.0 frames/s, limited by reading 600 MB per frame)
#   tracksingle       1.9            3.6           0.6 h           0.6 h
#   gettracks         3.2            6.2           1.1 h           1.1 h   serial
#   trackstats        2.6            7.5           1.3 h           1.3 h
#   identifymcs       1.9            6.8           1.2 h           1.7 h   serial
#   regionprops       2.3           11.4           2.0 h           5.7 h   grows faster than the number of frames
#   mapfeature        1.0            2.9           0.5 h           0.5 h
#   speed             0.7            2.0           0.3 h           0.3 h
#   total            19.2           54.7           9.5 h          13.7 h
#
# Memory: 64 workers, largest worker 5.0 GB, all workers 236 GB, node peak 237 GB of 512 GB, main process 16 GB (3 days).
# 128 workers would not fit in idfeature (5 GB each); 32 workers were 10 % slower in total on 1 day (idfeature is limited by reading).
# Wallclock: 16 h (1.2 x the upper estimate). MRMS (33 levels) takes 3 h 35 min per month: SCREAM is 3-4 x slower per month.
# To stay below 8 h the month would have to be split into jobs per step (run_* flags in the config: idfeature alone about 2.5 h).
#
# Single node: the run script starts its own Dask LocalCluster (run_parallel: 1, nprocesses in the config)
# the exit status of python (not of the last date) is the exit status of the job, so a failed step shows as FAILED in sacct
python /global/homes/f/feng045/program/PyFLEXTRKR-dev/runscripts/run_mcs_radar3d.py /global/u1/f/feng045/program/scream/tracking/jobs_mcs/config_mcs_3km_SCREAMv1-Cess2_monthly_202007.yaml
status=$?

date
exit $status
