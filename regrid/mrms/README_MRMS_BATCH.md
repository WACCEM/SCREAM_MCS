# MRMS Batch Processing on NERSC Perlmutter

Parallel remapping of MRMS 3D reflectivity data to HRRR grid using batch SLURM jobs.

## Overview

- **Total files**: 52,705 MRMS reflectivity files
- **Processing time**: ~35 seconds per file (single core)
- **Strategy**: Split into ~19 batches, each running as 1-hour SLURM job
- **Parallelization**: 32 workers per node (128-core CPU nodes, optimal for I/O)
- **Expected total time**: ~2 hour (all batches running in parallel)

## Quick Start

### Step 1: Create batch file lists

```bash
cd /global/homes/f/feng045/program/scream/regrid/mrms
./create_mrms_batches.py
```

This creates 19 batch files (each ~2,800 files):
- `/pscratch/sd/i/iclas2/MRMS/batches/mrms_batch_01.txt`
- `/pscratch/sd/i/iclas2/MRMS/batches/mrms_batch_02.txt`
- ... through `mrms_batch_19.txt`

### Step 2: Submit all batch jobs

```bash
./submit_all_mrms_batches.sh
```

This submits all 6 SLURM jobs to the queue.

### Step 3: Monitor progress

```bash
# One-time check
./monitor_mrms_progress.sh

# Continuous monitoring (updates every 30 seconds)
watch -n 30 ./monitor_mrms_progress.sh

# Check SLURM queue
squeue -u $USER

# View specific job log (real-time)
tail -f /pscratch/sd/i/iclas2/MRMS/batches/logs/mrms_batch_*.log
```

## Manual Job Submission

Submit individual batches:

```bash
# Submit specific batch
sbatch slurm_remap_mrms_batch.sh 1

# Submit multiple batches
for i in {1..3}; do 
    sbatch slurm_remap_mrms_batch.sh $i
done
```

## File Locations

### Input
- MRMS files: `/pscratch/sd/i/iclas2/meng/mrms/conus_2025_netcdf/MRMS_MergedReflectivityQC_L33/`
- Format: `MRMS_MergedReflectivityQC_L33_YYYYMMDD-HHMMSS.nc`

### Output
- Remapped files: `/pscratch/sd/i/iclas2/MRMS/remap_hrrr/`
- Format: `MRMS_Reflectivity_HRRR_YYYYMMDD-HHMMSS.nc`

### Processing
- Batch lists: `/pscratch/sd/i/iclas2/MRMS/batches/`
- Job logs: `/pscratch/sd/i/iclas2/MRMS/batches/logs/`
- Temporary files: `/pscratch/sd/i/iclas2/MRMS/tmp/` (auto-cleaned)

## Performance Details

### Batch Configuration
- **Files per batch**: 2,800 files
- **Workers per node**: 32 (optimal for I/O and memory)
- **Target time per batch**: 120 minutes (2 hours)
- **Files per worker**: ~88 files
- **Processing rate**: ~24 files/min (measured from test)

### Resource Usage
- **Queue**: regular
- **Account**: m1867
- **Nodes per job**: 1 CPU node (128 cores)
- **Time limit**: 2 hours
- **Memory**: ~16-26 GB typical for 32 workers (256 GB available per CPU node)

### Expected Timeline
```
Serial processing:  512 hours
Parallel (19 jobs): ~2 hours (with queue time)
Total files:        52,705 files
Output size:        ~13 TB (assuming ~250 MB per file)
```

## Troubleshooting

### Check for failures

```bash
# Look for error messages in logs
grep -i error /pscratch/sd/i/iclas2/MRMS/batches/logs/*.log

# Check non-empty error files
find /pscratch/sd/i/iclas2/MRMS/batches/logs -name "*.err" -size +0

# View job log for specific batch
cat /pscratch/sd/i/iclas2/MRMS/batches/logs/batch_01_joblog.txt
```

### Resubmit failed batch

```bash
# Identify failed files from joblog
awk '$7 != 0' /pscratch/sd/i/iclas2/MRMS/batches/logs/batch_01_joblog.txt

# Resubmit entire batch
sbatch slurm_remap_mrms_batch.sh 1
```

### Cancel jobs

```bash
# Cancel specific job
scancel <job_id>

# Cancel all your jobs
scancel -u $USER

# Cancel only MRMS jobs
squeue -u $USER -o "%.18i %.30j" | grep mrms_remap | awk '{print $1}' | xargs scancel
```

## Verification

After completion, verify output:

```bash
# Count output files
ls /pscratch/sd/i/iclas2/MRMS/remap_hrrr/MRMS_Reflectivity_HRRR_*.nc | wc -l
# Should be: 52,705

# Check file sizes (should be ~250 MB each)
ls -lh /pscratch/sd/i/iclas2/MRMS/remap_hrrr/ | head -20

# Verify a sample file structure
ncdump -h /pscratch/sd/i/iclas2/MRMS/remap_hrrr/MRMS_Reflectivity_HRRR_20250930-223040.nc

# Check for any empty or corrupt files
find /pscratch/sd/i/iclas2/MRMS/remap_hrrr -name "*.nc" -size -1M
```

## Scripts Overview

| Script | Purpose |
|--------|---------|
| `create_mrms_batches.py` | Split file list into batches |
| `remap_mrms_to_hrrr.sh` | Single-file remapping (called by parallel) |
| `slurm_remap_mrms_batch.sh` | SLURM job script for batch processing |
| `submit_all_mrms_batches.sh` | Submit all batches at once |
| `monitor_mrms_progress.sh` | Monitor processing progress |

## Notes

- Each job targets 50 minutes to stay under 1-hour limit (includes overhead)
- GNU `parallel` provides automatic load balancing and progress reporting
- Temporary files are auto-cleaned after each file completes
- Conservative parallelization (100 vs 128 cores) improves I/O performance
- Compression level 1 balances file size vs processing speed

## Contact

For questions or issues, contact Zhe Feng (zhe.feng@pnnl.gov)
