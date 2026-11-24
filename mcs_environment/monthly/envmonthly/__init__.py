"""Monthly-mean environment fields (prw, hus850, hur500, wap500, ps) of ERA5 and the SCREAM / E3SM runs on a common 1 degree grid.

Modules: ``config`` (dataset configuration), ``timeaxis`` (months and time axes), ``readers`` (input layouts), ``vertical`` (interpolation to a
pressure level), ``writer`` (compressed netCDF output), ``native`` (step 1), ``regrid`` (step 2), ``climo`` (step 3), ``ncotools`` (NCO / ESMF).
The command-line scripts are in the parent folder (``make_weights.py``, ``make_monthly_native.py``, ``regrid_monthly.py``,
``calc_env_climo.py``, ``check_env_monthly.py``); see ``../README.md``.
"""

__version__ = "1.0.0"
