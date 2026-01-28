#!/bin/bash
#SBATCH -A m1657
#SBATCH -N 2              # Number of nodes (1 server + X workers)
#SBATCH -c 128            # All cores available
#SBATCH -q debug        # Regular queue (or debug for testing)
#SBATCH -t 00:30:00       # 4 hours (adjust based on number of tasks)
#SBATCH -C cpu
#SBATCH --job-name=remapDBZ
#SBATCH --mail-user=zhe.feng@pnnl.gov
#SBATCH --mail-type=END
#SBATCH --output=logs/log_remap_dbz_zmid.log

# cd $SCRATCH/scream_taskfarmer
# module load taskfarmer

# Set to 10 tasks per node (512 GB / 50 GB per task ≈ 10)
export THREADS=14

runcommands.sh tasklist.txt