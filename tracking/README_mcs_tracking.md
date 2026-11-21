# SCREAM MCS tracking (radar_feature, 3-km HRRR grid, 5-minute) - set up 2026-10-11

Same pipeline and parameters as the MRMS monthly MCS tracking (`airscape/conus_tracking/config/config_mcs_3km_MRMS_monthly.yaml`,
`PyFLEXTRKR-dev/runscripts/run_mcs_radar3d.py`); only the input description is SCREAM specific.

| file | content |
|---|---|
| `config_mcs_3km_SCREAMv1-Cess2_monthly.yaml` | monthly template (placeholders STARTDATE, ENDDATE, YEAR-MONTH) |
| `slurm_SCREAM-Cess2_conus_mcstracking.sh` | slurm template (account m1657, 1 node exclusive, regular, 16 h; per-step time table inside) |
| `generate_tracking_scripts.py` | makes the monthly configs and job scripts from the two templates (replaces STARTDATE, ENDDATE, YEAR-MONTH, DATE, CONFIG_TEMPLATE, RUN_SCRIPT; `--submit` only if asked) |
| `jobs_mcs/` | generated monthly configs and job scripts for 2020-04 ... 2020-09 (nothing submitted) |
| `flatten_remap_dir.sh` | moves the zstash sub-folder files up to `clouddata_path` (dry run by default, `--apply`) |

## Use
```bash
# 1. after the zstash extraction is complete: dry run, then move
./flatten_remap_dir.sh            # reports counts, empty files, files on a not-FULL OST
./flatten_remap_dir.sh --apply
# 2. generate (only needed again if the templates change)
python generate_tracking_scripts.py \
    -s 2020-04 -e 2020-09 -c config_mcs_3km_SCREAMv1-Cess2_monthly.yaml \
    -l slurm_SCREAM-Cess2_conus_mcstracking.sh -r run_mcs_radar3d.py -o jobs_mcs
# (no --submit: the files are only written; --no-make --submit submits files that already exist)
# 3. submit one month (from jobs_mcs, so that logs/ is jobs_mcs/logs)
cd jobs_mcs && sbatch slurm_SCREAM-Cess2_conus_mcstracking_202006.sh
```
Input `/pscratch/sd/w/wcmca1/SCREAMv1-cess2/remap_conus_5min/`, output `/pscratch/sd/w/wcmca1/SCREAMv1-cess2/mcs_conus/` (`tracking/YYYY-MM`, `stats`, `mcstracking`).
Check before submitting a month: all of its 8,640-8,928 frames exist and none is empty or on an unavailable OST (`lfs getstripe -i FILE` for each; a read of a file on the
unavailable OST hangs the job until the wallclock ends). Files of 2020-04 start at 00:05 (no 00:00 frame) and the extraction reached 2020-08-12 on 2020-10-11.

## What differs from the MRMS template
`databasename`, `time_format` (yyyy-mo-dd-hhmmss), `clouddata_path`, `root_path`, `reflectivity_varname: diag_equiv_reflectivity`, `z_dimname: lev`, `z_coordname: z_mid` (3-D height in m,
levels ordered top to bottom: the code reverses them), `x/y/lon/lat_coordname: longitude/latitude`, `z_coord_units_override: null`. Surface mask `sfc_dz_min/max` 1000 / 2500 m as in
the MRMS MCS config (the SCREAM cell config uses 50 / 1000: choose here for MRMS comparability), `echotop_gap: 8` (the MRMS MCS config uses 2; any value from 1 to 16 changes the SCREAM cell echo top by less than 0.2 km, see `README_echotop_gap.md`), terrain file the same HRRR file.

## Benchmark (one Perlmutter CPU node, `gap_test/mcs_bench*` on CFS)
| run | frames | workers | wall (min) | node peak (GB) | largest worker (GB) | MCS tracks |
|---|---|---|---|---|---|---|
| 2020-06-13 12Z - 06-14 12Z, input on CFS | 288 | 32 | 21.4 | 115 | 5.0 | 51 |
| same | 288 | 64 | 19.6 | 213 | 5.0 | 51 |
| 2020-06-15 - 06-17, input on scratch | 864 | 64 | 55.0 | 237 (main process 16) | 5.0 | 122 |

The final statistics file has the same 71 variables as the MRMS `mcs_tracks_final` file. Per-step times and the month estimate (9.5 to 13.7 h at 64 workers, over the 8 h of the MRMS template;
the template asks 16 h) are in the slurm template. Not run: a full month. The step that grows faster than the frames is `run_regionprops` (2.3 min for 1 day, 11.4 min for 3 days).
