#+
# Name:
#		GRIDRAD Python Module
# Purpose:
#		This module contains three functions for dealing with Gridded NEXRAD WSR-88D Radar
#		(GridRad) data: reading (read_file), filtering (filter), and decluttering (remove_clutter).
# Author and history:
#		Cameron R. Homeyer  2017-07-03.
#                         2021-02-23. Updated to be compatible with v4.2 GridRad data and v3 Python.
# Warning:
#		The authors' primary coding language is not Python. This code works, but may not be
#      the most efficient or proper approach. Please suggest improvements by sending an email
#		 to chomeyer@ou.edu.
#-

# Import python libraries
import os
import numpy as np
from netCDF4 import Dataset
from scipy import ndimage

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
	
	# Read global attributes
	Analysis_time           = str(id.getncattr('Analysis_time'          ))
	Analysis_time_window    = str(id.getncattr('Analysis_time_window'   ))
	File_creation_date      = str(id.getncattr('File_creation_date'     ))
	Grid_scheme             = str(id.getncattr('Grid_scheme'            ))
	Algorithm_version       = str(id.getncattr('Algorithm_version'      ))
	Algorithm_description   = str(id.getncattr('Algorithm_description'  ))
	Authors                 = str(id.getncattr('Authors'                ))
	Project_sponsor         = str(id.getncattr('Project_sponsor'        ))
	Project_name            = str(id.getncattr('Project_name'           ))
	
	# Read list of merged radar sweeps
	sweeps_list   = (id.variables['sweeps_merged'])[:]
	sweeps_merged = ['']*(id.dimensions['Sweep'].size)
	for i in range(0,id.dimensions['Sweep'].size):
		for j in range(0,id.dimensions['SweepRef'].size):
			sweeps_merged[i] += str(sweeps_list[i,j])
	
	# Read longitude dimension
	x = id.variables['Longitude']
	x = {'values'    : x[:],             \
		  'long_name' : str(x.long_name), \
		  'units'     : str(x.units),     \
		  'delta'     : str(x.delta),     \
		  'n'         : len(x[:])}
	
	# Read latitude dimension
	y = id.variables['Latitude']
	y = {'values'    : y[:],             \
		  'long_name' : str(y.long_name), \
		  'units'     : str(y.units),     \
		  'delta'     : str(y.delta),     \
		  'n'         : len(y[:])}
	
	# Read altitude dimension
	z = id.variables['Altitude']
	z = {'values'    : z[:],             \
		  'long_name' : str(z.long_name), \
		  'units'     : str(z.units),     \
		  'delta'     : str(z.delta),     \
		  'n'         : len(z[:])}
	
	# Read observation and echo counts
	nobs  = (id.variables['Nradobs' ])[:]
	necho = (id.variables['Nradecho'])[:]
	index = (id.variables['index'   ])[:]
	
	# Read reflectivity at horizontal polarization	
	Z_H  = id.variables['Reflectivity' ]
	wZ_H = id.variables['wReflectivity']
	
	# Create arrays to store binned values for reflectivity at horizontal polarization
	values    = np.zeros(x['n']*y['n']*z['n'])
	wvalues   = np.zeros(x['n']*y['n']*z['n'])
	values[:] = np.nan

	# Add values to arrays
	values[index[:]]  =  (Z_H)[:]
	wvalues[index[:]] = (wZ_H)[:]
	
	# Reshape arrays to 3-D GridRad domain
	values  =  values.reshape((z['n'], y['n'] ,x['n']))
	wvalues = wvalues.reshape((z['n'], y['n'] ,x['n']))

	Z_H = {'values'     : values,              \
			 'long_name'  : str(Z_H.long_name),  \
			 'units'      : str(Z_H.units),      \
			 'missing'    : np.nan,        \
			 'wvalues'    : wvalues,             \
			 'wlong_name' : str(wZ_H.long_name), \
			 'wunits'     : str(wZ_H.units),     \
			 'wmissing'   : wZ_H.missing_value,  \
			 'n'          : values.size}

	# Read velocity spectrum width	
	SW  = id.variables['SpectrumWidth' ]
	wSW = id.variables['wSpectrumWidth']

	# Create arrays to store binned values for velocity spectrum width
	values    = np.zeros(x['n']*y['n']*z['n'])
	wvalues   = np.zeros(x['n']*y['n']*z['n'])
	values[:] = np.nan

	# Add values to arrays
	values[index[:]]  =  (SW)[:]
	wvalues[index[:]] = (wSW)[:]
	
	# Reshape arrays to 3-D GridRad domain
	values  =  values.reshape((z['n'], y['n'] ,x['n']))
	wvalues = wvalues.reshape((z['n'], y['n'] ,x['n']))

	SW  = {'values'     : values,             \
			 'long_name'  : str(SW.long_name),  \
			 'units'      : str(SW.units),      \
			 'missing'    : np.nan,       \
			 'wvalues'    : wvalues,            \
			 'wlong_name' : str(wSW.long_name), \
			 'wunits'     : str(wSW.units),     \
			 'wmissing'   : wSW.missing_value,  \
			 'n'          : values.size}

	if ('AzShear' in id.variables):
		# Read azimuthal shear	
		AzShr  = id.variables['AzShear' ]
		wAzShr = id.variables['wAzShear']

		# Create arrays to store binned values for azimuthal shear
		values    = np.zeros(x['n']*y['n']*z['n'])
		wvalues   = np.zeros(x['n']*y['n']*z['n'])
		values[:] = np.nan

		# Add values to arrays
		values[index[:]]  =  (AzShr)[:]
		wvalues[index[:]] = (wAzShr)[:]
	
		# Reshape arrays to 3-D GridRad domain
		values  =  values.reshape((z['n'], y['n'] ,x['n']))
		wvalues = wvalues.reshape((z['n'], y['n'] ,x['n']))

		AzShr = {'values'     : values,                \
				   'long_name'  : str(AzShr.long_name),  \
				   'units'      : str(AzShr.units),      \
				   'missing'    : np.nan,          \
				   'wvalues'    : wvalues,               \
				   'wlong_name' : str(wAzShr.long_name), \
				   'wunits'     : str(wAzShr.units),     \
				   'wmissing'   : wAzShr.missing_value,  \
				   'n'          : values.size}

		# Read radial divergence	
		Div  = id.variables['Divergence' ]
		wDiv = id.variables['wDivergence']

		# Create arrays to store binned values for radial divergence
		values    = np.zeros(x['n']*y['n']*z['n'])
		wvalues   = np.zeros(x['n']*y['n']*z['n'])
		values[:] = np.nan

		# Add values to arrays
		values[index[:]]  =  (Div)[:]
		wvalues[index[:]] = (wDiv)[:]
	
		# Reshape arrays to 3-D GridRad domain
		values  =  values.reshape((z['n'], y['n'] ,x['n']))
		wvalues = wvalues.reshape((z['n'], y['n'] ,x['n']))

		Div = {'values'     : values,              \
				 'long_name'  : str(Div.long_name),  \
				 'units'      : str(Div.units),      \
				 'missing'    : np.nan,        \
				 'wvalues'    : wvalues,             \
				 'wlong_name' : str(wDiv.long_name), \
				 'wunits'     : str(wDiv.units),     \
				 'wmissing'   : wDiv.missing_value,  \
				 'n'          : values.size}	

	else:
		AzShr = -1
		Div   = -1


	if ('DifferentialReflectivity' in id.variables):
		# Read radial differential reflectivity	
		Z_DR  = id.variables['DifferentialReflectivity' ]
		wZ_DR = id.variables['wDifferentialReflectivity']
	
		# Create arrays to store binned values for differential reflectivity
		values    = np.zeros(x['n']*y['n']*z['n'])
		wvalues   = np.zeros(x['n']*y['n']*z['n'])
		values[:] = np.nan

		# Add values to arrays
		values[index[:]]  =  (Z_DR)[:]
		wvalues[index[:]] = (wZ_DR)[:]
	
		# Reshape arrays to 3-D GridRad domain
		values  =  values.reshape((z['n'], y['n'] ,x['n']))
		wvalues = wvalues.reshape((z['n'], y['n'] ,x['n']))

		Z_DR = {'values'     : values,               \
				  'long_name'  : str(Z_DR.long_name),  \
				  'units'      : str(Z_DR.units),      \
				  'missing'    : np.nan,         \
				  'wvalues'    : wvalues,              \
				  'wlong_name' : str(wZ_DR.long_name), \
				  'wunits'     : str(wZ_DR.units),     \
				  'wmissing'   : wZ_DR.missing_value,  \
				  'n'          : values.size}	

		# Read specific differential phase	
		K_DP  = id.variables['DifferentialPhase' ]
		wK_DP = id.variables['wDifferentialPhase']

		# Create arrays to store binned values for specific differential phase
		values    = np.zeros(x['n']*y['n']*z['n'])
		wvalues   = np.zeros(x['n']*y['n']*z['n'])
		values[:] = np.nan

		# Add values to arrays
		values[index[:]]  =  (K_DP)[:]
		wvalues[index[:]] = (wK_DP)[:]
	
		# Reshape arrays to 3-D GridRad domain
		values  =  values.reshape((z['n'], y['n'] ,x['n']))
		wvalues = wvalues.reshape((z['n'], y['n'] ,x['n']))

		K_DP = {'values'     : values,               \
				  'long_name'  : str(K_DP.long_name),  \
				  'units'      : str(K_DP.units),      \
				  'missing'    : np.nan,         \
				  'wvalues'    : wvalues,              \
				  'wlong_name' : str(wK_DP.long_name), \
				  'wunits'     : str(wK_DP.units),     \
				  'wmissing'   : wK_DP.missing_value,  \
				  'n'          : values.size}	

		# Read correlation coefficient	
		r_HV  = id.variables['CorrelationCoefficient' ]
		wr_HV = id.variables['wCorrelationCoefficient']
	
		# Create arrays to store binned values for correlation coefficient
		values    = np.zeros(x['n']*y['n']*z['n'])
		wvalues   = np.zeros(x['n']*y['n']*z['n'])
		values[:] = np.nan

		# Add values to arrays
		values[index[:]]  =  (r_HV)[:]
		wvalues[index[:]] = (wr_HV)[:]
	
		# Reshape arrays to 3-D GridRad domain
		values  =  values.reshape((z['n'], y['n'] ,x['n']))
		wvalues = wvalues.reshape((z['n'], y['n'] ,x['n']))

		r_HV = {'values'     : values,               \
				  'long_name'  : str(r_HV.long_name),  \
				  'units'      : str(r_HV.units),      \
				  'missing'    : np.nan,         \
				  'wvalues'    : wvalues,              \
				  'wlong_name' : str(wr_HV.long_name), \
				  'wunits'     : str(wr_HV.units),     \
				  'wmissing'   : wr_HV.missing_value,  \
				  'n'          : values.size}	

	else:
		Z_DR = -1
		K_DP = -1
		r_HV = -1
	
	# Close netCDF4 file
	id.close()
	
	# Return data dictionary	
	return {'name'                    : 'GridRad analysis for ' + Analysis_time, \
			  'x'                       : x, \
			  'y'                       : y, \
			  'z'                       : z, \
			  'Z_H'                     : Z_H, \
			  'SW'                      : SW, \
			  'AzShr'                   : AzShr, \
			  'Div'                     : Div, \
			  'Z_DR'                    : Z_DR, \
			  'K_DP'                    : K_DP, \
			  'r_HV'                    : r_HV, \
			  'nobs'                    : nobs, \
			  'necho'                   : necho, \
			  'file'                    : infile, \
			  'sweeps_merged'           : sweeps_merged, \
			  'Analysis_time'           : Analysis_time, \
			  'Analysis_time_window'    : Analysis_time_window, \
			  'File_creation_date'      : File_creation_date, \
			  'Grid_scheme'             : Grid_scheme, \
			  'Algorithm_version'       : Algorithm_version, \
			  'Algorithm_description'   : Algorithm_description, \
			  'Authors'                 : Authors, \
			  'Project_sponsor'         : Project_sponsor, \
			  'Project_name'            : Project_name}


# GridRad filter routine
def filter(data0):
	
	# Extract year from GridRad analysis time string
	year = int((data0['Analysis_time'])[0:4])

	# Set filtering thresholds
	wthresh = 1.5      # Bin weight threshold (dimensionless)
	freq_thresh = 0.6  # Echo frequency threshold (dimensionless)
	Z_H_thresh = 15.0  # Reflectivity threshold (dBZ)
	nobs_thresh = 2    # Number of observations threshold
	
	# Extract dimension sizes
	nx = (data0['x'])['n']
	ny = (data0['y'])['n']
	nz = (data0['z'])['n']
	
	# Create array to compute frequency of radar obs in grid volume with echo
	echo_frequency = np.zeros((nz, ny, nx))
	
	# Find bins with observations and compute echo frequency
	ipos = np.where(data0['nobs'] > 0)
	npos = len(ipos[0])
	if npos > 0:
		# Compute echo frequency (number of scans with echo / total scans)
		echo_frequency[ipos] = data0['necho'][ipos] / data0['nobs'][ipos]
	
	# Temporarily replace NaNs with zeros for filtering
	inan = np.where(np.isnan((data0['Z_H'])['values']))
	nnan = len(inan[0])
	if nnan > 0:
		((data0['Z_H'])['values'])[inan] = 0.0
	
	# Find observations with low weight or low echo frequency
	ifilter = np.where(
		(((data0['Z_H'])['wvalues'] < wthresh) & ((data0['Z_H'])['values'] < Z_H_thresh)) |
		((echo_frequency < freq_thresh) & (data0['nobs'] > nobs_thresh))
	)
	nfilter = len(ifilter[0])
	
	# Remove low confidence observations
	if nfilter > 0:
		((data0['Z_H'])['values'])[ifilter] = np.nan
		((data0['SW'])['values'])[ifilter] = np.nan
		
		if type(data0['AzShr']) is dict:
			((data0['AzShr'])['values'])[ifilter] = np.nan
			((data0['Div'])['values'])[ifilter] = np.nan
		
		if type(data0['Z_DR']) is dict:
			((data0['Z_DR'])['values'])[ifilter] = np.nan
			((data0['K_DP'])['values'])[ifilter] = np.nan
			((data0['r_HV'])['values'])[ifilter] = np.nan
	
	# Restore NaN values that were temporarily replaced
	if nnan > 0:
		((data0['Z_H'])['values'])[inan] = np.nan
	
	# Return filtered data0
	return data0

	
def remove_clutter(data0, skip_weak_ll_echo=False):
	"""
	Remove ground clutter and biological scatterers from GridRad data.
	
	Parameters:
	-----------
	data0 : dict
		GridRad data dictionary
	skip_weak_ll_echo : bool
		If False, remove weak low-level echo; if True, skip this step
	"""
	
	# Set fractional areal coverage threshold for speckle identification
	areal_coverage_thresh = 0.32
	
	# Extract dimension sizes
	nx = (data0['x'])['n']
	ny = (data0['y'])['n']
	nz = (data0['z'])['n']
	
	# Get references to key arrays
	zh_values = (data0['Z_H'])['values']
	z_values = (data0['z'])['values']
	
	# Helper function to apply mask to all variables
	def apply_mask_to_all(mask):
		"""Apply NaN mask to all radar variables."""
		if np.any(mask):
			((data0['Z_H'])['values'])[mask] = np.nan
			((data0['SW'])['values'])[mask] = np.nan
			
			if type(data0['AzShr']) is dict:
				((data0['AzShr'])['values'])[mask] = np.nan
				((data0['Div'])['values'])[mask] = np.nan
			
			if type(data0['Z_DR']) is dict:
				((data0['Z_DR'])['values'])[mask] = np.nan
				((data0['K_DP'])['values'])[mask] = np.nan
				((data0['r_HV'])['values'])[mask] = np.nan
	
	def remove_speckles(threshold=areal_coverage_thresh):
		"""Use uniform filter for efficient neighbor counting."""
		fin = np.isfinite(zh_values)
		# Use uniform filter (5x5 kernel in horizontal, no vertical smoothing)
		cover = ndimage.uniform_filter(fin.astype(np.float32), size=(1, 5, 5), mode='wrap')
		apply_mask_to_all(cover <= threshold)
	
	# Apply correlation coefficient filtering (if dual-pol data available)
	if type(data0['Z_DR']) is dict:
		# Use broadcasting to avoid creating full 3D array
		z_broadcast = z_values.reshape(nz, 1, 1)
		corr_mask = (
			((zh_values < 40.0) & ((data0['r_HV'])['values'] < 0.9)) |
			((zh_values < 25.0) & ((data0['r_HV'])['values'] < 0.95) & (z_broadcast >= 10.0))
		)
		apply_mask_to_all(corr_mask)
	
	# First pass at removing speckles
	remove_speckles(areal_coverage_thresh)


	# Attempts to mitigate ground clutter and biological scatterers
	if not skip_weak_ll_echo:
		# Create z_broadcast for height comparisons (avoids creating large 3D array)
		z_broadcast = z_values.reshape(nz, 1, 1)
		
		# Temporarily replace NaNs with zeros for processing
		inan = np.where(np.isnan((data0['Z_H'])['values']))
		nnan = len(inan[0])
		if nnan > 0:
			((data0['Z_H'])['values'])[inan] = 0.0
		
		# Find and remove weak low-level echo (< 10 dBZ below 4 km)
		ibad = np.where(((data0['Z_H'])['values'] < 10.0) & (z_broadcast <= 4.0))
		nbad = len(ibad[0])
		if nbad > 0:
			((data0['Z_H'])['values'])[ibad] = np.nan
			((data0['SW'])['values'])[ibad] = np.nan
			
			if type(data0['AzShr']) is dict:
				((data0['AzShr'])['values'])[ibad] = np.nan
				((data0['Div'])['values'])[ibad] = np.nan
			
			if type(data0['Z_DR']) is dict:
				((data0['Z_DR'])['values'])[ibad] = np.nan
				((data0['K_DP'])['values'])[ibad] = np.nan
				((data0['r_HV'])['values'])[ibad] = np.nan
		
		# Restore NaN values
		if nnan > 0:
			((data0['Z_H'])['values'])[inan] = np.nan
		
		# Second pass: compute column statistics for shallow/weak echo detection
		inan = np.where(np.isnan((data0['Z_H'])['values']))
		nnan = len(inan[0])
		if nnan > 0:
			((data0['Z_H'])['values'])[inan] = 0.0
		
		# Compute column-maximum reflectivity and echo top heights
		refl_max = np.nanmax((data0['Z_H'])['values'], axis=0)
		echo0_max = np.nanmax(((data0['Z_H'])['values'] > 0.0) * z_broadcast, axis=0)
		echo0_min = np.nanmin(((data0['Z_H'])['values'] > 0.0) * z_broadcast, axis=0)
		echo5_max = np.nanmax(((data0['Z_H'])['values'] > 5.0) * z_broadcast, axis=0)
		echo15_max = np.nanmax(((data0['Z_H'])['values'] > 15.0) * z_broadcast, axis=0)
		
		# Restore NaN values
		if nnan > 0:
			((data0['Z_H'])['values'])[inan] = np.nan
		
		# Identify weak and/or shallow echo columns
		ibad = np.where(
			((refl_max < 20.0) & (echo0_max <= 4.0) & (echo0_min <= 3.0)) |
			((refl_max < 10.0) & (echo0_max <= 5.0) & (echo0_min <= 3.0)) |
			((echo5_max <= 5.0) & (echo5_max > 0.0) & (echo15_max <= 3.0)) |
			((echo15_max < 2.0) & (echo15_max > 0.0))
		)
		nbad = len(ibad[0])
		
		# Remove entire columns identified as weak/shallow
		if nbad > 0:
			kbad = np.zeros(nbad, dtype=int)
			for k in range(nz):
				((data0['Z_H'])['values'])[(k + kbad), ibad[0], ibad[1]] = np.nan
				((data0['SW'])['values'])[(k + kbad), ibad[0], ibad[1]] = np.nan
				
				if type(data0['AzShr']) is dict:
					((data0['AzShr'])['values'])[(k + kbad), ibad[0], ibad[1]] = np.nan
					((data0['Div'])['values'])[(k + kbad), ibad[0], ibad[1]] = np.nan
				
				if type(data0['Z_DR']) is dict:
					((data0['Z_DR'])['values'])[(k + kbad), ibad[0], ibad[1]] = np.nan
					((data0['K_DP'])['values'])[(k + kbad), ibad[0], ibad[1]] = np.nan
					((data0['r_HV'])['values'])[(k + kbad), ibad[0], ibad[1]] = np.nan
	
	# Detect and remove clutter below convective anvils
	k4km = np.argmax(z_values >= 4.0)
	fin = np.isfinite(zh_values)
	
	# Find columns with gap at 4km but echo above and below (indicates low-level clutter)
	bad_columns = (
		~fin[k4km, :, :] & 
		(np.sum(fin[k4km:nz, :, :], axis=0) > 0) & 
		(np.sum(fin[0:k4km, :, :], axis=0) > 0)
	)
	
	# Remove low-level clutter in these columns (vectorized)
	if np.any(bad_columns):
		((data0['Z_H'])['values'])[:k4km + 1, bad_columns] = np.nan
		((data0['SW'])['values'])[:k4km + 1, bad_columns] = np.nan
		
		if type(data0['AzShr']) is dict:
			((data0['AzShr'])['values'])[:k4km + 1, bad_columns] = np.nan
			((data0['Div'])['values'])[:k4km + 1, bad_columns] = np.nan
		
		if type(data0['Z_DR']) is dict:
			((data0['Z_DR'])['values'])[:k4km + 1, bad_columns] = np.nan
			((data0['K_DP'])['values'])[:k4km + 1, bad_columns] = np.nan
			((data0['r_HV'])['values'])[:k4km + 1, bad_columns] = np.nan
	
	# Second pass at removing speckles
	remove_speckles(areal_coverage_thresh)
	
	return data0

# GridRad sample image plotting routine
def plot_image(data):
	
	# Import python libraries
	import sys
	import os
	import numpy as np
	import matplotlib.pyplot as plt

	# Extract dimensions and their sizes
	x  = (data['x'])['values']
	y  = (data['y'])['values']
	nx = (data['x'])['n']
	ny = (data['y'])['n']
	
	r = [ 49, 30, 15,150, 78, 15,255,217,255,198,255,109,255,255,255]		# RGB color values
	g = [239,141, 56,220,186, 97,222,164,107, 59,  0,  0,  0,171,255]
	b = [237,192,151,150, 25,  3,  0,  0,  0,  0,  0,  0,255,255,255]
	
	refl_max = np.nanmax((data['Z_H'])['values'], axis=0)						# Column-maximum reflectivity
 	
	img    = np.zeros((ny,nx,3))														# Create image for plotting
	img[:] = 200.0/255.0																	# Set default color to gray
	
	ifin = np.where(np.isfinite(refl_max))											# Find finite values
	nfin = len(ifin[0])																	# Count number of finite values
	
	for i in range(0,nfin):
		img[(ifin[0])[i],(ifin[1])[i],:] = (r[min(int(refl_max[(ifin[0])[i],(ifin[1])[i]]/5),14)]/255.0, \
														g[min(int(refl_max[(ifin[0])[i],(ifin[1])[i]]/5),14)]/255.0, \
														b[min(int(refl_max[(ifin[0])[i],(ifin[1])[i]]/5),14)]/255.0)
	
	imgplot = plt.imshow(img[::-1,:,:], extent = [x[0],x[nx-1],y[0],y[ny-1]])
	plt.savefig('gridrad_image.png')
	
