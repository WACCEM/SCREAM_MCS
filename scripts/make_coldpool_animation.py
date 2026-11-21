#!/usr/bin/env python
"""
Make cold pool snapshot animations (SCREAM cold pool anomaly + reflectivity + cell tracks + 10 m winds)
- Call the plotting script plot_subset_cell_coldpool_snapshots.py to generate the PNG files
- Create a video animation of every layout using FFmpeg

The settings of the picture (domain, projection, levels, vector spacing, ...) and, by default, the time range and the
layout are the "case" of coldpool_cases.yaml. Any month of the cell tracking run works; no config file is needed per case.
`extra_args` below passes any other option of the plotting script (e.g. --set style.vector_spacing_km=45).

Order of precedence of case, start_date, end_date and layout (first one that is set wins):
  command line  >  the variable at the top of this file (None = not set)  >  the case in coldpool_cases.yaml

Usage:
  python make_coldpool_animation.py --case line_mcs_20200711                  range and layout of the case
  python make_coldpool_animation.py --case se_us_20200520 -s 2020-05-20T12:00 -e 2020-05-20T13:00 --layout both
  python make_coldpool_animation.py                                         the variables below

Layouts (the layout is part of the file names, so that the two animations do not overwrite each other):
  single  one panel: cold pool shading, reflectivity, cell perimeters and tracks, wind vectors
  two     left: reflectivity + cells; right: cold pool + wind vectors + surface rain rate contours
  both    both layouts of every time: two PNG series, two animations

Names:  PNG   {figdir}{fig_basename}{layout}_YYYYMMDD_HHMMSS.png
        MP4   {animation_dir}{fig_basename}{layout}_{start_date YYYY-MM-DDTHH}_{end_date YYYY-MM-DDTHH}.mp4

Run from any folder: the plotting script is taken from the folder of this file.

Author: Zhe Feng | zhe.feng@pnnl.gov
"""

import os
import sys
import math
import glob
import subprocess
import tempfile
import argparse
import pandas as pd

###############################################################################################
# Script parameters
###############################################################################################

# Case of coldpool_cases.yaml (map domain, projection, levels, ..., and the default time range and layout);
# None = the built-in values (whole grid; then the time range must be given). Command line: --case NAME
case = 'ar_20200602'
case_file = None             # None = coldpool_cases.yaml next to the plotting script

# Time range 'YYYY-mm-ddTHH:MM' (the PNG files and the animation cover the times inside it that have both input files).
# None = start_date / end_date of the case. Command line: -s / --start, -e / --end
start_date = None
end_date = None
# Layout: 'single', 'two' or 'both' (two PNG series and two animations, named with the layout).
# None = the layout of the case. Command line: --layout
layout = None
# Any other options of plot_subset_cell_coldpool_snapshots.py, one list item per argument (not the layout, case or
# times: those have their own variables and command line options above), e.g.
# extra_args = ['--set', 'style.vector_spacing_km=45', '--set', 'options.bkg_radius_km=50', '--dbz_min', '20']
extra_args = []

# Inputs (None = the defaults of the plotting script)
config_file = None           # cell tracking yaml config file (the pixel-level and statistics files of the month)
data2d_path = None           # SCREAM 2D files (ps, T_2m, qv_2m, U/V 10 m, precipitation)

# Execution parameters
parallel_mode = 1
n_workers = 64
batch_size = None            # Frames per batch of the parallel plotting (None = 4 x n_workers)

# Own plotting function instead of the built-in layouts (file with a function of the signature of plot_frame, see the
# plotting script header); None = the built-in layouts
plot_module = None
plot_func = 'plot_frame'

# Output directories
figdir = "/global/cfs/cdirs/m1867/zfeng/E3SM/SCREAMv1/cess2/CONUS/figures/ColdPool/frames/"
animation_dir = "/global/cfs/cdirs/m1867/zfeng/E3SM/SCREAMv1/cess2/CONUS/figures/ColdPool/animations/"
# Base name of the PNG and animation files (None = {case}_ or coldpool_ without a case)
fig_basename = None

# Execution control options
run_plotting = True    # Set to False to skip plotting and use existing PNG files
run_ffmpeg = True      # Set to False to skip animation creation (plotting only)

# FFmpeg animation parameters (same as make_celltrack_animation.py)
playback_fps = 6       # PNGs shown per second = the playback speed of the animation (larger = faster)
frame_stride = 1       # use every Nth PNG (2 = every second PNG): the other way to shorten a long period
video_fps = None       # frame rate of the video file. None = automatic: playback_fps repeated to at least 10 fps with a whole
                       # number of repeats per PNG. It does not change the speed; players handle very low frame rates badly,
                       # so every PNG is repeated. Keep it a whole multiple of playback_fps (below it, PNGs are dropped)
video_quality = 24     # CRF value of libx264 (lower = better quality and larger file, range 0-51; 18-28 is the useful range).
                       # +6 CRF is about half the file size; 24 looks the same as 20 for thin lines and markers.
output_width = 1920    # Maximum output video width in pixels (height follows the aspect ratio). A PNG that is narrower is
                       # NOT enlarged (the single panel is 1650 px wide, the two-panel layout 2557 px). None = original size.
video_preset = 'slow'  # x264 speed / compression trade-off: ultrafast ... veryfast, faster, fast, medium (x264 default), slow,
                       # slower, veryslow. To turn off: 'medium', or None (no -preset option).

###############################################################################################
# Main execution
###############################################################################################

script_dir = os.path.dirname(os.path.abspath(__file__))
plot_script = os.path.join(script_dir, 'plot_subset_cell_coldpool_snapshots.py')

# Command line (all optional)
parser = argparse.ArgumentParser(description="Make cold pool snapshot PNG files and one mp4 per layout. Every option "
                                 "that is not given comes from the variables at the top of the file, then from the case.")
parser.add_argument('-s', '--start', default=None, help="first time YYYY-mm-ddTHH:MM (default: start_date, then the case)")
parser.add_argument('-e', '--end', default=None, help="last time YYYY-mm-ddTHH:MM (default: end_date, then the case)")
parser.add_argument('--case', default=None, help="case of coldpool_cases.yaml (default: case above)")
parser.add_argument('--layout', default=None, choices=['single', 'two', 'both'],
                    help="layout (default: layout above, then the case)")
cli = parser.parse_args()

# Case settings: the same function (and file) as the plotting script and the notebook use
sys.path.insert(0, script_dir)
import coldpool_snapshot_lib as cl

if cli.case is not None:
    case = cli.case
try:
    case_cfg = cl.load_case(case_file if case_file is not None else cl.DEFAULT_CASE_FILE, case)
except (ValueError, KeyError, FileNotFoundError) as e:
    sys.exit(f"ERROR: {e}")


def resolve(cli_value, var_value, case_value):
    """First value that is set: command line, variable of this file, case. Returns (value, where it came from)."""
    for source, value in (('command line', cli_value), ('variable in this file', var_value),
                          (f"case {case}" if case else 'built-in default', case_value)):
        if value is not None:
            return value, source
    return None, 'not set'


(start_date, src_start) = resolve(cli.start, start_date, case_cfg['start_date'])
(end_date, src_end) = resolve(cli.end, end_date, case_cfg['end_date'])
(layout, src_layout) = resolve(cli.layout, layout, case_cfg['options']['layout'])
if start_date is None or end_date is None:
    sys.exit("ERROR: no time range: use -s / -e, set start_date / end_date in this file, or use a case that has them "
             f"(case: {case})")
start_date, end_date = cl.norm_time(start_date), cl.norm_time(end_date)

layouts = ['single', 'two'] if layout == 'both' else [layout]
if any(lay not in ('single', 'two') for lay in layouts):
    sys.exit(f"layout must be 'single', 'two' or 'both', not '{layout}'")
if fig_basename is None:
    fig_basename = f"{case}_" if case else "coldpool_"
if not figdir.endswith('/'):
    figdir += '/'
if not animation_dir.endswith('/'):
    animation_dir += '/'

start_date_str = start_date[:13]  # YYYY-MM-DDTHH
end_date_str = end_date[:13]

print("Make cold pool snapshot animation")
print(f"Plotting script: {plot_script}")
print(f"Case: {case}   layouts: {', '.join(layouts)}  (layout from {src_layout})")
print(f"Date range: {start_date} to {end_date}  (start from {src_start}, end from {src_end})")
print(f"PNG files: {figdir}{fig_basename}<layout>_YYYYMMDD_HHMMSS.png")
print(f"Animations: {animation_dir}{fig_basename}<layout>_{start_date_str}_{end_date_str}.mp4")
print(f"Execution mode: Plotting={'✅' if run_plotting else '❌'}, FFmpeg={'✅' if run_ffmpeg else '❌'}")

if run_ffmpeg:
    os.makedirs(animation_dir, exist_ok=True)
if run_plotting:
    os.makedirs(figdir, exist_ok=True)

#########################################################
# Run plotting script
#########################################################
if run_plotting:
    print(f"📊 Running plotting script with {n_workers} workers...")
    cmd = [
        sys.executable, plot_script,
        '--start', start_date,
        '--end', end_date,
        '--layout', layout,
        '--parallel', str(parallel_mode),
        '--workers', str(n_workers),
        '--output', figdir,
        '--figbasename', fig_basename,
    ]
    if case is not None:
        cmd.extend(['--case', case])
    if case_file is not None:
        cmd.extend(['--case_file', case_file])
    if config_file is not None:
        cmd.extend(['--config', config_file])
    if data2d_path is not None:
        cmd.extend(['--data2d_path', data2d_path])
    if batch_size is not None:
        cmd.extend(['--batch_size', str(batch_size)])
    if plot_module is not None:
        cmd.extend(['--plot_module', plot_module, '--plot_func', plot_func])
    cmd.extend([str(a) for a in extra_args])

    print(f"Command: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"❌ Error: Plotting script failed with exit code {result.returncode}")
        sys.exit(1)
    print("✅ Plotting completed successfully!")
else:
    print("⏭️  Skipping plotting - using existing PNG files")

#########################################################
# Make the animations using ffmpeg: one per layout
#########################################################
if not run_ffmpeg:
    print("⏭️  Skipping animation creation - PNG files ready for manual processing")
    sys.exit(0)

start_dt = pd.to_datetime(start_date)
end_dt = pd.to_datetime(end_date)

# Width filter: shrink to output_width, never enlarge; both dimensions even (required by yuv420p)
if output_width is not None:
    vf_scale = f"scale='min({int(output_width) // 2 * 2},trunc(iw/2)*2)':-2"
else:
    vf_scale = 'scale=trunc(iw/2)*2:trunc(ih/2)*2'

# Frame rate of the video file: every PNG is repeated a whole number of times (the speed is set by playback_fps only)
video_fps_used = video_fps if video_fps is not None else playback_fps * max(1, math.ceil(10 / playback_fps))

n_made = 0
for lay in layouts:
    prefix = f"{fig_basename}{lay}_"
    animation_filename = f"{animation_dir}{prefix}{start_date_str}_{end_date_str}.mp4"
    print(f"🎬 Creating the animation of layout '{lay}' from PNG files...")

    # PNG files of this layout inside the date range (time from the file name)
    expected_files = []
    for png_file in sorted(glob.glob(f'{figdir}{prefix}*.png')):
        try:
            file_dt = pd.to_datetime(os.path.basename(png_file)[len(prefix):len(prefix) + 15], format='%Y%m%d_%H%M%S')
        except (ValueError, IndexError):
            continue   # a name that does not end in YYYYMMDD_HHMMSS (another case / layout that starts the same way)
        if start_dt <= file_dt <= end_dt:
            expected_files.append(png_file)

    print(f"Found {len(expected_files)} PNG files within date range {start_date} to {end_date}")
    if len(expected_files) == 0:
        print(f"❌ No PNG files of layout '{lay}' found within the specified date range!")
        print(f"   Check directory: {figdir}")
        print(f"   Expected pattern: {prefix}YYYYMMDD_HHMMSS.png")
        continue

    # Every frame_stride-th PNG
    if frame_stride > 1:
        expected_files = expected_files[::frame_stride]
        print(f"Using every {frame_stride}th PNG: {len(expected_files)} files")

    # Temporary file list for FFmpeg
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        temp_filelist = f.name
        for png_file in expected_files:
            f.write(f"file '{png_file}'\n")

    try:
        # FFmpeg concat demuxer with file list; -r before -i sets the playback speed (PNGs per second)
        ffmpeg_cmd = [
            'ffmpeg',
            '-f', 'concat',
            '-safe', '0',
            '-r', str(playback_fps),
            '-i', temp_filelist,
            '-vf', vf_scale,
            '-c:v', 'libx264',
            '-r', str(video_fps_used),  # frame rate of the video file (PNGs are repeated to reach it)
            '-crf', str(video_quality),
            '-pix_fmt', 'yuv420p',
        ]
        if video_preset is not None:
            ffmpeg_cmd.extend(['-preset', str(video_preset)])
        ffmpeg_cmd.extend(['-y', animation_filename])

        print("🎬 Animation settings:")
        print(f"   Playback: {playback_fps} PNGs per second (speed), every {frame_stride}th PNG, "
              f"video file {video_fps_used:g} fps (each PNG repeated {video_fps_used / playback_fps:g} times)")
        print(f"   Duration: {len(expected_files) / playback_fps:.0f} s")
        print(f"   Video quality (CRF): {video_quality} (lower=better), x264 preset {video_preset}")
        print(f"   Output width: at most {output_width if output_width else 'original'} pixels (never enlarged)")
        print(f"FFmpeg command: {' '.join(ffmpeg_cmd)}")
        print(f"Using {len(expected_files)} PNG files from {expected_files[0]} to {expected_files[-1]}")

        result = subprocess.run(ffmpeg_cmd)
    finally:
        os.unlink(temp_filelist)

    if result.returncode == 0:
        n_made += 1
        print(f"✅ Animation created successfully!")
        print(f"🎬 View animation here: {animation_filename}")
    else:
        print(f"❌ Error: FFmpeg failed with exit code {result.returncode}")

if n_made == 0:
    sys.exit(1)
