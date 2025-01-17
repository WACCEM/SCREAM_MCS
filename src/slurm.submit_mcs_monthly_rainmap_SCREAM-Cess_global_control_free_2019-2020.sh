#!/bin/bash
#SBATCH --job-name=2019-2020
#SBATCH -A m1867
#SBATCH --time=00:30:00
#SBATCH -q debug
#SBATCH -C cpu
#SBATCH -N 2 -c 128
#SBATCH --exclusive
#SBATCH --output=log_mcs_monthly_rainmap_SCREAM-Cess_global_control_free_2019-2020.log
#SBATCH --mail-type=END
#SBATCH --mail-user=zhe.feng@pnnl.gov

date

module load taskfarmer
export THREADS=13
runcommands.sh /global/u1/f/feng045/program/scream/src/tasklist_mcs_monthly_rainmap_SCREAM-Cess_global_control_free_2019-2020.txt

date
