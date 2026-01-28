# SCREAM to HRRR Grid Remapping Workflow

This directory contains scripts and configuration files for remapping E3SM SCREAM regional outputs (~3.25 km resolution) to the HRRR Lambert Conformal grid (~3 km resolution) over CONUS using ESMF and NCO tools.

## Overview

The workflow remaps 3D radar reflectivity and geopotential height fields from SCREAM's spectral element grid to HRRR's Lambert Conformal projection grid, producing analysis-ready files optimized for column-wise operations (vertical maximum reflectivity, echo-top height calculations, horizontal gradients).

### Input Data Specifications

**SCREAM Regional Domain (CONUS):**
- Latitude: 24.0°N - 50.0°N
- Longitude: 235.0°E - 294.0°E (125°W to 66°W)
- Native grid: 786,454 nodes (ne1024 spectral element)
- Remapped variables:
  - `diag_equiv_reflectivity(time, ncol, lev)`: 3D radar reflectivity (dBZ)
  - `z_mid(time, ncol, lev)`: Geopotential height (m)
  - `p_mid(time, ncol, lev)`: Pressure (Pa)
- Temporal resolution: 5-minute snapshots, 12 per hourly file

**Target HRRR Grid:**
- Projection: Lambert Conformal
- Dimensions: 1059 × 1799 × 128 levels × 12 timesteps
- Grid spacing: ~3 km

### Output Files

Two files are produced per hourly input:

1. **scream.z_mid_p_mid.5min.INSTANT.nmins_x5.YYYY-MM-DD-HHMMSS.nc** (~7.6 GB)
   - Contains: `z_mid` and `p_mid` (both remapped with bilinear interpolation)
   - Use case: Additional analysis requiring pressure levels

2. **scream.diag_equiv_reflectivity.5min.INSTANT.nmins_x5.YYYY-MM-DD-HHMMSS.nc** (~6.1 GB)
   - Contains: `diag_equiv_reflectivity` (neareststod) and `z_mid` (bilinear)
   - Use case: Primary file for convective cell tracking and echo-top height analysis

**Timestamp Format:** Output filenames use HHMMSS format (e.g., `020500` = 02:05:00 UTC) converted from SCREAM's original format (seconds since date start, e.g., `07500` seconds).

**Compression:** netCDF4 deflate_level=1 (3x compression for geopotential/pressure, 2x for reflectivity)
**Chunking:** time=1, lev=128 (full), y=256, x=256 (optimized for column operations)

---

## Prerequisites

### Software Requirements

- **Python 3.x** with numpy, xarray, pandas
- **NCL** (NCAR Command Language) for SCRIP file generation
- **ESMF 8.1.1+** with `ESMF_RegridWeightGen`
- **NCO tools** (ncremap, ncks, ncrename)
- **E3SM Unified Environment** on NERSC (recommended)

### Load Environment on NERSC Perlmutter

```bash
source /global/common/software/e3sm/anaconda_envs/load_latest_e3sm_unified_pm-cpu.sh
module load taskfarmer  # For parallel processing
```

---

## Workflow Steps

### Step 1: Generate SCRIP Files

SCRIP (Spherical Coordinate Remapping and Interpolation Package) files describe the grid geometry for ESMF.

#### 1a. Generate SCREAM Regional SCRIP File

**Critical:** Use the modified `create_regional_remapper.py` script that correctly handles regional spectral element grids (fix from Naser: [E3SM-Project/eamxx-scripts#193](https://github.com/E3SM-Project/eamxx-scripts/pull/193)).

```bash
python create_regional_remapper.py \
    --input /path/to/scream/output/file.nc \
    --output SCREAM_CONUS_ne1024_SCRIP.nc
```

**Output:** `SCREAM_CONUS_ne1024_SCRIP.nc` with `grid_size=786454`

#### 1b. Generate HRRR SCRIP File

Use NCL script to create SCRIP file for HRRR's curvilinear grid:

```bash
ncl make_HRRR_SCRIP.ncl
```

**Input:** HRRR grid file with 2D lat/lon coordinates
**Output:** `HRRR_SCRIP.nc`

---

### Step 2: Generate Weight Files with ESMF

Weight files contain the remapping coefficients and can be reused for all files with the same grid geometry.

```bash
./run_module_RegridWeightGen.sh
```

This script generates two weight files:
- `SCREAM_CONUS_ne1024_to_HRRR_neareststod.nc` (for reflectivity)
- `SCREAM_CONUS_ne1024_to_HRRR_bilinear.nc` (for geopotential height/pressure)

**Note:** Can be run directly on a login node by setting `tgtconf="netcdf"` (not `"pnetcdf"`).

**Edit script to set:**
```bash
srcgrid="SCREAM_CONUS_ne1024_SCRIP.nc"
dstgrid="HRRR_SCRIP.nc"
wgtdir="/path/to/output/weights"
```

---

### Step 3: Remap and Combine Variables

The main remapping script processes one pair of files (reflectivity + geopotential height).

#### Single File Processing

```bash
./remap_dbz_zmid.sh \
    output.scream.diag_equiv_reflectivity.5min.INSTANT.nmins_x5.2020-06-07-07500.nc \
    output.scream.z_mid_p_mid.5min.INSTANT.nmins_x5.2020-06-07-07500.nc
```

**Script workflow:**
1. **Step 1 (~140s):** Remap reflectivity using neareststod (nearest neighbor)
2. **Step 2 (~740s):** Remap z_mid and p_mid using bilinear interpolation + apply compression
3. **Step 3 (~200s):** Combine reflectivity with z_mid into single file
4. **Step 4 (~470s):** Rename dimensions (lat→y, lon→x), remove unwanted variables, apply compression
5. **Step 5 (~7s):** Clean up temporary files

**Total processing time:** ~26 minutes per hourly file

#### Configuration Variables

Edit the top of `remap_dbz_zmid.sh` to adjust:

```bash
# Chunking and compression settings
chunk_time=1      # 1 = one timestep per chunk
chunk_lev=128     # 128 = full vertical dimension (no chunking)
chunk_lat=256     # Spatial chunk size in y-direction
chunk_lon=256     # Spatial chunk size in x-direction
deflate_level=1   # 0 = no compression, 1-9 = compression level

# Input/output directories
in_dir='/pscratch/sd/w/wcmca1/SCREAMv1-cess2/run_conus/'
out_dir='/pscratch/sd/w/wcmca1/SCREAMv1-cess2/remap_conus'

# Weight files
map_neareststod='/path/to/SCREAM_CONUS_ne1024_to_HRRR_neareststod.nc'
map_bilinear='/path/to/SCREAM_CONUS_ne1024_to_HRRR_bilinear.nc'
```

---

### Step 4: Parallel Processing with TaskFarmer

For processing multiple files in parallel on NERSC Perlmutter.

#### 4a. Generate Task List

```bash
python generate_taskfarmer_list.py \
    --start-date 2020-06-01 \
    --end-date 2020-06-30 \
    --output tasks_june2020.txt
```

**Options:**
- `--input-dir`: Directory containing SCREAM output files (default: configured path)
- `--script`: Path to `remap_dbz_zmid.sh` (default: configured path)
- `--start-date`, `--end-date`: Filter files by date range (YYYY-MM-DD format)

**Output:** Text file with one task per line:
```
/path/to/remap_dbz_zmid.sh output.scream.diag_equiv_reflectivity...nc output.scream.z_mid_p_mid...nc
/path/to/remap_dbz_zmid.sh output.scream.diag_equiv_reflectivity...nc output.scream.z_mid_p_mid...nc
...
```

#### 4b. Submit TaskFarmer Job

```bash
module load taskfarmer
sbatch slurm_regrid_taskfarmer.sh
```

**Recommended TaskFarmer configuration:**

```bash
#!/bin/bash
#SBATCH -N 5              # 5 nodes (1 server + 4 workers)
#SBATCH -c 128            # All cores available
#SBATCH -q regular
#SBATCH -t 04:00:00       # 4 hours
#SBATCH -C cpu
#SBATCH -A your_account

module load taskfarmer
export THREADS=10         # 10 tasks per node (512 GB / 50 GB per task)

runcommands.sh tasks_june2020.txt
```

**Memory considerations:**
- Peak memory per task: ~40-50 GB
- Perlmutter CPU node: 512 GB RAM, 128 cores
- Recommended: `THREADS=10` (51 GB per task)
- Conservative: `THREADS=8` (64 GB per task)
- Aggressive: `THREADS=12-14` (37-43 GB per task)

**Throughput:**
- 4 worker nodes × 10 tasks/node = 40 parallel tasks
- ~26 min per file → ~200 files per hour
- Monitor with: `sqs` command

---

## Performance and Optimization

### Processing Time Breakdown

Based on testing with 14 parallel tasks, typical processing time per file:

| Step | Operation | Time | % of Total |
|------|-----------|------|------------|
| 1 | Remap reflectivity (neareststod) | 140s | 9% |
| 2 | Remap z_mid/p_mid (bilinear + compress) | 740s | 48% |
| 3 | Combine variables | 200s | 13% |
| 4 | Rename, remove vars, compress | 470s | 30% |
| 5 | Cleanup | 7s | <1% |
| **Total** | | **1557s** | **100%** |

**Total time:** 25-28 minutes per hourly file (12×5-min timesteps)

### Storage Savings

| File Type | Uncompressed | Compressed (deflate_level=1) | Compression Ratio |
|-----------|--------------|------------------------------|-------------------|
| z_mid + p_mid | ~22 GB | ~7.6 GB | 2.9:1 |
| diag_equiv_reflectivity + z_mid | ~12 GB | ~6.1 GB | 2.0:1 |
| **Total per hourly file** | **~34 GB** | **~13.7 GB** | **2.5:1** |

**Storage savings:** ~60% with minimal impact on read performance

### Optimization Notes

1. **Chunking rationale:**
   - `time=1`: Each timestep is independently processed in analysis workflows
   - `lev=128`: Full vertical dimension for column-maximum and echo-top height calculations
   - `y=256, x=256`: Balance between I/O efficiency and spatial access patterns

2. **Compression level:**
   - `deflate_level=1`: Good balance between compression ratio and speed
   - Higher levels (2-9) provide minimal additional compression but significantly slower

3. **Why two output files:**
   - Most analyses only need reflectivity + z_mid → smaller file size
   - Pressure field (p_mid) available in separate file for specialized analyses
   - Avoids redundant compression of unused variables

---

## Troubleshooting

### Common Issues

**1. ESMF triangulation failure with bilinear/conservative methods**
- **Cause:** SCREAM spectral element grid structure not compatible with ESMF triangulation
- **Solution:** Use neareststod or nearest_s2d methods instead

**2. SCRIP file grid_size mismatch**
- **Cause:** NCL `unstructured_to_ESMF` creates mesh elements (~1.5M) instead of nodes (786K)
- **Solution:** Use `create_regional_remapper.py` with correct node-based SCRIP generation

**3. HDF5 locking errors during compression**
- **Cause:** Attempting to rename dimensions/variables in compressed netCDF4 file
- **Solution:** Script performs all renames before compression step

**4. Segmentation fault in Step 2**
- **Cause:** ncks trying to do regridding + compression simultaneously
- **Solution:** Two-step process: remap first, then apply compression

**5. Out of memory errors**
- **Cause:** Too many parallel tasks for available RAM
- **Solution:** Reduce `THREADS` in TaskFarmer (try 8 instead of 10)

### Validation

Check output file structure:

```bash
ncdump -h scream.diag_equiv_reflectivity.5min.INSTANT.nmins_x5.2020-06-07-020500.nc
```

Expected dimensions:
```
dimensions:
    time = 12 ;
    lev = 128 ;
    y = 1059 ;
    x = 1799 ;
```

Expected variables:
- `diag_equiv_reflectivity(time, lev, y, x)`
- `z_mid(time, lev, y, x)`
- `latitude(y, x)` or `latitude(y)`
- `longitude(y, x)` or `longitude(x)`

---

## References

1. **SCRIP Regional Fix:** [E3SM-Project/eamxx-scripts#193](https://github.com/E3SM-Project/eamxx-scripts/pull/193)
2. **ESMF Regridding:** [https://earthsystemmodeling.org/regrid/](https://earthsystemmodeling.org/regrid/)
3. **NCO Tools:** [http://nco.sourceforge.net/](http://nco.sourceforge.net/)
4. **NERSC TaskFarmer:** [https://docs.nersc.gov/jobs/workflow/taskfarmer/](https://docs.nersc.gov/jobs/workflow/taskfarmer/)

---

## File Descriptions

| File | Purpose |
|------|---------|
| `create_regional_remapper.py` | Generate SCRIP file for SCREAM regional spectral element grid |
| `make_HRRR_SCRIP.ncl` | Generate SCRIP file for HRRR curvilinear grid |
| `run_module_RegridWeightGen.sh` | Generate ESMF weight files (neareststod and bilinear) |
| `remap_dbz_zmid.sh` | Main remapping script for single file pair |
| `generate_taskfarmer_list.py` | Generate task list for parallel processing |
| `slurm_regrid_taskfarmer.sh` | TaskFarmer batch script for NERSC Perlmutter |

---

## Contact

For questions or issues with this workflow, contact the E3SM SCREAM team or consult the E3SM User Forum.

**Last Updated:** January 2026
