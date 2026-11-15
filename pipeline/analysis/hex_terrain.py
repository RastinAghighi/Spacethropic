"""Terrain columns per R8 hexagon (user: "use R8 resolution as final"), all bodies together.

For every hexagon table (Earth contours_r8_v2 8x/4x, Moon and Mars 240m/native), re-read the
same elevation grid that table's contours were traced from, compute per pixel
  slope_deg  = atan(|gradient|) with true metre spacing per row
  tri_m      = mean |dz| to the 8 neighbours (Terrain Ruggedness Index, as features.py)
on the whole tile mosaic (so pixels at a hexagon edge see their real neighbours), then summarise
over each hexagon's own pixels with the site pipeline's terrain columns:
  elevation_m__std, slope_deg__{mean,std,p10,p50,p90}, tri_m__{mean,std,p10,p50,p90}
Scale note: slope/TRI depend on pixel size; each table uses its own level (Earth 8x 240 m,
4x 120 m; Moon 240 m / 118 m; Mars 240 m / 200 m), recorded in the manifest.

Usage: uv run python analysis/hex_terrain.py [--workers 20]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path

for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")
os.environ.setdefault("GDAL_CACHEMAX", "128")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contours_planet as planet  # noqa: E402
import contours_r8 as earth  # noqa: E402
import h3  # noqa: E402
import numpy as np  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402
from rasterio.features import rasterize  # noqa: E402
from scipy.ndimage import find_objects  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "out"
STATS = ("mean", "std", "p10", "p50", "p90")
COLS = ["elevation_m__std"] + [f"{l}__{s}" for l in ("slope_deg", "tri_m") for s in STATS]
DATASETS = [  # (body, level, folder)
    ("earth", "8x", OUT / "contours_r8_v2" / "8x_i20m"),
    ("earth", "4x", OUT / "contours_r8_v2" / "4x_i20m"),
    ("moon", "240m", OUT / "contours_planet" / "moon_240m_i20m"),
    ("moon", "native", OUT / "contours_planet" / "moon_native_i20m"),
    ("mars", "240m", OUT / "contours_planet" / "mars_240m_i20m"),
    ("mars", "native", OUT / "contours_planet" / "mars_native_i20m"),
]


def slope_tri(z: np.ndarray, dy_m: float, dx_m: np.ndarray):
    """z (h, w) float32 with NaN; dx_m per row (h,). Returns slope_deg, tri_m (float32)."""
    gy, gx = np.gradient(z.astype(np.float64), axis=(0, 1))
    slope = np.degrees(np.arctan(np.hypot(gy / dy_m, gx / dx_m[:, None]))).astype(np.float32)
    p = np.pad(z, 1, constant_values=np.nan)
    h, w = z.shape
    acc = np.zeros((h, w), np.float32)
    n = np.zeros((h, w), np.float32)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy or dx:
                d = np.abs(p[1 + dy:1 + dy + h, 1 + dx:1 + dx + w] - z)
                ok = np.isfinite(d)
                acc[ok] += d[ok]
                n += ok
    tri = np.where((n > 0) & np.isfinite(z), acc / np.maximum(n, 1), np.nan).astype(np.float32)
    return slope, tri


def summarise(labels: np.ndarray, n: int, elev, slope, tri) -> np.ndarray:
    """(n, len(COLS)) per-label stats over valid pixels."""
    out = np.full((n, len(COLS)), np.nan, np.float32)
    for k, sl in enumerate(find_objects(labels, max_label=n)):
        if sl is None:
            continue
        inside = labels[sl] == k + 1
        e = elev[sl][inside]
        e = e[np.isfinite(e)]
        if e.size:
            out[k, 0] = e.std()
        for b, arr in enumerate((slope, tri)):
            v = arr[sl][inside]
            v = v[np.isfinite(v)]
            if v.size:
                p10, p50, p90 = np.percentile(v, [10, 50, 90])
                out[k, 1 + 5 * b:6 + 5 * b] = (v.mean(), v.std(), p10, p50, p90)
    return out


def earth_tile(name: str, level: str):
    lat = int(name[23:25]) * (1 if name[22] == "N" else -1)
    lon = int(name[30:33]) * (1 if name[29] == "E" else -1)
    existing = earth.existing_tiles()
    shape = h3.LatLngPoly([(lat, lon), (lat, lon + 1), (lat + 1, lon + 1), (lat + 1, lon)])
    cells = sorted(h3.polygon_to_cells(shape, earth.H3_RES))
    if not cells:
        return np.zeros(0, np.uint64), np.zeros((0, len(COLS)), np.float32)
    polys = earth.hex_polygons(cells, lon + 0.5)
    xs = [x for p in polys for x, _ in p["coordinates"][0]]
    ys = [y for p in polys for _, y in p["coordinates"][0]]
    frac = earth.removed_fraction(polys, (min(xs), min(ys), max(xs), max(ys)), lat + 0.5)
    keep = np.nonzero(frac < earth.REMOVE_AT)[0]
    if not keep.size:
        return np.zeros(0, np.uint64), np.zeros((0, len(COLS)), np.float32)
    kp = [polys[i] for i in keep]
    kx = [x for p in kp for x, _ in p["coordinates"][0]]
    ky = [y for p in kp for _, y in p["coordinates"][0]]
    pad = 0.004  # one extra pixel ring beyond the contour pass so edge gradients are real
    bounds = (min(kx) - pad, max(min(ky) - pad, -90), max(kx) + pad, min(max(ky) + pad, 90))
    elev, T, _ = earth.read_elevation(bounds, earth.LEVELS[level], existing)
    labels = rasterize(((p, j + 1) for j, p in enumerate(kp)), out_shape=elev.shape, transform=T, fill=0, dtype="int32")
    rows_lat = T.f + (np.arange(elev.shape[0]) + 0.5) * T.e
    dy = abs(T.e) * earth.M_PER_DEG
    dx = T.a * np.cos(np.radians(rows_lat)) * earth.M_PER_DEG
    slope, tri = slope_tri(elev, dy, dx)
    ids = np.array([h3.str_to_int(cells[i]) for i in keep], np.uint64)
    return ids, summarise(labels, keep.size, elev, slope, tri)


def planet_tile(body: str, name: str, level: str):
    t = next(tt for tt in planet.plan(body) if planet.tile_id(body, tt) == name)
    R = planet.BODIES[body]["R"]
    grid = planet.Grid(R)
    lat0, lat1, lon0, lon1 = t
    ii, jj = grid.centres_in(lat0, lat1, lon0, lon1)
    ids = (ii << 32) | jj
    ids.sort()
    m_deg = math.degrees(2.5 * planet.EDGE_M / R) + 0.01
    full = lon1 - lon0 >= 360
    mlon = 0 if full else m_deg / max(math.cos(math.radians(max(abs(lat0), abs(lat1)))), 0.02)
    elev, lat_ax, lon_ax = planet.read_dem(body, lat0 - m_deg, lat1 + m_deg, lon0 - mlon, lon1 + mlon,
                                           None if level == "native" else float(level[:-1]))
    cell = grid.nearest(lat_ax, ((lon_ax + 180) % 360) - 180)
    idx = np.clip(np.searchsorted(ids, cell), 0, ids.size - 1)
    labels = np.where(ids[idx] == cell, idx + 1, 0).astype(np.int32)
    dy = abs(np.radians(lat_ax[1] - lat_ax[0])) * R if lat_ax.size > 1 else 1.0
    dlon = np.radians(np.median(np.diff(lon_ax))) if lon_ax.size > 1 else 1.0
    dx = np.maximum(dlon * np.cos(np.radians(lat_ax)) * R, 1.0)
    slope, tri = slope_tri(elev, dy, dx)
    return ids.astype(np.uint64), summarise(labels, ids.size, elev, slope, tri)


def update(body: str, level: str, folder: str, tile: str) -> int:
    ids, vals = earth_tile(tile, level) if body == "earth" else planet_tile(body, tile, level)
    path = Path(folder) / "tiles" / f"{tile}.hexes.parquet"
    t = pq.read_table(path)
    hexes = t.column("hex").to_numpy()
    order = np.argsort(ids)
    pos = np.clip(np.searchsorted(ids[order], hexes), 0, max(ids.size - 1, 0))
    match = ids.size > 0
    for c, col in enumerate(COLS):
        v = np.full(hexes.size, np.nan, np.float32)
        if match:
            hit = ids[order][pos] == hexes
            v[hit] = vals[order][pos[hit], c]
        arr = pa.array(v, pa.float32())
        t = t.set_column(t.schema.get_field_index(col), col, arr) if col in t.column_names else t.append_column(col, arr)
    tmp = str(path) + ".tmp"
    pq.write_table(t, tmp, compression="zstd")
    os.replace(tmp, path)
    return int(np.isfinite(t.column("slope_deg__mean").to_numpy(zero_copy_only=False)).sum())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=20)
    ap.add_argument("--limit", type=int, help="first N tiles per dataset (testing)")
    a = ap.parse_args()
    log_dir = ROOT / "data" / "interim" / "global"
    done_path = log_dir / "terrain_done.txt"
    done = set(done_path.read_text().split()) if done_path.exists() else set()

    queues = []
    for body, level, folder in DATASETS:
        if (folder / "done.txt").exists():
            tiles = (folder / "done.txt").read_text().split()[: a.limit]
            queues.append([(body, level, str(folder), t) for t in tiles if f"{folder.name}/{t}" not in done])
    jobs = []
    while any(queues):  # interleave datasets so all bodies advance together
        for q in queues:
            if q:
                jobs.append(q.pop(0))
    print(f"terrain: {len(jobs)} tile tables to do", flush=True)

    t0, n_ok, last = time.time(), 0, 0.0
    errors = open(log_dir / "terrain_errors.txt", "a")
    with ProcessPoolExecutor(a.workers) as ex, open(done_path, "a") as dl:
        queue, futs = list(jobs), {}
        while queue or futs:
            while queue and len(futs) < a.workers and (not futs or earth.memory_ok()):
                j = queue.pop(0)
                futs[ex.submit(update, *j)] = j
            if not futs:
                time.sleep(5)
                continue
            finished, _ = wait(futs, timeout=10, return_when=FIRST_COMPLETED)
            for f in finished:
                body, level, folder, tile = futs.pop(f)
                try:
                    f.result()
                except Exception:
                    errors.write(f"{folder} {tile}\n{traceback.format_exc()}\n")
                    errors.flush()
                    continue
                dl.write(f"{Path(folder).name}/{tile}\n")
                dl.flush()
                n_ok += 1
            if time.time() - last > 60:
                last = time.time()
                print(f"terrain: {n_ok}/{len(jobs)} tables, eta {(len(jobs) - n_ok) / max(n_ok / (last - t0), 1e-9) / 3600:.2f} h", flush=True)

    for body, level, folder in DATASETS:
        mp = folder / "manifest.json"
        if mp.exists():
            m = json.loads(mp.read_text())
            px = {"8x": "~240 m", "4x": "~120 m", "240m": "240 m", "native": "118 m (Moon) / 200 m (Mars)"}[level]
            m.setdefault("features", {})["terrain"] = {
                "columns": COLS,
                "source": f"per R8 hexagon from the elevation pixels inside it ({px}); slope = atan(|grad|), "
                          "tri = mean |dz| to 8 neighbours, computed on the whole tile mosaic"}
            tmp = mp.with_suffix(".tmp")
            tmp.write_text(json.dumps(m, indent=2))
            os.replace(tmp, mp)
    print("terrain: done", flush=True)


if __name__ == "__main__":
    main()
