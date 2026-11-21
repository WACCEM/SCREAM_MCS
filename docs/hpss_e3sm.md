# Archiving the E3SM MCS-tracking output on HPSS (htar) and getting it back

`tracking_e3sm/hpss_e3sm_backup.py` writes every top-level directory of `<root>/<model>_remap_0.1deg` to NERSC HPSS as ONE tar archive;
`tracking_e3sm/hpss_e3sm_restore.py` brings back whole archives or any sub-folder of them. Both run `htar`, which works on login nodes and in the
**xfer QOS** (free of charge, up to 48 h, runs on a login-type node), not on compute nodes: `tracking_e3sm/slurm_hpss_e3sm_backup.sbatch` and
`slurm_hpss_e3sm_restore.sbatch` are the job scripts, `tracking_e3sm/hpss_e3sm_lib.py` the library, `tests/test_hpss_e3sm.py` the tests.
The scripts are modeled on `airscape/MRMS_Processing/scripts/hpss_backup.py` / `hpss_restore.py` (same plan / `--run` / verify / CSV pattern, same limits).

## Layout

```text
/home/f/feng045/E3SM_polun/ne120_remap_0.1deg/<dir>.tar            (+ <dir>.tar.idx written by htar, + <dir>.tar.links.tsv written by the script)
/home/f/feng045/E3SM_polun/ne30_remap_0.1deg/<dir>.tar
```

`E3SM_polun` also holds four older archives (`E3SM_CTL.tar`, `maps.tar`, `OBS_180W-179E.tar`, `stats.tar`, 26 Oct 2026): the scripts do not touch them.

| directory | what it is | ne120 (GB) | ne30 (GB) |
|---|---|---|---|
| `mcs_tbpf` | the 10 mm/h production: cloudid and track files, pixel files, statistics, trackpcp (ne120 2009-2011, ne30 2009-2020) | 634.7 | 958.7 |
| `mcs_tbpf_hr2p0` | the 2.0 mm/h production (matchpf to trackpcp); links into `mcs_tbpf` | 336.4 | 522.9 |
| `mcs_tbpf_sens` | the one-year `heavy_rainrate_thresh` sensitivity runs; links into `mcs_tbpf` | 655.2 | 213.0 |
| `olr_pcp` | the regridded OLR / precipitation input | 149.5 | 201.9 |

(plan of 2026-11-18: 8 archives, 3.67 TB, 26,000 to 318,000 members each, none refused). Every archive is inside the 100 GB - 2 TB range NERSC recommends.
`animations_2panel_tbpf` and `quicklooks_2panel_tbpf` are not backed up unless named with `--dirs`.
The members are the paths relative to the model folder (`mcs_tbpf/2010/mcstracking/.../mcstrack_*.nc`), so extracting into a folder recreates the tree.

## The symbolic links (read this before restoring)

htar limits a link name to 99 characters, and the trees hold tens of thousands of absolute links whose targets are 110 to 116 characters long
(`mcs_tbpf/<year>/tracking/campaign_*/cloudid_*.nc`, `mcs_tbpf_hr2p0/<year>/stats/mcs_tracks_*.rows`, `.../tracking`). So:

* **htar archives the real files only.** The scan never follows a link, so a derived tree does not duplicate the files it links to.
* Every symbolic link and every empty directory goes into the **manifest** `<dir>.tar.links.tsv` (a header with the model folder the paths come from,
  `L<TAB>link<TAB>target`, `D<TAB>empty dir`), which the backup script copies to HPSS next to the tar (`hsi put`).
* The restore script reads the manifest back and recreates the links and empty directories (only those under the requested paths). `--relink` rewrites an
  absolute target that points into the original data root to point into `--dest`, so that a tree restored together with the tree it links to works.
* **`mcs_tbpf_hr2p0` and `mcs_tbpf_sens` are complete only together with `mcs_tbpf`** (their `tracking` folders and identifymcs row tables are links into it):
  restore both and use `--relink`.

## Back up

| | without `--run`: the **plan** (a dry run) | with `--run`: what the xfer job does |
|---|---|---|
| does | scans the directories and prints one line per archive: name, files, links, GB, notes | writes each archive with htar, reads it back to check its CRCs, copies the manifest, records the result |
| writes | **nothing**: no list file, no log, no CSV, nothing in HPSS | list files, htar logs, a CSV report in `<root>/_hpss_logs` and the archives |
| runs on | a login or compute node (it only lists and `stat`s files, about 1 min) | the **xfer QOS** only |

```bash
cd /global/u1/f/feng045/program/scream
python tracking_e3sm/hpss_e3sm_backup.py                                   # the plan of both models (nothing is written)
mkdir -p /pscratch/sd/f/feng045/E3SM_polun/_hpss_logs/slurm                # the Slurm log folder must exist before sbatch
for M in ne120 ne30; do sbatch --export=ALL,MODELS=$M,WORKERS=4 tracking_e3sm/slurm_hpss_e3sm_backup.sbatch; done     # one xfer job per model
tail -f /pscratch/sd/f/feng045/E3SM_polun/_hpss_logs/slurm/e3sm_hpss_backup_<jobid>.out     # the plan, then one line per finished archive
python tracking_e3sm/hpss_e3sm_restore.py --list                           # what HPSS holds now
```

**Reading the plan.** Columns: archive (below the HPSS folder), real files, links, GB, notes.

| note | meaning | what happens |
|---|---|---|
| `ok` | nothing to report | the archive is written |
| `SKIP: ...` | no files, or the newest file is younger than `--min-age-min` (default 30): the directory is probably still being written | left for later, run again when the files are final |
| `... below the recommended 100 GB`, `... above htar's soft limit` | warnings | written anyway |
| anything else (a `.tmp` / `.part` file, a path longer than 154 + 99 characters, a file above 64 GB, a bundle above 2 TB, a socket or fifo) | **refusal** | that archive is not written, exit status 1; the others are |

Options: `--models`, `--dirs NAME ...` (default: all directories but the two excluded ones; naming one includes it), `--hpss-dir` (must exist), `--workers` (archives at the
same time, default 3, HPSS allows 15 sessions), `--verify-existing` (read archives that are in HPSS already back and check their CRCs), `--no-crc`, `--min-age-min`, `--work-dir`.
The job script reads `MODELS`, `DIRS`, `WORKERS`, `EXTRA`, `ROOT`, `HPSS_DIR` from the environment (the header of `slurm_hpss_e3sm_backup.sbatch` has the recipes).

What `--run` does for each archive: checks the limits (a violation refuses it), writes the list of files, runs `htar -c -V -Hcrc -M n -L list` in the model folder, verifies with
`htar -K -Hverify=crc` (reads the archive back), confirms that the tar and its `.idx` are in HPSS and puts the manifest. Status per archive: `verified` (written and read back),
`written` (`--no-crc`), `exists` (already in HPSS with its index: skipped; a missing manifest is added), `skipped`, `refused`, `incomplete` (a tar without its `.idx`, the sign of an
interrupted htar: reported, never touched; check it, `hsi rm` it if it is garbage, run again), `failed` (see the log named in the message).
**Restart:** submit the same job again after a time-out or a failure. **htar cannot append:** archive a directory when its files are final (a later change is a new archive).
Nothing is ever deleted on scratch or in HPSS by these scripts.

## Restore

```bash
python tracking_e3sm/hpss_e3sm_restore.py --list
# the plan and the htar command of one sub-folder, nothing extracted
python tracking_e3sm/hpss_e3sm_restore.py --models ne120 --dirs mcs_tbpf_hr2p0 --path mcs_tbpf_hr2p0/2010/stats --dest $SCRATCH/restore --dry-run
# do it (small: on a login node; larger: in the xfer QOS)
python tracking_e3sm/hpss_e3sm_restore.py --models ne120 --dirs mcs_tbpf_hr2p0 --path mcs_tbpf_hr2p0/2010/stats --dest $SCRATCH/restore
PATHS="mcs_tbpf_hr2p0/2010/stats" DIRS="mcs_tbpf_hr2p0" sbatch --export=ALL,MODELS=ne120,DEST=$SCRATCH/restore tracking_e3sm/slurm_hpss_e3sm_restore.sbatch
# a whole tree with its links, together with the tree it links to
DIRS="mcs_tbpf mcs_tbpf_hr2p0" EXTRA="--relink" sbatch --export=ALL,MODELS=ne30,DEST=$SCRATCH/restore tracking_e3sm/slurm_hpss_e3sm_restore.sbatch
```

* `--dest` plays the role of the data root: the files come back as `<dest>/<model>_remap_0.1deg/<dir>/...`. Restoring into the original data root is refused.
* `--path` names folders or files of the archive (relative to the model folder). The member list is read from the index (no tape), and only those folders are named to `htar -x -p`.
  A path that is a link or that has no member below it is an error.
* A path that already exists in `--dest` is left alone (`--overwrite` extracts it again and replaces links that point elsewhere). After each archive the number of files per requested
  path is compared with the member list; a shortfall is a failure.
* `-Hcrc` is used while extracting (`--no-crc` to skip); `--nostage` is htar's `-Hnostage` for a few small members of an archive of 100 GB or more.
* The CSV of the run (`restore_<time>.csv`) and htar's logs are in `<dest>/_hpss_logs` (`--work-dir`).

## Checked

* `tests/test_hpss_e3sm.py` (20 tests, `python -m pytest tests/test_hpss_e3sm.py`): limits, links and manifest, skipping, interrupted / failed / refused archives, partial restores, relink, counts,
  dry runs, with `htar` / `hsi` replaced by small programs that keep a tape in a temporary folder.
* **Against real HPSS (2026-11-18, folder `/home/f/feng045/E3SM_polun/_smoke`, removed afterwards; login node):** `quicklooks_2panel_tbpf` (25 files, 45 MB) and a synthetic directory
  with a link whose target has 144 characters, a relative link, a link to a directory and an empty folder were written, **verified against their CRCs**, indexed and listed in 2-3 s each;
  restored they are identical: `diff -r` and `cmp` byte for byte, permissions and modification times equal, the same link targets, the empty folder back; a sub-path restore named only that
  folder to htar; `--relink` rewrote the 144-character target into the destination and the link resolves; a restore into the original data root and a path that is not in the archive are refused.
