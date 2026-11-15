"""H3 (v4) geographic assignment and cell geometry for regular latitude/longitude grids.

This module only answers "which H3 cell holds this sample?" and "what does that
cell look like on the ground?". It knows nothing about terrain or about any
particular dataset.

Assignment (pixel-centre rule)
    Each raster sample goes to the H3 cell that contains its geographic centre,
    using h3-py v4 ``latlng_to_cell(lat, lng, res)``. Note that **latitude comes
    first**, while GeoJSON stores **longitude first**. H3 does not reject swapped
    arguments (latitude -112.7 is silently wrapped to a valid but wrong cell), so
    the order matters and is tested. A sample whose footprint straddles a cell edge
    goes wholly to the cell holding its centre. This is the documented boundary
    approximation of the pilot.

    H3 treats geodetic WGS 84 latitude/longitude as spherical coordinates, as is
    standard practice. Cells at different resolutions are **not** nested: a fine
    cell's parent is not guaranteed to contain all of the fine cell's samples, so
    each resolution is assigned directly from the samples, never from a finer one.

Cell geometry
    Polygons use the vertices from ``cell_to_boundary``. Areas and overlaps are
    computed on the WGS 84 ellipsoid with the cylindrical equal-area mapping
    (lambda, F(phi)) in which ellipsoidal area is planar area, with polygon edges
    taken as straight lines in that plane. H3 edges are great-circle arcs; for the
    cell sizes used here the two differ by well under a metre (quantified in the
    tests). Because all cells share vertices and use the same edge model, the
    clipped pieces of neighbouring cells tile a rectangle exactly. That makes the
    area conservation check meaningful.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import h3
import numpy as np
from h3.api import basic_int as h3i

from . import geodesy
from .nasadem import BBox, GeoGrid

H3_MIN_RES, H3_MAX_RES = 0, 15
# Overlap areas below this are treated as zero (degenerate slivers from shared edges).
MIN_OVERLAP_M2 = 1e-3
H3_SPHERE_NOTE = (
    "h3.cell_area: area on H3's authalic sphere (R = 6371.007180918475 km); WGS 84 "
    "latitude/longitude are used directly as spherical coordinates"
)


def validate_resolution(resolution: int) -> int:
    if isinstance(resolution, bool) or int(resolution) != resolution:
        raise ValueError(f"H3 resolution must be an integer, got {resolution!r}")
    res = int(resolution)
    if not H3_MIN_RES <= res <= H3_MAX_RES:
        raise ValueError(f"H3 resolution must be in {H3_MIN_RES}..{H3_MAX_RES}, got {res}")
    return res


def h3_versions() -> dict:
    v = h3.versions()
    return {"h3_python": v.get("python"), "h3_c": v.get("c")}


def cell_to_str(cell: int) -> str:
    """Canonical lower-case hexadecimal H3 identifier (e.g. '8612ebc77ffffff')."""
    return h3.int_to_str(int(cell))


# --------------------------------------------------------------------------- assignment


def assign_points(lats, lons, resolution: int) -> np.ndarray:
    """H3 cell (uint64) containing each point, given separate latitude and longitude arrays."""
    res = validate_resolution(resolution)
    lat = np.asarray(lats, dtype=np.float64).reshape(-1)
    lon = np.asarray(lons, dtype=np.float64).reshape(-1)
    if lat.shape != lon.shape:
        raise ValueError(f"lats and lons differ in size: {lat.size} vs {lon.size}")
    if lat.size and not (np.all(np.abs(lat) <= 90.0) and np.all(np.abs(lon) <= 180.0)):
        raise ValueError("latitudes must be within +-90 and longitudes within +-180 degrees")
    f = h3i.latlng_to_cell
    return np.fromiter((f(a, b, res) for a, b in zip(lat.tolist(), lon.tolist())), dtype=np.uint64, count=lat.size)


def assign_grid(grid: GeoGrid, resolution: int) -> np.ndarray:
    """H3 cell of every sample centre of a regular grid, shape (nrows, ncols), rows north -> south.

    Grid samples are pixel-is-point, so a sample's position is its centre:
    (grid.lats()[row], grid.lons()[col]).
    """
    res = validate_resolution(resolution)
    lats = grid.lats()
    lons = grid.lons()
    if not (np.all(np.abs(lats) <= 90.0) and np.all(np.abs(lons) <= 180.0)):
        raise ValueError("grid extends beyond valid latitude/longitude ranges")
    f = h3i.latlng_to_cell
    lon_list = lons.tolist()
    out = np.empty((grid.nrows, grid.ncols), dtype=np.uint64)
    for r, lat in enumerate(lats.tolist()):  # latitude first: H3's argument order
        out[r] = [f(lat, lon, res) for lon in lon_list]
    return out


# --------------------------------------------------------------------------- geometry


def cell_boundary_lonlat(cell) -> np.ndarray:
    """Cell vertices as an (n, 2) array of [longitude, latitude], counter-clockwise, ring not closed.

    ``cell_to_boundary`` returns (lat, lng) pairs; they are swapped here into the
    GeoJSON order. Cells crossing the antimeridian (and so the polar cells) are
    rejected rather than handled incorrectly.
    """
    key = cell if isinstance(cell, str) else cell_to_str(cell)
    latlng = np.asarray(h3.cell_to_boundary(key), dtype=np.float64)
    ring = latlng[:, ::-1].copy()
    if np.ptp(ring[:, 0]) > 180.0:
        raise NotImplementedError(f"H3 cell {key} crosses the antimeridian; not supported yet")
    if _signed_area(ring) < 0:
        ring = ring[::-1].copy()
    return ring


def _signed_area(xy: np.ndarray) -> float:
    if len(xy) < 3:
        return 0.0
    x = xy[:, 0] - xy[0, 0]
    y = xy[:, 1] - xy[0, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y))


def authalic_area_coordinate(lat_deg):
    """F(phi) (m^2 per radian of longitude) such that dA = dF * dlambda on the WGS 84 ellipsoid.

    F(phi) = a^2/2 * q(phi), with Snyder's q = (1 - e^2) [sin phi / (1 - e^2 sin^2 phi)
    + artanh(e sin phi) / e], so dF/dphi = M(phi) N(phi) cos(phi). The area of a
    latitude/longitude quadrangle is (F(phi2) - F(phi1)) * (lambda2 - lambda1).
    """
    e2 = geodesy.WGS84_E2
    e = np.sqrt(e2)
    s = np.sin(np.radians(lat_deg))
    q = (1.0 - e2) * (s / (1.0 - e2 * s * s) + np.arctanh(e * s) / e)
    return 0.5 * geodesy.WGS84_A**2 * q


def _to_area_plane(ring_lonlat: np.ndarray) -> np.ndarray:
    ring = np.asarray(ring_lonlat, dtype=np.float64)
    return np.column_stack([np.radians(ring[:, 0]), authalic_area_coordinate(ring[:, 1])])


def _plane_area(xy: np.ndarray) -> float:
    return abs(_signed_area(xy)) if len(xy) >= 3 else 0.0


def ring_area_m2(ring_lonlat) -> float:
    """WGS 84 ellipsoidal area (m^2) of a simple polygon given as [lon, lat] vertices.

    Exact for latitude/longitude rectangles. Other edges are treated as straight in
    the equal-area plane (lambda, F(phi)).
    """
    ring = np.asarray(ring_lonlat, dtype=np.float64)
    return _plane_area(_to_area_plane(ring)) if len(ring) >= 3 else 0.0


def bbox_area_m2(bbox: BBox) -> float:
    """Exact WGS 84 area of a latitude/longitude rectangle (m^2)."""
    return float(
        (authalic_area_coordinate(bbox.north) - authalic_area_coordinate(bbox.south))
        * np.radians(bbox.east - bbox.west)
    )


def _clip_plane(pts: np.ndarray, bbox: BBox) -> np.ndarray:
    """Sutherland-Hodgman clip of an equal-area-plane polygon to the image of ``bbox``."""
    x0, x1 = np.radians(bbox.west), np.radians(bbox.east)
    y0, y1 = float(authalic_area_coordinate(bbox.south)), float(authalic_area_coordinate(bbox.north))
    poly = [tuple(p) for p in pts]
    for axis, bound, keep_greater in ((0, x0, True), (0, x1, False), (1, y0, True), (1, y1, False)):
        if not poly:
            break
        poly = _clip_half_plane(poly, axis, bound, keep_greater)
    return np.asarray(poly, dtype=np.float64).reshape(-1, 2)


def _from_area_plane(xy: np.ndarray) -> np.ndarray:
    if not len(xy):
        return np.empty((0, 2))
    return np.column_stack([np.degrees(xy[:, 0]), _inverse_authalic(xy[:, 1])])


def clip_ring_to_bbox(ring_lonlat, bbox: BBox) -> np.ndarray:
    """Clip a polygon ([lon, lat] vertices) to a longitude/latitude rectangle (Sutherland-Hodgman).

    Intersections are interpolated in the equal-area plane, consistent with
    ``ring_area_m2``, so the clipped pieces of adjacent cells tile the rectangle.
    Returns the clipped ring as [lon, lat] (possibly empty).
    """
    return _from_area_plane(_clip_plane(_to_area_plane(ring_lonlat), bbox))


def _clip_half_plane(poly: list, axis: int, bound: float, keep_greater: bool) -> list:
    def inside(p) -> bool:
        return p[axis] >= bound if keep_greater else p[axis] <= bound

    out = []
    n = len(poly)
    for i in range(n):
        cur, prev = poly[i], poly[i - 1]
        cur_in, prev_in = inside(cur), inside(prev)
        if cur_in != prev_in:
            t = (bound - prev[axis]) / (cur[axis] - prev[axis])
            cross = [prev[0] + t * (cur[0] - prev[0]), prev[1] + t * (cur[1] - prev[1])]
            cross[axis] = bound  # exact on the clip line
            out.append(tuple(cross))
        if cur_in:
            out.append(cur)
    return out


def _inverse_authalic(F: np.ndarray, iterations: int = 6) -> np.ndarray:
    """Latitude (deg) for given F values (Newton iterations from the spherical estimate)."""
    F = np.asarray(F, dtype=np.float64)
    a2 = geodesy.WGS84_A**2
    f_pole = float(authalic_area_coordinate(90.0))
    phi = np.arcsin(np.clip(F / f_pole, -1.0, 1.0))
    for _ in range(iterations):
        lat = np.degrees(phi)
        dF = geodesy.meridional_radius_m(lat) * geodesy.prime_vertical_radius_m(lat) * np.cos(phi)
        phi = phi - (authalic_area_coordinate(lat) - F) / np.where(dF > 0, dF, a2)
    return np.degrees(phi)


@dataclass(frozen=True)
class CellGeometry:
    """Ground geometry of one H3 cell relative to the analysed footprint."""

    cell: int
    boundary_lonlat: np.ndarray  # (n, 2) counter-clockwise, not closed
    centre_lat: float
    centre_lon: float
    is_pentagon: bool
    area_m2: float  # WGS 84 ellipsoidal area of the whole cell polygon
    h3_area_m2: float  # h3.cell_area (spherical), for reference
    overlap_area_m2: float  # exact area of (cell polygon intersect footprint), same model as area_m2
    overlap_lonlat: np.ndarray  # clipped polygon (observed part of the cell)

    @property
    def h3_id(self) -> str:
        return cell_to_str(self.cell)

    @property
    def overlap_fraction(self) -> float:
        return self.overlap_area_m2 / self.area_m2

    @property
    def is_complete(self) -> bool:
        """True when the footprint covers the whole cell polygon."""
        return self.overlap_area_m2 >= self.area_m2 * (1.0 - 1e-9)


def cell_geometry(cell, footprint: BBox) -> CellGeometry:
    key = cell if isinstance(cell, str) else cell_to_str(cell)
    ring = cell_boundary_lonlat(key)
    plane = _to_area_plane(ring)
    clipped = _clip_plane(plane, footprint)
    overlap = _plane_area(clipped)  # an unclipped cell gives exactly the same number as its area
    lat, lon = h3.cell_to_latlng(key)
    return CellGeometry(
        cell=h3.str_to_int(key),
        boundary_lonlat=ring,
        centre_lat=float(lat),
        centre_lon=float(lon),
        is_pentagon=bool(h3.is_pentagon(key)),
        area_m2=_plane_area(plane),
        h3_area_m2=float(h3.cell_area(key, unit="m^2")),
        overlap_area_m2=overlap if overlap > MIN_OVERLAP_M2 else 0.0,
        overlap_lonlat=_from_area_plane(clipped),
    )


def uncovered_overlapping_cells(cells: Iterable[int], footprint: BBox) -> list[CellGeometry]:
    """Cells that overlap the footprint but received no sample centre (thin boundary slivers).

    With pixel-centre assignment, a cell can overlap the footprint by less than a
    pixel without containing any sample centre. Every such cell borders an assigned
    cell, so the immediate neighbours (``grid_disk`` k = 1) of the assigned cells are
    a complete candidate set. Their overlap closes the exact area budget.
    """
    assigned = {int(c) for c in cells}
    candidates = set()
    for c in assigned:
        candidates.update(h3i.grid_disk(c, 1))
    candidates -= assigned
    out = []
    for c in sorted(candidates):
        geom = cell_geometry(c, footprint)
        if geom.overlap_area_m2 > 0.0:
            out.append(geom)
    return out
