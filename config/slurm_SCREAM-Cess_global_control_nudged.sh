#!/bin/bash
#SBATCH -A m1867
#SBATCH -J CTLnudged
#SBATCH -t 24:00:00
#SBATCH -q regular
#SBATCH -C cpu
#SBATCH --nodes=1
#SBATCH --cpus-per-task=64
#SBATCH --exclusive
#SBATCH --output=log_SCREAM-Cess_global_control_nudged.log
#SBATCH --mail-type=END
#SBATCH --mail-user=zhe.feng@pnnl.gov

date

module load python
source activate /global/common/software/m1867/python/pyflex

# Run Python
cd /global/homes/f/feng045/program/PyFLEXTRKR-dev/runscripts
python run_mcs_tbpf.py /global/homes/f/feng045/program/scream/config/config_SCREAM-Cess_global_control_nudged.yml

date