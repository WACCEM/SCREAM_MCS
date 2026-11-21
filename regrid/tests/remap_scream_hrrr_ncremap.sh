#!/bin/bash
#
# Remap SCREAM unstructured grid data to HRRR curvilinear grid using ncremap
#
# This script uses ncremap for standard unstructured to structured grid remapping.
# If your SCREAM data has regional suffix strings (RRG format), use the RRG mode version.
#
# Required inputs:
#   1. Source grid file: SCREAM grid with lat/lon
#   2. Destination grid file: HRRR grid with lat/lon
#   3. Source data file: SCREAM data to remap
#
# Author: Generated for SCREAM to HRRR remapping
# Date: 2026-01-26

set -e  # Exit on error

# ==============================================================================
# USER CONFIGURATION
# ==============================================================================

# Source SCREAM data file to remap
DAT_SRC="/pscratch/sd/w/wcmca1/SCREAMv1-cess2/run_conus/output.scream.diag_equiv_reflectivity.5min.INSTANT.nmins_x5.2020-06-06-79500.nc"

# SCREAM grid file (contains lat/lon for ncol dimension)
GRD_SRC="/pscratch/sd/w/wcmca1/SCREAMv1-cess2/maps/scream_conus_ne1024_grid.nc"

# Destination grid file (HRRR with lat/lon for y,x dimensions)
# GRD_DST="/pscratch/sd/w/wcmca1/SCREAMv1-cess2/maps/hrrr_latlon.nc"
GRD_DST="/pscratch/sd/w/wcmca1/SCREAMv1-cess2/maps/hrrr_sfc_latlon_crop.nc"

# Output directory
OUT_DIR="/pscratch/sd/w/wcmca1/SCREAMv1-cess2/remap_conus"

# Map (weight) file directory
MAP_DIR="/pscratch/sd/w/wcmca1/SCREAMv1-cess2/maps"

# Regridding method: bilinear, conserve, patch, neareststod, nearestdtos
# NOTE: bilinear/conserve fail due to SCREAM grid triangulation issues
# Use neareststod (nearest neighbor) for robustness
REMAP_METHOD="neareststod"

# Output filename
OUT_FILE="${OUT_DIR}/scream_reflectivity_hrrr_ncremap_${REMAP_METHOD}.nc"

# Weight filename (optional - ncremap will auto-generate if not specified)
MAP_FILE="${MAP_DIR}/weight_scream_to_hrrr_${REMAP_METHOD}.nc"

# ==============================================================================
# SETUP
# ==============================================================================

# Create output directories
mkdir -p "${OUT_DIR}"
mkdir -p "${MAP_DIR}"

# Check if input files exist
if [ ! -f "${DAT_SRC}" ]; then
    echo "ERROR: Source data file not found: ${DAT_SRC}"
    exit 1
fi

if [ ! -f "${GRD_SRC}" ]; then
    echo "ERROR: Source grid file not found: ${GRD_SRC}"
    exit 1
fi

if [ ! -f "${GRD_DST}" ]; then
    echo "ERROR: Destination grid file not found: ${GRD_DST}"
    exit 1
fi

# Load NCO module if needed
# module load nco  # Uncomment if NCO is not already loaded

echo "========================================================================"
echo "SCREAM to HRRR Remapping using ncremap"
echo "========================================================================"
echo "Source data:       ${DAT_SRC}"
echo "Source grid:       ${GRD_SRC}"
echo "Destination grid:  ${GRD_DST}"
echo "Remap method:      ${REMAP_METHOD}"
echo "Output file:       ${OUT_FILE}"
echo "Map file:          ${MAP_FILE}"
echo "========================================================================"

# ==============================================================================
# NCREMAP COMMAND
# ==============================================================================

# Build ncremap command with options
NCREMAP_CMD="ncremap"

# Source grid (infer from data file or specify explicitly)
NCREMAP_CMD+=" -s ${GRD_SRC}"

# Destination grid
NCREMAP_CMD+=" -g ${GRD_DST}"

# Regridding algorithm
NCREMAP_CMD+=" -a ${REMAP_METHOD}"

# Map file (optional - ncremap will generate and save it)
NCREMAP_CMD+=" -m ${MAP_FILE}"

# Source and destination files
NCREMAP_CMD+=" ${DAT_SRC} ${OUT_FILE}"

# ==============================================================================
# EXECUTE REMAPPING
# ==============================================================================

echo ""
echo "Executing ncremap command:"
echo "${NCREMAP_CMD}"
echo ""

# Run ncremap
eval ${NCREMAP_CMD}

# Check if output was created successfully
if [ -f "${OUT_FILE}" ]; then
    echo ""
    echo "========================================================================"
    echo "Remapping completed successfully!"
    echo "  Output file: ${OUT_FILE}"
    echo "  Map file:    ${MAP_FILE}"
    echo "========================================================================"
    
    # Print file info
    echo ""
    echo "Output file information:"
    ncdump -h "${OUT_FILE}" | head -50
else
    echo ""
    echo "ERROR: Output file was not created!"
    exit 1
fi
