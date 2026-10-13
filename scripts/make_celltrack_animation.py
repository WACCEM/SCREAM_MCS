#!/usr/bin/env python
"""
Make cell tracking animation (SCREAM simulated cell tracks, whole CONUS)
- Call plotting script to generate PNG files
- Create a video animation using FFmpeg

The map is the HRRR Lambert Conformal projection of the whole pixel-level domain (set lon_min ... lat_max
to zoom in; the radar / city / NEXRAD options below are for a regional subset). Run from this folder: the
plotting script plot_subset_cell_tracks_terrain.py (and plot_batches.py) are taken from "./".

Author: Zhe Feng | zhe.feng@pnnl.gov
"""

import os
import math
import glob
import subprocess
import pandas as pd
import tempfile

###############################################################################################
# Script parameters
###############################################################################################

# Script parameters
# SCREAM
start_date = "2020-07-01T00:00"
end_date = "2020-07-01T23:59"
# MRMS
# start_date = "2025-05-02T00:00"
# end_date = "2025-05-04T00:00"

# Radar location (optional - if not provided, defaults to domain center; only used for range circles)
radar_lat = None
radar_lon = None
# BNF site
# radar_lat = 34.723
# radar_lon = 273.428
# Phoenix
# radar_lat = 33.4484
# radar_lon = 247.926

# Map projection. HRRR's own Lambert Conformal (the pixel-level grid is a rectangle in it); optional
# parameters set to None are the cartopy defaults of the projection (-96, 39, (33, 45) for Lambert Conformal)
projection = 'LambertConformal'
central_longitude = -97.5
central_latitude = 38.5
standard_parallels = [38.5]   # one or two values, None = default

# Define domain map extent [degree] (all None = the whole pixel-level domain, full CONUS)
lon_min = None
lon_max = None
lat_min = None
lat_max = None
# Southeast US region
# lon_min = radar_lon - 6.0
# lon_max = radar_lon + 6.0
# lat_min = radar_lat - 4
# lat_max = radar_lat + 4
# Phoenix region
# lon_min = radar_lon - 4.0
# lon_max = radar_lon + 4.0
# lat_min = radar_lat - 2.5
# lat_max = radar_lat + 2.5

# Get start year from start_date
start_year = str(start_date.split('-')[0])

# Tracking config file
# SCREAM
config_file = "/global/homes/f/feng045/program/scream/tracking/config_celltracking_3km_SCREAMv1-Cess2_CONUS_07.yaml"
# MRMS
# config_file = "/global/homes/f/feng045/program/scream/tracking/jobs/config_celltracking_3km_MRMS_202505.yaml"

# Execution parameters
parallel_mode = 1
n_workers = 64
batch_size = None  # Frames per batch of the parallel plotting (None = 4 x n_workers); every batch gets only the tracks of its time window
figsize_x = 10  # Width in inches (height is auto-calculated to maintain aspect ratio)

# Tracking pixel-level file time format
time_format = 'yyyymodd_hhmmss'

# Variable name for plotting in pixel files
varname = 'dbz_comp'

# Title prefix for plots (added before date/time, can be an empty string)
title_prefix = 'SCREAM Cess2'
# title_prefix = 'MRMS'

# Control features to draw
draw_land = True  # Draw land features
draw_border = True  # Draw country borders
draw_state = True    # Draw state/province borders
show_rangecircle = False  # Draw radar range circles
show_azimuth = False      # Draw azimuth lines
show_tracks = True        # Show tracks
show_paths = True         # Show track path lines (None = auto from show_tracks)
show_symbols = False       # Show track centroid symbols (None = auto from show_tracks)
show_city = False        # Overplot city locations as filled diamonds (the list in the plotting script is Phoenix / Tucson)
show_nexrad = False       # Overplot NEXRAD locations as filled circles (the list in the plotting script is the Phoenix area)
nexrad_radius = 150       # NEXRAD range circle radius in km (0 = no circle)
show_cell_numbers = False # Write the cell track numbers on the map (unreadable on a whole-CONUS map)
# Cell style (None = the default of the plotting script, the picture of earlier versions)
show_cell_outline = True    # Draw the cell perimeters
cell_color = None           # Perimeter color (default black), e.g. 'white'
cell_perim_alpha = None     # Perimeter transparency (default 0.6)
cell_perim_width = 1        # Perimeter width in grid cells
cell_halo = None            # Color of a 1-cell ring just outside the perimeters, e.g. 'k' around white perimeters
cell_perim_cmap = None      # Colormap name (colorcet or matplotlib) for one perimeter color per track, e.g. 'glasbey_dark'
cell_track_color = None     # Track path color (default black)
cell_track_lw = 0.5        # Track path line width [points] (default 1)
cell_track_ls = '-'         # Track path line style, e.g. '--', ':'
cell_min_hours = 0.0        # Draw only cells of tracks that live at least this long [hour] (0 = all)
grid_linewidth = 0.5        # Line width of the lat/lon gridlines (0 = only the labels)
grid_linestyle = ':'        # Gridline style, e.g. ':'
grid_alpha = 0.5            # Gridline transparency
show_terrain = True         # Draw the terrain background
# Font sizes
fontsize = 13              # Main font size for labels and text
fontsize_tracks = 6        # Font size for track numbers (None = auto-calculate as fontsize*0.8)
# Map resolution for Natural Earth features (Cartopy options: '10m', '50m', '110m')
# '10m' = highest detail (slowest), '50m' = medium detail, '110m' = lowest detail (fastest)
map_resolution = '50m'
# Figure parameters
subset = 1  # Subset data before plotting (0:no, 1:yes)
fig_basename = "cell_tracks_"

# Output directories
# SCREAM
figdir = "/global/cfs/cdirs/m1657/zfeng/SCREAMv1-cess2/cell_conus/quicklooks_conus/"
animation_dir = "/global/cfs/cdirs/m1657/zfeng/SCREAMv1-cess2/cell_conus/animations_conus/"
# MRMS
# figdir = "/global/cfs/cdirs/m1657/zfeng/MRMS/cell_conus/quicklooks/"
# animation_dir = "/global/cfs/cdirs/m1657/zfeng/MRMS/cell_conus/animations/"

# Execution control options
run_plotting = False   # Set to False to skip plotting and use existing PNG files
run_ffmpeg = True     # Set to False to skip animation creation (plotting only)

# FFmpeg animation parameters
playback_fps = 12       # PNGs shown per second = the playback speed of the animation (larger = faster)
frame_stride = 1       # use every Nth PNG (2 = every second PNG): the other way to shorten a long period
video_fps = None       # frame rate of the video file. None = automatic: playback_fps repeated to at least 10 fps with a whole
                       # number of repeats per PNG. It does not change the speed; players handle very low frame rates badly,
                       # so every PNG is repeated. Keep it a whole multiple of playback_fps (below it, PNGs are dropped)
video_quality = 20     # CRF value (lower = better quality, range 0-51, 18-28 is good)
output_width = 1920    # Output video width in pixels (height auto-calculated to maintain aspect ratio, set to None to keep original size)

# Animation parameters
start_date_str = start_date[:13]  # Extract YYYY-MM-DDTHH
end_date_str = end_date[:13]      # Extract YYYY-MM-DDTHH
animation_filename = f"{animation_dir}{fig_basename}{start_date_str}_{end_date_str}.mp4"

###############################################################################################
# Main execution
###############################################################################################

# script_dir = "/global/homes/f/feng045/program/PyFLEXTRKR-dev/Analysis/"
script_dir = "./"

print("Make cell tracking animation")
print(f"Plotting script: {script_dir}plot_subset_cell_tracks_terrain.py")
print(f"Date range: {start_date} to {end_date}")
print(f"Radar location: ({radar_lat}, {radar_lon})")
print(f"Projection: {projection} (central longitude {central_longitude}, central latitude {central_latitude}, "
      f"standard parallels {standard_parallels})")
print(f"Execution mode: Plotting={'✅' if run_plotting else '❌'}, FFmpeg={'✅' if run_ffmpeg else '❌'}")

# Create directories if they don't exist
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
        'python', f'{script_dir}plot_subset_cell_tracks_terrain.py',
        '--start', start_date,
        '--end', end_date,
        '--config', config_file,
        '--projection', projection,
    ]

    # Optional projection parameters
    if central_longitude is not None:
        cmd.extend(['--central_longitude', str(central_longitude)])
    if central_latitude is not None:
        cmd.extend(['--central_latitude', str(central_latitude)])
    if standard_parallels is not None:
        cmd.extend(['--standard_parallels'] + [str(v) for v in standard_parallels])
    
    # Add radar location if provided
    if radar_lat is not None:
        cmd.extend(['--radar_lat', str(radar_lat)])
    if radar_lon is not None:
        cmd.extend(['--radar_lon', str(radar_lon)])
    
    # Add extent if all values are provided
    if all(v is not None for v in [lon_min, lon_max, lat_min, lat_max]):
        cmd.extend(['--extent', str(lon_min), str(lon_max), str(lat_min), str(lat_max)])
    
    cmd.extend([
        '--subset', str(subset),
        '--time_format', str(time_format),
        '--parallel', str(parallel_mode),
        '--workers', str(n_workers),
    ] + (['--batch_size', str(batch_size)] if batch_size is not None else []) + [
        '--output', figdir,
        '--figsize_x', str(figsize_x),
        '--figbasename', fig_basename,
        '--varname', varname,
        '--draw_land', str(int(draw_land)),
        '--draw_border', str(int(draw_border)),
        '--draw_state', str(int(draw_state)),
        '--show_rangecircle', str(int(show_rangecircle)),
        '--show_azimuth', str(int(show_azimuth)),
        '--show_tracks', str(int(show_tracks)),
        '--fontsize', str(fontsize),
        '--map_resolution', map_resolution,
        '--title_prefix', title_prefix,
    ])
    
    # Add optional show_paths and show_symbols if specified (not None)
    if show_paths is not None:
        cmd.extend(['--show_paths', str(int(show_paths))])
    if show_symbols is not None:
        cmd.extend(['--show_symbols', str(int(show_symbols))])
    if fontsize_tracks is not None:
        cmd.extend(['--fontsize_tracks', str(fontsize_tracks)])
    cmd.extend(['--show_city', str(int(show_city))])
    cmd.extend(['--show_nexrad', str(int(show_nexrad))])
    cmd.extend(['--show_cell_numbers', str(int(show_cell_numbers))])
    cmd.extend(['--nexrad_radius', str(nexrad_radius)])
    # Cell style: only the options that are set, the others stay the default of the plotting script
    cmd.extend(['--show_cell_outline', str(int(show_cell_outline))])
    cmd.extend(['--cell_perim_width', str(cell_perim_width)])
    # '=' form: a line style such as '--' would be read as the end-of-options marker by argparse
    cmd.append(f'--cell_track_ls={cell_track_ls}')
    cmd.extend(['--cell_min_hours', str(cell_min_hours)])
    for _opt, _val in (('--cell_color', cell_color), ('--cell_perim_alpha', cell_perim_alpha), ('--cell_halo', cell_halo),
                       ('--cell_perim_cmap', cell_perim_cmap), ('--cell_track_color', cell_track_color),
                       ('--cell_track_lw', cell_track_lw)):
        if _val is not None:
            cmd.extend([_opt, str(_val)])
    cmd.extend(['--grid_linewidth', str(grid_linewidth), f'--grid_linestyle={grid_linestyle}', '--grid_alpha', str(grid_alpha)])
    cmd.extend(['--show_terrain', str(int(show_terrain))])

    print(f"Command: {' '.join(cmd)}")
    result = subprocess.run(cmd)

    if result.returncode != 0:
        print(f"❌ Error: Plotting script failed with exit code {result.returncode}")
        exit(1)
        
    print("✅ Plotting completed successfully!")
else:
    print("⏭️  Skipping plotting - using existing PNG files")

#########################################################
# Make animation using ffmpeg
#########################################################
if run_ffmpeg:
    print("🎬 Creating animation from PNG files...")
    
    # Get all PNG files matching the basename pattern
    all_png_files = sorted(glob.glob(f'{figdir}{fig_basename}*.png'))
    
    # Parse datetime from actual filenames to filter by date range
    start_dt = pd.to_datetime(start_date)
    end_dt = pd.to_datetime(end_date)
    
    expected_files = []
    for png_file in all_png_files:
        # Extract the datetime string from filename (assumes format: basename_YYYYMMDD_HHMMSS.png)
        try:
            basename_len = len(fig_basename)
            datetime_str = os.path.basename(png_file)[basename_len:basename_len+15]  # YYYYMMDD_HHMMSS
            file_dt = pd.to_datetime(datetime_str, format='%Y%m%d_%H%M%S')
            
            # Check if file is within the specified date range
            if start_dt <= file_dt <= end_dt:
                expected_files.append(png_file)
        except (ValueError, IndexError):
            # Skip files that don't match the expected datetime format
            continue
    
    print(f"Found {len(expected_files)} PNG files within date range")
    print(f"Time range: {start_date} to {end_date}")

    if len(expected_files) == 0:
        print("❌ No PNG files found within the specified date range!")
        print(f"   Check directory: {figdir}")
        print(f"   Expected pattern: {fig_basename}YYYYMMDD_HHMMSS.png")
        exit(1)

    # Every frame_stride-th PNG
    if frame_stride > 1:
        expected_files = sorted(expected_files)[::frame_stride]
        print(f"Using every {frame_stride}th PNG: {len(expected_files)} files")

    # Create a temporary file list for FFmpeg
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        temp_filelist = f.name
        for png_file in sorted(expected_files):
            f.write(f"file '{png_file}'\n")

    try:
        # Build video filter string based on output_width parameter
        if output_width is not None:
            # Scale to specified width, maintaining aspect ratio, ensuring dimensions divisible by 2
            vf_scale = f'scale={output_width}:-2'
        else:
            # Just ensure dimensions are divisible by 2 (no scaling)
            vf_scale = 'scale=trunc(iw/2)*2:trunc(ih/2)*2'
        
        # Frame rate of the video file: every PNG is repeated a whole number of times (the speed is set by playback_fps only)
        video_fps_used = video_fps if video_fps is not None else playback_fps * max(1, math.ceil(10 / playback_fps))

        # Use FFmpeg concat demuxer with file list
        ffmpeg_cmd = [
            'ffmpeg',
            '-f', 'concat',
            '-safe', '0',
            '-r', str(playback_fps),  # input: PNGs shown per second = playback speed
            '-i', temp_filelist,
            '-vf', vf_scale,
            '-c:v', 'libx264',
            '-r', str(video_fps_used),  # output: frame rate of the video file (PNGs are repeated to reach it)
            '-crf', str(video_quality),
            '-pix_fmt', 'yuv420p',
            '-y', animation_filename
        ]
        
        print(f"🎬 Animation settings:")
        print(f"   Playback: {playback_fps} PNGs per second (speed), every {frame_stride}th PNG, "
              f"video file {video_fps_used:g} fps (each PNG repeated {video_fps_used / playback_fps:g} times)")
        print(f"   Duration: {len(expected_files) / playback_fps:.0f} s")
        print(f"   Video quality (CRF): {video_quality} (lower=better)")
        print(f"   Output width: {output_width if output_width else 'original'} pixels (height auto-scaled)")
        print(f"FFmpeg command: {' '.join(ffmpeg_cmd)}")
        print(f"Using {len(expected_files)} PNG files from {expected_files[0]} to {expected_files[-1]}")
        
        result = subprocess.run(ffmpeg_cmd)
        
    finally:
        # Clean up temporary file
        os.unlink(temp_filelist)

    if result.returncode == 0:
        print(f"✅ Animation created successfully!")
        print(f"🎬 View animation here: {animation_filename}")
    else:
        print(f"❌ Error: FFmpeg failed with exit code {result.returncode}")
        
else:
    print("⏭️  Skipping animation creation - PNG files ready for manual processing")
