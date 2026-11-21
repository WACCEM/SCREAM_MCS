#!/bin/bash
# Move the SCREAM remapped 3-D reflectivity files that zstash extracted into the sub-folder
#   /pscratch/sd/w/wcmca1/SCREAMv1-cess2/remap_conus_5min/remap_conus_5min/
# up one level, where the tracking configs expect them (clouddata_path).
#
# usage: flatten_remap_dir.sh            dry run: only reports
#        flatten_remap_dir.sh --apply    moves the files
#
# mv inside one file system only renames the entry (metadata), the data is not read or copied, so it is safe even for
# files on a degraded OST; the check below is to report them.
# Not moved: a file that already exists in the parent (reported) and files of size 0. The 3 most recently written files
# are listed: after an interrupted zstash extraction the last one is probably partial (file sizes differ by month, from
# about 520 to 610 MB, so a size threshold cannot tell).
PARENT=/pscratch/sd/w/wcmca1/SCREAMv1-cess2/remap_conus_5min
SUB=$PARENT/remap_conus_5min
APPLY=0
[ "$1" == "--apply" ] && APPLY=1

cd $SUB || exit 1
# file list from ls | grep (a glob of 38,000 names exceeds the argument limit)
ls -1 | grep -E '^scream\.diag_equiv_reflectivity\.5min\.INSTANT\.nmins_x5\..*\.nc$' > /tmp/flatten_names.$$
echo "files in sub-folder: $(wc -l < /tmp/flatten_names.$$)"
# sizes (metadata only)
xargs -a /tmp/flatten_names.$$ -n 500 stat -c "%s %n" > /tmp/flatten_sizes.$$
echo "most recently written (check these after an interrupted extraction):"
xargs -a /tmp/flatten_names.$$ -n 500 stat -c "%Y %n" | sort -n | tail -3 | awk '{print "  "$2}'

# files of the sub-folder that are on the OST that is reported not FULL
bad=$(for f in /proc/fs/lustre/osc/scratch-OST*/import; do s=$(timeout 5 grep -m1 "state:" $f 2>/dev/null); case "$s" in *FULL*) ;; *) basename $(dirname $f) | sed -E 's/scratch-OST([0-9a-f]{4}).*/\1/';; esac; done)
for h in $bad; do
  idx=$((16#$h))
  c=$(xargs -a /tmp/flatten_names.$$ -n 100 lfs getstripe -i 2>/dev/null | grep -c "^${idx}$")
  echo "OST $idx (not FULL): $c files in the sub-folder"
done

nmove=0; nskip=0
while read -r size name; do
  if [ -e "$PARENT/$name" ]; then echo "EXISTS in parent, not moved: $name"; nskip=$((nskip+1)); continue; fi
  if [ "$size" -eq 0 ]; then echo "EMPTY, not moved: $name"; nskip=$((nskip+1)); continue; fi
  nmove=$((nmove+1))
  [ $APPLY -eq 1 ] && mv -n "$name" "$PARENT/$name"
done < /tmp/flatten_sizes.$$
rm -f /tmp/flatten_sizes.$$ /tmp/flatten_names.$$
if [ $APPLY -eq 1 ]; then echo "moved $nmove files, skipped $nskip"; else echo "dry run: would move $nmove files, skip $nskip (use --apply)"; fi
