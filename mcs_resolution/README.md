# MCS resolution-sensitivity study: SCREAM 3 km and 13 km, E3SM 25 km and 100 km, and IMERG observations

This folder holds the **setup of the MCS tracking** of all data sets of the study ([tracking/](tracking)) and the **Sahel MCS animations**
([animation/](animation)). This page also lists where everything else of the study is. State of the files described here: 2026-11-25.

Contents: [Data sets](#1-data-sets) · [Which files made and describe each data set](#2-config-code-and-statistics-of-each-data-set) ·
[Differences between the data sets](#3-differences-between-the-data-sets) · [Inventory of scripts and folders](#4-inventory-of-scripts-and-folders) ·
[Running the tracking again](#5-running-the-tracking-again) · [Sahel animations](#6-sahel-mcs-animations) · [Data at risk and open items](#7-data-at-risk-and-open-items)

## 1. Data sets

The key is the one used in `Notebooks/plot_tropical_mcs_trackstats_all_sources.ipynb` and in the animation tools.

| key | label | model / data | tracked period | years in the analysis files |
|---|---|---|---|---|
| `obs` | OBS | GPM MergedIR Tb + IMERG V07B (global MCS V3, MCSMIP) | 1998-2025 (yearly) | 2007-2017 |
| `scream3_ctl` | 3-km CTL | SCREAM decadal ne1024 | 1995-2005 (yearly) | 1995-2005 |
| `scream3_tune` | 3-km TUNE | SCREAMv1 Cess2 | 2019-08-03 to 2021-03-05 (one run) | 2019-2021 |
| `scream13_ctl` | 13-km CTL | SCREAM decadal ne256, run `01` | 1995-2005 (yearly) | 1995-2005 |
| `scream13_tune` | 13-km TUNE | SCREAM decadal ne256, run `03` | 1995-2005 (yearly) | 1995-2005 |
| `e3sm25` | 25-km | E3SM ne120 | 2009-2011 (yearly) | 2009-2011 |
| `e3sm100` | 100-km | E3SM ne30 | 2009-2020 (yearly) | 2009-2020 |

All data sets are tracked on a 0.1 x 0.1 degree lat-lon grid with hourly Tb and precipitation.

## 2. Config, code and statistics of each data set

### Tracking inputs, configs and code

| key | input data | tracking config (the record of the run) | PyFLEXTRKR code that ran |
|---|---|---|---|
| `obs` | `/pscratch/sd/w/wcmca1/GPM/IR_IMERG_Combined_V07B/<year>/` | `/global/cfs/cdirs/wcm_shr/gsharing/MCS_Global/V3/MCSMIP/config_mcs_tbpf_imergv7_mcsmip.yml` (published with the data; saved with the 2024 dates) | old workflow; the commit is not recorded in this repository |
| `scream3_ctl` | `/global/cfs/cdirs/e3smdata/simulations/scream-decadal/MCS/input4tracking/ne1024/` | `tracking/obs_scream_decadal/as_run/config_mcs_tbpf_SCREAM_decadal_<year>.yml` | `runscripts/run_mcs_tbpf_mcsmip.py` of the working copy of PyFLEXTRKR-dev (no pinned commit); logs of 2026-06-07 and 06-08 |
| `scream3_tune` | HEALPix catalog `scream_cess2` (`hackathon/catalog/NERSC/main.yaml`) | pixel files: `tracking/scream_cess2/config_mcs_tbpf_SCREAMv1-Cess2.yml`; statistics: `..._rows.yml` | pixel files: `run_mcs_tbpf_mcsmip.py` (environment `pyflex-dev`); statistics re-run of 2026-11-16: `run_mcs_tbpf_unified.py` of the pinned worktree `tbpf_code_a4b8ad8` |
| `scream13_ctl` | `.../input4tracking/ne256/01/` | `.../as_run/config_mcs_tbpf_SCREAM_ne256_ctl_<year>.yml` | as `scream3_ctl`; logs of 2026-06-09 to 06-11 |
| `scream13_tune` | `.../input4tracking/ne256/03/` | `.../as_run/config_mcs_tbpf_SCREAM_ne256_tune_<year>.yml` | as `scream3_ctl`; logs of 2026-06-11 to 06-13 |
| `e3sm25` | `/pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/olr_pcp/` | `tracking/e3sm/as_run/ne120_hr10/` (idfeature to identifymcs) and `.../ne120_hr2p0/campaign_<year>/` (matchpf onward) | 10 mm/h campaigns: `tbpf_perf_code` (2009; commit 1e7d2c4), `tbpf_code_a4b8ad8` (2010, 2011). 2 mm/h: `tbpf_code_38ae5d1` |
| `e3sm100` | `/pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/olr_pcp/` | `.../ne30_hr10/` and `.../ne30_hr2p0/campaign_<year>/` | 10 mm/h: `tbpf_code_a4b8ad8`; `tbpf_code_ece05b2` for the February tracking job and the statistics job of 2012, 2016, 2020 (`calendar: noleap`). 2 mm/h: `tbpf_code_38ae5d1` |

The pinned worktrees are in `/pscratch/sd/f/feng045/`.

* **OBS: the IMERG template of this repository did not make the V3 data.** `config_mcs_tbpf_IMERGv7_mcsmip_template.yml` (and the 1998-2024 configs
  made from it) has `idclouds_minute: 00`, `duration_range: [2, 100]`, `pbc_extended_fraction: 0.2`. The published V3 config has `30`, `[2, 400]`, `0.5`,
  and the V3 pixel files are stamped hh:30. The combined OBS Parquet of the notebooks is the V3 run too: its times are hh:30, its 2010 global file has
  exactly the 41,967 tracks that pass the region filter out of the 42,237 of the V3 yearly file (the other 270 have a mean longitude beyond 180 degrees),
  and all 258 tracks that start over the Sahel in August 2010 are identical. **Use the V3 config.**
* **E3SM was not set up from `e3sm_polun/tracking`.** That folder belongs to the earlier study of the native 1 degree `E3SM_CTL` run and 1 degree IMERG.
  The 0.1 degree runs were made by `PyFLEXTRKR-dev/config/generate_tbpf_mcstracking_scripts.py` (10 mm/h) and then
  `tracking/e3sm/gen_heavyrain_sensitivity.py --production` (2 mm/h). From `e3sm_polun`, only the input remapping (`regrid/`) belongs to this study.

### Pixel files and track statistics

In a pixel-level file `mcstrack_*.nc` the mask `cloudtracknumber` has the value N over the MCS of **row N-1 of the yearly final statistics file of the same
run**. The combined Parquet files renumber the tracks, so they cannot be used with the pixel files. The pairs below passed the pairing check of the
animation tools (`animation/sahel_common.py`) for one week each.

| key | pixel-level files | yearly final statistics | combined Parquet of the notebooks (tropics and global) |
|---|---|---|---|
| `obs` | `.../MCS_Global/V3/MCSMIP/mcstracking_mcsmip/<dates>/` (CFS) | `.../MCSMIP/stats_mcsmip/mcsmip_mcs_tracks_final_<dates>.nc` (dense netCDF) | `/global/cfs/cdirs/m1867/zfeng/SCREAM-decadal/mcs_global_v3/MCSMIP/stats/` |
| `scream3_ctl` | `/pscratch/sd/w/wcmca1/SCREAM-decadal/mcs_tbpf/ne1024/<year>/mcstracking/<dates>/` | `/global/cfs/cdirs/m1867/zfeng/SCREAM-decadal/ne1024/stats/` (dense netCDF) | same folder |
| `scream3_tune` | `/pscratch/sd/w/wcmca1/SCREAMv1-cess2/mcs/mcstracking/20190803.0000_20210306.0000/` | `/global/cfs/cdirs/m1867/zfeng/E3SM/SCREAMv1/cess2/global/mcs/stats/` (row tables and dense netCDF) | same folder (copy in `SCREAM-decadal/cess2/stats/`) |
| `scream13_ctl` | `.../mcs_tbpf/ne256/ctl/<year>/mcstracking/<dates>/` | `.../SCREAM-decadal/ne256/ctl/stats/` (dense netCDF) | same folder |
| `scream13_tune` | `.../mcs_tbpf/ne256/tune/<year>/mcstracking/<dates>/` | `.../SCREAM-decadal/ne256/tune/stats/` (dense netCDF) | same folder |
| `e3sm25` | `.../E3SM_polun/ne120_remap_0.1deg/mcs_tbpf_hr2p0/<year>/mcstracking/<dates>/` | `.../mcs_tbpf_hr2p0/<year>/stats/` (row tables and dense netCDF; CFS copy in `m1867/zfeng/E3SM_polun/.../mcs_tbpf_hr2p0/stats/`) | CFS folder of the copy |
| `e3sm100` | `.../ne30_remap_0.1deg/mcs_tbpf_hr2p0/<year>/mcstracking/<dates>/` | as `e3sm25` | as `e3sm25` |

`<dates>` is `YYYY0101.0000_<YYYY+1>0101.0000`. SCREAM and OBS statistics are the dense netCDF files of the old workflow; E3SM uses row tables
(`stats_format: rows`, [PyFLEXTRKR docs](https://github.com/WACCEM/PyFLEXTRKR-dev/blob/perf-workflow/docs/rowstats.md)). `scripts/combine_filter_mcs_trackstats.py`
reads both and writes the combined Parquet files with the same 69 columns (Step 2c of the [main README](../README.md)).

The SCREAM pixel folders are not the `root_path` of the decadal configs (`/pscratch/sd/f/feng045/SCREAM-decadal/...`): give plotting tools the pixel
folder and the statistics file explicitly, as `animation/sahel_sources.yaml` does.

## 3. Differences between the data sets

Compared with one config per data set. The same in all: `cloudtb_core/cold/warm` 225 / 241 / 261 K, `area_thresh` 800 km2, `mincoldcorepix` 4,
`othresh` 0.5, `timegap` 3.1 h, `mcs_tb_area_thresh` 40,000 km2, `mcs_tb_duration_thresh` 4 h, `mcs_pf_durationthresh` 4 h, `mcs_pf_gap` 1,
`mcs_pf_majoraxis_for_lifetime` 20 km, `pf_rr_thres` 2 mm/h, `pixel_radius` 10 km.

| setting | OBS (V3) | 3-km CTL | 3-km TUNE | 13-km CTL / TUNE | 25 / 100-km |
|---|---|---|---|---|---|
| **`heavy_rainrate_thresh` [mm/h]** | 10 | 10 | 10 | 10 | **2.0** |
| `geolimits` (latitude) | 60 | 65 | 60 | 65 | 60 |
| `area_method` | `latlon` | `latlon` | not set (code default) | `latlon` | `latlon` |
| `pbc_extended_fraction` | 0.5 | 0.2 | 0.25 | 0.2 | 0.1 |
| `duration_range` [time steps] | 2-400 | 2-100, `duration_range_auto_update` | 2-650 | 2-100, auto update | 2-400, auto update |
| Tb | `Tb` | from OLR `LW_flux_up_at_model_top` | from OLR `rlut` | from OLR `LW_flux_up_at_model_top` | from OLR `FLUT` |
| precipitation | `precipitation` | `precip_total_surf_mass_flux` | `pr` | `precip_total_surf_mass_flux` | `PRECT` |
| other keys only here | `idclouds_hourly: 1`, `idclouds_minute: 30` | | | | `core_operator: lt`, `growth_method: edt`, `calendar` (see below) |

* **E3SM threshold.** `heavy_rainrate_thresh` is 2.0 mm/h for E3SM and 10 mm/h for OBS and SCREAM: at 10 mm/h the coarse E3SM runs have very few MCSs
  (sensitivity tests: Step 2e of the [main README](../README.md), `Notebooks/plot_mcs_heavyrain_sensitivity_e3sm.ipynb`). The 10 mm/h E3SM outputs
  (`mcs_tbpf/`) still exist next to the 2 mm/h ones (`mcs_tbpf_hr2p0/`). The notebooks use 2 mm/h.
* **Calendar.** The model runs have no 29 February. E3SM 2012, 2016 and 2020 were tracked with `calendar: noleap`, without which tracks are cut at 1 March.
  The SCREAM decadal runs used the old workflow, which has no such key; whether their tracks are cut at 1 March of 1996, 2000 and 2004 has not been checked.
* **3-km TUNE.** The pixel files are from the older run, the statistics from the re-run. According to the main README the re-run has the identical set of
  79,370 robust MCSs (same start times and durations); precipitation-feature and movement columns differ in about 4 % of the rows.

## 4. Inventory of scripts and folders

Paths are relative to the `scream` repository unless they start with `/`.

### Tracking setup (this folder)

| folder / file | content |
|---|---|
| `tracking/obs_scream_decadal/` | `config_mcs_tbpf_{IMERGv7_mcsmip,SCREAM_decadal,SCREAM_ne256_ctl,SCREAM_ne256_tune}_template.yml`, the 4 `slurm_mcs_*_template.sh`, `gen_scream_tracking_scripts.py`, `gen_imerg_tracking_scripts.py` |
| | `gen_{scream,imerg}_mcs_monthly_stats_taskfarmer.py` (monthly MCS rain maps), `slurm_zstash_to_hpss.sh`, `config_mcs_SCREAM_decadal_HsiYen.yml` (config of Hsi-Yen Ma) |
| `tracking/obs_scream_decadal/as_run/` | frozen record: per-year configs and job scripts (git-ignored), TaskFarmer task lists and job scripts, `logs/` (git-ignored). Contents are unchanged, so they still name the old folder `tracking_decadal/`. No per-year IMERG job scripts were kept |
| `tracking/obs_scream_decadal/jobs/` | where the generators write from now on (git-ignored) |
| `tracking/scream_cess2/` | `config_mcs_tbpf_SCREAMv1-Cess2.yml` and `..._rows.yml`, `slurm_SCREAM-Cess2_global.sh`, `..._global_dask.sh`, `..._stats_rerun.sh` |
| `tracking/e3sm/` | `gen_heavyrain_sensitivity.py` (2 mm/h production and sensitivity runs), `finalize_production_tree.py` (cross-year links) |
| `tracking/e3sm/templates/` | **copies**: `config_mcs_tbpf_e3sm_0p1deg_template.yml`, `slurm_tbpf_mcstracking_{track,stats_multinode}.sh` (from `PyFLEXTRKR-dev/config/` at 38ae5d1; the campaigns ran with the version of their pinned code) and `config_mcs_tbpf_e3sm_ne30_0p1deg_template.yml` (it existed only on pscratch) |
| `tracking/e3sm/as_run/` | **copies** from pscratch. `*_hr10/campaign_<year>/`: `jobs.json`, `submissions.jsonl`, statistics config and job script (one monthly tracking job as example in 2010). `*_hr2p0/campaign_<year>/`: config and job script |

Until 2026-11-25 these files were in `tracking_decadal/`, `tracking/` (Cess2) and `tracking_e3sm/` (the two E3SM scripts). Older documents
(`docs/PLAN_*.md`, `HANDOFF_*.md`) use the old paths.

### Related tracking code that stayed where it was

| location | content |
|---|---|
| `/global/homes/f/feng045/program/PyFLEXTRKR-dev` | tracking package: `runscripts/run_mcs_tbpf_unified.py` (new workflow), `runscripts/run_mcs_tbpf_mcsmip.py` (old), `config/generate_tbpf_mcstracking_scripts.py` (campaign generator), [docs/tbpf_mcs_workflow.md](https://github.com/WACCEM/PyFLEXTRKR-dev/blob/perf-workflow/docs/tbpf_mcs_workflow.md) |
| `/global/homes/f/feng045/program/e3sm_polun/regrid` | E3SM input: remapping of ne120 / ne30 OLR and precipitation to 0.1 degree (`docs/regrid_e3sm.md` of that repository) |
| `/global/homes/f/feng045/program/e3sm_polun/tracking` | **not part of this study** (native 1 degree `E3SM_CTL` and 1 degree IMERG) |
| `tracking/` | cell tracking, CONUS radar MCS tracking and the 1-year SCREAM Cess (DYAMOND-era) configs: other projects |
| `tracking_e3sm/hpss_e3sm_*` | HPSS backup and restore of the E3SM outputs (`docs/hpss_e3sm.md`) |

The SCREAM decadal input files (remapped to 0.1 degree) were made by Hsi-Yen Ma (see the main README).

### Post-processing and analysis

| location | content |
|---|---|
| `scripts/combine_filter_mcs_trackstats.py` | yearly statistics (dense netCDF or row tables) -> one Parquet file per region |
| `tracking/obs_scream_decadal/gen_*_taskfarmer.py` + `scripts/run_mcs_monthly_rainmap_latlon.sh` | monthly MCS rain maps (old workflow; the E3SM runs write them as a tracking step) |
| `scripts/calc_mcs_rainmap_climo_from_monthly.py` | monthly climatology of the rain maps |
| `scripts/gen_mergir_missing_data_taskfarmer.py`, `calc_mergir_missing_data.py` | MergedIR valid-data counts (OBS mask of the maps) |
| `rainrate_hist/` | rain-rate histograms on a 1 degree grid from the pixel files ([README](../rainrate_hist/README.md)) |
| `mcs_environment/` | environment along MCS tracks, and `monthly/` 1 degree monthly environment fields ([README](../mcs_environment/README.md)) |
| `scripts/cess2_cfs_swap_wcmca1.sh`, `scripts/strip_scream_extra_variables.py` | CFS file handling |

### Key notebooks (`Notebooks/`)

| notebook | shows | main input |
|---|---|---|
| `plot_tropical_mcs_trackstats_all_sources.ipynb` | tropical MCS track statistics, box plots, composite life cycles | combined `tropics` Parquet files (section 2) |
| `plot_global_mcs_climo_rainmap_scream_e3sm_obs.ipynb` | MCS cloud frequency, precipitation and precipitation fraction maps | monthly rain-map climatologies |
| `plot_mcs_heavyrain_sensitivity_e3sm.ipynb` | E3SM `heavy_rainrate_thresh` sensitivity | `mcs_tbpf_sens` runs (made by `gen_heavyrain_sensitivity.py`) |
| `plot_tropical_rainrate_pdf_all_sources.ipynb` | rain-rate distributions | output of `rainrate_hist/` (`SCREAM-decadal/mcs_rainhist`) |
| `plot_global_env_climo_scream_e3sm_obs.ipynb` | environment climatology maps | output of `mcs_environment/monthly` (`SCREAM-decadal/monthly_env`) |

The CFS paths that each notebook reads are in its configuration cell.

## 5. Running the tracking again

**SCREAM decadal and OBS** (old workflow): in `tracking/obs_scream_decadal/`. The SCREAM generator and both TaskFarmer generators choose the data set by
commented / uncommented constants at the top of the file (as committed: 13-km TUNE). Outputs go to `jobs/`; with `--submit` the job is submitted from
`jobs/`, so the Slurm logs are in `jobs/logs/`. Check the `root_path` of the template first: it points to the old output location.

```bash
cd mcs_resolution/tracking/obs_scream_decadal
python gen_scream_tracking_scripts.py --start-year 2000 --end-year 2000     # writes jobs/config_*.yml and jobs/slurm_*.sh
```

**3-km TUNE:** the job scripts in `tracking/scream_cess2/` (the two `global` scripts log to `logs/` of the folder they are submitted from;
`slurm_SCREAM-Cess2_stats_rerun.sh` writes to the `mcs_rerun` root).

**E3SM, 10 mm/h** (new workflow). This command is **reconstructed** from the campaign configs and job scripts (ne30, 2010); the exact command line was not saved.
Run it from the pinned worktree so that queued jobs import that code:

```bash
E=/pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg
cd /pscratch/sd/f/feng045/tbpf_code_a4b8ad8
python config/generate_tbpf_mcstracking_scripts.py -s 2010-01 -e 2010-12 \
    -c <config_mcs_tbpf_e3sm_ne30_0p1deg_template.yml> -o $E/mcs_tbpf/campaign_2010 \
    --input-dir $E/olr_pcp --root-path $E/mcs_tbpf/2010 --account m1657 --track-time 01:00:00 \
    --stats-nodes 4 --stats-time 02:00:00 --trackpcp on --profile-dir $E/mcs_tbpf/2010/profile --pin-code   # add --submit to submit
```

A template **without `calendar: noleap`** splits tracks at 1 March of leap years.

**E3SM, 2 mm/h:** Step 2e of the [main README](../README.md) (`tracking/e3sm/gen_heavyrain_sensitivity.py --production`, then `finalize_production_tree.py`).
The default `--code-dir` is `tbpf_code_a4b8ad8`; the production used `--code-dir /pscratch/sd/f/feng045/tbpf_code_38ae5d1`.

## 6. Sahel MCS animations

One 7-day animation per data set on the same map (0-30 N, 20 W - 40 E): Tb, precipitation, MCS outlines (one color per track), tracks and track numbers;
hourly frames at 4 frames per second (42 s). Environment: `/global/common/software/m1867/python/pyflex26.3`; run on a compute node.

| file in `animation/` | content |
|---|---|
| `sahel_sources.yaml` | per data set: config, yearly statistics, pixel folder, Parquet for the period selection, **start day**; shared map box and output folder |
| `select_sahel_periods.py` | ranks 7-day periods by the large, long-lived MCSs over the Sahel |
| `make_mcs_animation_sahel.py` | checks the inputs and makes the frames and the mp4 (plotting by `pyflextrkr.visualization.mcs_animation`) |
| `sahel_common.py` | shared helpers, including the pairing check of pixel files and statistics |

```bash
cd mcs_resolution/animation
python make_mcs_animation_sahel.py --source all --check-only                  # checks only
python make_mcs_animation_sahel.py --source all --workers 64                  # all 7 animations
python make_mcs_animation_sahel.py --source obs --start 2010-08-07            # another week of one data set
python select_sahel_periods.py --sources obs --top 8                          # more candidate periods
```

Tests: `tests/test_mcs_resolution.py`.

**Output:** `/pscratch/sd/f/feng045/SCREAM-decadal/mcs_animations_sahel/mcs_sahel_<key>_<first day>_<last day>.mp4`, frames in `<key>/frames/`,
ranking tables in `period_selection/`. pscratch is purged: copy what you want to keep.

### How the periods were chosen

Same rules for all data sets: MCSs with a lifetime of 12 h or more and a largest cold cloud area (over the whole life) of 100,000 km2 or more;
their hourly time steps with the center in 5-20 N, 18 W - 35 E, May to September; score of a 7-day window = sum of the cold cloud area over those time steps
(area-time integral). The best non-overlapping windows were checked for complete pixel files and missing Tb. The models are free-running, so the dates differ
between data sets and are not comparable day by day.

Rank 1 was taken for six data sets. For 13-km CTL rank 2 was taken: in rank 1 (1999-06-07) only 3 of the 57 MCSs moved clearly westward
(5 degrees or more in the core box), most were nearly stationary clusters. This second step was a judgment from the track maps, not part of the score.

Columns: score in 10^6 km2 h; MCSs = qualifying MCSs in the core box; >=18 h = those with 18 h or more in the box; longest = most hours in the box;
area = largest cold cloud area in 10^5 km2.

| key | period | rank | score | MCSs | >=18 h | longest [h] | area | moved west / east |
|---|---|---|---|---|---|---|---|---|
| `obs` | 2007-08-26 to 09-01 | 1 | 163 | 64 | 27 | 57 | 13.4 | 19 / 0 |
| `scream3_ctl` | 2003-07-22 to 07-28 | 1 | 266 | 48 | 18 | 100 | 14.8 | 16 / 0 |
| `scream3_tune` | 2020-08-15 to 08-21 | 1 | 200 | 39 | 16 | 53 | 12.1 | 13 / 0 |
| `scream13_ctl` | 1999-07-17 to 07-23 | 2 | 219 | 35 | 14 | 102 | 15.4 | 8 / 0 |
| `scream13_tune` | 2001-08-18 to 08-24 | 1 | 278 | 31 | 15 | 63 | 20.3 | 12 / 1 |
| `e3sm25` | 2009-08-30 to 09-05 | 1 | 183 | 64 | 35 | 74 | 9.8 | 25 / 0 |
| `e3sm100` | 2017-06-05 to 06-11 | 1 | 245 | 10 | 6 | 109 | 15.8 | 4 / 0 |

These numbers describe **one week picked from each record for its large MCSs**, and the records have different lengths (1.6 to 12 years), so they must not
be read as a comparison of the data sets.

### Before comparing the movies

**The rain color scale starts at 2 mm/h; weaker rain is not drawn.** This hides much more of the E3SM rain than of the others, so the E3SM movies look far
drier than their rain amounts are. Share of the rain amount that is drawn (every 3rd frame of each animated week):

| key | at 2 mm/h or more, whole map [%] | same, inside MCS outlines [%] | at 1 mm/h or more, whole map [%] |
|---|---|---|---|
| `obs` | 67 | 80 | 83 |
| `scream3_ctl` | 85 | 89 | 91 |
| `scream3_tune` | 87 | 91 | 93 |
| `scream13_ctl` | 85 | 91 | 92 |
| `scream13_tune` | 83 | 90 | 90 |
| `e3sm25` | 17 | 33 | 38 |
| `e3sm100` | 17 | 35 | 44 |

(These are the shares of one week each, not a comparison of the data sets. Script: `period_selection/check_rain_visibility.py` in the output folder.)
The levels are fixed in `pyflextrkr/visualization/mcs_cli.py` (the 1-panel `tbpf` block); there is no option for them.

Also, from the plotting code and style shared by all movies: each MCS outline has its own color (the magenta circle "MCS Mask" in the legend is only a
symbol), thin outlines can be faint on white cloud shields, and the legend covers the lower right corner of the map.

## 7. Data at risk and open items

**On purgeable scratch only, or mainly:**
* the SCREAM decadal and Cess2 pixel files (`/pscratch/sd/w/wcmca1/...`); their backup state was not checked;
* the E3SM pixel files and yearly trees (`/pscratch/sd/f/feng045/E3SM_polun/`); HPSS backup: `docs/hpss_e3sm.md`;
* the pinned code worktrees (`/pscratch/sd/f/feng045/tbpf_code_*`; the commits are in the PyFLEXTRKR-dev repository).

**Open items:**
* 3-km CTL, global Parquet, 2000: 56,957 tracks; the yearly file has 57,891, of which 57,445 pass the global filter. The other 488 are not explained.
  The `tropics` file of the same year, which the notebooks use, matches exactly (38,019), as does the OBS tropics file of 2010 (31,067). Other years were not compared.
* SCREAM decadal leap years (section 3, calendar) are not checked.
* The PyFLEXTRKR commit of the SCREAM decadal and OBS runs is not recorded here.
* `tests/test_rainmap_notebook.py::test_configuration_of_the_zonal_panels` fails because the legend columns of the rain-map notebook (commit f62fa14)
  differ from the values in the test. This is independent of this folder.
