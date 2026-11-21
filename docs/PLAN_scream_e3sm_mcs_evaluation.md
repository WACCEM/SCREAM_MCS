# SCREAM / E3SM MCS evaluation: plan (APPROVED 2026-11-16, in progress)

This file is the durable copy of the plan, written so that a new Claude session can continue without the earlier conversation. The same
plan is summarized in the auto-memory note `project_scream_e3sm_mcs_evaluation`. The plan below is the version the user approved on
2026-11-16 with these comments built in: environment pyflex26.3 everywhere (kernel `pyflex26_3`); every sensitivity run starts at matchpf
(the key is read by matchpf and by robustmcs); test year 2010; ne30 years 2009-2020; pixel files kept.

## Status and how to resume

**Status:** approved; implementation started on 2026-11-16. The progress log at the end of this file says what is done and what is next;
it is updated at every checkpoint.

**To resume after a restart:**

1. Start the Claude session with the working directory `/global/u1/f/feng045/program` (auto-memory is stored per working directory).
2. First message:

```text
Resume the SCREAM/E3SM MCS evaluation. Read
/global/homes/f/feng045/program/scream/docs/PLAN_scream_e3sm_mcs_evaluation.md
and the memory note project_scream_e3sm_mcs_evaluation, then continue from the progress log at the end of the file.
Ask me before submitting Slurm jobs or deleting anything.
```

3. An interactive node held by Claude (job name `scream_e3sm_eval`) ends after 4 h; the progress log names the job id.

## The original request (condensed, so nothing depends on the old chat)

Evaluate MCSs simulated in SCREAM (EAMxx) and E3SM against satellite observations; compare MCS statistics across horizontal grid
spacing (3, 13, 25, 100 km) and examine the sensitivity of MCS precipitation to environmental factors. MCSs are tracked with
PyFLEXTRKR following MCSMIP (Feng et al. 2025, doi 10.1029/2024JD042204). Performance/workflow background:
`/global/u1/f/feng045/program/PyFLEXTRKR-dev/docs/HANDOFF_performance_workflow.md` (local, untracked).

| set | what | location | tracking |
| --- | --- | --- | --- |
| OBS | NCEP Merged IR Tb + GPM IMERGv7, 0.1 deg, 2007-2017 | stats `/global/cfs/cdirs/m1867/zfeng/SCREAM-decadal/mcs_global_v3/MCSMIP`; monthly and climo rain maps `/global/cfs/cdirs/wcm_shr/gsharing/MCS_Global/V3/MCSMIP/stats_mcsmip/monthly` (climo copy in `.../m1867/zfeng/SCREAM-decadal/mcs_global_v3/MCSMIP/monthly`) | before the performance work; combined Parquet exist |
| SCREAM ne1024 | about 3 km, 11 yr (1995-2005) | `/global/cfs/cdirs/m1867/zfeng/SCREAM-decadal/ne1024` | before; combined Parquet exist |
| SCREAM ne256 CTL | about 13 km, 11 yr | `.../SCREAM-decadal/ne256/ctl` | before; Parquet exist |
| SCREAM ne256 TUNE | about 13 km, 11 yr | `.../SCREAM-decadal/ne256/tune` | before; Parquet exist |
| SCREAM Cess2 | about 3 km, same setting as tuned, about 1.5 yr (2019-08..2021-02) | `/global/cfs/cdirs/m1867/zfeng/E3SM/SCREAMv1/cess2/global/mcs` | before; **no combined Parquet found** (see 2) |
| E3SM ne120 | about 25 km, 2009-2011 | `/pscratch/sd/f/feng045/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf` | after; row stats |
| E3SM ne30 | about 100 km, 2009-2020 complete (the user's inventory said 11 yr) | `/pscratch/sd/f/feng045/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf` | after; row stats |

New code goes in `/global/homes/f/feng045/program/scream` (Notebooks, scripts, ...).

**Request 1, MCS maps.** Climatology from monthly files with `scripts/calc_mcs_rainmap_climo_from_monthly.py` (E3SM monthly files
are still in annual sub-folders such as `2010/stats/monthly/`: collect them in a symlink folder first). New notebook with (a) a
function with one colorbar per row (right) or per column (bottom), like `plot_nxm_maps_1colorbar`; (b) a function with two
colorbars, OBS and Model-OBS, like `plot_maps_two_groups_diffs_grid`; (c) the 6 simulations (3-km CTL and TUNE, 13-km CTL and TUNE,
25 km, 100 km) plus OBS, one variable per plot, 2 columns x 4 rows plus a zonal-mean line plot as in
`plot_extreme_rain_threshold_map.ipynb` (does the rectilinear grid need a cos(lat) adjustment?). Variables: MCS cloud frequency, MCS
precipitation, MCS precipitation fraction; colormaps of `plot_cof_annual_map.ipynb`; set the bias levels from the SCREAM runs and
ignore the saturating 100-km for now.

**Then (sensitivity).** Reduce `heavy_rainrate_thresh` for the two E3SM sets: test values 5.0, 3.0, 2.0, 1.5, 1.0; re-run robustmcs
to rainmap for each, 1 year of simulation; rain-map climo per set; key metric MCS precipitation fraction (plus MCS cloud frequency and
MCS precipitation); a dedicated notebook following the new one: OBS + bias for each threshold (2 columns x 3 rows) with the last
panel the zonal-mean lines. The user reviews and picks the threshold to run for all years.

**Request 2, MCS track stats.** References: `scream/Notebooks/plot_tropical_mcs_trackstats_land_ocean.ipynb` and
`PyFLEXTRKR-dev/Notebooks/demo_mcs_track_stats_rows_pandas.ipynb`. Propose a method to unify the track-stats file format: the row
files are Parquet but come as several files per set (tracks, entries, fragments, meta); how can they be read and combined with the
OBS and SCREAM Parquet files? All user-customizable items go in the Configuration section; the reference notebook has labels, paths,
region, years; add the source color there too.

**Added on 2026-11-16 (Step 0).** Help clean up temporary test files from earlier sessions, in parallel with the other work; start
with a quick scan of the top-20 directories by inode (file) count that are not production files and belong to feng045 in
`/pscratch/sd/f/feng045` and `/pscratch/sd/w/wcmca1`; the user reviews the list before anything is deleted.

## What you are approving

1. **Step 0:** a read-only scan of the top-20 inode-heavy, non-production directories in `/pscratch/sd/f/feng045` and
   `/pscratch/sd/w/wcmca1`, then **your review; I delete nothing until you mark directories**.
2. **Part 1A/1B:** symlink folders and climatology files for E3SM ne120 / ne30 and Cess2, and one new maps notebook for 7 sources.
3. **Part 1C:** a generator for the `heavy_rainrate_thresh` sensitivity (ne120 and ne30, year 2010, **each run starting at matchpf**), a
   control run that must match production exactly, then **I stop and ask you before submitting the 10 jobs**, then a sensitivity notebook.
4. **Part 2:** the unified track-stats proposal (tidy Parquet), a rows reader in `combine_filter_mcs_trackstats.py`, the Cess2 and E3SM
   Parquet files, and a config-driven notebook. **Includes two small semantic changes** (see Part 2) for you to approve.
5. **Never without asking:** submit/cancel Slurm jobs (my own interactive node, account m1657, is the exception), delete anything,
   write to CFS, commit.

**Environment for everything (notebooks, scripts, tests, generator, runs): `/global/common/software/m1867/python/pyflex26.3`, notebook kernel
`pyflex26_3`.** I checked: it has the same `colormaps` (0.4.2) as the COF notebook, plus cartopy, pandas 3, pyarrow, nbconvert.

Decided by you: test year **2010**; ne30 years **2009-2020**; pixel files of the test runs **kept**; runs **start at matchpf**.
My defaults, each one Configuration key (veto any): 3-km CTL = ne1024 decadal and 3-km TUNE = Cess2 (inferred: Cess2 is "same setting as
tuned"); outputs and figures on pscratch; colors OBS black, 3-km CTL dodgerblue, 3-km TUNE navy, 13-km CTL tomato, 13-km TUNE forestgreen,
25 km darkorange, 100 km mediumorchid.

## Context

First numbers I measured (60S-60N, cos-weighted over OBS-valid cells, annual mean):

| source | MCS cloud freq % | MCS precip mm/d | total precip mm/d | MCS precip fraction % |
| --- | --- | --- | --- | --- |
| OBS (2007-17) | 3.69 | 1.54 | 3.05 | 50.5 |
| SCREAM ne1024 / ne256 ctl / ne256 tune | 5.10 / 4.79 / 4.83 | 1.58 / 1.68 / 1.72 | 3.18 / 3.30 / 3.28 | 49.6 / 50.8 / 52.5 |
| E3SM ne120 (2009) | 2.49 | 0.58 | 3.15 | **18.5** |
| E3SM ne30 (2009) | 0.45 | 0.10 | 3.17 | **3.3** |

E3SM rarely meets the MCSMIP heavy-rain test (`pf_maxrainrate > heavy_rainrate_thresh = 10 mm/h` for >= 4 h): 79-108 robust MCS per ne30
year, 7,498-7,653 per ne120 year. January 2009 shows no spin-up signal.

Facts the plan relies on:

- Monthly rain maps `mcs_rainmap_YYYYMM.nc` have the same variables everywhere. OBS, E3SM, Cess2: 1200x3600 (lat +-59.95); SCREAM: 1300 rows
  (+-64.95), cut to +-60 and re-labelled to the OBS grid as your existing notebook does.
- Climo files exist for OBS and the three SCREAM decadal sets. Missing: ne120 (36 monthly files), ne30 (144), Cess2 (19 files
  `mcs_rainmap_201908..202102.nc`). `calc_mcs_rainmap_climo_from_monthly.py` works on all of them unchanged.
- **`heavy_rainrate_thresh` is one config key read by two steps** (PyFLEXTRKR-dev, branch perf-workflow): matchpf, whose rows step
  `matchtbpf_rows.py:92` imports the per-file worker `matchtbpf_func.py`, which reads it at `:48`
  (`heavy_rainrate_thresh = config["heavy_rainrate_thresh"]`) and applies it at `:304` (`idx_heavyrain = np.where(sub_rainrate_map >
  heavy_rainrate_thresh)` -> `total_heavyrain`, `total_heavyvolrain`, `rainrate_heavyrain`) and `:751` (PF heavy-rain accumulation,
  `pf_accumrainheavy`), and `matchtbpf_rows.py:206` writes it to the file attributes; robustmcs, `robustmcs_rows.py:131`
  (`pf_maxrainrate[group] > params["heavy_rainrate_thresh"]`, the MCSMIP test). So the key takes full effect only if matchpf is
  re-run: that is why every sensitivity run starts at matchpf. The robust MCS set itself depends on the key only through `:131`.
- matchpf needs only the cloudid files (it reads `precipitation` from them, `matchtbpf_func.py:91-97`), the landmask file (absolute path in
  the config) and the identifymcs output `mcs_tracks_<dates>.rows`. Rain maps come from the `mcstrack_*` pixel files (mapfeature, from
  the robust stats): matchpf -> robustmcs -> mapfeature -> speed -> dense_netcdf -> rainmap.
- Row tables (`tracks`, `entries`, `fragments`, `meta.json`) hold everything of the 69-column OBS/SCREAM Parquet (identical schema in both).
- **Cess2 has no combined Parquet** (only one multi-year final netCDF, 79,370 tracks, 2019-08-03..2021-03-06); its name has no
  `_YYYY0101.`, so the current `_extract_year` would skip it.
- pscratch: 77.7 of 107 TB, **9.25M of 10M files**.

## Step 0 (parallel with everything else): clean up old temporary test files, you review first

Why: files at 9.25M of 10M, and the kept sensitivity runs add about 1.1 TB and 97k files. Scope: `/pscratch/sd/f/feng045` and
`/pscratch/sd/w/wcmca1` (there: only files owned by feng045; the top level has `hackathon` and `Sahel_MCS` owned by you).

1. **Scan only, read-only**, on my interactive node in the background, one traversal per top-level folder, never on the login node:
   files per directory rolled up to a depth where the top 20 are meaningful, then size and newest file date for those 20. The script
   stays in the session scratchpad. If the filesystem-traversal hook blocks a root, I stop and tell you.
2. **Two top-20 tables**, one per tree: rank, path, files, size, newest file, hint `KEEP?` (E3SM `mcs_tbpf/<year>`, `campaign_*`, `olr_pcp`,
   `GPM_IMERG` production year, `SCREAM-decadal`, `MRMS`, pinned worktrees `tbpf_code_*` (the sensitivity runs use `tbpf_code_a4b8ad8`),
   `tbpf_perf_results`) or `REVIEW`. Candidates from my notes: `tbpf_unified_test` (about 10 GB), `tbpf_demo_root`, the E3SM regrid `_test`
   output (about 150 GB), `post_tail4_*`, `view_track_only`, dry-run campaigns, `test`, `tmp`, `r7_..r15_*`, `lifecycle_animation*`,
   `mcs_tuning_runs`, `mcs_climatology_runs`, `DYAMOND*_SCREAMv1`, zarr test stores such as
   `/pscratch/sd/w/wcmca1/hackathon/mcs_masks/_test_scream_parallel.zarr`.
3. **You mark what to delete.** Then per directory `/bin/rm -r` on verified absolute paths, in the background with a log, with
   `lfs quota -u feng045 /pscratch` before and after.

## Part 1A: climatology files for E3SM and Cess2 (no code change)

1. Symlink folders as in README Step 2b, with a year-only glob (it excludes `campaign_*` and `post_tail4_2009`):
   `<root>/<ne120|ne30>_remap_0.1deg/mcs_tbpf/monthly/` <- `../20[0-9][0-9]/stats/monthly/mcs_rainmap_*.nc` (check 36 and 144 links).
2. `scripts/calc_mcs_rainmap_climo_from_monthly.py` (pyflex26.3, on the interactive node): ne120 `2009-01..2011-12`, ne30 `2009-01..2020-12`,
   Cess2 `2019-08..2021-02` (reads the CFS folder, writes to `/pscratch/sd/f/feng045/SCREAM-decadal/cess2/monthly/`). Cess2's Mar-Jul have
   one year only; the annual mean is the mean of the 12 monthly means (flagged in the notebook).

## Part 1B: `Notebooks/plot_global_mcs_climo_rainmap_scream_e3sm_obs.ipynb` (kernel pyflex26_3)

**One Configuration section holds everything editable:** `SOURCES` (label, climo file, years text, color, linewidth), OBS valid-fraction file
(`.../SCREAM-decadal/maps/merg_valid_fraction_1998_2024.nc`, threshold 0.75), topography file and terrain contour levels (None = off),
`figdir` (pscratch), `SEASONS` (default `['ANN']`), projection (Robinson, central longitude 225) and lat range, a variable table (name,
units, OBS levels, bias levels, colormap, over/under colors), `ncol=2`, zonal bin width (2 deg), `mask_to_obs_valid`, fonts, dpi.

**Functions** (docstrings with inputs/outputs/defaults, a comment on every block, per your CLAUDE.md):

- loader: open a climo file, cut to +-60, relabel to the OBS grid **with an explicit coordinate-difference check**, annual/seasonal mean,
  fraction = 100 x MCS precip / total precip from the means (as in your notebook).
- `plot_maps_cbar_per_row_or_col` (from `plot_nxm_maps_1colorbar`): one colorbar per row (right) or per column (bottom).
- `plot_obs_and_bias_maps` (lat-lon version of `plot_maps_two_groups_diffs_grid`, one variable per figure): `[OBS colorbar | maps |
  Model-OBS colorbar]`, 2 columns x 4 rows = OBS + 6 biases + the zonal-mean panel in the empty 8th slot, as in
  `plot_extreme_rain_threshold_map.ipynb`; `pcolormesh` instead of `egh.healpix_show`.
- **Zonal mean (your cos(lat) question):** along one latitude row all cells have the same area, so a plain mean is already correct;
  **cos(lat) weights are needed as soon as rows are combined** (2-degree bins, tropical or global means), so bins are cos(lat)-weighted
  over valid cells. The fraction line is the **ratio of the zonal means** (MCS / total), not the mean of the ratios.
- OBS missing-Tb mask: gray on the OBS panel (as now) and applied to every bias and zonal calculation, so models are compared on the same cells.

**Colormaps and levels** (colormaps from `plot_cof_annual_map.ipynb`, levels checked against the data): cloud frequency `cet_l_wcmr`
(OBS median 2.7, p99 13.6, max 21 %: levels [0.5,1,2,3,4,6,8,10,13,16,20]); MCS precipitation `WhBlGrYeRe` [0.1,0.2,0.5,1,1.5,2,3,4,6,8,10];
fraction `WhiteBlueGreenYellowRed` truncated to 0-0.8, levels 0..80 step 10, over `firebrick`; biases `BrBG`. Bias levels come from the
**SCREAM** biases (1st-99th percentile of Model-OBS: cloud freq -7..+12 %, MCS precip -4..+6 mm/d, fraction -45..+33 pts), e.g.
[-10,-8,-6,-4,-2,-1,1,2,4,6,8,10], [-4,-3,-2,-1.5,-1,-0.5,0.5,1,1.5,2,3,4], [-50,-40,-30,-20,-10,-5,5,10,20,30,40,50]; E3SM 100 km will
saturate (accepted). A helper cell prints the SCREAM bias percentiles so levels are easy to retune.

**Figures:** per variable (MCS cloud frequency, MCS precipitation, MCS precipitation fraction): OBS + biases + zonal mean; plus one
overview (3 variables x 7 sources) drawn with `plot_maps_cbar_per_row_or_col` in both modes (colorbar right per row, bottom per column).

## Part 1C: heavy_rainrate_thresh sensitivity (E3SM ne120 and ne30, year 2010, each run from matchpf to rainmap)

**Generator `tracking_e3sm/gen_heavyrain_sensitivity.py`** (modeled on `PyFLEXTRKR-dev/config/generate_tbpf_mcstracking_scripts.py`; writes
only into pscratch, never into production folders). Per (model, threshold) a run tree
`<model>_remap_0.1deg/mcs_tbpf_sens/heavyrain_<tag>/2010/` (`tag` = `5p0`, `3p0`, ...) with:

- `tracking` -> symlink to the production `2010/tracking` (cloudid files, read-only), and `stats/mcs_tracks_<dates>.rows` -> symlink to the
  production identifymcs output (the only stats input matchpf needs); `grid_area_file` in the config points at the production
  `grid_area_from_latlon.nc`. Everything from matchpf on is written fresh into the run tree.
- a config copied from `campaign_2010/*_stats201001_201012.yml` (same keys and values) with only these lines changed:
  `heavy_rainrate_thresh`, `root_path`, `step_profile_dir`, `run_parallel: 1`, `nprocesses: 128`, `skip_completed_steps: False`,
  `run_idfeature/tracksingle/gettracks/trackstats/identifymcs/trackpcp: False`,
  `run_matchpf/robustmcs/mapfeature/speed/dense_netcdf/rainmap: True` (text substitution, so comments are kept).
- a one-node Slurm script (m1657, regular, `-C cpu`, 3 h) using the pinned worktree `/pscratch/sd/f/feng045/tbpf_code_a4b8ad8` (the code that
  made the production 2010 outputs) and pyflex26.3; after a clean run it calls the climo script on the run's 12 monthly maps
  (`stats/monthly/mcs_rainmap_monthly_climo_201001_201012.nc`). Estimate from the E3SM 2009 step times: ne120 about 70-80 min
  (matchpf about 40, mapfeature about 20, the rest about 15), ne30 less.
- It prints the planned jobs and the pscratch quota; nothing is submitted without `--submit`.

**Control run first:** ne120 at **10.0 mm/h** (the production value), also from matchpf, on my interactive node. Compared with production by
`PyFLEXTRKR-dev/tests/tbpf_compare.py` (`mcs_tracks_pf`, robust and final row tables and all 8,760 pixel files; `tracking` is shared through
the symlink, so it is skipped) **plus `netcdf_differences` from the same module on the 12 `stats/monthly` rain maps and the dense
`mcs_tracks_final_*.nc`**, because tbpf_compare does not cover those two. It must show 0 differences; this validates the symlink and
config machinery and matchpf. Its pixel files duplicate production once verified (+106 GB, 8,760 files): I keep them and ask before deleting.

**Then the tests (10 jobs):** thresholds 5.0, 3.0, 2.0, 1.5, 1.0 x ne120, ne30: about 10 node-hours (estimate 8-12), about 1 TB of pixel
files (kept). **I stop and ask you before submitting.** The baseline (10.0) uses the production 2010 maps and final stats; its 1-year climo
is made with the same script. Because every run is complete from matchpf on, the run for the threshold you choose is already the 2010
production result with that key; the other years need a normal stats job from matchpf.

**Notebook `Notebooks/plot_mcs_heavyrain_sensitivity_e3sm.ipynb`** (built from the Part 1B cells, same Configuration style): per model and
variable, OBS + Model-OBS bias for each of the 5 thresholds (2 columns x 3 rows) with the zonal-mean panel appended as the last panel
(baseline 10 mm/h and OBS are lines in it; `show_baseline_map=True` adds the baseline bias map: 7 maps, zonal panel in the 8th slot). Key
variable **MCS precipitation fraction**; cloud frequency and MCS precipitation as complementary figures. A printed and CSV summary table per
model and threshold: robust MCS count, total heavy rain, 60S-60N cos-weighted mean fraction / MCS rain / cloud freq, and map RMSE vs OBS,
to help you pick the production threshold.

## Part 2: unified MCS track statistics

**Proposal: the common analysis format is the tidy track-time Parquet that OBS and SCREAM already use** (one row per track x time, the
69-column schema, `mcs_tracks_final_combined_{region}_{y0}_{y1}.parquet`). Row-table folders are not merged with those files; each E3SM year
is converted once by a reader that produces exactly the same table, and the notebook concatenates all sources in memory with a `source`
label (as today). Mapping:

| rows file | tidy columns |
| --- | --- |
| `tracks.parquet` (11 columns) | per-track columns repeated on every row (`track_duration`, `start_/end_status`, `start_/end_basetime`, `start_split_`/`end_merge_cloudnumber`, `pbc_flag`, `mcs_duration`, `pf_lifetime`) |
| `entries.parquet` (94 columns) | per-time columns; `k` -> `relative_step`; `pf_*__0` -> `pf_*` (largest PF) |
| `fragments.parquet` | `merge_ccs_area` / `split_ccs_area` = sum of `ccs_area` by `kind` (0 merge, 1 split), NaN -> 0 |
| `meta.json` | fill values (-9999 -> NaN), `time_resolution_hour`, format version check |

**Implementation:** extend `scripts/combine_filter_mcs_trackstats.py`, run in pyflex26.3. The reader uses the supported API
`pyflextrkr.rowstats.RowStats` (`open`, `to_pandas('tracks'|'entries'|'fragments')`, `meta`) instead of re-parsing the layout; the script
docstring states the dependency (PyFLEXTRKR with `rowstats.py`, branch perf-workflow, editable install). Dispatch on `.nc` vs `.rows`; same
region filter, same unique `local_track`, same column order and dtypes (floats float64, times ms UTC); a fixed `UNIFIED_COLUMNS` list is
checked on every output. E3SM years are collected by symlinks like the monthly files
(`<root>/stats/` <- `../20[0-9][0-9]/stats/mcs_tracks_final_*.rows`). Outputs, **tropics and global versions as for the other sources**:
ne120 2009-11 and ne30 2009-20 in `<root>/mcs_tbpf/stats/`, Cess2 2019-21 (new) in `/pscratch/sd/f/feng045/SCREAM-decadal/cess2/stats/`.

**Two small semantic changes for you to approve:** (1) `period` becomes the calendar year of the track start; for yearly files this equals the
file year, and it is meaningful for the single multi-year Cess2 file. I verify on your real OBS/SCREAM Parquet files that the new rule
reproduces their existing `period` for every track before relying on it. (2) The output file name takes its years from `period` (the
`_YYYY0101.` regex goes away); names of the existing yearly sets stay the same.

**Notebook `Notebooks/plot_tropical_mcs_trackstats_all_sources.ipynb`** (kernel pyflex26_3): the reference notebook's load and summary steps
with one Configuration section holding, per source, label, path, region, start/end year **and color** (plus `SOURCE_ORDER`, land/ocean
thresholds, variable lists, styles); `SOURCE_COLORS` and the overlay styles derive from it. The analysis cells are not ported until you
review the format.

**Test `scripts/tests/test_combine_filter_mcs_trackstats_rows.py`** (unittest in pyflex26.3, like your existing one): small synthetic dense
file -> `dense_to_rows` / `write_rows` -> both routes -> `assert_frame_equal`; fill handling; region filter.

## Order of work and checkpoints

Right after approval: sync the docs file and the memory note with these changes (done 2026-11-16, see the progress log).

0. Interactive node (m1657, mine). **Step 0 scan starts first, in the background. Checkpoint: you review the top-20 lists before any deletion.**
1. Part 1A -> Part 1B notebook, run with `jupyter nbconvert --execute` (kernel pyflex26_3); I inspect every PNG and iterate. **Checkpoint: you
   review the maps.**
2. Part 1C: generator, control run + exact comparison, then **ask before submitting the 10 jobs**.
3. While those queue and run: Part 2 (converter, test, Parquet files, notebook, README section).
4. After the jobs: climo check, sensitivity notebook, summary table. **Checkpoint: you pick the threshold.**
5. README updated (E3SM/Cess2 steps, sensitivity driver, unified format, new notebooks); the interactive node released with `scancel`.

## Verification

- Climo: new E3SM climo against an independent monthly-file calculation (ne120 2009 fraction 18.5 %); the notebook runs top to bottom;
  every figure inspected (labels, colorbars inside the figure, zonal panel, mask).
- Control run: 0 differences against production (pf, robust and final row tables, pixel files, rain maps, dense file).
- Sensitivity runs: in each run's `mcs_tracks_pf` the attribute `heavy_rainrate_thresh` equals the key; robust MCS count and total heavy
  rain rise monotonically as the threshold falls; 12 monthly maps + final stats + climo per run.
- Converter: rows route == dense route on ne120 2010 (`assert_frame_equal`); its schema == the OBS/SCREAM Parquet schema; the new `period`
  rule == the existing `period` of every track in the OBS/SCREAM Parquet; the unit test passes.

## Risks and what I will state in the results

- Once heavy rain is relaxed, `mcs_min_rainvol_thresh` (20000 km2 mm/h) may become the binding criterion at ne30. Not part of this test.
- Climatologies cover different periods (OBS 2007-17, SCREAM 1995-2005, E3SM 2009-20, Cess2 19 months); 1-year ne30 tests are noisy.
- Pixel files kept: about 1.1 TB and 97k files with the control (pscratch at about 9.35M of 10M files) unless Step 0 frees space.
- The Cess2 Parquet was not where you expected; this plan generates it.
- The pyflex26.3 environment is an editable install of the live PyFLEXTRKR-dev: the Part 2 reader needs that repo on a branch that has
  `rowstats.py` (perf-workflow today).

## Files

New: `Notebooks/plot_global_mcs_climo_rainmap_scream_e3sm_obs.ipynb`, `Notebooks/plot_mcs_heavyrain_sensitivity_e3sm.ipynb`,
`Notebooks/plot_tropical_mcs_trackstats_all_sources.ipynb`, `tracking_e3sm/gen_heavyrain_sensitivity.py`,
`scripts/tests/test_combine_filter_mcs_trackstats_rows.py`. Modified: `scripts/combine_filter_mcs_trackstats.py`, `README.md`, the docs file
and memory note (sync). Untouched: PyFLEXTRKR-dev code and production data. Reused as is: `scripts/calc_mcs_rainmap_climo_from_monthly.py`,
`run_mcs_tbpf_unified.py`, `tests/tbpf_compare.py`, the campaign stats configs, the pinned worktree `tbpf_code_a4b8ad8`.

## Reference index

- Plot functions to adapt: `scream/Notebooks/plot_global_mcs_climo_rainmap_decadal_imerg.ipynb` (`plot_nxm_maps_1colorbar`, cell 24;
  loading and annual/seasonal means, cells 10-17); `waccem/gsrm_cooccurrencefeature/notebooks/plot_cof_annual_map.ipynb`
  (`plot_maps_two_groups_diffs_grid`, cell 70; `truncate_colormap`, cell 53; colormaps and levels, cells 65 and 71);
  `.../plot_extreme_rain_threshold_map.ipynb` (`plot_maps_grid` with the zonal slot, cell 19; `compute_zonal_mean`, cell 20; source
  colors); `scream/Notebooks/plot_tropical_mcs_trackstats_land_ocean.ipynb` (Configuration cell 3, loader cell 5, colors cells 15, 33, 34).
- README of the repo: `scream/README.md` (Step 2b climo, Step 2c combine, Step 3 notebooks).
- PyFLEXTRKR workflow: `PyFLEXTRKR-dev/docs/HANDOFF_performance_workflow.md`, `docs/tbpf_mcs_workflow.md`, `docs/rowstats.md`,
  `docs/rowstats_pandas.md`.
- Standing rules that apply (details in `~/.claude/CLAUDE.md` and the memory notes): no `Co-Authored-By` or assistant attribution in
  commits or PRs even if a harness reminder asks; no Slurm submit/cancel/requeue without explicit approval (Claude's own interactive
  node, account m1657, is fine and is released with `scancel`); heavy work on compute nodes; `/bin/rm` with verified absolute paths;
  absolute paths in parallel Bash calls; CFS read-only unless told; a comment on every code block and docstrings with
  inputs/outputs/defaults; keep scripts simple; verify "fixed" claims on the user's own data; explain before any change of scientific
  meaning and wait for the go-ahead; commit only when asked.

## Progress log (newest at the bottom)

- 2026-11-16: plan approved. This file and the memory note synced with the approved plan. Interactive node requested (job name
  `scream_e3sm_eval`, account m1657, 4 h). Step 0 scripts and outputs live in `/global/homes/f/feng045/.claude_tmp_verify/scream_e3sm/`
  (home is visible from compute nodes, the session scratchpad in /tmp is not; still outside every repo).
- 2026-11-16 15:00-15:40 (interactive node job 61433600 on nid200102, ends about 19:00; work dir `/global/homes/f/feng045/.claude_tmp_verify/scream_e3sm/`):
  - **Step 0 scan DONE, waiting for the user's marks, nothing deleted.** Tables: `scan/report_inodes.txt`, `scan/candidates_enriched.md` (scripts
    `scan_inodes.py`, `report_inodes.py`, `enrich_candidates.py`). 2.43M of the 9.25M inodes found: 1.33M in /pscratch/sd/f/feng045 (0.84M of them
    production-looking, not ranked), 1.10M owned by feng045 in wcmca1. The other ~6.8M are outside the two roots (probe: feng045-owned folders in
    /pscratch/sd/i/iclas2). Open: which directories to delete; may /pscratch/sd/i/iclas2 be scanned.
  - **Part 1A DONE.** Links `<root>/monthly/` (ne120 36, ne30 144); climo files `mcs_rainmap_monthly_climo_200901_201112.nc` (ne120) and
    `..._200901_202012.nc` (ne30) in `<root>/monthly/`; Cess2 `..._201908_202102.nc` in `/pscratch/sd/f/feng045/SCREAM-decadal/cess2/monthly/`.
    Checked against the direct monthly calculation (MCS fraction ne120 18.331 vs 18.319 %, ne30 3.687 vs 3.687, Cess2 49.672 vs 49.592).
  - **Part 1B built.** The three notebooks are made by `build_notebooks.py` from the percent-format sources `nb_maps_part1.py`, `nb_maps_part2.py`,
    `nb_sens_body.py`, `nb_trackstats.py` (edit those, rebuild into the Notebooks folder, execute with nbconvert, kernel pyflex26_3). Test runs looked right
    (2 x 4 layout, two colorbars, zonal panel, both overview layouts). E3SM colors changed to darkviolet (25 km) and saddlebrown (100 km): darkorange
    looked like the tomato of SCREAM 13 km CTL.
  - **Part 1C:** generator `tracking_e3sm/gen_heavyrain_sensitivity.py` written and dry-run checked (the config differs from production only in the planned
    lines). Control run ne120 10.0 mm/h (from matchpf) started 15:21 on the node, log `<mcs_tbpf_sens>/heavyrain_10p0/logs/control_run.log`; `after_control.sh`
    makes its climatology and runs `compare_control.py` (tbpf_compare + netcdf_differences) when it ends, results in `compare_control.log`. Baseline
    climatologies (production 2010) are in `<root>_sens/baseline_2010/monthly/`. **The 10 jobs are NOT submitted: ask the user first.**
  - **Part 2:** `scripts/combine_filter_mcs_trackstats.py` has the rows route; unit test `scripts/tests/test_combine_filter_mcs_trackstats_rows.py` (8 tests, ok).
    Real data (`verify_combine.py`): rows == dense for ne120 2010 and ne30 2012 (tropics and global), the schema equals the OBS and SCREAM Parquet files, the
    new `period` rule has 0 mismatching rows in the 4 existing files (about 29M rows). E3SM and Cess2 Parquet files made by `run_combine.sh`.
  - README updated (Steps 2b, 2c, 2e, 3).

- 2026-11-16 15:40-17:15 (same node, job 61433600):
  - **Step 0, third tree scanned at the user's request** (`/pscratch/sd/i/iclas2`, feng045-owned files only, 6.84M inodes; the three trees together
    account for the quota: 1.33M + 1.10M + 6.84M of the 9.25M). Tables: `scan/report_inodes_i_iclas2.txt`, `scan/candidates_enriched_pieces_i_iclas2.md`
    (tables were posted to the user). **Still nothing deleted; waiting for the user's marks for all three tables.**
  - **Cess2 combine needed one rule:** the Cess2 final file has no `total_volrain` and `total_heavyvolrain`. `conform_columns` now fills a missing column
    with NaN (float64) and prints `WARNING ... filled with NaN: [...]`; an extra column is still an error. (My decision, in the spirit of "NaN + log, not
    crash"; reversible. Hazard for the analysis: a pandas `sum` of an all-NaN column is 0, so the notebook has a cell that lists all-NaN columns per source.)
    The conversion read the 79,370-track file from CFS very slowly (small chunks, > 40 min), so a copy `cess2/stats/input_copy/` (808 MB, deletable)
    on pscratch was used; both regions then took about 3 min.
  - **Parquet files made** (tropics and global): ne120 `<root>/mcs_tbpf/stats/mcs_tracks_final_combined_{tropics,global}_2009_2011.parquet`, ne30
    `..._2009_2020.parquet`, Cess2 `/pscratch/sd/f/feng045/SCREAM-decadal/cess2/stats/..._2019_2021.parquet`.
  - **Notebooks:** `plot_global_mcs_climo_rainmap_scream_e3sm_obs.ipynb` executed, 0 errors, 5 figures in `/pscratch/sd/f/feng045/SCREAM-decadal/figures_e3sm/`
    (3 variables x OBS + biases + zonal mean, 2 overview figures); `plot_tropical_mcs_trackstats_all_sources.ipynb` executed on all 7 sources, 0 errors;
    `plot_mcs_heavyrain_sensitivity_e3sm.ipynb` NOT executed on purpose (no results yet; tested on the baseline and on a stand-in run).
  - **Control run ne120 10.0 mm/h finished** (all steps, 12 monthly maps, final stats, climatology). `compare_control.py` (serial tbpf_compare) was too
    slow (one pixel-file pair takes 4-10 s, 8,761 pairs) and was stopped; `compare_control_parallel.py` does the same checks with the pixel files spread
    over 48 processes. Row tables (identifymcs, matchpf, robustmcs, final): identical. Pixel files / rain maps / dense file / climatology: see the next entry.
- 2026-11-16 17:15 **NEXT STEPS (resume here).**
  1. **Needs the user's explicit approval: submit the 10 sensitivity jobs** (account m1657, regular QOS, 1 node each, 3 h limit). The control run took
     74 min (matchpf 36, mapfeature 25, speed 6, rainmap 5, rest about 2), so the estimate is 5 x about 75 min (ne120) + 5 x less (ne30) = about 10
     node-hours; about 8,800 files and 100 GB per run (about 88k files and 1 TB in total: pscratch from 9.26M to about 9.35M of the 10M files, 77.8 to
     about 79 TB of 100 TB). Command, from `/global/u1/f/feng045/program/scream` (login node is fine, it only writes text files and calls sbatch):
     `python tracking_e3sm/gen_heavyrain_sensitivity.py --models ne120 ne30 --thresholds 5.0 3.0 2.0 1.5 1.0 --submit` (with the pyflex26.3 python).
     Run trees: `<root>_sens/heavyrain_<tag>/2010/`, job logs in `<root>_sens/heavyrain_<tag>/logs/`.
  2. After the jobs end: check each with `sacct` AND with the outputs (a Slurm COMPLETED state is not proof): 12 monthly rain maps, final `.rows`, the
     `..._climo_201001_201012.nc`, the `heavy_rainrate_thresh` attribute of `mcs_tracks_pf` equal to the key, robust MCS count and total heavy rain
     rising monotonically as the threshold falls. A failed job can be resubmitted as it is (`skip_completed_steps` is False, it redoes everything).
  3. Execute `Notebooks/plot_mcs_heavyrain_sensitivity_e3sm.ipynb` on a compute node (nbconvert, kernel pyflex26_3; the maps notebook took about 20 min),
     read the summary table (CSV and printed), inspect the figures, give the table to the user. **The user picks the production threshold.**
  4. Step 0: the user marks directories in the three tables; then `/bin/rm -r` on verified absolute paths in the background with a log and
     `lfs quota -u feng045 /pscratch` before and after.
  5. Release the interactive node (`scancel 61433600`; ends about 19:00 anyway). Nothing is committed: the user decides when (no attribution lines).
- 2026-11-16 17:25 **Control run ne120 10.0 mm/h == production: VERIFIED, 0 data differences.** `compare_control_parallel.py` (log
  `.claude_tmp_verify/scream_e3sm/compare_control_parallel.log`): row tables of identifymcs, matchpf (`mcs_tracks_pf`), robustmcs and final identical;
  8,761 / 8,761 pixel files identical (752 s on 48 processes); dense final `.nc` identical; 12 monthly rain maps and the 1-year climatology (control vs
  baseline from the production maps) identical **except the global attribute `created_on`** (a creation timestamp, production 2026-11-15 19:34 vs control
  2026-11-16 16:29; with it ignored 13 / 13 are identical). `tests/tbpf_compare.py` ignores only `Created_on` / `Created` (capital C), so a plain
  `netcdf_differences` on rain maps reports `created_on`; add `created_on` to `IGNORED_GLOBAL_ATTRS` there if wanted (PyFLEXTRKR-dev left untouched).
  Only "only in production": `tracknumbers_` and `trackstats_sparse_` (they come before matchpf), as expected. The control run: matchpf 36 min,
  robustmcs 0.1, mapfeature 25, speed 6, dense 0.5, rainmap 4.7, total 74 min. This validates the symlink and config machinery of the generator.
- 2026-11-16 17:26 interactive node job 61433600 released with `scancel` (nothing running on it). For notebook runs or the deletion step request a new one
  (`salloc --no-shell -A m1657 -C cpu -q interactive -N 1 -t 04:00:00`, job name `scream_e3sm_eval`); item 5 of the NEXT STEPS above is done.
  pscratch at release: 77.8 TB of 100 TB, 9,258,573 of 10,000,000 files. **Open for the user: (1) approval to submit the 10 jobs, (2) deletion marks.**

---

# ROUND 2 (APPROVED 2026-11-16 evening): deletions, Cess2 re-run, notebook revision, space check

The user's round-2 inputs and the approved plan (verbatim copy of the plan file, headings shifted one level). Progress entries for round 2 are appended at the very end of this file.

## SCREAM / E3SM MCS evaluation, round 2: deletions, Cess2 re-run, notebook revision, space check

### Context

Round 1 (maps notebook, track-stats notebook, Parquet files, heavy_rainrate_thresh generator, control run == production) is done and
documented in `/global/homes/f/feng045/program/scream/docs/PLAN_scream_e3sm_mcs_evaluation.md` (progress log + NEXT STEPS) and the memory
note `project_scream_e3sm_mcs_evaluation`. Your new inputs: (1) a list of directories to delete, with the HPSS-archive condition for the MRMS
netCDF files; (2) re-run the Cess2 (SCREAM 3 km TUNE) stats steps with row stats so `total_volrain` / `total_heavyvolrain` exist; (3) revise
the maps notebook; (4) after the deletions, check that pscratch has room for the 10 heavy_rainrate sensitivity jobs. This plan replaces the
round-1 plan file; **my first action after approval is to append this plan and a progress entry to the docs file and the memory note.**

Environment everywhere: `/global/common/software/m1867/python/pyflex26.3` (notebook kernel `pyflex26_3`). Heavy work on compute nodes (own
interactive allocations, account m1657, the exception my notes allow); nothing submitted to the batch queue; nothing committed or pushed.

### Facts measured while planning (all read-only)

- pscratch now: 9,258,573 of 10,000,000 files (hard limit 10.5M), 77.8 of 100 TB. Scan of 2026-11-16: 1.33M inodes in `/pscratch/sd/f/feng045`,
  1.10M in `wcmca1`, 6.84M in `iclas2` (feng045-owned only, which is what the quota counts).
- Inodes of your delete list (from the scan): feng045 **451,548**; wcmca1 **649,909**; iclas2 **3,797,682**, of which the MRMS netCDF products to
  remove are 3,230,821 (EchoTop_18 635,685; EchoTop_30 635,676; ReflectivityAtLowestAltitude 635,383; PrecipRate 635,263; NLDN 633,881;
  Model_0degC_Height 54,933) and the other iclas2 folders 566,861. **Total about 4.9M inodes -> pscratch would drop from 9.26M to about 4.4M files.**
  Together with the 10 sensitivity jobs (+88k files, +1 TB) that is about 4.5M of 10M: enough, to be confirmed with `lfs quota` and a re-scan.
- **HPSS archives of `MRMS/mrms_5min/netcdf`** (`.../logs/hpss/`): 4 CSV reports, **all archives "verified"** (htar write + `-K -Hverify=crc` + index
  check), 136 `*.verify.log` all end with `HTAR SUCCESSFUL`, none contains an error. Coverage 2020-10-14 .. 2026-10-23: L33 monthly, the other
  products yearly (2020 partial, 2021-2024, 2025, 2026-01-01..10-23). File counts per product and year equal the scratch counts (e.g. EchoTop_18:
  22,490 / 104,806 / 105,064 / 105,088 / 105,398 / 105,120 archived = scratch) **except the last days**: scratch has 2026 files that no archive
  has (EchoTop_18: 85,517 on scratch vs 85,229 archived = 288 files = 20261024; Model_0degC_Height 7,125 vs 7,101). Scratch holds 9 products
  (`netcdf/CONUS/<product>/<yyyymmdd>/`), all 9 are in the archives.
- **Model_0degC_Height_00.50 is not in your keep list** (it is archived), so it goes with the others; I flag it in the report.
- `hackathon/etc_data` is, per my notes, the **production** ETC data of the COF/ETC work (round 2 promoted on pscratch and CFS on 2026-09-29;
  `etc_data_prev_production_20260929` and `etc_data_coldcore` are different folders and stay). `hackathon/mcs` is owned by `wcmca1` (a shared
  account), `scream-cess-healpix` shows 182,854 directories owned by feng045 and no files owned by feng045.
- Cess2 (SCREAM 3 km TUNE) tracking tree `/pscratch/sd/w/wcmca1/SCREAMv1-cess2/mcs/` (retrieved from HPSS 2026-11-12/13): `tracking/` 13,921
  cloudid + 13,919 track files, `mcstracking/20190803.0000_20210306.0000/` 13,921 pixel files, `stats/` dense files of Jan 2026 (old code:
  `trackstats_sparse_*.nc` 0.55 GB, `tracknumbers_*.nc`, `mcs_tracks_*`, `_pf_`, `_robust_`, `_final_`). Config
  `scream/tracking/config_mcs_tbpf_SCREAMv1-Cess2.yml`: pixel_radius 10 km fixed area (no `area_method`), `mcsmip` thresholds, heavy 10 mm/h, no
  `stats_format` / `robustmcs_definition` keys. 2019-08-03 .. 2021-03-06 hourly = 1.6 times the files of an E3SM year.
- Row steps (pinned code `tbpf_code_a4b8ad8`): identifymcs rows reads **`trackstats_sparse_<dates>.nc`**; matchpf reads the cloudid files + landmask +
  the identifymcs rows; robustmcs reads matchpf; **speed reads the pixel files `mcstrack_*` in `pixeltracking_outpath`** (so skipping mapfeature
  means speed uses the old pixel files). Timing reference (performance_tbpf.md, E3SM year, 4 nodes): identifymcs 1.8 min, matchpf the long step
  (36 min on 1 node), robustmcs 0.1, speed 6 min on 1 node: 1.6 times the data on 4 nodes gives about 20-35 min.
- The OBS per-year monthly rain maps 2007-2017 are **not on disk any more** under `mcs_global_v3` (only the climo file, which has `*_std`), but they
  are inside the Zenodo archives `/pscratch/sd/w/wcmca1/GPM/MCS_Global/V3/Zenodo/global_mcs_pyflextrkr_monthly_rainmap_v3_mcsmip_{2005-2011,
  2012-2018}.tar.gz` (the climo file is `.../MCSMIP/monthly/mcs_rainmap_monthly_climo_200701_201712.nc`).

### 1. Deletions (you approved the list; I verify first, delete only what passes)

**Approved paths** (exact; siblings with similar names such as `hackathon/etc_data_*`, `hackathon/mcs_masks*`, `MRMS/mrms_5min/regrid/hrrr_combined`
stay):

| tree | delete | check before deleting |
| --- | --- | --- |
| `/pscratch/sd/f/feng045` | `mcs_animation`, `waccem/mcs_global/mcstracking`, `usa/gridrad_v3/v3_final/mcstracking_extc`, `E3SM_polun/_test`, `mcs_radar3d_validation/may_combine_false`, `SAAG/hist/auxhist/refl/cacti`, `tbpf_unified_test/work`, `pyflextrkr_mcsdef/test2d`, `mcs_climatology_runs` (whole) | not a symlink, no file of a kept production tree links into it; list top-level content and newest dates |
| `/pscratch/sd/w/wcmca1` | `hackathon/tmp`, `hackathon/healpix`, `hackathon/etc_data`, `hackathon/mcs`, `scream-cess-healpix`, `GPM/healpix` | **count files not owned by feng045** in each (never delete another user's files: skip and report); **`hackathon/etc_data`: a verified copy must exist on CFS (names + sizes + a sample of checksums), otherwise skipped and I ask** |
| `/pscratch/sd/i/iclas2` | `MRMS/mcs_tuning` (listed twice), `MRMS/chain_debug`, `MRMS/nersc_test_20260614`, `MRMS/cell_conus`, `MRMS/mrms_5min/regrid/mergir_hourly`, and in `MRMS/mrms_5min/netcdf/CONUS` the 6 products other than `MergedReflectivityQCComposite_00.50`, `MergedReflectivityQC_L33`, `MultiSensor_QPE_01H_Pass2_00.00` | `cell_conus`: file names + sizes of all 159,008 inodes against `/global/cfs/cdirs/m1657/zfeng/MRMS/cell_conus` (read-only), plus a sample of byte comparisons; `mergir_hourly`: against `/global/cfs/cdirs/m2637/zfeng/MergedIR_MRMS_combined` the same way (52,224 hourly files on CFS, 52,296 files here: the difference is listed, not assumed); netCDF: see below |

**MRMS netCDF archive check (answers "confirm they are archived").** On a compute node, in parallel: for every product, list all files on
scratch (4.56M names, os.scandir) and compare with the union of the member lists `.../logs/hpss/lists/*.list`; per archive compare file count and
byte sum with the CSV (`files`, `bytes`) and require every scratch mtime to be older than the archive's write time. Then a **sample restore from
HPSS**: `htar -x` of 3 small member sets (3 different archives, e.g. an EchoTop_18 2021 day, a PrecipRate 2026 day, a Model_0degC_Height 2024
day) into a temporary scratch folder, `cmp` against the scratch originals, folder removed (read-only on HPSS, on the login node; if that is not
allowed I stop and ask, no Slurm job). Result table to you. **Rule: a file is deleted only if it is a member of a verified archive.** The unarchived
last days (20261024 and any newer) stay, so those product folders keep a few hundred files; you can archive them later with `hpss_backup.py`.
The three keep-products are untouched.

**Execution.** Manifest of absolute paths in the work dir (`/global/homes/f/feng045/.claude_tmp_verify/scream_e3sm/`), checks print a table, then
`/bin/rm -r` (the user's `rm` is aliased to `rm -i`) per directory, 16 at a time (xargs -P 16; the netCDF products split per product and year),
in the background on an own 1-node interactive allocation (job name `scream_cleanup`, so the Cess2 timing is not disturbed), one log per
directory, `lfs quota -u feng045 /pscratch` before and after. Paths are literal (the hooks block `$VAR` roots). Anything that fails a check is
skipped and reported; I ask before touching it.

### 2. Cess2 (SCREAM 3 km TUNE) re-run: identifymcs, matchpf, robustmcs, speed (no mapfeature), row stats

**Design: nothing in the old tree is modified.** New root `/pscratch/sd/f/feng045/SCREAM-decadal/cess2/mcs_rerun/` (decision; old results on wcmca1
stay as the reference):

- `tracking` -> symlink to the old `tracking/` (cloudid files for matchpf); `mcstracking/20190803.0000_20210306.0000` -> symlink to the old pixel
  folder (speed); `stats/trackstats_sparse_20190803.0000_20210306.0000.nc` and `tracknumbers_...nc` -> symlinks to the old files. Everything the 4
  steps write goes to the new `stats/` (row folders `mcs_tracks_*.rows`, `_pf_`, `_robust_`, `_final_`, the dense `mcs_tracks_final_*.nc` from the
  dense_netcdf step, which is on by default with rows + speed).
- **Config** `scream/tracking/config_mcs_tbpf_SCREAMv1-Cess2_rows.yml` (new file; the uncommitted original is not touched), from the Cess2 config by
  text substitution so comments stay: `stats_format: rows`, `robustmcs_definition: mcsmip`, `run_identifymcs/matchpf/robustmcs/speed: True` and
  `run_remap_healpix` and every other step False (`run_mapfeature: False`), `root_path`, `run_parallel: 2` (Dask scheduler, 4 nodes),
  `verify_step_outputs: True`, `skip_completed_steps: False`, `step_profile_dir`. **Not changed:** pixel_radius 10 km fixed area, thresholds,
  `heavy_rainrate_thresh` 10 (the same MCS definition as the old data and as the pixel files that speed reuses).
- **Launcher** `scream/tracking/slurm_SCREAM-Cess2_stats_rerun.sh`, modeled on `PyFLEXTRKR-dev/config/slurm_tbpf_mcstracking_stats_multinode.sh`
  (Dask scheduler on the first node, 64 workers on each of 4 nodes, wait for all 256 workers, then
  `python /pscratch/sd/f/feng045/tbpf_code_a4b8ad8/runscripts/run_mcs_tbpf_unified.py <config> <scheduler_file>`; the pinned worktree is the code
  that made the E3SM production, with `total_volrain` in matchpf). It works from an allocation id (`srun --jobid=<id> --overlap`), so it needs no
  batch submission.
- **Interactive job:** `salloc --no-shell -A m1657 -C cpu -q interactive -N 4 -t 01:30:00 -J cess2_rerun` (QOS limit 4 nodes / 4 h; I checked), the
  launcher runs detached, logs under `<root>/logs/`. **I monitor it** with background waiters: step times (`pyflextrkr.step_timing` lines), the
  Dask worker count, and the step outputs as they appear; a first look after the first minutes (identifymcs must read the Jan-2026
  `trackstats_sparse` file with the new code: if it fails, it fails fast with exit code 1 and I report before anything else is run).
  Expected 20-35 min; the allocation is released with `scancel` right after (about 2-4 node-hours charged to m1657).
- **Checks after the run (before any use):** (a) every step passed its output check and the job exited 0; (b) the new `mcs_tracks_pf` has
  `total_volrain` and `total_heavyvolrain`, non-NaN where `total_rain` exists; (c) **old vs new**: every variable both have (`mcs_tracks_pf`,
  `_robust`, `_final`) read with `RowStats.to_pandas` against the old dense files agrees (float tolerance), and **the robust MCS track set is
  identical to the old one** (count and track numbers). This is the condition for speed using the old pixel files; if the set differs I stop and
  report instead of using the speed result. (d) the dense final file and the speed variables are plausible against the old ones.
- **After the check** (small, optional step, shown to you first): `combine_filter_mcs_trackstats.py` on the new final rows -> Parquet
  (tropics + global) in `<root>/parquet/`, without the NaN-fill warning; I do not overwrite the existing Cess2 Parquet in
  `SCREAM-decadal/cess2/stats/` until you say so. The old NaN-filled files and `input_copy/` (808 MB) stay for now.

### 3. `plot_global_mcs_climo_rainmap_scream_e3sm_obs.ipynb` revision

Edits go into the percent-format sources `/global/homes/f/feng045/.claude_tmp_verify/scream_e3sm/nb_maps_part1.py` and `nb_maps_part2.py`; rebuild
with `build_notebooks.py` into `scream/Notebooks/`, execute with `jupyter nbconvert --execute` (kernel pyflex26_3) on a compute node (about
20 min; the Cess2 job and the deletions run at the same time on other allocations), look at every PNG. Each change is one Configuration key where it
is a setting.

1. **Order of variables in the two 7-source overviews:** `VARIABLES_TO_PLOT = ['cloudfreq', 'mcspcp', 'pcpfrac']` (Frequency, Precipitation,
   Fraction): rows of the colorbar-per-row figure, columns of the colorbar-per-column figure; the per-variable figures follow the same order.
2. **`plot_obs_and_bias_maps` layout:** the zonal-mean panel moves to the second slot (right of OBS): panels (a) OBS, (b) Zonal mean, then rows of
   `3 km CTL | 3 km TUNE`, `13 km CTL | 13 km TUNE`, `25 km | 100 km` (the bias list order is already that; only the zonal slot, the panel
   letters of the biases (c)-(h) and the bottom-row longitude labels change). The `zonal_in_slot` / `append_row` logic is replaced by an explicit
   `zonal_slot` index (default 1).
3. **OBS interannual band** (your choice: IQR of the zonal means): extract only the 132 OBS monthly files 2007-01..2017-12 from the two mcsmip
   Zenodo archives into `/pscratch/sd/f/feng045/SCREAM-decadal/mcs_global_v3/monthly_2007_2017/`; **first check** that the 12-month climatology
   computed from them reproduces the existing OBS climo file (`calc_mcs_rainmap_climo_from_monthly.py` logic: annual = 24 x sum / ntimes) to float
   precision. Per year: annual fields -> cos(lat)-weighted 2-degree zonal means over OBS-valid cells (`zonal_mean_cosw`, the same as the lines);
   fraction = ratio of that year's zonal means; band = 25th and 75th percentile across the 11 years per bin, `fill_between` in light gray under the
   black OBS line, legend entry "OBS interannual IQR (2007-2017)". The per-year zonal means are cached in a small netCDF next to the figures
   (Configuration: `obs_monthly_dir`, `obs_iqr_years`, `show_obs_iqr`).
4. **Gray "Missing data" in every map panel, the text only on OBS:** the valid-data mask is passed to `draw_map_panel` for all panels
   (`missing=mask`, `missing_text=is_obs`); biases are NaN there already, so the gray replaces the white.
5. **Less vertical stretch:** the maps are drawn with `set_aspect('auto')` in a box of `panel_aspect = 0.5`, but the Robinson map between 60S and
   60N is about 0.39 (height / width). `panel_aspect` becomes `None` = computed from the projection and `lat_range` (transform of the corners), so
   the panels have their true aspect (about 20 % lower per panel, consistent with your earlier "true map aspect" rule); the colorbar length and the
   zonal panel follow the new height, the legend headroom is re-tuned.
6. **Fonts, same in ALL notebooks made in this session (your comment):** `mpl.rcParams['font.family'] = 'STIXGeneral'` and
   `['mathtext.fontset'] = 'stix'` in the imports cell of each of the three notebooks: the maps notebook (all its figures, overviews included), the
   heavy_rainrate sensitivity notebook (its imports cell is copied from the maps notebook by `build_notebooks.py`, so it follows automatically) and the
   track-stats notebook (its own imports cell). `font_scale = 1.3` multiplies `fontsize` (12 -> 15.6) and `cb_fontsize` (11 -> 14.3), and with them the
   tick, legend and title sizes that derive from them, in the OBS + bias figures of the maps notebook **and of the sensitivity notebook** (same
   function, same figure type). **Assumptions (veto on approval):** the two overview figures and the line plots of the track-stats notebook get the
   font family but keep their sizes; any notebook I make later in this session gets the same rcParams (recorded as a project style in the docs file
   and the memory note, not as a general rule).
7. **The other function changes (items 2, 4, 5) live in the function cells that the sensitivity notebook copies**, so it gets the gray masks and
   the true aspect too; its zonal panel stays in the **last** slot as you specified for it (`zonal_slot` default = last; the maps notebook sets
   `zonal_slot = 1`), and it shows the same OBS IQR band (from the same cache). Both notebooks are rebuilt; the sensitivity notebook stays
   unexecuted (no results yet), the maps and track-stats notebooks are re-executed so their saved outputs have the new fonts.

### 4. Space check after the deletions

`lfs quota -u feng045 /pscratch` before and after; a fresh run of `scan_inodes.py` / `report_inodes.py` on the three trees (about 15 min in the
background) to confirm what is left and to list the next top-20; a table: files and TB now, planned additions (10 sensitivity jobs +88k files /
+1 TB; the Cess2 re-run a few hundred new files and a few GB, because the cloudid and pixel files are linked, not copied), the margin to the
10M soft limit, and, for the future, the 15 E3SM production years that would be re-run from matchpf with the chosen threshold (about 1.6 TB /
130k files if kept as new folders, net zero if they replace the production years). The verdict (enough or not) goes into the report.

### Order of work

0. Sync docs + memory (plan, progress entry).
1. Start the deletion pre-flight checks (own 1-node allocation) and, in parallel, set up the Cess2 re-run (config, launcher, symlinks, 4-node
   allocation, run, monitor): they use different filesystems paths and allocations.
2. While those run: notebook edits, the 132 OBS files extraction and climo reproduction check.
3. Deletions execute when their checks pass; Cess2 checks (a)-(d); notebook execution and figure inspection; space re-check.
4. Release all allocations. **Checkpoints for you:** the HPSS check table + any skipped item (before the netCDF delete), the Cess2 comparison
   result, the revised figures. After that: the heavy_rainrate job submission is still waiting for your approval (nothing changes there).

### Verification (end to end)

- Deletions: each deleted path no longer exists; each kept path (3 MRMS products, `etc_data_*`, `mcs_masks*`, production trees) still has its
  scan count; quota before/after; deletion logs without errors; items skipped by a check are listed with the reason.
- Cess2: exit 0, all four output checks passed, step times logged; new vs old comparison (c) with the result table; `total_volrain` /
  `total_heavyvolrain` present and consistent (`total_volrain` ~ `total_rain` x 100 km^2 for the fixed pixel area, spot check).
- Notebooks: the maps and track-stats notebooks run top to bottom with 0 errors; every figure viewed (order, zonal slot, gray masks and one
  "Missing data" text, band visible and plausible against the std in the climo file, aspect, STIXGeneral in titles, labels, ticks, legends and
  colorbars); the OBS climo reproduction check passes; the rebuilt sensitivity notebook is checked with the baseline (and a stand-in run) as in
  round 1, its rcParams cell and zonal-last layout confirmed.
- Space: the table above with measured numbers.

### Risks and what I will state

- `hackathon/etc_data` is production on pscratch (CFS copy verified first, else skipped); `hackathon/mcs` and `scream-cess-healpix` live in the shared
  `wcmca1` area: only feng045-owned files are removed, others are reported.
- The MRMS netCDF deletion relies on the archives; the last unarchived days are kept; Model_0degC_Height goes too (archived, not in your keep list).
- Speed reuses the old pixel files: valid only if the new robust MCS set equals the old one (checked, else stopped).
- Zonal-mean band: the 2007-2017 per-year files come from the Zenodo copy, verified against the existing climatology.
- Interactive 4-node allocation and a second 1-node allocation at the same time (QOS shows no per-user limit besides 4 nodes per job); if the
  multi-node srun inside an allocation does not work, fallback: one node with 128 workers (about 2.5 times slower), never a batch submission
  without your approval.

### Files

New: `scream/tracking/config_mcs_tbpf_SCREAMv1-Cess2_rows.yml`, `scream/tracking/slurm_SCREAM-Cess2_stats_rerun.sh`, deletion manifest and logs in the
work dir, per-year OBS cache next to the figures. Modified: the three notebooks in `scream/Notebooks/` (`plot_global_mcs_climo_rainmap_scream_e3sm_obs`
and `plot_tropical_mcs_trackstats_all_sources` rebuilt and re-executed, `plot_mcs_heavyrain_sensitivity_e3sm` rebuilt, unexecuted), their
sources in the work dir (`nb_maps_part1.py`, `nb_maps_part2.py`, `nb_sens_body.py`, `nb_trackstats.py`), `scream/README.md` (a short note on the Cess2 re-run and on the band), the docs file and the memory note.
Untouched: PyFLEXTRKR-dev, the old Cess2 tree, production data, the existing Parquet files until you decide.

- 2026-11-16 17:50 **Round 2 approved** (plan above). User's decisions: OBS band = IQR of the zonal means (their extreme-rain notebook convention); fonts
  `STIXGeneral` + `mathtext.fontset stix` in ALL notebooks made in this session (maps, sensitivity, track-stats; project style, not a general rule);
  font_scale 1.3 for the OBS + bias figures. Interactive allocation 61433600 was released earlier; new ones are requested for the cleanup (1 node) and the
  Cess2 re-run (4 nodes). **Round 2 NEXT STEPS are the 'Order of work' of the plan above; the heavy_rainrate job submission still waits for the user.**

- 2026-11-16 20:10 **Round 2 in progress** (interactive allocations: 61446671 `cess2_rerun` 4 nodes nid[200051-200054] ends ~21:17, 61446672 `scream_cleanup` 1 node nid200032 ends ~22:47; work files in `.claude_tmp_verify/scream_e3sm/`, cleanup logs and manifests in `cleanup/`):
  - **Deletions done** (pre-flight `cleanup_preflight.py`, guarded deleter `cleanup_delete.py`): MRMS netCDF: all 136 HPSS archives passed every check, sample restore 12/12 files byte-identical, 13,206
    date folders of the 6 products removed (3.2M files), kept: the 3 products and the 600 unarchived files of 20261024 (EchoTop_18, EchoTop_30, Model_0degC_Height); the 3 now-empty product folders removed.
    `cell_conus` (158,997 files / 2,747 GB identical on CFS, 80/80 byte-identical sample), `mergir_hourly` date folders (52,224 names on CFS, same sizes, sample identical; the 72 `_reports/*.csv`
    are kept), `hackathon/etc_data` (all 15,763 files on CFS wcm_shr/hk25/etc_data, same sizes, sample identical), `hackathon/tmp`, `GPM/healpix` (contents; the empty `healpix` folder cannot be removed:
    parent not group-writable), the 9 feng045 folders (of `mcs_animation` only the frame folders: the four `new/frames/YYYYMM.tar.gz` made today 16:02-16:19 + tar_dirs.sh + tar.log were KEPT),
    `mcs_tuning`, `chain_debug`, `nersc_test_20260614`. Quota 9,258,867 -> 4,805,417 files, 77.9 -> 66.2 TB (before the mergir/G4 steps).
  - **NOT deleted, waiting for the user:** `hackathon/healpix` (62,299 entries owned by wcmca1), `hackathon/mcs` (146,845 wcmca1 + 1 smheflin), `scream-cess-healpix` (1,403 wcmca1, 132 zx2217, 62 chenzm):
    other owners' files; deleting only the feng045-owned entries would free the quota without touching theirs.
  - **OBS band source:** the Zenodo monthly rain maps are the TC-EXCLUDED set (MCS precipitation 8.6 % and cloud frequency 6.3 % below the OBS climo file), so they do NOT reproduce the climatology the notebook
    uses; the TC-included originals are `/global/cfs/cdirs/wcm_shr/gsharing/MCS_Global/V3/MCSMIP/stats_mcsmip/monthly/` (the `monthly_extc` folder is the excluded set). The 132 files 2007-2017 were
    copied to `/pscratch/sd/f/feng045/SCREAM-decadal/mcs_global_v3/monthly_2007_2017` and reproduce the OBS climo file exactly (largest difference 0.0); the Zenodo extraction is parked in `_zenodo_extc_2007_2017` (delete later).
  - **Cess2 re-run:** root `SCREAM-decadal/cess2/mcs_rerun/`, config `scream/tracking/config_mcs_tbpf_SCREAMv1-Cess2_rows.yml`, launcher `scream/tracking/slurm_SCREAM-Cess2_stats_rerun.sh <jobid> 4`
    (run on the first node via ssh): identifymcs 2.83 min (106,682 Tb MCS), matchpf 13.2 min (100 % of 1,634,717 entries have PF statistics), robustmcs 0.15 min (**79,370 robust tracks = the old count**), speed running.
  - Notebooks: sources edited (backups `bak_*_before_round2.*`), rebuilt into `Notebooks/` and executed (maps, track-stats); sensitivity notebook rebuilt, unexecuted.

- 2026-11-16 20:30 **Cess2 re-run DONE and checked** (job 61446671 released 20:21; exit 0, 31 min incl. 1 min Dask start): identifymcs 2.83 min, matchpf 13.20 min (100 % of 1,634,717 entries have PF
  statistics), robustmcs 0.15 min (79,370 robust MCS), speed 6.94 min (1,144,526 finite speeds), dense netCDF 6.34 min (`mcs_tracks_final_*.nc`, 830 MB, the old one 807 MB). Outputs in
  `/pscratch/sd/f/feng045/SCREAM-decadal/cess2/mcs_rerun/stats/` (rows folders + dense file; logs in `logs/`), tidy Parquet (tropics 54,010 tracks, global 78,785 tracks in the box, 1,356,951 rows, 69
  columns, NO NaN-fill warning, `total_volrain` = 100 x `total_rain` exactly = pixel area 100 km2) in `mcs_rerun/parquet/`; the existing Parquet in `cess2/stats/` is NOT replaced yet.
  **Old (Jan 2026 code, dense) vs new (pinned code a4b8ad8, rows)** with `check_cess2_rerun.py` + `analyze_cess2_diff.py` (tables kept in `mcs_rerun/_check_{old,new}.parquet`, deletable):
  the robust MCS set is identical (79,370 tracks, same local_track ids, start times, durations; same 1,356,951 rows), all Tb columns (area, ccs_area, mean location, tb) identical, but **4.1 % of the
  rows (56,277; 22,017 of 78,785 tracks) differ in PF-derived columns**: pf_lon / pf_lat and centroids 1-3 % of rows (median 1-4 deg; 29 % of the differing rows are in the 2 % of tracks that cross the
  periodic boundary, pbc_flag), PF identification (pf_npf, area, rain rate, ...) only 0.03-0.1 % of rows (335-812 tracks), movement_* 1.8 % of rows. Not bit-identical to the old statistics:
  the cause is a change of matchpf/PBC/speed code since January (not traced to a commit); speed used the OLD pixel files (labels of the old PF numbering), so the movement columns of rows with a
  changed PF numbering are inconsistent. Decision for the user: use the re-run Parquet (has total_volrain; matches the code of the E3SM production) or keep the old one (NaN volrain).

- 2026-11-16 20:50 **Round 2 finished** (both allocations released: 61446671 at 20:21, 61446672 at 20:50; nothing queued). Final numbers: pscratch 9,258,867 -> 4,751,033 files (before the three wcmca1 folders and
  the 4 tarballs), 77.9 -> 65.9 TB; fresh scan (`cleanup/report_after.txt`, old tables in `scan_before_cleanup/`): feng045 886k (847k production-looking), wcmca1 829k, iclas2 3.04M (MRMS netcdf 1.33M of the 3 kept
  products, hrrr_combined 637k). Planned additions: 10 sensitivity jobs +88k files / +1 TB, Cess2 re-run 45 files: about 4.85M of 10M files, about 67 TB of 100 TB: enough. Notebooks rebuilt and executed
  (maps: 0 error cells, 5 figures 20:22-20:41; track-stats: 0 error cells; sensitivity: rebuilt, code tested with the control run as a stand-in threshold, NOT executed); my temporary files removed
  (`_zenodo_extc_2007_2017`, `_verify_climo`, `figures_e3sm_test_r2`, `_check_*.parquet`). **Open for the user:** (1) approval to submit the 10 heavy_rainrate jobs, (2) `hackathon/healpix`,
  `hackathon/mcs`, `scream-cess-healpix` (other owners' files), (3) the four `mcs_animation/new/frames/YYYYMM.tar.gz` (kept), (4) swap of the Cess2 Parquet for `mcs_rerun/parquet/` (4.1 % of the rows
  differ in PF/movement columns), (5) commit (README, scripts, tracking config + launcher, notebooks; the repo has many other uncommitted changes).

---

# ROUND 3 (APPROVED 2026-11-16 night): submit the sensitivity jobs, Cess2 Parquet swap, notebook revisions

The user's round-3 answers and the approved plan (verbatim copy of the plan file, headings shifted one level). User decisions: submit the 10 jobs; hackathon comparison/deletion SCRAPPED (enough inodes); mcs_animation deleted by the user (tarballs are on CFS /global/cfs/cdirs/m1657/zfeng/MRMS/cell_mcs_conus/track_maps/mcs_multicell_2025_v1/frames); swap in the re-run Cess2 Parquet; maps: aspect stays 'auto' by default (user prefers one knob) and the figsize is fixed/overridable; OBS band = zonal mean of the cell-wise interannual IQR; composites both raw and interpolated.

## SCREAM / E3SM MCS evaluation, round 3: submit the sensitivity jobs, Cess2 Parquet swap, notebook revisions

### Context

Round 2 is finished and documented in `/global/homes/f/feng045/program/scream/docs/PLAN_scream_e3sm_mcs_evaluation.md` (progress log) and the memory note
`project_scream_e3sm_mcs_evaluation`. Your answers and feedback today: (1) **submit the 10 heavy_rainrate sensitivity jobs** (this is the explicit
Slurm approval); (2) the `hackathon` comparison with CFS and the bash file for wcmca1 are **scrapped** (you have enough inode space; nothing is compared, deleted or
written there); (3) `mcs_animation` is deleted by you (tarballs are on CFS); (4) swap in the re-run Cess2 Parquet, archive the old one, record it
in the docs and the memory; (5) map-plot feedback (figsize option, maps still stretched, zonal panel, OBS band, labels, gap; **keep `aspect='auto'` as the
default and fix the figsize**); (6) port the analyses of
`plot_tropical_mcs_trackstats_land_ocean.ipynb` into `plot_tropical_mcs_trackstats_all_sources.ipynb`. Your answer on the composites: **both raw and
interpolated**. **My first action after approval is to append this plan to the docs file and note it in the memory note.**

Environment: `/global/common/software/m1867/python/pyflex26.3` (kernel `pyflex26_3`); heavy work on one own interactive node (account m1657); CFS read-only;
no commits unless you ask; no deletion of other users' files.

### Facts measured while planning (read-only)

- **Why the maps are still stretched** (your point is right): `plot_obs_and_bias_maps` and `plot_maps_cbar_per_row_or_col` size the figure with a cell width of
  `figwidth / ncol` (7.5 in), but the real cell is 5.9 in (colorbars and margins take the rest), and the maps are drawn with `set_aspect('auto')`, so they fill the
  too-tall cell. True aspect of Robinson 60S-60N = **0.373**; the last bias figure has panels of **0.443** (19 % too tall). The per-column overview has the same formula.
- **OBS interannual band:** the band I drew (IQR across the 11 years of the *annual zonal mean*) is only **9-10 % of the line over all latitudes and 1.6-6.6 % in the
  tropics**, so the 3-pt black line hides it. The *zonal mean of the cell-wise* interannual spread is **about 23-30 % of the line as a standard deviation** (a normal IQR
  = 1.35 x std = 32-41 %). The climo file has only `*_std`, no IQR; I can make the exact cell-wise IQR from the 11 annual fields I already have (the TC-included monthly files
  copied to `SCREAM-decadal/mcs_global_v3/monthly_2007_2017`, verified equal to the climo file).
- **Stats data check on the 7 Parquet files:** the columns the reference analyses need (`pf_landfrac`, `start_split_cloudnumber` / `end_merge_cloudnumber` NaN = natural start/end, `total_volrain`,
  `total_heavyvolrain`, `movement_speed`, `track_duration`) behave the same in all sources (non-split/non-merge tracks 11-43 %; land/ocean tracks: 3 km TUNE 11,986 / 26,139, 25 km 4,407 / 5,674,
  **100 km 18 land / 150 ocean**). The old Cess2 file has `total_volrain` 100 % NaN (the reference table and composites need it), the re-run has 0 % NaN. seaborn 0.13.2 and scipy 1.17.1 are in pyflex26.3.

### A. Actions

1. **Submit the 10 sensitivity jobs** (account m1657, regular QOS, 1 node, 3 h each; about 10 node-hours; +88k files, +1 TB; pscratch is at 4.75M of 10M files):
   `python tracking_e3sm/gen_heavyrain_sensitivity.py --models ne120 ne30 --thresholds 5.0 3.0 2.0 1.5 1.0 --submit` from `/global/u1/f/feng045/program/scream`
   (pyflex26.3 python; it rewrites the same configs and calls sbatch). Check: 10 job ids in `squeue`, `submitted.jsonl` of the generator, nothing for the control. Record the ids in the docs
   and memory with the next steps (check each run by its outputs, run `plot_mcs_heavyrain_sensitivity_e3sm.ipynb`, you pick the threshold). The jobs run unattended; I do not wait for them.
2. **`mcs_animation`:** nothing to do (you deleted it); I only confirm the folder is gone and note the CFS location of the tarballs in the docs.
3. **Cess2 Parquet swap** (`/pscratch/sd/f/feng045/SCREAM-decadal/cess2/stats/`): create `archive_20261116_old_dense_version/`, move into it the two old files
   `mcs_tracks_final_combined_{tropics,global}_2019_2021.parquet` (and the `input_copy/` folder they were made from) plus a short `README.md` (what, when, why, how to restore); copy the new files
   from `cess2/mcs_rerun/parquet/` to `cess2/stats/` (same names, so the notebooks need no path change), verify with `cmp` and by reading them (shape, 69 columns, `total_volrain` non-NaN).
   **Docs and memory record:** what changed (old: dense final file of 2026-01-17 made with an older PyFLEXTRKR, `total_volrain` and `total_heavyvolrain` NaN-filled; new: row tables re-run 2026-11-16
   with pinned code `tbpf_code_a4b8ad8`, same 79,370 robust tracks), the differences (4.1 % of rows differ in PF-derived and movement columns, numbers per column, mostly periodic-boundary tracks;
   ocean tracks 26,091 -> 26,139), where everything is (archive folder, `mcs_rerun`, the config, the launcher, the check scripts), and how to undo. The old pscratch archive is purgeable: note it.
4. **`hackathon` and `scream-cess-healpix`:** untouched (scrapped by you); the three wcmca1 folders stay on the open list of the docs, with a note that nothing is needed for the quota.

### B. Maps notebook (`plot_global_mcs_climo_rainmap_scream_e3sm_obs.ipynb`, sources in `.claude_tmp_verify/scream_e3sm/nb_maps_part1.py` / `nb_maps_part2.py`)

1. **`figsize=(x, y)` option** in `plot_obs_and_bias_maps` and `plot_maps_cbar_per_row_or_col` (also a Configuration key): if given it replaces the computed size.
2. **No stretching, with `aspect='auto'` kept as the default (your preference, one knob):** the maps stay `set_aspect('auto', adjustable=None)` and I fix the **figure size**: the automatic figure
   height is computed from the **measured** cell width instead of `figwidth / ncol` (build the GridSpec, read the width of a map cell, then height = rows x cell width x 0.373 + the row spacing + the
   fixed title / colorbar / margin inches, resize, then draw), so each cell has the true shape and the maps fill it without gaps. `figsize` (item 1) overrides it when you want to tune by hand.
   A parameter `aspect='auto' | 'equal'` is added (`'equal'` = cartopy keeps the true shape inside any cell, with possible white space); it is **not** the default. Applies to the bias figures and
   to both overviews (the 7-column row layout and the vertical 3-column layout).
3. **Zonal panel:** its axes top is aligned with the top of the OBS map (the title sits above it like the map titles); its left edge is placed from the measured tight bounding box of the tick labels
   and y label (about 0.05 in gap to the cell) so it sits close to the OBS map; the bottom keeps room for the x label. Legend headroom re-tuned.
4. **OBS interannual band:** new Configuration key `obs_iqr_method = 'cell_iqr'` (default): the 25th and 75th percentile across the 11 years of the annual field **in every cell**, then the same
   cos(lat)-weighted 2-degree zonal mean of those two fields (valid cells; for the fraction, the cell-wise IQR of the annual fraction field). The previous definition stays as `'zonal_iqr'`. The cache
   file name includes the method. I print the relative band width per variable in the notebook so that you can see it is visible. Legend text: "OBS interannual IQR (2007-2017)".
5. **Labels:** `SOURCES` labels become `OBS`, `3-km CTL`, `3-km TUNE`, `13-km CTL`, `13-km TUNE`, `25-km`, `100-km` (no SCREAM / E3SM; hyphen before km) in the zonal legend, overview titles and row
   labels; bias titles become `(c) 3-km (CTL − OBS)`, `(d) 3-km (TUNE − OBS)`, ..., and for E3SM (no CTL/TUNE) `(g) 25-km − OBS`; the Cess2 period reads `2019-08 to 2021-02`. The
   same short labels are used in the stats notebook. (The sensitivity notebook keeps its own labels "E3SM 25 km" in titles; it shares the function cells and the band.)
6. Rebuild with `build_notebooks.py`, execute with nbconvert on the node (about 25 min), and **check the result by measurement** (panel height / width of the saved PNG = 0.373 within 1 %), then look at all five figures.

### C. Stats notebook (`plot_tropical_mcs_trackstats_all_sources.ipynb`, source `nb_trackstats.py`): port of the 5 analyses

Reference cells -> new cells (all appended after the existing load / checks / summary; every setting goes to the Configuration cell, source colors, labels and order come from `SOURCES`,
`REF_SOURCE = 'obs'`, the other six sources are the comparisons; no hard-coded SCREAM names):

| your item | reference cells | what is ported |
| --- | --- | --- |
| land / ocean split and lifetime statistics (needed by the next two) | 9, 11, 12, 13 | `classify_land_ocean` (LAND_MINFRAC 0.9, OCEAN_MAXFRAC 0.1), derived `ccs_area_all`, `core_area_ratio`, `heavy_rain_ratio`, variable lists, `compute_lifetime_stats`, land / ocean overlap check |
| box-whisker plots of the lifetime statistics | 16, 18 | `plot_boxplots` (3 x 3 grid, land / ocean on x, 7 sources as hue, whiskers 5-95 %, mean marker, notch, `n=` in the legend), same variables, titles, log scales and labels |
| table with % difference and significance tests | 20, 21 | `compute_sig_table` (Mann-Whitney U, alpha 0.01, Tb normalised by the OBS P10-P90 range, `MIN_N`), `build_html_table` (OBS means; model columns `L: +12%`, `✘` = not significant), saved as HTML |
| composite lifecycle (by lifetime) | 23, 26, 28, 30 | `composite_track_evolution`, non-merge / non-split filter, `comp_var_specs`, duration bins 4-10 ... 26-30 h, `plot_composite_evolution` (one panel per variable x source, color = duration bin), **Land and Ocean** |
| composite lifecycle (Land vs Ocean) | 32, 33, 34 | `plot_composite_evolution_shading` (sources overlaid, columns Land / Ocean, bins 10-14 h dashed and 22-26 h solid, a second figure with IQR shading for 10-14 h) |
| composite lifecycle (interpolated) | 23 (`interpolate=True`) | **each composite figure twice**: interpolated (time-normalised, the reference setting; the main set) and raw relative time (n falls at the tail); a Configuration key `COMPOSITE_MODES = ['interpolated', 'raw']` |

Adaptations I will state in the notebook: a bin needs at least `MIN_TRACKS_COMPOSITE = 20` tracks (E3SM 100 km has 18 land tracks and 69 non-split tracks, so most of its panels stay empty or are
skipped); `MIN_N = 5` of the table is kept; figures go to `figdir` (PNG at 200 dpi, PDF optional by a key); fonts STIXGeneral; docstrings and a comment on every block as in your other code.
**Run time:** the reference interpolates track by track in Python; with 7 sources it may take tens of minutes. I time one source first; if the full run would exceed about 30 minutes I vectorise the
interpolation by exact duration (all tracks of equal length in one array) and **prove it equals the loop version** on OBS (same arrays) before using it. Memory: the 30M-row table fits on a 512 GB
node (about 20 GB per full copy). The notebook is executed with nbconvert on the node; every figure is viewed; the table is checked against the numbers of the Parquet files (for example the
OBS mean lifetime 17.8 h of the summary cell).

### Order of work

0. Docs + memory sync (this plan). 1. **Submit the 10 jobs** (they queue while I work). 2. Cess2 Parquet swap + docs/memory/README record. 3. One interactive node (m1657, 4 h) for the notebook
runs. 4. Maps notebook edits, rebuild, execute, measure, view. 5. Stats notebook port, time the composites, execute, view. 6. README, docs, memory; release the node; results to you.

### Verification

- Jobs: 10 ids queued; later each run checked by outputs (round-2 recipe), not by the Slurm state.
- Swap: `cmp` of the copied files with `mcs_rerun/parquet`, archive folder holds the old two files + README, both Parquet read back, docs and memory entries exist.
- Maps (`aspect='auto'`, the default): measured panel aspect 0.373 (within 1 %) in the bias PNGs and both overviews, so the maps are not stretched and there are no gaps; the zonal axes top equals the OBS map top and its left edge is close to the OBS panel; the band is visible (relative width printed);
  labels as specified; sensitivity notebook rebuilt and its stand-in test still runs.
- Stats: notebook runs top to bottom with 0 error cells; figure and table sanity (OBS values equal the existing summary; model % differences have the expected sign from the earlier tables); vectorised
  composites (if used) identical to the loop version; every figure viewed.

### Risks and what I will state

- With `aspect='auto'` the maps fill their cells, so the figure height must be right: it is solved from the measured cell width, and `figsize` is the manual override if a layout still needs tuning.
- The Cess2 re-run differs from the old data in 4.1 % of rows (PF position / movement): all Cess2 results in the stats notebook now come from the re-run.
- E3SM 100 km has too few land / no-split tracks for composites and several table cells (shown as `N/A` / empty by design).
- The sensitivity jobs use the pinned code `tbpf_code_a4b8ad8` and the control run reproduced production exactly; they are independent of everything else.

### Files

New: `cess2/stats/archive_20261116_old_dense_version/` (data + README). Modified: the maps, sensitivity (rebuilt, unexecuted) and track-stats notebooks and
their sources in `.claude_tmp_verify/scream_e3sm/`, `scream/README.md` (Step 3 entries, Cess2 note), the docs file and the memory note. Untouched: PyFLEXTRKR-dev, production data, `hackathon`,
`scream-cess-healpix`, CFS.
- 2026-11-16 21:35 round 3 approved; progress entries below.
- 2026-11-16 21:38 **The 10 heavy_rainrate sensitivity jobs are SUBMITTED** (user's explicit approval): job ids 61451205-61451214 in the order hr5p0_ne120, hr3p0_ne120, hr2p0_ne120, hr1p5_ne120, hr1p0_ne120,
  hr5p0_ne30, hr3p0_ne30, hr2p0_ne30, hr1p5_ne30, hr1p0_ne30 (account m1657, regular QOS, 1 node, 3 h limit each; log of the submission `submitted.jsonl` of the generator). Run trees
  `<root>_sens/heavyrain_<tag>/2010/`, job logs in `<root>_sens/heavyrain_<tag>/logs/`. **NEXT when they have ended:** check each run by its OUTPUTS (12 monthly rain maps, final rows, the climo file, the
  `heavy_rainrate_thresh` attribute of `mcs_tracks_pf` = the key, robust MCS count and total heavy rain rising as the threshold falls; a COMPLETED Slurm state is not proof), then execute
  `Notebooks/plot_mcs_heavyrain_sensitivity_e3sm.ipynb` on a compute node, give the summary table to the user, who picks the production threshold. A failed job can be resubmitted as it is.
- 2026-11-16 21:40 **Cess2 Parquet SWAPPED** (user's decision): in `/pscratch/sd/f/feng045/SCREAM-decadal/cess2/stats/` the files `mcs_tracks_final_combined_{tropics,global}_2019_2021.parquet` are now the
  re-run version (copied from `cess2/mcs_rerun/parquet/`, `cmp`-identical; tropics 54,010 tracks / 889,852 rows, global 78,785 tracks / 1,356,951 rows; `total_volrain` 100 % non-NaN, `total_heavyvolrain` 94 % / 90 %).
  The OLD files and `input_copy/` (the old dense final file copy) were MOVED to `cess2/stats/archive_20261116_old_dense_version/` with a README (origin, differences, restore). What changed: old = dense final file of
  2026-01-17 made with an older PyFLEXTRKR (no total_volrain / total_heavyvolrain: NaN-filled, converter warning); new = row-table re-run of 2026-11-16 (identifymcs, matchpf, robustmcs, speed, dense netCDF; no mapfeature;
  pinned code `tbpf_code_a4b8ad8`; config `scream/tracking/config_mcs_tbpf_SCREAMv1-Cess2_rows.yml`, launcher `scream/tracking/slurm_SCREAM-Cess2_stats_rerun.sh`). Differences: same 79,370 robust tracks and rows, Tb columns identical,
  4.1 % of rows (22,017 tracks) differ in PF / movement columns (PF position 1-3 % of rows, PF identification 0.03-0.1 %, movement 1.8 %; 29 % of them in periodic-boundary tracks), ocean tracks 26,091 -> 26,139.
  The archive is on pscratch (purgeable); the old dense source is on wcmca1 scratch and in HPSS. `mcs_animation` is gone (user deleted it; the tarballs are on CFS `m1657/zfeng/MRMS/cell_mcs_conus/track_maps/mcs_multicell_2025_v1/frames`).
  The hackathon / scream-cess-healpix folders of wcmca1 are NOT touched (scrapped by the user: inode space is sufficient).
- 2026-11-16 22:10 **Round 3 notebooks.** Interactive node job 61451255 (nid200029, m1657, 4 h, ends about 01:40) holds the notebook runs; work files in `.claude_tmp_verify/scream_e3sm/` (backups
  `bak_*_before_round3.*`, test logs in `cleanup/`, staging builds `nb_build_r3*`).
  - **Maps notebook** (sources `nb_maps_part1.py`, `nb_maps_part2.py`): `figsize=(x, y)` option and `aspect='auto'` (default) / `'equal'` in `plot_obs_and_bias_maps` and `plot_maps_cbar_per_row_or_col`; the cause of the
    stretching was the figure-height formula (cell width `figwidth/ncol` = 7.5 in instead of the measured 5.9 in, and the overviews even `panel_aspect=0.5`): the height is now solved from the MEASURED cell width, and
    the measured panel aspect (test wrapper) is 0.373 = the true Robinson 60S-60N value in the bias figures (15 x 10.9 in) and in both overviews (26 x 4.85 in, 12 x 11.9 in). Zonal axes: top = top of the OBS map,
    left edge from its measured tick-label box (`zonal_pad_in`), for an appended zonal row a top pad (`zonal_top_pad_in`). OBS band: `obs_iqr_method='cell_iqr'` (zonal mean of the cell-wise 25-75 % interannual range;
    25-39 % of the line, visible) or `'zonal_iqr'` (IQR of the annual zonal mean: 2-10 %, hidden by the line); per-year zonal means and the cell IQR cached in one netCDF (cache version 2); the cell-wise percentiles use a vectorised
    `percentiles_over_years` (equal to np.nanpercentile to 4e-8, 100 times faster). Labels `3-km CTL` ... `100-km` without SCREAM / E3SM, titles `3-km (CTL − OBS)` / `25-km − OBS` (`bias_title`).
    The sensitivity notebook shares the function cells (rebuilt, its stand-in test runs, not executed). Executed notebooks: maps (final build, executed on the node), sens (rebuilt only).
  - **Track-stats notebook** (source `nb_trackstats.py`): the 5 analyses of `plot_tropical_mcs_trackstats_land_ocean.ipynb` ported for all 7 sources with every setting in the Configuration cell: land / ocean split and lifetime
    statistics, box-whisker plots, the table of % differences with Mann-Whitney U (HTML), composite life cycles (by lifetime for Land and Ocean; Land vs Ocean overlay with two bins and with IQR shading), each interpolated and raw.
    `composite_track_evolution` is vectorised (tracks with the same number of valid values are interpolated together) and the notebook checks it against the track-by-track loop (OBS land, 10-14 h, ccs_area: difference 5e-10 =
    3e-16 relative). Executed in about 4 minutes on one node, 0 error cells, 16 figure/table files in `figures_e3sm/` (`mcs_lifetime_stats_land_ocean_boxplot_tropics.png`, `Table_tropics_mcs_trackstats_land_ocean.html`,
    `composite_by_lifetime_{land,ocean}_{interpolated,raw}_tropics.png`, `composite_land_vs_ocean_{interpolated,raw}[_10-14h_iqr]_tropics.png`, `composite_tracks_per_bin_tropics.csv`). E3SM 100-km has 18 land / 150 ocean tracks and
    no composites (fewer than 20 tracks per bin: drawn as empty panels with a note). Notable: all models have P95 / mean PF rain rates 2-4 times the observation (the table: +150 to +330 % for 3-km and 13-km sets).
- 2026-11-16 22:35 **Round 3 finished.** Maps notebook executed with the final build (0 error cells; the five figures 22:10-22:26 in `figures_e3sm/`, viewed: bias figures 15 x 10.9 in with maps at the true shape, the vertical 3-column
  overview about square); track-stats notebook executed twice (final: IQR shading alpha 0.2, 0 error cells); sensitivity notebook rebuilt (unexecuted, stand-in test ran). README updated (Step 2c Cess2 note, Step 3 entries). Interactive node
  61451255 released. The 10 jobs 61451205-61451214 are queued/running. Open: results of the 10 jobs (check outputs, then the sensitivity notebook), the user's threshold choice, commit (nothing committed; the repo has many other uncommitted changes), the three wcmca1 folders (scrapped).
- 2026-11-16 22:35 **Sensitivity jobs: 4 of 5 ne30 jobs FAILED in the speed step (the user must decide how to continue).** State at 22:28: ne30 hr5p0 (61451210) COMPLETED (12 monthly rain maps + climo);
  ne30 hr3p0 / hr2p0 / hr1p5 / hr1p0 (61451211-14) FAILED (exit 1) after matchpf, robustmcs and mapfeature had finished (8,761 pixel files each, robust rows present, no final rows, no rain maps, no climo); the 5 ne120 jobs
  (61451205-09) are still running (matchpf 35.7 min done, in mapfeature, speed expected about 22:50). **Error (identical in all four):** `pyflextrkr/movement_speed.py` line 329 in `movement_of_feature_fft`:
  `np.apply_along_axis(np.mean, 1, np.where(result > np.quantile(result, .995)))` -> `IndexError: index -1 is out of bounds for axis 0 with size 0` when the FFT cross-correlation `result` of a feature pair
  is constant (both masked fields all zero), so no value exceeds its 99.5 % quantile: a degenerate feature the production runs (10 mm/h) did not hit; with a lower heavy_rainrate_thresh more (weaker) tracks reach the speed step.
  The speed step is NOT needed for the rain maps (rainmap reads the pixel files and the robust rows) or for the key metric. **Robust MCS counts (2010; control 10.0 = 7,498 ne120):** ne120 5.0 15,427; 3.0 25,803; 2.0 33,421;
  1.5 and 1.0 33,421 (saturated); ne30 5.0 899; 3.0 2,985; 2.0 5,613; 1.5 and 1.0 5,613 (saturated: another criterion binds below 2 mm/h).
  **Options for the user (nothing resubmitted):** (a) resubmit the failed runs with `run_speed: False`, `run_dense_netcdf: False` and `skip_completed_steps: True` (the finished steps are skipped: rainmap + climo only, about 10-15 min
  per run), the same for any ne120 run that fails in speed; (b) guard the empty case in `movement_speed.py` (a PyFLEXTRKR change: the pinned worktree is shared with production, so it would be a new pin) and re-run speed.

---

# ROUND 4 (APPROVED 2026-11-17): speed-step guard and re-submission, Cess2 to CFS, commit, memory of the stats notebook

State at the start (09:18): all 5 ne120 jobs and ne30 5.0 COMPLETED, ne30 3.0/2.0/1.5/1.0 FAILED in the speed step. User decisions: option b (guard + new pin, committed locally in PyFLEXTRKR-dev), the abort threshold is a config key speed_max_nan_pair_fraction (default 0.05), CFS archive = only the 4 replaced old dense files (the stats folder is owned by wcmca1, mode 755: stage + a bash file for wcmca1), commit the maps notebook, measure the memory of the stats notebook. Verbatim copy of the approved plan (headings shifted one level):

## SCREAM / E3SM MCS evaluation, round 4: speed-step guard and re-submission, Cess2 to CFS, commit, memory of the stats notebook

### Context

Round 3 is documented in `/global/homes/f/feng045/program/scream/docs/PLAN_scream_e3sm_mcs_evaluation.md` (progress log) and the memory note
`project_scream_e3sm_mcs_evaluation`. Today's state (2026-11-17 09:18): of the 10 sensitivity jobs **all 5 ne120 jobs and ne30 5.0 COMPLETED**
(12 monthly rain maps + climatology each); **ne30 3.0, 2.0, 1.5, 1.0 FAILED** in the speed step (`IndexError`, `movement_speed.py:329`); nothing is queued.
Your five points: (1) explain the failure and the option-b guard, (2) re-submit the failed jobs and run the sensitivity notebook afterwards, (3) copy the
swapped Cess2 stats to CFS, (4) commit the maps notebook, (5) the memory of the track-stats notebook and whether it can run on a login node.
Environment: `/global/common/software/m1867/python/pyflex26.3`, kernel `pyflex26_3`; own interactive node (account m1657) for the work; no attribution lines in commits.
**My first action after approval is to append this plan to the docs file and the memory note.**

### 1. Answers to your questions about the speed failure

**What the speed step does.** For every MCS track and every pair of consecutive pixel files it cuts the precipitation field of the track's precipitation
feature out of both files (zero outside the track mask), flips the second field and takes the FFT convolution of the two, `result` (the cross-correlation map).
The position of the peak of `result` relative to the centre of the box is the displacement of the feature between the two times: `y_lag`, `x_lag`, then distance
and speed.

**What the 99.5 % quantile is for (line 329).** Instead of the single largest pixel of `result` (`argmax`, which is noisy and jumps between equal values), the
code takes **all pixels above the 99.5 % quantile of `result`, i.e. the top 0.5 % of the map, and averages their y and x indices**: the centroid of the correlation
peak, rounded to a pixel. It is a robust, slightly smoothed peak position.

**Why it crashed.** If `result` is **constant** (typically all zeros, because one or both masked fields contain no signal: the track mask has only zero / NaN
precipitation in one of the two files), the 99.5 % quantile equals every value, **no pixel is strictly greater**, `np.where` returns empty index arrays, and
`np.apply_along_axis(np.mean, 1, <empty 2 x 0 array>)` raises `IndexError: index -1 is out of bounds for axis 0 with size 0`. One such pair kills the whole step
(Dask cancels all tasks). The ne120 runs and all production years (10 mm/h) never had such a pair; at ne30 (100 km grid, lower thresholds, many more and weaker tracks) four runs did.
I do not yet know which pair it is: finding the pair(s) and their cause (track mask without precipitation?) is the first step of the fix (listed below).

**The guard (option b), what it does and its consequence.** In `movement_of_feature_fft`, before the averaging: if no pixel exceeds the quantile, the correlation has no peak,
so **no displacement can be measured**: leave `y_lag` and `x_lag` as NaN (the value every unmeasurable track already has: tracks smaller than `min_size_thresh_for_speed`)
and go on to the next track, with a log line (file pair, track number). Consequences: (i) that pair has NaN movement and speed instead of a crash; the later filter
`filter_track_movement` already skips NaN and interpolates over them if the track has at least 3 valid speeds, otherwise the track's movement stays NaN (the existing
rule for short tracks); (ii) **normal pairs are untouched**: the original averaging expression is kept, so their lags are bit-identical (I prove it with the existing
test `tests/test_movement_speed.py` / `movement_speed_reference.py` and on real pairs); (iii) following your guardrail rule "NaN + log, not crash", the number of such pairs
is **counted and recorded** in the output (attribute of the movement variables / step log) and the step **aborts only if more than a configurable share of the measured pairs is affected**
(a real data problem, not a corner case). **The share is a config key, `speed_max_nan_pair_fraction`, default 0.05 (5 %) if the key is absent**, so every existing config keeps working
and a user can override it; the config templates document it next to `max_speed_thresh` (see below). The same function serves the dense and the row-table speed step (`movement_speed_rows.py` calls it), so one guard fixes both.

**Option b: benefit and drawback.**
- *Benefit:* fixes the cause, so the same crash cannot hit other thresholds, the ne30 / ne120 production years, other models or datasets; all 10 sensitivity runs get the
  complete output set (speed, final rows, dense netCDF, rain maps, climatology), so the chosen threshold's run is directly a usable production year and its track-statistics
  Parquet exists. Option a (skip speed) would leave those 4 runs without final statistics.
- *Drawbacks:* (1) a change in a shared module of your repo that production uses, so it needs a test and a **commit** (local, branch `perf-workflow`, unpushed); (2) the
  affected pairs get NaN speed, which is a (small, counted) loss of samples, and a silent NaN could hide a data problem, hence the count and the 5 % abort; (3) the 4 re-run
  steps run with a different code pin than the other 6 runs (next paragraph): identical for the steps involved, but it must be documented.

**What "a new pin" means.** The jobs do not import the live repo `PyFLEXTRKR-dev` (it changes whenever you work on it); they import a **frozen git worktree** of one commit,
`/pscratch/sd/f/feng045/tbpf_code_a4b8ad8` (the E3SM production and all 10 sensitivity jobs; others exist: `tbpf_code_ece05b2` = current HEAD, `tbpf_perf_code`). A fix in
`movement_speed.py` is a new commit; to run it in a job I create **a new worktree at that commit** (for example `tbpf_code_<new hash>`) and point the job's `PYTHONPATH` and run
script at it (`--code-dir` of the generator). I checked that a4b8ad8 and the current HEAD ece05b2 differ only in the track steps (calendar key), step checks and docs, not in speed,
dense netCDF, rain map or climatology code, so the new pin (ece05b2 + the guard) behaves like a4b8ad8 in the steps that will run.

### 2. Plan: re-submit the 4 failed ne30 runs (3.0, 2.0, 1.5, 1.0), then the sensitivity notebook

*(Decided by you: **option b**, including the local commit in PyFLEXTRKR-dev and the new pin.)*

1. **Find the failing pair(s)** on my interactive node: run `movement_of_feature_fft` over the 8,761 pixel-file pairs of ne30 3.0 in parallel (read-only), list the pairs and tracks that
   give an empty peak, and what the masked fields look like (all zero / NaN?). This explains the cause and gives the test case.
2. **Guard in `pyflextrkr/movement_speed.py`** as described above, the count recorded by the two drivers (`movement_speed.py` dense, `movement_speed_rows.py`), the 5 % abort; a unit test
   (a synthetic degenerate pair gives NaN lags and no exception, the count is recorded, a normal pair equals the reference; the threshold key: the default 0.05 when it is missing, an override,
   the step stops above it and not below) in `tests/test_movement_speed.py`; the whole speed test suite passes
   (pyflex26.3 + pytest); **real data check**: old code vs new code on 100 real pairs of the finished ne30 5.0 run give identical arrays.
3. **Commit** the guard in `PyFLEXTRKR-dev` (branch `perf-workflow`, local, not pushed; message without attribution lines), then
   `git worktree add /pscratch/sd/f/feng045/tbpf_code_<hash> <hash>`.
4. **Generator:** one general option `--skip-completed-steps` in `tracking_e3sm/gen_heavyrain_sensitivity.py` (writes `skip_completed_steps: True`; documented key of the template for
   "resubmit a failed job"), default off. Then
   `python tracking_e3sm/gen_heavyrain_sensitivity.py --models ne30 --thresholds 3.0 2.0 1.5 1.0 --code-dir /pscratch/sd/f/feng045/tbpf_code_<hash> --skip-completed-steps --time 01:00:00 --submit`
   (account m1657, regular, 1 node each; matchpf, robustmcs and mapfeature are skipped because their outputs are verified complete; speed, dense netCDF, rain maps and the climatology run, about 15-25 min
   each). Your approval of this plan is the approval to submit these 4 jobs.
5. **Check each run by its outputs** (not the Slurm state): 12 monthly rain maps, final rows with speed, dense final file, climatology, the `heavy_rainrate_thresh` attribute of `mcs_tracks_pf` = the key,
   the recorded number of NaN-speed pairs (and its share), robust count and total heavy rain monotonic in the threshold. At the same time I check the other 6 finished runs the same way (they ran with no guard).
6. **Execute `Notebooks/plot_mcs_heavyrain_sensitivity_e3sm.ipynb`** (kernel pyflex26_3, interactive node, about 20 min), look at every figure, and give you the summary table
   (robust MCS count, heavy rain total, mean fraction / MCS rain / cloud frequency, RMSE vs OBS per model and threshold). **You pick the threshold.**

### 3. Plan: Cess2 stats to CFS `/global/cfs/cdirs/m1867/zfeng/E3SM/SCREAMv1/cess2/global/mcs/stats`

**Where the row folders are (your question).** The four row-table folders of the re-run are in `/pscratch/sd/f/feng045/SCREAM-decadal/cess2/mcs_rerun/stats/`:
`mcs_tracks_*.rows` (identifymcs, 80 MB), `mcs_tracks_pf_*.rows` (matchpf, 333 MB), `mcs_tracks_robust_*.rows` (robustmcs, 304 MB), `mcs_tracks_final_*.rows` (speed, 312 MB), each with
`tracks.parquet`, `entries.parquet`, `fragments.parquet`, `meta.json`; plus the dense `mcs_tracks_final_*.nc` (792 MB). I swapped only the **tidy Parquet** into `cess2/stats/` last night, which
is why that folder shows no row folders. Old CFS stats folder vs new run:

| old file in CFS `stats/` | size | new equivalent |
| --- | --- | --- |
| `mcs_tracks_*.nc` (identifymcs) | 0.37 GB | `mcs_tracks_*.rows` |
| `mcs_tracks_pf_*.nc` | 0.92 GB | `mcs_tracks_pf_*.rows` |
| `mcs_tracks_robust_*.nc` | 0.76 GB | `mcs_tracks_robust_*.rows` |
| `mcs_tracks_final_*.nc` | 0.81 GB | `mcs_tracks_final_*.rows` and the new dense `mcs_tracks_final_*.nc` (0.79 GB) |
| `trackstats_*.nc` (dense, 8.0 GB), `trackstats_sparse_*.nc`, `tracknumbers_*.nc` | 8.6 GB | **none: these steps were not re-run** (the new tree only links the two small old files; the dense trackstats is not needed by the rows steps) |
| `monthly/` (39 HEALPix monthly rain maps) | | none (not re-run; unchanged) |
| not in CFS yet | | the two combined Parquet (tropics, global; 116 + 183 MB) |

**Permissions (a finding).** `.../global/mcs` and `.../global/mcs/stats` are owned by **wcmca1 with mode 755**: neither you nor I (feng045) can create, move or delete anything inside them;
only the parent `.../cess2/global/` is writable by feng045. So the swap is done in two parts, the same way as the earlier wcmca1 clean-up:
1. **Staging (me, as feng045):** copy all new outputs (about 2.0 GB: the 4 row folders, the new dense final `.nc`, the 2 Parquet) from pscratch into a staging folder
   `.../cess2/global/stats_rerun_20261116_staging/` on CFS (plain copy on the login node, explicitly authorized by you), verify every file (sizes + `cmp` of the files, `RowStats` opens the row folders).
2. **Swap (you, as wcmca1):** a bash file `/global/u1/f/feng045/program/scream/scripts/cess2_cfs_swap_wcmca1.sh` (checks `id -un` is wcmca1, `--dry-run`, log) that creates
   `stats/archive_20261116_old_dense_version/`, moves the old files into it and moves the staged files into `stats/`; it also writes a `README.md` in the archive (what, when, why, differences,
   how to restore, copied from the pscratch archive README). **Decided by you:** only the 4 replaced old dense files (`mcs_tracks_`, `mcs_tracks_pf_`, `mcs_tracks_robust_`,
   `mcs_tracks_final_` `.nc`, 2.85 GB) go into the archive; `trackstats_`, `trackstats_sparse_`, `tracknumbers_` and `monthly/` stay in `stats/` (valid inputs of the new outputs).
3. After you ran it I verify the final CFS folder (listing, sizes, open one row folder and the Parquet).

### 4. Plan: commit the maps notebook

`/global/u1/f/feng045/program/scream`, branch `main` (the repo's own practice: local commits on main, 2 ahead of origin/main; nothing is pushed): `git add` only
`Notebooks/plot_global_mcs_climo_rainmap_scream_e3sm_obs.ipynb` (new, tracked nowhere yet, 6.1 MB with its figures), check the staged diff (`git diff --cached --stat`, no stray content, nothing else staged;
the many other uncommitted files of the repo stay untouched), commit with a message in the style of the log, **no Co-Authored-By or any attribution line** (your CLAUDE.md), no push:
"Add global MCS climatology map notebook for SCREAM, E3SM and observations", body: OBS and Model - OBS maps of MCS cloud frequency, precipitation and precipitation fraction with zonal means and the OBS interannual
band; 7-source overviews; figure height solved from the measured cell width so the maps keep their shape.

### 5. Plan: memory of the track-stats notebook

I have no measurement yet (it ran 4 minutes on a 503 GB node and I did not record memory). I will **measure it**: run the notebook source as a script on my interactive node under
`/usr/bin/time -v` (peak resident memory, wall time) with a background sampler of the process memory every 2 s, matched to the notebook stages (load of the 7 Parquet files, concat, land / ocean split,
lifetime statistics, box plots, table, composites), and report the numbers, per stage and the peak. My estimate before measuring: 30.4M rows x 69 columns x 8 bytes = about 17 GB for the table,
about 35 GB at the concat, and I expect a peak of 40-60 GB.
**Login node:** `login38` has 502 GB with about 60 GB free now, and no per-user memory cgroup limit (`memory.max` is `max`), but it is shared and NERSC policy (and your CLAUDE.md) is to
keep memory- and CPU-heavy work off the login nodes; a 4-minute run at tens of GB can get killed and disturbs other users. So the answer depends on the measured peak; if it is
well below about 30 GB I would call it acceptable, otherwise use the interactive QOS (it started in seconds each time today). **If the peak is too high for you I can make the load read only the
columns the analyses use (about 27 of 69), which should cut the peak by more than half**; I will propose that after the measurement, I will not change the notebook without your OK.

**The threshold key `speed_max_nan_pair_fraction`** (read with `config.get("speed_max_nan_pair_fraction", 0.05)` by both speed drivers; a value outside 0-1 is an error at start-up of the step).
Documented in the config files next to `max_speed_thresh` with this comment (final wording in the file):

```yaml
speed_max_nan_pair_fraction: 0.05  # [fraction 0-1] largest share of the measured feature pairs that may have NO measurable movement before the speed step stops with an error.
                                   # A pair has none when the cross-correlation of the two masked precipitation fields has no peak (a field is all zero / NaN inside the track mask).
                                   # Such pairs get NaN movement (like tracks that are too small) and are counted in the output; a few are a corner case, a large share means
                                   # the pixel files or the precipitation field are inconsistent. 0: stop at the first such pair; 1: never stop. Default (key absent): 0.05
```

It goes into the two templates of the unified workflow (`config/config_mcs_tbpf_e3sm_0p1deg_template.yml`, `config/config_mcs_tbpf_imergv7_global_template.yml`), into the Cess2 rows config
`scream/tracking/config_mcs_tbpf_SCREAMv1-Cess2_rows.yml`, and in the speed-step paragraph of `docs/tbpf_mcs_workflow.md`; the other ~50 configs use the default (nothing to edit). The 4 re-run sensitivity configs
come from the campaign config and use the default.

### Order of work

0. Docs + memory sync. 1. Interactive node (1 node, m1657, 4 h). 2. Commit the maps notebook (login node, minutes). 3. Cess2 staging copy to CFS (login node) and the wcmca1 bash file. 4. Failing-pair scan, guard,
tests, commit, new pin, generator option, submit the 4 jobs (about 1.5 h). 5. While they run: the memory measurement of the stats notebook. 6. Check the 10 runs, execute the sensitivity
notebook, summary table. 7. README / docs / memory; release the node.

### Verification

- Guard: test suite green; old vs new identical on 100 real pairs of ne30 5.0; the failing pair(s) of ne30 3.0 give NaN and are counted; the 4 re-run jobs complete with the recorded count below 5 %.
- Re-run outputs: the checks of step 5 above; all 10 runs listed in one table (12 maps, climo, final rows, attribute = key).
- CFS: staged copies identical to pscratch (`cmp`), the bash file passes `bash -n` and its dry run refuses to run as feng045 and prints the plan; after your run the folder listing matches the plan.
- Commit: `git show --stat` lists only the notebook; `git status` shows the other files unchanged.
- Memory: the report has the peak, the wall time and the per-stage numbers from the log of the sampler.

### Risks and what I will state

- The guard turns a crash into NaN speeds for the degenerate pairs; if the scan shows many of them (more than a few percent) I stop and report instead of hiding a data problem.
- The 4 re-run steps use pin ece05b2 + guard, the other 6 runs a4b8ad8: identical code in the steps that matter (diff checked), documented in the docs file.
- CFS `stats` cannot be written by feng045: the final swap depends on you running the wcmca1 script.
- The notebook commit adds a 6 MB file with embedded figures to the repo history.

### Files

New: the guard test, `scripts/cess2_cfs_swap_wcmca1.sh`, the staging folder and the archive README on CFS / pscratch, a new pinned worktree. Modified: `PyFLEXTRKR-dev/pyflextrkr/movement_speed.py` and
`movement_speed_rows.py`, the two config templates and `docs/tbpf_mcs_workflow.md` (committed locally in one commit), `tests/test_movement_speed.py`, `scream/tracking_e3sm/gen_heavyrain_sensitivity.py` (the `--skip-completed-steps` option), the docs file, the memory note, README.
Untouched: production data, the old Cess2 tree, the three wcmca1 folders, everything else of the repos.
- 2026-11-17 09:40 round 4 approved; progress entries below.
- 2026-11-17 09:45 round 4, steps done: (1) interactive node 61481099 (nid200073, m1657, 4 h, until ~13:40); (2) maps notebook committed on scream main, 93681fa (only that file, no attribution, not pushed);
  (3) Cess2 outputs staged on CFS `.../cess2/global/stats_rerun_20261116_staging/` (stats/: 4 `.rows` folders + new dense final `.nc`; parquet/: tropics + global), 19 files, byte-compared with the pscratch
  originals on the node = identical; permissions g+rw, o+r (setgid directories, group m1867); `scripts/cess2_cfs_swap_wcmca1.sh` written (refuses other users than wcmca1, `--dry-run`, size check of the 15 staged
  files, archives only the 4 old dense `.nc` into `stats/archive_20261116_old_dense_version/` + README + log, moves the staged files into `stats/`); WAITING for the user to run it as wcmca1.
- 2026-11-17 09:45 FINDING that corrects the explanation of the speed failure: the traceback of the crash is in `np.quantile` (`arr[-1, ...]` of an EMPTY array), i.e. `result` has size 0 = the bounding box of a track has no row or
  no column (`get_bounding_box_for_fft` returns the INCLUSIVE last row/column, `field[ymin:ymax, xmin:xmax]` drops it: a track that occupies one row or one column in both files gives an empty box). The CONSTANT-result case does not crash:
  np.where is empty, the mean of an empty slice is NaN and `.astype('int')` makes a huge negative integer (RuntimeWarning "invalid value encountered in cast"; 21 such warnings in the failed ne3 3.0 log before it stopped); the
  huge lag then becomes a huge speed that max_speed_thresh removes later. So the guard must cover both cases. Scan of ne30 3.0 (all 8,760 pairs) running: scripts in `.claude_tmp_verify/scream_e3sm/scan_speed_pairs.py`.
- 2026-11-17 10:10 round 4, speed guard DONE. **Scan of ne30 3.0** (all 8,760 pairs, 127,748 measured feature pairs, `scan_speed_pairs.py`, read-only): 40 degenerate pairs = 0.031 %: (A) 1 EMPTY correlation map = track 1649 in row 0 of the
  grid in `mcstrack_20100719_140000 -> 150000` (shape [0, 26]; this is the crash); (B) 39 TIED maximum: real fields (14-423 non-zero pixels, sums 14-470) but no pixel strictly above the 99.5 % quantile of the correlation map (the maximum is a plateau,
  the field of ne30 is constant over blocks of pixels): np.where is empty, mean of empty = NaN, `.astype('int')` = huge integer (RuntimeWarning), huge lag -> huge speed -> removed by `max_speed_thresh` and INTERPOLATED (the filter interpolates values above the
  threshold, but leaves NaN as NaN). B never crashes, it is silent and exists in every completed run. **Guard (PyFLEXTRKR-dev 80438a4, local, unpushed, perf-workflow):** A -> NaN lags + log + count; B -> values UNCHANGED (bit-identical to the old code,
  only a log line with pair and track), because making B NaN or measuring the plateau would change completed outputs; counters `speed_pairs_measured` / `speed_pairs_without_movement` as attributes of the final rows and dense file; abort if
  NaN pairs > `speed_max_nan_pair_fraction` (default 0.05) x measured pairs, value outside 0-1 stops at the start; the key is documented in the 2 templates, the Cess2 rows config and `docs/tbpf_mcs_workflow.md`. Tests: 58 speed tests (dense + rows),
  35 step/unified/import/docs tests pass. **Real data, old pin a4b8ad8 vs new code:** 100 pairs spread over ne30 5.0: all arrays identical; the 40 degenerate pairs of 3.0: 39 identical, the crashing pair gives NaN for track 1649 and valid lags for
  the 13 other tracks. Open question for the user: (B) fallback to the plateau centroid (`>=`) instead of the huge lag, which would change completed runs.
  Pinned worktree `/pscratch/sd/f/feng045/tbpf_code_80438a4` (differs from a4b8ad8 only in the calendar key, the step checks, the track steps and the guard: none runs in matchpf ... rainmap with the config of these runs).
  Generator: `--skip-completed-steps` added. **4 ne30 jobs (3.0/2.0/1.5/1.0) submitted 10:00: 61481773-76** (m1657, regular, 1 node, 1 h; matchpf/robustmcs/mapfeature skipped by their output checks, speed ... rainmap run; the ne30 5.0 run took
  3.3 min for speed, 4.5 min for the rain maps).
- 2026-11-17 10:20 round 4, MEMORY of `plot_tropical_mcs_trackstats_all_sources.ipynb` MEASURED (source run as a script on the node under `/usr/bin/time -v`, RSS at every cell + a 2-s sampler; scripts `nb_trackstats_mem.py`,
  `run_mem.sh`, `mem_run.log`, `mem_samples.csv`, `mem_time_v.txt` in `.claude_tmp_verify/scream_e3sm/`; figures of the test went to `SCREAM-decadal/_mem_test_figs/`, not to the real figure folder): **peak 38.2 GB resident (`Maximum resident set size`
  38,168,588 kB), reached while the 7 Parquet files are read and concatenated (t = 3 - 41 s; 30.4M rows x 69 columns); then 18 - 22 GB after the intermediate frames are freed, 28 GB with the lifetime-statistics tables (t = 60 s), 30 - 32 GB during
  the composites and plots, 32 GB at the end; wall time 2 min 7 s (the notebook took about 4 min in a Jupyter kernel), 1 core (92 % CPU), exit 0, no error.** A kernel keeps the inline figures too, so expect a few GB more. Login node (login38, 502 GB,
  about 61 GB free, no per-user memory limit): not recommended, 38 GB would be 60 % of the free memory of a shared node (and NERSC policy keeps memory-heavy work off the login nodes). **Lean load measured (not applied to the notebook):** reading only the 25 columns
  that the source names (of 69) gives 6.6 GB in memory and a peak of 14.0 GB for the load (18 s) instead of 38 GB.
- 2026-11-17 10:50 round 4, SENSITIVITY RUNS CHECKED and NOTEBOOK EXECUTED. The 4 resubmitted ne30 jobs (61481773-76) ran speed ... rainmap in 11-15 min with the guard: feature pairs without a measurable movement 1 of 127,748 (3.0), 2 of 186,246 (2.0, 1.5, 1.0);
  3.0, 1.5, 1.0 COMPLETED; **2.0: all six steps OK (ledger), but the climatology script that the Slurm script runs afterwards HUNG** (futex wait, 258 threads, 0.3 % CPU, header-only output of 27 kB; the same script ran cleanly in the other 9 runs: the xarray /
  Dask lock hang of [[reference_xarray_lock_leak_dask]] is the likely cause, not investigated). I did NOT scancel (needs the user's approval): the job will end at its 1 h limit (about 10:57) as TIMEOUT; its climatology I recomputed with the same script into a temp
  folder and moved into place by atomic rename (135.6 MB, same variables / sizes as 1.0, the mean of `precipitation` equal to the 1.0 run: 2.5954). Output check of all 10 runs (`check_sens_runs.py`, by outputs: 12 rain maps, climatology opens with valid
  `mcs_precipitation`, final rows + dense file with the same tracks, `heavy_rainrate_thresh` of matchpf and robustmcs tables == key, pixel files 8,761 == cloudid files, speed counters): **all runs complete and consistent**, robust MCS and heavy-rain total
  non-decreasing with a lower threshold. Robust MCS ne120 15,427 / 25,803 / 33,421 / 33,421 / 33,421 and ne30 899 / 2,985 / 5,613 / 5,613 / 5,613 for 5.0 / 3.0 / 2.0 / 1.5 / 1.0 (production 10.0: 7,498 and 91): **identical MCS sets for 2.0, 1.5 and 1.0**, because the
  PF is made of pixels >= `PF_rainrate_thresh` = 2.0 mm/h, so any `heavy_rainrate_thresh` <= 2.0 is always met by the maximum PF rain rate (only the heavy-rain sums differ). `plot_mcs_heavyrain_sensitivity_e3sm.ipynb` executed (16 min, 0 error cells), 8 files in
  `SCREAM-decadal/figures_e3sm/heavyrain_sensitivity/`. Summary (ANN 2010; OBS fraction 50.5 %, cloud frequency 3.69 %, MCS precipitation 1.54 mm/day): ne120 fraction 17.9 / 24.2 / 27.9 / 29.7 / 29.7 / 29.7 %, RMSE 32.8 / 29.1 / 26.5 / 25.1 / 25.1 / 25.1;
  ne30 fraction 3.9 / 13.2 / 22.0 / 26.0 / 26.0 / 26.0 %, RMSE 43.5 / 37.1 / 31.3 / 28.5 / 28.5 / 28.5 (10 / 5 / 3 / 2 / 1.5 / 1 mm/h). Cosmetic issue left: in the zonal panel of the fraction and cloud-frequency figures the legend box covers the top of the
  OBS line near the equator (`zonal_headroom` 0.9 is too small there); a re-run takes 16 min. The user picks the threshold.

---

# ROUND 5 (APPROVED 2026-11-17): E3SM production at heavy_rainrate_thresh 2.0 (15 years), tied-maximum NaN, notebooks re-run

State at the start (12:50): round 4 finished; the user chose 2.0 mm/h for ne30 and ne120 (MCS sets identical for 2.0, 1.5, 1.0), verified the Cess2 swap request (CFS checked read-only: 19 files same size as pscratch, archive + log present), asked about the tied-maximum lag (decision: NaN + log, before the production runs) and chose the new tree mcs_tbpf_hr2p0 beside mcs_tbpf. Verbatim copy of the approved plan (headings shifted one level):

## Round 5: E3SM production at heavy_rainrate_thresh 2.0 (15 years), tied-maximum NaN, notebooks re-run

### Context

Round 4 is finished (docs file `/global/homes/f/feng045/program/scream/docs/PLAN_scream_e3sm_mcs_evaluation.md`, memory note `project_scream_e3sm_mcs_evaluation`):
the speed guard is committed (PyFLEXTRKR-dev `80438a4`, local), all 10 sensitivity runs are complete and checked, and the sensitivity notebook was executed.
The MCS sets are identical for 2.0, 1.5 and 1.0 mm/h (the precipitation-feature threshold is 2.0), so you chose **2.0 for ne30 and ne120**.
This round (1) re-runs the production from matchpf to trackpcp with 2.0 for every production year (ne120 2009-2011, ne30 2009-2020 = 15 years), (2) verified your
Cess2 swap on CFS, (3) answers the tied-maximum question and (as you decided) sets those pairs to NaN before the production runs, (4) re-runs the notebooks afterwards.
Environment: `/global/common/software/m1867/python/pyflex26.3`, kernel `pyflex26_3`; own interactive node (account m1657) for the checks; no attribution lines in commits.
**My first action after approval is to append this plan to the docs file and note it in the memory note.**

### 0. Your item 3: CFS folder verified (read-only, done)

`/global/cfs/cdirs/m1867/zfeng/E3SM/SCREAMv1/cess2/global/mcs/stats` after your run (12:34): the 4 new row folders (`mcs_tracks_`, `_pf_`, `_robust_`, `_final_` `*.rows`, each with tracks / entries / fragments .parquet + meta.json),
the new dense `mcs_tracks_final_*.nc` (830,328,711 B) and the two combined Parquet (tropics 121.5 MB, global 191.3 MB) are there; **all 19 files have the same size as the pscratch originals**
(which were byte-compared with the staged copies earlier). The archive `archive_20261116_old_dense_version/` holds the 4 old dense files (sizes equal to the old listing: 370,735,555 / 918,224,479 / 756,265,651 / 807,676,621 B), `README.md` and
`swap_20261116.log` (clean: steps 2-4, "staging folder removed", DONE 12:34:38). `trackstats_*`, `trackstats_sparse_*`, `tracknumbers_*` and `monthly/` are untouched; the staging folder is gone.
Remaining (needs a node, read-only): `cmp` of the 19 files against pscratch, open one row folder with `RowStats` and one Parquet from CFS. Small finding: the new files are owned by feng045 (group m1867, g+rw, o+r), the archive folder is mode 2770 (group only).

### 1. Your item 4: tied-maximum lag, and the change (decided: NaN + log)

**Is it easy to detect? Yes, exactly and for free.** It is the condition `peak[0].size == 0` (no pixel strictly above the 99.5 % quantile of the correlation map) that I added in `movement_of_feature_fft` to log the case; the same event is the
numpy "invalid value encountered in cast" warning. It needs no threshold or tuning. Old outputs also carry a fingerprint: a tied pair has `movement_theta == 45.0` exactly and `movement_distance_x == movement_distance_y`.
**How common:** the 10 mm/h production had none (0 warnings in all 6 production stats logs checked); in the 2.0 / 1.5 / 1.0 mm/h runs: ne30 92 of 186,246 measured pairs (0.05 %), ne120 about 27 of about 614,000 (0.004 %), ne30 3.0: 39 (0.03 %).
**Cause:** the E3SM fields are constant over blocks of pixels (regridded from 25 / 100 km cells), so the correlation of two small boxes has a plateau at its maximum (at least two tied values) and "strictly above the quantile" selects nothing.
**What a tied pair does today:** mean of an empty selection = NaN, `.astype('int')` makes -9.2e18, so x and y lag are equal and huge: speed is huge, `filter_track_movement` interpolates the speed and distance from the neighbours (the pair
looks measured) while the direction stays at exactly 45 degrees and the x / y components are equal (invented numbers).
**Would NaN alleviate it? Yes.** The interpolation inputs do not change (the huge value was excluded from them by `max_speed_thresh` anyway), but that pair then shows a gap (speed, distance, direction and both components NaN)
instead of an interpolated speed with a made-up direction. Costs: a tiny gap; the entries of the sensitivity runs and the old Cess2 / IMERG outputs keep the old behavior (they differ from the new production only in those 0.05 % entries;
speed is not used by the sensitivity notebook).

**Change (PyFLEXTRKR-dev, one new local commit on `perf-workflow`, no attribution):**
- `pyflextrkr/movement_speed.py` `movement_of_feature_fft`: in the block `if peak[0].size == 0:` log (pair, track) and `continue` (lags stay NaN), as for the empty bounding box; docstrings of the function and of `count_unmeasurable_pairs` say "empty box or tied maximum".
  The NaN lags are already counted by `count_unmeasurable_pairs` (`speed_pairs_without_movement`) and covered by `speed_max_nan_pair_fraction` (0.05; the ne30 2.0 share is 0.05 %), so the abort rule needs no change.
- Config text of the key (two templates, `scream/tracking/config_mcs_tbpf_SCREAMv1-Cess2_rows.yml`) and the row of `docs/tbpf_mcs_workflow.md`: "a pair has none when the track occupies a single row or column, or when the maximum of the correlation is tied"; remove the sentence that says the tied case is only logged.
- `tests/test_movement_speed.py`: flip `test_a_tied_maximum_keeps_the_old_values_and_is_logged` (now: NaN lags, other tracks equal, counted, logged; the frozen reference still gives the huge value, kept as a documented difference);
  dense and rows end-to-end test with a tied pair.
- Real data: `speed_pairs_old_new.py` / `compare_speed_old_new.py` (in `.claude_tmp_verify/scream_e3sm/`): 100 ne30 5.0 pairs identical; the 92 tied pairs of ne30 2.0 + the 40 of ne30 3.0 now NaN, every other track of those pairs identical; speed suites + related suites pass.
- New pin: `git worktree add --detach /pscratch/sd/f/feng045/tbpf_code_<hash> <hash>` (used by the 15 production jobs).

### 2. Your item 1: production at 2.0 mm/h, matchpf to trackpcp

**Where the outputs go (your choice: new tree beside the 10 mm/h production, which stays untouched as the baseline):**
```
/pscratch/sd/f/feng045/E3SM_polun/<ne120|ne30>_remap_0.1deg/mcs_tbpf_hr2p0/
    <year>/tracking                      link to ../../mcs_tbpf/<year>/tracking (cloudid + track files, read only)
    <year>/stats/mcs_tracks_<dates>.rows link to the production identifymcs output (the only stats input of matchpf)
    <year>/stats/                        NEW: mcs_tracks_{pf,robust,final}_<dates>.rows, mcs_tracks_final_<dates>.nc, monthly/mcs_rainmap_YYYYMM.nc,
                                         trackpcp_metrics_*.parquet, trackpcp_pixels_*.parquet, trackpcp_grid.nc
    <year>/mcstracking/                  NEW: 8,760 pixel files (about 110 GB per year, kept: the rain maps and trackpcp need them)
    <year>/profile/                      step ledger (wall time, memory) and Dask reports
    campaign_<year>/                     config_*.yml, slurm_*.sh, logs/ (one job per year)
    stats/                               cross-year: links to the 3-12 yearly mcs_tracks_final_*.rows + the combined Parquet (tropics, global)
    monthly/                             links to the yearly rain maps + the multi-year climatology
```
Same names as `mcs_tbpf`, so the notebooks only change the root. Sizes: about 110 GB and 8,900 files per year, **1.65 TB and 134,000 files for the 15 years**; pscratch is at 66.6 of 100 TB and 4.84M of 10M files now.

**Generator:** extend `scream/tracking_e3sm/gen_heavyrain_sensitivity.py` (the 10-run generator with the proven config logic: copy of the production stats config of the year with only the listed lines changed) with `--production` and `--years`:
- run root `<base>_hr<tag>/<year>/`, config + Slurm script + logs in `<base>_hr<tag>/campaign_<year>/`, job name `hr2p0_<model>_<year>`;
- steps `matchpf, robustmcs, mapfeature, speed, dense_netcdf, rainmap` **plus `trackpcp`** (the sensitivity runs left it off; its `trackpcp_*` keys come from the production config);
- `heavy_rainrate_thresh: 2.0`, `run_parallel: 1` (one-node LocalCluster, the pattern of the sensitivity jobs), `skip_completed_steps: False`, `step_profile_dir`, `grid_area_file`;
- **no per-year climatology in the Slurm script** (one script run hung on 2026-11-17; the production climatology is a multi-year file made once afterwards, below);
- the production config of each year is found by the existing glob `campaign_<year>/*_stats<year>01_<year>12.yml` (it exists for all 15 years, ne120 2009 included); a missing file stops the generator.
- New small script `tracking_e3sm/finalize_production_tree.py` (links `stats/` and `monthly/` across years, same layout as `mcs_tbpf`), run after the jobs.
Commands (pinned worktree of section 1), first without `--submit` to print the plan and the pscratch quota, then with it:
`python tracking_e3sm/gen_heavyrain_sensitivity.py --production --models ne120 --years 2009 2010 2011 --thresholds 2.0 --code-dir <worktree> --time 03:00:00 [--submit]` and the same for `--models ne30 --years 2009 ... 2020`.

**Jobs and time:** 15 jobs, 1 node each, account m1657, regular, 3 h limit, all independent. Measured step times at 2.0 (1 node): ne120 matchpf 36 + mapfeature 26 + speed 12.5 + dense 2 + rainmap 5 min and trackpcp about 10 min (it ran 10 min in the 4-node job with 0.9 effective cores, main-process peak 16 GB) = about 1.5 h;
ne30 about 45 min (matchpf 10 + mapfeature 20 + speed 3 + rainmap 5 + trackpcp 2). About 16 node-hours in total; if the queue starts them together everything is done in 1.5 to 2 h. **Your approval of this plan is the approval to submit these 15 jobs.**

### 3. After the runs (notebooks and docs)

1. **Check every year by its outputs** (`check_sens_runs.py` adapted to the production tree): 12 rain maps, final rows + dense file with the same tracks, trackpcp files, `heavy_rainrate_thresh` = 2.0 in the matchpf and robustmcs tables,
   pixel files = cloudid files, speed counters (`speed_pairs_without_movement` share far below 5 %), and for 2010 **equality with the sensitivity 2.0 runs** (robust MCS ne120 33,421 and ne30 5,613; rain maps and row tables identical, the final movement
   entries differ only at the tied pairs) with `PyFLEXTRKR-dev/tests/tbpf_compare.py` / `compare_control_parallel.py` (48 processes, on the node).
2. `finalize_production_tree.py`, then on the node: multi-year climatology with `scripts/calc_mcs_rainmap_climo_from_monthly.py --indir <root>/monthly --start-date 2009-01 --end-date 2011-12` (ne120) and `2009-01 .. 2020-12` (ne30), and the tidy Parquet with
   `scripts/combine_filter_mcs_trackstats.py --indir <root>/stats --pattern 'mcs_tracks_final_*.rows' --region tropics|global --outdir <root>/stats`.
3. **Notebooks** (sources and builder in `.claude_tmp_verify/scream_e3sm/`: edit the source, `build_notebooks.py`, execute with `$JUPYTER nbconvert --execute --inplace` kernel `pyflex26_3` on the node, 0 error cells, look at every figure):
   - `plot_global_mcs_climo_rainmap_scream_e3sm_obs.ipynb` (maps): the climatology paths of `e3sm25` / `e3sm100` -> `mcs_tbpf_hr2p0/monthly/`; text that quotes the old E3SM numbers is updated.
   - `plot_tropical_mcs_trackstats_all_sources.ipynb` (track statistics): `combined_dir` of `e3sm25` / `e3sm100` -> `mcs_tbpf_hr2p0/stats`; the Cess2 `combined_dir` -> the CFS folder you just swapped (the pscratch copy can be purged, the other SCREAM sources are on CFS).
   - `plot_mcs_heavyrain_sensitivity_e3sm.ipynb`: **not changed** (its baseline is the 10 mm/h `mcs_tbpf` tree, which stays; the 2.0 point is the sensitivity run, identical to the new production).
4. README (E3SM sections, key facts: the 18.5 % / 3.3 % MCS-precipitation fractions become the 2.0 values), docs progress log, memory note. Release the node. Commits only if you ask (the scream files of rounds 4 and 5 are still uncommitted).

### Order of work

0. Docs + memory sync. 1. Interactive node (1 node, m1657, 4 h). 2. Tied-maximum change, tests, real-pair comparison, commit, new pin (about 40 min). 3. Generator `--production` / `--years`, finalize script, dry run for all 15 years,
`diff` of one generated config against its production config (only the listed lines differ), then submit the 15 jobs. 4. While they run: CFS `cmp` check of the Cess2 files (node), monitor the jobs (a log whose last line repeats for 10 min needs a look; I ask before any `scancel`).
5. Outputs check, finalize, climatology, Parquet, notebooks, docs, node release.

### Verification

- Tied maximum: speed suites green; 100 real ne30 5.0 pairs identical old vs new; tied pairs of ne30 2.0 / 3.0 give NaN, all other tracks identical; counters in the job logs.
- Generator: dry run for 15 years prints 15 configs; a `diff` against the production stats config of 2010 shows only `heavy_rainrate_thresh`, `root_path`, `step_profile_dir`, the `run_*` flags, `run_parallel`, `skip_completed_steps`, `grid_area_file`.
- Production: the per-year output check, 2010 equal to the sensitivity 2.0 runs, `heavy_rainrate_thresh` = 2.0 everywhere, robust MCS counts per year listed in one table.
- Notebooks: executed with 0 error cells, figures viewed, E3SM sources point at `mcs_tbpf_hr2p0` (checked in the printed load lines: rows, tracks, file names).
- CFS: `cmp` and an opened row folder / Parquet (section 0).

### Risks

- **trackpcp was never run in a derived tree** (the sensitivity runs left it off) and 1-node memory of its main process is about 16 GB (fine). If it fails, the earlier steps are kept and I resubmit the year with `skip_completed_steps: True` (the generator option exists).
- Two silent Dask hangs are known (xarray lock leak; trackstats gather loop). The jobs have a 3 h limit; the per-year climatology script (the one that hung on 2026-11-17) is no longer part of them.
- m1657 node-hours: about 16 are needed; I could not read the balance (no `sbank` here), a refusal shows at `sbatch`.
- The 15 jobs use the new pin, the 10 mm/h tree used `a4b8ad8`: the steps matchpf to rainmap are identical for pairs that do not tie (proved on real pairs), the 2.0 results of the sensitivity runs agree with the first production years.
- pscratch is not backed up and purges inactive files; the new tree is not copied to CFS unless you ask. The 10 mm/h tree stays (about 1.6 TB of pixel files) until you say otherwise.

### Files

New: `scream/tracking_e3sm/finalize_production_tree.py`, a new worktree `tbpf_code_<hash>`, the production tree `mcs_tbpf_hr2p0` (both models), one new PyFLEXTRKR-dev commit. Modified: `PyFLEXTRKR-dev/pyflextrkr/movement_speed.py`, `tests/test_movement_speed.py` (+ rows test),
`config/config_mcs_tbpf_e3sm_0p1deg_template.yml`, `config/config_mcs_tbpf_imergv7_global_template.yml`, `docs/tbpf_mcs_workflow.md`, `scream/tracking/config_mcs_tbpf_SCREAMv1-Cess2_rows.yml`, `scream/tracking_e3sm/gen_heavyrain_sensitivity.py`,
the two notebook sources + their rebuilt notebooks, `scream/README.md`, the docs file, the memory note. Untouched: the 10 mm/h production, the sensitivity runs, the Cess2 CFS folder, everything pushed.
- 2026-11-17 12:50 round 5 approved; progress entries below.
- 2026-11-17 13:15 round 5, TIED MAXIMUM DONE + 15 PRODUCTION JOBS SUBMITTED. Tied maximum -> NaN (+ log + count): PyFLEXTRKR-dev commit **38ae5d1** (local, unpushed), pinned worktree `/pscratch/sd/f/feng045/tbpf_code_38ae5d1`; tests 96 passed
  (speed dense + rows, step checks, unified, imports, docs); real pairs, old pin a4b8ad8 vs new code (`speed_pairs_old_new.py`, `compare_speed_old_new2.py`): ne30 5.0 100 pairs: 566 tracks identical, 0 different; ne30 3.0 40 degenerate pairs: 598 identical, 40 -> NaN
  (39 tied + 1 empty box), 0 different; ne30 2.0 93 pairs: 1,968 identical, 94 -> NaN (92 tied + 2 empty), 0 different. Generator `tracking_e3sm/gen_heavyrain_sensitivity.py` got `--production` and `--years` (folders `<model>_remap_0.1deg/mcs_tbpf_hr<tag>/<year>` and
  `campaign_<year>`, steps matchpf..trackpcp, no per-year climatology, `--thresholds` required; run_dense_netcdf is added when a config lacks it: the ne120 2009 config is older). Dry run for all 15 years, `diff` of three generated configs (ne120 2009, 2010, ne30 2012) against the
  production configs: only run_trackstats / run_identifymcs False, run_parallel 1, root_path, heavy_rainrate_thresh 2.0, step_profile_dir, grid_area_file (+ run_dense_netcdf for 2009). **Submitted 13:12: ne120 2009-2011 = 61494694-96, ne30 2009-2020 = 61494697-708**
  (m1657, regular, 1 node, 3 h; ledger `<model>_remap_0.1deg/mcs_tbpf_hr2p0/submissions.jsonl`; expected about 1.5 h for ne120, 45 min for ne30).
- 2026-11-17 14:10 round 5: Cess2 CFS files byte-compared on the node (`cmp_cess2_cfs.sh`): 19 of 19 IDENTICAL to the pscratch originals (item 3 fully verified). New: `tracking_e3sm/finalize_production_tree.py`, README paragraph, notebook sources edited (`nb_maps.py` climo paths and `nb_trackstats.py` combined_dir -> `mcs_tbpf_hr2p0`; Cess2 -> CFS), `check_production.py`.
  The 15 production jobs were still PENDING (reason Priority) 55 min after submission; waiting for them (watcher armed).

---

# ROUND 5b (APPROVED 2026-11-18): 2.0 mm/h production checked, notebooks switched to it, OBS fraction band made consistent

State at the start (11:10): the 15 hr2p0 production jobs of round 5 are COMPLETED (ledgers and logs clean). The user asked to check them, to re-run the notebooks with E3SM ne120 / ne30 switched to the 2.0 outputs, and to explain the OBS zonal IQR band (why the fraction band is below the line). Decisions: precipitation-weight the fraction band; re-run the sensitivity notebook too. Verbatim copy of the approved plan (headings shifted one level):

## Round 5b: 2.0 mm/h production checked, notebooks switched to it, OBS fraction band made consistent

### Context

Round 5 (`/global/homes/f/feng045/program/scream/docs/PLAN_scream_e3sm_mcs_evaluation.md`, memory note `project_scream_e3sm_mcs_evaluation`) submitted the 15 production jobs at heavy_rainrate_thresh 2.0
(ne120 2009-2011 = 61494694-96, ne30 2009-2020 = 61494697-708, output tree `<e3sm_root>/<model>_remap_0.1deg/mcs_tbpf_hr2p0/`, pinned code `tbpf_code_38ae5d1`). You say they are done and ask for three things:
(1) check their completion, (2) re-run the notebooks with the E3SM ne120 and ne30 data switched to the 2.0 outputs (I read "the sensitivity jobs / outputs" as these 15 `hr2p0` jobs: they are the only ones with the
multi-year coverage that the notebooks use; the one-year sensitivity runs stay as they are), (3) explain the IQR shading of the zonal-mean plot and why the fraction band lies below the line.
Environment: `/global/common/software/m1867/python/pyflex26.3`, kernel `pyflex26_3`, own interactive node (the one of round 5 has ended); no attribution lines in commits.
**My first action after approval is to append this plan to the docs file and update the memory note (round 5 result + this round).**

### 1. Completion status (checked read-only, done)

- **Slurm:** all 15 jobs COMPLETED, exit 0 (ne120 1 h 50 min each, ne30 57-60 min each; they started 15:40 on 17 Nov, the last ended 05:28 on 18 Nov).
- **Step ledgers** (`<year>/profile/step_ledger.jsonl`): every step `ok` in all 15 years (matchpf, robustmcs, mapfeature, speed, dense_netcdf, rainmap, trackpcp). Longer than estimated: trackpcp 28 min (ne120) and 16 min (ne30) on one node.
- **Logs:** no failed step in any log; the only `Traceback` lines (ne120 2011, 2) are the Dask nanny / tornado noise of the shutdown after the last step, as in the earlier runs.
- **Speed counters** (new attributes): pairs without a measurable movement (empty box or tied maximum) ne120 27-43 of about 610,000 (0.004-0.007 %), ne30 74-113 of about 185,000 (0.04-0.06 %): far below the 5 % limit.
- **Outputs per year:** 12 monthly rain maps, the final row folder and the dense `.nc`, the three trackpcp files, `heavy_rainrate_thresh` = 2.0 in the matchpf and robustmcs tables.
- **Robust MCS tracks per year:** ne120 33,009 / 33,421 / 33,450 (2009-11); ne30 5,557 5,613 5,792 5,477 5,527 5,549 5,661 5,556 5,759 5,667 5,549 5,473 (2009-20). **2010 equals the sensitivity 2.0 runs** (33,421 and 5,613).
- **Still to do on a node (content level):** `check_production.py` (pixel files = cloudid files, dense tracks = row tracks, no `movement_theta == 45.0` fingerprint of the old tied-maximum garbage) and a content comparison of 2010 with the sensitivity 2.0 run (rain maps and row tables identical; the final movement entries differ only at the NaN pairs).
- Unrelated: the `idl_mcsidc_monthly` array in the queue is not mine.

### 2. Answer to your question 3: the IQR band of the zonal-mean plot (to be given in the reply)

**How it is computed** (`obs_zonal_band`, method `cell_iqr`, in the maps notebook): for each of the 11 OBS years (2007-2017) the annual field is made exactly like the OBS field (12 monthly fields, equal month weights; the fraction as the ratio of the
year's MCS and total precipitation in every cell). Then, in **every 0.1 degree cell, the 25th and the 75th percentile across the 11 years** (vectorised `percentiles_over_years`, numpy linear interpolation). Finally those two percentile **fields** are averaged in 2 degree latitude bins,
cos(latitude)-weighted, over the cells valid in OBS (4,180,223 cells), with `zonal_mean_cosw(da, None, ...)`, i.e. a **plain area-weighted average**. So it is "the typical local interannual IQR", not the IQR of the zonal mean (that one, `zonal_iqr`, is only 2-10 % of the line).
**Why the fraction band is low but the other two straddle the line** (measured from the cached band file `obs_zonal_annual_2007_2017_ANN.nc` and the OBS climatology, same 4,180,223 valid cells):
- The **line** for the fraction is a **ratio of sums** (`zonal_mean_cosw` with a denominator): sum of MCS precipitation / sum of total precipitation, i.e. a **precipitation-weighted** mean of the cell fractions, dominated by the rainy cells (about 62-64 % near the equator).
- The **band** averages the cell percentiles with plain **area weights**: dry or weakly raining cells (low fractions of 30-45 %, noisy) count as much as the rainy ones. The area-weighted mean of the cell fractions lies **inside the band in 60 of 60 bins** (it is 6.1 % below the line on average, 16 % at 15S, e.g. 41 against 57 %), while the line is above the band in 35 of 60 bins and never below.
- **Cloud frequency and MCS precipitation have no denominator**: line and band are both plain area-weighted averages of the same cells, so the line lies inside the band in 60 of 60 bins (at 0.52-0.56 of the band width, a little above the middle because the mean exceeds the median).
So it is a mismatch of two averages for a ratio variable, not an interannual-variability effect.

### 3. Changes (decided by you: precipitation-weight the fraction band; re-run the sensitivity notebook too)

1. **Band for variables with a denominator** (`nb_maps_part1.py`, function `obs_zonal_band`, source in `/global/homes/f/feng045/.claude_tmp_verify/scream_e3sm/`): keep the yearly denominator fields, take their mean over the years as the weight `W` (= the climatological total precipitation of the line), and average
   the cell percentile fields as `zonal_mean_cosw(q * W, den=W)` (ratio of sums = precipitation-weighted mean of q, exactly the construction of the line). Variables without a denominator (frequency, MCS precipitation) are **unchanged**. Cache key `version` 3 (the cache is made again once from the 132 monthly OBS maps, a few minutes),
   docstring and the configuration comment updated. The `zonal_iqr` method is unchanged.
2. **Notebook sources, already edited in round 5:** `nb_maps.py` (= `nb_maps_part1.py` + `nb_maps_part2.py`: climatology paths of `e3sm25` / `e3sm100` -> `mcs_tbpf_hr2p0/monthly/`) and `nb_trackstats.py` (`combined_dir` of both -> `mcs_tbpf_hr2p0/stats`; Cess2 -> the CFS folder you swapped). Text in the notebooks that quotes old E3SM numbers is updated after the run.
3. **Sensitivity notebook** (`nb_sens_body.py`): its data are unchanged (baseline = the 10 mm/h `mcs_tbpf` tree, the 2.0 point = the sensitivity run = the new production year 2010); it is rebuilt so that it carries the new band function (the builder copies the function cells of the maps notebook) and `zonal_headroom` 0.9 -> 1.3 so that the legend does not cover the OBS line.
   After the maps notebook ran I look at its zonal panels too: if its legend also covers a line, the same headroom is set there and that notebook is run again (its run is short).
4. README (OBS band description, E3SM key facts: the old 18.5 % / 3.3 % MCS precipitation fractions become the 2.0 production values), docs progress log, memory note.

### 4. Order of work

0. Docs + memory sync. 1. Interactive node (1 node, m1657, 4 h). 2. `check_production.py` + the 2010 content comparison (`compare_control_parallel.py` / `tests/tbpf_compare.py`, on the node). 3. `tracking_e3sm/finalize_production_tree.py --models ne120 ne30 --tag 2p0`
(links `stats/` and `monthly/`). 4. On the node: multi-year climatology `calc_mcs_rainmap_climo_from_monthly.py --indir <root>/monthly` for 2009-01..2011-12 (ne120) and 2009-01..2020-12 (ne30); tidy Parquet `combine_filter_mcs_trackstats.py --indir <root>/stats --pattern 'mcs_tracks_final_*.rows' --region tropics|global --outdir <root>/stats` (4 files); check them like in round 3
(schema equal to the OBS / SCREAM files, tracks and rows equal to the row tables). 5. Band change (section 3.1), `build_notebooks.py OUTDIR`, copy the three notebooks to `scream/Notebooks/` (backups of the executed ones: `bak_executed_*`), execute with
`$JUPYTER nbconvert --to notebook --execute --inplace --ExecutePreprocessor.kernel_name=pyflex26_3` on the node (maps and track-statistics in parallel, then the sensitivity notebook, about 16 min), 0 error cells, look at every figure. 6. README, docs, memory; release the node.

### Verification

- Band: (a) frequency and MCS-precipitation bands equal the old cached values (same percentiles, same weights); (b) the new fraction band has the line inside it in (nearly) all 60 bins, printed as in the diagnostic above (position of the line in the band for the three variables); (c) the figure shows the band straddling the line.
- E3SM data in the notebooks: the printed load lines show the `mcs_tbpf_hr2p0` paths, rows, tracks and file names per source (track counts: the tropics file has at most the robust MCS count of the years, ne120 about 100,000 and ne30 about 67,000 tracks over the years); no `mcs_tbpf/` path remains in the two executed notebooks.
- Parquet / climatology: the Parquet tracks and rows equal the row tables (the converter check of round 3), the climatology has the same variables as the 10 mm/h file and its `precipitation` mean equals the one of the 10 mm/h climatology (same input precipitation).
- Production: `check_production.py` prints no PROBLEM and 2010 agrees with the sensitivity 2.0 runs.
- Notebooks: executed with 0 error cells, all figures viewed (including the legend positions), the old executed notebooks kept as `bak_executed_*`.

### Risks

- The two E3SM sources now have far more tracks than before (ne120 about 7,500 -> 33,000 per year, ne30 about 90 -> 5,600 per year): the track-statistics notebook gets bigger (the earlier peak was 38 GB, expect about 45-55 GB: node only, not the login node) and its composites and tables for the 100-km source, which the old notebook skipped for lack of tracks, may now be drawn: I check that text and the empty-panel notes.
- Re-reading the 132 OBS monthly files for the new cache takes some minutes; the cache is rewritten (version 3), the old one stays as a backup copy.
- Pixel files of the production tree (about 1.65 TB) stay on pscratch, not backed up; the 10 mm/h tree stays untouched. Nothing is copied to CFS, committed or pushed without your word (scream files of rounds 4 and 5 are still uncommitted).

### Files

Modified: `nb_maps_part1.py` (`obs_zonal_band`, config comment), `nb_sens_body.py` (`zonal_headroom`), the three rebuilt notebooks in `/global/u1/f/feng045/program/scream/Notebooks/`, `scream/README.md`, the docs file, the memory note.
New (data): `mcs_tbpf_hr2p0/{stats,monthly}` link folders, the two multi-year climatology files and four Parquet files, the new OBS band cache. Untouched: the 10 mm/h production, the sensitivity runs, the Cess2 CFS folder.
- 2026-11-18 11:10 round 5b approved; progress entries below.
- 2026-11-18 11:20 round 5b, production CHECKED and DATA PRODUCTS MADE. Interactive node 61540111 (nid200094). (1) All 15 hr2p0 jobs COMPLETED, every step `ok` in the 15 step ledgers, no failed step in the logs (the 2 Tracebacks of ne120 2011 are Dask shutdown noise); trackpcp 28 min ne120 / 16 min ne30 per year; speed pairs
  without a measurable movement 0.004-0.007 % (ne120), 0.04-0.06 % (ne30). `check_production.py` (content level): all years complete and consistent (12 maps, dense == rows tracks, trackpcp files, key 2.0, pixel files = cloudid files). CORRECTION: the `movement_theta == 45.0` count (about 2 % of the entries) is NOT a
  fingerprint of the old tied-maximum garbage (integer pixel lags give an exact 45 degrees for any diagonal movement), I wrongly offered it as one. **The real test, `compare_prod_sens.py` (production 2010 vs the sensitivity 2.0 run):** matchpf and robustmcs row tables identical, 12/12 monthly rain maps identical (only `created_on` differs),
  121 sampled pixel files identical, final row tables differ in exactly **27 (ne120) / 92 (ne30) movement entries = the tied pairs (production NaN, sensitivity run finite)**, the dense file only in the movement variables and the speed counters.
  (2) `finalize_production_tree.py` made `stats/` (3 and 12 row-folder links) and `monthly/` (36 and 144 rain-map links); multi-year climatology `mcs_rainmap_monthly_climo_200901_201112.nc` (ne120, 649 MB) and `..._200901_202012.nc` (ne30, 299 MB); Parquet tropics / global: ne120 1.61M / 2.40M rows (66,786 / 98,933 tracks of the 99,880 robust),
  ne30 1.27M / 2.59M rows (30,998 / 65,764 tracks of 67,180), schema equal to the OBS file (`verify_hr2p0_parquet.py`).
  (3) Band: `obs_zonal_band` now precipitation-weights the percentile fields of variables with a denominator (cache version 3; the old cache is kept as `obs_zonal_annual_2007_2017_ANN_version2_area_weighted.nc`); sensitivity notebook `zonal_headroom` 1.3; the three notebooks were rebuilt and copied into `scream/Notebooks/`
  (the executed ones of round 4 are `bak_executed_*_before_round5b.ipynb` in `.claude_tmp_verify/scream_e3sm/`) and are being executed (maps then sensitivity, track statistics in parallel).
- 2026-11-18 11:55 round 5b DONE. Notebooks executed on the node, 0 error cells each: track statistics (147 s; E3SM sources `mcs_tbpf_hr2p0`: 25-km 66,786 tracks / 1.61M rows, 100-km 30,998 tracks / 1.27M rows in the tropics; 32.7M rows in total; land / ocean tracks with lifetime 25-km 27,036 / 23,261 and 100-km 11,133 / 11,443, so the 100-km
  source now has composites; Cess2 read from the CFS folder), maps (1,386 s, includes making the new OBS band cache: about 10 min), sensitivity (981 s; its data and summary table are unchanged, it carries the new band function and `zonal_headroom` 1.3, legend no longer covers the OBS line). All figures looked at (stats: box plots, tracks per year, composites;
  maps: overview, fraction, cloud frequency; sensitivity: ne120 fraction). **Band:** `obs_zonal_band` precipitation-weights the percentile fields of the fraction (cache version 3): cloud-frequency and MCS-precipitation bands numerically unchanged (max difference 0), annual zonal means unchanged, the fraction line is inside the band in 60 of 60 bins (old band: 25), band width / line 0.24 (old 0.26).
  **Area means 60S-60N (cells valid in OBS), ANN, 2.0 mm/h production vs old 10 mm/h:** MCS precipitation fraction 25-km 29.9 % (18.3), 100-km 25.5 % (3.7), OBS 50.5; cloud frequency 5.22 / 4.27 % (2.48 / 0.49), OBS 3.69; MCS precipitation 0.94 / 0.81 mm/day (0.58 / 0.12), OBS 1.54 (`area_means_e3sm.py`). README updated (OBS band, E3SM numbers, track-statistics section).
  Open: nothing is committed (scream: README, generator, finalize script, 3 notebooks, swap script, Cess2 config; PyFLEXTRKR-dev: 80438a4 and 38ae5d1 local), nothing is pushed; the 10 mm/h tree stays; the one-year sensitivity runs stay.

---

# HOUSEKEEPING (APPROVED 2026-11-18): HPSS backup / restore scripts for the E3SM trees, notebooks switched to the CFS copies, zonal legend outside

State at the start: round 5b done; the user asked for HPSS backup and retrieval scripts (one tar per directory, 100 GB - 2 TB), a test with quicklooks_2panel_tbpf, then xfer jobs; and to switch the notebook inputs to the CFS copies, re-run, prove identity with pscratch, commit; plus (plan comment) the zonal-mean legend outside the axes at the upper right with a tighter y range, also in the sensitivity notebook. Verbatim copy of the approved plan (headings shifted one level):

## Housekeeping: HPSS backup / restore scripts for the E3SM trees, and the three notebooks switched to the CFS copies

### Context

Two housekeeping requests after round 5b (`/global/homes/f/feng045/program/scream/docs/PLAN_scream_e3sm_mcs_evaluation.md`, memory note `project_scream_e3sm_mcs_evaluation`):
(1) back up the E3SM MCS-tracking output trees on HPSS (one tar per directory, 100 GB to 2 TB, scripts modeled on `airscape/MRMS_Processing/scripts/hpss_backup.py` / `hpss_restore.py`), test them on `quicklooks_2panel_tbpf`, then submit xfer jobs;
(2) make the three notebooks read the CFS copies instead of pscratch, re-run them, prove the results identical to the pscratch-based ones, then commit the notebooks.
Environment: `/global/common/software/m1867/python/pyflex26.3` (kernel `pyflex26_3`); own interactive node (account m1657) for content-level work; no attribution lines in commits.
**My first action after approval is to append this plan to the docs file and note it in the memory note.**

### 1. HPSS backup and restore

**What I found (read-only).**
- `/home/f/feng045/E3SM_polun` exists and already holds four old archives from 26 Oct (`E3SM_CTL.tar`, `maps.tar`, `OBS_180W-179E.tar`, `stats.tar` + `.idx`): they are not touched. The sub-folders do not exist yet. I read your "e30 / e120" as `ne30_remap_0.1deg` and `ne120_remap_0.1deg` (the names of the scratch folders).
- Limits (NERSC htar page, same as the MRMS doc): bundle 100 GB - 2 TB, member file at most about 68 GB (64 GB used), member path prefix 154 + name 99 characters, **link names at most 99 characters**, soft limit 1,000,000 members (`-M` up to 5,000,000), no appending, htar only on login and xfer nodes (not on compute nodes).
- **Symbolic links are a problem and shape the design:** the trees hold tens of thousands of absolute links with 110-116 character targets (`mcs_tbpf/<year>/tracking/campaign_*/cloudid_*.nc`, about 8,761 per year; `stats/mcs_tracks_*.rows` in `mcs_tbpf_hr2p0` and every sensitivity run, 116 characters). htar would refuse them, and the NERSC page does not say whether it follows or stores links.
  Decision: **htar archives real files only; the links go into a manifest** `<dir>.tar.links.tsv` (link path relative to the model folder, tab, target) that the backup script `hsi put`s next to the tar and the restore script reads back to recreate the links (`--relink` re-points absolute targets from the old root to the new one). Links are never followed (no size blow-up, a restored `mcs_tbpf_hr2p0` is only complete together with `mcs_tbpf`, said in the docs).

**Layout and sizes** (one tar per top-level directory, `animations_2panel_tbpf` and `quicklooks_2panel_tbpf` are not backed up by default):
```text
/home/f/feng045/E3SM_polun/ne120_remap_0.1deg/{mcs_tbpf_hr2p0 314 G, mcs_tbpf 592 G, olr_pcp 140 G, mcs_tbpf_sens 611 G}.tar   (+ .tar.idx, .tar.links.tsv)
/home/f/feng045/E3SM_polun/ne30_remap_0.1deg/{mcs_tbpf_hr2p0 488 G, mcs_tbpf 895 G, olr_pcp 189 G, mcs_tbpf_sens 199 G}.tar
```
8 archives, 3.4 TB, every one inside 100 GB - 2 TB; members are paths relative to the model folder (`mcs_tbpf/2010/...`), so extracting into a folder recreates the tree. The member counts (roughly 50,000 for the sensitivity trees, 300,000 for ne30 `mcs_tbpf`) stay below 1,000,000.

**Code (new, in `scream/tracking_e3sm/`, not committed unless you say so):**
- `hpss_e3sm_lib.py`: the logic that needs no HPSS (scan a directory without following links, limits and refusals, manifest, htar / hsi command lines and parsers, archive listing); `run_tool`, `hsi_ls`, `hsi_mkdir_p`, `ensure_transfer_host` and the parsers are the proven ones of `mrms_processing/hpss.py`, copied (the two repositories stay independent).
- `hpss_e3sm_backup.py`: **without `--run` it only prints the plan** (archive, files, links, GB, notes) and writes nothing; with `--run`: `htar -c -V -Hcrc -M n -L list` in the model folder, `htar -K -Hverify=crc`, check of `.tar` + `.idx`, `hsi put` of the manifest, CSV report; skips an archive that exists with its index, reports (never touches) an interrupted one, refuses a temporary file / too long path / member above 64 GB / bundle above 2 TB, leaves a directory whose newest file is younger than 30 min. Options: `--models`, `--dirs` (default: all but the two excluded), `--hpss-dir` (default the root above), `--workers`, `--no-crc`, `--verify-existing`, `--min-age-min`, `--work-dir` (default `/pscratch/sd/f/feng045/E3SM_polun/_hpss_logs`, outside the archived trees).
- `hpss_e3sm_restore.py`: `--list`; `--models`, `--dirs`, `--path` (one or several sub-paths of an archive, for example `mcs_tbpf_hr2p0/2010/stats`, extracted from the index without reading the whole tape), `--dest` (required; refuses the original root unless `--overwrite`), `--relink`, `--dry-run`, `--nostage`, `--no-crc`; afterwards the file count is compared with the member list and the links of the manifest are recreated.
- `slurm_hpss_e3sm_backup.sbatch`, `slurm_hpss_e3sm_restore.sbatch`: like the MRMS ones (account m1657, `--qos=xfer -C cron`, 48 h / 12 h, 8 GB, licenses `SCRATCH,hpss`, settings through environment variables: `MODELS`, `DIRS`, `WORKERS`, `EXTRA`).
- `scream/tests/test_hpss_e3sm.py`: pytest with a fake `htar` / `hsi` that keep a tape in a temp folder (the pattern of `MRMS_Processing/tests/test_hpss.py`): limits, links and manifest, skip / exists / incomplete / failed, subset restore, relink, counts, dry runs. `scream/docs/hpss_e3sm.md` (layout, plan reading, restore recipes, the symlink rule, measured numbers) and a pointer in the README.

**Test (as you asked, small first):**
1. pytest (fake tools) on the node.
2. Real HPSS on a login node (htar works there; 45 MB), folder `/home/f/feng045/E3SM_polun/_smoke/`: (a) `quicklooks_2panel_tbpf` (real data, the note "below 100 GB" is expected), (b) a small synthetic directory with a link whose target has 116 characters, a relative link and a link to a directory. Dry-run plan, then `--run` (written, verified against the CRCs, indexed, manifest put), `--list`, restore into `$SCRATCH/hpss_e3sm_smoke/restore` (also a `--path` subset), then `diff -r` and `cmp` byte by byte, permissions, times and `readlink` of every link equal to the source. Afterwards I remove the `_smoke` folder in HPSS (`hsi rm` of the files and directories I made there, nothing else) and the scratch test folders.
3. Dry-run plan for all 8 real archives (login node, scan only, a few minutes): I check counts, sizes, refusals before submitting.

**Production run (submitted after the test passed, as you asked):** two xfer jobs, one per model (`MODELS=ne120`, `MODELS=ne30`), 4 workers each (4 archives per job at the same time, 8 of the 15 allowed HPSS sessions). At the 120-180 MB/s measured for the MRMS archives plus the read-back of the CRC verification I expect 8-10 h per job (48 h limit; resubmitting continues, finished archives are skipped). Logs in `E3SM_polun/_hpss_logs/slurm/`. When they end: the CSV of each job (all `verified`), `hpss_e3sm_restore.py --list`, and one real restore check: `--path ne120_remap_0.1deg ... mcs_tbpf_hr2p0/2010/stats/monthly` (12 rain maps) extracted from the real archive and compared with `cmp` against pscratch.

### 2. Notebooks from the CFS copies

**What is on CFS (read-only look):** `E3SM_polun/<ne120|ne30>_remap_0.1deg/{mcs_tbpf, mcs_tbpf_hr2p0}/{monthly, stats}` as real files (monthly maps + climatology, final row folders + the combined Parquet; copied 17-18 Nov, owner wcmca1, group m1867 group-writable); `SCREAM-decadal/{cess2/{monthly (Cess2 climatology + maps), stats}, ne1024, ne256, maps, mcs_global_v3/MCSMIP/{monthly (two climatology files), stats (Parquet)}}`; `E3SM/SCREAMv1/cess2/global/mcs/stats` (the swapped Cess2 statistics, already cmp-verified). ne1024, ne256, the OBS climatology / Parquet, the masks and the topography are already read from CFS by the notebooks.
**What is missing and how it is handled (your answers):** the 132 OBS monthly maps for the interannual band are read from the original `wcm_shr/gsharing/MCS_Global/V3/MCSMIP/stats_mcsmip/monthly` (no copy); the sensitivity notebook's working set is **copied to CFS** (about 6 GB, new `mcs_tbpf_sens/` next to `mcs_tbpf`, group-writable for me): per run (10) the 1-year climatology and the final row folder, plus the baseline climatology made with `calc_mcs_rainmap_climo_from_monthly.py` from the CFS 2010 production maps into `mcs_tbpf_sens/baseline_2010/monthly/`.

**Changes in the notebook sources** (`/global/homes/f/feng045/.claude_tmp_verify/scream_e3sm/`: `nb_maps_part1.py`, `nb_trackstats.py`, `nb_sens_body.py`, then `build_notebooks.py`): `E3SM = '/global/cfs/cdirs/m1867/zfeng/E3SM_polun'` (climatology paths of the maps notebook, `combined_dir` of the statistics notebook, `MODELS[..]['root']` of the sensitivity notebook), the Cess2 climatology -> `SCREAM-decadal/cess2/monthly/...`, `obs_monthly_dir` -> the wcm_shr folder; in the sensitivity notebook `run_paths` reads the baseline final rows from `<root>/stats/mcs_tracks_final_<dates>.rows` (CFS has no per-year folders). Figures and tables are still written to the same `figdir` on pscratch.

**Zonal-mean panel, your comment (maps and sensitivity notebooks; same function `draw_zonal_panel`, so the two cannot drift apart):** the legend moves to the **upper right of the axes, outside it** (one column, `loc='upper left'`, anchored at the axes' upper-right corner, `bbox_to_anchor=(1.01, 1.0)`; it may extend beyond the axes into the white margin, and `savefig(bbox_inches='tight')` widens the saved file if it reaches past the figure edge), and the y-limit headroom drops from 0.9 (maps) / 1.3 (sensitivity) to **0.1**, so the lines and the OBS band fill the axes and the differences between the lines show. Implementation: one new key `zonal_legend_anchor = (1.01, 1.0)` (None = the old position inside the axes at `zonal_legend_loc`, the one-key-with-null convention), `zonal_legend_ncol` 2 -> 1, `zonal_headroom` 0.9 / 1.3 -> 0.1, in `draw_zonal_panel`, `plot_obs_and_bias_maps` and the Configuration cells of both notebooks (and the README text). Geometry I checked on the 2026-11-18 figures: in the maps figures the free space is above the bias colorbar to the right of the zonal axes (the colorbar starts at about 70 % of the top row), in the sensitivity figures the zonal row is the bottom row and nothing is to its right; a one-column legend of 8 entries is about 2.6 in wide and 1.5 in tall, so it fits with the saved file a little wider. I look at every zonal panel afterwards (3 maps figures, 6 sensitivity figures) and, if the legend touches a colorbar, shorten it (smaller font or the periods dropped from the labels) before the final run.

**Proof of identity, in four steps (run BEFORE the legend change, so that only the inputs differ):**
1. **Data:** a script on the node compares every CFS file the notebooks read with its pscratch counterpart by size and `cmp` (E3SM `monthly` + `stats` of both trees, the Cess2 climatology and Parquet, the 132 OBS monthly maps wcm_shr vs the pscratch copy, and after the copy the ten sensitivity runs). Any difference stops the work.
2. **Snapshot** the current outputs as the reference: the three figure folders (about 60 MB), the summary CSV / HTML tables and the OBS band cache (`obs_zonal_annual_*`).
3. **Re-run** the three notebooks on the node with the CFS inputs (`nbconvert --execute --inplace`, kernel `pyflex26_3`), the band cache under a new temporary name so that the band is really recomputed from the CFS monthly maps (maps notebook about 23 min, statistics 2.5 min, sensitivity about 16 min after the maps one: they share the cache).
4. **Compare** every output with the snapshot: PNG files byte by byte (if the bytes differ, pixel arrays), CSV and HTML text, the band cache arrays with `np.array_equal`; 0 error cells; the printed load lines show only CFS paths (no `/pscratch` input left in the executed notebooks).
If something differs I report it, change nothing further and commit nothing.
5. **Legend / y-limit change** (above) on top of the proven CFS inputs: rebuild, re-run the maps and sensitivity notebooks (the statistics notebook has no zonal panel and is not run again; the band cache of step 3 is reused, so about 15 min and 16 min), 0 error cells, look at every zonal panel. Their figures differ from the snapshot only in the layout of that panel (data and lines identical: checked on the cached line values of the zonal panel in the run).
6. **Commit** exactly the three notebooks on `main` of the scream repo (`git add` of those files only, `git diff --cached --stat` checked, message without attribution lines, no push; the notebooks carry their executed outputs, about 6 MB each). The message says that the inputs come from CFS (identical to pscratch, checked) and that the zonal legend moved outside with a tighter y range.

### Order of work

0. Docs + memory sync. 1. Interactive node. 2. HPSS code, docs, pytest. 3. Real-HPSS smoke test and clean-up. 4. Dry-run plan of the 8 archives, then submit the 2 xfer jobs. 5. While they run: CFS copy of the sensitivity working set, baseline climatology, cmp script, snapshot, notebook sources (CFS inputs only), build, re-run, compare (identity proof); then the zonal legend / y-limit change, rebuild, re-run of the maps and sensitivity notebooks, look at the zonal panels, commit. 6. When the jobs end: check the CSVs, `--list`, the sample restore; docs / memory; release the node.

### Verification

- pytest of the HPSS scripts passes; the smoke test restores byte-identical files and the same link targets, and leaves nothing behind in HPSS or scratch.
- Dry-run plan: 8 archives, no refusal, each 100 GB - 2 TB, member counts below 1,000,000; after the jobs all 8 `verified` with `.idx` and manifest, `--list` shows them, the sample restore is `cmp`-identical.
- Notebooks: the step-1 data comparison is clean, the step-4 outputs are identical, 0 error cells; after the legend change the zonal panels show the legend outside at the upper right without touching a colorbar or a line, the lines fill the axes (y range tight, headroom 0.1), the OBS band still straddles the OBS line; then the commit shows exactly the three files.

### Risks

- htar on login nodes is only for the 45 MB smoke test; the 3.4 TB go through the xfer jobs. I cannot see the HPSS quota; a refusal would show in the htar log and stop that archive (the others continue).
- The trees must not change during the run (they are static now; the newest-file test of 30 minutes guards against a job that is still writing).
- A restored `mcs_tbpf_hr2p0` / `mcs_tbpf_sens` needs `mcs_tbpf` next to it, or `--relink` plus the restored tracking folder (documented).
- The CFS write for the sensitivity working set is about 6 GB in your own group-writable area; the existing CFS copies, the wcm_shr folder and everything pushed stay untouched. PNG byte equality assumes deterministic rendering (matplotlib writes no timestamps); the fallback is the pixel comparison. A legend outside the axes can reach the right colorbar of the maps figures or widen the saved image; I check each figure and shorten the legend if needed.

### Files

New: `scream/tracking_e3sm/{hpss_e3sm_lib.py, hpss_e3sm_backup.py, hpss_e3sm_restore.py, slurm_hpss_e3sm_backup.sbatch, slurm_hpss_e3sm_restore.sbatch}`, `scream/tests/test_hpss_e3sm.py`, `scream/docs/hpss_e3sm.md`, the HPSS folders and archives, `E3SM_polun/_hpss_logs/` on pscratch, the CFS `mcs_tbpf_sens/` working set, a comparison script and the reference snapshot in `.claude_tmp_verify/scream_e3sm/`.
Modified: the three notebook sources (inputs; and `nb_maps_part1.py` / `nb_maps_part2.py` / `nb_sens_body.py` for the zonal legend and headroom), the three notebooks (committed), `scream/README.md` (HPSS pointer, CFS inputs, zonal panel), the docs file, the memory note.
Untouched: the four old HPSS archives, the scratch trees (read only), the wcm_shr folder, the existing CFS E3SM / SCREAM-decadal copies.
- 2026-11-18 housekeeping approved; progress entries below.
- 2026-11-18 22:00 housekeeping, HPSS part: scripts written (`tracking_e3sm/hpss_e3sm_{lib,backup,restore}.py`, `slurm_hpss_e3sm_{backup,restore}.sbatch`, `tests/test_hpss_e3sm.py` 20 tests pass with a fake htar/hsi, `docs/hpss_e3sm.md`, README pointer). Finding: absolute symlinks with 110-144 character targets (`mcs_tbpf/<y>/tracking/campaign_*`, `stats/mcs_tracks_*.rows` of the derived trees)
  exceed htar's 99-character link limit: htar archives real files only, a manifest `<dir>.tar.links.tsv` (`hsi put` next to the tar) recreates links and empty folders on restore (`--relink` re-points absolute targets). REAL-HPSS SMOKE TEST (login node, `/home/f/feng045/E3SM_polun/_smoke`): `quicklooks_2panel_tbpf` (25 files, 45 MB) + a synthetic
  tree (144-character link target, relative link, link to a folder, empty folder) written, verified against the CRCs (2-3 s each), `--list`; restored `diff -r` / `cmp` identical, permissions and mtimes equal, link targets equal, sub-path restore named only the folder to htar, `--relink` re-pointed the long link and it resolves; refusal of the original data root and of a missing path
  checked; smoke folders removed from HPSS (only my own `_smoke` objects; the 4 old archives untouched) and from scratch. PLAN of all 8 archives (scan only, node): ne120 mcs_tbpf 634.7 GB (79,425 files, 52,599 links), mcs_tbpf_hr2p0 336.4 (26,405 / 45), mcs_tbpf_sens 655.2 (52,790 / 12), olr_pcp 149.5 (26,281 / 0); ne30 mcs_tbpf 958.7 (317,602 / 210,406),
  mcs_tbpf_hr2p0 522.9 (105,615 / 180), mcs_tbpf_sens 213.0 (43,996 / 10), olr_pcp 201.9 (105,121 / 0): 3.67 TB, none refused, all within 100 GB - 2 TB. **Two xfer jobs submitted 21:48: ne120 = 61560296, ne30 = 61560297** (`WORKERS=4`, 48 h, logs `E3SM_polun/_hpss_logs/slurm/`, CSV in `_hpss_logs`).
- 2026-11-18 22:30 housekeeping, CFS notebooks part. CFS copies found (E3SM_polun CFS `mcs_tbpf` + `mcs_tbpf_hr2p0` monthly + stats, SCREAM-decadal cess2 monthly + stats, ne1024, ne256, OBS climatology + Parquet); **copied to CFS by me (4.1 GB, user-approved): the sensitivity working set**
  `E3SM_polun/<model>_remap_0.1deg/mcs_tbpf_sens/heavyrain_<tag>/2010/stats/{monthly/mcs_rainmap_monthly_climo_201001_201012.nc, mcs_tracks_final_20100101.0000_20110101.0000.rows}` (10 runs) and the baseline climatologies `mcs_tbpf_sens/baseline_2010/monthly/` made from the CFS production maps.
  **Data identity (`compare_cfs_pscratch.py`, byte for byte):** E3SM `monthly` + `stats` of both trees and both models 492 files / 6.6 GB identical (file sets equal); Cess2 climatology + Parquet 5 files identical; the 132 OBS monthly maps (wcm_shr original vs the pscratch copy) identical; the copied sensitivity files 50 identical;
  the two derived baseline climatologies differ in file size (creation time stamp) but are identical in content (`netcdf_differences`). **Identity of the notebook outputs (`compare_outputs_hk1.py`):** the three notebooks with the CFS inputs (E3SM -> CFS, Cess2 climatology -> `SCREAM-decadal/cess2/monthly`, OBS monthly -> the wcm_shr original, band cache recomputed under a temporary name,
  sensitivity baseline rows from `<root>/stats`) ran with 0 error cells (statistics 157 s, maps 1,418 s, sensitivity 998 s): **25 of 25 output files (PNG, CSV, HTML) byte-identical** to the pscratch run, the OBS band cache identical in all 9 arrays, no pscratch input path left in the notebooks (only the output folder and the cache). Backups: `bak_executed_*_before_housekeeping.ipynb`.
  Then the zonal legend change (`apply_legend_patch.py`: legend outside at the upper right via `zonal_legend_anchor = (1.01, 1.0)`, one column, `zonal_headroom` 0.1) in the maps and sensitivity notebooks; final run in progress.
- 2026-11-18 23:25 housekeeping, notebooks DONE and COMMITTED (scream main **1211c3e**, exactly the three notebooks, no attribution, not pushed). Zonal legend (your comment): first version (legend anchored just right of the zonal axes) overlapped the bias colorbar in the sensitivity figures (the colorbar reaches down into the zonal row), so the final rule is: legend one column at the upper right
  of the zonal axes (outside, top aligned), and if its box would touch the bias colorbar (padded 8 px) it moves to the right of the colorbar and its label; `zonal_legend_outside = True` (False = old, inside), `zonal_headroom = 0.1`; saved files are 160-480 px wider (tight bbox). Checked on the maps figures (legend above the colorbar tip) and the sensitivity figures (right of the colorbar): no collision, the lines fill the axes.
  Final run (maps 1,423 s, sensitivity 1,144 s): 0 error cells, no pscratch input path; against the pscratch reference exactly the 9 zonal-panel PNGs (3 maps + 6 sensitivity) differ (layout), the other 16 output files (overviews, composites, box plots, tables, CSV, summary PNG) stay byte-identical, the band cache identical. Temporary test files removed; the reference snapshot is kept in `SCREAM-decadal/figures_e3sm_ref_r5b/`.
  HPSS (23:20, jobs 61560296 / 61560297 running 1 h 41 min): written so far ne120 mcs_tbpf_hr2p0 (336.4 GB), olr_pcp (149.5 GB), ne30 mcs_tbpf_hr2p0 (522.9 GB), mcs_tbpf_sens (213.0 GB), olr_pcp (201.9 GB) with their index (and manifest where there are links or empty folders); the big ones are still writing, then each archive is read back against its CRCs.
