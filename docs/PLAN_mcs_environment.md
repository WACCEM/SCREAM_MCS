# MCS environment extraction (SCREAM / E3SM / ERA5): plan (APPROVED 2026-11-20, in progress)

This file is the durable copy of the plan, written so that a new Claude session can continue without the earlier conversation. The same
plan is summarized in the auto-memory note `project_mcs_environment_extraction`. The plan below is the version the user approved on
2026-11-20 after one round of review comments (relative-time composites, diameters 200/400/600 km, Cess2 `prw` from `3hi_ne120pg2`,
parallel Parquet writing, ERA5 transfer README) and two answers (ERA5 copy with the user's own Globus login; mask 850 hPa below ground in all sources).

## Status and how to resume

**Status:** approved; implementation started on 2026-11-20. The progress log at the end of this file says what is done and what is next;
it is updated at every checkpoint.

**To resume after a restart:**

1. Start the Claude session with the working directory `/global/u1/f/feng045/program` (auto-memory is stored per working directory).
2. First message:

```text
Resume the MCS environment extraction. Read
/global/homes/f/feng045/program/scream/docs/PLAN_mcs_environment.md
and the memory note project_mcs_environment_extraction, then continue from the progress log at the end of the file.
Ask me before submitting Slurm jobs or deleting anything.
```

3. Python environment: `/global/common/software/m1867/python/pyflex26.3/bin/python` (numpy, scipy, pandas, pyarrow, netCDF4, cftime, PyYAML, pytest are installed).
   Heavy runs need an interactive CPU node requested by Claude (`salloc --nodes=1 --qos interactive --constraint cpu --time 04:00:00 --account=m1867`,
   or m1657 when m1867 has no node-hours); scripts for the node must not live in /tmp (node-local).

## The original request (verbatim, so nothing depends on the old chat)

```text
# MCS environment analysis

Make a plan to extract environmental variables averaged in a specified diameter following MCS tracks.

Requirements:
- For each MCS, extract environmental variables averaged within a specified diameter circle (make multiple diameters that user can specify, set default: 100, 200, 400, 600 km)
- For 24 h prior to MCS starts, stay at the same location as the MCS start location to extract
- After MCS starts, the circular area follows the centroid of the MCS till the track ends
- Save the time series output to a Parquet file format, with attributes, units, compression
- Find the closest time from the environment data (3-h or 6-h) to the MCS track data (1-h). For 6-h, pick the center of the 6-h window from the 1-h MCS tracks so the largest time difference is no more than than 3-h
- Because almost all variables I want are 2D, it may be more efficient to extract all of them in the same slurm job, so that output contains all variables needed
- High efficiency parallel processing

Issues that could affect the workflow:
1. Is there a fast approach to find all grid cells within a given circle from a cube sphere grid (E3SM output grid)?
- This operation will be applied to 10s of thousands of MCSs and each one have 10s of hours, so it needs to be very efficient

2. Input file non-uniformity
- E3SM and SCREAM have different variable names. A config file should be made to rename the input variables to standard output variable names using dictionary
- The input files have different temporal resolutions (usually lower) from the MCS tracks (hourly), and may have different organizations (e.g. 3-h data in a daily file; 6-h data in a daily file, etc). The code must be flexible to deal with finding the matching input file and closest time to adapt to different input file organization
- Ideally, the code should be flexible to handle different types of data. If some specific handling is needed, make the I/O portion modular to adapt to different sources.

Data sources and short names:
- SCREAM-decadal ne1024 (~3.25 km, CTL): "3-km CTL"
- SCREAM-decadal ne256 (~13 km, CTL): "13-km CTL"
- SCREAM-decadal ne256 (~13 km, TUNE): "13-km TUNE"
- SCREAM-Cess2 ne1024 (~3.25 km, use the same "TUNE" physics as ne256): Cess2 "3-km TUNE"

References:
Extract MCS environment: @waccem/gsrm_mcs_environments/extract_environments/get_env_vars_time_batching.py
	- This will the be main workflow to follow
	- The input data in this workflow is Zarr on Healpix grid
	- Currently my input data have not been remapped to Healpix and they're netcdf

Extract ETC environment: @waccem/gsrm_cooccurrencefeature/extract_environments/extract_etc_2d_vars.py
- This version is adapted from the extract MCS environment workflow, with a few differences:
	- It does not save environments before ETC forms
	- It remaps Healpix to a lat-lon grid and saves the 2D pixel values to a Zarr file (not needed)
	- It handles different input variable units and conversion, interpolation (may or may not be needed)

Input data:
MCS data:
	- OBS: /global/cfs/cdirs/m1867/zfeng/SCREAM-decadal/mcs_global_v3/MCSMIP/stats/mcs_tracks_final_combined_tropics_2007_2017.parquet
	- 3-km CTL: /global/cfs/cdirs/m1867/zfeng/SCREAM-decadal/ne1024/stats/mcs_tracks_final_combined_tropics_1995_2005.parquet
	- 3-km TUNE: /global/cfs/cdirs/m1867/zfeng/E3SM/SCREAMv1/cess2/global/mcs/stats/mcs_tracks_final_combined_tropics_2019_2021.parquet
	- 13-km CTL: /global/cfs/cdirs/m1867/zfeng/SCREAM-decadal/ne256/ctl/stats/mcs_tracks_final_combined_tropics_1995_2005.parquet
	- 13-km TUNE: /global/cfs/cdirs/m1867/zfeng/SCREAM-decadal/ne256/tune/stats/mcs_tracks_final_combined_tropics_1995_2005.parquet
	- 25-km: /global/cfs/cdirs/m1867/zfeng/E3SM_polun/ne120_remap_0.1deg/mcs_tbpf_hr2p0/stats/mcs_tracks_final_combined_tropics_2009_2011.parquet
	- 100-km: /global/cfs/cdirs/m1867/zfeng/E3SM_polun/ne30_remap_0.1deg/mcs_tbpf_hr2p0/stats/mcs_tracks_final_combined_tropics_2009_2020.parquet

Environment data:
- OBS (ERA5 1-h, 0.25 deg data)
NOTE: ERA5 data is on CFS, which is not designed to handled very large amount of parallel file access
Best practice is to copy the data I need to access to pscratch using Globus CLI.
NERSC Globus CLI: https://docs.nersc.gov/services/globus/#command-line-globus-transfers-at-nersc
Prepare a script that I can run, not using my account, but using my project's collaboration account (wcmca1), so that the files copied to pscratch will count towards that account instead of my personal account.
Copy the data to: /pscratch/sd/w/wcmca1/ERA5

root: /global/cfs/projectdirs/m3522/cmip6/ERA5
2D: /e5.oper.an.sfc (monthly files)
	- TCWV (e5.oper.an.sfc.128_137_tcwv.ll025sc.)
3D: /e5.oper.an.pl (daily files)
	- Q (select 850, e5.oper.an.pl.128_133_q.ll025sc.)
	- R (select 850, 500, e5.oper.an.pl.128_157_r.ll025sc.)
	- W (select 850, 500, e5.oper.an.pl.128_135_w.ll025sc.)

- 3-km CTL but the outputs are coarsen to ne30 (~100 km):
root: /pscratch/sd/w/wcmca1/SCREAM-decadal/

Variables to compute:
3hourlyINST_ne30pg2
	- Compute specific humidity at 850hPa from T_mid_at_850hPa & RelativeHumidity_at_850hPa
	- RelativeHumidity_at_850hPa
	- RelativeHumidity_at_500hPa
	- omega_at_850hPa
	- omega_at_500hPa
	- precip_liq_surf_mass_flux

6hourlyINST_ne30pg2
	- VapWaterPath

- 3-km TUNE
root: /pscratch/sd/w/wcmca1/SCREAMv1-cess2/run
Variables to compute:

3hi_ne30pg2
	- Compute specific humidity at 850hPa from T_mid_at_850hPa & RelativeHumidity_at_850hPa
	- RelativeHumidity_at_850hPa
	- RelativeHumidity_at_500hPa
	- omega_at_850hPa
	- omega_at_500hPa
	- precip_liq_surf_mass_flux

I have not located where the 13-km environmental data yet. I will update you after I know the path.
- 13-km CTL
root: TBD
Variables to compute:

- 13-km TUNE
root: TBD
Variables to compute:

- 25-km:
root: /pscratch/sd/p/plma/e3sm_scratch/v3/E3SMv3_ne120/run
h1 files: hourly instantaneous
	- Q850 (Specific Humidity)
	- RH850
	- RH500 (compute from T500 and Q500)
	- TMQ
	- OMEGA500
	- PRECT

- 100-km:
root: /pscratch/sd/p/plma/e3sm_scratch/egu2025/ctl.fr/run
h3 files: hourly instantaneous
	- RH850
	- TMQ
	- OMEGA500
	- PRECT = PRECC + PRECL
```

(The original text asked for a wcmca1-owned ERA5 copy and the 100-km diameter; both were changed in the review, see the plan below.)

## The approved plan (verbatim)

## MCS environment extraction for SCREAM / E3SM / ERA5 — plan (revised after your review)

### Context

For every MCS track of 7 sources (OBS, 3-km CTL, 3-km TUNE, 13-km CTL, 13-km TUNE, 25-km, 100-km) extract environmental variables averaged inside circles of several diameters
(default **200 / 400 / 600 km**, user-settable): the circle stays at the MCS **start location for the 24 h before the start**, then **follows the MCS centroid until the track ends**.
Output: one compressed Parquet time series per source and year, with units and attributes; **all variables of a source come from the same job**.

The reference workflow (`waccem/gsrm_mcs_environments/extract_environments/get_env_vars_time_batching.py`) is HEALPix-Zarr based and slow per circle (`xarray .sel(cell=...)`, dicts of
DataArrays, Python loops over rows). Here the inputs are netCDF on cubed-sphere grids (ne30pg2, ne120pg2, …) and a lat-lon grid (ERA5). I keep its good ideas (group samples by time, read each
time slice once, valid-count bookkeeping, `time_offset_hours`/`data_time` columns, Parquet) and take the **exact time matching + NaN/record/5 % sanity limit** from `extract_etc_2d_vars.py`.

Decisions made in this session: ERA5 is copied with **your own Globus login** (files owned by feng045; quota 49.5 of 100 TB used, the copy adds about 18.7 TB and 12.5 k files → about 68 TB);
**all 850 hPa variables are masked below ground in every source** (needs ERA5 surface pressure `sp` in the copy). Code lives in the **scream repo**
(`/global/homes/f/feng045/program/scream/mcs_environment/`), env `pyflex26.3` (numpy 2.4, scipy 1.17, pandas 3.0, pyarrow 23, netCDF4 1.7, cftime, PyYAML, pytest: nothing to install;
no xarray/dask in the hot path, see the lock-leak lesson). No commits unless you ask, no assistant attribution lines.

### Your review comments → what changed

- **Relative-time composites (your main question): my first draft would NOT have given the same relative times.** Rows were on the environment-time grid, so `time_offset_hours = env time − track start`
  shifted with the start hour (3-h data: a track starting 14:00 got offsets …, +1, +4, +7; 15:00 → 0, +3, +6; 16:00 → −1, +2, +5). Your `evolution_by_radius` (`tools_mcs_stats.py`) does
  `groupby('time_offset_hours')` on the exact value, so each bin would hold about 1/3 of the tracks, there would be 3× as many bins, and 2/3 of the tracks would have no row at 0.
  **Redesign (section B):** every track gets rows at *nominal* offsets exactly k·Δ (…, −Δ, 0, +Δ, …); the environment is taken from the nearest env time and the shift is stored (`env_dt_hours`,
  |dt| ≤ 1.5 h for 3-h data, ≤ 3 h for 6-h data). This is what your old workflow did (`subsample_tracks_by_frequency` + `method='nearest'`), so the `groupby` and the `time_window` filters in your notebook keep working.
- **Parallel Parquet writing:** a Parquet file has one writer (the footer is written once at close), so nothing writes concurrently into one file. Parallelism = **one part file per task**, written
  with `pyarrow.parquet.write_table` inside `multiprocessing` workers (finished parts are skipped on restart); the parent then merges the year's parts into one file (OBS: about 4 M rows per year,
  ≈ 0.1–0.2 GB, one process is fine). A directory of part files also reads as one table with `pd.read_parquet(dir)`, as your notebook already does for its variable folders.
- **Cess2 `3hi_ne120pg2`:** confirmed (checked): 345 600 columns, `VapWaterPath`, `ps`, `omega_at_500hPa`, and 3-D `RelativeHumidity`/`T_mid`/`omega`/`p_mid`/`qv` on 37 model levels; 254 daily files
  **2019-08-01 … 2020-04-10 only** (the newest file, 786 MB vs 6.26 GB, looks partial; the folder was modified today). So the 3-km TUNE `prw` comes from that stream, **a source can have streams on different grids**
  (ne30pg2 + ne120pg2, now supported), and `prw` is NaN for tracks after 2020-04-10 (recorded as coverage, not an error). I do not interpolate the 3-D fields to 850/500 hPa on the finer grid (see assumptions).
- **RH500:** derived from T500 + Q500 for the 25-km (both are in the h1 files) as you said. The 100-km run has T500 but no Q500 in h2/h3/h4, so there is no `rh500` there (not in your list).
- **Diameters:** default 200, 400, 600 km.
- **Names/units follow your notebook:** `prw`, `rh850`, `rh500`, `q850`, `omega850`, `omega500` (+ `pr`); `q850` in **kg kg-1** (your notebook labels it g/g); `time_offset_hours`, `data_time` as in the old files;
  an optional helper turns the new wide table into the per-variable frames (`track_id`, `radius`, `time_offset_hours`, `mean`) that `tools_mcs_stats.py` expects.
- **ERA5 transfer README:** added as a deliverable (section G).

---

### What I measured (the design rests on these)

**Tracks (all 7 Parquets share the 69-column schema).** Key = (`period` as *string* year, `local_track` int64); sorted by (period, local_track, base_time); `start_basetime` = first row for 100 %;
`track_duration` = row count. Hourly at :00 except **OBS at :30**. `meanlon` is *unwrapped* (−207 … +212), so only 3-D unit vectors may be used for geometry. NaN positions: OBS 5 rows, 3-km CTL 35,
13-km 34–51. Gaps inside tracks: OBS 971 (≤ 3 h), 25-km 21 (≤ 2 h), 3-km none. Tracks spilling into the next year: 569 (3-km CTL), 60 (25-km). Tracks starting within 24 h of the record start:
OBS 121, 3-km CTL 162, 25-km 63 (the 25-km env record starts 2009-01-01, so those get NaN pre-start rows, logged, not an error).
**Expected samples (rows are × 3 diameters):** OBS ≈ 14.1 M (hourly ERA5), 3-km CTL ≈ 5.8 M, 3-km TUNE ≈ 0.7 M, 13-km ≈ 6 M each, 25-km ≈ 3.2 M, 100-km ≈ 2.0 M.

**Environment inputs**

| source | stream / layout | facts found |
|---|---|---|
| 3-km CTL (coarsened to ne30pg2, 21 600 cols) | `…3hourlyINST_ne30pg2` 8 rec/file, `…6hourlyINST_ne30pg2` 4 rec/file, NETCDF3 | 4 129 `.nc` files per stream 1994-10-01…2006-01-21 (only the 3 noleap Feb 29 absent). **Oct-1994 files start at 00:00 (`-00000`), later ones at 03:00 / 06:00** and end with the next-day 00:00. Extra `.nc~`, `.nc~~`, `.rhist.` files. **Empty files (0 records): 3-h 2002-12-10, 2003-06-28, 2004-05-14, 2006-01-21; 6-h the same plus 2001-07-18.** RH is a fraction; `lat`/`lon` say `rad` but are degrees; `area` sums to 0.0108 not 4π (constant factor: relative weights only); T/RH/omega at 850 hPa masked in 500 cells |
| 3-km TUNE (Cess2) | `output.3hi_ne30pg2` 584 daily files 2019-08-01…2021-03-06; `output.3hi_ne120pg2` 254 files …2020-04-10 | same variable names as the decadal 3-h on ne30pg2; `prw` only from the ne120pg2 stream (above) |
| 25-km | `E3SMv3_ne120.eam.h1.*` hourly, 24 rec/file, 3.3 GB, 345 600 cols | 1 208 days 2009-01-01…2012-04-23; Q850, RH850, T500, Q500, TMQ, OMEGA500, PRECT, **PS**; RH500 and OMEGA850 are not output |
| 100-km | `ctl.fr.eam.h3.*` hourly, 24 rec/file, 21 600 cols | 7 666 days 2000-01-01…2021-01-01; RH850, TMQ, OMEGA500, PRECC, PRECL, **PS** (no PRECT, no Q500 in h2/h3/h4) |
| OBS (ERA5, 0.25°) | pl daily files (37 levels, chunk `[1,37,721,1440]`, zlib) + sfc monthly TCWV and SP (chunk `[27,139,277]`) | lat 90→−90, lon 0…359.75, hourly; Q/R 1.38 GB, W 1.75 GB per day → **4.5 GB/day, 2007-2017 ≈ 18.1 TB** (+0.28 TB margin months 2006-12, 2018-01; +0.16 TB TCWV; +0.16 TB SP) |

**Below-ground 850 hPa:** SCREAM masks (500 of 21 600 cells), **E3SM stores extrapolated numbers** (ne120: 15 446 of 345 600 cells have PS < 850 hPa, 2 822 of 168 192 in 30S–30N; RH850 there up to 141 %),
**ERA5 too** (Q850 over Tibet is filled). Hence the mask decision above.

**Circle search benchmark** (scipy `cKDTree`, 3-D unit vectors, 200 random tropical centres ≈ the MCS samples at one env time, r ≤ 300 km; identical to `query_ball_point`):

| grid | tree build | search, 200 circles | mean cells per circle at d = 200 / 400 / 600 km |
|---|---|---|---|
| ne30pg2 (21 600) | 0.01 s | 3 ms | **1.3 (2 % empty)** / 5.1 / 11.7 |
| ne120pg2 (345 600) | 0.15 s | 19 ms | 20.6 / 83 / 186 |
| ERA5 0.25° (1.04 M) | 0.5 s | 43 ms | 42.5 / 170 / 382 |

The circle search is negligible (3-km CTL ≈ 100 s CPU for all 32 k env times; ERA5 ≈ 1 h CPU for 96 k steps ÷ 64 workers): **the jobs are I/O-bound (ERA5: 18 TB to read).**

**q ↔ RH formulas vs E3SM ne120 (one time step, 850 hPa above ground):** `q850` from `T850`+`RH850` differs from the stored `Q850` by **+1.8…2.0 % mean, 5.5 % rms** (p99 26 %) for all three saturation
formulas (Bolton, Goff–Gratch, Murphy–Koop) and both RH definitions (q/qs, e/es); the formulas differ from each other by ≤ 0.2 %. `RH700` from `T700`+`Q700` is off by −2.2 %-pts mean, 5.5 rms.
Most likely T, Q, RH are interpolated to the pressure level independently (not verified). So the SCREAM `q850` derived from T and RH is an approximation (+2 % bias, a few % noise per cell that averages down
inside a circle); the 25-km `rh500` is computed from the same-level T and Q, which is the consistent direction.

---

### Design

#### A. Circle search (your issue 1) — one 3-D KD-tree per grid + batched sparse distance matrix
- Build once per grid: unit-sphere xyz of all cell centres → `cKDTree` (cubed-sphere, lat-lon, HEALPix, any unstructured grid; no pole/dateline/cube-edge special cases; angle units checked because SCREAM labels degrees as `rad`).
- For all samples of one env time: `cKDTree(centres).sparse_distance_matrix(grid_tree, chord(r_max), output_type='ndarray')` (**not** `coo_matrix`: it can drop exact zeros = a cell centre exactly at the circle centre).
  Smaller diameters are thresholds on the same distances (3 diameters cost one search).
- Weights: cell `area` (normalised; ERA5 uses cos φ); mean = `W @ V0 / W @ M` (two sparse matmuls; V0 = values with NaN→0, M = valid mask; float64). Masked cells (model fill values, **below-ground 850 hPa**)
  are excluded and `<var>_validfrac` (valid weight / total weight) is reported.
- **Empty circles** (2 % of the 200-km circles on ne30pg2): `empty_circle: nearest_cell` (default) uses the nearest cell; `nan` leaves NaN. `n_cells` is always stored (note: 200-km circles on ne30pg2 hold 1.3 cells on average, i.e.
  nearly point samples of the grid; use `n_cells` to filter). Rejected: HEALPix remap (extra lossy step), neighbour tables from snapped centres (error up to half a cell = 77 km on ne30pg2), per-sample `query_ball_point` loops.

#### B. Time alignment: nominal relative-time grid (the composite axis)
Per track (valid hourly points, first time t₀, last tₙ) and the source's step Δ (`step_hours`; null = the finest stream step: 3 h SCREAM, 1 h ERA5/E3SM):
- **Rows at nominal offsets k·Δ:** pre-start k = −24/Δ … −1 (circle fixed at the start position), in-track k = 0 … ⌊(tₙ−t₀)/Δ⌋ (circle at the track centroid at t₀+kΔ; if the track has a gap there, the nearest existing point, `track_dt_hours` ≠ 0).
  `time_offset_hours = kΔ` exactly for every track; `data_time = t₀ + kΔ`. Time 0 exists for every track and all tracks fall in the same bins.
- **Environment snapshot = nearest env time to `data_time`** (ties → earlier), per stream; `env_dt_hours = env time − data_time` ∈ [−step/2, +step/2). It is **constant per track** for a regular stream, so a track is
  shifted as a whole, never smeared. A frame farther than step/2 (missing file, empty day, record end) gives NaN, never the nearest frame.
- Worked example, 3-h env (00, 03, … 21), track 14:00–20:00: rows at offsets −24 … −3 (8 pre-start, circle at the 14:00 centroid), 0, +3, +6. Env times 15:00 / 18:00 / 21:00 (dt +1 h); a track starting 15:00 has dt 0, one starting
  16:00 has dt −1 h — all three contribute to the same bins 0, +3, +6.
- 6-h env: nominal 3-h rows map to the nearest 6-h time (|dt| ≤ 3 h; neighbouring rows can share a snapshot): 3-km CTL `prw`, stored as `env_dt_hours_<stream group>`.
- OBS: tracks at :30, ERA5 hourly: the tie goes to the earlier hour, so `env_dt_hours = −0.5` for all rows.
- NaN-position track rows are dropped before matching; tracks with gaps use the nearest existing point. No track filtering inside the extraction (you filter later with (period, local_track), e.g. your `filter_tracks_by_initiation`).
- Sample generation is vectorised (searchsorted + `np.repeat`), no per-track Python loops. Missing frames are counted per stream group and recorded (counts + first 200 times in the attributes); the job fails only if more than
  `max_missing_fraction` (0.05) of the rows lack a frame of the primary (finest) group. Secondary groups only report coverage (the Cess2 `prw` ends 2020-04-10).

#### C. Heterogeneous inputs (your issue 2) — config + file index + small readers
- `config/sources.yaml`: per source `tracks`, `grids` (name → kind, lat/lon/area names), `streams` (root, glob `pattern`, `reader`, `grid`), per stream `variables`: standard name ← raw name(s), `scale`, `units`,
  optional `level_hpa`, or `derive` (`sum`, `q_from_rh`, `rh_from_q`); source-level `ps` (stream + variable, Pa) used to mask every `level_hpa` variable where `ps < level` (SCREAM: `ps: null`, native fill values).
  Defaults: `diameters_km: [200, 400, 600]`, `pre_start_hours: 24`, `step_hours: null`, `weighting: area`, `empty_circle: nearest_cell`, `max_missing_fraction: 0.05`. One key with `null` = off, no flag + value pairs.
- **`FileIndex`** (format-agnostic): scans a stream once (thread pool, reads only `time`, cftime noleap → datetime), caches (path, mtime, size, record, time) next to the output and answers "which file/record holds time T".
  Daily/monthly/8-record/4-record layouts, shifted starts (`-00000` vs `-10800`), empty or partial files, duplicate backups (`.nc~` never matches `*.nc`) and calendars become irrelevant. Duplicate times: keep the later file, log it.
- **Streams are grouped by (grid, identical time axis)**; a group needs one circle search per env time (ERA5: q, r, w, tcwv, sp share one). A source may have several grids (Cess2: ne30pg2 + ne120pg2).
- **Readers** (≈ 3 classes, one `read(file, record, var) -> 1-D cell array` interface): `ncol` (SCREAM, E3SM), `latlon` (ERA5 sfc), `latlon_level` (ERA5 pl: level by value; **HDF5 chunk cache ≥ one chunk, ≈ 150 MB**, so 850 and 500 hPa
  decompress a chunk once; the monthly sfc files need the same). Direct `netCDF4`; fill/non-finite values → NaN. A zarr/HEALPix source = one more reader. Raw names live only in the YAML; the 13-km sources are added there when you know the paths.

#### D. Parallel architecture (one job per source-year)
1. Parent: load tracks of the requested `period` years; vectorised sample table (rows × diameters later); FileIndex + grids; per stream group the env record/`env_dt_hours` of every sample.
2. **Task = (stream group, one calendar day of env times)**. `multiprocessing` fork pool (`--nproc`, default `SLURM_CPUS_ON_NODE`); trees and index are inherited copy-on-write, each worker opens its own files
   (`HDF5_USE_FILE_LOCKING=FALSE`, `OMP_NUM_THREADS=1`).
3. Per env time in a task: read all variables of the group (one slice each), mask below-ground cells, build the sparse weights for the samples assigned to that snapshot, matmul, and write one part Parquet
   (`sample_id`, `n_cells`, per diameter and variable the mean and `validfrac`) with `pyarrow.parquet.write_table`.
4. Parent: assemble by `sample_id` (NaN where a group has no frame), sort by (period, local_track, time_offset_hours, diameter_km), write `mcs_env_<source>_<year>.parquet` once; `combine_mcs_env.py` writes
   `mcs_env_<source>_tropics_<y0>_<y1>.parquet`. Parts are removed after the checks pass.
5. Slurm: `gen_mcs_env_jobs.py` writes one script per source-year (1 node, `--exclusive`; array over years for ERA5); account asked at run time (m1867 default, m1657 if m1867 has no node-hours). **Nothing is submitted without your approval.**
   Wall times are estimates until measured (compute is minutes per year; ERA5 reading dominates; `step_hours: 3` would cut it 3× if hourly ERA5 is not needed).

#### E. Output Parquet (zstd level 3, row groups ≈ 1 M rows, dictionary for `period`), long format
One row per (track, nominal time, diameter), so the schema does not depend on the diameter list and files from different runs concatenate (like the old `radius` column).

| column | type | meaning |
|---|---|---|
| `period`, `local_track` | str, int64 | track key (as in the MCS stats file) |
| `time_offset_hours` | float32 | nominal offset k·Δ from the track start (… −Δ, 0, Δ …): **the composite axis, same grid for all tracks** |
| `data_time` | timestamp[ms, UTC] | nominal time = start + offset (old schema name) |
| `track_time`, `track_dt_hours` | timestamp, float32 | track point used for the centre (+ key = join to the track stats `base_time`); `data_time − track_time` (0 unless a gap) |
| `center_lat`, `center_lon` | float32 | circle centre = track `meanlat/meanlon` at `track_time` (start position for offsets < 0), lon as in the track file |
| `diameter_km` | int16 | circle diameter |
| `env_dt_hours` (+ `env_dt_hours_<group>`) | float32 | env snapshot time − `data_time`, NaN when the frame is missing |
| `n_cells` (+ `n_cells_<grid>`) | int32 | cells in the circle on that grid (≥ 1 with the nearest-cell fallback) |
| `<var>`, `<var>_validfrac` | float32 | area-weighted mean over valid cells; valid weight fraction |

Per-column Parquet field metadata: `units`, `long_name`, raw source variables, conversion. File-level key `mcs_env` (JSON): source label, config snapshot, diameters, weighting, Earth radius 6371 km, matching rules,
stream steps, sample counts, missing-frame counts/times and per-group coverage, track file + row count, input index summary, code git hash, library versions, creation time. `outputs.read_mcs_env(path)` returns a
DataFrame with `df.attrs` filled from it; `outputs.to_variable_frame(df, var)` returns (`track_id`, `radius` [= diameter_km], `time_offset_hours`, `mean`) for `tools_mcs_stats.py`.

#### F. Standard variables (units: prw kg m-2, q850 kg kg-1, rh %, omega Pa s-1, pr mm h-1 instantaneous)

| std | OBS (ERA5 1 h) | 3-km CTL (3 h + 6 h) | 3-km TUNE (3 h; prw 3 h on ne120pg2) | 25-km (1 h) | 100-km (1 h) |
|---|---|---|---|---|---|
| `prw` | TCWV | VapWaterPath (6-h stream) | VapWaterPath (`3hi_ne120pg2`, to 2020-04-10) | TMQ | TMQ |
| `q850` | Q @850 | from T_mid_at_850hPa + RH850 | same | Q850 | — |
| `rh850` | R @850 | RelativeHumidity_at_850hPa ×100 | same | RH850 | RH850 |
| `rh500` | R @500 | RelativeHumidity_at_500hPa ×100 | same | from T500 + Q500 | — |
| `omega850` | W @850 | omega_at_850hPa | same | — | — |
| `omega500` | W @500 | omega_at_500hPa | same | OMEGA500 | OMEGA500 |
| `pr` | — | (precip_liq + precip_ice) × 3.6e6 | same | PRECT × 3.6e6 | (PRECC + PRECL) × 3.6e6 |
| mask (`level_hpa` vars) | SP (`128_134_sp`) | native fill values | native fill values | PS | PS |

Saturation vapour pressure: one formula (Murphy–Koop over liquid), RH as q/qs like CAM/EAM/EAMxx. ERA5 `R` (%) and `W` (Pa s-1) units are verified from the file attributes at implementation.

#### G. ERA5 copy (you run it with your own Globus login; I only write the scripts, I cannot authenticate Globus here)
`era5_copy/make_era5_globus_script.sh YEAR0 YEAR1`, in the style of your 2021 `make_era5_3d_filelist_4globus.sh`: per year it writes the monthly file lists (pl: `128_133_q`, `128_157_r`, `128_135_w`; sfc: `128_137_tcwv`,
`128_134_sp`) and `globus_copy_<year>.sh` with `mkdir -p` + `transfer_files.py -s dtn -t dtn -d <dir> -i <list> -p` per month and type (24 tasks per year, below Globus' 100-pending limit; 2006-12 is added to the 2007 script and
2018-01 to the 2017 script). Layout mirrors CFS: `/pscratch/sd/w/wcmca1/ERA5/e5.oper.an.{pl,sfc}/YYYYMM/` (group-writable, setgid; files owned by feng045). Pre-flight in the generator: every source file exists (stops otherwise),
planned bytes vs `lfs quota -u $USER`. `verify_era5_copy.sh` compares counts and byte sizes against CFS.
**`era5_copy/README.md` (new, short step-by-step following docs.nersc.gov/services/globus):** (1) `module load globus-tools` (loads a Python module: do not mix with `conda init`); (2) check that your NERSC account is linked:
`globus get-identities <nersc_user>@nersc.gov` (a UUID = linked, `NO_SUCH_IDENTITY` = link it first); (3) `bash make_era5_globus_script.sh 2007 2007`; (4) `bash globus_copy_2007.sh` — the first `transfer_files.py` call prints a URL, log in
with Globus in a browser and paste the code back (token stored in `$HOME`); (5) monitor with `check_transfers.py` (last 10 transfers, `-d` details, `-i <task id>`) or the Globus web app; (6) `bash verify_era5_copy.sh 2007`; (7) repeat per year
(limits: 3 active and 100 pending tasks per Globus user, so one year per call; a failed month is rerun by running its two lines again); (8) quota/inode note. Start with 2007 (+2006-12, ≈ 1.8 TB), then the other years.
Whole 37-level files are copied (Globus cannot subset levels).

---

### Files to create (in `scream/`)

```
mcs_environment/
  README.md                      usage, schema, config guide, how to add a source, validation numbers
  config/sources.yaml            7 sources (13-km blocks commented until paths are known)
  mcsenv/{config,grid,tracks,fileindex,readers,derive,extract,outputs}.py
  extract_mcs_env.py             CLI: --source --years Y0 Y1 [--diameters-km ...] [--nproc] [--start-date/--end-date] [--out-dir]
  combine_mcs_env.py             per-year files -> multi-year file
  gen_mcs_env_jobs.py + slurm_template.sh
  check_mcs_env_output.py        post-run checks by outputs (not exit code)
  era5_copy/{make_era5_globus_script.sh, verify_era5_copy.sh, README.md}
tests/test_mcs_env_*.py          pytest, synthetic netCDF built in tmp_path
docs/PLAN_mcs_environment.md     this plan verbatim + original request + PROGRESS LOG (your pattern)
```
Patterns reused (not imports): time batching and Parquet columns from `get_env_vars_time_batching.py`; `check_missing_frames` + exact matching from `extract_etc_2d_vars.py`; zstd Parquet as in
`scripts/combine_filter_mcs_trackstats.py`. All new code follows your rules: a comment above every major block and sub-section, docstrings with inputs/outputs/defaults for every function.

### Implementation steps
0. Save this plan verbatim into `scream/docs/PLAN_mcs_environment.md` (+ progress log).
1. Library + unit tests on the login node (small data only).
2. `sources.yaml` for 3-km CTL, 3-km TUNE, 25-km, 100-km, OBS; ERA5 scripts + README written (not run).
3. Interactive CPU node (own `salloc`, account m1867 or m1657): formula validation, one month per source, brute-force cross-check, composite-alignment check, scaling test (nproc 1 vs 32 vs 128).
4. You run the ERA5 copy (2007 first); I verify it, run the ERA5 test month and check against an independent reader.
5. Generate Slurm scripts; **ask before submitting**; production runs; `check_mcs_env_output.py`; combine; README/docs; memory notes.
6. 13-km CTL/TUNE added when you send the paths and variable names.

### Verification
- **Unit tests:** circle membership vs brute-force haversine (random centres incl. poles, dateline, unwrapped lon ±200, a centre exactly on a cell centre); weighted mean with NaN/masked cells; below-ground mask (`ps < level`);
  **alignment table (Δ = 1/3/6 h, :00 and :30 tracks, start hours 0…23: every track has offsets exactly k·Δ, a row at 0, |env_dt| ≤ Δ/2, ties → earlier)**; tracks with gaps, NaN positions, at record start/end; FileIndex on
  synthetic layouts (daily 8-rec, 4-rec, monthly hourly, 1-rec, shifted start, empty/partial file, `.nc~` duplicate); streams on two grids; unit conversions; `q_from_rh`/`rh_from_q` round trip; Parquet metadata round trip;
  part-file restart (a deleted part is recomputed, finished parts are kept).
- **Real data:** (a) formula table above reproduced on several ne120 times; (b) per source, 30 random output rows recomputed independently (xarray + haversine) and compared (rtol 1e-5), `n_cells` identical; (c) `nproc=1` vs
  `nproc=32` give identical tables; (d) `check_mcs_env_output.py`: key uniqueness, row count = expected sample count from the track file, **`groupby('time_offset_hours')` counts equal the number of live tracks in every bin and only
  multiples of Δ occur**, non-NaN share per variable and per phase (pre-start vs in-track), `n_cells`/`validfrac` distributions, value ranges (rh 0–120 %, prw 0–90, |omega| < 10, pr ≥ 0), every (period, local_track) of the
  track file present, missing-frame counts match the known gaps (SCREAM-decadal empty days, 25-km record start, Cess2 `prw` end 2020-04-10), join to the track file on (period, local_track, track_time) = 100 %.
- **ERA5:** `verify_era5_copy.sh` (counts and sizes), then one extracted month compared with an independent reader, including the `sp` mask over the Tibetan Plateau and the Andes.

### Assumptions to confirm (defaults used unless you say otherwise)
1. "MCS start" = first track row (`relative_step` 0), consistent with your notebook's time 0.
2. The circle sits on the track centroid at the *nominal* time while the field is the nearest env snapshot (up to 1.5 h / 3 h away, stored in `env_dt_hours`), as in your old workflow; centring the circle at the env time instead
   would keep field and circle simultaneous but would shift the relative-time label — a one-line change later if you prefer it.
3. Circle = cell centres within great-circle distance ≤ diameter/2, area-weighted mean, nearest-cell fallback when empty; 200-km circles on ne30pg2 are nearly single cells.
4. `pr` = liquid + ice (the files hold both; you listed only liquid).
5. ERA5 stays hourly (`step_hours: null` → 1 h); `step_hours: 3` would match the SCREAM sampling and cut the ERA5 reading 3×.
6. 3-km TUNE keeps the ne30pg2 stream for everything except `prw`; the 3-D fields on ne120pg2 could give all variables on the finer grid by vertical interpolation to 850/500 hPa, not planned.
7. `q850` from RH/T carries the +2 % / 5 % noise above; ERA5 `R` is mixed-phase (IFS) while E3SM/EAMxx RH is liquid-only, so `rh500` differs by definition at 500 hPa (recorded in the attributes, not harmonised).
8. Outputs on `/pscratch/sd/f/feng045/mcs_env/<source>/`; nothing is written to CFS without your request.


## Reference index

| what | where |
| --- | --- |
| Reference MCS-environment workflow (HEALPix Zarr) | `/global/u1/f/feng045/program/waccem/gsrm_mcs_environments/extract_environments/get_env_vars_time_batching.py` |
| ETC 2D extraction (exact time matching, `check_missing_frames`) | `/global/u1/f/feng045/program/waccem/gsrm_cooccurrencefeature/extract_environments/extract_etc_2d_vars.py` |
| User's analysis of the old outputs (composites by `time_offset_hours`) | `waccem/gsrm_mcs_environments/analysis/analyze_envvars_evolution.ipynb`, `tools_mcs_stats.py` (`evolution_by_radius`, `plot_correlation_matrix`) |
| 2021 ERA5 Globus list generators | `waccem/era5/scripts/make_era5_3d_filelist_4globus.sh`, `make_era5_2d_filelist_4globus.sh` |
| MCS track Parquet files (7 sources) | listed in "The original request" |
| NERSC Globus docs | https://docs.nersc.gov/services/globus/ (`module load globus-tools`, `transfer_files.py`, `check_transfers.py`); collaboration accounts need a dedicated endpoint (ticket), `collabsu` is not available on Perlmutter |
| Globus limits | 3 active and 100 pending transfer tasks per user (docs.globus.org FAQ) |
| Cess2 environment streams | `/pscratch/sd/w/wcmca1/SCREAMv1-cess2/run/output.3hi_ne30pg2`, `.../output.3hi_ne120pg2` (to 2020-04-10) |

## Progress log (newest at the bottom)

- 2026-11-20 plan approved after one review round (see the plan's "Your review comments" section). Facts measured read-only before the plan (all in the plan): track Parquet structure, environment file layouts of
  all sources, KD-tree benchmark, q/RH formula check on E3SM ne120, below-ground 850 hPa handling, ERA5 sizes, feng045 pscratch quota (49.5 of 100 TB, 3.65 M of 10 M files). Step 0 (this file) done.
- 2026-11-20 22:40 steps 1-2 DONE (uncommitted, nothing pushed). New in `scream/`: `mcs_environment/` (`mcsenv/{config,derive,grid,tracks,fileindex,readers,extract,outputs}.py`, `extract_mcs_env.py`,
  `combine_mcs_env.py`, `gen_mcs_env_jobs.py` + `slurm_template.sh`, `check_mcs_env_output.py`, `validate_humidity_formulas.py`, `config/sources.yaml`, `era5_copy/{make_era5_globus_script.sh,
  verify_era5_copy.sh,era5_common.sh,README.md}`, `README.md`) and `tests/test_mcs_env_core.py` + `test_mcs_env_pipeline.py` (**30 tests pass**: circles vs haversine, alignment, file layouts, an end-to-end run on
  synthetic files compared row by row with a brute force, serial = parallel, restart, guard). Design changes made while coding (all small): `n_cells` is per GRID (filled by any group on that grid, 0 = no frame
  anywhere on that grid), `track_dt_hours` = nominal time clamped to the track minus `track_time`, `period` is a dictionary column, the track-start filter is stored in the file metadata (`track_start_range`).
  ERA5 generator tested on the real CFS listing (2007: 1,309 files, 1.97 TB, 28 tasks; quota check works; 29-day February OK); verify script returns status 1 on an uncopied year.
- 2026-11-20 22:40 REAL DATA on my interactive node (job 61719424, nid200021, account m1867, 4 h, ends about 02:25; scripts and logs in `/global/homes/f/feng045/.claude_tmp_verify/mcs_env/`, outputs in
  `/pscratch/sd/f/feng045/mcs_env_dev/`, NOT the production folder). One month each (64 workers): 100-km Jan 2010 (12,422 samples, 16 s incl. a 9 s scan of 7,666 files), 25-km Jan 2010 (83,957 samples, 13 s),
  3-km CTL Jan 1996 (45,416 samples, two groups, 13 s), 3-km TUNE Jan 2020 (36,156 samples, two grids, 7 s): **every structural check passes and 240 / 360 / 420 / 420 independently recomputed values
  (60 random rows each) agree**. ERA5 read straight from CFS (Jan 2007, 72 tracks, 3,106 samples, 16 workers, 53 s; one day of snapshots about 45 s of one core: decompression and reads dominate).
  `validate_humidity_formulas.py` (7 E3SM times): q850 from T, RH is +1.6 % (0.9-2.5) with 5.0 % rms against the stored Q850, RH700 from T, Q is -1.8 %-pts with 5.0 rms. Data facts found: 7 / 3 duplicate times
  on 1994-10-31 (files `-00000` and `-10800` overlap; file modified last used; outside the MCS record), empty days as listed in the plan. The hook blocks `rm` with a shell variable and foreground `sleep`.
  NEXT: ERA5 check + scaling results, full-record runs of the 4 non-ERA5 sources into `mcs_env_dev` with combine + checks, then ask the user about finalizing / Slurm; the user runs the ERA5 copy (2007 first).
- 2026-11-20 22:46 more validation. ERA5 from CFS (Jan 2007, tracks that start 3-4 Jan: 72 tracks, 3,106 samples): all structural checks pass, 240 independently recomputed values (40 random rows) agree (OBS runs as ONE group:
  q, r, w, tcwv, sp share one circle search). Scaling on 25-km Jan 2010 (31 day-tasks): 220 s / 36 s / 16 s / 17 s for 1 / 16 / 64 / 128 workers, output identical bit for bit. Added tests: CLI + track-file reading +
  date filter + overrides, checker (passes a good file, fails a changed value and a duplicated row), combine (two years, refuses files made with other settings), ERA5 shell scripts on a fake CFS tree (generator lists,
  skips complete files, relists wrong sizes, stops on missing sources; verify exit codes): **38 tests pass in total**. `mcs_environment/.gitignore` ignores `__pycache__/` and generated `slurm/` and `era5_copy/list_*`.
  Full-record staging runs of 100km 2009-2020, 25km 2009-2011, 3km_CTL 1995-2005, 3km_TUNE 2019-2021 started 22:44 into `/pscratch/sd/f/feng045/mcs_env_dev/full/` (extract, check 20 rows each year, combine).
- 2026-11-20 23:00 BUG FOUND BY THE REAL DATA AND FIXED: the first full 100-km run reported 473 / 514 / 353 samples without a snapshot, all on 29 February of 2012 / 2016 / 2020. Cause: E3SM and SCREAM use a noleap
  calendar (and so do their tracks: 0 track rows on 29 Feb), but my time arithmetic ran on epoch seconds (a Gregorian axis), so "24 h before 1 March" fell on a non-existent 29 February and a track that crosses the
  leap day (consecutive rows 25 h apart in labels) was stretched by 24 h. Affected: 100-km 2012: 12 crossing tracks and 12 tracks starting on 1 Mar; 3-km CTL 1996: 163 tracks starting on 1 Mar (0 crossing). Checked before
  fixing: the track labels are NOT shifted (the correlation of environment `pr` with the track `pf_rainrate` after February in 2012 is like the non-leap control year 2013). Fix: `mcsenv/modelcal.py` (`to_model_axis`,
  `to_labels`, `leap_day_labels_present`), `FileIndex.calendar` (cache version 2), `extract.py` converts track times and snapshot axes to the model axis for a noleap source and the output times back to labels
  (file metadata `calendar`), a track file with 29 Feb for a noleap model is refused, checker made calendar-aware, version 1.1.0. Tests: model axis contiguous/invertible over a century, samples across the leap day,
  index calendar kinds, an end-to-end run around 29 Feb 2000 against a brute force that counts MODEL HOURS (a mutation test without the conversion fails), refusal of 29 Feb tracks: **43 tests pass in total (45 after the fail-fast test)**.
  Real data after the fix: 100-km 2012 has 0 of 169,356 samples without a snapshot and passes all checks. Staging re-run of the four sources started 22:55 into `/pscratch/sd/f/feng045/mcs_env_dev/full2/`
  (the first run, `full/`, used the old arithmetic and was stopped; ignore it).
- 2026-11-20 23:10 STAGING COMPLETE (node 61719424 released). Full records of the four sources whose environment data exist, extracted with the corrected (model-axis) code with 128 workers into
  `/pscratch/sd/f/feng045/mcs_env_dev/full2/<source>/` (NOT the production folder): 100km 2009-2020 (12 files, 94 MB, combined 6.03 M rows, extraction 110 s), 25km 2009-2011 (3 files, 214 MB, combined 9.63 M rows, 238 s),
  3km_CTL 1995-2005 (11 files, 434 MB, combined 17.70 M rows, 92 s), 3km_TUNE 2019-2021 (3 files, 53 MB, combined 2.24 M rows, 21 s). **29 of 29 yearly files pass every structural check; 3,244 independently
  recomputed values (20 random rows per year; 100 rows on the full 25-km 2010 file) have 0 mismatches.** Missing snapshots are exactly the known gaps and nothing else: 25-km 2009 970 samples (0.09 %, tracks starting in the first
  24 h of the record), 3-km CTL the empty SCREAM days (2001 6-h stream only 1,247; 2002 1,623; 2003 850; 2004 1,520; 0 in the leap years 1996 and 2000), 100-km none, 3-km TUNE `prw` (ne120pg2) 74 % in 2020 and 100 % in 2021
  (stream ends 2020-04-10; the checker warns instead of failing for a group without any snapshot in the period). Plausibility: the 100-km composite by time since initiation is physically sensible (prw and rh850 rise before
  the start, omega500 peaks at +3 h, pr jumps at 0) and every track has a row in each bin from -24 h to +3 h; on 3-km CTL 1996 the 3-hourly snapshot shift is -1/0/+1 h for a third of the tracks each and constant per track.
  ERA5 (CFS, Jan 2007): synthetic tracks over the Tibetan Plateau and the Amazon through the whole pipeline: all 850 hPa variables are NaN over Tibet (validfrac 0), 500 hPa and prw valid, Amazon all valid.
  Fail-fast fix in `run_tasks` (a failing task terminates the pool at once) with a test: 45 tests pass. `mcs_env_dev/full` (first run, old arithmetic) and the small test folders there can be deleted by the user.
  OPEN: (1) the user runs the ERA5 copy (`era5_copy/README.md`, 2007 first) -> then the OBS test month, the checker on it, and the production array (`gen_mcs_env_jobs.py --source OBS --years 2007 2017`, ask before submitting);
  (2) 13-km CTL/TUNE paths and variable names; (3) the user decides whether the four staged sources are promoted to `$SCRATCH/mcs_env` (a rename) and/or copied to CFS; (4) nothing is committed.
- 2026-11-20 23:45 ERA5 COPY, first run by the user: `globus_copy_2007.sh` on the Perlmutter login node failed in every `transfer_files.py` call with `AuthAPIError ... 400 Bad Request` (POST auth.globus.org/v2/oauth2/token,
  in `activate_token` -> `RefreshTokenAuthorizer`). Diagnosis from the helper's source (`/global/common/software/nersc9/globus-tools/1.0/bin`, `nersc_globus_tools/token_management.py`; token FILES not read, only their names and
  dates): the helper keeps its OWN tokens in `~/.globus/transfer.json` and `~/.globus/<collection>.<collection>.json`, separate from the `globus` CLI login (`~/.globus/cli`); the user's files dated 2024-02-09 are rejected by Globus
  (the DTN<->DTN token file does not exist yet, so the helper refreshes the old `transfer.json`). `transfer_files.py --renew` is parsed but never used in this module version; the supported fix is
  `generate_token.py -s dtn -t dtn --renew` (deletes the old tokens, asks for a login URL + code, up to twice). The user asked whether the script must run on a DTN: no, `transfer_files.py` is only a client that submits a task to the
  Globus service (`submit_transfer`) and prints the task id; `dtn` in `-s dtn -t dtn` names the NERSC DTN collection, not the machine it runs on, so the login node is right. Changes: `era5_copy/README.md` new step 3 (renew the
  tokens), steps renumbered, a Troubleshooting section; the generated runner now has `set -e` (stops at the first failed call instead of 28 tracebacks) and a comment with the fix; the test checks both.
- 2026-11-21 00:05 ERA5 2007 COPIED by the user (after `generate_token.py -s dtn -t dtn --renew`): `verify_era5_copy.sh 2007 2007` = 1,309 files, 0 problems (2006-12 .. 2008-01 incl. SP). Globus facts measured with a read-only
  task listing through the helper's client: the 28 tasks took 7-22 s each (mean 14 s), 1.97 TB, 0 faults, at most 4 in flight, the whole copy 2.5 min (about 14 GB/s). **Why `check_transfers.py` showed no new task:** its default
  listing (`task_list(limit=10)`, no `orderby`) returns the OLDEST tasks (here the September copies); the user's history holds 75 tasks and the ERA5 ones are the newest; `check_transfers.py -n 200 -p | tail -30` shows them
  (both stored tokens belong to the same account). Answer to "can all years be queued": yes, back to back (`for y in $(seq 2008 2017); do bash globus_copy_$y.sh || break; done`), tasks finish about as fast as they are
  submitted; Globus limit 3 active + 100 pending per user; remaining about 17 TB, about 20-30 min. README step 5 / 8 and the troubleshooting list were updated, the runner header names the right monitoring command.
  OBS 2007 extraction from the copy: see the next entry.
- 2026-11-21 00:16 OBS 2007 EXTRACTED FROM THE USER'S COPY (node 61722455, released): `extract_mcs_env.py --source OBS --years 2007 2007 --nproc 128` -> `/pscratch/sd/f/feng045/mcs_env_dev/full2/OBS/mcs_env_OBS_2007.parquet`
  (88.6 MB): 30,638 tracks, 1,276,923 samples, 3,830,769 rows, 0 samples without a snapshot, 366 day-tasks, **11 min 52 s wall with 128 workers** (I/O bound: user 425 min, sys 230 min; the index of the copy takes 5 s).
  Checker: every structural check passes (288 offset bins = live tracks, join to the track file 100 %), NaN share of the 850 hPa variables 0.1 % (circles entirely below ground), ranges fine, **240 independently recomputed values
  (40 random rows) 0 mismatches**. Production estimate for OBS 2007-2017: about 12 min per year and node, so a Slurm array of 11 nodes takes about 15 min wall (`gen_mcs_env_jobs.py --source OBS --years 2007 2017 --account m1867
  --time 00:30:00`; ask the user before submitting); `--step-hours 3` would cut the I/O about 3x. Test suite now 46 tests (runner stops at the first failed transfer call). NEXT: the user submits 2008-2017 (README step 8),
  `verify_era5_copy.sh 2008 2017`, then OBS production with approval; 13-km paths still open.
- 2026-11-21 00:25 OBS 2007 composite on the nominal grid (400 km circles, `groupby('time_offset_hours')` as in `evolution_by_radius`): all 30,638 tracks sit in every bin from -24 to +3 h (28,994 at +6 h, 19,506 at +12 h, 5,414 at +24 h:
  tracks end); prw 51.17 (-24 h) -> 53.40 (0 h) -> 54.35 kg m-2 (+12 h), q850 0.01250 -> 0.01291, rh850 81.4 -> 84.8 %, rh500 62.7 -> 68.8 %, omega500 -0.075 -> -0.133 (0 h) -> -0.161 Pa s-1 (+3 h), then about -0.16; the omega500
  signal grows as the circle shrinks (0 h: -0.165 / -0.133 / -0.110 for 200 / 400 / 600 km). Same shape as the 100-km model composite. Bins after the start lose tracks (survivorship), so read them as lifecycle means, not as
  one fixed sample. Node 61722455 cancelled (sacct CANCELLED, no job left in squeue).
- 2026-11-21 11:40 COMPOSITE NOTEBOOK + OBS 2007-2017 (request: environment composites by land / ocean with the robust-MCS filter of Paccini et al. 2026, compared with `analyze_envvars_evolution.ipynb`; all OBS years extracted meanwhile).
  Plan approved with two comments (split / merge test = `isnan(start_split_cloudnumber) & isnan(end_merge_cloudnumber)`; OBS extraction on interactive nodes). Plan file: `~/.claude/plans/mcs-environment-analysis-serene-emerson-of-35683c9b-...md`.
  * **OBS 2008-2017 extracted** on two own interactive nodes (61743257 nid200051, 61743258 nid200028, both released): `.claude_tmp_verify/mcs_env/run_obs_all.sh` / `run_obs_range.sh` (one year at a time with 128 workers, the checker after each year). I stopped the sequential loop after 2008
    and split 2009-2013 / 2014-2017 over the two nodes (the interrupted 2009 resumed from its part files). 11 yearly files, 29,155-31,704 tracks and 3.68-3.98 M rows each, 0 samples without a snapshot, every year ALL CHECKS PASSED (120 values, 0 mismatches; 2007: 240), 11-12 min per year
    (14 min with both nodes reading ERA5). Combined: `full2/OBS/mcs_env_OBS_tropics_2007_2017.parquet` (42,341,919 rows, 980 MB).
  * **Notebook** `scream/Notebooks/analyze_mcs_env_composites_land_ocean.ipynb` (uncommitted; built by a scratchpad script, executed in place with `jupyter nbconvert`, kernel pyflex26_3, 47-51 s, 4.4-4.8 GB): joins track stats and env files (track file from the env metadata), `summarize_tracks` +
    `apply_criteria` (tropics; first 2 steps non-MCS; one unbroken MCS block; the user's split / merge test; rain peak in MCS; duration <= p95 per source and surface), ocean = lifetime-max `pf_landfrac` < 0.1 / land = min > 0.9 (the user's convention), 400-km circles, funnel and variants tables,
    Fig. 4 / Fig. 5 styles (PDFs at initiation; median with the ERA5 IQR) for ocean and land, mean version, ocean-vs-land overlay, key numbers, a notes cell with the comparison. Output (figures, `composites_{ocean,land}.csv`, `robust_tracks_<source>.parquet`): `/pscratch/sd/f/feng045/mcs_env_dev/figures/`.
    Robust tracks (ocean / land): ERA5 2007-2017 35,107 / 31,404; 3-km CTL 23,570 / 27,702; 3-km TUNE 3,933 / 3,197; 25-km 901 / 1,183; 100-km 739 / 895 (OBS 2007 alone: 3,116 / 2,711, as the prototype on the track files).
  * **Tests** `scream/tests/test_mcs_env_notebook.py` (13: the tagged function cells on synthetic tracks, every criterion removes a known track, loading / matching / masking, composites, figures as 24-bit PNG); a mutation check (10 deliberate changes of the notebook code) is caught every time. Whole suite: 59 passed.
  * **Verification against Laura's code and data** (`.claude_tmp_verify/mcs_env/verify_vs_paccini.py`, `compare_figure.py`, `variant_composites.py`; read-only): her `MCS_filter` on her dense track files reproduces her pickles (SCREAM 1,936, ERA5 2,825; she used 3 initial non-MCS steps, the paper says 2), and `select_robust_tracks` with her options gives
    exactly the same track lists (0 differences, both sources); `filter_tracks_by_initiation` of `tools_mcs_stats.py` equals the notebook quantities (27,986 tracks); `composite_by_offset` equals `evolution_by_radius` (mean and bin counts) for all her variables. Her ERA5 RH850 / RH500 folders are EMPTY on her scratch (not compared).
  * **Result** (median, ocean, 0 / +6 / +12 h; the figure `compare_with_paccini_{mean,median}_ocean.png` in the figure folder): 3-km CTL against her SCREAM Cess1: TCWV -2 / -3 / -3 %, RH850 -1 %, Qv850 +2 / 0 / 0 %, omega850 +8 / -6 / -6 %, RH500 +7 %, omega500 ascent +16 % stronger at 0 h and 20 / 40 % weaker at +6 / +12 h;
    ERA5 2007-2017 against her ERA5 2020: TCWV -0.3 / -0.4 / -0.5 %, Qv850 -1 / -1 / 0 %, omega850 -9 / -10 / -4 %, omega500 15 / 9 / 14 % weaker ascent. The omega500 difference after initiation: her 3 initial steps explain a small part (3-km CTL +6 h: -0.099 -> -0.109, hers -0.123), the circle size matters a lot
    (omega500 at 0 h -0.161 / -0.067 / -0.036 for 200 / 400 / 600 km; her 2 deg radius = 444 km gives about -0.057 to -0.060, hers -0.058), the rest is probably the different track sets / periods. The repository criteria change the ocean track numbers by -7 % (ERA5) / -11 % (3-km CTL) / -66 % (100-km), the land numbers by -24 / -46 %.
  * Open: Laura's repo update (rescan, the variants table shows the effect of each change); 13-km paths; promotion of the staging folder; nothing committed.
- 2026-11-21 12:50 PROMOTION + GRID STYLE + COMMIT (user request). **Staging folder promoted**: `mv /pscratch/sd/f/feng045/mcs_env_dev/full2 /pscratch/sd/f/feng045/mcs_env` (production folder = default `--out-dir` of `extract_mcs_env.py`; same file system, so a rename; target did not exist) and `mcs_env_dev/figures` -> `mcs_env/figures`.
  Checked against an inventory taken before: 56 files with identical names and sizes, 0 Parquet footers with a row count different from the extraction metadata; combined files OBS 2007-2017 42,341,919 rows, 3-km CTL 17,695,566, 100-km 6,028,419, 25-km 9,633,204, 3-km TUNE 2,239,533. Nothing written to CFS.
  `mcs_env_dev` still holds the superseded `full` (first run, old arithmetic), the small test folders (`100km`, `25km`, `3km_CTL`, `3km_TUNE`, `OBS`, `leapfix`, `scaling_n*`) and `nb_dev` (development copy of the notebook, `paccini_reference_composites.csv`): for the user to delete.
  Notebook: `ENV` = production folder, `figdir` = `mcs_env/figures/`; **time-series plots (median with shading, mean, ocean-vs-land overlay): dashed grid (`0.55`, `--`) drawn above the shaded band and below the lines** (`axisbelow='line'`), the distributions keep the light solid grid; test added (mutation caught); notebook re-executed
  from the production folder (56 s, 4.4 GB), whole suite 59 passed. Commit: see the git log (branch `mcs-environment` of the scream repo; only the files of the MCS environment work).
- 2026-11-21 13:10 The user edited the notebook after the commit 3b21903: the grid of the plots is now dotted (`:`, `0.55`, width 0.5, alpha 0.75) and the distributions use it too (`_style_axes(ax, dashed_grid=True)` in all three plot functions). The test and the wording (docstring, README) follow the notebook; the parameter name `dashed_grid` was kept. The execution outputs of the notebook were re-saved by the user's Jupyter session.
