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

Each hourly input file (containing 12×5-min timesteps) produces:

1. **One combined z_mid/p_mid file** (~7.6 GB, 12 timesteps)
   - Filename: `scream.z_mid_p_mid.5min.INSTANT.nmins_x5.YYYY-MM-DD-HHMMSS.nc`
   - Contains: `z_mid` and `p_mid` (both remapped with bilinear interpolation)
   - Use case: Additional analysis requiring pressure and height

2. **Twelve individual reflectivity+z_mid files** (~600 MB each, 1 timestep each)
   - Filename: `scream.diag_equiv_reflectivity.5min.INSTANT.nmins_x5.YYYY-MM-DD-HHMMSS.nc`
   - Contains: `diag_equiv_reflectivity` (neareststod) and `z_mid` (bilinear)
   - Use case: Primary files for convective cell tracking analysis
   - Total size: ~6 GB for 12 files

**Timestamp Format:** Output filenames use HHMMSS format (e.g., `020500` = 02:05:00 UTC) converted from SCREAM's original format (seconds since date start, e.g., `07500` seconds). Times are rounded to the nearest minute.

**Compression:** netCDF4 deflate_level=1 (~2.5x compression)
**Chunking:** time=1, lev=128 (full), y=256, x=256 (optimized for column operations)

**Why split into individual files?** Single-timestep files are optimized for PyFLEXTRKR cell tracking workflows, which process one time step at a time, reducing memory overhead and enabling efficient parallel processing (by files).

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

### Step 3: Remap, Combine, and Split Variables

The main remapping script processes one pair of files (reflectivity + geopotential height) and splits the output into individual 5-minute timestep files.

#### Single File Processing

```bash
./remap_dbz_zmid_5min.sh \
    output.scream.diag_equiv_reflectivity.5min.INSTANT.nmins_x5.2020-06-07-07500.nc \
    output.scream.z_mid_p_mid.5min.INSTANT.nmins_x5.2020-06-07-07500.nc
```

**Script workflow:**
1. **Step 1 (~88s):** Remap reflectivity using neareststod + rename dimensions/variables for consistency
2. **Step 2 (~373s):** Remap z_mid and p_mid using bilinear + rename dimensions/variables + apply compression
3. **Step 3 (~9s):** Combine reflectivity with z_mid into temporary file
4. **Step 4 (~142s):** Split into 12 individual 5-minute files using CDO timestamps + remove unwanted variables + apply compression/chunking
5. **Step 5 (~14s):** Clean up temporary files

**Total processing time:** ~12 minutes per hourly file (produces 13 output files: 1 z_mid/p_mid + 12 reflectivity/z_mid)

**Alternative:** For workflows that need 12-timestep files, use `remap_dbz_zmid.sh` instead (~26 min per file).

#### Configuration Variables

Edit the top of `remap_dbz_zmid_5min.sh` (or `remap_dbz_zmid.sh` for 12-timestep files) to adjust:

```bash
# Chunking and compression settings
chunk_time=1      # 1 = one timestep per chunk
chunk_lev=128     # 128 = full vertical dimension (no chunking)
chunk_lat=256     # Spatial chunk size in y-direction
chunk_lon=256     # Spatial chunk size in x-direction
deflate_level=1   # 0 = no compression, 1-9 = compression level

# Input/output directories
in_dir='/pscratch/sd/w/wcmca1/SCREAMv1-cess2/run_conus/'
tmp_dir='/pscratch/sd/w/wcmca1/SCREAMv1-cess2/remap_conus'  # Temporary files
out_dir='/pscratch/sd/w/wcmca1/SCREAMv1-cess2/remap_conus_5min'  # Individual 5-min files

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
    -s 2020-06-01 \
    -e 2020-06-30 \
    --output tasks_june2020.txt
```

**Options:**
- `--input-dir`: Directory containing SCREAM output files (default: configured path)
- `--script`: Path to remapping script (default: `remap_dbz_zmid_5min.sh`)
- `-s, --start-date`: Filter files by start date (YYYY-MM-DD format)
- `-e, --end-date`: Filter files by end date (YYYY-MM-DD format)
- `--output`: Output task list filename

**Output:** Text file with one task per line:
```
/path/to/remap_dbz_zmid_5min.sh output.scream.diag_equiv_reflectivity...nc output.scream.z_mid_p_mid...nc
/path/to/remap_dbz_zmid_5min.sh output.scream.diag_equiv_reflectivity...nc output.scream.z_mid_p_mid...nc
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
#SBATCH --nodes=32
#SBATCH -c 128
#SBATCH -q regular
#SBATCH -t 04:00:00       # 4 hours for ~4488 files
#SBATCH -C cpu
#SBATCH -A your_account

export THREADS=16

runcommands.sh tasks_all.txt
```

**Resource planning:**
- Processing time: ~12 min per hourly file (conservative: 20 min)
- Peak memory per task: ~30-40 GB
- Perlmutter CPU node: 512 GB RAM, 128 cores
- **Recommended:** 16 tasks/node (32 GB per task)
- Node throughput: 16 tasks/node × 3 files/hour/task = 48 files/node/hour

**Throughput estimates:**
- 16 nodes: ~770 files/hour → 4488 files in ~6 hours
- 32 nodes: ~1536 files/hour → 4488 files in ~3 hours
- Monitor with: `sqs` command

**For smaller batches:** Adjust `--nodes` proportionally (e.g., 8 nodes for ~1000 files)

#### 4c. Check for Missing Outputs

After a TaskFarmer job completes, verify all expected output files were created:

```bash
./find_missing_outputs.sh tasklist_202007.txt
```

**What it does:**
- Reads your tasklist and checks if all 12 expected 5-min output files exist for each input
- Reports which tasks have incomplete outputs
- Generates a new tasklist (e.g., `tasklist_202007_missing.txt`) with only incomplete tasks

**Typical output:**
```
Checking for missing output files from tasklist...
Missing 5/12 outputs from: output.scream.diag_equiv_reflectivity.5min...nc
Missing 12/12 outputs from: output.scream.diag_equiv_reflectivity.5min...nc

========================================================================
Summary:
  Total input files checked: 72
  Input files with missing outputs: 8
  Total missing output files: 100 (expected: 864)
  Missing tasklist saved to: tasklist_202007_missing.txt
========================================================================
```

**Reprocess missing files:**
```bash
module load taskfarmer
sbatch slurm_regrid_taskfarmer.sh  # Edit to use tasklist_202007_missing.txt
```

Or with GNU parallel (interactive node):
```bash
parallel -j 16 < tasklist_202007_missing.txt
```

---

## Performance and Optimization

### Processing Time Breakdown

**Using `remap_dbz_zmid_5min.sh` (recommended for cell tracking workflows):**

Based on single-file testing, typical processing time per hourly input:

| Step | Operation | Time | % of Total |
|------|-----------|------|------------|
| 1 | Remap reflectivity + rename | 88s | 12% |
| 2 | Remap z_mid/p_mid + rename + compress | 373s | 53% |
| 3 | Combine variables | 9s | 1% |
| 4 | Split to 12 files + remove vars + compress | 142s | 20% |
| 5 | Cleanup | 14s | 2% |
| **Total** | | **710s** | **100%** |

**Total time:** ~12 minutes per hourly file → produces 13 files (1 z_mid/p_mid + 12 reflectivity/z_mid)

**Using `remap_dbz_zmid.sh` (for 12-timestep files):**
- Total time: ~26 minutes per hourly file → produces 2 files
- Use when downstream analysis requires multi-timestep files

### Storage Savings

**Per hourly input (12 timesteps):**

| File Type | Uncompressed | Compressed (deflate_level=1) | Compression Ratio |
|-----------|--------------|------------------------------|-------------------|
| z_mid + p_mid (1 file, 12 times) | ~22 GB | ~7.6 GB | 2.9:1 |
| diag_equiv_reflectivity + z_mid (12 files, 1 time each) | ~18 GB | ~7.2 GB (12×600 MB) | 2.5:1 |
| **Total output** | **~40 GB** | **~14.8 GB** | **2.7:1** |

**Per individual 5-min file:**
- Single reflectivity+z_mid file: ~1.5 GB uncompressed → ~600 MB compressed (2.5:1)

**Storage savings:** ~60% with minimal impact on read performance

### Optimization Notes

1. **Chunking rationale:**
   - `time=1`: Each timestep is independently processed in analysis workflows
   - `lev=128`: Full vertical dimension for column-maximum and echo-top height calculations
   - `y=256, x=256`: Balance between I/O efficiency and spatial access patterns

2. **Compression level:**
   - `deflate_level=1`: Good balance between compression ratio and speed
   - Higher levels (2-9) provide minimal additional compression but significantly slower

3. **Why split into individual timestep files:**
   - PyFLEXTRKR cell tracking processes one time step at a time if multiple times are in an input file
   - Reduces memory overhead (600 MB vs 6.1 GB per file loaded)
   - Enables more efficient parallel processing in tracking workflows as files are processed in parallel

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

Check individual 5-min file structure:

```bash
ncdump -h scream.diag_equiv_reflectivity.5min.INSTANT.nmins_x5.2020-06-07-020500.nc
```

Expected dimensions:
```
dimensions:
    time = 1 ;      // Single timestep
    lev = 128 ;
    y = 1059 ;
    x = 1799 ;
```

Expected variables:
- `diag_equiv_reflectivity(time, lev, y, x)`
- `z_mid(time, lev, y, x)`
- `latitude(y, x)` or `latitude(y)`
- `longitude(y, x)` or `longitude(x)`
- `time(time)` with proper time coordinate

Check z_mid/p_mid file (12 timesteps):
```bash
ncdump -h scream.z_mid_p_mid.5min.INSTANT.nmins_x5.2020-06-07-020500.nc
```
Expected: `time = 12`, contains `z_mid` and `p_mid` variables

---

## References

1. **SCRIP Regional Fix:** [E3SM-Project/eamxx-scripts#193](https://github.com/E3SM-Project/eamxx-scripts/pull/193)
2. **ESMF Regridding:** [https://earthsystemmodeling.org/regrid/](https://earthsystemmodeling.org/regrid/)
3. **NCO Tools:** [http://nco.sourceforge.net/](http://nco.sourceforge.net/)
4. **NERSC TaskFarmer:** [https://docs.nersc.gov/jobs/workflow/taskfarmer/](https://docs.nersc.gov/jobs/workflow/taskfarmer/)

---

## GridRad to HRRR Grid Remapping Workflow

This section describes the Python-based workflow for remapping GridRad 3D radar reflectivity data to the HRRR grid using xESMF. GridRad provides NEXRAD WSR-88D radar observations gridded to a regular latitude-longitude grid at 0.02° resolution (~2 km).

### Overview

The GridRad remapping workflow uses modern Python tools (xESMF, xarray, Dask) to efficiently remap observational radar data to match SCREAM output grid for model validation and evaluation studies.

**Input Data Specifications:**

- **GridRad v4.2:** 3D NEXRAD radar mosaic
  - Horizontal grid: 1248 × 2832 (lat × lon) at 0.02° resolution
  - Vertical levels: 28 heights (1-24 km ASL)
  - Variables: Reflectivity (dBZ), observations count, echo count, weights
  - Temporal resolution: Hourly snapshots
  - Coverage: CONUS and adjacent regions

**Target HRRR Grid:**
- Same Lambert Conformal grid as SCREAM output (1059 × 1799)
- Enables direct comparison with SCREAM radar reflectivity simulations

**Output Files:**
- Filename: `GridRad_HRRR_YYYYMMDDTHHMMSSZ.nc`
- Variables: `Reflectivity`, `Nradobs`, `Nradecho`, `wReflectivity`, with proper geolocation
- Compression: netCDF4 deflate_level=1
- Size: ~250 MB per hourly file (uncompressed: ~600 MB)

### Software Requirements

```bash
# Load Python environment with required packages
conda activate /global/homes/f/feng045/envs/pyflex-dev

# Required Python packages:
# - xarray, numpy, xesmf (≥0.8), dask, netCDF4
```

### Scripts and Usage

#### Core Scripts

1. **`gridrad.py`** - Official GridRad v4.2 data reader library
   - Reads GridRad NetCDF files with proper attribute handling
   - Extracts reflectivity, observations, echoes, coordinates
   - Compatible with GridRad v4.2 3D radar mosaic format

2. **`remap_gridrad_to_hrrr.py`** - Main remapping script
   - Uses xESMF for efficient horizontal regridding
   - Supports bilinear (default) and conservative remapping
   - Parallel processing with Dask for batch operations
   - Automatic weight file generation and reuse

#### Basic Usage

**Single file:**
```bash
python remap_gridrad_to_hrrr.py -s /path/to/nexrad_3d_v4_2_20200616T000000Z.nc
```

**Multiple files (parallel processing):**
```bash
python remap_gridrad_to_hrrr.py -n 60 /pscratch/sd/i/iclas2/GridRad/2020/nexrad_3d_v4_2_2020*.nc
```

**Using quoted glob pattern:**
```bash
python remap_gridrad_to_hrrr.py -n 60 "/pscratch/sd/i/iclas2/GridRad/2020/nexrad_3d_v4_2_2020{04,05,06,07,08}*.nc"
```

#### Command Line Options

```bash
python remap_gridrad_to_hrrr.py [-h] [-o OUTPUT_DIR] [-m {conservative,bilinear}] 
                                [-w WEIGHT_DIR] [-p] [-s] [-n N_WORKERS]
                                [--hrrr-grid HRRR_GRID]
                                input_files [input_files ...]

Options:
  input_files              Input file(s) - accepts multiple files or patterns
  -o, --output-dir         Output directory (default: /pscratch/sd/i/iclas2/GridRad/regrid_hrrr)
  -m, --method            Remapping method: bilinear or conservative (default: bilinear)
  -w, --weight-dir        Weight file directory (default: /pscratch/sd/i/iclas2/GridRad/weights)
  -p, --parallel          Run in parallel using Dask (default: True)
  -s, --serial            Run in serial mode (overrides --parallel)
  -n, --n-workers         Number of Dask workers (default: 32)
  --hrrr-grid             HRRR grid file (default: /pscratch/sd/i/iclas2/GridRad/maps/hrrr_sfc_latlon_orog_lsm.nc)
```

### Technical Details

#### Remapping Method

**Bilinear interpolation (default):**
- Faster and more stable for curvilinear HRRR grid
- Suitable for reflectivity fields with smooth spatial gradients
- Avoids degenerate cell issues with curvilinear grids

**Conservative remapping (optional):**
- Preserves spatial integrals
- Requires grid cell bounds estimation for curvilinear HRRR grid
- May fail with degenerate cell errors - use `-m bilinear` instead

#### Processing Workflow

1. **Read GridRad data** using official v4.2 library
2. **Convert dBZ to linear units** (mm⁶/m³) before remapping
3. **Remap 3D arrays directly** (no height level loop - optimized)
4. **Convert back to dBZ** with proper handling of invalid values:
   - Masks zeros, negatives, and non-finite values
   - Sets `missing_value=-999.0` for unmapped/invalid regions
   - Prevents `-inf` values in output
5. **Create CF-compliant output** with:
   - Standard `time` coordinate (datetime objects, auto-encoded by xarray)
   - `base_time` coordinate (seconds since epoch, for compatibility)
   - Proper geolocation (latitude, longitude)
   - Compressed netCDF4 format

#### Weight File Management

Weight files are automatically generated on first run and reused for subsequent files:
- Created: `gridrad_1248x2832_to_hrrr_1059x1799_bilinear.nc`
- Stored in: `WEIGHT_DIR` (default: `/pscratch/sd/i/iclas2/GridRad/weights/`)
- Reused for all files with matching source/destination grids
- Significantly speeds up processing after initial weight generation

### Performance Benchmarks

**Test Configuration:**
- NERSC Perlmutter CPU node: 128 cores, 512 GB RAM
- GridRad grid: 1248 × 2832 × 28 levels
- HRRR grid: 1059 × 1799 × 28 levels
- Method: Bilinear interpolation

**Small batch (24 hourly files, parallel mode with 24 workers):**
```
Total time: 28.0s (0.5 min)
Average: 1.2s per file
```

**Large batch (3,671 hourly files, April-August 2020, parallel mode with 60 workers):**
```
Recommended configuration:
- Workers: 60 (limited by memory: 512GB / 8GB per worker)
- Memory per worker: 8 GB
- Processing time: ~1.2s per file (with weight file reuse)
- Total time: ~75-90 seconds for full batch
- Throughput: ~2,500 files/hour
```

**Resource recommendations for large datasets:**
- **60 workers** for 512 GB node (leaves 32 GB headroom)
- **48 workers** for conservative memory usage
- CPU headroom: 60-70% utilization typical with I/O wait

**Estimated processing times:**
- Single file (first run): ~5-10s (includes weight file generation)
- Single file (subsequent): ~1-2s (reuses weights)
- 100 files (parallel, 60 workers): ~2 minutes
- 1000 files (parallel, 60 workers): ~20 minutes
- 3600+ files (parallel, 60 workers): ~1.5 hours

### Storage and Output

**Per hourly file:**
- Input (GridRad): ~380 MB (compressed)
- Output (HRRR grid): ~250 MB (compressed with deflate_level=1)
- Compression ratio: 2.4:1 from uncompressed
- Variables: 4 (Reflectivity, Nradobs, Nradecho, wReflectivity)

**Total storage for 5-month dataset (April-August 2020):**
- Input: ~1.4 TB (3,671 files)
- Output: ~920 GB (3,671 files)

### Validation and Quality Control

**Check output file structure:**
```bash
ncdump -h GridRad_HRRR_20200616T000000Z.nc
```

**Expected dimensions:**
```
dimensions:
    time = 1 ;
    height = 28 ;
    y = 1059 ;
    x = 1799 ;
```

**Expected variables:**
- `Reflectivity(time, height, y, x)` - Radar reflectivity (dBZ)
  - `missing_value = -999.0`
  - `valid_range = [-20.0, 80.0]`
- `Nradobs(time, height, y, x)` - Number of radar observations
- `Nradecho(time, height, y, x)` - Number of radar echoes
- `wReflectivity(time, height, y, x)` - Reflectivity bin weights
- `time(time)` - CF-compliant time coordinate
- `base_time(time)` - Seconds since 1970-01-01 (epoch)
- `latitude(y, x)` - 2D latitude array
- `longitude(y, x)` - 2D longitude array
- `height(height)` - Height above sea level (km)

### Common Issues and Solutions

**1. Out of memory with parallel processing**
- **Solution:** Reduce number of workers: `-n 48` or `-n 32`
- Each worker needs ~8 GB for safe operation

**2. Slow first-file processing**
- **Cause:** Weight file generation takes 3-5 seconds
- **Solution:** Normal behavior - subsequent files will be fast

**3. Degenerate cell errors with conservative method**
- **Cause:** HRRR curvilinear grid bounds estimation creates degenerate cells
- **Solution:** Use bilinear method (default): `-m bilinear`

**4. Missing time coordinate in output**
- **Cause:** GridRad v4.2 timestamp includes 'Z' suffix
- **Solution:** Automatically handled by datetime parsing in script


---

## File Descriptions

| File | Purpose |
|------|---------|
| **SCREAM Remapping** | |
| `create_regional_remapper.py` | Generate SCRIP file for SCREAM regional spectral element grid |
| `make_HRRR_SCRIP.ncl` | Generate SCRIP file for HRRR curvilinear grid |
| `run_module_RegridWeightGen.sh` | Generate ESMF weight files (neareststod and bilinear) |
| `remap_dbz_zmid_5min.sh` | **Recommended:** Remap + split into individual 5-min files (~12 min/file) |
| `remap_dbz_zmid.sh` | Alternative: Remap to 12-timestep files (~26 min/file) |
| `test_split_timesteps.sh` | Utility to split existing 12-timestep files into individual 5-min files |
| `generate_taskfarmer_list.py` | Generate task list for parallel processing (supports -s/-e short options) |
| `slurm_regrid_taskfarmer.sh` | TaskFarmer batch script for NERSC Perlmutter (16 tasks/node) |
| `find_missing_outputs.sh` | Check tasklist for incomplete outputs, generate reprocessing list |
| **MRMS & GridRad Remapping** | |
| `gridrad.py` | Official GridRad v4.2 data reader library |
| `remap_gridrad_to_hrrr.py` | Remap GridRad 3D reflectivity to HRRR grid using xESMF |
| `make_MRMS_SCRIP.ncl` | Generate SCRIP file for MRMS 3D reflectivity grid |
| `run_module_RegridWeightGen_MRMS.sh` | Generate ESMF weight file for MRMS remapping |
| `remap_mrms_to_hrrr.sh` | Remap MRMS 3D reflectivity to HRRR grid using conservative method |

---

## Contact

For questions or issues with this workflow, contact the E3SM SCREAM team or consult the E3SM User Forum.

**Last Updated:** January 2026
