import os
import numpy as np
# import xarray as xr
# from matplotlib import cm
# import ESMF
# import pyproj
from netCDF4 import Dataset, chartostring, Variable
# import datetime
# import calendar
# import pytz
# import time
# import ipyparallel as ipp
# import glob
# import sys
# import netCDF4

# GridRad read routine


def read_file(infile):
    # Check to see if file exists
    if not os.path.isfile(infile):
        print('File "' + infile + '" does not exist.  Returning -2.')
        return -2

    # Check to see if file has size of zero
    if os.stat(infile).st_size == 0:
        print('File "' + infile + '" contains no valid data.  Returning -1.')
        return -1

    # Open GridRad netCDF file
    id = Dataset(infile, "r", format="NETCDF4")

    # Read global attributes (with defaults for missing attributes)
    def get_attr_safe(nc_obj, attr_name, default=''):
        """Safely get attribute, return default if not found."""
        try:
            return str(nc_obj.getncattr(attr_name))
        except AttributeError:
            return default
    
    Analysis_time = get_attr_safe(id, 'Analysis_time')
    Analysis_time_window = get_attr_safe(id, 'Analysis_time_window')
    File_creation_date = get_attr_safe(id, 'File_creation_date')
    Grid_scheme = get_attr_safe(id, 'Grid_scheme')
    Algorithm_version = get_attr_safe(id, 'Algorithm_version')
    Algorithm_description = get_attr_safe(id, 'Algorithm_description')
    Data_source = get_attr_safe(id, 'Data_source')
    Data_source_URL = get_attr_safe(id, 'Data_source_URL')
    NOAA_wct_export_Version = get_attr_safe(id, 'NOAA_wct-export_Version')
    Authors = get_attr_safe(id, 'Authors')
    Project_sponsor = get_attr_safe(id, 'Project_sponsor')
    Project_name = get_attr_safe(id, 'Project_name')

    # Read list of merged files (if available)
    try:
        file_list = (id.variables['files_merged'])[:]
        files_merged = [''] * (id.dimensions['File'].size - 1)
        for i in range(0, id.dimensions['File'].size - 1):
            for j in range(0, id.dimensions['FileRef'].size - 1):
                files_merged[i] += str(file_list[i, j])
    except (KeyError, IndexError):
        files_merged = []

    # Read longitude dimension
    x = id.variables['Longitude']
    x = {'values': x[:],
         'long_name': str(x.long_name),
         'units': str(x.units),
         'delta': str(x.delta),
         'n': len(x[:])}

    # Read latitude dimension
    y = id.variables['Latitude']
    y = {'values': y[:],
         'long_name': str(y.long_name),
         'units': str(y.units),
         'delta': str(y.delta),
         'n': len(y[:])}

    # Read altitude dimension
    z = id.variables['Altitude']
    z = {'values': z[:],
         'long_name': str(z.long_name),
         'units': str(z.units),
         'delta': str(z.delta),
         'n': len(z[:])}

    # Read observation and echo counts
    nobs = (id.variables['Nradobs'])[:]
    necho = (id.variables['Nradecho'])[:]
    index = (id.variables['index'])[:]

    # Read reflectivity variables
    Z_H = id.variables['Reflectivity']
    wZ_H = id.variables['wReflectivity']

    # Create arrays to store binned values
    values = np.zeros(x['n'] * y['n'] * z['n'])
    wvalues = np.zeros(x['n'] * y['n'] * z['n'])
    values[:] = float('nan')

    # Add values to arrays
    values[index[:]] = (Z_H)[:]
    wvalues[index[:]] = (wZ_H)[:]

    # Reshape arrays to 3-D GridRad domain
    values = values.reshape((z['n'], y['n'], x['n']))
    wvalues = wvalues.reshape((z['n'], y['n'], x['n']))

    Z_H = {'values': values,
           'long_name': str(Z_H.long_name),
           'units': str(Z_H.units),
           'missing': float('nan'),
           'wvalues': wvalues,
           'wlong_name': str(wZ_H.long_name),
           'wunits': str(wZ_H.units),
           'wmissing': wZ_H.missing_value,
           'n': values.size}

    # Close netCDF4 file
    id.close()

    # Return data dictionary
    return {'name': 'GridRad analysis for ' + Analysis_time,
            'x': x,
            'y': y,
            'z': z,
            'Z_H': Z_H,
            'nobs': nobs,
            'necho': necho,
            'file': infile,
            'files_merged': files_merged,
            'Analysis_time': Analysis_time,
            'Analysis_time_window': Analysis_time_window,
            'File_creation_date': File_creation_date,
            'Grid_scheme': Grid_scheme,
            'Algorithm_version': Algorithm_version,
            'Algorithm_description': Algorithm_description,
            'Data_source': Data_source,
            'Data_source_URL': Data_source_URL,
            'NOAA_wct_export_Version': NOAA_wct_export_Version,
            'Authors': Authors,
            'Project_sponsor': Project_sponsor,
            'Project_name': Project_name}


# GridRad filter routine
# Commented out - not needed for basic file reading
'''
def filter(data0):
    """
    Filter weak reflectivity with small weighting and not observed by multiple radars.
    """

    # Import python libraries
    import sys
    import os
    import numpy as np

    # Extract year from GridRad analysis time string
    year = int((data0['Analysis_time'])[0:4])

    # Set absolute minimum weight threshold for an observation (dimensionless)
    wmin = 0.1
    # Set default bin weight threshold for filtering by year (dimensionless)
    wthresh = 1.33 - 1.0 * (year < 2009)
    # Set echo frequency threshold (dimensionless)
    freq_thresh = 0.6
    Z_H_thresh = 18.5                       # Reflectivity threshold (dBZ)
    nobs_thresh = 2                          # Number of observations threshold

    # Extract dimension sizes
    nx = (data0['x'])['n']
    ny = (data0['y'])['n']
    nz = (data0['z'])['n']

    # Create array to compute frequency of radar obs in grid volume with echo
    echo_frequency = np.zeros((nz, ny, nx))

    ipos = np.where(data0['nobs'] > 0)        # Find bins with obs
    npos = len(ipos[0])                       # Count number of bins with obs

    if (npos > 0):
        # Compute echo frequency (number of scans with echo out of total number of scans)
        echo_frequency[ipos] = (data0['necho'])[ipos] / (data0['nobs'])[ipos]

    # Find bins with NaNs
    inan = np.where(np.isnan((data0['Z_H'])['values']))
    # Count number of bins with NaNs
    nnan = len(inan[0])

    if (nnan > 0):
        ((data0['Z_H'])['values'])[inan] = 0.0

    # Find observations with low weight
    ifilter = np.where(((data0['Z_H'])['wvalues'] < wmin) |
                       (((data0['Z_H'])['wvalues'] < wthresh) & ((data0['Z_H'])['values'] <= Z_H_thresh)) |
                       ((echo_frequency < freq_thresh) & (data0['nobs'] > nobs_thresh)))

    nfilter = len(ifilter[0])   # Count number of bins that need to be removed

    # Remove low confidence observations
    if (nfilter > 0):
        ((data0['Z_H'])['values'])[ifilter] = float('nan')

    # Replace NaNs that were previously removed
    if (nnan > 0):
        ((data0['Z_H'])['values'])[inan] = float('nan')

    # Return filtered data0
    return data0
'''

# Commented out - not needed for basic file reading
'''
def remove_clutter(data0, skip_weak_ll_echo=False, **kwargs):
    """
    Remove clutter filter
    """

    # Set defaults for optional parameters
    #   if ('skip_weak_ll_echo' not in kwargs): skip_weak_ll_echo = 0

    # Import python libraries
    import sys
    import os
    import numpy as np

    # Set fractional areal coverage threshold for speckle identification
    areal_coverage_thresh = 0.32

    # Extract dimension sizes
    nx = (data0['x'])['n']
    ny = (data0['y'])['n']
    nz = (data0['z'])['n']

    # Copy altitude array to 3 dimensions
    zzz = ((((data0['z'])['values']).reshape(nz, 1, 1)
            ).repeat(ny, axis=1)).repeat(nx, axis=2)

    # First pass at removing speckles
    fin = np.isfinite((data0['Z_H'])['values'])

    # Compute fraction of neighboring points with echo
    cover = np.zeros((nz, ny, nx))
    for i in range(-2, 2):
        for j in range(-2, 2):
            cover += np.roll(np.roll(fin, i, axis=2), j, axis=1)
    cover = cover / 25.0

    # Find bins with low nearby areal echo coverage (i.e., speckles) and remove (set to NaN).
    ibad = np.where(cover <= areal_coverage_thresh)
    nbad = len(ibad[0])
    if (nbad > 0):
        ((data0['Z_H'])['values'])[ibad] = float('nan')

    # Attempts to mitigate ground clutter and biological scatterers
    #         if (skip_weak_ll_echo == 0):
    if (skip_weak_ll_echo == False):
            # First check for weak, low-level echo
        # Find bins with NaNs
        inan = np.where(np.isnan((data0['Z_H'])['values']))
        # Count number of bins with NaNs
        nnan = len(inan[0])

        if (nnan > 0):
            ((data0['Z_H'])['values'])[inan] = 0.0

        # Find weak low-level echo and remove (set to NaN)
        ibad = np.where(((data0['Z_H'])['values'] < 10.0) & (zzz <= 4.0))
        nbad = len(ibad[0])
        if (nbad > 0):
            ((data0['Z_H'])['values'])[ibad] = float('nan')

        # Replace NaNs that were removed
        if (nnan > 0):
            ((data0['Z_H'])['values'])[inan] = float('nan')

        # Second check for weak, low-level echo
        # Find bins with NaNs
        inan = np.where(np.isnan((data0['Z_H'])['values']))
        # Count number of bins with NaNs
        nnan = len(inan[0])

        if (nnan > 0):
            ((data0['Z_H'])['values'])[inan] = 0.0

        refl_max = np.nanmax((data0['Z_H'])['values'],             axis=0)
        echo0_max = np.nanmax(((data0['Z_H'])['values'] > 0.0) * zzz, axis=0)
        echo0_min = np.nanmin(((data0['Z_H'])['values'] > 0.0) * zzz, axis=0)
        echo5_max = np.nanmax(((data0['Z_H'])['values'] > 5.0) * zzz, axis=0)
        echo15_max = np.nanmax(((data0['Z_H'])['values'] > 15.0) * zzz, axis=0)

        # Replace NaNs that were removed
        if (nnan > 0):
            ((data0['Z_H'])['values'])[inan] = float('nan')

        # Second check for weak, low-level echo
        # Find bins with NaNs
        inan = np.where(np.isnan((data0['Z_H'])['values']))
        # Count number of bins with NaNs
        nnan = len(inan[0])

        if (nnan > 0):
            ((data0['Z_H'])['values'])[inan] = 0.0

        refl_max = np.nanmax((data0['Z_H'])['values'],             axis=0)
        echo0_max = np.nanmax(((data0['Z_H'])['values'] > 0.0) * zzz, axis=0)
        echo0_min = np.nanmin(((data0['Z_H'])['values'] > 0.0) * zzz, axis=0)
        echo5_max = np.nanmax(((data0['Z_H'])['values'] > 5.0) * zzz, axis=0)
        echo15_max = np.nanmax(((data0['Z_H'])['values'] > 15.0) * zzz, axis=0)

        # Replace NaNs that were removed
        if (nnan > 0):
            ((data0['Z_H'])['values'])[inan] = float('nan')

        # Find weak and/or shallow echo
        ibad = np.where(((refl_max < 20.0) & (echo0_max <= 4.0) & (echo0_min <= 3.0)) |
                        ((refl_max < 10.0) & (echo0_max <= 5.0) & (echo0_min <= 3.0)) |
                        ((echo5_max <= 5.0) & (echo5_max > 0.0) & (echo15_max <= 3.0)) |
                        ((echo15_max < 2.0) & (echo15_max > 0.0)))
        nbad = len(ibad[0])
        if (nbad > 0):
            kbad = (np.zeros((nbad))).astype(int)
            for k in range(0, nz - 1):
                ((data0['Z_H'])['values'])[
                    (k + kbad), ibad[0], ibad[1]] = float('nan')

    # Find clutter below convective anvils
    k4km = ((np.where((data0['z'])['values'] >= 4.0))[0])[0]
    fin = np.isfinite((data0['Z_H'])['values'])
    ibad = np.where((fin[k4km, :, :] == 0) &
                    (np.sum(fin[k4km:(nz - 1), :, :], axis=0) > 0) &
                    (np.sum(fin[0:(k4km - 1), :, :], axis=0) > 0))
    nbad = len(ibad[0])
    if (nbad > 0):
        kbad = (np.zeros((nbad))).astype(int)
        for k in range(0, k4km):
            ((data0['Z_H'])['values'])[
                (k + kbad), ibad[0], ibad[1]] = float('nan')

    # Second pass at removing speckles
    fin = np.isfinite((data0['Z_H'])['values'])

    # Compute fraction of neighboring points with echo
    cover = np.zeros((nz, ny, nx))
    for i in range(-2, 2):
        for j in range(-2, 2):
            cover += np.roll(np.roll(fin, i, axis=2), j, axis=1)
    cover = cover / 25.0

    # Find bins with low nearby areal echo coverage (i.e., speckles) and remove (set to NaN).
    ibad = np.where(cover <= areal_coverage_thresh)
    nbad = len(ibad[0])
    if (nbad > 0):
        ((data0['Z_H'])['values'])[ibad] = float('nan')

    return data0
'''

# Commented out - not needed for basic file reading
'''
def get_source_lonlat(source_file):
    
    data = read_file(source_file)
    # nobs = data['nobs']
    lon = data['x']['values'] - 360.
    lat = data['y']['values']
    # Great 2D lat/lon
    src_lon, src_lat = np.meshgrid(lon, lat)
    return (src_lon, src_lat)
'''  # End of all commented out functions (filter, remove_clutter, get_source_lonlat, process_file, etc.)

# Note: All other functions (init_grids, write_output_file) and the main section 
# have been removed as they are not needed for remap_gridrad_to_hrrr.py
# Only the read_file() function is required.
