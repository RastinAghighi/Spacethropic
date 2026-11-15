"""Independent verification of the Spacethropic NASADEM terrain pipeline on real data (DRUMHELLER-PILOT-02).

Run from the project root (a few minutes; peak memory about 0.7 GB):

    .venv\\Scripts\\python -I validation\\independent_check.py ^
        NASADEM_HGT_001-20261114_161823\\NASADEM_HGT_n51w113.zip --work-dir <scratch dir>

It writes ``validation/results/n51w113_validation.json`` and prints a summary.

What is independent of the pipeline, and what is not
----------------------------------------------------
Written separately for this check. The reference part imports nothing from ``spacethropic``:

* ZIP access and HGT/NUM/SWB decoding use only the standard library: a hand-written ZIP
  central-directory parser, raw-DEFLATE decompression with ``zlib``, CRC-32 and size checks,
  and big-endian int16 decoding with ``struct`` and ``array.byteswap``. The pipeline uses
  ``zipfile`` and a numpy ``>i2`` dtype instead.
* AOI rows/columns are derived in integer arc-seconds.
* Ground distances are ECEF chord lengths between neighbouring sample centres. The
  pipeline uses meridional and prime-vertical radii of curvature instead.
* Cell areas use the exact ellipsoidal-quadrangle (authalic-latitude) formula. The
  pipeline uses M * N * cos(lat) * dlat * dlon instead.
* Horn slope is written with named neighbours a..i, and TRI with explicit neighbours.
  Detrended roughness uses an explicit 9 x 9 least-squares projection matrix, both in
  sample-index coordinates and in the true metric (trapezoidal) window coordinates. The
  pipeline uses a closed-form orthogonal decomposition in index coordinates.
* Statistics use ``numpy.average`` and ``numpy.percentile(weights=..., method="inverted_cdf")``.
  The pipeline uses its own ``stats.summarize``.

Not independent:

* The NASADEM format interpretation comes from the same NASADEM User Guide: big-endian
  int16, 3601 x 3601, row 0 = northern edge, tile name = south-west corner, SWB 255 = water.
* The metric definitions (Horn slope, Riley TRI, RMS residual about the 3 x 3 plane) are
  the same by design.
* numpy and the WGS 84 constants are shared.
* The same engineer wrote both the pipeline and this check.

Only ``compare_with_pipeline`` imports ``spacethropic``, to compare against it.
"""

from __future__ import annotations

import argparse
import array
import gc
import json
import math
import random
import re
import shutil
import struct
import sys
import tempfile
import time
import zlib
from pathlib import Path

import numpy as np

# ----------------------------------------------------------------------------- constants (re-stated here)

N = 3601  # samples per side of a 1 arc-second NASADEM_HGT tile
STEP = 1.0 / 3600.0  # degrees
SRTM_VOID = -32768
SWB_WATER = 255
WGS84_A = 6_378_137.0
WGS84_F = 1.0 / 298.257_223_563
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)
PERCENTILES = (5.0, 25.0, 50.0, 75.0, 95.0)
DRUMHELLER_BBOX = (-112.80, 51.40, -112.60, 51.52)  # west, south, east, north (README example)
DRUMHELLER_TOWN = (51.4636, -112.7106)  # approximate public coordinates; plausibility check only
SAMPLE_SEED = 20261114  # deterministic sample of real elevation values
MC_SEED = 12345  # quantisation Monte Carlo
LAYERS = ("slope", "dzdx", "dzdy", "tri", "rough_index", "rough_metric", "slope_zt", "slope_ls")

# 3x3 window positions in row-major order (row 0 = north): u = east offset, v = north offset.
_POS = [(di, dj) for di in range(3) for dj in range(3)]
U = np.array([dj - 1 for di, dj in _POS], dtype=np.float64)
V = np.array([1 - di for di, dj in _POS], dtype=np.float64)

# Per-pixel tolerances (absolute): |pipeline - reference| <= tol.
# The pipeline stores layers as float32: half an ulp is 1.9e-6 at 45 deg and 3.8e-6 at 72 m.
PIXEL_TOL = {
    "elevation": 0.0,
    "slope": 1e-5,
    "roughness_tri": 1e-5,
    "roughness_detrended": 1e-5,
    # The pipeline fits its plane in index space, which assumes the same dx on all three rows.
    # The true window is a trapezoid: row spacing changes by tan(lat) * dlat ~ 6e-6 per row.
    # Bound: |dz| between columns (<= ~40 m) * 6e-6 * O(1) ~ 3e-4 m.
    "roughness_detrended_vs_metric_window": 5e-4,
}


def stat_tolerance(measurement: str, stat: str) -> tuple[float, float]:
    """(absolute, relative) tolerance for one summary statistic."""
    if stat == "count_valid":
        return 0.0, 0.0
    if stat == "valid_area_km2":
        return 0.0, 1e-9  # M*N*cos(lat) cell area vs exact quadrangle: ~1e-11 relative
    if measurement == "elevation":
        return (0.0, 1e-9) if stat in ("mean", "std") else (0.0, 0.0)  # integer heights: exact
    if stat in ("mean", "std"):
        return 0.0, 1e-6  # mean of float32-rounded values
    return 1e-5, 0.0  # min/max/percentiles are single float32 samples


def within(value: float, ref: float, tol: tuple[float, float]) -> bool:
    return abs(value - ref) <= tol[0] + tol[1] * abs(ref)


# ----------------------------------------------------------------------------- stdlib ZIP / HGT reader


def read_zip_members(path: Path) -> dict[str, bytes]:
    """Decompress every member of a (non-ZIP64, unencrypted) ZIP using struct + zlib only.

    Each member's CRC-32 and uncompressed size are checked against the central directory.
    """
    data = Path(path).read_bytes()
    eocd = data.rfind(b"PK\x05\x06", max(0, len(data) - 65_557))
    if eocd < 0:
        raise ValueError("end-of-central-directory record not found")
    _, _, _, _, n_entries, _cd_size, cd_offset, _ = struct.unpack_from("<IHHHHIIH", data, eocd)
    if cd_offset == 0xFFFFFFFF or n_entries == 0xFFFF:
        raise ValueError("ZIP64 archives are not supported by this reference reader")
    members: dict[str, bytes] = {}
    pos = cd_offset
    for _ in range(n_entries):
        (sig, _vm, _vn, flags, method, _t, _d, crc, csize, usize, nlen, xlen, clen, _ds, _ia, _ea,
         local_off) = struct.unpack_from("<IHHHHHHIIIHHHHHII", data, pos)
        if sig != 0x02014B50:
            raise ValueError(f"bad central-directory signature at offset {pos}")
        name = data[pos + 46 : pos + 46 + nlen].decode("utf-8" if flags & 0x800 else "cp437")
        pos += 46 + nlen + xlen + clen
        if name.endswith("/"):
            continue
        if flags & 0x1:
            raise ValueError(f"{name}: encrypted members are not supported")
        if struct.unpack_from("<I", data, local_off)[0] != 0x04034B50:
            raise ValueError(f"{name}: bad local-header signature")
        lnlen, lxlen = struct.unpack_from("<HH", data, local_off + 26)
        start = local_off + 30 + lnlen + lxlen
        raw = data[start : start + csize]
        if method == 8:
            dec = zlib.decompressobj(-15)
            out = dec.decompress(raw) + dec.flush()
        elif method == 0:
            out = raw
        else:
            raise ValueError(f"{name}: unsupported compression method {method}")
        if len(out) != usize or (zlib.crc32(out) & 0xFFFFFFFF) != crc:
            raise ValueError(f"{name}: size or CRC-32 mismatch")
        members[name] = out
    return members


def tile_origin(name: str) -> tuple[int, int]:
    """(south, west) integer degrees from an SRTM-style tile name such as 'n51w113'."""
    m = re.search(r"([ns])(\d{2})([ew])(\d{3})", name.lower())
    if not m:
        raise ValueError(f"no tile id in {name!r}")
    south = int(m.group(2)) * (1 if m.group(1) == "n" else -1)
    west = int(m.group(4)) * (1 if m.group(3) == "e" else -1)
    return south, west


def decode_hgt(buf: bytes) -> array.array:
    """Big-endian int16 -> native ``array('h')`` (no numpy)."""
    arr = array.array("h")
    if arr.itemsize != 2:
        raise RuntimeError("array('h') is not 16-bit on this platform")
    arr.frombytes(buf)
    if sys.byteorder == "little":
        arr.byteswap()
    return arr


def hgt_value(buf: bytes, row: int, col: int, ncols: int = N) -> int:
    """One big-endian int16 sample, decoded with struct from its byte offset."""
    return struct.unpack_from(">h", buf, 2 * (row * ncols + col))[0]


# ----------------------------------------------------------------------------- geometry


def _snap(x: float) -> float:
    return float(round(x)) if abs(x - round(x)) < 1e-6 else x  # tolerance in arc-seconds


def aoi_window(bbox, south: int, west: int) -> tuple[slice, slice]:
    """Rows/cols whose sample centres satisfy south <= lat < north and west <= lon < east.

    Worked in integer arc-seconds: lat(r) = top - r and lon(c) = west + c.
    """
    w, s, e, n = (_snap(v * 3600.0) for v in bbox)
    top_as, west_as = (south + 1) * 3600, west * 3600
    # s <= top - r < n   <=>   top - n < r <= top - s
    r_first = math.floor(top_as - n) + 1
    r_last = math.floor(top_as - s)
    # w <= west + c < e  <=>   w - west <= c < e - west
    c_first = math.ceil(w - west_as)
    c_last = math.ceil(e - west_as) - 1
    r_first, c_first = max(r_first, 0), max(c_first, 0)
    r_last, c_last = min(r_last, N - 1), min(c_last, N - 1)
    return slice(r_first, r_last + 1), slice(c_first, c_last + 1)


def lat_lon(south: int, west: int):
    lats = ((south + 1) * 3600 - np.arange(N)) / 3600.0
    lons = (west * 3600 + np.arange(N)) / 3600.0
    return lats, lons


def ecef(lat_deg, lon_deg):
    phi = np.radians(np.asarray(lat_deg, dtype=np.float64))
    lam = np.radians(np.asarray(lon_deg, dtype=np.float64))
    s = np.sin(phi)
    nu = WGS84_A / np.sqrt(1.0 - WGS84_E2 * s * s)
    return np.stack([nu * np.cos(phi) * np.cos(lam), nu * np.cos(phi) * np.sin(lam), nu * (1.0 - WGS84_E2) * s], axis=-1)


def chord_m(lat1, lon1, lat2, lon2):
    """Straight-line distance (m) between two points on the WGS 84 ellipsoid (h = 0).

    For 20-60 m separations the chord equals the geodesic to ~1e-10 m.
    """
    return np.linalg.norm(ecef(lat1, lon1) - ecef(lat2, lon2), axis=-1)


def quad_area_m2(lat1, lat2, dlon_deg):
    """Exact area of the ellipsoidal quadrangle lat1..lat2 x dlon (authalic-latitude formula)."""
    e = math.sqrt(WGS84_E2)

    def q(lat):
        s = np.sin(np.radians(lat))
        return s / (1.0 - WGS84_E2 * s * s) + np.log((1.0 + e * s) / (1.0 - e * s)) / (2.0 * e)

    b2 = WGS84_A**2 * (1.0 - WGS84_E2)
    return 0.5 * b2 * np.radians(dlon_deg) * (q(lat2) - q(lat1))


def row_cell_area_m2(lats, step=STEP):
    return quad_area_m2(lats - step / 2, lats + step / 2, step)


# ----------------------------------------------------------------------------- reference terrain


def projection_matrix(x, y) -> np.ndarray:
    """9 x 9 residual projector I - A (A'A)^-1 A' for the plane z = c0 + c1 x + c2 y."""
    a = np.column_stack([np.ones(9), x, y])
    return np.eye(9) - a @ np.linalg.solve(a.T @ a, a.T)


P_INDEX = projection_matrix(U, V)


def reference_terrain(z, lats_deg, step_deg=STEP, out=None, strip_rows=128, metric_roughness=True):
    """Reference layers for a north-up lat/lon grid; NaN where the 3x3 window is incomplete.

    The grid's outer rows and columns have no complete window. Any NaN sample makes its
    windows NaN through arithmetic propagation. Returns (layers, per-row spacings).
    """
    z = np.asarray(z, dtype=np.float64)
    nr, nc = z.shape
    keys = LAYERS if metric_roughness else tuple(k for k in LAYERS if k != "rough_metric")
    if out is None:
        out = {k: np.full((nr, nc), np.nan) for k in keys}
    else:
        for k in keys:
            out[k][...] = np.nan
    lat = np.asarray(lats_deg, dtype=np.float64)
    ew1 = chord_m(lat, 0.0, lat, step_deg)  # one column step, per row
    ew2 = chord_m(lat, 0.0, lat, 2 * step_deg)  # columns c-1 -> c+1, per row
    ns_up = np.full(nr, np.nan)
    ns_up[1:] = chord_m(lat[:-1], 0.0, lat[1:], 0.0)  # row r-1 -> r
    ns_dn = np.full(nr, np.nan)
    ns_dn[:-1] = ns_up[1:]  # row r -> r+1
    ns2 = np.full(nr, np.nan)
    ns2[1:-1] = chord_m(lat[:-2], 0.0, lat[2:], 0.0)  # row r-1 -> r+1
    with np.errstate(invalid="ignore"):
        for r0 in range(1, nr - 1, strip_rows):
            r1 = min(r0 + strip_rows, nr - 1)  # centre rows r0 .. r1-1
            zs = z[r0 - 1 : r1 + 1]
            a, b, c = zs[:-2, :-2], zs[:-2, 1:-1], zs[:-2, 2:]
            d, e, f = zs[1:-1, :-2], zs[1:-1, 1:-1], zs[1:-1, 2:]
            g, h, i = zs[2:, :-2], zs[2:, 1:-1], zs[2:, 2:]
            xt, xm, xb = ew2[r0 - 1 : r1 - 1, None], ew2[r0:r1, None], ew2[r0 + 1 : r1 + 1, None]
            yy = ns2[r0:r1, None]
            sl = (slice(r0, r1), slice(1, nc - 1))
            # Horn (1981): weights 1-2-1 across the difference direction.
            dzdx = ((c - a) / xt + 2.0 * (f - d) / xm + (i - g) / xb) / 4.0
            dzdy = ((a - g) + 2.0 * (b - h) + (c - i)) / (4.0 * yy)  # north minus south
            out["dzdx"][sl] = dzdx
            out["dzdy"][sl] = dzdy
            out["slope"][sl] = np.degrees(np.arctan(np.sqrt(dzdx * dzdx + dzdy * dzdy)))
            del dzdx, dzdy
            # Estimator sensitivity: Zevenbergen-Thorne (4-neighbour) and equal-weight least-squares plane.
            gx, gy = (f - d) / xm, (b - h) / yy
            out["slope_zt"][sl] = np.degrees(np.arctan(np.hypot(gx, gy)))
            gx = ((c - a) / xt + (f - d) / xm + (i - g) / xb) / 3.0
            gy = ((a - g) + (b - h) + (c - i)) / (3.0 * yy)
            out["slope_ls"][sl] = np.degrees(np.arctan(np.hypot(gx, gy)))
            del gx, gy
            # Riley TRI.
            out["tri"][sl] = np.sqrt(sum((nb - e) ** 2 for nb in (a, b, c, d, f, g, h, i)))
            # Detrended roughness: explicit projection onto the plane-residual space.
            win = np.stack([a, b, c, d, e, f, g, h, i], axis=-1) - e[..., None]
            res = win @ P_INDEX.T
            out["rough_index"][sl] = np.sqrt(np.mean(res * res, axis=-1))
            del res
            if metric_roughness:
                for k, r in enumerate(range(r0, r1)):
                    x = np.array([(dj - 1) * ew1[r + di - 1] for di, dj in _POS])
                    y = np.array([(ns_up[r], 0.0, -ns_dn[r])[di] for di, dj in _POS])
                    res = win[k] @ projection_matrix(x, y).T
                    out["rough_metric"][r, 1 : nc - 1] = np.sqrt(np.mean(res * res, axis=-1))
            del win
    return out, {"ew1": ew1, "ns2": ns2}


def reference_stats(values, row_area, mask, percentiles=PERCENTILES) -> dict:
    """Area-weighted statistics with numpy's own routines (not stats.summarize)."""
    v_all = np.asarray(values)
    ok = np.asarray(mask, dtype=bool) & np.isfinite(v_all)
    n = int(np.count_nonzero(ok))
    if n == 0:
        return {"count_valid": 0}
    w = np.repeat(np.asarray(row_area, dtype=np.float64), np.count_nonzero(ok, axis=1))  # row-major like v_all[ok]
    v = v_all[ok].astype(np.float64)
    mean = float(np.average(v, weights=w))
    std = float(np.sqrt(np.average((v - mean) ** 2, weights=w)))
    pct = np.percentile(v, percentiles, weights=w, method="inverted_cdf")
    out = {"count_valid": n, "min": float(v.min()), "max": float(v.max()), "mean": mean, "std": std}
    out.update({f"p{q:g}": float(p) for q, p in zip(percentiles, pct)})
    out["valid_area_km2"] = float(w.sum()) / 1e6
    return out


# ----------------------------------------------------------------------------- pipeline comparison


def _pixel_diff(pipe, ref, rows: slice, cols: slice, strip=300) -> dict:
    """Max |pipeline - reference| over pixels finite in both, plus NaN-pattern mismatches."""
    max_abs, nan_mismatch, n_both = 0.0, 0, 0
    for a in range(0, pipe.shape[0], strip):
        p = np.asarray(pipe[a : a + strip], dtype=np.float64)
        q = np.asarray(ref[rows.start + a : rows.start + a + p.shape[0], cols], dtype=np.float64)
        pn, qn = np.isnan(p), np.isnan(q)
        nan_mismatch += int(np.count_nonzero(pn != qn))
        both = ~pn & ~qn
        n_both += int(np.count_nonzero(both))
        if both.any():
            max_abs = max(max_abs, float(np.max(np.abs(p[both] - q[both]))))
    return {"max_abs_diff": max_abs, "nan_pattern_mismatches": nan_mismatch, "pixels_compared": n_both}


def compare_with_pipeline(zip_path, hgt_bytes, z16, num, swb, south, west, aois, ref_layers, ref_stats,
                          stored_json: dict, check) -> dict:
    from spacethropic.nasadem import HGT_DTYPE, BBox, NasademGranule
    from spacethropic.pipeline import AnalysisConfig, analyze_granule

    result: dict = {}
    lats, lons = lat_lon(south, west)
    with NasademGranule(zip_path) as g:
        raw = g._read_rows(g.members.hgt, HGT_DTYPE, slice(None))
        check("reader: full_hgt_identical_to_stdlib_decode", np.array_equal(raw, z16), f"all {raw.size} int16 samples")
        del raw
        elev = g.read_elevation(dtype=np.float32)  # the pipeline's float path, read once
        rng = random.Random(SAMPLE_SEED)
        dr, dc = aois["drumheller_badlands"]
        pts = [(0, 0), (0, N - 1), (N - 1, 0), (N - 1, N - 1), (N // 2, N // 2),
               (dr.start, dc.start), (dr.stop - 1, dc.stop - 1)]
        pts += [(rng.randrange(N), rng.randrange(N)) for _ in range(2000)]
        pts += [(rng.randrange(dr.start, dr.stop), rng.randrange(dc.start, dc.stop)) for _ in range(1000)]
        mism = sum(int(elev[r, c] != hgt_value(hgt_bytes, r, c)) for r, c in pts)
        check("reader: sampled_values_match_struct_decode", mism == 0,
              f"{len(pts)} points (random.Random({SAMPLE_SEED}) + 7 fixed), {mism} mismatches")
        result["sample_points"] = {
            "count": len(pts), "seed": SAMPLE_SEED, "mismatches": mism,
            "first_points_row_col_lat_lon_height": [
                [r, c, float(lats[r]), float(lons[c]), hgt_value(hgt_bytes, r, c)] for r, c in pts[:12]],
        }
        del elev
        check("reader: full_num_identical", np.array_equal(g.read_num(), num), "NUM layer, all samples")
        check("reader: full_swb_identical", np.array_equal(g.read_swb(), swb), "SWB layer, all samples")
        dlat = float(np.max(np.abs(g.grid.lats() - lats)))
        dlon = float(np.max(np.abs(g.grid.lons() - lons)))
        check("geometry: sample_coordinates", dlat < 1e-12 and dlon < 1e-12,
              f"max |lat diff| {dlat:.1e} deg, max |lon diff| {dlon:.1e} deg")
        dx_ref = chord_m(lats, 0.0, lats, STEP)
        ns2 = np.full(N, np.nan)
        ns2[1:-1] = chord_m(lats[:-2], 0.0, lats[2:], 0.0)
        rdx = float(np.max(np.abs(g.grid.dx_m() / dx_ref - 1)))
        rdy = float(np.nanmax(np.abs(g.grid.dy_m() / (ns2 / 2) - 1)))
        rarea = float(np.max(np.abs(g.grid.cell_area_m2() / row_cell_area_m2(lats) - 1)))
        check("geometry: dx_vs_ecef_chord", rdx < 1e-9, f"max relative diff {rdx:.1e} (tol 1e-9)")
        check("geometry: dy_vs_ecef_chord", rdy < 1e-9, f"max relative diff {rdy:.1e} (tol 1e-9)")
        check("geometry: cell_area_vs_exact_quadrangle", rarea < 1e-9, f"max relative diff {rarea:.1e} (tol 1e-9)")
        result["geometry"] = {"dx_rel_diff_max": rdx, "dy_rel_diff_max": rdy, "cell_area_rel_diff_max": rarea,
                              "dx_m_range_tile": [float(dx_ref.min()), float(dx_ref.max())],
                              "dy_m_range_tile": [float(np.nanmin(ns2 / 2)), float(np.nanmax(ns2 / 2))]}

    for name, (rows, cols) in aois.items():
        bbox = None if name == "tile" else BBox(*DRUMHELLER_BBOX)
        t0 = time.time()
        summary, layers = analyze_granule(zip_path, AnalysisConfig(bbox=bbox, name=name, rasterio_crosscheck=False))
        aoi = summary["aoi"]
        check(f"{name}: window_vs_integer_arcsec_derivation",
              aoi["row_range"] == [rows.start, rows.stop] and aoi["col_range"] == [cols.start, cols.stop],
              f"pipeline rows {aoi['row_range']} cols {aoi['col_range']}; reference rows "
              f"[{rows.start}, {rows.stop}] cols [{cols.start}, {cols.stop}]")
        # Area of the selected cells (cell edges half a step outside the extreme sample centres).
        lat_hi, lat_lo = lats[rows.start] + STEP / 2, lats[rows.stop - 1] - STEP / 2
        exact_area = float(quad_area_m2(lat_lo, lat_hi, (cols.stop - cols.start) * STEP)) / 1e6
        check(f"{name}: aoi_area_vs_exact_quadrangle", within(aoi["area_km2"], exact_area, (0, 1e-9)),
              f"pipeline {aoi['area_km2']:.9f} km2, exact {exact_area:.9f} km2")
        water_ref = swb[rows, cols] == SWB_WATER
        check(f"{name}: water_mask_identical", np.array_equal(layers.water, water_ref),
              f"{int(water_ref.sum())} water samples")
        mask_ref = (z16[rows, cols] != SRTM_VOID) & ~water_ref
        check(f"{name}: analysis_mask_identical", np.array_equal(layers.analysis_mask, mask_ref),
              f"{int(mask_ref.sum())} analysed samples")
        pix = {"elevation": _pixel_diff(layers.elevation_m, z16, rows, cols)}
        for key, lay, refkey in (("slope", layers.slope_deg, "slope"), ("roughness_tri", layers.tri_m, "tri"),
                                 ("roughness_detrended", layers.roughness_m, "rough_index"),
                                 ("roughness_detrended_vs_metric_window", layers.roughness_m, "rough_metric")):
            pix[key] = _pixel_diff(lay, ref_layers[refkey], rows, cols)
        for key, dd in pix.items():
            tol = PIXEL_TOL[key]
            check(f"{name}: per_pixel_{key}", dd["nan_pattern_mismatches"] == 0 and dd["max_abs_diff"] <= tol,
                  f"max |diff| {dd['max_abs_diff']:.2e} (tol {tol:g}), NaN-pattern mismatches "
                  f"{dd['nan_pattern_mismatches']}, {dd['pixels_compared']} pixels")
        stat_rows = []
        for meas in ("elevation", "slope", "roughness_tri", "roughness_detrended"):
            pstats = summary["measurements"][meas]
            sstats = stored_json[name]["measurements"][meas]
            for stat, rv in ref_stats[name][meas].items():
                tol = stat_tolerance(meas, stat)
                pv, sv = pstats[stat], sstats[stat]
                stat_rows.append({
                    "measurement": meas, "statistic": stat, "reference": rv, "pipeline_rerun": pv,
                    "stored_json": sv, "abs_diff_vs_reference": abs(pv - rv),
                    "tolerance_abs": tol[0], "tolerance_rel": tol[1],
                    "within_tolerance": within(pv, rv, tol),
                    "stored_equals_rerun": within(sv, pv, (1e-12, 1e-11)),  # stored JSON keeps 12 significant digits
                })
        n_bad = sum(not r["within_tolerance"] for r in stat_rows)
        n_drift = sum(not r["stored_equals_rerun"] for r in stat_rows)
        check(f"{name}: statistics_vs_reference", n_bad == 0, f"{len(stat_rows)} statistics, {n_bad} outside tolerance")
        check(f"{name}: stored_outputs_reproduced", n_drift == 0,
              f"{len(stat_rows)} statistics, {n_drift} stored values differ from a fresh run")
        ref_undefined = int(np.count_nonzero(mask_ref & np.isnan(np.asarray(ref_layers["slope"][rows, cols]))))
        sc = summary["sample_counts"]
        check(f"{name}: undefined_derivative_count", sc["derivative_undefined_in_analysis"] == ref_undefined,
              f"pipeline {sc['derivative_undefined_in_analysis']}, reference {ref_undefined}")
        result[name] = {"pipeline_seconds": round(time.time() - t0, 1), "per_pixel": pix, "statistics": stat_rows,
                        "pipeline_sample_counts": sc}
        del summary, layers
        gc.collect()
    return result


# ----------------------------------------------------------------------------- diagnostics (no pass/fail)


def diagnostics(z16, num, swb, lats, west, aois, ref_layers, spacing) -> dict:
    out: dict = {}
    area = row_cell_area_m2(lats)
    water = swb == SWB_WATER
    rng = np.random.default_rng(MC_SEED)
    wpad = np.zeros((N + 2, N + 2), dtype=bool)
    wpad[1:-1, 1:-1] = water
    touch = np.zeros((N, N), dtype=bool)  # 3x3 window holds a water sample
    for di in range(3):
        for dj in range(3):
            touch |= wpad[di : di + N, dj : dj + N]
    del wpad
    for name, (rows, cols) in aois.items():
        d: dict = {}
        mask = (z16[rows, cols] != SRTM_VOID) & ~water[rows, cols]
        w_row = area[rows]
        counts = np.bincount(num[rows, cols][mask], minlength=256)
        d["num_code_area_fraction_unweighted"] = {str(k): round(float(counts[k] / counts.sum()), 6)
                                                  for k in np.flatnonzero(counts)}
        sl, tri, rough = (np.asarray(ref_layers[k][rows, cols]) for k in ("slope", "tri", "rough_index"))
        fin = mask & np.isfinite(sl)
        wts = np.broadcast_to(w_row[:, None], sl.shape)
        wfin = float(wts[fin].sum())
        d["area_fraction_slope_exactly_0"] = float(wts[fin & (sl == 0)].sum() / wfin)
        d["area_fraction_tri_exactly_0"] = float(wts[fin & (tri == 0)].sum() / wfin)
        d["area_fraction_roughness_below_1e-9_m"] = float(wts[fin & (rough < 1e-9)].sum() / wfin)
        # Horn gradient noise from 1 m rounding when rounding errors are ~iid U(-0.5, 0.5): sigma = 1/(8 * spacing).
        dx_m, dy_m = float(np.mean(spacing["ew1"][rows])), float(np.nanmean(spacing["ns2"][rows]) / 2)
        d["horn_rounding_sigma_deg"] = {"east_west": math.degrees(math.atan(1 / (8 * dx_m))),
                                        "north_south": math.degrees(math.atan(1 / (8 * dy_m))),
                                        "dx_m": dx_m, "dy_m": dy_m}
        # Monte Carlo floor: each analysed pixel's Horn gradient as a perfect plane, random offset, rounded to 1 m.
        step = 1 if name != "tile" else 3  # subsample the full tile
        sub = (slice(None, None, step), slice(None, None, step))
        keep = fin[sub]
        gx = np.asarray(ref_layers["dzdx"][rows, cols])[sub][keep]
        gy = np.asarray(ref_layers["dzdy"][rows, cols])[sub][keep]
        dxr = np.broadcast_to(spacing["ew1"][rows][sub[0]][:, None], keep.shape)[keep]
        dyr = np.broadcast_to((spacing["ns2"][rows][sub[0]] / 2)[:, None], keep.shape)[keep]
        obs = rough[sub][keep]
        plane = rng.random(gx.size)[:, None] + gx[:, None] * U * dxr[:, None] + gy[:, None] * V * dyr[:, None]
        floor = np.sqrt(np.mean((np.round(plane) @ P_INDEX.T) ** 2, axis=1))
        del plane
        floor_p95 = float(np.percentile(floor, 95))
        d["roughness_quantisation_floor"] = {
            "pixels": int(gx.size), "subsample_step": step,
            "floor_percentiles_m": {f"p{q:g}": float(v) for q, v in zip(PERCENTILES, np.percentile(floor, PERCENTILES))},
            "observed_percentiles_m": {f"p{q:g}": float(v) for q, v in zip(PERCENTILES, np.percentile(obs, PERCENTILES))},
            "floor_p95_m": floor_p95,
            "fraction_observed_at_or_below_floor_p95": float(np.mean(obs <= floor_p95)),
            "rms_floor_m": float(np.sqrt(np.mean(floor**2))),
            "rms_observed_m": float(np.sqrt(np.mean(obs**2))),
        }
        del floor
        # TRI anisotropy: effective baseline TRI / (sqrt(6) |grad|) for 3-15 deg slopes, by aspect.
        grad = np.hypot(gx, gy)
        slp = np.degrees(np.arctan(grad))
        theta = np.arctan2(gy, gx)
        band = (slp >= 3) & (slp <= 15)
        ew_face = band & (np.abs(np.cos(theta)) >= np.cos(np.radians(15)))
        ns_face = band & (np.abs(np.sin(theta)) >= np.cos(np.radians(15)))
        with np.errstate(divide="ignore", invalid="ignore"):
            eff = tri[sub][keep] / (math.sqrt(6.0) * grad)
        d["tri_effective_baseline_m"] = {
            "east_west_facing_median": float(np.median(eff[ew_face])), "east_west_n": int(ew_face.sum()),
            "north_south_facing_median": float(np.median(eff[ns_face])), "north_south_n": int(ns_face.sum()),
            "plane_prediction_east_west_m": dx_m, "plane_prediction_north_south_m": dy_m,
        }
        del gx, gy, grad, slp, theta, eff, obs

        def wstats(layer):
            v = np.asarray(ref_layers[layer][rows, cols])[fin]
            w = wts[fin]
            p50, p95 = np.percentile(v, [50, 95], weights=w, method="inverted_cdf")
            return {"mean": float(np.average(v, weights=w)), "p50": float(p50), "p95": float(p95)}

        d["slope_estimator_sensitivity_deg"] = {k: wstats(layer) for k, layer in
                                                (("horn", "slope"), ("zevenbergen_thorne", "slope_zt"),
                                                 ("least_squares_plane", "slope_ls"))}
        shore = fin & touch[rows, cols]
        d["land_pixels_with_water_in_window"] = int(shore.sum())
        if shore.any():
            d["slope_mean_all_deg"] = d["slope_estimator_sensitivity_deg"]["horn"]["mean"]
            d["slope_mean_excluding_those_deg"] = float(np.average(sl[fin & ~shore], weights=wts[fin & ~shore]))
        out[name] = d
        del sl, tri, rough, fin, shore
        gc.collect()
    del touch
    # SWB/HGT alignment: NASADEM flattens mapped water bodies, so water-water neighbours should share a height.
    eq_h = z16[:, :-1] == z16[:, 1:]
    ww = water[:, :-1] & water[:, 1:]
    ll = ~water[:, :-1] & ~water[:, 1:]
    out["water_alignment"] = {
        "equal_height_fraction_water_water_pairs": float(eq_h[ww].mean()) if ww.any() else None,
        "equal_height_fraction_land_land_pairs": float(eq_h[ll].mean()),
        "water_water_pairs": int(ww.sum()),
        "pairs": "east-west neighbours, whole granule",
    }
    del eq_h, ww, ll
    # Georeferencing plausibility: the town centre should sit on the Red Deer River valley floor.
    rows, cols = aois["drumheller_badlands"]
    zr = z16[rows, cols].astype(np.float64)
    r_t = int(round((lats[0] - DRUMHELLER_TOWN[0]) * 3600))
    c_t = int(round((DRUMHELLER_TOWN[1] - west) * 3600))
    z_t = float(z16[r_t, c_t])
    near = z16[r_t - 30 : r_t + 31, c_t - 30 : c_t + 31]  # +-30 samples: ~0.9 km N-S, ~0.6 km E-W
    out["georeferencing_plausibility"] = {
        "town_coordinates_deg_approx": list(DRUMHELLER_TOWN), "town_sample_row_col": [r_t, c_t],
        "town_elevation_m": z_t, "aoi_percentile_rank_of_town_elevation": float(np.mean(zr <= z_t) * 100),
        "aoi_min_m": float(zr.min()), "aoi_max_m": float(zr.max()),
        "neighbourhood_min_m": float(near.min()), "neighbourhood_max_m": float(near.max()),
    }
    del zr
    # Spatial scale: the same metrics on a 3 arc-second decimation of the tile (~58 x 93 m spacing).
    z3 = z16[::3, ::3].astype(np.float64)
    lats3 = lats[::3]
    lay3, _ = reference_terrain(z3, lats3, step_deg=3 * STEP, metric_roughness=False)
    area3 = row_cell_area_m2(lats3, 3 * STEP)
    idx3 = np.arange(0, N, 3)
    scale = {}
    for name, (rows, cols) in aois.items():
        rsel = (idx3 >= rows.start) & (idx3 < rows.stop)
        csel = (idx3 >= cols.start) & (idx3 < cols.stop)
        s3 = lay3["slope"][np.ix_(rsel, csel)]
        r3 = lay3["rough_index"][np.ix_(rsel, csel)]
        m3 = ~water[::3, ::3][np.ix_(rsel, csel)] & np.isfinite(s3)
        w3 = np.broadcast_to(area3[rsel][:, None], s3.shape)[m3]
        scale[name] = {
            "slope_mean_deg": float(np.average(s3[m3], weights=w3)),
            "slope_p95_deg": float(np.percentile(s3[m3], 95, weights=w3, method="inverted_cdf")),
            "slope_max_deg": float(s3[m3].max()),
            "roughness_detrended_mean_m": float(np.average(r3[m3], weights=w3)),
            "samples": int(m3.sum()),
        }
    out["metrics_at_3_arcsec_decimation"] = scale
    return out


# ----------------------------------------------------------------------------- main


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("zip_path", type=Path)
    ap.add_argument("--outputs", type=Path, default=Path("outputs"), help="directory holding the stored pipeline outputs")
    ap.add_argument("--results", type=Path, default=Path("validation/results/n51w113_validation.json"))
    ap.add_argument("--work-dir", type=Path, default=None, help="scratch directory for memory-mapped layers")
    args = ap.parse_args(argv)
    t_start = time.time()
    checks: list[dict] = []

    def check(name, passed, detail):
        checks.append({"check": name, "passed": bool(passed), "detail": detail})

    def log(msg):
        print(f"[{time.time() - t_start:6.1f}s] {msg}", flush=True)

    # 1. Standard-library read ---------------------------------------------------------------
    members = read_zip_members(args.zip_path)
    check("reader: zip_members_crc32_and_size", True,
          f"{len(members)} members inflated with zlib; CRC-32 and sizes match the central directory")
    by_ext = {Path(k).suffix.lower(): k for k in members}
    hgt_b, num_b, swb_b = members[by_ext[".hgt"]], members[by_ext[".num"]], members[by_ext[".swb"]]
    check("reader: byte_counts", len(hgt_b) == 2 * N * N and len(num_b) == N * N and len(swb_b) == N * N,
          f"hgt {len(hgt_b)} = 2 x {N}^2, num {len(num_b)}, swb {len(swb_b)}")
    south, west = tile_origin(by_ext[".hgt"])
    arr = decode_hgt(hgt_b)
    n_void = arr.count(SRTM_VOID)
    vmin, vmax, vsum = min(arr), max(arr), sum(arr)
    pure = {"void_count": n_void, "min_m": vmin, "max_m": vmax, "mean_m_unweighted_all_samples": vsum / len(arr),
            "samples": len(arr)}
    log(f"stdlib decode: {len(arr)} samples, min {vmin}, max {vmax}, voids {n_void}")
    z16 = np.frombuffer(arr, dtype=np.int16).reshape(N, N)  # native-endian view of the stdlib-decoded values
    num = np.frombuffer(num_b, dtype=np.uint8).reshape(N, N)
    swb = np.frombuffer(swb_b, dtype=np.uint8).reshape(N, N)
    lats, _ = lat_lon(south, west)
    aois = {"tile": aoi_window((west, south, west + 1, south + 1), south, west),
            "drumheller_badlands": aoi_window(DRUMHELLER_BBOX, south, west)}
    log("AOI windows " + ", ".join(f"{k}: rows {v[0].start}-{v[0].stop} cols {v[1].start}-{v[1].stop}"
                                   for k, v in aois.items()))

    stored = {}
    for name, sub in (("tile", "n51w113_tile"), ("drumheller_badlands", "n51w113_drumheller_badlands")):
        stored[name] = json.loads((args.outputs / sub / "terrain_summary.json").read_text(encoding="utf-8"))
    ge = stored["tile"]["granule"]["elevation"]
    check("reader: stored_inspect_summary_vs_pure_python",
          ge["min_m"] == vmin and ge["max_m"] == vmax and ge["void_count"] == n_void
          and within(ge["mean_m_unweighted_all_samples"], pure["mean_m_unweighted_all_samples"], (0, 1e-11)),
          f"stored min/max/mean/voids {ge['min_m']}/{ge['max_m']}/{ge['mean_m_unweighted_all_samples']}/"
          f"{ge['void_count']}; pure Python {vmin}/{vmax}/{pure['mean_m_unweighted_all_samples']:.9f}/{n_void}")
    n_water, n_land = int(np.count_nonzero(swb == SWB_WATER)), int(np.count_nonzero(swb == 0))
    sg = stored["tile"]["granule"]["swb"]
    check("masks: swb_counts_vs_stored", sg["water_count"] == n_water and sg["land_count"] == n_land,
          f"water {n_water}, land {n_land}, other {N * N - n_water - n_land}")
    check("masks: num0_equals_swb255", np.array_equal(num == 0, swb == SWB_WATER), "NUM water code <=> SWB water")
    for name, (rows, cols) in aois.items():
        n_w = int(np.count_nonzero(swb[rows, cols] == SWB_WATER))
        check(f"{name}: water_count_vs_stored", n_w == stored[name]["sample_counts"]["water_samples"],
              f"{n_w} water samples")

    # 2. Reference layers on the whole granule (memory-mapped) ---------------------------------
    work = args.work_dir or Path(tempfile.mkdtemp(prefix="spacethropic_validation_"))
    work.mkdir(parents=True, exist_ok=True)
    ref_layers = {k: np.lib.format.open_memmap(work / f"ref_{k}.npy", mode="w+", dtype=np.float64, shape=(N, N))
                  for k in LAYERS}
    z64 = z16.astype(np.float64)
    _, spacing = reference_terrain(z64, lats, out=ref_layers)
    del z64
    for m in ref_layers.values():
        m.flush()
    gc.collect()
    log("reference layers computed")
    s = ref_layers["slope"]
    edges = bool(np.isnan(s[[0, N - 1], :]).all() and np.isnan(s[:, [0, N - 1]]).all())
    inner = int(np.count_nonzero(np.isnan(s[1:-1, 1:-1])))
    check("reference: only_granule_edges_undefined", edges and inner == 0,
          f"outer rows/cols undefined: {edges}; undefined interior samples: {inner}")

    # 3. Reference statistics ----------------------------------------------------------------
    area = row_cell_area_m2(lats)
    ref_stats: dict = {}
    extra: dict = {}
    for name, (rows, cols) in aois.items():
        mask = (z16[rows, cols] != SRTM_VOID) & (swb[rows, cols] != SWB_WATER)
        ref_stats[name] = {}
        for meas, layer in (("elevation", z16), ("slope", ref_layers["slope"]), ("roughness_tri", ref_layers["tri"]),
                            ("roughness_detrended", ref_layers["rough_index"])):
            ref_stats[name][meas] = reference_stats(layer[rows, cols], area[rows], mask)
            gc.collect()
        e = z16[rows, cols][mask].astype(np.float64)
        extra[name] = {
            "roughness_detrended_metric_window": reference_stats(ref_layers["rough_metric"][rows, cols], area[rows], mask),
            "elevation_unweighted_mean": float(e.mean()),
            "elevation_unweighted_linear_percentiles": {f"p{q:g}": float(v)
                                                        for q, v in zip(PERCENTILES, np.percentile(e, PERCENTILES))},
        }
        del e
        gc.collect()
        log(f"reference statistics: {name}")

    # 4. Diagnostics ---------------------------------------------------------------------------
    diag = diagnostics(z16, num, swb, lats, west, aois, ref_layers, spacing)
    gc.collect()
    log("diagnostics done")

    # 5. Pipeline comparison -------------------------------------------------------------------
    comparison = compare_with_pipeline(args.zip_path, hgt_b, z16, num, swb, south, west, aois, ref_layers,
                                       ref_stats, stored, check)
    log("pipeline comparison done")

    results = {
        "task": "DRUMHELLER-PILOT-02 independent verification",
        "zip_file": args.zip_path.name,
        "tile_origin_south_west_deg": [south, west],
        "aoi_windows": {k: {"rows": [v[0].start, v[0].stop], "cols": [v[1].start, v[1].stop]} for k, v in aois.items()},
        "pure_python_hgt_summary": pure,
        "checks": checks,
        "all_checks_passed": all(c["passed"] for c in checks),
        "reference_statistics": ref_stats,
        "reference_extra": extra,
        "comparison": comparison,
        "diagnostics": diag,
        "tolerances": {
            "per_pixel_abs": PIXEL_TOL,
            "statistics": "exact for counts and integer-valued elevation statistics; 1e-9 relative for elevation "
                          "mean/std and areas; 1e-6 relative for float32-layer mean/std; 1e-5 absolute for "
                          "float32-layer min/max/percentiles",
        },
        "software": {"python": sys.version.split()[0], "numpy": np.__version__},
        "runtime_s": round(time.time() - t_start, 1),
    }
    del s
    ref_layers.clear()
    gc.collect()
    if args.work_dir is None:
        shutil.rmtree(work, ignore_errors=True)
    args.results.parent.mkdir(parents=True, exist_ok=True)
    args.results.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    failed = [c["check"] for c in checks if not c["passed"]]
    print(f"{len(checks)} checks: {len(checks) - len(failed)} passed, {len(failed)} failed")
    for c in checks:
        print(f"  [{'PASS' if c['passed'] else 'FAIL'}] {c['check']}: {c['detail']}")
    print(f"wrote {args.results}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
