"""WGS 84 ellipsoid helpers for metric distances and areas on latitude/longitude grids.

Geographic rasters (such as NASADEM) are sampled at fixed *angular* steps. The
ground distance of one step depends on latitude, and east-west steps shrink
with cos(latitude), so pixels are not square in metres (at 51.5 N a 1"
sample spacing is ~19.3 m east-west but ~30.9 m north-south). These functions
convert angular steps to metres on the WGS 84 ellipsoid using the local radii
of curvature, which is exact to well below a millimetre for arc-second steps.
"""

from __future__ import annotations

import numpy as np

WGS84_A = 6_378_137.0  # semi-major axis (m)
WGS84_F = 1.0 / 298.257_223_563  # flattening
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)  # first eccentricity squared


def meridional_radius_m(lat_deg):
    """Radius of curvature in the meridian, M(lat), in metres."""
    s = np.sin(np.radians(lat_deg))
    return WGS84_A * (1.0 - WGS84_E2) / (1.0 - WGS84_E2 * s * s) ** 1.5


def prime_vertical_radius_m(lat_deg):
    """Radius of curvature in the prime vertical, N(lat), in metres."""
    s = np.sin(np.radians(lat_deg))
    return WGS84_A / np.sqrt(1.0 - WGS84_E2 * s * s)


def metres_per_degree_lat(lat_deg):
    """Ground length (m) of one degree of latitude, centred on ``lat_deg``."""
    return np.radians(1.0) * meridional_radius_m(lat_deg)


def metres_per_degree_lon(lat_deg):
    """Ground length (m) of one degree of longitude along the parallel ``lat_deg``."""
    return np.radians(1.0) * prime_vertical_radius_m(lat_deg) * np.cos(np.radians(lat_deg))


def cell_area_m2(lat_deg, dlat_deg: float, dlon_deg: float):
    """Area (m^2) of a ``dlat_deg`` x ``dlon_deg`` cell centred on latitude ``lat_deg``.

    Uses M * N * cos(lat) * dlat * dlon. The relative error versus the exact
    ellipsoidal quadrangle is of order dlat^2 (~1e-11 for 1" cells).
    """
    return metres_per_degree_lat(lat_deg) * dlat_deg * metres_per_degree_lon(lat_deg) * dlon_deg
