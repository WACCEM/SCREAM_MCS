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

---

#### Step 2c — Combine and filter MCS track statistics

**Script:** `scripts/combine_filter_mcs_trackstats.py`

**What it does:** Reads yearly `mcs_tracks_final_*.nc` files, filters tracks whose
lifetime-mean location falls within a named bounding box (tropics or global), flattens
the jagged `(tracks × times)` arrays to a tidy one-row-per-timestep DataFrame (skipping
fill-padded entries), assigns globally unique track indices across all years, and writes a
single compressed Parquet file. This pre-flattening step makes notebook analysis much
faster than opening the raw NetCDF files.

**Input:** Yearly `mcs_tracks_final_*.nc` files in `<root_path>/stats/`

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
```

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
