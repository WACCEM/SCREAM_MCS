#!/bin/bash
#SBATCH -A m1867
#SBATCH -J Cess2mcs
#SBATCH -t 24:00:00
#SBATCH -q regular
#SBATCH -C cpu
#SBATCH --nodes=5
#SBATCH --cpus-per-task=128
#SBATCH --exclusive
#SBATCH --output=logs/log_SCREAM-Cess2_global.log
#SBATCH --mail-type=END
#SBATCH --mail-user=zhe.feng@pnnl.gov

date

module load python
source activate /global/common/software/m1867/python/pyflex-dev

# Run Python
cd /global/homes/f/feng045/program/PyFLEXTRKR-dev/runscripts
python run_mcs_tbpf_mcsmip.py /global/homes/f/feng045/program/scream/tracking/config_mcs_tbpf_SCREAMv1-Cess2.yml

date
