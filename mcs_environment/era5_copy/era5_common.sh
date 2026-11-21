#!/bin/bash
# Common definitions of the ERA5 copy scripts (sourced by make_era5_globus_script.sh and verify_era5_copy.sh, not run by itself).
#
# Which ERA5 files the MCS environment extraction needs (CFS -> scratch):
#   pressure levels, one file per DAY and variable:   e5.oper.an.pl/YYYYMM/e5.oper.an.pl.<code>.ll025sc.YYYYMMDD00_YYYYMMDD23.nc
#   surface,        one file per MONTH and variable:  e5.oper.an.sfc/YYYYMM/e5.oper.an.sfc.<code>.ll025sc.YYYYMM0100_YYYYMM<last day>23.nc

# Source (CFS) and destination (scratch); override with the environment variables ERA5_SRC and ERA5_DST
indir=${ERA5_SRC:-/global/cfs/projectdirs/m3522/cmip6/ERA5}
outdir=${ERA5_DST:-/pscratch/sd/w/wcmca1/ERA5}

# Variable codes: Q, R, W on pressure levels; TCWV and surface pressure (SP masks the 850 hPa fields below the ground)
pl_vars=("128_133_q" "128_157_r" "128_135_w")
sfc_vars=("128_137_tcwv" "128_134_sp")

# days_in_month YYYY MM -> number of days of that month (28..31, Gregorian)
days_in_month() {
    date -d "$1-$2-01 +1 month -1 day" +%d
}

# year_months YEAR Y0 Y1 -> the months (YYYYMM, one per line) that the script of YEAR copies: its 12 months, plus the December before the first year
# and the January after the last year (the 24 h before an MCS that starts on 1 January and the last hours of the last year need them)
year_months() {
    local y=$1 y0=$2 y1=$3 m
    if [ "$y" -eq "$y0" ]; then echo "$((y0 - 1))12"; fi
    for m in $(seq -w 1 12); do echo "${y}${m}"; done
    if [ "$y" -eq "$y1" ]; then echo "$((y1 + 1))01"; fi
}

# expected_files TYPE YYYYMM -> the source files of one month, one path per line (TYPE is pl or sfc)
expected_files() {
    local type=$1 ym=$2 y=${2:0:4} m=${2:4:2} dim d v
    dim=$(days_in_month "$y" "$m")
    if [ "$type" = "pl" ]; then
        for v in "${pl_vars[@]}"; do
            for d in $(seq -w 1 "$dim"); do
                echo "${indir}/e5.oper.an.pl/${ym}/e5.oper.an.pl.${v}.ll025sc.${ym}${d}00_${ym}${d}23.nc"
            done
        done
    else
        for v in "${sfc_vars[@]}"; do
            echo "${indir}/e5.oper.an.sfc/${ym}/e5.oper.an.sfc.${v}.ll025sc.${ym}0100_${ym}${dim}23.nc"
        done
    fi
}

# destination_of SOURCE_FILE TYPE YYYYMM -> where the file goes on scratch (same month folder as on CFS)
destination_of() {
    echo "${outdir}/e5.oper.an.$2/$3/$(basename "$1")"
}
