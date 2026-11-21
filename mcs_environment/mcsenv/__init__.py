"""mcsenv: environmental variables averaged in circles that follow MCS tracks (SCREAM, E3SM, ERA5).

For every MCS track the package extracts environment variables averaged inside circles of several diameters. The circle stays at the MCS start
location for the 24 h before the start and follows the MCS centroid afterwards. Rows sit on a nominal relative-time grid (offsets k * step from
the track start, the same for every track) and take the environment of the nearest available time.

Modules (one job each, see mcs_environment/README.md):

* ``config``    source definitions (paths, streams, variable names, units) read from ``config/sources.yaml``
* ``derive``    unit conversion, derived variables (q from RH, sums) and the below-ground mask
* ``grid``      circle search on any grid with a 3-D KD-tree and sparse area weights
* ``tracks``    MCS track files and the vectorised sample table (nominal times, track positions)
* ``fileindex`` which file and record holds which time (any file layout), cached
* ``readers``   one function per input layout (``ncol`` cubed-sphere, ``latlon``, ``latlon_level``)
* ``extract``   the parallel job: tasks, part files, assembly
* ``outputs``   Parquet writing and reading with units and attributes
"""

__version__ = "1.1.0"
