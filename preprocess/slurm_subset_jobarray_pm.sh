#!/bin/bash
#SBATCH -A m1867
#SBATCH -J subset
#SBATCH -t 00:30:00
#SBATCH -q regular
#SBATCH -C cpu
#SBATCH --nodes=2
#SBATCH --ntasks-per-node=128
#SBATCH --exclusive
#SBATCH --mail-type=END
#SBATCH --mail-user=zhe.feng@pnnl.gov
#SBATCH --output=log_%A_%a.log

# To submit the job for a specific range of parts:
# sbatch --array=<indexlist>[%<limit>] slurm_subset_jobarray_pm.sh

# For example, to submit all 20 jobs, but limit to running 2 at a time:
# sbatch --array=0-19%2 slurm_subset_jobarray_pm.sh
# For running a number of specific jobs:
# sbatch --array=3,5,12,30-33%6 slurm_subset_jobarray_pm.sh

date
module load taskfarmer
export THREADS=128

cd /global/homes/f/feng045/program/scream/preprocess
runcommands.sh tasks_$SLURM_ARRAY_TASK_ID
date
