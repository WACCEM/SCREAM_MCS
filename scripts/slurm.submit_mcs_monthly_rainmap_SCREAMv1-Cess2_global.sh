#!/bin/bash
#SBATCH --job-name=MonthRain
#SBATCH -A m1867
#SBATCH --time=00:30:00
#SBATCH -q debug
#SBATCH -C cpu
#SBATCH -N 3 -c 128
#SBATCH --exclusive
#SBATCH --output=logs/log_mcs_monthly_rainmap_SCREAMv1-Cess2_global.log
#SBATCH --mail-type=END
#SBATCH --mail-user=zhe.feng@pnnl.gov

date

# module load taskfarmer
export THREADS=9
runcommands.sh /global/homes/f/feng045/program/scream/src/tasklist_mcs_monthly_rainmap_SCREAMv1-Cess2_global.txt

date