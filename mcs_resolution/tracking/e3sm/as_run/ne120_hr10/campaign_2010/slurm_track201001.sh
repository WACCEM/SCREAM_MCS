#!/bin/bash
#SBATCH -A m1657
#SBATCH -J track201001
#SBATCH --qos=regular
#SBATCH --nodes=1
#SBATCH -C cpu
#SBATCH --time=01:00:00
#SBATCH --exclusive
#SBATCH --output=logs/log_track201001_%j.log

# One node, one job of config/generate_tbpf_mcstracking_scripts.py: a track job (idfeature, tracksingle, gettracks of one month), the
# plain job of a chunk of one month (all steps), or a stats job on one node (--stats-nodes 1: the links and the stitched track numbers of
# its chunk first, then trackstats ... speed over the whole chunk). The run script starts its own Dask LocalCluster (run_parallel: 1 and
# nprocesses in the config). The filled copies of this template are written by the generator, which says what each job does.
date

module load python
source activate /global/common/software/m1867/python/pyflex26.3
export PYTHONPATH=/pscratch/sd/f/feng045/tbpf_code_a4b8ad8${PYTHONPATH:+:$PYTHONPATH}

# the exit status of python (not of the last date) is the exit status of the job, so a failed step shows as FAILED in sacct
python /pscratch/sd/f/feng045/tbpf_code_a4b8ad8/runscripts/run_mcs_tbpf_unified.py /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/campaign_2010/config_mcs_tbpf_e3sm_0p1deg_template_track201001.yml
status=$?

date
exit $status
