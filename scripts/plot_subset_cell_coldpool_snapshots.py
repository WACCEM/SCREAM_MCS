#!/usr/bin/env python
"""
Plot snapshots of the SCREAM cold pool (2 m virtual potential temperature anomaly), low-level reflectivity, cell
tracks and 10 m winds for a range of times, e.g. as the frames of an animation.

Two layouts (--layout, or "layout" of a case):
  single  one panel: cold pool anomaly (shading), low-level reflectivity, cell perimeters and tracks, 10 m wind vectors
  two     left: low-level reflectivity, cell perimeters and tracks; right: cold pool anomaly, 10 m wind vectors and
          contours of the surface rain rate (default > 10 mm/h, red)
  both    both files of every time

The functions are in coldpool_snapshot_lib.py, the same file that the notebook
Notebooks/tests/test_plot_coldpool_snapshots_scream.ipynb imports (no copy to keep in step). The settings of a case
(domain, map center, levels, vector spacing, ...) are in coldpool_cases.yaml, see the header of that file.

Inputs: the cell tracking pixel-level files and track statistics of the month (-c config), and the SCREAM 2D surface
files remapped to the same grid (--data2d_path): ps, T_2m, qv_2m, U_at_10m_above_surface, V_at_10m_above_surface,
precip_total_surf_mass_flux. Only times that have both files are plotted.

Usage:
>python plot_subset_cell_coldpool_snapshots.py -s 2020-05-20T12:00 -e 2020-05-20T15:00 --case se_us_20200520 \\
      -p 1 --workers 16 --output /path/to/figures/
>python plot_subset_cell_coldpool_snapshots.py --case se_us_20200520 -p 1 --output /path/to/figures/   (range of the case)
>python plot_subset_cell_coldpool_snapshots.py --case se_us_20200520 --show_case
>python plot_subset_cell_coldpool_snapshots.py -s 2020-05-20T12:00 -e 2020-05-20T15:00 --list_times

Time range:
-s, --start / -e, --end   First / last time (YYYY-mm-ddTHH:MM[:SS]). Default: start_date / end_date of the case; a time
                          range from one of the two is required (the files of a time are found from its month, any month works)

Settings of a case (command line options win over the case file, the case file over the built-in values):
--case_file FILE          YAML file of the cases (default coldpool_cases.yaml next to this script)
--case NAME               Case of the file
--set BLOCK.KEY=VALUE     Any key of the file: --set style.cp_levels="[-4,-3,-2,-1]" --set map.central_longitude=-90
                          (BLOCK is style, map or options; VALUE is YAML; can be given several times)
--show_case               Print the settings in force and exit
--layout single|two|both, --extent lonmin lonmax latmin latmax, --projection, --central_longitude (number or auto),
--central_latitude, --standard_parallels, --bkg_radius_km, --land_ocean_separate 0|1, --dbz_var, --lookback_hours,
--cp_levels, --dbz_min, --dbz_alpha, --rain_levels, --vector_spacing_km, --vector_scale, --figsize_x, --dpi,
--show_cell_numbers 0|1, --show_symbols 0|1     (the same keys as in the "map", "options" and "style" blocks)

Other arguments:
-c, --config              Cell tracking YAML config: only the root path, file base names and grid spacing are used, which
                          are the same in every monthly config, so it does not have to match the month of the times
--data2d_path, --data2d_base   Directory and file name base of the 2D files
-p, --parallel            0 serial, 1 parallel with a Dask LocalCluster (batched, see plot_batches.py)
--workers, --batch_size   Workers (default: nprocesses of the config) and frames per batch (default 4 x workers)
--output, --figbasename   Output directory and figure base name (default {case}_ or coldpool_);
                          files are {figbasename}{layout}_{YYYYMMDD_HHMMSS}.png
--plot_module FILE --plot_func NAME   Use your own plotting function instead of the built-in layouts, without editing
                          anything: a Python file with  def NAME(frame, track_dict, style, map_info) -> figure
                          (default NAME plot_frame). frame, track_dict, style and map_info are what the notebook and
                          coldpool_snapshot_lib.py build; the file can use  import coldpool_snapshot_lib as cl  and the
                          draw_* helpers. This is for trying a function; make a change that should stay in
                          coldpool_snapshot_lib.py itself.
--list_times              Print the times that have all inputs and the files without a partner; no plotting
"""
__author__ = "Zhe.Feng@pnnl.gov"

import argparse
import importlib.util
import os
import sys
import numpy as np
import pandas as pd
import yaml
import matplotlib.pyplot as plt

import coldpool_snapshot_lib as cl
import plot_batches


def parse_cmd_args():
    p = argparse.ArgumentParser(description="Plot SCREAM cold pool + low-level reflectivity + cell tracks + wind snapshots.",
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-s", "--start", default=None, help="first time, YYYY-mm-ddTHH:MM[:SS] (default: start_date of the case)")
    p.add_argument("-e", "--end", default=None, help="last time, YYYY-mm-ddTHH:MM[:SS] (default: end_date of the case)")
    p.add_argument("-c", "--config", default=cl.CONFIG_FILE,
                   help="cell tracking yaml config file (root path, file names, dx; any month of the run)")
    p.add_argument("--data2d_path", default=cl.DIR_2D, help="directory of the SCREAM 2D files")
    p.add_argument("--data2d_base", default=cl.BASE_2D, help="file name base of the SCREAM 2D files")
    p.add_argument("--case_file", default=cl.DEFAULT_CASE_FILE, help="yaml file of the cases")
    p.add_argument("--case", default=None, help="case of the case file")
    p.add_argument("--set", action="append", default=[], metavar="BLOCK.KEY=VALUE", help="override a key of a case (yaml value)")
    p.add_argument("--show_case", action="store_true", help="print the settings in force and exit")
    # map
    p.add_argument("--extent", nargs=4, type=float, default=None, help="lonmin lonmax latmin latmax")
    p.add_argument("--projection", default=None)
    p.add_argument("--central_longitude", default=None, help="number or auto")
    p.add_argument("--central_latitude", default=None, help="number or auto")
    p.add_argument("--standard_parallels", nargs="+", default=None, help="numbers or auto")
    # options
    p.add_argument("--layout", default=None, choices=["single", "two", "both"])
    p.add_argument("--bkg_radius_km", type=float, default=None)
    p.add_argument("--land_ocean_separate", type=int, default=None)
    p.add_argument("--dbz_var", default=None)
    p.add_argument("--lookback_hours", type=float, default=None)
    # style
    p.add_argument("--cp_levels", nargs="+", type=float, default=None)
    p.add_argument("--dbz_min", type=float, default=None)
    p.add_argument("--dbz_alpha", type=float, default=None)
    p.add_argument("--rain_levels", nargs="+", type=float, default=None)
    p.add_argument("--vector_spacing_km", type=float, default=None)
    p.add_argument("--vector_scale", type=float, default=None)
    p.add_argument("--figsize_x", type=float, default=None)
    p.add_argument("--dpi", type=int, default=None)
    p.add_argument("--show_cell_numbers", type=int, default=None)
    p.add_argument("--show_symbols", type=int, default=None)
    # run
    p.add_argument("-p", "--parallel", type=int, default=0, help="0 serial, 1 parallel")
    p.add_argument("--workers", type=int, default=None)
    p.add_argument("--batch_size", type=int, default=None)
    p.add_argument("--output", default="./")
    p.add_argument("--figbasename", default=None)
    p.add_argument("--plot_module", default=None)
    p.add_argument("--plot_func", default="plot_frame")
    p.add_argument("--list_times", action="store_true")
    return p.parse_args()


def number_or_auto(v):
    return v if v is None or v == 'auto' else float(v)


def cli_overrides(args):
    """The values given on the command line, in the blocks of a case file."""
    cli = {'style': {}, 'map': {}, 'options': {}, 'start_date': None, 'end_date': None}
    given = lambda v: v is not None
    if given(args.start):
        cli['start_date'] = args.start
    if given(args.end):
        cli['end_date'] = args.end
    if given(args.extent):
        cli['map']['extent'] = list(args.extent)
    if given(args.projection):
        cli['map']['projection'] = args.projection
    if given(args.central_longitude):
        cli['map']['central_longitude'] = number_or_auto(args.central_longitude)
    if given(args.central_latitude):
        cli['map']['central_latitude'] = number_or_auto(args.central_latitude)
    if given(args.standard_parallels):
        cli['map']['standard_parallels'] = 'auto' if args.standard_parallels == ['auto'] \
            else [float(v) for v in args.standard_parallels]
    for k in ('layout', 'bkg_radius_km', 'dbz_var', 'lookback_hours'):
        if given(getattr(args, k)):
            cli['options'][k] = getattr(args, k)
    if given(args.land_ocean_separate):
        cli['options']['land_ocean_separate'] = bool(args.land_ocean_separate)
    for k in ('cp_levels', 'dbz_min', 'dbz_alpha', 'rain_levels', 'vector_spacing_km', 'vector_scale', 'figsize_x', 'dpi'):
        if given(getattr(args, k)):
            cli['style'][k] = getattr(args, k)
    for k in ('show_cell_numbers', 'show_symbols'):
        if given(getattr(args, k)):
            cli['style'][k] = bool(getattr(args, k))
    if cli['style'].get('cp_levels') is not None:
        cli['style']['cp_levels'] = sorted(cli['style']['cp_levels'])
    # --set BLOCK.KEY=VALUE (yaml values) win over the options above
    for item in args.set:
        key, eq, value = item.partition('=')
        block, dot, name = key.partition('.')
        if block not in ('style', 'map', 'options') or not dot or not name or not eq:
            sys.exit(f"--set {item}: use BLOCK.KEY=VALUE with BLOCK style, map or options")
        cli[block][name] = yaml.safe_load(value)
    return cli


_PLOT_FUNC = {}


def get_plot_function(path, name):
    """Plotting function of a user file (loaded once per process)."""
    key = (path, name)
    if key not in _PLOT_FUNC:
        spec = importlib.util.spec_from_file_location("user_plot_module", path)
        mod = importlib.util.module_from_spec(spec)
        sys.path.insert(0, os.path.dirname(os.path.abspath(path)))
        spec.loader.exec_module(mod)
        _PLOT_FUNC[key] = getattr(mod, name)
    return _PLOT_FUNC[key]


def work_for_time_loop(pixel_f, f2d, tstr, track_dict=None, map_info=None, style=None, opts=None):
    """Read one time, make the figure(s) of the layout(s) and save them. Returns 1."""
    cl.init_paths(opts['config'], opts['data2d_path'], opts['data2d_base'])    # the workers start with the defaults
    t = pd.Timestamp(tstr)
    o = opts['options']
    frame = cl.load_frame(t, opts['extent'], radius_km=o['bkg_radius_km'], buffer_deg=o['buffer_deg'],
                          dbz_var=o['dbz_var'], land_ocean_separate=bool(o['land_ocean_separate']))
    tag = f"{t:%Y%m%d_%H%M%S}"
    if opts['plot_module'] is not None:
        funcs = {'custom': get_plot_function(opts['plot_module'], opts['plot_func'])}
    else:
        funcs = {}
        if o['layout'] in ('single', 'both'):
            funcs['single'] = cl.plot_single_panel
        if o['layout'] in ('two', 'both'):
            funcs['two'] = cl.plot_two_panel
    for name, func in funcs.items():
        fig = func(frame, track_dict, style, map_info)
        figname = f"{opts['figdir']}{opts['figbasename']}{name}_{tag}.png"
        fig.savefig(figname, facecolor='w')
        plt.close(fig)
        print(figname, flush=True)
    return 1


if __name__ == "__main__":
    args = parse_cmd_args()
    cl.init_paths(args.config, args.data2d_path, args.data2d_base)

    # Settings of the case: built-in < case file < command line
    try:
        case = cl.load_case(args.case_file, args.case, cli_overrides(args))
    except (ValueError, KeyError, FileNotFoundError) as e:
        sys.exit(f"ERROR: {e}")
    if args.show_case:
        cl.show_case(case)
        sys.exit(0)
    # Time range: command line > start_date / end_date of the case
    if case['start_date'] is None or case['end_date'] is None:
        sys.exit("ERROR: no time range: give -s/--start and -e/--end, or a --case with start_date and end_date")
    style, options, map_kw = case['style'], case['options'], case['map']

    start, end = pd.Timestamp(case['start_date']), pd.Timestamp(case['end_date'])
    print(f"Time range {start} to {end}" + (f" (case {args.case})" if args.start is None and args.end is None else ""))
    times, only_pixel, only_2d = cl.available_times(start, end)
    print(f"{len(times)} times with the cell tracking file and the 2D file between {start} and {end}")
    if only_pixel or only_2d:
        print(f"  without partner: {len(only_pixel)} times with only a pixel file, {len(only_2d)} with only a 2D file (skipped)")
    if args.list_times:
        for t in times:
            print(f"  {t}")
        for t in only_pixel:
            print(f"  {t}  only pixel file")
        for t in only_2d:
            print(f"  {t}  only 2D file")
        sys.exit(0)
    if len(times) == 0:
        sys.exit("No time has all input files.")

    # Map: the same in all frames (projection, axes limits and, with them, the figure size)
    map_info = cl.make_map_info(**map_kw)
    print(f"Map extent {map_info['extent']}, projection {map_info['projection']} centered at "
          f"{map_info['central_longitude']:.1f} E, {map_info['central_latitude']:.1f} N, aspect {map_info['aspect_yx']:.3f}")

    figdir = args.output if args.output.endswith('/') else args.output + '/'
    os.makedirs(figdir, exist_ok=True)
    figbasename = args.figbasename if args.figbasename is not None else (f"{args.case}_" if args.case else 'coldpool_')
    opts = {'extent': map_kw['extent'], 'options': options, 'figdir': figdir, 'figbasename': figbasename,
            'plot_module': args.plot_module, 'plot_func': args.plot_func,
            'config': args.config, 'data2d_path': args.data2d_path, 'data2d_base': args.data2d_base}

    # The months of the frames: the cell tracks of a month come from the statistics file of that month
    months = sorted({cl.month_period(t) for t in times})
    n_failed_total = 0
    n_workers = args.workers if args.workers is not None else cl.config['nprocesses']
    cluster = client = None
    if args.parallel == 1:
        cluster, client = plot_batches.make_cluster(n_workers, cl.config.get("dask_tmp_dir", "./"))
    for month in months:
        tm = [t for t in times if cl.month_period(t) == month]
        track_dict = cl.load_tracks(tm[0], tm[-1], options['lookback_hours'])
        items = [(cl.pixel_file(t), cl.file_2d(t), t.strftime('%Y-%m-%dT%H:%M:%S')) for t in tm]
        if args.parallel == 0:
            for it in items:
                work_for_time_loop(*it, track_dict=track_dict, map_info=map_info, style=style, opts=opts)
                plot_batches.release_memory()
        elif args.parallel == 1:
            batch_size = args.batch_size or plot_batches.default_batch_size(n_workers)
            ftimes = plot_batches.frame_times([t.timestamp() for t in tm])
            failed = plot_batches.run_in_batches(
                client, work_for_time_loop, items=items, times=ftimes,
                subset_fn=lambda t0, t1: {'track_dict': plot_batches.subset_track_dict(track_dict, t0, t1)},
                batch_size=batch_size, common={'map_info': map_info, 'style': style, 'opts': opts})
            n_failed_total += len(failed)
        else:
            sys.exit('Valid parallelization flag not provided')
    if client is not None:
        client.close()
        cluster.close()
    if n_failed_total > 0.05 * len(times):
        sys.exit(f'{n_failed_total} of {len(times)} frames failed')
