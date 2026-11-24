# Monthly-mean environment fields on a 1 degree grid

Monthly-mean 2-D fields of the large-scale environment of ERA5 and the SCREAM / E3SM runs, regridded to one global 1 x 1 degree grid, with
12-month climatologies. They are the map companion of the along-track environment of `../` (circle means along MCS tracks).

| CMIP name | variable | units | ERA5 | SCREAM 3 km | E3SM 25 km | E3SM 100 km |
|---|---|---|---|---|---|---|
| `prw` | total column water vapor | kg m-2 | `TCWV`, hourly, monthly mean | `VapWaterPath` | `TMQ` | `TMQ` |
| `hus850` | specific humidity at 850 hPa | 1 (kg/kg) | `Q`, level picked | `qv`, **interpolated** | `Q`, **interpolated** | `Q`, **interpolated** |
| `hur500` | relative humidity at 500 hPa | % | `R`, level picked | `RelativeHumidity` x 100, **interpolated** | `RELHUM`, **interpolated** | `RELHUM`, **interpolated** |
| `wap500` | omega at 500 hPa | Pa s-1 | `W`, hourly, level picked, monthly mean | `omega_at_500hPa` | `OMEGA`, **interpolated** | `OMEGA500` |
| `ps` | surface pressure | Pa | `SP`, hourly, monthly mean | `ps` | `PS` | `PS` |

`ps` is not a target variable: ERA5 stores extrapolated values below the ground, so its 850 hPa fields are masked with the monthly-mean `ps`;
it is written for all sources.

## The four steps

```bash
PY=/global/common/software/m1867/python/pyflex26.3/bin/python
cd /global/homes/f/feng045/program/scream/mcs_environment/monthly        # run on an interactive compute node, not on a login node

# 0. the 1 degree grid and one bilinear weight file per source grid (ncremap + ESMF); ne30pg2 is shared by 3km_CTL, 3km_TUNE and 100km
$PY make_weights.py --configs config/ERA5.yaml config/3km_CTL.yaml config/3km_TUNE.yaml config/25km.yaml config/100km.yaml

# 1-3. per dataset: monthly files on the native grid, regridded to 1 degree, 12-month climatology
$PY make_monthly_native.py --config config/3km_CTL.yaml          # [--start YYYY-MM --end YYYY-MM --nproc N --overwrite]
$PY regrid_monthly.py      --config config/3km_CTL.yaml
$PY calc_env_climo.py      --config config/3km_CTL.yaml

# 4. check the outputs (compression, units, ranges, month coverage, missing cells); exit code 1 on a problem
$PY check_env_monthly.py   --config config/3km_CTL.yaml
```

Data go to `<data_root>/<dataset>/{native,latlon_1deg,climo}/` (`data_root` and `maps_dir` are set in `config/grids.yaml`; now
`/pscratch/sd/f/feng045/mcs_env/monthly`). Existing months are skipped (`--overwrite` redoes them); files are written under a temporary name and
renamed when complete. A month whose inputs are missing is reported as failed in `<dataset>/_reports/*.csv` and the run goes on; the exit code is 1
when more than 5 % of the months failed. `--nproc` defaults to what cores and memory allow.

Validation scripts (kept because they document how far the numbers can be trusted):

* `validate_regrid.py --config config/X.yaml --month YYYY-MM`: the numpy application of the weights against `ncremap`, an analytic field through
  the weights, area means and pattern correlation native vs 1 degree.
* `validate_interpolation.py`: the interpolation against the models' own 500 / 850 hPa diagnostics, and the ERA5 monthly files against the mean of
  the 6-hourly hourly-file snapshots.

Tests: `python -m pytest tests/test_env_monthly_*.py` from `scream/` (45 tests; the pipeline tests need NCO and run a real `ncremap`).

## Data on CFS (inventory, copy of 2026-11-23)

The monthly maps are archived on CFS in `/global/cfs/cdirs/m1867/zfeng/SCREAM-decadal/monthly_env/` (947 files, 2.87 GB; group m1867), a plain copy of the pscratch working copy
`/pscratch/sd/f/feng045/mcs_env/monthly` with the same layout (`rsync -rt`, nothing deleted; a full-checksum dry run `rsync -rcn` reports no difference and the byte count agrees):

| dataset | months | native grid | 1 degree | climatology | period of the climatology |
|---|---|---|---|---|---|
| `ERA5` | 132 (2007-01 .. 2017-12) | 132 files, 1.68 GB (0.25 degree) | 132 files, 124 MB | 11 MB | 2007-2017, 11 files per calendar month |
| `3km_CTL` | 127 of 132 (1995-01 .. 2005-12; 5 empty inputs) | 127 files, 56 MB (ne30pg2) | 127 files, 117 MB | 10 MB | 1995-2005, 10-11 per calendar month |
| `3km_TUNE` | 19 (2019-08 .. 2021-02) | 19 files, 8 MB (ne30pg2) | 19 files, 17 MB | 10 MB | March-July once, August-February twice |
| `25km` | 36 (2009-01 .. 2011-12) | 36 files, 304 MB (ne120pg2) | 36 files, 34 MB | 10 MB | 2009-2011, 3 per calendar month |
| `100km` | 144 (2009-01 .. 2020-12) | 144 files, 76 MB (ne30pg2) | 144 files, 130 MB | 10 MB | 2009-2020, 12 per calendar month |

Every file holds `prw`, `hus850`, `hur500`, `wap500`, `ps` (CMIP names, "What the numbers are" below); `<dataset>/{native,latlon_1deg,climo,_reports}`, file names
`env_<dataset>_native_<YYYYMM>.nc`, `env_<dataset>_1deg_<YYYYMM>.nc`, `env_<dataset>_1deg_monthly_climo_<YYYYMM>_<YYYYMM>.nc`; `_reports` are the run reports of the steps (CSV). `monthly_env/maps/` holds the
SCRIP grids and the bilinear weight files (`grid_g1deg.nc`, `grid_era5_025.nc` 96 MB, `map_era5_025_to_g1deg_bilinear.nc` 114 MB, `map_ne120pg2_to_g1deg_bilinear.nc` 45 MB, `map_ne30pg2_to_g1deg_bilinear.nc` 13 MB;
they are made in seconds by `make_weights.py`). Not copied: the run logs. The notebook `../../Notebooks/plot_global_env_climo_scream_e3sm_obs.ipynb` reads the climatologies of this copy and writes its figures to
`/global/cfs/cdirs/m1867/zfeng/SCREAM-decadal/figures_resolution/env_map/`. The processing root `data_root` of `config/grids.yaml` stays on pscratch (the working copy); after reprocessing copy again with
`rsync -rt --no-owner --no-group --no-perms --chmod=D2770,F660 --exclude=/logs /pscratch/sd/f/feng045/mcs_env/monthly/ /global/cfs/cdirs/m1867/zfeng/SCREAM-decadal/monthly_env/`.
The near-storm environment is in `/global/cfs/cdirs/m1867/zfeng/SCREAM-decadal/mcs_env/` (see `../README.md`).

## Configuration

* `config/grids.yaml`: folders, the target grid (`ncremap -G` string; `lon_typ=180_wst` gives -179.5 .. 179.5, `Grn_wst` gives 0.5 .. 359.5),
  the source grids (an existing SCRIP file or a generated one), the ESMF method, `valid_weight_fraction`, the deflate level.
* `config/variables.yaml`: the dictionary of the output names: CMIP name -> long name, standard name, units, level, plausible range. A dataset
  config can only use these names; add a line here to add a variable.
* `config/<dataset>.yaml`: one file per dataset. Each stream (family of files) lists its variables in **groups that say how they are obtained**:

  | group | meaning |
  |---|---|
  | `direct` | a 2-D variable that exists in the files (for hourly files: averaged over all records of the month) |
  | `plev_select` | a 3-D variable already on pressure levels (ERA5): the level is picked, nothing is interpolated |
  | `interpolate` | a 3-D variable on model levels: linear in ln(p) to `plev_hpa`, with the level pressure of the stream's `pressure:` |

  `pressure:` is `{field: p_mid}` (stored level pressure, SCREAM) or `{hybrid: {ps: PS, a: hyam, b: hybm, p0: P0}}` (E3SM). `scale` / `offset`
  convert raw values to the units of `variables.yaml` (SCREAM RH is a fraction: `scale: 100`). `mask_below_ground: ps` sets a level variable to NaN
  where the monthly-mean surface pressure is below the level.

**Adding a dataset** (for example 13-km CTL / TUNE, whose data are not located yet): copy `config/3km_CTL.yaml`, set `name`, `label`, `period`,
`grid` (add the grid to `config/grids.yaml` if it is not ne30pg2 / ne120pg2: a SCRIP file of the grid, or `generate`), `root` and `pattern`, and
the raw variable names; run `make_weights.py` with the new config and steps 1-4. `readers.py` has two layouts, `ncol` (unstructured, one monthly
file) and `latlon` (regular, any number of files per month); a new layout is one more function there and one word in `config.LAYOUTS`.

## What the numbers are (read before comparing sources)

* **Months.** The month of a file is taken from the averaging window `time_bnds[0]` (model files) or the time stamps (ERA5) and checked against the
  month asked for: a file of another month is refused. Model calendars are noleap, ERA5 standard; every file carries its calendar.
* **ERA5 monthly files** (`e5.oper.an.pl.monthly`) are monthly means (checked: Q850 and R500 against the mean of 6-hourly snapshots of January 2007,
  correlation 0.99998 / 0.9997), but contain only T, U, V, Q, R: **omega is the monthly mean of the hourly W files** (pscratch copy,
  2006-12 .. 2018-01), `prw` and `ps` the mean of the hourly files. A month needs at least 95 % of the expected hourly records, else it fails.
* **Interpolation of monthly means.** The interpolated fields (`hus850`, `hur500`; `wap500` for 25 km) are the interpolation of the monthly-mean
  field on the monthly-mean level pressure, not the monthly mean of the interpolated hourly or daily fields. Against the models' own diagnostics
  (`validate_interpolation.py`, ocean and lowland cells): E3SM 100 km `OMEGA` -> 500 hPa vs `OMEGA500` correlation 0.99998; SCREAM `T_mid` -> 850 hPa
  vs `T_mid_at_850hPa` rms 0.07-0.08 K; SCREAM `omega` -> 500 hPa correlation 0.9985-0.9991. **Over high terrain the SCREAM interpolation is less
  accurate** (omega at 500 hPa over land with ps < 800 hPa: rms difference 0.04 Pa/s against an rms of 0.11 Pa/s of the field, correlation 0.93, measured on January 1995): the SCREAM monthly
  files exist only on ne30pg2, coarsened from 3 km, and interpolating coarsened fields is not the coarsened online interpolation where the
  surface is steep. This affects the margins of Tibet, the Andes and the Rockies in `hus850` and `hur500`.
* **Relative humidity.** All three RH fields are the monthly mean of RH (ERA5 `R`, SCREAM `RelativeHumidity`, E3SM `RELHUM`). ERA5 `R` is
  mixed-phase (ice below 0 C), the models liquid-only, so `hur500` differs by definition at 500 hPa.
* **Below ground.** ERA5 values below the ground are extrapolated: `hus850`, `hur500`, `wap500` are masked where the monthly-mean `SP` is below the
  level. Model fields are NaN where the level lies below the lowest model level of the monthly-mean pressure.
* **Regridding.** ESMF bilinear weights from `ncremap`, applied with numpy (identical to `ncremap -m` where there is no missing value, checked to
  1e-8; `ncremap` fills destination cells without weights with zero and treats missing values in its own way). Source cells that are NaN are left
  out and a destination cell is the weighted mean of the valid cells if they hold at least `valid_weight_fraction` (0.5) of its weight, else it is
  missing; this keeps the masked area close to the true below-ground area (a stricter rule adds a one-cell ring). The two polar rows (|lat| = 89.5)
  of the ne30pg2 maps have no weights (the outermost source cell centre is at 88.9 degrees) and are missing; the maps are shown between 60S and
  60N. Bilinear interpolation from 0.25 degree samples only the nearest points; a conservative map would average. `method` in `grids.yaml`.
* **Climatology.** Unweighted mean of the monthly means of each calendar month over the period; `nmonths` gives the files per calendar month
  (Cess2: March to July once, August to February twice). The climatologies cover different periods (OBS 2007-2017, 3 km CTL 1995-2005, 3 km TUNE
  2019-08 .. 2021-02, 25 km 2009-2011, 100 km 2009-2020, the periods of the MCS rain-map climatologies), so compare them as climatologies.
* **Compression.** Every file is netCDF4 with deflate level 4 and shuffle, chunked by time step; `check_compression` runs after every written file
  and `check_env_monthly.py` on all of them.

## Code

`envmonthly/`: `config` (loader / validation), `timeaxis` (months, time axes, month check of files), `readers` (layouts `ncol`, `latlon`),
`vertical` (`interp_to_plev` adapted from `e3sm_polun/scripts/interp_to_plev.py`, the pressure of hybrid levels, below-ground mask), `writer`
(compressed output, `check_compression`), `native` (step 1), `regrid` (step 2, `Remapper`), `climo` (step 3), `runner` (process pool, report),
`ncotools` (NCO helpers, grids, weights and their checks; `find_tool` / `run_tool` are copied from `e3sm_polun/regrid/remap_e3sm.py`).
Environment: `/global/common/software/m1867/python/pyflex26.3` (the NCO programs are found in the E3SM-unified folder, `ncotools.DEFAULT_NCO_BIN`).

Maps and bias figures: `../../Notebooks/plot_global_env_climo_scream_e3sm_obs.ipynb` (reads the CFS copy, figures in `figures_resolution/env_map/`; shading with filled contours, `fill_style = 'pcolormesh'` for blocks).
