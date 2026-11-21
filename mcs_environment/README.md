# MCS environment extraction (SCREAM, E3SM, ERA5)

Environmental variables averaged inside circles that follow MCS tracks, for the 7 sources of the SCREAM / E3SM MCS evaluation
(OBS = ERA5, 3-km CTL, 3-km TUNE, 13-km CTL, 13-km TUNE, 25-km, 100-km). For every track and every circle diameter (default 200, 400, 600 km) the output is a time
series with **the same relative-time grid for every track** (offsets `k * step` from the MCS start), so tracks can be composited directly by time since initiation.
All variables of a source come from the same job. Plan, decisions and progress log: `docs/PLAN_mcs_environment.md`.

```bash
PY=/global/common/software/m1867/python/pyflex26.3/bin/python
cd /global/homes/f/feng045/program/scream/mcs_environment

# one source, one or more years (one Parquet file per year); use a compute node (salloc ... --qos interactive) for more than a test
$PY extract_mcs_env.py --source 3km_CTL --years 1995 2005 --nproc 128 --out-dir $SCRATCH/mcs_env
$PY check_mcs_env_output.py $SCRATCH/mcs_env/3km_CTL/mcs_env_3km_CTL_1996.parquet --brute-force 40      # checks by the contents of the file
$PY combine_mcs_env.py --source 3km_CTL --years 1995 2005 --dir $SCRATCH/mcs_env                       # one multi-year file
$PY gen_mcs_env_jobs.py --source 3km_CTL --years 1995 2005 --account m1867                              # writes slurm/slurm_mcsenv_3km_CTL.sh (no submit)
```

Useful options: `--diameters-km 200 400 600 800`, `--step-hours 3` (thin an hourly source such as ERA5 to 3 h), `--start-date/--end-date` (only tracks that start in that
range, for tests), `--max-missing-fraction`. Sources, paths, raw variable names and units are in `config/sources.yaml`.

## The rules (what a row means)

**Rows on a nominal relative-time grid.** For a track that starts at `t0` and ends at `tn`, with the step `Δ` of the source (3 h for SCREAM, 1 h for ERA5 and E3SM):

| rows | `time_offset_hours` | circle centre |
|---|---|---|
| before the start | `-24, -24+Δ, ..., -Δ` (24 h / Δ rows) | the start position (the first valid track point) |
| during the track | `0, Δ, 2Δ, ..., floor((tn-t0)/Δ) * Δ` | the valid track point nearest to `t0 + k·Δ` (ties: earlier); exact when the track has a point at that time |

`time_offset_hours` is the same grid for every track (a row at 0 and at -24 h exists for every track), so `df.groupby('time_offset_hours')` gives the composite by time
since initiation, with the number of live tracks in every bin. (A grid on the environment times would shift each track by its start hour modulo Δ.)

**Environment snapshot.** For every row the environment is the snapshot of each input stream that is nearest in time to the nominal time `data_time`, accepted only within
half a step of that stream (ties: the earlier snapshot; a shift of exactly +step/2 is rejected); otherwise the values are NaN, never the nearest other frame. The shift
`env_dt_hours = snapshot - data_time` is stored. It is constant for a track on a regular stream (a 3-hourly track starting at 14:00 sees 15:00, 18:00, ... with +1 h; one
starting at 15:00 sees 0 h; at 16:00 -1 h), at most 1.5 h for 3-hourly data and 3 h for 6-hourly data (3-km CTL `prw`), and -0.5 h for ERA5 against the :30 OBS tracks.
Example, 3-h data, track 14:00-20:00: rows at offsets -24 ... -3, 0, +3, +6 with centres at the 14:00 position (pre-start) and at the track position of 14:00, 17:00, 20:00.

**Circles.** A cell belongs to a circle when its centre is within `diameter / 2` (great circle, R = 6371 km) of the centre. The mean is weighted by cell area (`cos(lat)` for
ERA5) over the valid cells; `<var>_validfrac` is the valid weight divided by the total weight of the circle. A circle without any cell centre takes the nearest cell
(`empty_circle: nearest_cell`, `n_cells` = 1). **On the ne30pg2 grid (cells of about 154 km) a 200-km circle holds 1.3 cells on average and 68-70 % of the circles are one
cell; 400 and 600 km hold 5 and 12 cells. On ne120pg2 and ERA5 the 200-km circles hold 21 and 42 cells.** Use `n_cells` to filter.

**Calendars (29 February).** SCREAM and E3SM use a noleap calendar, and so do the MCS tracks made from them (no rows on 29 February: the hour after 28 February 23:00 is 1 March 00:00).
For a noleap source all time arithmetic (nominal times, durations, nearest snapshot) runs on the *model axis*, epoch seconds with every completed 29 February removed (`mcsenv/modelcal.py`), so that
"24 h before 1 March 03:00" is 28 February 03:00 and a track that crosses the leap day is not stretched by 24 h; the output carries the calendar labels of the model (never 29 February). ERA5 and the OBS
tracks use the standard calendar and are unchanged. A track file with times on 29 February for a noleap environment is refused. (Without this, in a leap year the 100-km E3SM run would have had 12 tracks
stretched by 24 h and 12 tracks starting on 1 March with their pre-start rows on a day that does not exist; the 3-km CTL 163 tracks starting on 1 March.) The file metadata records `calendar`.

**Pressure-level variables below the ground** (`level_hpa` in the configuration) are masked in every source: SCREAM stores fill values there, E3SM and ERA5 store
extrapolated numbers, so E3SM (`PS`) and ERA5 (`SP`, `128_134_sp`) are masked where the surface pressure is below the level.

## Output file

`<out-dir>/<source>/mcs_env_<source>_<year>.parquet` (zstd), long format: one row per (track, nominal time, diameter), sorted by period, local_track, time_offset_hours, diameter.

| column | meaning |
|---|---|
| `period` (str), `local_track` | track key, as in the MCS track Parquet files |
| `time_offset_hours` | nominal offset from the track start (h): the composite axis |
| `data_time` | nominal time = start + offset (UTC) |
| `track_time` | time of the track point used for the centre (join key to `base_time` of the track file); `track_dt_hours` = nominal time clamped to the track minus `track_time` (0 unless the track has no valid point at that time) |
| `center_lat`, `center_lon` | circle centre (track `meanlat`, `meanlon`; the longitude is unwrapped as in the track file) |
| `diameter_km` | circle diameter |
| `env_dt_hours` | snapshot time minus `data_time` of the primary (finest) stream group; one more column `env_dt_hours_<group>` for every other group (3-km CTL: `env_dt_hours_inst6h`; 3-km TUNE: `env_dt_hours_inst3h_ne120`); NaN = snapshot missing |
| `n_cells` | cells in the circle on the primary grid (>= 1; 0 where no group on that grid has a snapshot); `n_cells_<grid>` for another grid (3-km TUNE: `n_cells_ne120pg2`) |
| `prw`, `q850`, `rh850`, `rh500`, `omega850`, `omega500`, `pr` (per source) | the mean (units below); each with `<var>_validfrac` |

Units: `prw` kg m-2, `q850` kg kg-1 (the notebook's "g/g"), `rh*` %, `omega*` Pa s-1 (positive downward), `pr` mm h-1 (instantaneous). The Parquet field metadata holds `units`,
`long_name`, the raw source variables and the conversion of every column; the file metadata (key `mcs_env`, JSON) holds the source, rules, diameters, counts of samples, counts and
first times of missing snapshots per group, the index of the input files (empty and unreadable files, duplicate times), the full configuration, the git hash and library versions.

```python
import sys; sys.path.insert(0, '/global/homes/f/feng045/program/scream/mcs_environment')
from mcsenv.outputs import read_mcs_env, to_variable_frame
df = read_mcs_env('/pscratch/sd/f/feng045/mcs_env/3km_CTL/mcs_env_3km_CTL_1996.parquet')      # df.attrs['units'], df.attrs['mcs_env']
comp = df[df.diameter_km == 400].groupby('time_offset_hours')[['prw', 'rh850', 'omega500']].agg(['mean', 'count'])    # composite by time since initiation
frame = to_variable_frame(df, 'prw')       # track_id, radius (= diameter_km), time_offset_hours, data_time, mean: the layout of tools_mcs_stats.py
tracks = ...                                # join with the track statistics on (period, local_track, track_time == base_time)
```

## Sources and variables

| standard name | OBS (ERA5, 1 h) | 3-km CTL (3 h + 6 h) | 3-km TUNE (3 h) | 25-km (1 h) | 100-km (1 h) |
|---|---|---|---|---|---|
| `prw` | TCWV | VapWaterPath (6-h stream) | VapWaterPath of `3hi_ne120pg2` (to 2020-04-10) | TMQ | TMQ |
| `q850` | Q @850 | from T_mid_at_850hPa + RH850 | same | Q850 | - |
| `rh850` | R @850 | RelativeHumidity_at_850hPa x 100 | same | RH850 | RH850 |
| `rh500` | R @500 | RelativeHumidity_at_500hPa x 100 | same | from T500 + Q500 | - |
| `omega850` | W @850 | omega_at_850hPa | same | - | - |
| `omega500` | W @500 | omega_at_500hPa | same | OMEGA500 | OMEGA500 |
| `pr` | - | (precip_liq + precip_ice) x 3.6e6 | same | PRECT x 3.6e6 | (PRECC + PRECL) x 3.6e6 |
| below-ground mask | SP | native fill values | native fill values | PS | PS |

13-km CTL and 13-km TUNE: add a block to `config/sources.yaml` when the environment files are located (copy `3km_CTL`, set `tracks`, `root`, `pattern`, grid and variable names).

## Configuration (`config/sources.yaml`)

Raw names live only there. A source has `tracks`, `ps` (null or `{stream, var}`), `grids` (name -> `{stream, lat, lon, area}`) and `streams` (name -> `{root, pattern, reader, grid,
variables}`); a variable is `{from: <raw>}` or `{derive: sum | q_from_rh | rh_from_q, inputs: ...}` with `scale`, `offset`, `level_hpa`, `units`. Readers: `ncol` (cubed-sphere
`(time, ncol)`), `latlon`, `latlon_level` (level chosen by value). Defaults: `diameters_km`, `pre_start_hours`, `step_hours` (null = finest stream), `weighting`, `empty_circle`,
`max_missing_fraction`. **Layout independence:** `FileIndex` reads only the `time` variable of every file once (cached in `<out-dir>/<source>/_index`), so daily or monthly files, 1 to 24
records per file, files that start at 00:00 or 03:00, empty or partly written files, `.nc~` backups (the pattern ends in `.nc`) and `noleap` or `standard` calendars need no
code. Streams with the same grid and time axis share one circle search (a *group*); the first group (finest step) is the *primary* one.

## Method in one paragraph

Cell centres become unit vectors; one `cKDTree` per grid; for all samples that use the same snapshot one `sparse_distance_matrix` gives every (circle, cell) pair (no special case at
poles, the dateline or cube edges); weights and NaN cells are two sparse matrix products. Work is cut into tasks (stream group, one day of snapshots), run in a `fork` pool;
every task writes one part file (Parquet allows one writer per file), finished parts are skipped when a job is run again (`<out-dir>/<source>/_parts/<year>`, removed after
success), and the parent assembles the year into one file. Rows without a snapshot are NaN and recorded; the job stops before any work when more than
`max_missing_fraction` (5 %) of the rows have no snapshot in the primary group.

## Validation

* `python -m pytest tests/test_mcs_env_*.py` (59 tests; core, pipeline, CLI, ERA5 scripts, composite notebook): circles vs brute-force haversine (poles, unwrapped longitude, centre on a cell),
  alignment of tracks that start at every hour, tie and gap rules, file layouts, cache, duplicates, an end-to-end run on synthetic files with the quirks of the real data
  compared row by row with an independent brute force (masks, fallback, empty days, record start/end, a second grid, ERA5-style pressure levels and chunked files), serial = parallel,
  restart, guard, and the leap day (a noleap model around 29 February 2000 compared with a brute force that counts model hours).
* Real data, one month each (`check_mcs_env_output.py --brute-force`): 100-km, 25-km, 3-km CTL and 3-km TUNE pass every structural check and 240, 360, 420 and 420 independently recomputed
  values (60 random rows) agree to float32 precision.
* Alignment on real data (3-km CTL, 1996, 38,253 tracks): the snapshot shift `env_dt_hours` of the 3-hourly stream is -1, 0 or +1 h for one third of the tracks each and constant within every track; that of the 6-hourly
  `prw` stream is spread evenly over -3 ... +2 h. Composite of the 100-km source (30,998 tracks, 400-km circles): every track has a row in each bin from -24 h to +3 h; prw 51.8 -> 53.8 kg m-2 and rh850 83.9 -> 86.8 %
  between -24 h and the start, omega500 -0.12 -> -0.26 Pa s-1 (peak -0.28 at +3 h), pr 0.60 -> 1.06 mm h-1 (peak 1.15 at +3 h).
* **Full records** (production folder `$SCRATCH/mcs_env`, promoted from the staging folder on 2026-11-21: 56 files, 3.4 GB, names and sizes checked; final code v1.1.0, 128 workers, `check_mcs_env_output.py --brute-force`): 100-km 2009-2020, 25-km 2009-2011, 3-km CTL 1995-2005 and 3-km TUNE 2019-2021 (the whole Cess2 record) pass for
  every year (29 of 29 files, 3,244 independently recomputed values agree). **OBS (ERA5) 2007-2017** (2026-11-21, from the user's pscratch copy): 11 yearly files with 29,155 to 31,704 tracks and 3.68 to 3.98 M rows each,
  42,341,919 rows in the combined file (980 MB), 0 samples without an ERA5 snapshot in every year, every year passes all checks with 120 (2007: 240) independently recomputed values and 0 mismatches. A year takes 11-12 min with
  128 workers on one node (14 min per year when two nodes read ERA5 at the same time; the work is I/O-bound).
* Scaling on real data (25-km, January 2010, 83,957 samples = 31 day-tasks): 220 s with 1 worker, 36 s with 16, 16 s with 64, 17 s with 128; **the output is identical bit for bit for 1, 16, 64 and 128 workers**.
  The unit of parallel work is one day of snapshots, so a month cannot use more than about 31-37 workers; a year (365 tasks) keeps 128 workers busy. One day of ERA5 snapshots costs about 45 s of one core
  (decompression of the 150 MB chunks of Q, R, W, TCWV and SP for 24 hours), the other sources a few seconds per day.
* `validate_humidity_formulas.py` (E3SM ne120, 7 times): `q850` from (T850, RH850) is +1.6 % (0.9 to 2.5 %) above the stored `Q850` with 5.0 % rms (2.9 to 6.9 %, p99 26 %); `RH700` from
  (T700, Q700) is 1.8 %-points (1.2 to 2.5) below the stored value with 5.0 rms. The model interpolates T, Q and RH to the level independently, so the SCREAM `q850` (derived from T and RH)
  carries about +1.6 % bias and a few % noise per cell, which averages down inside a circle; the 25-km `rh500` is derived in the consistent direction (from T and Q). The three saturation
  formulas (Bolton, Goff-Gratch, Murphy-Koop) differ by less than 0.2 %.

## Known facts about the input data

* SCREAM-decadal: 4 empty daily files in the 3-hourly stream (2002-12-10, 2003-06-28, 2004-05-14, 2006-01-21), 5 in the 6-hourly stream (+ 2001-07-18): the snapshots of those days are missing (NaN, recorded).
  On 1994-10-31 the files `-00000` and `-10800` overlap (7 and 3 duplicate times, the file modified last is used), two months before the first track. `lat`/`lon` are labelled `rad` but are degrees,
  `area` is off by a constant factor (only ratios are used), RH is a fraction.
* 3-km TUNE (Cess2): `VapWaterPath` only in `output.3hi_ne120pg2`, which ends 2020-04-10 so far: `prw` is NaN for later tracks (coverage recorded in the file); the newest file may be partly written.
* E3SM: no `RH500` (derived from T500 + Q500 for the 25-km), no `Q500` for the 100-km (so no `rh500` there). Track longitudes are unwrapped (-207 ... 212), which only matters for code that assumes -180 ... 180.
* ERA5: `R` is relative humidity over mixed phase (IFS), the models use liquid water only, so `rh500` differs by definition at 500 hPa.

## Composites by land / ocean with the robust-MCS selection (notebook)

`../Notebooks/analyze_mcs_env_composites_land_ocean.ipynb` joins the track statistics (`mcs_tracks_final_combined_*.parquet`) with these environment files, selects the **robust MCS tracks**
of Paccini et al. (2026) **inside the notebook**, splits them into ocean and land tracks with `pf_landfrac` (the convention of `plot_tropical_mcs_trackstats_all_sources.ipynb`: ocean = lifetime maximum
< 0.1, land = lifetime minimum > 0.9) and makes the distributions at initiation (her Fig. 4) and the median evolution -24 ... +24 h with the ERA5 interquartile range (her Fig. 5), plus the mean evolution of
`analyze_envvars_evolution.ipynb`. Only the *Configuration* cell is edited (files of the sources, circle diameter = 400 km = 200-km radius, filter parameters); the track file is taken from the metadata of the
environment file. The notebook reads the production folder `$SCRATCH/mcs_env/<source>/` and writes figures, composite tables and the robust track lists to `$SCRATCH/mcs_env/figures/`; the time-series plots have a dashed grid above the shaded band. Run it on a compute node (`jupyter nbconvert --execute`, kernel `pyflex26_3`, one minute).

The criteria (tropics; first two steps non-MCS; MCS steps in one unbroken block; `isnan(start_split_cloudnumber) & isnan(end_merge_cloudnumber)`; `mcs_status` = 1 at the maximum of `total_rain`; duration <= 95th percentile
of the tracks that pass the others, per source and surface) are in `select_robust_tracks` / `apply_criteria`; the notebook prints the funnel and a **variants table** with the counts that the choices of the GSRM
repository code would give (3 initial steps, `sum(mcs_status) == mcs_duration`, status codes, land-fraction sum, no duration cut). With those options (`n_nonmcs=3, continuity='mcs_duration',
split_merge='status', ocean_rule='sum', duration_pct=None`) the functions reproduce Laura's pickles exactly (SCREAM 1,936 and ERA5 2,825 tracks, checked 2026-11-21 against her `MCS_filter` on her dense track files).
**Result of the first run (2026-11-21)**: the ocean composites of the 3-km CTL run agree with Laura's SCREAM Cess1 composites (TCWV within 3 %, RH850 within 1 %, Qv850 within 2 %) and those of ERA5 2007-2017 with her ERA5 2020 (TCWV within 0.5 %); omega500 after initiation is 10-40 % weaker here (circle size and track sets, see the notes at the end of the notebook).
`../tests/test_mcs_env_notebook.py` runs the function cells of the notebook on synthetic tracks (every criterion removes a known track; ten deliberate mutations of the notebook code are caught).

## ERA5 copy and files

`era5_copy/README.md` (step-by-step Globus guide), `era5_copy/make_era5_globus_script.sh`, `verify_era5_copy.sh`. Code: `mcsenv/` (`config`, `derive`, `grid`, `tracks`, `fileindex`, `readers`, `extract`,
`outputs`), `extract_mcs_env.py`, `combine_mcs_env.py`, `gen_mcs_env_jobs.py` + `slurm_template.sh`, `check_mcs_env_output.py`, `validate_humidity_formulas.py`; tests in `../tests/test_mcs_env_*.py`.
