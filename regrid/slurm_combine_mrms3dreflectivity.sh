#!/bin/bash

#SBATCH --account=m1657
#SBATCH --job-name mrms
#SBATCH --constraint=cpu
#SBATCH --time=01:30:00
#SBATCH -q regular 
#SBATCH --nodes=1

# Example usage:
# sbatch slurm_combine_mrms3dreflectivity.sh 0 999
# sbatch slurm_combine_mrms3dreflectivity.sh 1000 1999
# sbatch slurm_combine_mrms3dreflectivity.sh 2000 2999
 
script="/global/homes/f/feng045/program/scream/regrid/combine_mrms_3d_reflectivity.py"
 
start="${1:?start offset required}"
step="${2:-30}"
nproc="${3:-12}"
 
python "$script" --offset "$start" --count "$step" --nproc "$nproc"
echo "Finished processing records # $start with count $step"
 
exit 0