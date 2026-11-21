#!/bin/bash
# cess2_cfs_swap_wcmca1.sh: swap the re-run SCREAM Cess2 track statistics into the shared CFS folder (run it as wcmca1).
#
# Why this file exists: .../cess2/global/mcs and .../cess2/global/mcs/stats are owned by wcmca1 (mode 755), so feng045 can not create, move or
# delete anything in them. feng045 copied the re-run outputs (2026-11-16, pinned code tbpf_code_a4b8ad8) to the staging folder
#   /global/cfs/cdirs/m1867/zfeng/E3SM/SCREAMv1/cess2/global/stats_rerun_20261116_staging/
# and checked every file byte by byte against the pscratch originals. This script does the swap inside stats/ in four steps:
#   1. checks: user is wcmca1, the staging folder is complete (names + sizes), nothing of the new names exists yet;
#   2. creates stats/archive_20261116_old_dense_version/ and MOVES the 4 replaced old dense files into it (2.85 GB), with a README.md;
#   3. MOVES the new files from the staging folder into stats/ (a rename inside the same file system: instant, no second copy);
#   4. removes the (now empty) staging folders and lists the result.
# Not touched (still valid, were not re-run): trackstats_*.nc, trackstats_sparse_*.nc, tracknumbers_*.nc and monthly/.
#
# Usage (as wcmca1):  bash cess2_cfs_swap_wcmca1.sh --dry-run     # prints every step, changes nothing (run this first)
#                     bash cess2_cfs_swap_wcmca1.sh               # does the swap and writes a log into the archive folder
# The script stops at the first problem (set -e); nothing is deleted, only moved, so a stop in the middle can be undone with the mv commands
# of the log (and the README.md of the archive tells how to restore the old version).
set -euo pipefail

DRY=0
if [ "${1:-}" = "--dry-run" ]; then DRY=1; elif [ -n "${1:-}" ]; then echo "usage: $0 [--dry-run]"; exit 2; fi

# ----- Paths and names -----
BASE=/global/cfs/cdirs/m1867/zfeng/E3SM/SCREAMv1/cess2/global
STATS=$BASE/mcs/stats                                  # shared stats folder (owned by wcmca1)
STAGE=$BASE/stats_rerun_20261116_staging               # staging folder made by feng045
ARCH=$STATS/archive_20261116_old_dense_version         # archive of the replaced old files (new)
DATES=20190803.0000_20210306.0000
OLD=(mcs_tracks_$DATES.nc mcs_tracks_pf_$DATES.nc mcs_tracks_robust_$DATES.nc mcs_tracks_final_$DATES.nc)      # old dense files to archive
NEW_ROWS=(mcs_tracks_$DATES.rows mcs_tracks_pf_$DATES.rows mcs_tracks_robust_$DATES.rows mcs_tracks_final_$DATES.rows)   # new row folders
NEW_DENSE=mcs_tracks_final_$DATES.nc                   # new dense final file (same name as the old one: the old one is archived first)
NEW_PARQUET=(mcs_tracks_final_combined_tropics_2019_2021.parquet mcs_tracks_final_combined_global_2019_2021.parquet)

# Expected sizes in bytes of the staged files (measured by feng045 on 2026-11-17, identical to pscratch)
declare -A SIZE=(
  [stats/mcs_tracks_final_$DATES.nc]=830328711
  [parquet/mcs_tracks_final_combined_tropics_2019_2021.parquet]=121512564
  [parquet/mcs_tracks_final_combined_global_2019_2021.parquet]=191346985
  [stats/mcs_tracks_$DATES.rows/entries.parquet]=68391324
  [stats/mcs_tracks_$DATES.rows/fragments.parquet]=13540562
  [stats/mcs_tracks_$DATES.rows/tracks.parquet]=982915
  [stats/mcs_tracks_pf_$DATES.rows/entries.parquet]=334408156
  [stats/mcs_tracks_pf_$DATES.rows/fragments.parquet]=13540562
  [stats/mcs_tracks_pf_$DATES.rows/tracks.parquet]=982915
  [stats/mcs_tracks_robust_$DATES.rows/entries.parquet]=306282279
  [stats/mcs_tracks_robust_$DATES.rows/fragments.parquet]=11463181
  [stats/mcs_tracks_robust_$DATES.rows/tracks.parquet]=821188
  [stats/mcs_tracks_final_$DATES.rows/entries.parquet]=314053356
  [stats/mcs_tracks_final_$DATES.rows/fragments.parquet]=11463181
  [stats/mcs_tracks_final_$DATES.rows/tracks.parquet]=821188
)

# ----- Helper: run a command, or only print it in a dry run -----
run() {
  if [ $DRY -eq 1 ]; then echo "DRY RUN: $*"; else echo "+ $*"; "$@"; fi
}

# ----- Step 1: checks -----
echo "=== Step 1: checks ($(date '+%F %T')) ==="
if [ "$(id -un)" != "wcmca1" ]; then echo "ERROR: run this as wcmca1 (you are $(id -un))"; exit 1; fi
[ -d "$STATS" ] || { echo "ERROR: $STATS not found"; exit 1; }
[ -d "$STAGE" ] || { echo "ERROR: staging folder $STAGE not found"; exit 1; }
[ -w "$STATS" ] || { echo "ERROR: $STATS is not writable for $(id -un)"; exit 1; }
# The old files to archive must exist; the archive and the new names must not exist yet
for f in "${OLD[@]}"; do [ -f "$STATS/$f" ] || { echo "ERROR: old file $STATS/$f missing (already swapped?)"; exit 1; }; done
[ ! -e "$ARCH" ] || { echo "ERROR: $ARCH exists already (already swapped?)"; exit 1; }
for f in "${NEW_ROWS[@]}" "${NEW_PARQUET[@]}"; do [ ! -e "$STATS/$f" ] || { echo "ERROR: $STATS/$f exists already"; exit 1; }; done
# Every staged file must exist with the expected size (a partial copy would show here)
for f in "${!SIZE[@]}"; do
  [ -f "$STAGE/$f" ] || { echo "ERROR: staged file $STAGE/$f missing"; exit 1; }
  got=$(stat -c %s "$STAGE/$f")
  [ "$got" = "${SIZE[$f]}" ] || { echo "ERROR: $f has $got bytes, expected ${SIZE[$f]}"; exit 1; }
done
echo "OK: ${#SIZE[@]} staged files with the expected sizes; the 4 old dense files are present; the archive and the new names do not exist yet"

# From here on write a log into the archive folder (a dry run only prints)
if [ $DRY -eq 0 ]; then
  mkdir "$ARCH"
  exec > >(tee -a "$ARCH/swap_20261116.log") 2>&1
  echo "log of $(basename "$0"), user $(id -un), $(date '+%F %T')"
fi

# ----- Step 2: archive the 4 replaced old dense files -----
echo "=== Step 2: archive the old dense files into $ARCH ==="
for f in "${OLD[@]}"; do run mv "$STATS/$f" "$ARCH/$f"; done
if [ $DRY -eq 0 ]; then
cat > "$ARCH/README.md" <<'EOF'
# Archive of the old SCREAM Cess2 (3 km TUNE) dense track statistics (2026-11-16)

These 4 files were the PyFLEXTRKR track statistics of the SCREAM Cess2 run (2019-08-03 .. 2021-03-06) in `../` until 2026-11-17. They were made
on 2026-01-17 (dense netCDF, one array per variable over [tracks, times]) with an older PyFLEXTRKR that did not write `total_volrain` and
`total_heavyvolrain`. They were replaced by the re-run of 2026-11-16 (feng045, pinned code `tbpf_code_a4b8ad8`, config
`scream/tracking/config_mcs_tbpf_SCREAMv1-Cess2_rows.yml`).

| archived file (old) | size | step | replaced by (in `../`) |
| --- | --- | --- | --- |
| `mcs_tracks_20190803.0000_20210306.0000.nc` | 0.37 GB | identifymcs | `mcs_tracks_20190803.0000_20210306.0000.rows/` |
| `mcs_tracks_pf_20190803.0000_20210306.0000.nc` | 0.92 GB | matchpf | `mcs_tracks_pf_20190803.0000_20210306.0000.rows/` |
| `mcs_tracks_robust_20190803.0000_20210306.0000.nc` | 0.76 GB | robustmcs | `mcs_tracks_robust_20190803.0000_20210306.0000.rows/` |
| `mcs_tracks_final_20190803.0000_20210306.0000.nc` | 0.81 GB | speed | `mcs_tracks_final_20190803.0000_20210306.0000.rows/` and the new dense `mcs_tracks_final_20190803.0000_20210306.0000.nc` (0.83 GB) |

Added in `../` at the same time: the two combined tidy tables `mcs_tracks_final_combined_tropics_2019_2021.parquet` (tropics 20S-20N) and
`mcs_tracks_final_combined_global_2019_2021.parquet` (global box), made from the final statistics by `scream/scripts/combine_filter_mcs_trackstats.py`.

**Row tables (`*.rows/`).** One folder per step with `tracks.parquet`, `entries.parquet`, `fragments.parquet` and `meta.json`; read with
`pyflextrkr.rowstats.RowStats` (or `pandas.read_parquet`). The dense `mcs_tracks_final_*.nc` of the new run is made from the rows by the
`dense_netcdf` step and has the same layout as the old dense file.

**Unchanged in `../` (were not re-run, still valid inputs of the new outputs):** `trackstats_*.nc`, `trackstats_sparse_*.nc`, `tracknumbers_*.nc`, `monthly/`.

**Differences, old -> new** (measured on 2026-11-16 with `check_cess2_rerun.py` / `analyze_cess2_diff.py` by feng045):
- same 79,370 robust MCS tracks (same ids, start times, durations) and the same 1,356,951 rows (global box); all Tb-based columns identical;
- `total_volrain` and `total_heavyvolrain`: 100 % NaN in the old file -> filled in the new one (`total_volrain` = 100 km2 x `total_rain`, 10 km pixel);
- 4.1 % of the rows (56,277 rows; 22,017 of 78,785 tracks) differ in precipitation-feature (PF) and movement columns: PF position and centroids in 1-3 % of
  rows (median 1-4 degrees), PF identification (pf_npf, area, rain rate) in 0.03-0.1 % of rows, movement_* in 1.8 % of rows; 29 % of the differing rows are in
  the 2 % of tracks that cross the periodic boundary; ocean tracks (lifetime-max pf_landfrac < 0.1) 26,091 -> 26,139;
- the speed step used the OLD pixel files (mapfeature was not re-run), valid because the robust MCS set is identical.

**To restore the old version** (as wcmca1): `cd ..; mkdir superseded_rerun; mv mcs_tracks_*.rows mcs_tracks_final_*.nc mcs_tracks_final_combined_*.parquet superseded_rerun/;`
then `mv archive_20261116_old_dense_version/*.nc .` (the `.nc` files go back to their old names; keep this README and the log).
A copy of the old dense final file is also in `/pscratch/sd/w/wcmca1/SCREAMv1-cess2/mcs/stats/` and in HPSS.
EOF
echo "wrote $ARCH/README.md"
else
  echo "DRY RUN: would write $ARCH/README.md (what, when, why, differences, how to restore)"
fi

# ----- Step 3: move the new files from the staging folder into stats/ -----
echo "=== Step 3: move the new files into $STATS ==="
for d in "${NEW_ROWS[@]}"; do run mv "$STAGE/stats/$d" "$STATS/$d"; done
run mv "$STAGE/stats/$NEW_DENSE" "$STATS/$NEW_DENSE"
for f in "${NEW_PARQUET[@]}"; do run mv "$STAGE/parquet/$f" "$STATS/$f"; done

# ----- Step 4: remove the empty staging folders, list the result -----
echo "=== Step 4: clean up and list ==="
if [ $DRY -eq 0 ]; then
  rmdir "$STAGE/stats" "$STAGE/parquet" "$STAGE" && echo "staging folder removed" || echo "NOTE: the staging folder is not empty, left in place: $STAGE"
  ls -la "$STATS"
  ls -la "$ARCH"
  echo "DONE $(date '+%F %T')"
else
  echo "DRY RUN: would remove the empty staging folders and list $STATS and $ARCH"
  echo "DRY RUN finished: nothing was changed"
fi
