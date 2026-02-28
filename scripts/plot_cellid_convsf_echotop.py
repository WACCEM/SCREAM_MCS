"""
Visualize convective cell masks from PyFLEXTRKR cell identification outputs.

Creates 4-panel plots showing:
- Composite reflectivity
- Convective/stratiform classification
- Expanded cell mask
- 10-dBZ echo-top height

Usage:
>python plot_cellid_convsf_echotop.py -s STARTDATE -e ENDDATE -c CONFIG.yml

Required arguments:
-s, --start           Start time (format: YYYY-mm-ddTHH:MM:SS)
-e, --end             End time (format: YYYY-mm-ddTHH:MM:SS)
-c, --config          YAML config file for tracking

Optional arguments:
-p, --parallel        Run in parallel (0:serial, 1:parallel, default=0)
--workers             Number of Dask workers for parallel processing (default=4)
--extent              Map extent: lonmin lonmax latmin latmax
--figsize             Figure size: width height in inches (default: 16 10)
--dpi                 Figure DPI (default=200)
--output              Output directory for figures
--fontsize            Font size for labels and text (default=12)
--wspace              Width space between subplots (default=0.15)
--hspace              Height space between subplots (default=0.15)

Author: Zhe Feng (zhe.feng@pnnl.gov)
Date: February 9, 2026
"""

import numpy as np
import pandas as pd
import xarray as xr
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
import matplotlib.gridspec as gridspec
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from cartopy.mpl.ticker import LongitudeFormatter, LatitudeFormatter
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
import sys
import argparse
import warnings
from pathlib import Path
warnings.filterwarnings("ignore")

# For parallel processing
from dask.distributed import Client, LocalCluster

# PyFLEXTRKR utilities
sys.path.insert(0, '/global/homes/f/feng045/program/PyFLEXTRKR-dev')
from pyflextrkr.ft_utilities import load_config, subset_files_timerange

# Colormaps
try:
    import colormaps as colormaps
except ImportError:
    print("Warning: colorcet or colormaps not found. Using default colormaps.")
    colormaps = None

# Use non-gui backend
mpl.use('agg')

#-----------------------------------------------------------------------
def parse_cmd_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Visualize convective cell masks from PyFLEXTRKR cell identification outputs."
    )
    parser.add_argument("-s", "--start", help="first time in time series to plot, format=YYYY-mm-ddTHH:MM:SS", required=True)
    parser.add_argument("-e", "--end", help="last time in time series to plot, format=YYYY-mm-ddTHH:MM:SS", required=True)
    parser.add_argument("-c", "--config", help="yaml config file for tracking", required=True)
    parser.add_argument("-p", "--parallel", help="flag to run in parallel (0:serial, 1:parallel)", type=int, default=0)
    parser.add_argument("--workers", type=int, help="Number of Dask workers for parallel processing", default=4)
    parser.add_argument("--extent", nargs='+', help="map extent (lonmin, lonmax, latmin, latmax)", type=float, default=None)
    parser.add_argument("--subset", help="flag to subset data (0:no, 1:yes)", type=int, default=0)
    parser.add_argument("--figbasename", help="output figure base name", default="")
    parser.add_argument("--figsize", nargs='+', help="figure size (width, height) in inches", type=float, default=None)
    parser.add_argument("--figsize_x", type=float, help="figure width in inches (height auto-calculated)", default=16)
    parser.add_argument("--dpi", type=int, help="figure DPI", default=200)
    parser.add_argument("--output", help="output directory", default=None)
    parser.add_argument("--fontsize", type=float, help="Font size for labels and text", default=12)
    parser.add_argument("--wspace", type=float, help="Width space between subplots", default=0.15)
    parser.add_argument("--hspace", type=float, help="Height space between subplots", default=0.15)
    parser.add_argument("--map_resolution", help="Map resolution for Natural Earth features ('10m', '50m', '110m')", default='50m')
    parser.add_argument("--title_prefix", help="Prefix string to add to figure title", default="")
    args = parser.parse_args()

    # Put arguments in a dictionary
    args_dict = {
        'start_datetime': args.start,
        'end_datetime': args.end,
        'run_parallel': args.parallel,
        'workers': args.workers,
        'config_file': args.config,
        'extent': args.extent,
        'subset': args.subset,
        'figbasename': args.figbasename,
        'figsize': tuple(args.figsize) if args.figsize else None,
        'figsize_x': args.figsize_x,
        'dpi': args.dpi,
        'out_dir': args.output,
        'fontsize': args.fontsize,
        'wspace': args.wspace,
        'hspace': args.hspace,
        'map_resolution': args.map_resolution,
        'title_prefix': args.title_prefix,
    }

    return args_dict


#-----------------------------------------------------------------------
def plot_mxn_panels_lambert(nrow, ncol, data_arrays, lon_2d, lat_2d, cmaps, levels, 
                             titles=None, cbar_labels=None, figsize=(15, 10), 
                             dpi=150, map_extent=None, suptitle=None,
                             wspace=0.15, hspace=0.25, fontsize=12, figname=None):
    """
    Create a m×n panel plot with LambertConformal projection.
    
    Parameters:
    -----------
    nrow : int
        Number of rows
    ncol : int
        Number of columns
    data_arrays : list of lists (nrow × ncol)
        Nested list containing 2D data arrays to plot. Can contain None for empty panels.
    lon_2d : 2D array
        Longitude coordinates
    lat_2d : 2D array
        Latitude coordinates
    cmaps : list of lists (nrow × ncol)
        Nested list of colormap names for each panel
    levels : list of lists (nrow × ncol)
        Nested list of (vmin, vmax) tuples for each panel
    titles : list of lists (nrow × ncol), optional
        Nested list of titles for each panel
    cbar_labels : list of lists (nrow × ncol), optional
        Nested list of colorbar labels for each panel
    figsize : tuple, optional
        Figure size (width, height)
    dpi : int, optional
        Figure resolution
    map_extent : tuple, optional
        Map extent as (lon_min, lon_max, lat_min, lat_max). Default: [-110, -75, 25, 50]
    suptitle : string, optional
        Suptitle for figure
    wspace : float, optional
        Width space between subplots
    hspace : float, optional
        Height space between subplots
    fontsize : int, optional
        Base font size for labels
    figname : string, optional
        Name of the figure to save.
    
    Returns:
    --------
    fig : matplotlib figure
    axes : list of lists (nrow × ncol) of axes
    """
    mpl.rcParams['font.size'] = fontsize
    
    # Set map extent
    if map_extent is None:
        map_extent = [-110, -75, 25, 50]
    
    # Calculate central longitude
    central_lon = (map_extent[0] + map_extent[1]) / 2
    
    # Create projection
    proj = ccrs.LambertConformal(central_longitude=central_lon)
    land = cfeature.NaturalEarthFeature('physical', 'land', map_resolution)
    borders = cfeature.NaturalEarthFeature('cultural', 'admin_0_boundary_lines_land', map_resolution)
    states = cfeature.NaturalEarthFeature('cultural', 'admin_1_states_provinces_lakes', map_resolution)
    rivers = cfeature.NaturalEarthFeature('physical', 'rivers_lake_centerlines', map_resolution)
    map_edgecolor = 'k'
    river_color = 'gray'
    
    # Set default titles and labels if not provided
    if titles is None:
        titles = [[f'Panel {i*ncol + j + 1}' for j in range(ncol)] for i in range(nrow)]
    if cbar_labels is None:
        cbar_labels = [['' for j in range(ncol)] for i in range(nrow)]
    
    # Create figure and GridSpec
    fig = plt.figure(figsize=figsize, dpi=dpi)
    
    # Set up panels (nrow x ncol)
    h_ratios = list(np.repeat(1, nrow))
    w_ratios = list(np.repeat(1, ncol))
    gs = gridspec.GridSpec(nrow, ncol, figure=fig, 
                          height_ratios=h_ratios, width_ratios=w_ratios, 
                          wspace=wspace, hspace=hspace)
    
    # Create axes for each panel
    axes = [[None for j in range(ncol)] for i in range(nrow)]
    
    # Loop over rows and columns
    for row in range(nrow):
        for col in range(ncol):
            # Check if data is provided for this panel
            if data_arrays[row][col] is not None:
                # Setup two columns (left: plot, right: colorbar)
                gss = gridspec.GridSpecFromSubplotSpec(
                    1, 2, subplot_spec=gs[row, col], 
                    height_ratios=[1], width_ratios=[1, 0.04], 
                    wspace=0.02, hspace=0.
                )
                
                # Create axis with projection
                ax = plt.subplot(gss[0], projection=proj)
                
                # Set extent
                ax.set_extent(map_extent, crs=ccrs.PlateCarree())
                
                # Add map features
                ax.add_feature(states, edgecolor='gray', facecolor='none', linewidth=0.5, zorder=3)
                ax.add_feature(borders, edgecolor=map_edgecolor, facecolor='none', linewidth=0.5, zorder=3)
                ax.add_feature(land, facecolor='none', edgecolor=map_edgecolor, linewidth=0.5, zorder=3)
                # ax.add_feature(rivers, edgecolor=river_color, facecolor='none', linewidth=0.5, zorder=3)
                ax.set_aspect('auto', adjustable=None)
                
                # Plot data
                vmin, vmax = levels[row][col]
                im = ax.pcolormesh(lon_2d, lat_2d, data_arrays[row][col], 
                                  transform=ccrs.PlateCarree(),
                                  cmap=cmaps[row][col], vmin=vmin, vmax=vmax,
                                  shading='auto')
                
                # Add title
                ax.set_title(titles[row][col], loc='left', fontsize=fontsize, fontweight='bold')
                
                # Add gridlines without labels inside the map
                gl = ax.gridlines(draw_labels=False, linewidth=0.5, color='gray', alpha=0.5, linestyle='--')
                gl.right_labels = False
                gl.top_labels = False
                gl.xlabel_style = {'size': fontsize-2}
                gl.ylabel_style = {'size': fontsize-2}
                # lon_formatter = LongitudeFormatter(zero_direction_label=True)
                # lat_formatter = LatitudeFormatter()
                # ax.xaxis.set_major_formatter(lon_formatter)
                # ax.yaxis.set_major_formatter(lat_formatter)
                
                # Add axis labels only on outer edges
                if row == nrow - 1:  # Bottom row
                    ax.set_xlabel('Longitude', fontsize=fontsize-2)
                if col == 0:  # Left column
                    ax.set_ylabel('Latitude', fontsize=fontsize-2)
                
                # Create colorbar axis
                cax = plt.subplot(gss[1])
                cbar = plt.colorbar(im, cax=cax, label=cbar_labels[row][col])
                
                axes[row][col] = ax
    
    # Figure title
    if suptitle is not None:
        fig.suptitle(suptitle, fontsize=fontsize*1.5, fontweight='bold')

    # Save figure if filename provided
    if figname is not None:
        # Thread-safe figure output
        canvas = FigureCanvas(fig)
        canvas.print_png(figname)
        
    return fig, axes


#-----------------------------------------------------------------------
def work_for_time_loop(datafile, plot_info):
    """
    Process data for a single frame and make the plot.

    Args:
        datafile: string
            Pixel-level data filename
        plot_info: dictionary
            Dictionary containing plotting variables

    Returns:
        figname: string
            Output figure filename
    """
    
    map_extent = plot_info.get('map_extent')
    subset = plot_info.get('subset', 0)
    figbasename = plot_info.get('figbasename', '')
    figdir = plot_info.get('figdir')
    figsize = plot_info.get('figsize')
    dpi = plot_info.get('dpi')
    fontsize = plot_info.get('fontsize')
    wspace = plot_info.get('wspace')
    hspace = plot_info.get('hspace')
    map_resolution = plot_info.get('map_resolution', '50m')
    title_prefix = plot_info.get('title_prefix', '')

    # Read pixel-level data
    ds = xr.open_dataset(datafile).squeeze()

    # Get map extent from data if not provided
    if map_extent is None:
        lon_min = float(ds.longitude.min())
        lon_max = float(ds.longitude.max())
        lat_min = float(ds.latitude.min())
        lat_max = float(ds.latitude.max())
        map_extent = [lon_min, lon_max, lat_min, lat_max]

    # Get lon/lat coordinates
    lon_2d = ds.longitude.values
    lat_2d = ds.latitude.values

    # Subset pixel data within the map domain
    if subset == 1:
        lonmin, lonmax = map_extent[0], map_extent[1]
        latmin, latmax = map_extent[2], map_extent[3]
        
        # Use index slicing to subset - works for any 2D lat/lon grid without creating NaNs
        lon_vals = ds['longitude'].values
        lat_vals = ds['latitude'].values
        
        # Find all points within the domain
        mask = ((lon_vals >= lonmin) & (lon_vals <= lonmax) & 
                (lat_vals >= latmin) & (lat_vals <= latmax))
        
        # Find bounding box in index space
        rows, cols = np.where(mask)
        
        if len(rows) > 0:
            row_min, row_max = rows.min(), rows.max() + 1
            col_min, col_max = cols.min(), cols.max() + 1
            
            # Get dimension names
            dim_names = list(ds['longitude'].dims)
            dim_y = dim_names[0]
            dim_x = dim_names[1]
            
            # Subset using index slicing
            lon_2d = ds['longitude'].isel({dim_y: slice(row_min, row_max), dim_x: slice(col_min, col_max)}).squeeze().values
            lat_2d = ds['latitude'].isel({dim_y: slice(row_min, row_max), dim_x: slice(col_min, col_max)}).squeeze().values
            dbz_sub = ds['dbz_comp'].isel({dim_y: slice(row_min, row_max), dim_x: slice(col_min, col_max)}).squeeze()
            convsf_sub = ds['convsf'].isel({dim_y: slice(row_min, row_max), dim_x: slice(col_min, col_max)}).squeeze()
            convmask_sub = ds['conv_mask_inflated'].isel({dim_y: slice(row_min, row_max), dim_x: slice(col_min, col_max)}).squeeze()
            echotop_sub = ds['echotop10'].isel({dim_y: slice(row_min, row_max), dim_x: slice(col_min, col_max)}).squeeze()
        else:
            # No valid data in subset domain, use full domain
            dbz_sub = ds['dbz_comp'].squeeze()
            convsf_sub = ds['convsf'].squeeze()
            convmask_sub = ds['conv_mask_inflated'].squeeze()
            echotop_sub = ds['echotop10'].squeeze()
    else:
        # Use full domain
        dbz_sub = ds['dbz_comp'].squeeze()
        convsf_sub = ds['convsf'].squeeze()
        convmask_sub = ds['conv_mask_inflated'].squeeze()
        echotop_sub = ds['echotop10'].squeeze()

    # Prepare 4 data arrays (as nested list for 2x2 layout)
    data1 = dbz_sub.where(dbz_sub > 0, np.nan)  # Composite reflectivity
    data2 = convsf_sub.where(convsf_sub > 1, np.nan)  # Convective/stratiform flag (mask NO_SURF_ECHO=1)
    
    # For cell mask: apply modulo to cycle colors when there are > 256 cells
    # This prevents repeated colors for high-numbered cells
    convmask_data = convmask_sub.values.copy()
    mask_nonzero = convmask_data > 0
    if mask_nonzero.any():
        # Apply modulo only to non-zero values, cycling through 1-256
        convmask_data[mask_nonzero] = ((convmask_data[mask_nonzero] - 1) % 256) + 1
    data3 = xr.DataArray(convmask_data, coords=convmask_sub.coords, dims=convmask_sub.dims)
    data3 = data3.where(data3 > 0, np.nan)  # Expanded convective cell mask (cycled colors)
    
    data4 = echotop_sub / 1000  # 10-dBZ echo-top height [m to km]

    # Create custom colormap for convective/stratiform classification
    # Define colors for categories 2, 3, 4 (NO_SURF_ECHO:1 is masked)
    convsf_colors = ['gold', 'limegreen', 'red']
    convsf_cmap = ListedColormap(convsf_colors)
    convsf_bounds = [1.5, 2.5, 3.5, 4.5]  # Boundaries between categories
    convsf_norm = BoundaryNorm(convsf_bounds, convsf_cmap.N)

    # Organize data as nested list [row][col]
    data_arrays = [
        [data1, data2],  # First row
        [data3, data4]   # Second row
    ]

    # Define colormaps
    if colormaps is not None:
        cmaps = [
            ['gist_ncar', convsf_cmap],  # First row
            [colormaps.cet_g_bw_minc_minl, colormaps.WhiteBlueGreenYellowRed]  # Second row
        ]
    else:
        # Fallback to standard colormaps if colormaps module not available
        cmaps = [
            ['gist_ncar', convsf_cmap],
            ['gray', 'RdYlBu_r']
        ]

    # Define levels (vmin, vmax) for each panel
    levels = [
        [(0, 70), (1.5, 4.5)],    # First row
        [(1, 256), (0, 18)]       # Second row
    ]

    # Define titles
    titles = [
        ['Composite Reflectivity', 'Convective/Stratiform Flag'],
        ['Expanded Cell Mask', '10-dBZ Echo-top Height']
    ]

    # Define colorbar labels
    cbar_labels = [
        ['Reflectivity (dBZ)', ''],
        ['Cell ID', '10-dBZ ETH (km)']
    ]

    # Create time string for title and filename
    time_str = ds.time.dt.strftime('%Y-%m-%d %H:%M UTC').item()
    time_str_fig = ds.time.dt.strftime('%Y%m%d_%H%M').item()
    suptitle = f"{title_prefix} | {time_str}" if title_prefix else time_str
    figname = f"{figdir}{figbasename}{time_str_fig}.png"

    # Create the plot
    fig, axes = plot_mxn_panels_lambert(
        nrow=2, ncol=2,
        data_arrays=data_arrays,
        lon_2d=lon_2d,
        lat_2d=lat_2d,
        cmaps=cmaps,
        levels=levels,
        titles=titles,
        suptitle=suptitle,
        cbar_labels=cbar_labels,
        figsize=figsize,
        dpi=dpi,
        map_extent=map_extent,
        wspace=wspace,
        hspace=hspace,
        fontsize=fontsize,
        figname=figname,
    )

    # Customize colorbar for convective/stratiform panel (row=0, col=1)
    # Find all axes in the figure and identify the colorbar axis for the second panel
    all_axes = fig.get_axes()
    # Axes are created in order: map[0,0], cbar[0,0], map[0,1], cbar[0,1], map[1,0], cbar[1,0], map[1,1], cbar[1,1]
    # So colorbar for panel [0,1] should be at index 3
    cbar_ax = all_axes[3]  # Colorbar axis for second panel (row=0, col=1)
    # Set ticks and labels directly on the colorbar axis
    cbar_ax.set_yticks([2, 3, 4])
    cbar_ax.set_yticklabels(['WeakEcho', 'Stratiform', 'Convective'])

    # Save figure
    fig.savefig(figname, dpi=dpi, bbox_inches='tight', facecolor='w')
    plt.close(fig)

    print(f"Saved: {figname}")
    
    return figname


#-----------------------------------------------------------------------
if __name__ == "__main__":

    # Parse command-line arguments
    args_dict = parse_cmd_args()
    start_datetime = args_dict['start_datetime']
    end_datetime = args_dict['end_datetime']
    run_parallel = args_dict['run_parallel']
    n_workers = args_dict['workers']
    config_file = args_dict['config_file']
    map_extent = args_dict['extent']
    subset = args_dict['subset']
    figbasename = args_dict['figbasename']
    figsize = args_dict['figsize']
    figsize_x = args_dict['figsize_x']
    dpi = args_dict['dpi']
    out_dir = args_dict['out_dir']
    fontsize = args_dict['fontsize']
    wspace = args_dict['wspace']
    hspace = args_dict['hspace']
    map_resolution = args_dict['map_resolution']
    title_prefix = args_dict['title_prefix']
    
    # Determine the figsize based on lat/lon ratio
    if figsize is None:
        if map_extent is not None:
            # Calculate aspect ratio from map extent
            lon_span = map_extent[1] - map_extent[0]
            lat_span = map_extent[3] - map_extent[2]
            # Use simple lat/lon ratio (works reasonably well for mid-latitudes)
            aspect_ratio = lat_span / lon_span
            figsize_y = figsize_x * aspect_ratio
            figsize = (figsize_x, figsize_y)
        else:
            # Default figsize if map_extent not provided
            figsize = (figsize_x, figsize_x * 0.625)  # 16:10 aspect ratio
    print(f'Figure size (width, height) in inches: {figsize}')

    # Load configuration
    config = load_config(config_file)
    
    # Get pixel file directory and basename from config
    cloudid_filebase = config['cloudid_filebase']
    tracking_outpath = config.get('tracking_outpath')
    root_path = config.get('root_path')
    
    # Set output directory
    if out_dir is None:
        out_dir = f"{root_path}/quicklooks/"
    figdir = out_dir
    Path(figdir).mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {figdir}")

    # Find all pixel files within time range
    pixel_dir = tracking_outpath

    # Convert datetime string to Epoch time (base time)
    start_basetime = pd.to_datetime(start_datetime).timestamp()
    end_basetime = pd.to_datetime(end_datetime).timestamp()
    
    # Subset files within time range using directory path
    datafiles_all, \
    datafiles_basetime, \
    datafiles_datestring, \
    datafiles_timestring = subset_files_timerange(
        pixel_dir,
        cloudid_filebase,
        start_basetime,
        end_basetime,
        time_format='yyyymodd_hhmmss',
    )
    
    ntimes = len(datafiles_all)
    print(f"Number of files within time range: {ntimes}")
    
    if ntimes == 0:
        print("ERROR: No files found within specified time range")
        sys.exit(1)

    # Put plotting info in a dictionary
    plot_info = {
        'map_extent': map_extent,
        'subset': subset,
        'figbasename': figbasename,
        'figdir': figdir,
        'figsize': figsize,
        'dpi': dpi,
        'fontsize': fontsize,
        'wspace': wspace,
        'hspace': hspace,
        'map_resolution': map_resolution,
        'title_prefix': title_prefix,
    }

    # Serial processing
    if run_parallel == 0:
        print("Processing in serial...")
        for ifile in datafiles_all:
            figname = work_for_time_loop(ifile, plot_info)
    
    # Parallel processing
    elif run_parallel == 1:
        print(f"Processing in parallel with {n_workers} workers...")
        
        # Initialize Dask cluster
        cluster = LocalCluster(n_workers=n_workers, threads_per_worker=1)
        client = Client(cluster)
        print(f"Dask cluster dashboard: {client.dashboard_link}")
        
        # Create list of delayed tasks
        from dask import delayed
        results = []
        for ifile in datafiles_all:
            result = delayed(work_for_time_loop)(ifile, plot_info)
            results.append(result)
        
        # Compute all tasks
        from dask import compute
        final_results = compute(*results)
        
        # Close Dask cluster
        client.close()
        cluster.close()
        
        print(f"Completed processing {len(final_results)} files")
    
    print("Done!")
