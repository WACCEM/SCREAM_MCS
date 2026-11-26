#!/bin/bash
#SBATCH -A m1657
#SBATCH -J stats201101_201112
#SBATCH --qos=regular
#SBATCH --nodes=4
#SBATCH -C cpu
#SBATCH --time=02:00:00
#SBATCH --exclusive
#SBATCH --output=logs/log_stats201101_201112_%j.log

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
python /pscratch/sd/f/feng045/tbpf_code_a4b8ad8/runscripts/link_period_folders.py /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/tracking/campaign_201101_201112 /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/tracking/2011-01/ /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/tracking/2011-02/ /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/tracking/2011-03/ /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/tracking/2011-04/ /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/tracking/2011-05/ /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/tracking/2011-06/ /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/tracking/2011-07/ /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/tracking/2011-08/ /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/tracking/2011-09/ /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/tracking/2011-10/ /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/tracking/2011-11/ /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/tracking/2011-12/ || exit 1
python /pscratch/sd/f/feng045/tbpf_code_a4b8ad8/runscripts/stitch_tracknumbers.py /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/stats/tracknumbers_20110101.0000_20120101.0000.nc /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/stats/tracknumbers_20110101.0000_20110201.0000.nc /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/stats/tracknumbers_20110201.0000_20110301.0000.nc /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/stats/tracknumbers_20110301.0000_20110401.0000.nc /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/stats/tracknumbers_20110401.0000_20110501.0000.nc /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/stats/tracknumbers_20110501.0000_20110601.0000.nc /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/stats/tracknumbers_20110601.0000_20110701.0000.nc /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/stats/tracknumbers_20110701.0000_20110801.0000.nc /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/stats/tracknumbers_20110801.0000_20110901.0000.nc /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/stats/tracknumbers_20110901.0000_20111001.0000.nc /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/stats/tracknumbers_20111001.0000_20111101.0000.nc /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/stats/tracknumbers_20111101.0000_20111201.0000.nc /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/stats/tracknumbers_20111201.0000_20120101.0000.nc --tracking-dirs /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/tracking/2011-01/ /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/tracking/2011-02/ /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/tracking/2011-03/ /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/tracking/2011-04/ /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/tracking/2011-05/ /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/tracking/2011-06/ /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/tracking/2011-07/ /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/tracking/2011-08/ /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/tracking/2011-09/ /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/tracking/2011-10/ /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/tracking/2011-11/ /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/2011/tracking/2011-12/ --require-seams || exit 1
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
python /pscratch/sd/f/feng045/tbpf_code_a4b8ad8/runscripts/run_mcs_tbpf_unified.py /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/campaign_2011/config_mcs_tbpf_e3sm_0p1deg_template_stats201101_201112.yml $scheduler_file
status=$?

date
exit $status
