#!/bin/bash
#SBATCH -A m1657
#SBATCH -J stats201001_201012
#SBATCH --qos=regular
#SBATCH --nodes=4
#SBATCH -C cpu
#SBATCH --time=02:00:00
#SBATCH --exclusive
#SBATCH --output=logs/log_stats201001_201012_%j.log

# The stats job of a chunk on several nodes (config/generate_tbpf_mcstracking_scripts.py --stats-nodes N): the links to the cloudid and track
# files of the months and the stitched track numbers first (serial, a few minutes), then trackstats ... speed over the whole chunk with
# run_parallel: 2. A Dask scheduler runs on the first node and 64 workers on every node (the scheduler file is the second argument
# of the run script). The serial steps (identifymcs, robustmcs) run on the first node while the others wait, so more nodes pay only when the
# parallel steps (trackstats, matchpf, mapfeature, speed) dominate.
date

module load python
source activate /global/common/software/m1867/python/pyflex26.3
export PYTHONPATH=/pscratch/sd/f/feng045/tbpf_code_a4b8ad8${PYTHONPATH:+:$PYTHONPATH}

# Join the periods of this chunk: one folder with links to their files, the stitched tracknumbers file (--require-seams: a boundary
# without a shared cloudid file would restart the tracks there, the job stops instead)
python /pscratch/sd/f/feng045/tbpf_code_a4b8ad8/runscripts/link_period_folders.py /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/tracking/campaign_201001_201012 /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/tracking/2010-01/ /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/tracking/2010-02/ /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/tracking/2010-03/ /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/tracking/2010-04/ /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/tracking/2010-05/ /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/tracking/2010-06/ /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/tracking/2010-07/ /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/tracking/2010-08/ /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/tracking/2010-09/ /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/tracking/2010-10/ /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/tracking/2010-11/ /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/tracking/2010-12/ || exit 1
python /pscratch/sd/f/feng045/tbpf_code_a4b8ad8/runscripts/stitch_tracknumbers.py /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/stats/tracknumbers_20100101.0000_20110101.0000.nc /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/stats/tracknumbers_20100101.0000_20100201.0000.nc /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/stats/tracknumbers_20100201.0000_20100301.0000.nc /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/stats/tracknumbers_20100301.0000_20100401.0000.nc /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/stats/tracknumbers_20100401.0000_20100501.0000.nc /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/stats/tracknumbers_20100501.0000_20100601.0000.nc /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/stats/tracknumbers_20100601.0000_20100701.0000.nc /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/stats/tracknumbers_20100701.0000_20100801.0000.nc /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/stats/tracknumbers_20100801.0000_20100901.0000.nc /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/stats/tracknumbers_20100901.0000_20101001.0000.nc /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/stats/tracknumbers_20101001.0000_20101101.0000.nc /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/stats/tracknumbers_20101101.0000_20101201.0000.nc /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/stats/tracknumbers_20101201.0000_20110101.0000.nc --tracking-dirs /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/tracking/2010-01/ /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/tracking/2010-02/ /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/tracking/2010-03/ /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/tracking/2010-04/ /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/tracking/2010-05/ /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/tracking/2010-06/ /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/tracking/2010-07/ /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/tracking/2010-08/ /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/tracking/2010-09/ /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/tracking/2010-10/ /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/tracking/2010-11/ /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/2010/tracking/2010-12/ --require-seams || exit 1
ulimit -n 32000
export DASK_DISTRIBUTED__COMM__TIMEOUTS__CONNECT=360s
export DASK_DISTRIBUTED__COMM__TIMEOUTS__TCP=360s
workers_per_node=64
scheduler_file=$SCRATCH/scheduler_${SLURM_JOB_ID}.json
rm -f $scheduler_file

dask-scheduler --scheduler-file=$scheduler_file > logs/dask_scheduler_${SLURM_JOB_ID}.log 2>&1 &
until [ -s $scheduler_file ]; do sleep 2; done
srun --kill-on-bad-exit=0 -N $SLURM_NNODES --ntasks-per-node=$workers_per_node --cpus-per-task=2 --cpu-bind=cores \
    dask-worker --scheduler-file=$scheduler_file --nthreads 1 --memory-limit=7GB --local-directory=/tmp \
    --worker-class distributed.Worker > logs/dask_workers_${SLURM_JOB_ID}.log 2>&1 &
# the run starts when all the workers are there (10 min at most)
python -c "
from dask.distributed import Client
client = Client(scheduler_file='$scheduler_file', timeout=120)
client.wait_for_workers($workers_per_node * $SLURM_NNODES, timeout=600)
client.close()"
status=$?
if [ $status -ne 0 ]; then
    echo "the Dask workers did not connect"
    exit $status
fi

# the exit status of python (not of the last date) is the exit status of the job, so a failed step shows as FAILED in sacct
python /pscratch/sd/f/feng045/tbpf_code_a4b8ad8/runscripts/run_mcs_tbpf_unified.py /pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf/campaign_2010/config_mcs_tbpf_e3sm_ne30_0p1deg_template_stats201001_201012.yml $scheduler_file
status=$?

date
exit $status
