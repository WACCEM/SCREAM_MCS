#!/bin/bash
# Verify the ERA5 copy: every expected file exists on scratch with the same size as on CFS.
#
# Usage:   bash verify_era5_copy.sh YEAR0 YEAR1        e.g.  bash verify_era5_copy.sh 2007 2007
# Checks the same months as make_era5_globus_script.sh (the years plus the December before and the January after the range).
# Prints one line per month and type; the exit status is 1 when any file is missing or has another size (run the generator again: it lists only
# what is missing, then run the new globus_copy_<year>.sh).
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
source "${here}/era5_common.sh"

if [ $# -ne 2 ]; then echo "usage: bash $0 YEAR0 YEAR1"; exit 2; fi
y0=$1
y1=$2
bad=0
total=0

# Months of the whole range (each year's months once; margin months at the two ends)
months=$( { year_months "${y0}" "${y0}" "${y1}"; for y in $(seq $((y0 + 1)) "${y1}"); do year_months "${y}" "${y0}" "${y1}"; done; } | sort -u)
for ym in ${months}; do
    for type in pl sfc; do
        ok=0
        problems=0
        while read -r f; do
            dst=$(destination_of "${f}" "${type}" "${ym}")
            # A problem is a missing file or a different size; only the first five of each month and type are printed
            if [ ! -f "${dst}" ]; then
                problems=$((problems + 1))
                [ "${problems}" -le 5 ] && echo "  missing on scratch: ${dst}"
            elif [ -f "${f}" ] && [ "$(stat -c %s "${dst}")" != "$(stat -c %s "${f}")" ]; then
                problems=$((problems + 1))
                [ "${problems}" -le 5 ] && echo "  size differs: ${dst}"
            else
                ok=$((ok + 1))
            fi
        done < <(expected_files "${type}" "${ym}")
        total=$((total + ok))
        bad=$((bad + problems))
        echo "${ym} ${type}: ${ok} files ok, ${problems} problems"
    done
done
echo "verified ${total} files, ${bad} problems"
[ "${bad}" -eq 0 ]
