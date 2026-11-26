#!/usr/bin/env python
"""
Make the 7-day MCS animation over the Sahel for the sources of the MCS resolution-sensitivity study: one panel with Tb,
precipitation, the outlines of the tracked MCSs, their tracks and numbers. The same map, colors and track style for every source.

What each source reads (config file, yearly track statistics, pixel-level files) and its pre-defined period are in
sahel_sources.yaml. The frames and the mp4 are made by PyFLEXTRKR (pyflextrkr/visualization/mcs_animation.py, the code of
PyFLEXTRKR-dev/visualization/plot_mcs_tracks.py).

Before plotting, every source is checked: the files exist, every hour of the period has a pixel-level file, and the track
numbers of the pixel files belong to the statistics file (sahel_common.check_pairing). A failed check stops the run.

Usage (compute node, PyFLEXTRKR environment /global/common/software/m1867/python/pyflex26.3):
    python make_mcs_animation_sahel.py --source all --workers 64
    python make_mcs_animation_sahel.py --source obs e3sm25
    python make_mcs_animation_sahel.py --source all --check-only                       # only the checks, nothing is written
    python make_mcs_animation_sahel.py --source obs --start 2010-08-01 --ndays 2       # another period
    python make_mcs_animation_sahel.py --source obs --playback-fps 6 --skip-plotting   # remake the mp4 from the frames

The look (rain levels and colors, MCS outlines, pixels without Tb) is `look` in sahel_sources.yaml; it needs the options
--var2_levels, --oob_color_l/h and --tb_nan_color of PyFLEXTRKR.

Output: <outdir>/<source>/frames/*.png and <outdir>/mcs_sahel_<source>_<first day>_<last day>.mp4
"""
import argparse
import os
import sys

import sahel_common as common_tools


def parse_args(argv=None, keys=()):
    """
    Command line.

    Args:
        argv: list of str (default: None = sys.argv[1:])
        keys: sequence of str
            Source keys of the source file (listed in the help text).

    Returns:
        args: argparse.Namespace
    """
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--source', nargs='+', required=True, help=f"source keys or 'all': {', '.join(keys)}")
    p.add_argument('--config', default=common_tools.DEFAULT_SOURCES, help='source file (default: %(default)s)')
    p.add_argument('--start', default=None, help='first day YYYY-MM-DD (default: the start of the source in the source file)')
    p.add_argument('--ndays', type=int, default=None, help='number of days (default: ndays of the source file)')
    p.add_argument('--outdir', default=None, help='output folder (default: outdir of the source file)')
    p.add_argument('--workers', type=int, default=64, help='Dask workers that plot the frames (default: %(default)s)')
    p.add_argument('--playback-fps', type=float, default=4,
                   help='frames (hours) per second of the movie; 4 plays 7 days in 42 s (default: %(default)s)')
    p.add_argument('--check-only', action='store_true', help='run the checks only')
    p.add_argument('--skip-plotting', action='store_true', help='make the mp4 from the PNG frames that exist')
    return p.parse_args(argv)


def prepare(key, source, common, args):
    """
    Paths, period and checks of one source.

    Args:
        key: str
            Source key.
        source: dict
            Settings of the source.
        common: dict
            Shared settings.
        args: argparse.Namespace
            Command line.

    Returns:
        job: dict
            key, paths, t0, t1, nframes.

    Raises:
        ValueError: no start day; a file or folder is missing; hours without a pixel file; the pairing check fails.
    """
    start = args.start or source.get('start')
    if start is None:
        raise ValueError(f'{key}: no start day (set `start` in the source file or use --start)')
    ndays = args.ndays or common['ndays']
    t0, t1 = common_tools.period_of(start, ndays)
    paths = common_tools.source_paths(source, t0.year)
    # The period must not run into another year: the yearly statistics and pixel folders hold one year
    if '{year}' in source['pixel_path'] and t1.year != t0.year:
        raise ValueError(f'{key}: the period {t0:%Y-%m-%d} to {t1:%Y-%m-%d} crosses a year boundary')
    for name, path in paths.items():
        if not os.path.exists(path):
            raise ValueError(f'{key}: {name} does not exist: {path}')

    # Every hour of the period needs a pixel-level file
    files, missing = common_tools.files_of_period(common_tools.index_pixel_files(paths['pixel_path']), t0, t1)
    if len(files) == 0 or len(missing) > 0:
        raise ValueError(f'{key}: {len(files)} pixel files in the period, {len(missing)} hours without a file'
                         + (f' (first: {missing[0]})' if len(missing) else ''))

    # The track numbers of the pixel files must belong to the statistics file
    pairing = common_tools.check_pairing(files, paths['trackstats_file'])
    print(f"{key:14s} {t0:%Y-%m-%d} to {t1:%Y-%m-%d}: {len(files)} frames; pairing check {'passed' if pairing['ok'] else 'FAILED'}: "
          f"{pairing['matched']}/{pairing['masks']} masks have a statistics time step, "
          f"median center offset {pairing['median_offset']:.2f} deg", flush=True)
    if not pairing['ok']:
        raise ValueError(f"{key}: the pixel files and the statistics file do not belong together: {paths['trackstats_file']}")
    return {'key': key, 'paths': paths, 't0': t0, 't1': t1, 'nframes': len(files)}


def animation_parameters(job, source, common, args):
    """
    Parameters of pyflextrkr.visualization.mcs_animation for one source (the same look for all sources, except where a source
    sets its own `look` in the source file).

    Args:
        job: dict
            Output of prepare.
        source: dict
            Settings of the source.
        common: dict
            Shared settings.
        args: argparse.Namespace
            Command line.

    Returns:
        params: dict
            Names of mcs_animation.DEFAULTS.
    """
    outdir = os.path.abspath(args.outdir or common['outdir'])
    box = common['map_box']
    # The chosen look (colors, rain levels, outlines): the shared settings, replaced by those of the source where it has its own
    look = {**common.get('look', {}), **source.get('look', {})}
    return dict(
        **look,
        # One map: Tb (gray), precipitation (color), MCS outlines, tracks and numbers
        plot_type='1panel', data_type='tbpf',
        start_date=job['t0'].strftime('%Y-%m-%dT%H:%M'), end_date=job['t1'].strftime('%Y-%m-%dT%H:%M'),
        # Map domain; subset=1 reads only the pixels of the box
        lon_min=box['lon_min'], lon_max=box['lon_max'], lat_min=box['lat_min'], lat_max=box['lat_max'], subset=1,
        config_file=job['paths']['config_file'], trackstats_file=job['paths']['trackstats_file'], pixel_path=job['paths']['pixel_path'],
        # Tracks that started up to this many days before the period are drawn
        track_lookback_days=7,
        parallel_mode=1, n_workers=args.workers,
        figsize_x=14, dpi=140, fontsize=12, title_prefix=source['title'],
        draw_border=True, map_resolution='50m',
        # White halo around paths, symbols and numbers (the style of the PyFLEXTRKR Sahel demo animation)
        track_halo_color='white', track_halo_alpha=0.7, track_text_alpha=0.8,
        # mp4 settings
        playback_fps=args.playback_fps, video_quality=24, output_width=1920,
        run_plotting=not args.skip_plotting, run_ffmpeg=True,
        figdir=f"{outdir}/{job['key']}/frames/", animation_dir=f'{outdir}/', fig_basename=f"mcs_sahel_{job['key']}_",
    )


def main(argv=None):
    """
    Check all requested sources first, then make their animations one after the other.

    Args:
        argv: list of str (default: None = sys.argv[1:])
    """
    # The source keys go into the help text, so the source file is read before the arguments are parsed
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument('--config', default=common_tools.DEFAULT_SOURCES)
    known, _ = pre.parse_known_args(argv)
    common, sources = common_tools.load_sources(known.config)
    args = parse_args(argv, list(sources))

    keys = list(sources) if args.source == ['all'] else args.source
    unknown = [k for k in keys if k not in sources]
    if unknown:
        sys.exit(f"ERROR: unknown source(s) {', '.join(unknown)}; choose from {', '.join(sources)}")
    if args.start is not None and len(keys) > 1:
        sys.exit('ERROR: --start sets one period; give one source with it')

    # Check every source before the first (long) plotting run
    try:
        jobs = [prepare(key, sources[key], common, args) for key in keys]
    except ValueError as err:
        sys.exit(f'ERROR: {err}')
    if args.check_only:
        return

    from pyflextrkr.visualization.mcs_animation import main as make_animation

    # Loop over the sources: plot the frames and make the mp4 (argv=[]: the --set options of the PyFLEXTRKR wrappers are not used)
    for job in jobs:
        print(f"\n########## {job['key']}", flush=True)
        make_animation(animation_parameters(job, sources[job['key']], common, args), argv=[])


# The Dask workers import this file: the work is under __main__
if __name__ == '__main__':
    main()
