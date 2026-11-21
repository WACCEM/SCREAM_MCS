#!/bin/bash
# Restore E3SM MCS-tracking output directories (or parts of them) from HPSS in the xfer QOS (tracking_e3sm/hpss_e3sm_restore.py; docs/hpss_e3sm.md).
# Look at what is archived first, on a login node:  python tracking_e3sm/hpss_e3sm_restore.py --list
# and at the plan of a request (the archives it reads and the htar commands; nothing is extracted) with --dry-run:
#   python tracking_e3sm/hpss_e3sm_restore.py --models ne120 --dirs mcs_tbpf_hr2p0 --path mcs_tbpf_hr2p0/2010/stats --dest $SCRATCH/restore --dry-run
#
# SETTINGS are environment variables with the defaults below the #SBATCH lines; DEST has no default and must be given.
#   MODELS ne120 ne30 (space-separated list in front of sbatch)      DIRS archives to serve (empty = all of the models)
#   PATHS  only these paths of the archives, relative to the model folder (space-separated; empty = everything)
#   DEST   the data root to restore into: DEST/<model>_remap_0.1deg/<dir>/... (a folder on scratch or CFS, not the original root)
#   EXTRA  more hpss_e3sm_restore.py options as one string, e.g. "--relink --nostage --overwrite"      HPSS_DIR, WORKERS, REPO, PY
#
# EXAMPLES
#   PATHS="mcs_tbpf_hr2p0/2010/stats" DIRS="mcs_tbpf_hr2p0" sbatch --export=ALL,MODELS=ne120,DEST=$SCRATCH/restore tracking_e3sm/slurm_hpss_e3sm_restore.sbatch
#   DIRS="mcs_tbpf mcs_tbpf_hr2p0" EXTRA="--relink" sbatch --export=ALL,MODELS=ne30,DEST=$SCRATCH/restore tracking_e3sm/slurm_hpss_e3sm_restore.sbatch
#SBATCH --job-name=e3sm_hpss_restore
#SBATCH --account=m1657
#SBATCH --qos=xfer
#SBATCH --constraint=cron
#SBATCH --time=12:00:00
#SBATCH --mem=8G
#SBATCH --licenses=SCRATCH,hpss
#SBATCH --output=/pscratch/sd/f/feng045/E3SM_polun/_hpss_logs/slurm/%x_%j.out

REPO="${REPO:-/global/u1/f/feng045/program/scream}"
PY="${PY:-/global/common/software/m1867/python/py312/bin/python}"
MODELS="${MODELS:-ne120 ne30}"
DIRS="${DIRS:-}"
PATHS="${PATHS:-}"
DEST="${DEST:?set DEST=a folder on scratch or CFS (sbatch --export=ALL,DEST=...)}"
HPSS_DIR="${HPSS_DIR:-/home/f/feng045/E3SM_polun}"
WORKERS="${WORKERS:-2}"                        # archives read at the same time
EXTRA="${EXTRA:-}"                             # more options, e.g. "--relink --nostage --overwrite"

DIRS_ARG=""; PATHS_ARG=""
if [ -n "$DIRS" ]; then DIRS_ARG="--dirs $DIRS"; fi
if [ -n "$PATHS" ]; then PATHS_ARG="--path $PATHS"; fi
echo "HPSS restore on $(hostname), job ${SLURM_JOB_ID:-none}: models $MODELS dirs ${DIRS:-all} paths ${PATHS:-all} from $HPSS_DIR to $DEST"
# shellcheck disable=SC2086
"$PY" -u -I "$REPO/tracking_e3sm/hpss_e3sm_restore.py" --models $MODELS $DIRS_ARG $PATHS_ARG --dest "$DEST" \
      --hpss-dir "$HPSS_DIR" --workers "$WORKERS" $EXTRA
rc=$?
echo "hpss_e3sm_restore exited with $rc"
exit $rc
