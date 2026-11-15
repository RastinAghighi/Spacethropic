"""Contour lines for the whole Moon and Mars on hexagons of Earth's H3 r8 size.

Grid ("Earth-r8 hexagons", user rule: copy Earth r8 dimensions unchanged onto other bodies):
regular hexagons with the area of Earth's average H3 r8 cell (0.7373 km^2, edge 532.7 m),
laid in rows of constant latitude 1.5 edges apart; within a row, centres sqrt(3) edges apart
in true distance, odd rows offset by half a cell. Every elevation pixel belongs to its nearest
centre, so cells tile the surface without gaps (cells on seams between rows of different
counts are slightly irregular). Cell id = row << 32 | col (not an H3 index).

Elevation: the global mosaics the pipeline already uses (LOLA 118 m for the Moon, HRSC+MOLA
200 m for Mars), downloaded once by data/raw/global/planet/download.py (they are striped files
with no overviews, so range reads are slow). Each level area-averages them to a pixel size.

Per tile (moon 5 deg, mars 3 deg; one full-longitude tile per band near the poles):
  1. list hexagon centres in the tile
  2. read the tile + a 2-edge margin from the local mosaic at the level's pixel size
  3. assign pixels to the nearest centre, trace contours (fixed absolute heights, every
     --interval m above the body's reference sphere/areoid) inside each hexagon
  4. write <tile>.hexes.parquet + <tile>.lines.parquet (same schema as contours_r8.py), log done

Usage: uv run python analysis/contours_planet.py --bodies moon,mars [--levels 240m,native]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from datetime import datetime, timezone
from pathlib import Path

for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")
os.environ.setdefault("GDAL_CACHEMAX", "128")

import contourpy  # noqa: E402
import h3  # noqa: E402
import numpy as np  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402
import rasterio  # noqa: E402
from rasterio.enums import Resampling  # noqa: E402
from rasterio.windows import Window  # noqa: E402
from scipy.ndimage import find_objects  # noqa: E402

import contours_r8 as earth  # noqa: E402  (schemas, memory gate, manifest writer)

ROOT = Path(__file__).resolve().parents[1]
DEM_DIR = ROOT / "data" / "raw" / "global" / "planet"
RES = earth.H3_RES  # HEX_RES env var (default 8); user rule: Earth's mean cell at that resolution, 1:1 on every body
OUT_ROOT = ROOT / "data" / "out" / ("contours_planet" if RES == 8 else f"contours_planet_r{RES}")

AREA_M2 = h3.average_hexagon_area(RES, unit="m^2")     # Earth's mean cell at RES
EDGE_M = math.sqrt(2 * AREA_M2 / (3 * math.sqrt(3)))   # regular hexagon with that area
ROW_M, COL_M = 1.5 * EDGE_M, math.sqrt(3) * EDGE_M

BODIES = {
    "moon": {"R": 1737400.0, "dem": "moon_lola118.tif", "tile_deg": 5, "polar_from": 80,
             "datum": "LOLA heights relative to the 1737.4 km sphere"},
    "mars": {"R": 3396190.0, "dem": "mars_hrsc_mola200.tif", "tile_deg": 3, "polar_from": 81,
             "datum": "HRSC+MOLA heights relative to the MOLA areoid"},
}


class Grid:
    def __init__(self, R: float):
        self.R = R
        self.nrows = round(math.pi * R / ROW_M)
        self.dlat = 180.0 / self.nrows

    def row_lat(self, i):
        return -90.0 + (np.asarray(i) + 0.5) * self.dlat

    def ncols(self, i):
        return np.maximum(1, np.round(2 * math.pi * self.R * np.cos(np.radians(self.row_lat(i))) / COL_M)).astype(np.int64)

    def col_lon(self, i, j):
        n = self.ncols(i)
        return ((-180.0 + (np.asarray(j) + 0.5 + 0.5 * (np.asarray(i) % 2)) * 360.0 / n) + 180.0) % 360.0 - 180.0

    def centres_in(self, lat0, lat1, lon0, lon1):
        rows = np.arange(math.ceil((lat0 + 90) / self.dlat - 0.5), math.ceil((lat1 + 90) / self.dlat - 0.5))
        rows = rows[(rows >= 0) & (rows < self.nrows)]
        ii, jj = [], []
        for i in rows:
            n = int(self.ncols(i))
            w, off = 360.0 / n, 0.5 + 0.5 * (i % 2)
            if lon1 - lon0 >= 360:
                j = np.arange(n)
            else:
                # one extra column each side, then keep exactly the centres whose wrapped
                # longitude is in [lon0, lon1): every cell lands in exactly one tile
                j = np.arange(math.floor((lon0 + 180) / w - off) - 1, math.ceil((lon1 + 180) / w - off) + 1) % n
                j = np.unique(j)
                lon = self.col_lon(i, j)
                j = j[(lon >= lon0) & (lon < lon1)]
            ii.append(np.full(j.size, i))
            jj.append(j)
        if not ii:
            return np.zeros(0, np.int64), np.zeros(0, np.int64)
        return np.concatenate(ii).astype(np.int64), np.concatenate(jj).astype(np.int64)

    def nearest(self, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
        """Cell id (row << 32 | col) of the nearest centre for each (lat, lon) grid point
        (lat: (h,), lon: (w,) 1-D axes). The nearest centre is always in one of the two
        nearest rows: a third row is >= 2.25 edges away, a same-row neighbour <= 1.15."""
        h, w = lat.size, lon.size
        best_d = np.full((h, w), np.inf, np.float32)
        best = np.zeros((h, w), np.int64)
        base = np.floor((lat + 90) / self.dlat - 0.5).astype(np.int64)
        for k in (0, 1):
            i = np.clip(base + k, 0, self.nrows - 1)
            n = self.ncols(i)[:, None]
            off = (0.5 + 0.5 * (i % 2))[:, None]
            j = np.round((lon[None, :] + 180.0) / (360.0 / n) - off).astype(np.int64) % n
            clon = self.col_lon(i[:, None], j)
            clat = self.row_lat(i)[:, None]
            dlon = (lon[None, :] - clon + 180.0) % 360.0 - 180.0
            dx = np.radians(dlon) * np.cos(np.radians((lat[:, None] + clat) / 2))
            dy = np.radians(lat[:, None] - clat)
            d = (dx * dx + dy * dy).astype(np.float32)
            better = d < best_d
            best_d[better] = d[better]
            best[better] = ((np.broadcast_to(i[:, None], j.shape) << 32) | j)[better]
        return best


def plan(body: str) -> list[tuple[int, int, int, int]]:
    b = BODIES[body]
    s, polar = b["tile_deg"], b["polar_from"]
    tiles = []
    for lat0 in range(-90, 90, s):
        if lat0 >= polar or lat0 + s <= -polar:
            tiles.append((lat0, lat0 + s, -180, 180))
        else:
            tiles += [(lat0, lat0 + s, lon0, lon0 + s) for lon0 in range(-180, 180, s)]
    return tiles


def tile_id(body, t) -> str:
    lat0, _, lon0, lon1 = t
    return f"{body}_{lat0:+03d}_{'all' if lon1 - lon0 >= 360 else f'{lon0:+04d}'}"


def read_dem(body: str, lat0, lat1, lon0, lon1, pixel_m: float | None):
    """Area-averaged elevation on a regular lat/lon grid covering the bounds (lon may run past
    +-180; wrapped pieces are read separately). Returns (elev, lat_axis, lon_axis)."""
    b = BODIES[body]
    R = b["R"]
    path = DEM_DIR / b["dem"]
    with rasterio.open(path) as src:
        t = src.transform
        deg = src.crs.is_geographic
        to_deg = (lambda v: v) if deg else (lambda v: np.degrees(v / R))
        px_deg = abs(t.a) if deg else math.degrees(abs(t.a) / R)  # native pixel, degrees
        if pixel_m is None:
            step_lat = px_deg
        else:
            step_lat = max(math.degrees(pixel_m / R), px_deg)
        coslat = max(math.cos(math.radians(min(abs(lat0), abs(lat1)) if lat0 * lat1 > 0 else 0.0)), 0.02)
        step_lon = max(step_lat / coslat, px_deg) if lon1 - lon0 < 360 else max(step_lat / max(coslat, 0.02), px_deg)
        if lon1 - lon0 >= 360:
            lon0, lon1 = -180.0, 180.0
        pieces, segs = [], []
        if lon0 < -180:
            segs.append((lon0 + 360, 180.0, -360.0))
        segs.append((max(lon0, -180.0), min(lon1, 180.0), 0.0))
        if lon1 > 180:
            segs.append((-180.0, lon1 - 360, 360.0))
        lat0c, lat1c = max(lat0, -90.0), min(lat1, 90.0)
        x_of = (lambda lo: lo) if deg else (lambda lo: math.radians(lo) * R)
        col = lambda x: (x - t.c) / t.a  # noqa: E731
        row = lambda y: (y - t.f) / t.e  # noqa: E731
        r0 = max(int(math.floor(row(x_of(lat1c)))), 0)
        r1 = min(int(math.ceil(row(x_of(lat0c)))), src.height)
        nrows_out = max(int(round((r1 - r0) * px_deg / step_lat)), 1)
        lat_axis = to_deg(t.f + (r0 + (np.arange(nrows_out) + 0.5) * (r1 - r0) / nrows_out) * t.e)
        for a, z, shift in segs:
            c0 = max(int(math.floor(col(x_of(a)))), 0)
            c1 = min(int(math.ceil(col(x_of(z)))), src.width)
            if c1 <= c0:
                continue
            ncols_out = max(int(round((c1 - c0) * px_deg / step_lon)), 1)
            arr = src.read(1, window=Window(c0, r0, c1 - c0, r1 - r0), out_shape=(nrows_out, ncols_out),
                           resampling=Resampling.average, masked=True)
            arr = (arr.astype(np.float32) * np.float32(src.scales[0]) + np.float32(src.offsets[0])).filled(np.nan)
            lon_axis = to_deg(t.c + (c0 + (np.arange(ncols_out) + 0.5) * (c1 - c0) / ncols_out) * t.a) + shift
            pieces.append((lon_axis, arr))
    lon_axis = np.concatenate([p[0] for p in pieces])
    elev = np.concatenate([p[1] for p in pieces], axis=1)
    return elev, lat_axis, lon_axis


def process_tile(body: str, t, level: str, interval: float, out_dir: str) -> dict:
    t0 = time.time()
    b = BODIES[body]
    R = b["R"]
    grid = Grid(R)
    lat0, lat1, lon0, lon1 = t
    name = tile_id(body, t)
    ii, jj = grid.centres_in(lat0, lat1, lon0, lon1)
    ids = (ii << 32) | jj
    order = np.argsort(ids)
    ids, ii, jj = ids[order], ii[order], jj[order]
    clat, clon = grid.row_lat(ii), grid.col_lon(ii, jj)

    hex_rows = {f.name: [] for f in earth.HEX_SCHEMA}
    pts_x, pts_y, offs, l_hex, l_lev, l_closed = [], [], [0], [], [], []
    if ids.size:
        m_deg = math.degrees(2.5 * EDGE_M / R)
        full = lon1 - lon0 >= 360
        mlon = 0 if full else m_deg / max(math.cos(math.radians(max(abs(lat0), abs(lat1)))), 0.02)
        elev, lat_ax, lon_ax = read_dem(body, lat0 - m_deg, lat1 + m_deg,
                                        lon0 - mlon, lon1 + mlon, None if level == "native" else float(level[:-1]))
        cell = grid.nearest(lat_ax, ((lon_ax + 180) % 360) - 180)
        idx = np.searchsorted(ids, cell)
        idx_c = np.clip(idx, 0, ids.size - 1)
        labels = np.where(ids[idx_c] == cell, idx_c + 1, 0).astype(np.int32)
        slices = find_objects(labels, max_label=ids.size)
        for k in range(ids.size):
            sl = slices[k]
            n_px, stats, n_lines = 0, (np.nan, np.nan, np.nan), 0
            if sl is not None:
                sub = elev[sl]
                valid = (labels[sl] == k + 1) & np.isfinite(sub)
                n_px = int(valid.sum())
                if n_px:
                    v = sub[valid]
                    stats = (float(v.min()), float(v.mean()), float(v.max()))
                if n_px and min(sub.shape) >= 2 and stats[2] > stats[0]:
                    la = lat_ax[sl[0]]
                    lo = lon_ax[sl[1]]
                    x = np.radians((lo - clon[k] + 180) % 360 - 180) * math.cos(math.radians(clat[k])) * R
                    y = np.radians(la - clat[k]) * R
                    z = np.ma.masked_array(np.where(valid, sub, 0.0), ~valid)
                    levels = np.arange(math.ceil(stats[0] / interval) * interval, stats[2], interval)
                    if levels.size:
                        gen = contourpy.contour_generator(x, y, z, line_type="ChunkCombinedOffset")
                        for lev, (points, offsets) in zip(levels, gen.multi_lines(levels)):
                            p, o = points[0], offsets[0]
                            if p is None:
                                continue
                            for a_, b_ in zip(o[:-1], o[1:]):
                                seg = p[a_:b_]
                                pts_x.append(seg[:, 0].astype(np.float32))
                                pts_y.append(seg[:, 1].astype(np.float32))
                                offs.append(offs[-1] + (b_ - a_))
                                l_hex.append(int(ids[k]))
                                l_lev.append(lev)
                                l_closed.append(bool(np.array_equal(seg[0], seg[-1])))
                                n_lines += 1
            for key, val in zip(earth.HEX_SCHEMA.names, (int(ids[k]), float(clat[k]), float(clon[k]), 0.0,
                                                        n_px, *stats, n_lines)):
                hex_rows[key].append(val)

    o = np.asarray(offs, np.int32)
    xs = np.concatenate(pts_x) if pts_x else np.zeros(0, np.float32)
    ys = np.concatenate(pts_y) if pts_y else np.zeros(0, np.float32)
    lines = pa.table([
        pa.array(l_hex, pa.uint64()), pa.array(l_lev, pa.float32()), pa.array(l_closed, pa.bool_()),
        pa.ListArray.from_arrays(pa.array(o), pa.array(xs)), pa.ListArray.from_arrays(pa.array(o), pa.array(ys)),
    ], schema=earth.LINE_SCHEMA)
    hexes = pa.table({k_: pa.array(v_, earth.HEX_SCHEMA.field(k_).type) for k_, v_ in hex_rows.items()},
                     schema=earth.HEX_SCHEMA)
    out = Path(out_dir)
    for tbl, suffix in ((hexes, "hexes"), (lines, "lines")):
        final = out / f"{name}.{suffix}.parquet"
        tmp = final.with_suffix(".tmp")
        pq.write_table(tbl, tmp, compression="zstd")
        os.replace(tmp, final)
    return {"tile": name, "hexes_in_tile": int(ids.size), "hexes_kept": int(ids.size),
            "lines": len(l_hex), "points": int(xs.size), "seconds": round(time.time() - t0, 2)}


def run_level(body: str, level: str, interval: float, workers: int, root: Path, limit: int | None) -> str:
    base = root / f"{body}_{level}_i{interval:g}m"
    out = base / "tiles"
    out.mkdir(parents=True, exist_ok=True)
    done_path, err_path = base / "done.txt", base / "errors.txt"
    done = set(done_path.read_text().split()) if done_path.exists() else set()
    tiles = plan(body)[:limit]
    todo = [t for t in tiles if tile_id(body, t) not in done]
    info = json.loads((base / "manifest.json").read_text()) if (base / "manifest.json").exists() else {}
    totals = info.get("totals", {"hexes_kept": 0, "lines": 0, "points": 0})
    info.update({
        "body": body, "level": level, "contour_interval_m": interval, "datum": BODIES[body]["datum"],
        "hexagon": {"area_m2": AREA_M2, "edge_m": EDGE_M, "rule": f"Earth H3 r{RES} mean cell size, unchanged",
                    "id": "row << 32 | col (row: constant-latitude ring from the south pole)"},
        "dem": BODIES[body]["dem"], "tiles_total": len(tiles), "status": "running",
        "started": info.get("started", datetime.now(timezone.utc).isoformat(timespec="seconds")),
    })
    print(f"[{body} {level}] {len(todo)} of {len(tiles)} tiles to do", flush=True)
    t_start, last, n_ok, fails = time.time(), 0.0, 0, {}
    while todo and info["status"] == "running":
        broken = False
        with ProcessPoolExecutor(workers) as ex, \
                open(done_path, "a") as dl, open(err_path, "a") as el:
            queue, futs = list(todo), {}
            while queue or futs:
                while queue and len(futs) < workers and (not futs or earth.memory_ok()):
                    t = queue.pop(0)
                    try:
                        futs[ex.submit(process_tile, body, t, level, interval, str(out))] = t
                    except BrokenProcessPool:
                        broken = True
                        break
                if broken:
                    break
                if not futs:
                    time.sleep(5)
                    continue
                finished, _ = wait(futs, timeout=10, return_when=FIRST_COMPLETED)
                for f in finished:
                    t = futs.pop(f)
                    try:
                        r = f.result()
                    except BrokenProcessPool:
                        broken = True
                        continue
                    except Exception:
                        fails[t] = fails.get(t, 0) + 1
                        el.write(f"{tile_id(body, t)}\n{traceback.format_exc()}\n")
                        el.flush()
                        continue
                    dl.write(r["tile"] + "\n")
                    dl.flush()
                    done.add(r["tile"])
                    n_ok += 1
                    for k in totals:
                        totals[k] += r[k]
                if broken:
                    break
                if time.time() - last > 30 and n_ok:
                    last = time.time()
                    left = len(tiles) - len(done)
                    info.update({"tiles_done": len(done), "totals": totals,
                                 "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                 "eta_hours": round(left / max(n_ok / (last - t_start), 1e-9) / 3600, 2)})
                    earth.write_manifest(base / "manifest.json", info)
                    print(f"[{body} {level}] {len(done)}/{len(tiles)} tiles, {totals['hexes_kept']:,} hexes, "
                          f"{totals['lines']:,} lines, eta {info['eta_hours']} h", flush=True)
        todo = [t for t in todo if tile_id(body, t) not in done and fails.get(t, 0) < earth.MAX_TRIES]
        if broken:
            print(f"[{body} {level}] worker pool crashed; restarting with {len(todo)} tiles", flush=True)
    ndone = len(set(done_path.read_text().split()))
    info.update({"tiles_done": ndone, "totals": totals, "status": "complete" if ndone == len(tiles) else "incomplete",
                 "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    earth.write_manifest(base / "manifest.json", info)
    print(f"[{body} {level}] {info['status']}: {ndone}/{len(tiles)} tiles", flush=True)
    return info["status"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bodies", default="moon,mars")
    ap.add_argument("--levels", default="240m,native", help="pixel sizes, e.g. 240m,native")
    ap.add_argument("--interval", type=float, default=20.0)
    ap.add_argument("--workers", type=int, default=15)
    ap.add_argument("--limit", type=int, help="first N tiles only (testing)")
    ap.add_argument("--out", type=Path, default=OUT_ROOT)
    a = ap.parse_args()
    for level in a.levels.split(","):
        for body in a.bodies.split(","):
            run_level(body, level, a.interval, a.workers, a.out, a.limit)


if __name__ == "__main__":
    main()
