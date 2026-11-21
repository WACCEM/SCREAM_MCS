#!/bin/bash
#SBATCH -A m1657
#SBATCH -J cess2_rerun
#SBATCH --qos=regular
#SBATCH --nodes=4
#SBATCH -C cpu
#SBATCH --time=01:30:00
#SBATCH --exclusive
#SBATCH --output=/pscratch/sd/f/feng045/SCREAM-decadal/cess2/mcs_rerun/logs/log_%x_%j.log

# Cess2 (SCREAM 3 km TUNE) stats re-run with row tables: identifymcs, matchpf, robustmcs, speed (no mapfeature), config
# config_mcs_tbpf_SCREAMv1-Cess2_rows.yml. Modeled on PyFLEXTRKR-dev/config/slurm_tbpf_mcstracking_stats_multinode.sh: a Dask scheduler on the first
# node, 64 workers on every node, then run_mcs_tbpf_unified.py of the pinned code (the worktree that made the E3SM production, with total_volrain and
# total_heavyvolrain in matchpf).
#
# Two ways to run it:
#   sbatch slurm_SCREAM-Cess2_stats_rerun.sh                 # as a batch job (the #SBATCH lines above)
#   bash slurm_SCREAM-Cess2_stats_rerun.sh <jobid> [nodes]   # on the first node of an interactive allocation (salloc --no-shell ...), so that the
#                                                            # run can be watched; srun steps are attached to the allocation with --jobid
# Output: <root>/stats/ (row folders and the dense final file), logs in <root>/logs/ (run_<jobid>.log ends with "exit status N").

# Settings: the allocation, the environment, the code and the run
JOBID=${1:-$SLURM_JOB_ID}                         # allocation that carries the srun steps (default: the job this script runs in)
NODES=${2:-${SLURM_JOB_NUM_NODES:-4}}             # nodes of the allocation
WORKERS_PER_NODE=64                               # Dask workers per node, one thread each (as the E3SM stats jobs)
WORKER_MEMORY=7GB                                 # memory limit of a worker
ENV=/global/common/software/m1867/python/pyflex26.3
CODE=/pscratch/sd/f/feng045/tbpf_code_a4b8ad8     # pinned worktree: the code of the E3SM production runs
CONFIG=/global/u1/f/feng045/program/scream/tracking/config_mcs_tbpf_SCREAMv1-Cess2_rows.yml
ROOT=/pscratch/sd/f/feng045/SCREAM-decadal/cess2/mcs_rerun
SCHED=$ROOT/logs/scheduler_${JOBID}.json
date

# Environment: the pinned code first on the path (also inherited by the workers that srun starts), many open files, long Dask timeouts
export PATH=$ENV/bin:$PATH
export PYTHONPATH=$CODE${PYTHONPATH:+:$PYTHONPATH}
ulimit -n 32000
export DASK_DISTRIBUTED__COMM__TIMEOUTS__CONNECT=360s
export DASK_DISTRIBUTED__COMM__TIMEOUTS__TCP=360s
rm -f $SCHED

# Dask scheduler on this node, then the workers on all nodes of the allocation (--overlap: they share the cores of this script's step)
dask-scheduler --scheduler-file=$SCHED > $ROOT/logs/dask_scheduler_${JOBID}.log 2>&1 &
sched_pid=$!
until [ -s $SCHED ]; do sleep 2; done
srun --jobid=$JOBID --overlap --kill-on-bad-exit=0 -N $NODES --ntasks-per-node=$WORKERS_PER_NODE --cpus-per-task=2 --cpu-bind=cores \
    dask-worker --scheduler-file=$SCHED --nthreads 1 --memory-limit=$WORKER_MEMORY --local-directory=/tmp \
    --worker-class distributed.Worker > $ROOT/logs/dask_workers_${JOBID}.log 2>&1 &

# The run starts when all the workers are there (10 min at most)
python -c "
from dask.distributed import Client
client = Client(scheduler_file='$SCHED', timeout=120)
client.wait_for_workers($WORKERS_PER_NODE * $NODES, timeout=600)
print('Dask workers connected:', len(client.scheduler_info()['workers']))
client.close()"
status=$?
if [ $status -ne 0 ]; then
    echo "the Dask workers did not connect"
    echo "exit status $status"
    exit $status
fi

# The run; the exit status of python (not of the last date) is the exit status of the job, so a failed step shows as FAILED in sacct
python $CODE/runscripts/run_mcs_tbpf_unified.py $CONFIG $SCHED
status=$?
kill $sched_pid 2>/dev/null
date
echo "exit status $status"
exit $status
