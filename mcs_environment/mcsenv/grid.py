"""Circle search on any grid: one 3-D KD-tree per grid and a batched sparse distance matrix per time step.

A grid is a list of cell centres (latitude, longitude in degrees) with an optional cell area. The centres are converted to 3-D unit vectors, so the
search is identical for a cubed-sphere grid (ne30pg2, ne120pg2, ne1024pg2), a regular lat-lon grid (ERA5), HEALPix or any unstructured grid, and it
needs no special case for the poles, the dateline (also for unwrapped longitudes such as 207 degrees) or the cube edges.

For all circles of one time step (all MCS samples that use the same environment snapshot) ``cKDTree.sparse_distance_matrix`` returns every
(circle, cell) pair within the largest radius in one call; the smaller diameters are thresholds on the same distances. The result for each diameter
is a sparse weight matrix (circles x cells) whose entries are the cell areas, so that area-weighted means with masked (NaN) cells are two sparse
matrix products (``weighted_mean``). A circle that contains no cell centre either takes the nearest cell (default) or stays empty.
"""

from __future__ import annotations

import numpy as np
from scipy import sparse
from scipy.spatial import cKDTree

# Mean Earth radius used for the circle radius (km); the great-circle distance is distance_km / radius radians
EARTH_RADIUS_KM = 6371.0


def latlon_to_xyz(lat_deg, lon_deg):
    """3-D unit vectors of points given by latitude and longitude.

    Args:
        lat_deg: latitude in degrees (array or scalar).
        lon_deg: longitude in degrees, any range or unwrapped (array or scalar, same shape).

    Returns:
        array of shape (n, 3) with x, y, z on the unit sphere.
    """
    # Standard spherical to Cartesian conversion; the longitude only enters through sin and cos, so unwrapped values are fine
    lat = np.radians(np.atleast_1d(np.asarray(lat_deg, dtype=np.float64)))
    lon = np.radians(np.atleast_1d(np.asarray(lon_deg, dtype=np.float64)))
    cl = np.cos(lat)
    return np.stack([cl * np.cos(lon), cl * np.sin(lon), np.sin(lat)], axis=-1)


def chord_from_km(distance_km, earth_radius_km=EARTH_RADIUS_KM):
    """Straight-line (chord) distance on the unit sphere of a great-circle distance.

    Args:
        distance_km: great-circle distance in km.
        earth_radius_km: Earth radius in km (default 6371.0).

    Returns:
        chord length on the unit sphere, ``2 sin(theta / 2)`` with ``theta = distance / radius``.
    """
    return 2.0 * np.sin(np.asarray(distance_km, dtype=np.float64) / earth_radius_km / 2.0)


def haversine_km(lat1, lon1, lat2, lon2, earth_radius_km=EARTH_RADIUS_KM):
    """Great-circle distance in km between points (independent of the KD-tree; used by the tests and the validation).

    Args:
        lat1, lon1: first point(s) in degrees.
        lat2, lon2: second point(s) in degrees (broadcast against the first).
        earth_radius_km: Earth radius in km (default 6371.0).

    Returns:
        distance in km.
    """
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi, dlam = p2 - p1, np.radians(lon2) - np.radians(lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlam / 2) ** 2
    return 2 * earth_radius_km * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


class GridSearch:
    """Cell centres of one grid with a KD-tree, cell weights and the circle search.

    Args:
        lat_deg: latitude of the cell centres in degrees, shape (n_cells,).
        lon_deg: longitude of the cell centres in degrees (any convention), shape (n_cells,).
        area: cell areas or weights, shape (n_cells,), or None for equal weights. Only ratios matter (the SCREAM ``area`` is off by a constant).
        earth_radius_km: Earth radius in km used for the circle radius (default 6371.0).
    """

    def __init__(self, lat_deg, lon_deg, area=None, earth_radius_km=EARTH_RADIUS_KM):
        """Build the cell weights and the KD-tree of a grid (arguments: see the class docstring; raises ValueError for bad coordinates or areas)."""
        # Sanity check of the coordinates: a latitude outside +-90 degrees means radians were passed or the file is not what was expected
        lat = np.asarray(lat_deg, dtype=np.float64).ravel()
        lon = np.asarray(lon_deg, dtype=np.float64).ravel()
        if lat.size == 0 or lat.size != lon.size:
            raise ValueError("lat and lon must be non-empty and of equal length")
        if not (np.isfinite(lat).all() and np.isfinite(lon).all()) or np.abs(lat).max() > 90.0 + 1e-6:
            raise ValueError("cell centres must be finite with |lat| <= 90 degrees")
        # Cell weights: the given areas, or one for every cell
        if area is None:
            weights = np.ones(lat.size, dtype=np.float64)
        else:
            weights = np.asarray(area, dtype=np.float64).ravel()
            if weights.size != lat.size or not np.isfinite(weights).all() or (weights < 0).any():
                raise ValueError("area must be finite, non-negative and of the length of the grid")
        # The KD-tree on the unit sphere (built once per grid)
        self.lat, self.lon, self.weights = lat, lon, weights
        self.earth_radius_km = float(earth_radius_km)
        self.xyz = latlon_to_xyz(lat, lon)
        self.tree = cKDTree(self.xyz)

    @property
    def n_cells(self):
        """Number of cells of the grid."""
        return self.lat.size

    def circle_weights(self, lat_deg, lon_deg, diameters_km, empty_circle="nearest_cell"):
        """Sparse weight matrices of the circles of one time step, one per diameter.

        Args:
            lat_deg: latitude of the circle centres in degrees, shape (n,).
            lon_deg: longitude of the circle centres in degrees, shape (n,).
            diameters_km: circle diameters in km (list); a cell is inside when its centre is within diameter / 2 (great circle) of the centre.
            empty_circle: ``"nearest_cell"`` (default) gives a circle without any cell centre the nearest cell; ``"nan"`` leaves it empty.

        Returns:
            (matrices, n_cells): a list of ``scipy.sparse.csr_matrix`` of shape (n, n_grid_cells) with the cell area as entry for every cell inside
            the circle (one matrix per diameter), and an int32 array (n, n_diameters) with the number of cells in each circle.
        """
        # Step 1: circle centres as unit vectors and the chord length of every radius
        lat = np.atleast_1d(np.asarray(lat_deg, dtype=np.float64))
        lon = np.atleast_1d(np.asarray(lon_deg, dtype=np.float64))
        n, nd = lat.size, len(diameters_km)
        if n == 0:
            return [sparse.csr_matrix((0, self.n_cells)) for _ in diameters_km], np.zeros((0, nd), dtype=np.int32)
        centres = latlon_to_xyz(lat, lon)
        chords = [float(chord_from_km(d / 2.0, self.earth_radius_km)) for d in diameters_km]
        # Step 2: all (circle, cell) pairs within the largest radius in one dual-tree search; 'ndarray' keeps pairs at exactly zero distance
        pairs = cKDTree(centres).sparse_distance_matrix(self.tree, max(chords), output_type="ndarray")
        row, col, dist = pairs["i"], pairs["j"], pairs["v"]
        nearest = None
        matrices, n_cells = [], np.zeros((n, nd), dtype=np.int32)
        # Step 3: one weight matrix per diameter by thresholding the same distances
        for k, chord in enumerate(chords):
            inside = dist <= chord
            r, c = row[inside], col[inside]
            if empty_circle == "nearest_cell":
                # Circles without any cell centre take the nearest cell (the nearest-cell search is only run when needed)
                empty = np.flatnonzero(np.bincount(r, minlength=n) == 0)
                if empty.size:
                    if nearest is None:
                        nearest = self.tree.query(centres, k=1)[1]
                    r, c = np.concatenate([r, empty]), np.concatenate([c, nearest[empty]])
            n_cells[:, k] = np.bincount(r, minlength=n)
            matrices.append(sparse.csr_matrix((self.weights[c], (r, c)), shape=(n, self.n_cells)))
        return matrices, n_cells


def weighted_mean(weight_matrix, values):
    """Area-weighted mean of the valid cells of each circle, and the valid fraction of the weight.

    Args:
        weight_matrix: ``scipy.sparse`` matrix (n_circles, n_cells) of cell weights (one diameter of ``GridSearch.circle_weights``).
        values: array (n_cells, n_variables) with NaN for invalid cells (masked, below ground, missing).

    Returns:
        (mean, valid_fraction), both float64 (n_circles, n_variables): the mean over the valid cells (NaN when a circle has no valid cell)
        and the weight of the valid cells divided by the total weight of the circle.
    """
    # Valid cells contribute their value, invalid cells contribute nothing to the numerator or to the denominator
    values = np.asarray(values, dtype=np.float64)
    valid = np.isfinite(values)
    numerator = weight_matrix @ np.where(valid, values, 0.0)
    denominator = weight_matrix @ valid.astype(np.float64)
    total = np.asarray(weight_matrix.sum(axis=1)).reshape(-1, 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(denominator > 0, numerator / denominator, np.nan)
        fraction = np.where(total > 0, denominator / total, np.nan)
    return mean, fraction
