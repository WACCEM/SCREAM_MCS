#!/bin/bash
#SBATCH -A m1657
#SBATCH -J hr2p0_ne120_2011
#SBATCH --qos=regular
#SBATCH --nodes=1
#SBATCH -C cpu
#SBATCH --time=03:00:00
#SBATCH --exclusive
#SBATCH --output=/pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf_hr2p0/campaign_2011/logs/log_%x_%j.log

# production run of the E3SM ne120 year 2011 with 2.0 mm/h (gen_heavyrain_sensitivity.py --production): matchpf, robustmcs,
# mapfeature, speed, dense_netcdf, rainmap and trackpcp on one node (the run script starts its own Dask LocalCluster, run_parallel: 1).
# The code is the pinned worktree /pscratch/sd/f/feng045/tbpf_code_38ae5d1.
date

module load python
source activate /global/common/software/m1867/python/pyflex26.3
export PYTHONPATH=/pscratch/sd/f/feng045/tbpf_code_38ae5d1${PYTHONPATH:+:$PYTHONPATH}

# the exit status of python (not of the last date) is the exit status of the job, so a failed step shows as FAILED in sacct
python /pscratch/sd/f/feng045/tbpf_code_38ae5d1/runscripts/run_mcs_tbpf_unified.py /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf_hr2p0/campaign_2011/config_ne120_2011_hr2p0.yml
status=$?

date
exit $status
