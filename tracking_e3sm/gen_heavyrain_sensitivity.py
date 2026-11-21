#!/usr/bin/env python
"""
gen_heavyrain_sensitivity.py: configs and Slurm scripts of the heavy_rainrate_thresh sensitivity runs of the E3SM MCS tracking.

The config key heavy_rainrate_thresh [mm/h] is read by two steps of PyFLEXTRKR: matchpf (the heavy-rain sums of the precipitation
features, pyflextrkr/matchtbpf_func.py) and robustmcs (the MCSMIP test on the maximum PF rain rate, pyflextrkr/robustmcs_rows.py). A run
therefore starts at matchpf and goes on with robustmcs, mapfeature, speed, dense_netcdf and rainmap, so that every output agrees with the
key. The steps before matchpf do not depend on it and are shared with the production run through symbolic links.

For every (model, threshold) the script writes, under <e3sm_root>/<model>_remap_0.1deg/mcs_tbpf_sens/heavyrain_<tag>/ (tag 5p0, 3p0, ...):

    <year>/tracking                         symbolic link to the production cloudid / track files (read only)
    <year>/stats/mcs_tracks_<dates>.rows    symbolic link to the production identifymcs output (the only stats input of matchpf)
    <year>/...                              everything written by the run (stats, mcstracking pixel files, monthly rain maps, profile)
    config_<model>_<year>_hr<tag>.yml       the stats config of the production year with only these lines changed: heavy_rainrate_thresh,
                                            root_path, step_profile_dir, grid_area_file (added), run_parallel (1), skip_completed_steps,
                                            and the run_* flags (matchpf ... rainmap on, everything else off)
    slurm_<model>_hr<tag>.sh                one node, the pinned code, then the climatology of the 12 monthly rain maps
    logs/                                   Slurm logs

Production mode (--production, added 2026-11-17): the same machinery makes the PRODUCTION run of every year with one chosen threshold, from matchpf to
trackpcp (the sensitivity runs leave trackpcp off). The tree mirrors the 10 mm/h production <e3sm_root>/<model>_remap_0.1deg/mcs_tbpf/ and is called
mcs_tbpf_hr<tag>/ (tag 2p0, ...), next to it:

    mcs_tbpf_hr<tag>/<year>/tracking                      symbolic link to the production cloudid / track files (read only)
    mcs_tbpf_hr<tag>/<year>/stats/mcs_tracks_<dates>.rows symbolic link to the production identifymcs output
    mcs_tbpf_hr<tag>/<year>/...                           everything written by the run (stats, mcstracking pixel files, monthly rain maps, trackpcp, profile)
    mcs_tbpf_hr<tag>/campaign_<year>/                     config_<model>_<year>_hr<tag>.yml, slurm_<model>_<year>_hr<tag>.sh, logs/

One job per year; no per-year climatology (the multi-year one is made after all years, see finalize_production_tree.py).

Nothing is submitted unless --submit is given. The production folders are never written.

Usage:
    python gen_heavyrain_sensitivity.py --models ne120 --thresholds 10.0               # the control run (the production value)
    python gen_heavyrain_sensitivity.py --models ne120 ne30 --thresholds 5.0 3.0 2.0 1.5 1.0
    python gen_heavyrain_sensitivity.py ... --submit                                    # also sbatch the scripts
    python gen_heavyrain_sensitivity.py --production --models ne120 --years 2009 2010 2011 --thresholds 2.0 --code-dir <worktree> --time 03:00:00
                                                                                        # production at 2.0 mm/h, one job per year (add --submit)
    python gen_heavyrain_sensitivity.py --models ne30 --thresholds 3.0 --skip-completed-steps --code-dir <worktree> --submit
                                                                                        # resubmit a run that failed in a later step:
                                                                                        # matchpf ... are not run again if their outputs are complete
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Steps of run_mcs_tbpf_unified.py: the ones that run (they depend on heavy_rainrate_thresh) and the ones that do not
STEPS_ON = ["run_matchpf", "run_robustmcs", "run_mapfeature", "run_speed", "run_dense_netcdf", "run_rainmap"]
STEPS_OFF = ["run_idfeature", "run_tracksingle", "run_gettracks", "run_trackstats", "run_identifymcs", "run_trackpcp"]
# Production mode: the same steps plus trackpcp (the precipitation accumulated at every pixel of every MCS)
STEPS_ON_PRODUCTION = STEPS_ON + ["run_trackpcp"]
STEPS_OFF_PRODUCTION = [k for k in STEPS_OFF if k != "run_trackpcp"]
# Inodes and disk written by one run (E3SM ne120, one year: 8,760 pixel files of 12 MB and 12 rain maps): used for the quota estimate
INODES_PER_RUN = 8_900
GB_PER_RUN = 110


def parse_args():
    """
    Command line.

    Returns:
        args: argparse.Namespace
    """
    here = Path(__file__).resolve().parent
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--models", nargs="+", default=["ne120", "ne30"], help="E3SM sets (default: %(default)s)")
    p.add_argument("--year", type=int, default=2010, help="production year that the runs are copied from (default: %(default)s)")
    p.add_argument("--years", nargs="+", type=int, default=None,
                   help="several production years (default: only --year); with --production one job per year")
    p.add_argument("--production", action="store_true",
                   help="production run of the years from matchpf to trackpcp in <base>_hr<tag>/<year>/ instead of a sensitivity run "
                        "(default: sensitivity run in <base>_sens/heavyrain_<tag>/<year>/); --thresholds must be given")
    p.add_argument("--thresholds", nargs="+", type=float, default=None,
                   help="heavy_rainrate_thresh values in mm/h (default of the sensitivity runs: 5.0 3.0 2.0 1.5 1.0; required with --production)")
    p.add_argument("--e3sm-root", default="/pscratch/sd/f/feng045/E3SM_polun", help="folder with <model>_remap_0.1deg (default: %(default)s)")
    p.add_argument("--code-dir", default="/pscratch/sd/f/feng045/tbpf_code_a4b8ad8",
                   help="pinned PyFLEXTRKR worktree that made the production outputs (default: %(default)s)")
    p.add_argument("--env", default="/global/common/software/m1867/python/pyflex26.3", help="conda environment (default: %(default)s)")
    p.add_argument("--climo-script", default=str(here.parent / "scripts" / "calc_mcs_rainmap_climo_from_monthly.py"),
                   help="climatology script run after a clean job (default: %(default)s)")
    p.add_argument("--account", default="m1657", help="Slurm account (default: %(default)s)")
    p.add_argument("--qos", default="regular", help="Slurm QOS (default: %(default)s)")
    p.add_argument("--time", default="03:00:00", help="wall time of a job (default: %(default)s)")
    p.add_argument("--skip-completed-steps", action="store_true",
                   help="write skip_completed_steps: True: steps whose outputs are complete are not run again, to resubmit a run that "
                        "failed in a later step (default: False, every step runs; the run tree of an existing run is not emptied either way)")
    p.add_argument("--submit", action="store_true", help="sbatch the scripts (default: only write them)")
    args = p.parse_args()
    # The sensitivity runs have a default list of thresholds; a production run needs the one value to be chosen on purpose
    if args.thresholds is None:
        if args.production:
            p.error("--production needs --thresholds (for example --thresholds 2.0)")
        args.thresholds = [5.0, 3.0, 2.0, 1.5, 1.0]
    args.years = args.years or [args.year]
    return args


def set_key(text, key, value, add_if_missing=False):
    """
    Replace the value of a top-level YAML key that is written on one line, keeping the spacing before it and the comment after it.

    Args:
        text: str
            Config file text.
        key: str
            Key (for example 'run_matchpf'); the line is `key : value   # comment` or `key: value`.
        value: str or number
            New value, written as given.
        add_if_missing: bool (default: False)
            Append `key: value` at the end if the key is absent; otherwise a missing key is an error.

    Returns:
        text: str
            Text with the value replaced.

    Raises:
        ValueError: the key is not present exactly once (or absent while add_if_missing is False).
    """
    pattern = re.compile(rf"^({re.escape(key)}\s*:\s*)([^\s#][^#]*?)(\s*(?:#.*)?)$", re.M)
    found = pattern.findall(text)
    if len(found) == 0 and add_if_missing:
        return text.rstrip("\n") + f"\n{key}: {value}\n"
    if len(found) != 1:
        raise ValueError(f"the key {key!r} occurs {len(found)} times in the config (expected exactly one)")
    return pattern.sub(lambda m: f"{m.group(1)}{value}{m.group(3)}", text)


def get_key(text, key):
    """
    Value of a top-level one-line YAML key, without quotes and comment.

    Args:
        text: str
            Config file text.
        key: str
            Key to read.

    Returns:
        value: str
    """
    m = re.search(rf"^{re.escape(key)}\s*:\s*['\"]?([^'\"#\n]+?)['\"]?\s*(?:#.*)?$", text, re.M)
    if m is None:
        raise ValueError(f"the key {key!r} is not in the config")
    return m.group(1).strip()


def quota_line():
    """
    The pscratch quota line of the user (used inodes and limits), printed before the runs are made.

    Returns:
        line: str
            The `lfs quota -u` output of the user, or a note if it cannot be read.
    """
    try:
        out = subprocess.run(["lfs", "quota", "-u", os.environ.get("USER", "feng045"), "/pscratch"], capture_output=True, text=True).stdout
        return "\n".join(out.strip().splitlines()[-3:])
    except OSError:
        return "(lfs quota not available)"


def make_run(args, model, thr, year):
    """
    Write the run tree, the config and the Slurm script of one (model, threshold, year).

    Args:
        args: argparse.Namespace
            Command line (paths, Slurm settings, production flag).
        model: str
            E3SM set, for example 'ne120'.
        thr: float
            heavy_rainrate_thresh [mm/h] of the run.
        year: int
            Production year that the run is copied from.

    Returns:
        job: dict
            name, script, config, root, tag, model, threshold, year, ledger (the submissions file of the tree).

    Raises:
        FileNotFoundError: the production stats config, the tracking folder or the identifymcs output is missing.
    """
    tag = f"{thr:.1f}".replace(".", "p")
    base = f"{args.e3sm_root}/{model}_remap_0.1deg/mcs_tbpf"
    prod_root = f"{base}/{year}"
    # The stats config of the production year (one file per campaign)
    found = glob.glob(f"{base}/campaign_{year}/*_stats{year}01_{year}12.yml")
    if len(found) != 1:
        raise FileNotFoundError(f"{base}/campaign_{year}: expected one *_stats{year}01_{year}12.yml, found {found}")
    text = Path(found[0]).read_text()
    dates = f"{get_key(text, 'startdate')}_{get_key(text, 'enddate')}"
    # The production inputs of matchpf: the cloudid files and the identifymcs row tables
    prod_tracking = f"{prod_root}/tracking"
    prod_tb = f"{prod_root}/stats/mcs_tracks_{dates}.rows"
    for path in (prod_tracking, f"{prod_tb}/meta.json", f"{prod_root}/stats/grid_area_from_latlon.nc"):
        if not os.path.exists(path):
            raise FileNotFoundError(path)
    # The run tree: the shared inputs are symbolic links, everything else is written by the run
    if args.production:
        top = f"{base}_hr{tag}"                       # the production tree of this threshold, next to mcs_tbpf
        sens_dir = f"{top}/campaign_{year}"           # config, Slurm script and logs of the year
        config = f"{sens_dir}/config_{model}_{year}_hr{tag}.yml"
        script = f"{sens_dir}/slurm_{model}_{year}_hr{tag}.sh"
        name = f"hr{tag}_{model}_{year}"
        steps_on, steps_off = STEPS_ON_PRODUCTION, STEPS_OFF_PRODUCTION
    else:
        top = f"{base}_sens/heavyrain_{tag}"
        sens_dir = top
        config = f"{sens_dir}/config_{model}_{year}_hr{tag}.yml"
        script = f"{sens_dir}/slurm_{model}_hr{tag}.sh"
        name = f"hr{tag}_{model}"
        steps_on, steps_off = STEPS_ON, STEPS_OFF
    sens_root = f"{top}/{year}/"
    os.makedirs(f"{sens_root}stats", exist_ok=True)
    os.makedirs(f"{sens_dir}/logs", exist_ok=True)
    for target, link in ((prod_tracking, f"{sens_root}tracking"), (prod_tb, f"{sens_root}stats/mcs_tracks_{dates}.rows")):
        if not os.path.islink(link):
            os.symlink(target, link)
    # The config: the production lines with only the sensitivity changes
    for key in steps_on:
        # (the ne120 2009 config is older than the dense_netcdf step and has no run_dense_netcdf key: absent means on, so it is added)
        text = set_key(text, key, "True", add_if_missing=True)
    for key in steps_off:
        text = set_key(text, key, "False")
    text = set_key(text, "heavy_rainrate_thresh", f"{thr:.1f}")
    text = set_key(text, "root_path", sens_root)
    text = set_key(text, "step_profile_dir", f"{sens_root}profile")
    text = set_key(text, "run_parallel", 1)
    text = set_key(text, "skip_completed_steps", "True" if args.skip_completed_steps else "False")
    text = set_key(text, "grid_area_file", f"{prod_root}/stats/grid_area_from_latlon.nc", add_if_missing=True)
    last_step = "trackpcp" if args.production else "rainmap"
    kind = "production run" if args.production else "sensitivity run"
    header = (f"# heavy_rainrate_thresh {kind}: {model}, {year}, {thr:.1f} mm/h, from matchpf to {last_step}.\n"
              f"# Generated by scream/tracking_e3sm/gen_heavyrain_sensitivity.py from {found[0]}\n"
              f"# with only these lines changed: heavy_rainrate_thresh, root_path, step_profile_dir, run_parallel, skip_completed_steps,\n"
              f"# the run_* flags, and grid_area_file (added). tracking/ and the identifymcs output are links to the production run.\n")
    Path(config).write_text(header + text)
    # The Slurm script: one node, the pinned code; a sensitivity run also makes the climatology of its 12 monthly rain maps after a clean run
    # (a production run does not: the multi-year climatology is made once after all years)
    climo = f"""
# the climatology only after a clean run
if [ $status -eq 0 ]; then
    python {args.climo_script} --indir {sens_root}stats/monthly --outdir {sens_root}stats/monthly --start-date {year}-01 --end-date {year}-12
    status=$?
fi
""" if not args.production else ""
    what = (f"production run of the E3SM {model} year {year} with {thr:.1f} mm/h (gen_heavyrain_sensitivity.py --production): matchpf, robustmcs,\n"
            f"# mapfeature, speed, dense_netcdf, rainmap and trackpcp" if args.production else
            f"heavy_rainrate_thresh sensitivity run of the E3SM {model} year {year} with {thr:.1f} mm/h (gen_heavyrain_sensitivity.py): matchpf, robustmcs,\n"
            f"# mapfeature, speed, dense_netcdf and rainmap")
    Path(script).write_text(f"""#!/bin/bash
#SBATCH -A {args.account}
#SBATCH -J {name}
#SBATCH --qos={args.qos}
#SBATCH --nodes=1
#SBATCH -C cpu
#SBATCH --time={args.time}
#SBATCH --exclusive
#SBATCH --output={sens_dir}/logs/log_%x_%j.log

# {what} on one node (the run script starts its own Dask LocalCluster, run_parallel: 1).
# The code is the pinned worktree {args.code_dir}.
date

module load python
source activate {args.env}
export PYTHONPATH={args.code_dir}${{PYTHONPATH:+:$PYTHONPATH}}

# the exit status of python (not of the last date) is the exit status of the job, so a failed step shows as FAILED in sacct
python {args.code_dir}/runscripts/run_mcs_tbpf_unified.py {config}
status=$?
{climo}
date
exit $status
""")
    return dict(name=name, script=script, config=config, root=sens_root, tag=tag, model=model, threshold=thr, year=year,
                ledger=f"{top}/submissions.jsonl" if args.production else os.path.join(os.path.dirname(os.path.dirname(script)), "submissions.jsonl"))


def main():
    """Write all runs, print the list and the quota, and submit them if --submit was given."""
    args = parse_args()
    print("pscratch quota (user, kbytes, quota, limit, grace, files, quota, limit, grace):")
    print(quota_line())
    jobs = [make_run(args, model, thr, year) for model in args.models for thr in args.thresholds for year in args.years]
    print(f"\n{len(jobs)} run(s): about {len(jobs) * INODES_PER_RUN:,} inodes and {len(jobs) * GB_PER_RUN:,} GB of pixel files (kept) in total")
    for job in jobs:
        print(f"  {job['name']:18s} {job['threshold']:5.1f} mm/h  year {job['year']}  config {job['config']}\n{'':20s}script {job['script']}\n{'':20s}root   {job['root']}")
    # Submit only on request, and record what was submitted
    if not args.submit:
        print("\nNothing submitted (use --submit).")
        return 0
    for job in jobs:
        out = subprocess.run(["sbatch", job["script"]], capture_output=True, text=True)
        print(out.stdout.strip() or out.stderr.strip())
        with open(job["ledger"], "a") as f:
            f.write(json.dumps(dict(job, submitted=time.strftime("%Y-%m-%d %H:%M:%S"), sbatch=out.stdout.strip())) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
