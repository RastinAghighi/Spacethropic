"""3 x 3 neighbourhood terrain derivatives for grids with metric sample spacing.

All functions take a 2-D elevation array whose rows run north -> south (the
NASADEM/SRTM order) and return arrays of the same shape. A result is NaN on the
outermost rows/columns (no full 3 x 3 neighbourhood) and wherever any of the 9
window samples is NaN, so missing data never leaks into a derivative.

Spacings are in metres. ``dx`` (east-west) may vary per row, as it does on a
latitude/longitude grid; pass a scalar or an array with one value per row.
"""

from __future__ import annotations

import numpy as np

_NEIGHBOUR_OFFSETS = [(di, dj) for di in (0, 1, 2) for dj in (0, 1, 2) if (di, dj) != (1, 1)]


def _check_grid(z) -> np.ndarray:
    z = np.asarray(z, dtype=np.float64)
    if z.ndim != 2 or min(z.shape) < 3:
        raise ValueError(f"need a 2-D array of at least 3 x 3, got shape {z.shape}")
    return z


def _row_spacing(spacing, nrows: int, name: str) -> np.ndarray:
    s = np.asarray(spacing, dtype=np.float64)
    if s.ndim == 0:
        s = np.full(nrows, float(s))
    if s.shape != (nrows,):
        raise ValueError(f"{name} must be a scalar or have shape ({nrows},), got {s.shape}")
    if not np.all(np.isfinite(s) & (s > 0)):
        raise ValueError(f"{name} must be finite and positive")
    return s[:, None]


def invalid_window_mask(z) -> np.ndarray:
    """True where the 3 x 3 window is incomplete (grid edge) or contains a NaN."""
    z = _check_grid(z)
    nr, nc = z.shape
    bad = ~np.isfinite(z)
    core = np.zeros((nr - 2, nc - 2), dtype=bool)
    for di in (0, 1, 2):
        for dj in (0, 1, 2):
            core |= bad[di : di + nr - 2, dj : dj + nc - 2]
    out = np.ones(z.shape, dtype=bool)
    out[1:-1, 1:-1] = core
    return out


def horn_gradient(z, dx, dy) -> tuple[np.ndarray, np.ndarray]:
    """Surface gradient (dz/dx east, dz/dy north), dimensionless (m/m), by Horn (1981).

    Horn's 3 x 3 operator is the one used by GDAL ``gdaldem`` and ArcGIS. Each
    row's east-west central difference uses that row's own ``dx``, which is the
    correct form when dx varies with latitude.
    """
    z = _check_grid(z)
    nr, _ = z.shape
    dx = _row_spacing(dx, nr, "dx")
    dy = _row_spacing(dy, nr, "dy")
    dzdx = np.full(z.shape, np.nan)
    dzdy = np.full(z.shape, np.nan)
    ew = (z[:, 2:] - z[:, :-2]) / (2.0 * dx)  # per-row central differences
    dzdx[1:-1, 1:-1] = (ew[:-2] + 2.0 * ew[1:-1] + ew[2:]) / 4.0
    ns = (z[:-2, :] - z[2:, :]) / (2.0 * dy[1:-1])  # north minus south
    dzdy[1:-1, 1:-1] = (ns[:, :-2] + 2.0 * ns[:, 1:-1] + ns[:, 2:]) / 4.0
    invalid = invalid_window_mask(z)
    dzdx[invalid] = np.nan
    dzdy[invalid] = np.nan
    return dzdx, dzdy


def slope_from_gradient(dzdx: np.ndarray, dzdy: np.ndarray) -> np.ndarray:
    """Slope angle in degrees from a gradient pair."""
    return np.degrees(np.arctan(np.hypot(dzdx, dzdy)))


def slope_degrees(z, dx, dy) -> np.ndarray:
    """Slope angle in degrees (0 = flat), with Horn gradients on metric spacings."""
    return slope_from_gradient(*horn_gradient(z, dx, dy))


def terrain_ruggedness_index(z) -> np.ndarray:
    """Terrain Ruggedness Index (Riley et al., 1999) in metres.

    TRI = sqrt(sum over the 8 neighbours of (z_neighbour - z_centre)^2). It needs no
    horizontal distances, but it grows with both slope and sample spacing, so it
    is only comparable between grids with the same spacing.
    """
    z = _check_grid(z)
    nr, nc = z.shape
    centre = z[1:-1, 1:-1]
    acc = np.zeros_like(centre)
    for di, dj in _NEIGHBOUR_OFFSETS:
        acc += (z[di : di + nr - 2, dj : dj + nc - 2] - centre) ** 2
    out = np.full(z.shape, np.nan)
    out[1:-1, 1:-1] = np.sqrt(acc)
    out[invalid_window_mask(z)] = np.nan
    return out


def detrended_roughness(z) -> np.ndarray:
    """RMS residual (m) of the 9 window samples about their least-squares plane.

    Removing the local plane makes this zero on any uniform slope, so unlike TRI
    it measures small-scale relief, not steepness. On a regular grid the residual
    does not depend on dx or dy (rescaling the coordinates leaves the set of
    planes unchanged), so only the window's ground footprint sets the scale. On a
    latitude/longitude grid the window's east-west spacing varies by about 1e-5
    across 3 rows, which is ignored.
    """
    z = _check_grid(z)
    nr, nc = z.shape
    centre = z[1:-1, 1:-1]
    s = np.zeros_like(centre)  # sum of d
    s2 = np.zeros_like(centre)  # sum of d^2
    su = np.zeros_like(centre)  # sum of u*d (u = column offset, east positive)
    sv = np.zeros_like(centre)  # sum of v*d (v = row offset, north positive)
    for di in (0, 1, 2):
        for dj in (0, 1, 2):
            d = z[di : di + nr - 2, dj : dj + nc - 2] - centre  # relative to centre: avoids cancellation
            s += d
            s2 += d * d
            su += (dj - 1) * d
            sv += (1 - di) * d
    # {1, u, v} are orthogonal on the 3x3 stencil with sum(u^2) = sum(v^2) = 6.
    ssr = s2 - s * s / 9.0 - su * su / 6.0 - sv * sv / 6.0
    out = np.full(z.shape, np.nan)
    out[1:-1, 1:-1] = np.sqrt(np.maximum(ssr, 0.0) / 9.0)
    out[invalid_window_mask(z)] = np.nan
    return out


def hillshade(dzdx, dzdy, azimuth_deg: float = 315.0, altitude_deg: float = 45.0, z_factor: float = 1.0) -> np.ndarray:
    """Lambertian hillshade in [0, 1] from a metric gradient (azimuth clockwise from north)."""
    p = np.asarray(dzdx) * z_factor
    q = np.asarray(dzdy) * z_factor
    az, alt = np.radians(azimuth_deg), np.radians(altitude_deg)
    lx, ly, lz = np.sin(az) * np.cos(alt), np.cos(az) * np.cos(alt), np.sin(alt)
    shade = (-p * lx - q * ly + lz) / np.sqrt(1.0 + p * p + q * q)
    return np.clip(shade, 0.0, 1.0)
