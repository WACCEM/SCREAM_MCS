#!/bin/bash
#SBATCH --job-name=MonRainSCREAM
#SBATCH -A m1867
#SBATCH --time=00:20:00
#SBATCH -q debug
#SBATCH -C cpu
#SBATCH -N 8 -c 128
#SBATCH --exclusive
#SBATCH --output=logs/log_mcs_monthly_rainmap_SCREAM_decadal.log
#SBATCH --mail-type=END
#SBATCH --mail-user=zhe.feng@pnnl.gov

# ─────────────────────────────────────────────────────────────────────────────
# IMPORTANT: load the TaskFarmer module BEFORE submitting this job:
#   module load taskfarmer
# Then submit with:
#   sbatch slurm.submit_mcs_monthly_rainmap_SCREAM_ne256_tune.sh
# ─────────────────────────────────────────────────────────────────────────────

date

# Each task gets up to 12 cores on a 128-core node (THREADS workers/node).
# Memory budget: ~64 GB/task is conservative for ~50–60 GB peak; raise THREADS
# to 12–16 after profiling confirms Dask streaming keeps peaks below ~32 GB.
export THREADS=12

runcommands.sh /global/u1/f/feng045/program/scream/tracking_decadal/tasklist_mcs_monthly_rainmap_SCREAM_ne256_tune.txt

date
