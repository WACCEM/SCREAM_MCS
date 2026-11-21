#!/bin/bash
#SBATCH --job-name=IRMissing
#SBATCH -A m1867
#SBATCH --time=00:30:00
#SBATCH -q debug
#SBATCH -C cpu
#SBATCH -N 8 -c 128
#SBATCH --exclusive
#SBATCH --output=logs/log_mergir_missing_data.log
#SBATCH --mail-type=END
#SBATCH --mail-user=zhe.feng@pnnl.gov

# ─────────────────────────────────────────────────────────────────────────────
# IMPORTANT: load the TaskFarmer module BEFORE submitting this job:
#   module load taskfarmer
# Then submit with:
#   sbatch slurm.submit_mergir_missing_data.sh
# ─────────────────────────────────────────────────────────────────────────────

date

export THREADS=24

runcommands.sh /global/u1/f/feng045/program/scream/scripts/tasklist_mergir_missing_data.txt

date
