#!/bin/bash
# Back up the E3SM MCS-tracking output directories to HPSS with htar in the xfer QOS (tracking_e3sm/hpss_e3sm_backup.py; docs/hpss_e3sm.md).
# xfer jobs run on a login-type node, are free of charge and may run up to 48 h; htar does not work on compute nodes.
#
# ONE job archives everything that MODELS and DIRS select (WORKERS archives at a time). The job always runs hpss_e3sm_backup.py with --run and prints
# the plan table first, without waiting for you. To see the plan BEFORE submitting, run the same selection on a login node WITHOUT --run (a dry run: it
# only scans the directories, it writes nothing: no list files, no logs, nothing in HPSS):
#   python tracking_e3sm/hpss_e3sm_backup.py --models ne120
# Submitting the same job again continues after a time-out or a failure: archives that are in HPSS with their index are skipped.
#
# SETTINGS are environment variables with the defaults below the #SBATCH lines. Override them for one submission:
#   sbatch --export=ALL,MODELS=ne120,WORKERS=4 tracking_e3sm/slurm_hpss_e3sm_backup.sbatch          # NAME=value pairs, no spaces, no commas inside a value
#   DIRS="mcs_tbpf_hr2p0 olr_pcp" sbatch --export=ALL,MODELS=ne30 tracking_e3sm/slurm_hpss_e3sm_backup.sbatch    # values with spaces: in front of sbatch, quoted
#
#   MODELS   ne120, ne30 or both (a space-separated list: MODELS="ne120 ne30" in front of sbatch)           (default: ne120 ne30)
#   DIRS     directories below <ROOT>/<model>_remap_0.1deg; empty = all except animations_2panel_tbpf and quicklooks_2panel_tbpf   (default: empty)
#   EXTRA    more hpss_e3sm_backup.py options in one string, e.g. "--verify-existing" (read archives already in HPSS back and check their CRCs)
#   ROOT, HPSS_DIR (must exist in HPSS), WORKERS (archives written at the same time, 1-15), REPO, PY: where the data, the archives and the code are.
#
# RECIPES
#   1 everything, one job per model (the production run of 2026-11):
#       for M in ne120 ne30; do sbatch --export=ALL,MODELS=$M,WORKERS=4 tracking_e3sm/slurm_hpss_e3sm_backup.sbatch; done
#   2 one directory:
#       DIRS="mcs_tbpf_hr2p0" sbatch --export=ALL,MODELS=ne120 tracking_e3sm/slurm_hpss_e3sm_backup.sbatch
#   3 re-check what is archived (reads the archives back; nothing new is written):
#       EXTRA="--verify-existing" sbatch --export=ALL,MODELS=ne120 tracking_e3sm/slurm_hpss_e3sm_backup.sbatch
#SBATCH --job-name=e3sm_hpss_backup
#SBATCH --account=m1657
#SBATCH --qos=xfer
#SBATCH --constraint=cron
#SBATCH --time=48:00:00
#SBATCH --mem=8G
#SBATCH --licenses=SCRATCH,hpss
#SBATCH --output=/pscratch/sd/f/feng045/E3SM_polun/_hpss_logs/slurm/%x_%j.out

# ---- what to back up (overridable from the environment)
REPO="${REPO:-/global/u1/f/feng045/program/scream}"
PY="${PY:-/global/common/software/m1867/python/py312/bin/python}"
ROOT="${ROOT:-/pscratch/sd/f/feng045/E3SM_polun}"
MODELS="${MODELS:-ne120 ne30}"
DIRS="${DIRS:-}"                               # empty = every directory except the animation and quicklook folders
HPSS_DIR="${HPSS_DIR:-/home/f/feng045/E3SM_polun}"   # must exist
WORKERS="${WORKERS:-3}"                        # archives written at the same time (HPSS allows 15 sessions)
EXTRA="${EXTRA:-}"                             # more options, e.g. "--verify-existing"

DIRS_ARG=""
if [ -n "$DIRS" ]; then DIRS_ARG="--dirs $DIRS"; fi
echo "HPSS backup on $(hostname), job ${SLURM_JOB_ID:-none}: models $MODELS dirs ${DIRS:-all} from $ROOT to $HPSS_DIR, commit $(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo unknown)"
# shellcheck disable=SC2086
"$PY" -u -I "$REPO/tracking_e3sm/hpss_e3sm_backup.py" --root "$ROOT" --models $MODELS $DIRS_ARG \
      --hpss-dir "$HPSS_DIR" --workers "$WORKERS" $EXTRA --run
rc=$?
echo "hpss_e3sm_backup exited with $rc"
exit $rc
