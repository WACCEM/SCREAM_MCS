#!/bin/bash
#SBATCH -A m1657
#SBATCH -N 5              # Number of nodes (1 server + X workers)
#SBATCH -c 128            # All cores available
#SBATCH -q regular        # Regular queue (or debug for testing)
#SBATCH -t 01:30:00       # 4 hours (adjust based on number of tasks)
#SBATCH -C cpu
#SBATCH --job-name=remapDBZ
#SBATCH --mail-user=zhe.feng@pnnl.gov
#SBATCH --mail-type=END
#SBATCH --output=logs/log_remap_dbz_zmid.log

# !! REMEMBER TO LOAD taskfarmer before submitting the job !!
# module load taskfarmer

# Set to 16 tasks per node (512 GB / 16 tasks ≈ 32 GB per task)
export THREADS=16

runcommands.sh tasklist_202007.txt