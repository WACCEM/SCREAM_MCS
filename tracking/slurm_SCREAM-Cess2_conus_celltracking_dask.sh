#!/bin/bash
#SBATCH -A m1657
#SBATCH -J Cess2cell
#SBATCH --qos=debug
#SBATCH --nodes=4
#SBATCH --ntasks-per-node=64   # 64 workers per node (1 worker per core)
#SBATCH --cpus-per-task=1       # 1 CPU per worker
#SBATCH -C cpu
#SBATCH --time=00:30:00
#SBATCH --exclusive
#SBATCH --mail-user=zhe.feng@pnnl.gov
#SBATCH --mail-type=END
#SBATCH --output=logs/log_SCREAM-Cess2_conus_celltracking.log
date

# Calculate total tasks
ntasks=$(( $SLURM_NNODES * $SLURM_NTASKS_PER_NODE ))

echo "Total tasks: $ntasks"
echo "Tasks per node: $SLURM_NTASKS_PER_NODE"

echo "Starting scheduler and workers..."

# Generate a scheduler filename with a random string
random_str=`echo $RANDOM | md5sum | head -c 10`
scheduler_file=$SCRATCH/scheduler_${random_str}.json

rm -f $scheduler_file

module load python
source activate /global/common/software/m1867/python/pyflex-dev

# Set environment variables for timeouts globally
export DASK_DISTRIBUTED__COMM__TIMEOUTS__CONNECT=3600s
export DASK_DISTRIBUTED__COMM__TIMEOUTS__TCP=3600s

# Start Dask Scheduler
dask scheduler \
    --interface hsn0 \
    --scheduler-file $scheduler_file &

dask_pid=$!

# Wait for the scheduler to start
sleep 5
until [ -f $scheduler_file ]
do
    sleep 5
done

echo "Starting workers"

# Start Dask Workers
srun --ntasks=$ntasks --ntasks-per-node=$SLURM_NTASKS_PER_NODE \
     dask worker \
     --scheduler-file $scheduler_file \
     --interface hsn0 \
     --nthreads 1 \
     --memory-limit auto &

# Wait a bit to ensure workers have started
sleep 10

# Run Python
python /global/homes/f/feng045/program/PyFLEXTRKR-dev/runscripts/run_celltracking.py \
    /global/homes/f/feng045/program/scream/tracking/config_celltracking_3km_SCREAMv1-Cess2_CONUS.yaml \
    $scheduler_file

# Clean up the scheduler
echo "Cleaning up scheduler..."
kill -9 $dask_pid

date
