#!/usr/bin/env python
"""Step 4: check the outputs of one dataset (native monthly files, 1 degree monthly files, climatology).

For every month of the period: the file exists; every variable is stored deflated + shuffled; the variables, their units and standard names are
those of config/variables.yaml; the time stamp is the month of the file name; the values lie in the plausible range of the dictionary
(``valid_range``: this catches a wrong unit); the share of missing cells is small (pressure-level variables at 850 hPa have the below-ground
cells, everything else only the polar rows of the ne30pg2 maps). The climatology file must exist, with 12 months and compressed variables.
A table of the area-free mean, min and max over the months follows. Exit code 1 if any problem was found.

Example:
    python check_env_monthly.py --config config/3km_CTL.yaml
"""

import argparse
import sys
from pathlib import Path

import netCDF4
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from envmonthly.config import load_dataset  # noqa: E402
from envmonthly.timeaxis import check_file_month, parse_month  # noqa: E402
from envmonthly.writer import check_compression  # noqa: E402

# Largest share of missing cells: variables on a level near the ground (>= 700 hPa) have below-ground cells, all others only polar rows
MAX_NAN_LOW_LEVEL, MAX_NAN_OTHER = 0.15, 0.03


def check_file(path, ds_cfg, year, month, grid_kind):
    """Check one monthly file.

    Args:
        path: the file.
        ds_cfg: ``config.Dataset``.
        year, month: the month the file name says.
        grid_kind: ``"ncol"`` or ``"latlon"`` (the dimensions the file must have).

    Returns:
        (problems, stats): list of problem strings and dict name -> (mean, min, max, nan fraction) of the valid values.
    """
    problems = [f"{path.name}: {p}" for p in check_compression(path, names=ds_cfg.output_names())]
    stats = {}
    with netCDF4.Dataset(path) as ds:
        # Time stamp: the month of the file name
        try:
            check_file_month(ds, year, month, ds_cfg.calendar)
        except ValueError as exc:
            problems.append(f"{path.name}: {exc}")
        if ("ncol" in ds.dimensions) != (grid_kind == "ncol"):
            problems.append(f"{path.name}: wrong horizontal dimensions {list(ds.dimensions)}")
        # Every variable: presence, units, standard name, range, missing share
        for name in ds_cfg.output_names():
            d = ds_cfg.dictionary[name]
            if name not in ds.variables:
                problems.append(f"{path.name}: variable {name} is missing")
                continue
            v = ds[name]
            if getattr(v, "units", None) != d["units"] or getattr(v, "standard_name", None) != d["standard_name"]:
                problems.append(f"{path.name}: {name} has units '{getattr(v, 'units', None)}' / standard_name '{getattr(v, 'standard_name', None)}'")
            x = np.ma.filled(v[...].astype(np.float64), np.nan)
            x[np.abs(x) > 1e19] = np.nan
            nan = float(np.mean(~np.isfinite(x)))
            limit = MAX_NAN_LOW_LEVEL if d.get("plev_hpa", 0) >= 700 else MAX_NAN_OTHER
            if nan > limit:
                problems.append(f"{path.name}: {name} has {100 * nan:.1f} % missing cells (limit {100 * limit:.0f} %)")
            if nan == 1.0:
                continue
            lo, hi = d["valid_range"]
            if np.nanmin(x) < lo or np.nanmax(x) > hi:
                problems.append(f"{path.name}: {name} range {np.nanmin(x):.4g} .. {np.nanmax(x):.4g} is outside {lo} .. {hi}")
            stats[name] = (float(np.nanmean(x)), float(np.nanmin(x)), float(np.nanmax(x)), nan)
    return problems, stats


def main():
    """Check the monthly files and the climatology of a dataset and print the summary table."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True, help="dataset YAML file (config/<dataset>.yaml)")
    ap.add_argument("--start", default=None, help="first month YYYY-MM (default: the period of the config)")
    ap.add_argument("--end", default=None, help="last month YYYY-MM (default: the period of the config)")
    args = ap.parse_args()
    ds = load_dataset(args.config)
    start, end = (parse_month(args.start) if args.start else ds.start), (parse_month(args.end) if args.end else ds.end)
    months = ds.months(start, end)
    problems = []

    # Native and 1 degree monthly files of every month
    for label, path_of, kind in (("native", ds.native_path, ds.streams[0].layout), ("1 degree", ds.latlon_path, "latlon")):
        all_stats, missing = {n: [] for n in ds.output_names()}, []
        for year, month in months:
            path = path_of(year, month)
            if not path.exists():
                missing.append((year, month))
                continue
            p, s = check_file(path, ds, year, month, kind)
            problems += p
            for n, v in s.items():
                all_stats[n].append(v)
        # Exactly the months the config lists as known gaps may be missing
        unexpected = [m for m in missing if m not in ds.known_missing]
        if unexpected:
            problems.append(f"{label}: {len(unexpected)} of {len(months)} monthly files are missing: "
                            f"{', '.join(f'{y}-{m:02d}' for y, m in unexpected[:8])}{' ...' if len(unexpected) > 8 else ''}")
        present_known = [m for m in months if m in ds.known_missing and m not in missing]
        if present_known:
            print(f"   note: files exist for months listed as known gaps (update known_missing_months): {present_known}")
        print(f"{ds.name} {label}: {len(months) - len(missing)} of {len(months)} files" + (f" ({len(missing)} known gaps)" if missing and not unexpected else ""))
        for n, vals in all_stats.items():
            if vals:
                a = np.array(vals)
                print(f"   {n:7s} [{ds.dictionary[n]['units']:>7s}] mean of the months {a[:, 0].mean():12.5g}  (monthly means {a[:, 0].min():.5g} .. {a[:, 0].max():.5g})  "
                      f"min {a[:, 1].min():.5g}  max {a[:, 2].max():.5g}  missing {100 * a[:, 3].mean():.2f} %")

    # Climatology
    climo = ds.climo_path(start, end)
    if not climo.exists():
        problems.append(f"climatology {climo.name} does not exist (run calc_env_climo.py)")
    else:
        problems += [f"{climo.name}: {p}" for p in check_compression(climo, names=ds.output_names())]
        with netCDF4.Dataset(climo) as c:
            n_time = len(c.dimensions["time"])
            print(f"{ds.name} climatology: {climo.name}, {n_time} months, files per calendar month {c['nmonths'][:].tolist()}")
            if n_time != 12:
                problems.append(f"{climo.name}: {n_time} time steps, expected 12")

    print("PROBLEMS:" if problems else "all checks passed", *problems[:40], sep="\n  " if problems else " ")
    if len(problems) > 40:
        print(f"  ... and {len(problems) - 40} more")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
