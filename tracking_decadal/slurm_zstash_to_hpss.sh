#!/bin/bash
#SBATCH --qos=xfer
#SBATCH -C cron
#SBATCH --time=48:00:00
#SBATCH --job-name=SCREAMdecadal
#SBATCH --account=m1867
#SBATCH --mem=10GB
#SBATCH --output=zstash_backup_%j.log
#SBATCH --error=zstash_backup_%j.err
#SBATCH --mail-type=END,FAIL,TIME_LIMIT
#SBATCH --mail-user=zhe.feng@pnnl.gov

# Activate E3SM unified environment
source /global/common/software/e3sm/anaconda_envs/load_latest_e3sm_unified_pm-cpu.sh

# Define paths
LOCAL_DIR=/pscratch/sd/f/feng045/SCREAM-decadal
HPSS_DIR=/home/f/feng045/SCREAM-decadal

# Move to the top-level directory to be archived
cd ${LOCAL_DIR}

# Run zstash 
# zstash create --hpss=${HPSS_DIR} .

# Continue backup using update instead of create
zstash update --hpss=${HPSS_DIR} 
#    --exclude="run/*,run_conus/*"
