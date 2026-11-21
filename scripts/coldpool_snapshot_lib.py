"""
Shared functions of the SCREAM cold pool snapshots (notebook Notebooks/tests/test_plot_coldpool_snapshots_scream.ipynb and
script plot_subset_cell_coldpool_snapshots.py): reading one time, the 2 m virtual potential temperature anomaly, the layouts.

Edit the functions HERE (the notebook imports this file with autoreload, the script imports it): there is no second copy.

  load_frame(t, extent, ...)      dictionary of the cropped fields of one time
  load_tracks(t_first, t_last)    cell tracks of the cell tracking statistics of the month
  make_map_info(extent, ...)      projection and axes limits, fixed for all frames
  plot_single_panel / plot_two_panel(frame, track_dict, style, map_info) -> figure
  load_case(file, case, cli)      STYLE / map / options of a case from coldpool_cases.yaml
  draw_terrain, draw_coldpool, draw_reflectivity, draw_cells, draw_winds, draw_rain_contours   building blocks

A function of the layouts has the signature (frame, track_dict, style, map_info); a replacement of it can be given to
the script as --plot_module FILE --plot_func NAME.
"""
# ------------------------------------------------------------------------
# imports and paths
# ------------------------------------------------------------------------
import os, sys, glob, re, copy, datetime
import numpy as np
import pandas as pd
import xarray as xr
from scipy.signal import fftconvolve
from scipy.ndimage import generate_binary_structure
from skimage.draw import disk
import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.colors import LinearSegmentedColormap
from mpl_toolkits.axes_grid1.inset_locator import inset_axes
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from cartopy.mpl.ticker import LongitudeFormatter, LatitudeFormatter
from pyflextrkr.ft_utilities import load_config

# Cell tracking helpers of the cell-track plotting script (same folder as this file)
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)
import plot_subset_cell_tracks_terrain as cellplot
import yaml

# Cell tracking config: root path, file base names and grid spacing (all months of the run share them; the
# pixel-level files and the track statistics of a time are found by the month of the time)
CONFIG_FILE = '/global/homes/f/feng045/program/scream/tracking/config_celltracking_3km_SCREAMv1-Cess2_CONUS_05.yaml'
# SCREAM 2D surface fields remapped to the same HRRR grid
DIR_2D = '/pscratch/sd/w/wcmca1/SCREAMv1-cess2/remap_conus_2D_5min/'
BASE_2D = 'scream.2D.5min.INSTANT.nmins_x5.'
TERRAIN_FILE = '/pscratch/sd/w/wcmca1/SCREAMv1-cess2/maps/hrrr_sfc_latlon_orog_lsm.nc'


_PATHS_KEY = None


def init_paths(config_file=CONFIG_FILE, dir_2d=DIR_2D, base_2d=BASE_2D):
    """
    Set the paths and names that the functions below use (module-level variables). Does nothing if they are already
    set to these values (a Dask worker calls it for every frame).
    """
    global config, ROOT, PIXEL_BASE, STATS_BASE, DX, DIR_2D, BASE_2D, _PATHS_KEY
    key = (config_file, dir_2d, base_2d)
    if key == _PATHS_KEY:
        return
    config = load_config(config_file)
    ROOT = config['root_path']
    PIXEL_BASE = config['pixeltracking_filebase']
    STATS_BASE = config['trackstats_filebase']
    DX = config['dx']   # grid spacing [m]
    DIR_2D, BASE_2D = dir_2d, base_2d
    _PATHS_KEY = key


init_paths()


def month_period(t):
    """Start and end strings of the monthly cell tracking run that contains the time, e.g. 20200501.0000_20200601.0000."""
    t = pd.Timestamp(t)
    m0 = pd.Timestamp(year=t.year, month=t.month, day=1)
    m1 = m0 + pd.offsets.MonthBegin(1)
    return f"{m0:%Y%m%d}.0000_{m1:%Y%m%d}.0000"


def pixel_dir(t):
    """Directory of the cell tracking pixel-level files of the month of t."""
    return f"{ROOT}/{config['pixel_path_name']}/{month_period(t)}/"


def stats_file(t):
    """Cell track statistics file of the month of t."""
    return f"{ROOT}/{config['stats_path_name']}/{STATS_BASE}{month_period(t)}.nc"


# ------------------------------------------------------------------------
# file names of one time and the times that have all inputs
# ------------------------------------------------------------------------
def pixel_file(t):
    """Cell tracking pixel-level file of a pandas Timestamp."""
    t = pd.Timestamp(t)
    return f"{pixel_dir(t)}{PIXEL_BASE}{t:%Y%m%d_%H%M%S}.nc"


def file_2d(t):
    """SCREAM 2D surface file of a pandas Timestamp."""
    t = pd.Timestamp(t)
    return f"{DIR_2D}{BASE_2D}{t:%Y-%m-%d-%H%M%S}.nc"


def available_times(start, end):
    """
    Times in [start, end] that have the cell tracking pixel file AND the 2D file (file names only, no data is read).
    Returns (times with both, times with only a pixel file, times with only a 2D file).
    """
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    pix, two = set(), set()
    for day in pd.date_range(start.floor('D'), end.floor('D'), freq='D'):
        for f in glob.glob(f"{pixel_dir(day)}{PIXEL_BASE}{day:%Y%m%d}_*.nc"):
            pix.add(pd.to_datetime(os.path.basename(f)[len(PIXEL_BASE):-3], format='%Y%m%d_%H%M%S'))
        for f in glob.glob(f"{DIR_2D}{BASE_2D}{day:%Y-%m-%d}-*.nc"):
            two.add(pd.to_datetime(os.path.basename(f)[len(BASE_2D):-3], format='%Y-%m-%d-%H%M%S'))
    inrange = lambda s: sorted(t for t in s if start <= t <= end)
    both = sorted(pix & two)
    return inrange(both), inrange(pix - two), inrange(two - pix)


def has_all_inputs(t):
    """True if the pixel file, the 2D file and the track statistics of the month of t exist."""
    return os.path.isfile(pixel_file(t)) and os.path.isfile(file_2d(t)) and os.path.isfile(stats_file(t))


def check_time(t):
    """Print which of the input files of a time exist, and the nearest times that have all of them."""
    t = pd.Timestamp(t)
    print(f"time {t}")
    print(f"  pixel file exists: {os.path.isfile(pixel_file(t))}  {pixel_file(t)}")
    print(f"  2D file exists:    {os.path.isfile(file_2d(t))}  {file_2d(t)}")
    print(f"  track stats exist: {os.path.isfile(stats_file(t))}  {stats_file(t)}")
    both, _, _ = available_times(t - pd.Timedelta('1h'), t + pd.Timedelta('1h'))
    if t not in both:
        print('  NOT available with all inputs; nearest times that are:', [f'{x:%H:%M}' for x in both])
    return t in both


# ------------------------------------------------------------------------
# circular running mean (NaN aware)
# ------------------------------------------------------------------------
def circular_kernel(radius_km, dx_m):
    """
    Normalized circular (disk) kernel of a radius in km on a grid of dx_m metres. The size is always odd (2 * ceil(radius
    in points) + 1) so that the center point is the center of the circle; an even size shifts the mean by one point.
    """
    radius_px = radius_km * 1000. / dx_m
    half = int(np.ceil(radius_px))
    n = 2 * half + 1
    k = np.zeros((n, n), dtype=np.float64)
    rr, cc = disk((half, half), radius_px)
    k[rr, cc] = 1
    return k / k.sum()


def running_mean(field, valid, kernel, min_weight=0.5):
    """
    Circular running mean of a 2D field that ignores invalid points (normalized convolution computed with FFTs):
    mean = conv(valid * field) / conv(valid). Points where less than min_weight of the kernel area has valid
    data (the edge of the data domain) are NaN.
    """
    f = np.where(valid, field, 0.0)
    w = fftconvolve(valid.astype(np.float64), kernel, mode='same')
    num = fftconvolve(f, kernel, mode='same')
    with np.errstate(invalid='ignore', divide='ignore'):
        out = num / w
    out[w < min_weight] = np.nan
    return out


# ------------------------------------------------------------------------
# read one time and compute the cold pool anomaly
# ------------------------------------------------------------------------
RD_CP = 287.04 / 1005.7   # R_d / c_p for the potential temperature

def load_frame(t, extent=None, radius_km=100., buffer_deg=None, dbz_var='dbz_lowlevel', land_ocean_separate=True,
               min_weight=0.2):
    """
    Read the cell tracking pixel file and the 2D surface file of one time, compute the surface virtual potential
    temperature anomaly against a circular running mean (radius_km: the RADIUS of the circle, 100 km = 200 km
    diameter), the rain rate and the winds, and return them cropped to the extent in a dictionary.

    extent: [lonmin, lonmax, latmin, latmax] (degrees east 0-360 or -180..180), None = the whole grid.
    The background is computed on the extent plus buffer_deg (None = radius_km / 70 + 0.1 degrees, the radius at
    50 N), so that it has no edge effect inside the extent.
    land_ocean_separate: True = the background of a land point is the mean of the land points only (and of an
    ocean point of the ocean points only), so that the land-sea contrast does not appear as a cold pool along
    the coast. Land-sea mask: lsm of the HRRR terrain file. min_weight: fraction of the circle that must have data.
    """
    t = pd.Timestamp(t)
    ds2 = xr.open_dataset(file_2d(t))
    dsp = xr.open_dataset(pixel_file(t))
    lon = ds2['longitude'].values
    lat = ds2['latitude'].values
    if not np.allclose(lon, dsp['longitude'].squeeze().values):
        raise ValueError('longitude of the 2D file and of the cell tracking file differ')

    def box(ext):
        """y/x index slices of the lon/lat box."""
        if ext is None:
            return slice(0, lon.shape[0]), slice(0, lon.shape[1])
        lo0, lo1 = np.asarray(ext[:2]) % 360
        m = (lon >= lo0) & (lon <= lo1) & (lat >= ext[2]) & (lat <= ext[3])
        yy, xx = np.where(m)
        return slice(yy.min(), yy.max() + 1), slice(xx.min(), xx.max() + 1)

    if buffer_deg is None:
        buffer_deg = radius_km / 70. + 0.1
    big = None if extent is None else [extent[0] - buffer_deg, extent[1] + buffer_deg,
                                       extent[2] - buffer_deg, extent[3] + buffer_deg]
    ys, xs = box(big)
    ps = ds2['ps'].isel(time=0, y=ys, x=xs).values.astype(np.float64)
    t2 = ds2['T_2m'].isel(time=0, y=ys, x=xs).values.astype(np.float64)
    qv = ds2['qv_2m'].isel(time=0, y=ys, x=xs).values.astype(np.float64)
    # Holes: NaN outside the model domain, and unphysical values at the domain edge (ps 1e4 Pa, T 1e-5 K)
    valid = np.isfinite(ps) & np.isfinite(t2) & np.isfinite(qv) & (ps > 50000.) & (t2 > 200.)
    # Virtual potential temperature at 2 m (qv is a mixing ratio, formula of the LASSO notebook)
    theta = t2 * (1.e5 / np.where(valid, ps, 1.e5)) ** RD_CP
    thetav = theta * (1. + 0.608 * qv)
    kernel = circular_kernel(radius_km, DX)
    ds_ter = xr.open_dataset(TERRAIN_FILE)
    lsm = ds_ter['lsm'].squeeze().values
    land = lsm[ys, xs] > 0.5
    if land_ocean_separate:
        bg_land = running_mean(thetav, valid & land, kernel, min_weight)
        bg_ocean = running_mean(thetav, valid & ~land, kernel, min_weight)
        thetav_bg = np.where(land, bg_land, bg_ocean)
    else:
        thetav_bg = running_mean(thetav, valid, kernel, min_weight)
    anom = np.where(valid, thetav - thetav_bg, np.nan)

    # Crop to the extent
    ys2, xs2 = box(extent)
    cy = slice(ys2.start - ys.start, ys2.stop - ys.start)
    cx = slice(xs2.start - xs.start, xs2.stop - xs.start)
    crop = lambda a: a[cy, cx]
    rain = ds2['precip_total_surf_mass_flux'].isel(time=0, y=ys2, x=xs2).values * 3.6e6   # m/s -> mm/h
    frame = {
        'time': t,
        'timestr': f"{t:%Y-%m-%d %H:%M:%S} UTC",
        'lon': cellplot.norm_lon(lon[ys2, xs2]),     # -180..180 for the map projections
        'lat': lat[ys2, xs2],
        'thetav': crop(thetav), 'thetav_bg': crop(thetav_bg), 'anom': crop(anom), 'valid': crop(valid),
        'rain': rain,
        'U': ds2['U_at_10m_above_surface'].isel(time=0, y=ys2, x=xs2).values,
        'V': ds2['V_at_10m_above_surface'].isel(time=0, y=ys2, x=xs2).values,
        'dbz': dsp[dbz_var].isel(time=0, lat=ys2, lon=xs2).values,
        'tn': dsp['tracknumber'].isel(time=0, lat=ys2, lon=xs2).values,
        'conv_mask': dsp['conv_mask'].isel(time=0, lat=ys2, lon=xs2).values,
    }
    frame['hgt'] = ds_ter['orog'].squeeze().values[ys2, xs2]
    frame['land'] = land[cy, cx]
    ds2.close(); dsp.close(); ds_ter.close()

    # Cell perimeters and centers of the cells in the frame
    st = generate_binary_structure(2, 1)
    frame['tn_perim'] = cellplot.label_perimeter(frame['tn'], st)
    tnconv = np.where(frame['conv_mask'] > 0, frame['tn'], np.nan)
    lon_tn, lat_tn, _, _, tn_unique = cellplot.calc_cell_center(tnconv, frame['lon'], frame['lat'],
                                                               np.arange(frame['lon'].shape[1]), np.arange(frame['lon'].shape[0]))
    frame.update({'lon_tn': lon_tn, 'lat_tn': lat_tn, 'tn_unique': tn_unique})
    return frame


def load_tracks(t_first, t_last=None, lookback_hours=3.):
    """
    Cell tracks that started between t_first - lookback_hours and t_last (default t_first) as the dictionary of the
    cell tracking plots (tracks of the month of t_first; a track is drawn up to 15 minutes after it ended).
    """
    t_first = pd.Timestamp(t_first)
    t_last = t_first if t_last is None else pd.Timestamp(t_last)
    start = (t_first - pd.Timedelta(hours=lookback_hours)).strftime('%Y-%m-%dT%H:%M:%S')
    end = t_last.strftime('%Y-%m-%dT%H:%M:%S')
    return cellplot.get_track_stats(stats_file(t_first), start, end, datetime.timedelta(minutes=15))


# ------------------------------------------------------------------------
# fixed levels, colormaps and sizes: the same in every frame
# ------------------------------------------------------------------------
def get_cmap_by_name(name):
    """Matplotlib colormap, or a colorcet one (e.g. 'CET_L1', 'fire') if matplotlib does not know the name."""
    try:
        return plt.get_cmap(name)
    except ValueError:
        import colorcet
        if name in colorcet.cm:
            return colorcet.cm[name]
        raise ValueError(f"'{name}' is neither a matplotlib nor a colorcet colormap")


def truncate_cmap(name, lo=0.0, hi=1.0, n=256):
    cmap = get_cmap_by_name(name)
    return LinearSegmentedColormap.from_list(f'{name}_trunc', cmap(np.linspace(lo, hi, n)))

STYLE = {
    # Cold pool: virtual potential temperature anomaly [K], negative values only
    'cp_levels': [-5, -4, -3, -2.5, -2, -1.5, -1.25, -1],
    'cp_cmap': 'Blues_r',                # matplotlib or colorcet name
    'cp_cmap_range': [0.0, 0.8],         # part of the colormap that is used (the white end would not show)
    'cp_label': r'2 m $\theta_v$ anomaly (K)',
    # Low-level reflectivity [dBZ], follows the cell tracking plots
    'dbz_levels': np.arange(-10, 70.1, 5),
    'dbz_cmap': 'gist_ncar',
    'dbz_label': 'Low-level reflectivity (dBZ)',   # the maximum of 50-1000 m above the surface
    'dbz_min': 10,            # weaker echo is not drawn (both layouts), so that the cold pool shows
    'dbz_alpha': 1.0,         # < 1 blends the colors with the cold pool shading and they no longer match the colorbar
    # Surface rain rate contours [mm/h]
    'rain_levels': [10],
    'rain_color': 'red',
    'rain_lw': 0.9,
    # Winds at 10 m
    'vector_spacing_km': 60,
    'vector_scale': 400,      # data units (m/s) per axes width: fixed, so that the arrows compare between frames
    'vector_width': 0.0020,
    'vector_color': 'gray',
    'quiverkey_speed': 10,    # speed of the key arrow [m/s]
    'quiverkey_xy': [0.93, 0.10],   # position of the key (arrow center) in axes coordinates
    'quiverkey_box': True,    # filled box behind the key, so that it stands out from the map layers (False = no box)
    'quiverkey_box_color': 'white', 'quiverkey_box_alpha': 0.9, 'quiverkey_box_edge': 'gray',
    'quiverkey_box_pad': 4,   # space between the arrow / label and the box edge [points]
    # Cells
    'perim_color': 'k', 'perim_alpha': 0.6, 'cell_track_color': 'k',
    'show_tracks': True, 'show_paths': True, 'show_symbols': False, 'show_cell_numbers': False,
    'lev_lifetime': np.arange(0.5, 4.01, 0.5), 'cmap_tracks': 'Spectral_r', 'cbticks_tracks': [1, 2, 3, 4],
    'cblabel_tracks': 'Lifetime (hour)', 'marker_size': [10, 10, 10], 'lw_centroid': [1, 1, 1],
    # Map
    'terrain_levels': np.arange(500, 4001, 500), 'terrain_cmap': 'Greys',
    'draw_land': True, 'draw_border': True, 'draw_state': True, 'map_resolution': '50m',
    'fontsize': 11, 'dpi': 150, 'figsize_x': 11.0,   # figure width [in]; the height follows the map aspect
    'title_prefix': 'SCREAM Cess2',
}


# ------------------------------------------------------------------------
# cases: settings per case from a YAML file (STYLE, map and options overrides)
# ------------------------------------------------------------------------
# Built-in values of the options and of the map (the keys of the "options" and "map" blocks of a case)
OPTIONS = {
    'layout': 'two',               # single | two | both
    'bkg_radius_km': 100.,         # radius of the circular running mean of the anomaly [km]
    'land_ocean_separate': True,   # land and ocean points averaged separately
    'dbz_var': 'dbz_lowlevel',     # reflectivity variable of the pixel file (dbz_comp = composite)
    'lookback_hours': 3.,          # cell tracks that started this long before the first time are drawn
    'buffer_deg': None,            # buffer around the extent for the running mean [degree]; None = radius / 70 km + 0.1
}
MAP = {
    'extent': None,                # [lonmin, lonmax, latmin, latmax]; None = the whole grid
    'projection': 'LambertConformal',
    'central_longitude': 'auto',   # 'auto' = the center of the extent
    'central_latitude': 'auto',
    'standard_parallels': 'auto',
}
DEFAULT_CASE_FILE = os.path.join(SCRIPTS_DIR, 'coldpool_cases.yaml')


def _check_keys(block, name, valid):
    unknown = sorted(set(block) - set(valid))
    if unknown:
        raise ValueError(f"unknown key(s) {unknown} in '{name}'; valid keys: {sorted(valid)}")


def make_style(overrides=None):
    """A copy of STYLE with the overrides (a dictionary of STYLE keys; lists become arrays where STYLE has arrays)."""
    overrides = dict(overrides or {})
    _check_keys(overrides, 'style', STYLE)
    style = copy.deepcopy(STYLE)
    for k, v in overrides.items():
        style[k] = np.asarray(v) if isinstance(STYLE[k], np.ndarray) else v
    return style


CASE_KEYS = ('description', 'start_date', 'end_date', 'map', 'options', 'style')


def norm_time(v):
    """'YYYY-mm-ddTHH:MM' (with :SS only if the seconds are not 0) of a string or datetime, None stays None.
    YAML turns an unquoted 2020-05-20T12:00:00 into a datetime, so the values of the file can be either."""
    if v is None:
        return None
    t = pd.Timestamp(v)
    return t.strftime('%Y-%m-%dT%H:%M:%S') if t.second else t.strftime('%Y-%m-%dT%H:%M')


def load_case(case_file=DEFAULT_CASE_FILE, case=None, cli=None):
    """
    Settings of a case: {'name', 'description', 'start_date', 'end_date', 'style', 'map', 'options'}.

    Order of precedence (later wins): built-in STYLE / MAP / OPTIONS < "defaults" of the YAML file < the case <
    cli, a dictionary {'style': {...}, 'map': {...}, 'options': {...}, 'start_date': ..., 'end_date': ...} of the
    values given on the command line.
    map is the keyword arguments of make_map_info, options those of load_frame and of the layouts (see OPTIONS).
    start_date / end_date are 'YYYY-mm-ddTHH:MM' strings, None if neither the file nor the command line gives them.
    """
    cfg = {}
    if case_file is not None and os.path.isfile(case_file):
        with open(case_file) as f:
            cfg = yaml.safe_load(f) or {}
    elif case is not None:
        raise FileNotFoundError(f'case file not found: {case_file}')
    cases = cfg.get('cases') or {}
    if case is not None and case not in cases:
        raise KeyError(f"case '{case}' is not in {case_file}; cases: {sorted(cases)}")
    blocks = {'style': {}, 'map': {}, 'options': {}}
    times = {'start_date': None, 'end_date': None}
    defaults, the_case = cfg.get('defaults') or {}, cases.get(case) or {}
    _check_keys(defaults, "defaults", [k for k in CASE_KEYS if k != 'description'])
    _check_keys(the_case, f'case {case}', CASE_KEYS)
    for src in (defaults, the_case, cli or {}):
        for b in blocks:
            blocks[b].update(src.get(b) or {})
        for k in times:
            if src.get(k) is not None:
                times[k] = norm_time(src[k])
    _check_keys(blocks['map'], 'map', MAP)
    _check_keys(blocks['options'], 'options', OPTIONS)
    out = {'name': case, 'description': the_case.get('description', ''), **times,
           'style': make_style(blocks['style']), 'map': {**MAP, **blocks['map']}, 'options': {**OPTIONS, **blocks['options']}}
    return out


def show_case(c):
    """Print the effective settings of a case (what load_case returned), with the map center that 'auto' gives."""
    print(f"case: {c['name']}  {c['description']}")
    print(f"time range: {c['start_date']} to {c['end_date']}")
    for b in ('map', 'options'):
        print(f'{b}:')
        for k, v in c[b].items():
            print(f'  {k}: {v}')
    mi = make_map_info(**c['map'])
    print(f"  -> map center in use: {mi['central_longitude']:.2f} E, {mi['central_latitude']:.2f} N, "
          f"standard parallels {mi['standard_parallels']}, aspect {mi['aspect_yx']:.3f}")
    print('style:')
    for k, v in c['style'].items():
        print(f'  {k}: {np.asarray(v).tolist() if isinstance(v, np.ndarray) else v}')


# ------------------------------------------------------------------------
# map projection, fixed gridspec, shared drawing helpers
# ------------------------------------------------------------------------
def make_map_info(extent=None, projection='LambertConformal', central_longitude='auto', central_latitude='auto',
                  standard_parallels='auto'):
    """
    Map settings that stay the same for all frames: projection and the axes limits in projection coordinates.

    extent: [lonmin, lonmax, latmin, latmax] box (degrees east, 0-360 or -180..180); None = the whole data grid
        (the rectangle of the grid in the projection).
    central_longitude, central_latitude, standard_parallels: numbers, or 'auto' = the center of the extent
        (one standard parallel at the central latitude); for the whole grid 'auto' is the HRRR projection
        (-97.5, 38.5, 38.5).
    """
    if extent is None:
        with xr.open_dataset(TERRAIN_FILE) as ds_ter:
            lon_grid = ds_ter['longitude'].squeeze().values
            lat_grid = ds_ter['latitude'].squeeze().values
        ext = [float(lon_grid.min()), float(lon_grid.max()), float(lat_grid.min()), float(lat_grid.max())]
        auto_lon, auto_lat = -97.5, 38.5
    else:
        ext = list(extent)
        lo0, lo1 = cellplot.norm_lon(ext[0]), cellplot.norm_lon(ext[1])
        if lo1 < lo0:
            lo1 += 360.
        auto_lon = float(cellplot.norm_lon((lo0 + lo1) / 2.))
        auto_lat = (ext[2] + ext[3]) / 2.
    clon = auto_lon if central_longitude in (None, 'auto') else float(central_longitude)
    clat = auto_lat if central_latitude in (None, 'auto') else float(central_latitude)
    if standard_parallels in (None, 'auto'):
        parallels = [clat]
    else:
        parallels = [float(v) for v in np.atleast_1d(standard_parallels)]
    if cellplot.projection_key(projection) == 'platecarree':
        proj = cellplot.make_projection(projection, clon)
    else:
        proj = cellplot.make_projection(projection, clon, clat, parallels)
    if extent is None:
        proj_extent = cellplot.projected_extent(proj, None, lon_grid, lat_grid)
    else:
        proj_extent = cellplot.projected_extent(proj, ext)
    return {'extent': ext, 'projection': projection, 'central_longitude': clon, 'central_latitude': clat,
            'standard_parallels': parallels, 'proj': proj, 'proj_extent': proj_extent,
            'aspect_yx': (proj_extent[3] - proj_extent[2]) / (proj_extent[1] - proj_extent[0])}


def layout_gridspec(layout):
    """Fixed gridspec parameters of a layout: columns [map, colorbar, (spacer, colorbar | map, colorbar)]."""
    if layout == 'single':
        return dict(ncols=4, width_ratios=[1, 0.02, 0.13, 0.02], map_cols=[0],
                    left=0.075, right=0.94, top=0.92, bottom=0.075, wspace=0.02)
    return dict(ncols=5, width_ratios=[1, 0.02, 0.16, 1, 0.02], map_cols=[0, 3],
                left=0.05, right=0.925, top=0.90, bottom=0.075, wspace=0.02)


def figure_size(layout, map_info, figsize_x):
    """Figure size [in] such that the map axes of the gridspec have the aspect of the projected extent."""
    g = layout_gridspec(layout)
    cell_w = (g['right'] - g['left']) / (g['ncols'] + g['wspace'] * (g['ncols'] - 1))
    map_w = cell_w * g['ncols'] * g['width_ratios'][0] / sum(g['width_ratios'])
    map_h = g['top'] - g['bottom']
    return (figsize_x, round(figsize_x * map_w * map_info['aspect_yx'] / map_h, 2))


def new_figure(layout, map_info, style, figsize=None):
    """Figure with the fixed gridspec; returns fig, list of map axes, list of colorbar axes."""
    g = layout_gridspec(layout)
    figsize = figsize or figure_size(layout, map_info, style['figsize_x'] * (1.0 if layout == 'single' else 1.55))
    mpl.rcParams['font.size'] = style['fontsize']
    fig = plt.figure(figsize=figsize, dpi=style['dpi'], facecolor='w')
    gs = gridspec.GridSpec(1, g['ncols'], width_ratios=g['width_ratios'], left=g['left'], right=g['right'],
                           top=g['top'], bottom=g['bottom'], wspace=g['wspace'])
    axs = [fig.add_subplot(gs[0, c], projection=map_info['proj']) for c in g['map_cols']]
    cols_cax = [1] if layout == 'single' else [1, 4]
    caxs = [fig.add_subplot(gs[0, c]) for c in cols_cax]
    if layout == 'single':
        caxs.append(fig.add_subplot(gs[0, 3]))
    return fig, axs, caxs


def setup_map(ax, map_info, style, left_labels=True):
    """Extent, background features, gridline labels and terrain of one map."""
    data_proj = ccrs.PlateCarree(central_longitude=0)
    ax.set_extent(map_info['proj_extent'], crs=map_info['proj'])
    ax.set_aspect('auto', adjustable=None)
    if style['draw_land']:
        ax.add_feature(cfeature.NaturalEarthFeature('physical', 'land', style['map_resolution']),
                       edgecolor='k', facecolor='none', linewidth=0.8, zorder=4)
    if style['draw_border']:
        ax.add_feature(cfeature.NaturalEarthFeature('cultural', 'admin_0_boundary_lines_land', style['map_resolution']),
                       edgecolor='k', facecolor='none', linewidth=0.8, zorder=4)
    if style['draw_state']:
        ax.add_feature(cfeature.NaturalEarthFeature('cultural', 'admin_1_states_provinces_lakes', style['map_resolution']),
                       edgecolor='gray', facecolor='none', linewidth=0.5, zorder=4)
    gl = ax.gridlines(crs=data_proj, draw_labels=True, linestyle='--', linewidth=0.)
    gl.right_labels = False
    gl.top_labels = False
    gl.left_labels = left_labels
    gl.x_inline = False
    gl.y_inline = False
    gl.rotate_labels = False
    if cellplot.projection_key(map_info['projection']) == 'platecarree':
        ax.xaxis.set_major_formatter(LongitudeFormatter(zero_direction_label=True))
        ax.yaxis.set_major_formatter(LatitudeFormatter())


def draw_terrain(ax, frame, style):
    cmap = copy.copy(plt.get_cmap(style['terrain_cmap']))
    norm = mpl.colors.BoundaryNorm(style['terrain_levels'], ncolors=cmap.N)
    return ax.pcolormesh(frame['lon'], frame['lat'], frame['hgt'], shading='nearest', norm=norm, cmap=cmap,
                         transform=ccrs.PlateCarree(), zorder=0)


def draw_reflectivity(ax, frame, style):
    """Low-level reflectivity of the pixel file: the same function, threshold and alpha in every layout."""
    cmap = plt.get_cmap(style['dbz_cmap'])
    norm = mpl.colors.BoundaryNorm(style['dbz_levels'], ncolors=cmap.N)
    dbz = np.ma.masked_where(~(frame['dbz'] >= style['dbz_min']), frame['dbz'])
    return ax.pcolormesh(frame['lon'], frame['lat'], dbz, shading='nearest', norm=norm, cmap=cmap,
                         transform=ccrs.PlateCarree(), zorder=2, alpha=style['dbz_alpha'])


def coldpool_cmap(style):
    """Colormap of the cold pool anomaly: style['cp_cmap'] (name) restricted to style['cp_cmap_range']."""
    lo, hi = style['cp_cmap_range']
    return truncate_cmap(style['cp_cmap'], lo, hi)


def draw_coldpool(ax, frame, style):
    cmap = coldpool_cmap(style)
    norm = mpl.colors.BoundaryNorm(style['cp_levels'], ncolors=cmap.N, extend='min')
    anom = np.ma.masked_where(~(frame['anom'] <= max(style['cp_levels'])), frame['anom'])
    return ax.pcolormesh(frame['lon'], frame['lat'], anom, shading='nearest', norm=norm, cmap=cmap,
                         transform=ccrs.PlateCarree(), zorder=1)


def draw_winds(ax, frame, style):
    s = max(1, int(round(style['vector_spacing_km'] * 1000. / DX)))
    o = s // 2
    sl = (slice(o, None, s), slice(o, None, s))
    q = ax.quiver(frame['lon'][sl], frame['lat'][sl], frame['U'][sl], frame['V'][sl], pivot='mid',
                  scale=style['vector_scale'], width=style['vector_width'], color=style['vector_color'],
                  transform=ccrs.PlateCarree(), zorder=6)
    kx, ky = style['quiverkey_xy']
    labelsep = 0.05    # inch between the arrow and its label
    qk = ax.quiverkey(q, kx, ky, style['quiverkey_speed'], f"{style['quiverkey_speed']} m/s", labelpos='S',
                      coordinates='axes', zorder=10, labelsep=labelsep, fontproperties={'size': style['fontsize']})
    if style['quiverkey_box']:
        draw_quiverkey_box(ax, qk, style, kx, ky, labelsep)
    return q


def draw_quiverkey_box(ax, qk, style, kx, ky, labelsep):
    """Filled box (axes coordinates) just behind the vector key, so that the key stands out from the map layers.
    The box fits the arrow (speed / vector_scale of the axes width) and the label, plus quiverkey_box_pad points."""
    ax.apply_aspect()
    fig = ax.figure
    w_ax, h_ax = ax.bbox.width, ax.bbox.height              # pixels
    ppi = fig.dpi
    pad = style['quiverkey_box_pad'] / 72. * ppi            # pixels
    arrow = style['quiverkey_speed'] / style['vector_scale'] * w_ax
    try:
        ext = qk.text.get_window_extent(fig.canvas.get_renderer())
        label_w, label_h = ext.width, ext.height
    except Exception:       # a backend without get_renderer: size from the font size (about 0.6 em per character)
        label_w = 0.6 * len(qk.text.get_text()) * style['fontsize'] / 72. * ppi
        label_h = 1.2 * style['fontsize'] / 72. * ppi
    half_w = max(arrow, label_w) / 2. + pad
    top = 3. * style['vector_width'] * w_ax / 2. + pad       # head width = 3 shaft widths (matplotlib default headwidth)
    bottom = labelsep * ppi + label_h + pad
    box = mpl.patches.Rectangle((kx - half_w / w_ax, ky - bottom / h_ax), 2. * half_w / w_ax, (top + bottom) / h_ax,
                                transform=ax.transAxes, facecolor=style['quiverkey_box_color'],
                                alpha=style['quiverkey_box_alpha'], edgecolor=style['quiverkey_box_edge'],
                                linewidth=0.6, zorder=9.5, clip_on=False)
    ax.add_patch(box)
    return box


def draw_rain_contours(ax, frame, style):
    return ax.contour(frame['lon'], frame['lat'], frame['rain'], levels=style['rain_levels'],
                      colors=style['rain_color'], linewidths=style['rain_lw'], transform=ccrs.PlateCarree(), zorder=7)


def draw_cells(ax, frame, track_dict, style, perim_alpha=None, tracks=True):
    """Cell perimeters, and (tracks=True) track paths / symbols with the lifetime colorbar, as in the cell tracking plots."""
    tproj = ccrs.PlateCarree()
    cellplot.draw_class_perimeter(ax, frame['lon'], frame['lat'], frame['tn_perim'], style['perim_color'],
                                  style['perim_alpha'] if perim_alpha is None else perim_alpha, 3, tproj)
    if tracks and style['show_tracks'] and track_dict is not None and track_dict['ntracks'] > 0:
        pixel_bt = np.datetime64(frame['time'])
        cmap_l = plt.get_cmap(style['cmap_tracks'])
        norm_l = mpl.colors.BoundaryNorm(style['lev_lifetime'], ncolors=cmap_l.N, clip=True)
        lifetime, cell_bt = track_dict['lifetime'], track_dict['cell_bt']
        cell_lon, cell_lat = track_dict['cell_lon'], track_dict['cell_lat']
        dt_thres, time_res = track_dict['dt_thres'], track_dict['time_res']
        lt, bt = lifetime.values, cell_bt.values
        for itrack in range(track_dict['ntracks']):
            ilife = lt[itrack]
            idur = int(ilife / time_res)
            ibt = bt[itrack, :idur]
            if idur == 0 or np.all(np.isnat(ibt)):
                continue
            if (pixel_bt - np.nanmax(ibt)).astype('timedelta64[m]') > np.timedelta64(int(dt_thres.total_seconds() // 60), 'm'):
                continue          # the track ended longer ago than the retain time
            idx = np.where(ibt <= pixel_bt)[0]
            if len(idx) == 0:
                continue
            k = 0 if ilife < 1 else (1 if ilife < 2 else 2)
            lons, lats = cell_lon.values[itrack, idx], cell_lat.values[itrack, idx]
            if style['show_paths']:
                ax.plot(lons, lats, lw=style['lw_centroid'][k], ls='-', color=style['cell_track_color'], transform=tproj, zorder=4)
            if style['show_symbols']:
                sizes = np.repeat(style['marker_size'][k], len(idx)).astype(float)
                sizes[0] *= 2
                ax.scatter(lons, lats, s=sizes, c=np.repeat(ilife, len(idx)), norm=norm_l, cmap=cmap_l,
                           edgecolor='k', marker='o', transform=tproj, zorder=5)
        if style['show_symbols']:
            cax = inset_axes(ax, width='100%', height='100%', bbox_to_anchor=(.04, .97, .3, .03), bbox_transform=ax.transAxes)
            cb = mpl.colorbar.ColorbarBase(cax, cmap=cmap_l, norm=norm_l, orientation='horizontal', label=style['cblabel_tracks'])
            cb.set_ticks(style['cbticks_tracks'])
    if style['show_cell_numbers']:
        for ii in range(len(frame['lon_tn'])):
            ax.text(frame['lon_tn'][ii], frame['lat_tn'][ii], f"{frame['tn_unique'][ii]:.0f}", color='k',
                    size=style['fontsize'] * 0.7, weight='bold', transform=ccrs.PlateCarree(), zorder=6)


# ------------------------------------------------------------------------
# version a: all elements in one panel
# ------------------------------------------------------------------------
def plot_single_panel(frame, track_dict, style, map_info, figname=None):
    """Cold pool anomaly, low-level reflectivity, cell perimeters and tracks, and 10 m winds in one panel."""
    fig, axs, caxs = new_figure('single', map_info, style)
    ax = axs[0]
    setup_map(ax, map_info, style)
    draw_terrain(ax, frame, style)
    pcm_cp = draw_coldpool(ax, frame, style)
    pcm_z = draw_reflectivity(ax, frame, style)
    draw_cells(ax, frame, track_dict, style)
    draw_winds(ax, frame, style)
    # Colorbars: cold pool, reflectivity
    fig.colorbar(pcm_cp, cax=caxs[0], ticks=style['cp_levels'], extend='min', label=style['cp_label'])
    fig.colorbar(pcm_z, cax=caxs[1], ticks=style['dbz_levels'][::2], extend='both', label=style['dbz_label'])
    ax.set_title(f"{style['title_prefix']} | {frame['timestr']}")
    if figname:
        fig.savefig(figname)
    return fig


# ------------------------------------------------------------------------
# version b: reflectivity + cells (left), cold pool + winds + rain contours (right)
# ------------------------------------------------------------------------
def plot_two_panel(frame, track_dict, style, map_info, figname=None):
    """Left: low-level reflectivity, cell perimeters and tracks. Right: cold pool anomaly, 10 m winds, rain rate contours."""
    fig, axs, caxs = new_figure('two', map_info, style)
    axl, axr = axs
    setup_map(axl, map_info, style, left_labels=True)
    setup_map(axr, map_info, style, left_labels=False)
    # Left
    draw_terrain(axl, frame, style)
    pcm_z = draw_reflectivity(axl, frame, style)
    draw_cells(axl, frame, track_dict, style)
    fig.colorbar(pcm_z, cax=caxs[0], ticks=style['dbz_levels'][::2], extend='both', label=style['dbz_label'])
    axl.set_title('Low-level reflectivity, cell perimeters and tracks', loc='left')
    # Right
    draw_terrain(axr, frame, style)
    pcm_cp = draw_coldpool(axr, frame, style)
    draw_cells(axr, frame, track_dict, style, perim_alpha=0.4, tracks=False)
    draw_winds(axr, frame, style)
    draw_rain_contours(axr, frame, style)
    fig.colorbar(pcm_cp, cax=caxs[1], ticks=style['cp_levels'], extend='min', label=style['cp_label'])
    rl = ', '.join(f'{v:g}' for v in style['rain_levels'])
    axr.set_title(f"Cold pool, 10 m wind, rain > {rl} mm/h (red)", loc='left')
    fig.suptitle(f"{style['title_prefix']} | {frame['timestr']}", fontweight='bold')
    if figname:
        fig.savefig(figname)
    return fig
