#!/usr/bin/env python
"""
finalize_production_tree.py: make the cross-year folders of a production tree made by gen_heavyrain_sensitivity.py --production.

The production jobs write one folder per year, <e3sm_root>/<model>_remap_0.1deg/mcs_tbpf_hr<tag>/<year>/. The notebooks and the converter read the
same layout as the 10 mm/h production <model>_remap_0.1deg/mcs_tbpf/, which has two folders across the years. This script makes them, as relative
symbolic links (nothing is copied, nothing is deleted):

    mcs_tbpf_hr<tag>/stats/mcs_tracks_final_<dates>.rows   -> ../<year>/stats/mcs_tracks_final_<dates>.rows       (one per year)
    mcs_tbpf_hr<tag>/monthly/mcs_rainmap_<YYYYMM>.nc       -> ../<year>/stats/monthly/mcs_rainmap_<YYYYMM>.nc    (12 per year)

It stops with an error if a year has no final row tables or not exactly 12 monthly rain maps (a year that has not finished), and it never replaces
a file or a link that exists and points elsewhere. Afterwards it prints the commands that make the multi-year climatology and the combined Parquet
files (they need a compute node and are run by hand).

Usage:
    python finalize_production_tree.py --models ne120 ne30 --tag 2p0
"""
import argparse
import glob
import os
import sys


def parse_args():
    """
    Command line.

    Returns:
        args: argparse.Namespace
            models (list of str), tag (str), e3sm_root (str).
    """
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--models", nargs="+", default=["ne120", "ne30"], help="E3SM sets (default: %(default)s)")
    p.add_argument("--tag", required=True, help="threshold tag of the tree, for example 2p0 for mcs_tbpf_hr2p0")
    p.add_argument("--e3sm-root", default="/pscratch/sd/f/feng045/E3SM_polun",
                   help="folder with <model>_remap_0.1deg (default: %(default)s)")
    return p.parse_args()


def link_once(target, link):
    """
    Make a symbolic link, or check that it exists already and points to the same target.

    Args:
        target: str
            What the link points to (written as given: a relative path).
        link: str
            Path of the link.

    Returns:
        created: bool
            True if the link was made, False if it existed already with the same target.

    Raises:
        FileExistsError: the path exists and is not a link to `target`.
    """
    # Existing link with the right target: nothing to do; anything else at the path is an error
    if os.path.islink(link):
        if os.readlink(link) == target:
            return False
        raise FileExistsError(f"{link} is a link to {os.readlink(link)}, not to {target}")
    if os.path.exists(link):
        raise FileExistsError(f"{link} exists and is not a link")
    os.symlink(target, link)
    return True


def finalize_model(top):
    """
    Make the stats/ and monthly/ link folders of one production tree.

    Args:
        top: str
            Production tree of one model and threshold, <e3sm_root>/<model>_remap_0.1deg/mcs_tbpf_hr<tag>.

    Returns:
        summary: dict
            years (list of str), rows (number of row folders linked), maps (number of rain maps linked), created (number of new links).

    Raises:
        FileNotFoundError: no year folder, a year without final row tables, or a year without 12 monthly rain maps.
    """
    # The year folders (four digits) of the tree
    years = sorted(d for d in os.listdir(top) if d.isdigit() and len(d) == 4 and os.path.isdir(f"{top}/{d}"))
    if not years:
        raise FileNotFoundError(f"no year folder in {top}")
    os.makedirs(f"{top}/stats", exist_ok=True)
    os.makedirs(f"{top}/monthly", exist_ok=True)
    n_rows = n_maps = created = 0
    # Loop over the years: link the final row tables and the 12 monthly rain maps
    for year in years:
        rows = sorted(glob.glob(f"{top}/{year}/stats/mcs_tracks_final_*.rows"))
        maps = sorted(glob.glob(f"{top}/{year}/stats/monthly/mcs_rainmap_{year}[0-1][0-9].nc"))
        if len(rows) != 1 or not os.path.exists(f"{rows[0]}/meta.json"):
            raise FileNotFoundError(f"{top}/{year}: expected one complete mcs_tracks_final_*.rows, found {rows}")
        if len(maps) != 12:
            raise FileNotFoundError(f"{top}/{year}: expected 12 monthly rain maps, found {len(maps)}")
        # One link per final row folder: stats/<name> -> ../<year>/stats/<name>
        name = os.path.basename(rows[0])
        created += link_once(f"../{year}/stats/{name}", f"{top}/stats/{name}")
        n_rows += 1
        # One link per monthly rain map: monthly/<name> -> ../<year>/stats/monthly/<name>
        for m in maps:
            name = os.path.basename(m)
            created += link_once(f"../{year}/stats/monthly/{name}", f"{top}/monthly/{name}")
            n_maps += 1
    return dict(years=years, rows=n_rows, maps=n_maps, created=created)


def main():
    """Finalize the tree of every model and print the next commands."""
    args = parse_args()
    for model in args.models:
        top = f"{args.e3sm_root}/{model}_remap_0.1deg/mcs_tbpf_hr{args.tag}"
        res = finalize_model(top)
        first, last = res["years"][0], res["years"][-1]
        print(f"{model}: years {first}-{last} ({len(res['years'])}), {res['rows']} row folders and {res['maps']} rain maps linked "
              f"({res['created']} new links) in {top}")
        # The next steps, for a compute node
        print(f"  climatology: python scripts/calc_mcs_rainmap_climo_from_monthly.py --indir {top}/monthly --outdir {top}/monthly "
              f"--start-date {first}-01 --end-date {last}-12")
        for region in ("tropics", "global"):
            print(f"  parquet:     python scripts/combine_filter_mcs_trackstats.py --indir {top}/stats --pattern 'mcs_tracks_final_*.rows' "
                  f"--region {region} --outdir {top}/stats")
    return 0


if __name__ == "__main__":
    sys.exit(main())
