# **SCREAM MCS & Convective Cell Analysis**


---
This repository contains MCS & convective cell analysis codes and Jupyter Notebooks for the SCREAM simulations.

---

## SCREAM decadal MCS tracking workflow

This section documents the end-to-end workflow for tracking Mesoscale Convective Systems
(MCS) in the **SCREAM decadal simulations (1995–2005)** and the companion **IMERGv7
observational dataset**, plus the downstream post-processing and analysis steps.

Three SCREAM simulation sets are tracked:

| Label | Resolution | Input data directory |
|-------|-----------|----------------------|
| `ne1024` | ~3 km | `/global/cfs/cdirs/e3smdata/simulations/scream-decadal/MCS/input4tracking/ne1024/` |
| `ne256 ctl` | ~13 km, control | `/global/cfs/cdirs/e3smdata/simulations/scream-decadal/MCS/input4tracking/ne256/01/` |
| `ne256 tune` | ~13 km, tuned | `/global/cfs/cdirs/e3smdata/simulations/scream-decadal/MCS/input4tracking/ne256/03/` |

The SCREAM hourly OLR+precipitation data were remapped to a common IMERG 0.1°x0.1° (latxlon) grid, produced by Hsi-Yen Ma (ma21@llnl.gov).

**Simpler 1-year workflow:** The SCREAM Cess-Potter (1-year) simulation uses a single
config per case and lives in `tracking/` (+ `preprocess/`, `scripts/`). The multi-year
per-year script generation described below is only needed for the decadal runs.

**Common environment (all tracking jobs):**
- NERSC Perlmutter CPU, account `m1867`, QOS `regular`, `--exclusive`.
- 8 nodes × 128 MPI tasks/node = **1,024 Dask-MPI workers** (1 thread/worker), `run_parallel: 2`.
- Activate: `module load python && source activate /global/common/software/m1867/python/pyflex26.3`
- Driver: `PyFLEXTRKR-dev/runscripts/run_mcs_tbpf_mcsmip.py <config.yml> <scheduler_file>`

All scripts below live in `tracking_decadal/` unless noted otherwise.

---

### Step 1a — Generate per-year tracking config and Slurm scripts

Two generator scripts produce one config YAML and one Slurm shell script per year, by
substituting `STARTDATE`, `ENDDATE`, and `YEAR` placeholders in template files.

**SCREAM** (`gen_scream_tracking_scripts.py`):

```bash
cd tracking_decadal/

# Write config YAMLs + Slurm scripts for all years (default: 1995–2005)
python gen_scream_tracking_scripts.py

# Custom year range
python gen_scream_tracking_scripts.py --start-year 2000 --end-year 2002

# Write files AND submit immediately
python gen_scream_tracking_scripts.py --submit

# Submit previously written scripts without regenerating them
python gen_scream_tracking_scripts.py --no-write_config --no-write_slurm --submit
```

**OBS: Tb + IMERGv7** (`gen_imerg_tracking_scripts.py`):

```bash
# Default range: 1998–2025
python gen_imerg_tracking_scripts.py

# Custom range + submit
python gen_imerg_tracking_scripts.py --start-year 2000 --end-year 2002 --submit
```

**Template files** — the active template pair is set by the `CONFIG_TEMPLATE` /
`SLURM_TEMPLATE` constants at the top of each generator script:

| Dataset | Config template | Slurm template |
|---------|----------------|----------------|
| SCREAM ne1024 | `config_mcs_tbpf_SCREAM_decadal_template.yml` | `slurm_mcs_SCREAM_decadal_template.sh` |
| SCREAM ne256 ctl | `config_mcs_tbpf_SCREAM_ne256_ctl_template.yml` | `slurm_mcs_SCREAM_ne256_ctl_template.sh` |
| SCREAM ne256 tune | `config_mcs_tbpf_SCREAM_ne256_tune_template.yml` | `slurm_mcs_SCREAM_ne256_tune_template.sh` |
| OBS IMERGv7 | `config_mcs_tbpf_IMERGv7_mcsmip_template.yml` | `slurm_mcs_IMERGv7_mcsmip_template.sh` |

Each generated config YAML controls the full PyFLEXTRKR pipeline
(`run_idfeature` → `run_tracksingle` → `run_gettracks` → `run_trackstats` →
`run_identifymcs` → `run_matchpf` → `run_robustmcs` → `run_mapfeature` → `run_speed`).
Key per-dataset settings: `clouddata_path`, `root_path` (output root), `databasename`
(file prefix), `startdate`/`enddate`.

Slurm log files are written to `tracking_decadal/logs/` (created automatically).

---

### Step 1b — Tracking performance and conservative Slurm sizing

Measured wallclock times per simulation-year (full pipeline, 8 nodes / 1,024 workers,
from `tracking_decadal/logs/`):

| Dataset | Wallclock range | Mean | `--time` in template |
|---------|----------------|------|---------------------|
| SCREAM ne1024 | 13–16 h | ~14.4 h | `20:00:00` |
| SCREAM ne256 ctl | 6.9–8.1 h | ~7.2 h | `11:00:00` |
| SCREAM ne256 tune | 7.0–7.4 h | ~7.2 h | `11:00:00` |
| OBS IMERGv7 | not profiled here | — | `03:00:00` |

**Notes:**
- The **ne1024 runtime is dominated by `idfeature`** (~7.7 h to identify cloud objects
  from 8,760 hourly files). The remaining steps (track linking through speed) 
  take another ~6–8 h.
- Some `tracking_decadal/logs/log_SCREAM_1995..2002.log` entries show only ~1.4–2 h
  because those particular runs had `run_idfeature` … `run_identifymcs` set to `False` in
  the config (partial re-runs of the `matchpf`→`speed` tail only). The full-pipeline cost
  is reflected in the 2003–2005 logs.
- The comment block reading *"~15 hours / 512 workers / 64 per node"* present in every
  Slurm template is **stale**; the actual `#SBATCH` directives (`--ntasks-per-node=128`,
  `--time` as above) are authoritative.
- Occasional runs fail and need resubmission (e.g., `log_SCREAM_ne256_tune_1997_error.log`
  documents one such failure). Check the log tail for errors before assuming a job completed.
- **Recommendation:** keep the validated 8-node / 1,024-worker configuration.
  Reducing node count will increase wallclock proportionally.

---

### Step 2 — Post-processing to MCS statistics

#### Step 2a — Monthly MCS precipitation maps (NERSC TaskFarmer)

**Script:** `tracking_decadal/gen_scream_mcs_monthly_stats_taskfarmer.py` (SCREAM) /
`tracking_decadal/gen_imerg_mcs_monthly_stats_taskfarmer.py` (OBS)

**What it does:** Generates a TaskFarmer tasklist and Slurm submission script. Each task
calls wrapper `scripts/run_mcs_monthly_rainmap_latlon.sh <config.yml> <year> <month>`,
which runs `PyFLEXTRKR-dev/Analysis/calc_tbpf_mcs_monthly_rainmap.py`. For each
calendar month it reads the pixel-tracking files (`mcstrack_*.nc`) and the MCS track
statistics, and produces a monthly MCS precipitation map file.

**Input:** Per-year config YAMLs (from Step 1a) + pixel-tracking NetCDF files
(`<root_path>/mcstracking/mcstrack_YYYYMM*.nc`)

**Output:** Monthly `mcs_rainmap_YYYYMM*.nc` files under `<root_path>/stats/monthly/`

**Peak memory:** ~6 GB per task (measured; see
`tracking_decadal/logs/log_mcs_monthly_rainmap_SCREAM_decadal.log`).
Default `THREADS=12` (concurrent tasks/node) is conservative — a 512 GB Perlmutter node
can safely run far more; raise `--threads` to 24–48 for faster throughput.

```bash
cd tracking_decadal/

# Generate tasklist + Slurm script (SCREAM, default 1995-01 to 2005-12)
python gen_scream_mcs_monthly_stats_taskfarmer.py

# Custom date range, more threads, more nodes
python gen_scream_mcs_monthly_stats_taskfarmer.py \
    --start-date 2000-01 --end-date 2002-12 \
    --threads 24 --nodes 2

# Submit (must load taskfarmer module first)
module load taskfarmer
sbatch slurm.submit_mcs_monthly_rainmap_SCREAM_ne256_tune.sh

# Same workflow for OBS
python gen_imerg_mcs_monthly_stats_taskfarmer.py
module load taskfarmer
sbatch slurm.submit_mcs_monthly_rainmap_IMERGv7.sh
```

---

#### Step 2b — Monthly climatology from monthly data

**Script:** `scripts/calc_mcs_rainmap_climo_from_monthly.py`

**What it does:** Reads all monthly `mcs_rainmap_*.nc` files for a given date range,
computes 12-month climatological means of total precipitation, MCS precipitation, MCS
precipitation fraction, MCS precipitation frequency, MCS precipitation intensity, and MCS
cloud frequency; also computes the interannual standard deviation of annual means for each
variable.

**Gathering monthly files across years:** After Step 2a, the monthly `mcs_rainmap_*.nc`
files live under each year's `stats/monthly/` directory (`<root_path>` is per-year). Create
a single `monthly/` directory under each simulation set / OBS parent directory and symlink
(or copy) all years' files into it, so the climatology script can read them through one
`--indir`:

```bash
# e.g. /pscratch/sd/f/feng045/SCREAM-decadal/ne256/tune/monthly
cd <source>/monthly
ln -s ../*/stats/monthly/mcs_rainmap_*.nc .
```

**Input:** Gathered monthly `mcs_rainmap_YYYYMM*.nc` files (Step 2a output)

**Output:** `mcs_rainmap_monthly_climo_{YYYYMM}_{YYYYMM}.nc` in `--outdir`

```bash
python scripts/calc_mcs_rainmap_climo_from_monthly.py \
    --indir  /pscratch/sd/f/feng045/SCREAM-decadal/ne256/tune/monthly/ \
    --outdir /pscratch/sd/f/feng045/SCREAM-decadal/ne256/tune/monthly/ \
    --start-date 1995-01 \
    --end-date   2005-12
```

Repeat for each simulation set (`ne1024`, `ne256/ctl`, `ne256/tune`) and for the OBS
(`waccem/mcs_global_v3/MCSMIP/stats/monthly/`).

**E3SM (ne120, ne30) and SCREAM Cess2.** The E3SM tracking (PyFLEXTRKR `stats_format: rows`,
one folder per year) writes the monthly maps into each year's folder,
`<root>/<year>/stats/monthly/`, with `<root>` =
`/pscratch/sd/f/feng045/E3SM_polun/{ne120,ne30}_remap_0.1deg/mcs_tbpf`. Collect them with a
year-only glob (it does not match the `campaign_*` folders) and run the same script:

```bash
cd <root> && mkdir -p monthly && cd monthly
ln -s ../20[0-9][0-9]/stats/monthly/mcs_rainmap_*.nc .

python scripts/calc_mcs_rainmap_climo_from_monthly.py \
    --indir <root>/monthly --outdir <root>/monthly \
    --start-date 2009-01 --end-date 2011-12          # ne120; --end-date 2020-12 for ne30

# SCREAM Cess2 (3 km, 2019-08 to 2021-02): read from CFS, write the climatology to pscratch
python scripts/calc_mcs_rainmap_climo_from_monthly.py \
    --indir  /global/cfs/cdirs/m1867/zfeng/E3SM/SCREAMv1/cess2/global/mcs/stats/monthly \
    --outdir /pscratch/sd/f/feng045/SCREAM-decadal/cess2/monthly \
    --start-date 2019-08 --end-date 2021-02
```

Cess2 has 19 months: March to July occur once, August to February twice. The annual mean of
the climatology is the mean of its 12 monthly means.

---

#### Step 2c — Combine and filter MCS track statistics

**Script:** `scripts/combine_filter_mcs_trackstats.py`

**What it does:** Reads yearly `mcs_tracks_final_*.nc` files (dense netCDF of the old
pipeline) or `mcs_tracks_final_*.rows` folders (PyFLEXTRKR row tables), filters tracks whose
lifetime-mean location falls within a named bounding box (tropics or global), flattens
the jagged `(tracks × times)` arrays to a tidy one-row-per-timestep DataFrame (skipping
fill-padded entries), assigns globally unique track indices across all files, tags every row
with the calendar year in which its track starts (`period`), and writes a single compressed
Parquet file with the same 69 columns for every source. This pre-flattening step makes
notebook analysis much faster than opening the raw NetCDF files.

**Input:** Yearly `mcs_tracks_final_*.nc` files, or `mcs_tracks_final_*.rows` folders
(`--pattern '*mcs_tracks_final_*.rows'`, pyflex26.3 environment), in `<root_path>/stats/`. A
file that does not start on 1 January, such as the 19-month SCREAM Cess2 file, is read too.

**Output:** `mcs_tracks_final_combined_{region}_{start_year}_{end_year}.parquet`

```bash
# SCREAM ne256 tune, tropics (20°S–20°N)
python scripts/combine_filter_mcs_trackstats.py \
    --indir  /pscratch/sd/f/feng045/SCREAM-decadal/ne256/tune/stats/ \
    --region tropics \
    --start-year 1995 --end-year 2005

# OBS IMERGv7, tropics (custom glob pattern for MCSMIP filenames)
python scripts/combine_filter_mcs_trackstats.py \
    --indir   /pscratch/sd/f/feng045/waccem/mcs_global_v3/MCSMIP/stats/ \
    --pattern 'mcsmip_mcs_tracks_final_*.nc' \
    --region  tropics \
    --start-year 1998 --end-year 2024

# Available regions: tropics (20°S–20°N), global (90°S–90°N)
# Override bounds with --latmin/--latmax/--lonmin/--lonmax

# E3SM ne120 (row tables): collect the yearly folders by links, then combine
cd /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf && mkdir -p stats && cd stats
ln -s ../20[0-9][0-9]/stats/mcs_tracks_final_*.rows .
python scripts/combine_filter_mcs_trackstats.py \
    --indir  /pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf/stats \
    --pattern '*mcs_tracks_final_*.rows' --region tropics

# SCREAM Cess2 (one dense file of 19 months), written to pscratch
python scripts/combine_filter_mcs_trackstats.py \
    --indir  /global/cfs/cdirs/m1867/zfeng/E3SM/SCREAMv1/cess2/global/mcs/stats \
    --outdir /pscratch/sd/f/feng045/SCREAM-decadal/cess2/stats --region tropics
```

**Cess2 re-run with row tables (SCREAM 3 km TUNE).** The 2026-01 Cess2 statistics were made with
an older PyFLEXTRKR that did not write `total_volrain` / `total_heavyvolrain` (the converter fills
such a column with NaN and prints a warning). `tracking/slurm_SCREAM-Cess2_stats_rerun.sh` re-runs
identifymcs, matchpf, robustmcs and speed (not mapfeature) with `stats_format: rows`
(`tracking/config_mcs_tbpf_SCREAMv1-Cess2_rows.yml`; 4 nodes, about 30 minutes) in a new root
`/pscratch/sd/f/feng045/SCREAM-decadal/cess2/mcs_rerun/` that links the old cloudid and pixel
files, so the old tree is untouched. The speed step reads the old pixel files, which is valid
only because the new robust MCS set is identical to the old one (79,370 tracks, same start times
and durations). The Tb-based columns are identical; the precipitation-feature (PF) columns and
the movement variables differ in about 4 % of the rows (see the progress log in
`docs/PLAN_scream_e3sm_mcs_evaluation.md`).

**Copy to CFS.** The shared stats folder `.../cess2/global/mcs/stats` is owned by `wcmca1` (mode 755),
so the new outputs were staged by feng045 in `.../cess2/global/stats_rerun_20261116_staging/` (checked
byte by byte against pscratch) and `scripts/cess2_cfs_swap_wcmca1.sh` does the swap as `wcmca1`:
the 4 replaced old dense files go to `stats/archive_20261116_old_dense_version/` (with a README and a
log), the 4 row folders, the new dense final file and the two combined Parquet files move into
`stats/`; `trackstats_*`, `tracknumbers_*` and `monthly/` stay. Run it with `--dry-run` first.

```bash
# interactive allocation (own, account m1657), then on its first node:
salloc --no-shell -A m1657 -C cpu -q interactive -N 4 -t 01:30:00 -J cess2_rerun
bash tracking/slurm_SCREAM-Cess2_stats_rerun.sh <jobid> 4      # logs in <root>/logs/
python scripts/combine_filter_mcs_trackstats.py --indir <root>/stats --pattern 'mcs_tracks_final_*.rows' \
    --region tropics --outdir <root>/parquet
```

**Unified format.** Every source (OBS, SCREAM, E3SM) has one combined file with **one row per
track and time step** and the same 69 columns (`UNIFIED_COLUMNS` in the script; a file with
other columns is an error), so the notebooks concatenate the sources in memory with a `source`
label. The row tables (`tracks.parquet`, `entries.parquet`, `fragments.parquet`, `meta.json`)
are joined into that table, not merged with the other Parquet files:

| row-table file | columns of the combined file |
| --- | --- |
| `tracks` | per-track variables, repeated on every row of the track (`track_duration`, `start_status`, `start_basetime`, `pbc_flag`, `mcs_duration`, `pf_lifetime`, …) |
| `entries` | per-time variables; `k` → `relative_step`; `pf_*__0` → `pf_*` (the largest precipitation feature) |
| `fragments` | `merge_ccs_area`, `split_ccs_area`: sums of `ccs_area` by kind (0 merge, 1 split) |
| `meta.json` | integer fill values (−9999) → NaN, `time_resolution_hour` |

The two input routes give identical tables (checked on E3SM ne120 2010 and ne30 2012 and by
`scripts/tests/test_combine_filter_mcs_trackstats_rows.py`). `period` reproduces the `period` of
the existing OBS and SCREAM files for every row.

---

#### Step 2d — OBS Tb data-quality: monthly valid-data counts (NERSC TaskFarmer)

**Script:** `scripts/gen_mergir_missing_data_taskfarmer.py`

**What it does:** Generates a TaskFarmer tasklist and Slurm submission script to compute
monthly **valid Tb-data counts** from the combined Tb+IMERG 10 km hourly files
(`merg_YYYYMMDD??_10km-pixel.nc`). Each hourly file contains two 30-minute snapshots of
the Global MergedIR brightness temperature dataset (at the :00 and :30 minute marks), so
the script separately counts valid observations at both minute marks
(`count_00min` / `count_30min`) along with the total expected time steps
(`ntimes_00min` / `ntimes_30min`).

Each task calls wrapper `scripts/run_mergir_missing_data.sh <year> <month>` →
`scripts/calc_mergir_missing_data.py`.

**Input:** Hourly `merg_YYYYMMDD??_10km-pixel.nc` files in
`/pscratch/sd/w/wcmca1/GPM/IR_IMERG_Combined_V07B/<year>/`

**Output:** Monthly `merg_monthly_validcount_*.nc` files

```bash
cd scripts/

# Generate tasklist + Slurm script (default 1998-01 to 2024-12)
python gen_mergir_missing_data_taskfarmer.py

# Custom range (fast debug job)
python gen_mergir_missing_data_taskfarmer.py \
    --start-date 2000-01 --end-date 2000-12 \
    --threads 24 --nodes 1 --qos debug --time 00:30:00

# Submit
module load taskfarmer
sbatch slurm.submit_mergir_missing_data.sh
```

---

#### Step 2e — E3SM `heavy_rainrate_thresh` sensitivity (one year, several thresholds)

**Script:** `tracking_e3sm/gen_heavyrain_sensitivity.py`

**Why:** E3SM at 25 and 100 km has far fewer MCSs than observed, because the MCSMIP
definition needs the maximum precipitation-feature rain rate to exceed `heavy_rainrate_thresh`
(10 mm/h) for 4 h. The key is read by two PyFLEXTRKR steps, matchpf (the heavy-rain sums) and
robustmcs (the MCSMIP test), so every run starts at matchpf and goes on through robustmcs,
mapfeature, speed, dense_netcdf and rainmap. The steps before matchpf do not depend on the key
and are shared with the production run.

**What it does:** for every model and threshold it writes, under
`<root>_sens/heavyrain_<tag>/` (`<root>` as in Step 2b, tag `5p0`, `3p0`, …), a copy of the
production stats config of the year with only the sensitivity lines changed, a one-node Slurm
script (pinned PyFLEXTRKR code, then the climatology of the 12 monthly rain maps) and the run
tree `<year>/` whose `tracking` folder and identifymcs output are links to the production run.
Nothing is submitted without `--submit`; the production folders are never written.

```bash
# control run: the production value must reproduce the production outputs exactly
python tracking_e3sm/gen_heavyrain_sensitivity.py --models ne120 --thresholds 10.0
# the tests (10 jobs, about 10 node-hours and about 1 TB of pixel files); add --submit to sbatch
python tracking_e3sm/gen_heavyrain_sensitivity.py --models ne120 ne30 --thresholds 5.0 3.0 2.0 1.5 1.0
# baseline climatology: the production year with the same script
python scripts/calc_mcs_rainmap_climo_from_monthly.py --indir <root>/2010/stats/monthly \
    --outdir <root>_sens/baseline_2010/monthly --start-date 2010-01 --end-date 2010-12
```

**Resubmitting a run that failed in a later step.** `--skip-completed-steps` writes
`skip_completed_steps: True`, so matchpf, robustmcs and mapfeature (their outputs are complete)
are not run again; the run tree of an existing run is never emptied by the script:

```bash
python tracking_e3sm/gen_heavyrain_sensitivity.py --models ne30 --thresholds 3.0 2.0 1.5 1.0 \
    --code-dir <pinned worktree> --skip-completed-steps --time 01:00:00 --submit
```

**The speed step and `speed_max_nan_pair_fraction` (2026-11-17).** Four ne30 runs (3.0 to 1.0 mm/h)
stopped in the speed step with an `IndexError`: a track that occupies one row of the grid (row 0
in ne30 at 3.0 mm/h, 1 of 127,748 measured feature pairs) has an empty bounding box and an empty
correlation map. PyFLEXTRKR-dev commit 80438a4 gives such a pair NaN movement, logs it, counts it
(output attributes `speed_pairs_measured`, `speed_pairs_without_movement`) and stops only if the
share exceeds the config key `speed_max_nan_pair_fraction` (default 0.05). The 4 runs were
resubmitted with the code of that commit (pinned worktree `tbpf_code_80438a4`); the other 6 runs
used `tbpf_code_a4b8ad8`, which gives identical results for every pair that does not crash. A
second case, a correlation map with a tied maximum (no pixel above its 99.5 % quantile: 92 of 186,246 pairs = 0.05 % in ne30 at 2.0 mm/h, none at 10 mm/h), used to
get a huge lag that `max_speed_thresh` removed and the filter interpolated, with an invented direction of exactly 45 degrees. Since commit 38ae5d1 (pinned
worktree `tbpf_code_38ae5d1`, used by the production runs) it is NaN as well, logged and counted. See `docs/PLAN_scream_e3sm_mcs_evaluation.md`.

**Production at the chosen threshold (2026-11-17: 2.0 mm/h).** The MCS sets of the sensitivity runs are identical for 2.0, 1.5 and 1.0 mm/h (the
precipitation-feature threshold is 2.0 mm/h), so 2.0 was chosen for ne30 and ne120. `--production` runs every production year (ne120 2009-2011, ne30
2009-2020) from matchpf to trackpcp in a new tree next to the 10 mm/h production, which stays untouched:

```text
<e3sm_root>/<model>_remap_0.1deg/mcs_tbpf_hr2p0/
    <year>/            tracking and the identifymcs output are links to mcs_tbpf/<year>; stats/ (row tables, dense file, monthly/ rain maps,
                       trackpcp_*), mcstracking/ (pixel files), profile/ (step ledger)
    campaign_<year>/   config, Slurm script and logs of the year (one job of one node)
    stats/, monthly/   across the years (links), made by tracking_e3sm/finalize_production_tree.py, plus the combined Parquet files
                       and the multi-year climatology
```

```bash
python tracking_e3sm/gen_heavyrain_sensitivity.py --production --models ne120 --years 2009 2010 2011 --thresholds 2.0 \
    --code-dir <pinned worktree> --time 03:00:00 --submit                  # then the same for --models ne30 --years 2009 ... 2020
python tracking_e3sm/finalize_production_tree.py --models ne120 ne30 --tag 2p0    # after all years are done; prints the next commands
```

The control run is compared with production by `PyFLEXTRKR-dev/tests/tbpf_compare.py` (row
tables and pixel files) and `netcdf_differences` of the same module (monthly rain maps and the
dense final file).

---

### Housekeeping — HPSS backup of the E3SM output

`tracking_e3sm/hpss_e3sm_backup.py` / `hpss_e3sm_restore.py` (xfer jobs `slurm_hpss_e3sm_*.sbatch`) write every directory of
`<root>/<model>_remap_0.1deg` (`mcs_tbpf`, `mcs_tbpf_hr2p0`, `mcs_tbpf_sens`, `olr_pcp`) to one htar archive under
`/home/f/feng045/E3SM_polun/<model>_remap_0.1deg/` and bring back whole archives or sub-folders. htar cannot take the long absolute symbolic
links of these trees, so it archives the real files and a manifest `<dir>.tar.links.tsv` recreates the links. Layout, plan reading, restore
recipes and the tests: `docs/hpss_e3sm.md`.

---

### Step 3 — Analysis and visualization

> **Note:** Run these notebooks on a **NERSC Perlmutter compute node** (e.g., via a
> Jupyter session on a compute node or an `salloc` interactive session) due to the memory
> requirements of loading large climatology and track-statistics datasets.

#### `Notebooks/plot_global_mcs_climo_rainmap_decadal_imerg.ipynb`

Plots **annual and monthly mean MCS precipitation statistics** as global maps, comparing
two SCREAM simulation sets against IMERGv7 observations.

- **Reads:** Monthly climatology files produced in Step 2b
  (`mcs_rainmap_monthly_climo_*.nc`) for each simulation set and OBS, plus an ERA5
  topography file and the MergedIR valid-data mask (`merg_valid_fraction_*.nc` from Step
  2d / `plot_mergir_missingdata_map.ipynb`).
- **Produces:** Multi-panel global maps of total precipitation, MCS precipitation, MCS
  fraction, MCS frequency, and MCS cloud frequency, saved to
  `/global/cfs/cdirs/m1867/zfeng/SCREAM-decadal/figures/`.

#### `Notebooks/plot_tropical_mcs_trackstats_land_ocean.ipynb`

Compares **tropical MCS lifetime statistics** between IMERG observations and SCREAM model
output, separated by land vs. ocean tracks.

- **Reads:** Combined Parquet files produced in Step 2c
  (`mcs_tracks_final_combined_tropics_*.parquet`) for each simulation set and OBS.
- **Produces:** Box-whisker plot of per-track lifetime statistics (duration,
  precipitation rate, size, propagation speed, etc.) split by land/ocean classification,
  composite time-evolution plots of mean/median time series of track properties by 
  track-duration bins,
  saved to `/global/cfs/cdirs/m1867/zfeng/SCREAM-decadal/figures/`.
- The `scripts/combine_filter_mcs_trackstats.py` pre-processing step (Step 2c) must be
  run before running this notebook.

#### `Notebooks/plot_mergir_missingdata_map.ipynb`

Computes and visualizes the **MergedIR Tb valid-data fraction** over the full IMERGv7
record.

- **Reads:** Monthly `merg_monthly_validcount_*.nc` files produced in Step 2d.
- **Produces:**
  - Pentad maps showing valid-data fraction for both the :00 and :30 minute marks,
    grouped into multi-year pentad periods (e.g., 1998–2000, 2000–2005, …).
  - Annual maps of valid-data fraction (`merg_valid_fraction_*.nc`).
  - A saved annual-mean valid-fraction file (`merg_valid_fraction_{min_year}_{max_year}.nc`)
    used as a data-coverage mask in the global MCS climatology plots above.


#### `Notebooks/plot_global_mcs_climo_rainmap_scream_e3sm_obs.ipynb`

Global maps of the **MCS cloud frequency, MCS precipitation and MCS precipitation fraction** of
the observation, the SCREAM sets (3-km CTL = ne1024, 3-km TUNE = Cess2, 13-km CTL and TUNE) and
E3SM (25-km = ne120, 100-km = ne30), one variable per figure: the observation, the
model − OBS bias of every simulation, and the cos(latitude)-weighted zonal mean of all sources.

- **Reads:** the monthly climatology files of Step 2b for every source, the MergedIR
  valid-data mask and the ERA5 topography. **E3SM since 2026-11-18: the 2.0 mm/h production**
  (`mcs_tbpf_hr2p0`, Step 2e) with `heavy_rainrate_thresh` 2.0 instead of the 10 mm/h of `mcs_tbpf`: area-mean
  MCS precipitation fraction (60S-60N, cells valid in OBS) 25-km 29.9 % (10 mm/h: 18.3 %), 100-km 25.5 %
  (10 mm/h: 3.7 %), OBS 50.5 %; cloud frequency 5.2 % / 4.3 % (OBS 3.7 %); MCS precipitation 0.94 / 0.81 mm/day
  (OBS 1.54).
- **Functions:** `plot_maps_cbar_per_row_or_col` (one colorbar per row, or per column; the
  7-source overviews show frequency, precipitation, fraction) and `plot_obs_and_bias_maps`
  (observation colorbar and bias colorbar; (a) OBS, (b) zonal mean, then 3-km CTL / TUNE,
  13-km CTL / TUNE, 25 / 100-km, titles such as `3-km (CTL − OBS)`; gray cells without observation
  in every panel). **Figure size:** the maps fill their cells (`aspect='auto'`, the default), so
  the figure height is solved from the measured width of a map cell and the true aspect of the
  projection (0.373 for Robinson, 60S-60N): the maps are not stretched and there are no gaps
  (measured on the figures). `figsize=(x, y)` overrides the solved size; `aspect='equal'` lets
  cartopy keep the true shape inside any cell instead. The zonal axes has its top at the top of
  the OBS map and its left edge close to it. Bias levels follow the SCREAM biases; the 100-km
  E3SM bias saturates them.
- **OBS band:** the gray band of the OBS zonal mean is, with `obs_iqr_method = 'cell_iqr'` (the
  default), the zonal mean of the cell-wise interquartile range across the years 2007-2017 (the
  local interannual spread, about 25 % of the line); `'zonal_iqr'` is the IQR of the annual zonal mean
  itself (2-10 % of the line, hidden by the OBS line) (`obs_zonal_band`). **The band is averaged like the
  line of the same variable** (since 2026-11-18): area-weighted for the cloud frequency and the precipitation,
  precipitation-weighted for the fraction, which is a ratio of sums (the line is dominated by the rainy
  cells). Before, the fraction percentiles were also area-weighted, which put the band about 6 % below the
  line (the line was above the band in 35 of 60 latitude bins; now it is inside the band in 60 of 60). It needs the monthly OBS rain maps of
  the **same dataset as the OBS climatology (TC included)**, copied from
  `/global/cfs/cdirs/wcm_shr/gsharing/MCS_Global/V3/MCSMIP/stats_mcsmip/monthly/` to
  `obs_monthly_dir`; they reproduce the climatology file exactly. The Zenodo monthly maps and
  `monthly_extc` are the TC-excluded set (MCS precipitation about 9 % lower): do not mix them.
- **Inputs from CFS (2026-11-19):** all sources are read from CFS: the E3SM climatologies from `/global/cfs/cdirs/m1867/zfeng/E3SM_polun/<model>_remap_0.1deg/mcs_tbpf_hr2p0/monthly`,
  the Cess2 climatology from `SCREAM-decadal/cess2/monthly`, ne1024 / ne256 / OBS as before, and the 132 monthly OBS maps of the band from the original files of the V3 dataset
  (`/global/cfs/cdirs/wcm_shr/gsharing/MCS_Global/V3/MCSMIP/stats_mcsmip/monthly`). Every one of these files was compared byte for byte with the pscratch copy the notebooks used before, the
  three notebooks were re-run on the CFS inputs and **all 25 output files (figures, CSV, HTML) are byte-identical** to the pscratch-based run, the OBS band cache identical in all arrays.
  Only the figures, tables and the band cache are written to pscratch.
- **Zonal-mean panel:** the legend (one column) is outside the axes, at their upper right, and may reach into the right margin of the figure (the saved file is cropped tight); if it would touch the
  bias colorbar (a zonal row below the maps) it goes to the right of the colorbar. The y range has only 10 % headroom above the lines (`zonal_headroom = 0.1`), so that the lines fill the axes.
  `zonal_legend_outside = False` and `zonal_headroom = 0.9` give the old legend inside the axes.
- **Configuration:** one cell with all paths, labels, colors, levels, seasons and options
  (`font_scale`, `figsize`, `aspect`, `zonal_slot`, `show_obs_iqr`, `obs_iqr_method`). The notebooks of this evaluation
  use the `STIXGeneral` font (set in the imports cell). Kernel `pyflex26_3`. Figures go to
  `figdir` (pscratch by default).

#### `Notebooks/plot_mcs_heavyrain_sensitivity_e3sm.ipynb`

Results of Step 2e: for each E3SM model and variable, the observation, the bias of every
`heavy_rainrate_thresh` and the zonal means of all runs, with the MCS precipitation fraction as
the key metric, a summary table (robust MCS count, heavy-rain total, area means, map RMSE) and
a summary figure. It uses the same functions and Configuration style as the notebook above and
lists the runs that are not finished. Its inputs are on CFS too: the working set of the ten sensitivity runs (per run the
1-year climatology and the final row folder) in `E3SM_polun/<model>_remap_0.1deg/mcs_tbpf_sens/heavyrain_<tag>/2010/stats`, the baseline climatologies in
`mcs_tbpf_sens/baseline_2010/monthly` (made from the CFS production maps) and the baseline rows in `mcs_tbpf/stats`; the full run folders are on pscratch and in HPSS (`docs/hpss_e3sm.md`).
The zonal panel has the same legend and y range as the maps notebook.

#### `Notebooks/plot_tropical_mcs_trackstats_all_sources.ipynb`

Loads the combined Parquet files of Step 2c for the observation, SCREAM and E3SM (one
Configuration section with label, folder, years and color of every source, and every setting of the
analyses), checks that they have the same columns and data types, summarizes tracks and durations,
and then runs the analyses of `plot_tropical_mcs_trackstats_land_ocean.ipynb` for all 7 sources
(about 4 minutes on a compute node):

- land / ocean classification (lifetime min / max `pf_landfrac`) and one row per track of lifetime
  statistics;
- **box-whisker plots** of the lifetime statistics (land / ocean on x, one box per source);
- the **table of mean % differences vs the observation with Mann-Whitney U significance tests**
  (HTML, `✘` = not significant, `L:` land, `O:` ocean);
- **composite life cycles** of tracks with a natural start and end, by duration bin: by lifetime
  (land and ocean), and land versus ocean with all sources overlaid (two duration bins, and one bin
  with the interquartile range shaded), each **interpolated** (time-normalized, the reference
  setting) and **raw** (relative time); `composite_track_evolution` is vectorized and checked
  against the track-by-track loop in the notebook (difference 3e-16).

A duration bin with fewer than `MIN_TRACKS_COMPOSITE` tracks is not composited. **E3SM since 2026-11-18:
the 2.0 mm/h production** (`mcs_tbpf_hr2p0/stats` on CFS, tropics): 25-km 66,786 tracks (2009-2011) and 100-km
30,998 tracks (2009-2020), against 7,500 per year and about 90 per year at 10 mm/h, so the 100-km source
(11,133 land and 11,443 ocean tracks with a lifetime) now has composites. The Cess2 (3-km TUNE) row reads the
re-run statistics (with `total_volrain`) from the CFS folder `cess2/global/mcs/stats`.
