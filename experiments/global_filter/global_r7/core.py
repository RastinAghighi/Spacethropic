"""Permissive v2 MODIS-only policy and spherical, bounded-memory H3 quadrature.

Policy adapted from data/cleaning 475bf4e global_mask_v2.py and contours_r8.py.
Quadrature replaces the latter's latitude/longitude rasterization, including at poles.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import h3
import numpy as np

R_KM = 6371.007180918475
H, W, DEG = 3600, 7200, 0.05
VEG = (1, 2, 3, 4, 5, 6, 8, 11, 12, 14)
OTHER = (7, 9, 10, 15, 16)
BITS = dict(
    ocean=1,
    water=2,
    built=4,
    population=8,
    vegetation=16,
    mixed=32,
    missing_landcover=64,
    missing_population=128,
    barren_in_removed=256,
)
EXCLUDED = 63
MISSING = 192
POLICY = dict(
    name="v2_modis_only_permissive",
    original_commit="475bf4e",
    population_max=50,
    water_max=0.5,
    built_max=0.25,
    vegetation_max=0.5,
    nonanalog_max=0.5,
    remove_at=0.9,
    analog_classes=list(OTHER),
    esri=False,
    ndvi_gate=False,
    missing="uncertain; never eligible",
    barren_rescue="review only",
)


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(8 << 20), b""):
            h.update(b)
    return h.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
    tmp.replace(path)


def pixel_areas():
    edges = np.radians(90 - DEG * np.arange(H + 1))
    return R_KM**2 * np.radians(DEG) * (np.sin(edges[:-1]) - np.sin(edges[1:]))


def pixel_indices(lat, lon):
    return (
        np.clip(np.floor((90 - np.asarray(lat)) / DEG).astype(int), 0, H - 1),
        np.floor(((np.asarray(lon) + 180) % 360) / DEG).astype(int) % W,
    )


def policy_flags(
    land, water, built, veg, density, lc_known, pop_known, barren_count=None
):
    """Known failures override missingness; reasons are overlapping, not additive."""
    flags = np.zeros(np.shape(water), np.uint16)
    flags[~np.asarray(land, bool)] |= BITS["ocean"]
    flags[np.asarray(lc_known) & (water >= 0.5)] |= BITS["water"]
    flags[np.asarray(lc_known) & (built >= 0.25)] |= BITS["built"]
    flags[np.asarray(pop_known) & (density >= 50)] |= BITS["population"]
    flags[np.asarray(lc_known) & (veg >= 0.5)] |= BITS["vegetation"]
    flags[(flags == 0) & lc_known & ((water + built + veg) >= 0.5)] |= BITS["mixed"]
    flags[np.asarray(land) & ~np.asarray(lc_known)] |= BITS["missing_landcover"]
    flags[np.asarray(land) & ~np.asarray(pop_known)] |= BITS["missing_population"]
    if barren_count is not None:
        rescue = (flags & (BITS["water"] | BITS["vegetation"] | BITS["mixed"])) != 0
        rescue &= (flags & (BITS["ocean"] | BITS["built"] | BITS["population"])) == 0
        flags[rescue & (barren_count >= 24)] |= BITS["barren_in_removed"]
    return flags


def vectors(latlon):
    lat, lon = np.radians(np.asarray(latlon)).T
    return np.column_stack(
        (np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat))
    )


@lru_cache(maxsize=8)
def triangle_stencil(n):
    if not 1 <= n <= 32:
        raise ValueError("subdivisions must be 1..32")

    def v(i, j):
        return [1 - (i + j) / n, i / n, j / n]

    triangles = []
    for i in range(n):
        for j in range(n - i):
            triangles.append([v(i, j), v(i + 1, j), v(i, j + 1)])
            if i + j < n - 1:
                triangles.append([v(i + 1, j), v(i + 1, j + 1), v(i, j + 1)])
    return np.asarray(triangles)


def cell_samples(cell, subdivisions=8):
    """Centroids of small spherical triangles, weighted by exact solid angle.

    Normalized linear combinations lie on great-circle edges. Triangles tile
    the H3 spherical polygon, including pentagons, face splits and polar cells.
    Integration of a discontinuous mask is approximate; geometry/total area is exact.
    """
    boundary = vectors(h3.cell_to_boundary(cell))
    center = vectors([h3.cell_to_latlng(cell)])[0]
    triangles = np.stack(
        (
            np.broadcast_to(center, boundary.shape),
            boundary,
            np.roll(boundary, -1, axis=0),
        ),
        axis=1,
    )
    q = np.einsum("svi,tij->tsvj", triangle_stencil(subdivisions), triangles).reshape(
        -1, 3, 3
    )
    q /= np.linalg.norm(q, axis=2, keepdims=True)
    a, b, c = q[:, 0], q[:, 1], q[:, 2]
    numerator = np.abs(np.einsum("ij,ij->i", a, np.cross(b, c)))
    denominator = (
        1 + np.sum(a * b, axis=1) + np.sum(b * c, axis=1) + np.sum(c * a, axis=1)
    )
    areas = 2 * np.arctan2(numerator, denominator) * R_KM**2
    points = q.sum(axis=1)
    points /= np.linalg.norm(points, axis=1, keepdims=True)
    lat = np.degrees(np.arcsin(np.clip(points[:, 2], -1, 1)))
    lon = np.degrees(np.arctan2(points[:, 1], points[:, 0]))
    return lat, lon, areas


class Mask:
    """Memory-mapped prepared 0.05 degree inputs. No global H3 array."""

    source_kind = "prepared_global_mask"

    def __init__(self, root):
        self.root = Path(root)
        self.manifest = json.loads((self.root / "manifest.json").read_text())
        if self.manifest["status"] != "complete":
            raise ValueError("Input preparation is incomplete")
        for name, info in self.manifest["files"].items():
            if digest(self.root / name) != info["sha256"]:
                raise ValueError(f"Input checksum mismatch: {name}")
        self.flags = np.load(self.root / "flags.npy", mmap_mode="r")
        self.land = np.load(self.root / "land.npy", mmap_mode="r")
        self.density = np.load(self.root / "density.npy", mmap_mode="r")
        self.counts = np.load(self.root / "counts.npy", mmap_mode="r")
        self.source_id = digest(self.root / "manifest.json")

    def sample(self, lat, lon):
        r, c = pixel_indices(lat, lon)
        cnt = self.counts[:, r, c].astype(np.float32)
        total = cnt.sum(axis=0)
        fractions = cnt / np.maximum(total, 1)
        return dict(
            flags=self.flags[r, c],
            land=self.land[r, c],
            density=self.density[r, c],
            fractions=fractions,
            class_known=total > 0,
            groups=np.stack(
                (
                    fractions[0],
                    fractions[13],
                    fractions[list(VEG)].sum(axis=0),
                    fractions[list(OTHER)].sum(axis=0),
                )
            ),
        )


def evaluate(cell, sampler, subdivisions=8, margin=0.01):
    lat, lon, area = cell_samples(cell, subdivisions)
    # Hundreds of samples generally hit only a few coarse pixels. Coalesce them
    # before reading the global memmaps; preserve exactly the same quadrature.
    rr, cc = pixel_indices(lat, lon)
    pixels, inverse = np.unique(rr * W + cc, return_inverse=True)
    w = np.bincount(inverse, weights=area) / area.sum()
    s = sampler.sample(90 - (pixels // W + 0.5) * DEG, -180 + (pixels % W + 0.5) * DEG)
    flags = s["flags"]
    excluded = (flags & EXCLUDED) != 0
    unknown = ~excluded & ((flags & MISSING) != 0)
    eligible = ~excluded & ~unknown
    ef, uf, xf = (float(w @ x) for x in (eligible, unknown, excluded))
    near = abs(xf - 0.9) <= margin
    rescue = bool(np.any(flags & BITS["barren_in_removed"]))
    # Preserve original >=90% removal, but retain threshold/missing/rescue cases as uncertain.
    if xf >= 0.9 and not near and not rescue:
        decision = "excluded"
    elif uf > 1e-12 or near or rescue:
        decision = "uncertain"
    else:
        decision = "eligible"
    lc = np.asarray(s["class_known"], bool)
    pop = np.isfinite(s["density"])
    cp = float(w @ pop)
    avg_pop = float(w @ np.where(pop, s["density"], 0)) / cp if cp > 0 else None
    clat, clon = h3.cell_to_latlng(cell)
    result = dict(
        h3_cell=cell,
        resolution=h3.get_resolution(cell),
        latitude=clat,
        longitude=clon,
        cell_area_km2=h3.cell_area(cell, unit="km^2"),
        land_fraction=float(w @ s["land"]),
        eligible_fraction=ef,
        uncertain_fraction=uf,
        excluded_fraction=xf,
        decision=decision,
        baseline_kept=bool(xf < 0.9),
        reason_bits=int(np.bitwise_or.reduce(flags)),
        mixed_cell=bool(xf > 1e-12 and xf < 1 - 1e-12),
        near_threshold=near,
        barren_in_removed=rescue,
        class_observed_fraction=float(w @ lc),
        population_observed_fraction=cp,
        population_density_observed_mean=avg_pop,
        sample_count=len(area),
        quadrature_area_error=abs(area.sum() / h3.cell_area(cell, unit="km^2") - 1),
        provenance_id=sampler.source_id,
    )
    result.update(
        {
            f"lc_{k:02d}_fraction": float(w @ s["fractions"][k]) if lc.any() else None
            for k in range(17)
        }
    )
    result.update(
        {
            f"group_{name}_fraction": float(w @ s["groups"][i])
            for i, name in enumerate(("water", "built", "vegetation", "other"))
        }
    )
    result.update(
        {
            f"reason_{name}_fraction": float(w @ ((flags & bit) != 0))
            for name, bit in BITS.items()
        }
    )
    return result
