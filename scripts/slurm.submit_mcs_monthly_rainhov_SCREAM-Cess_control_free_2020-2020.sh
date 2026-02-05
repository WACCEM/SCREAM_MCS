#!/bin/bash
#SBATCH --job-name=2020-2020
#SBATCH -A m1867
#SBATCH --time=00:10:00
#SBATCH -q regular
#SBATCH -C cpu
#SBATCH -N 2 -c 128
#SBATCH --exclusive
#SBATCH --output=log_mcs_monthly_rainhov_SCREAM-Cess_control_free_2020-2020.log
#SBATCH --mail-type=END
#SBATCH --mail-user=zhe.feng@pnnl.gov

date

module load taskfarmer
export THREADS=6
runcommands.sh /global/u1/f/feng045/program/scream/src/tasklist_mcs_monthly_rainhov_SCREAM-Cess_control_free_2020-2020.txt

date
