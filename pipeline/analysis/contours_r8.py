"""Streaming contour lines for every kept Earth H3 r8 hexagon, coarse to fine.

For each Copernicus GLO-30 1-degree tile touching kept land (data/out/global_mask/kept.tif):
  1. list the r8 hexagons whose centre lies in the tile (each hexagon belongs to one tile)
  2. drop a hexagon if >= 90% of its area is removed land (ocean / populated / vegetated),
     measured on a ~0.001 deg sample grid, so the hexagon set is the same at every level
  3. read the tile's elevation at the chosen overview level, plus a thin border from its
     neighbours so edge hexagons are complete (range reads; the tile is never stored)
  4. trace contour lines at fixed absolute heights (every --interval m, EGM2008) inside each
     hexagon, in float32 metres east/north of the hexagon centre
  5. write <tile>.lines.parquet + <tile>.hexes.parquet atomically, then log the tile as done

Levels run one after another (default 8x -> 4x -> 2x -> full); each is a complete dataset in
its own folder. Finished tiles can be handed off at any time; a rerun skips done tiles.

Usage: uv run python analysis/contours_r8.py [--levels 8x,4x,2x,full] [--interval 20]
                                             [--workers 16] [--tiles NAME,...] [--limit N]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "8")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "3")
os.environ.setdefault("VSI_CACHE", "TRUE")
# Many worker processes: one BLAS thread and a small GDAL block cache each, or RAM runs out.
for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")
os.environ.setdefault("GDAL_CACHEMAX", "128")

import contourpy  # noqa: E402
import h3  # noqa: E402
import numpy as np  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402
import rasterio  # noqa: E402
import requests  # noqa: E402
from rasterio.features import rasterize  # noqa: E402
from rasterio.warp import Resampling, reproject  # noqa: E402
from rasterio.windows import from_bounds  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from rasterio.transform import from_origin  # noqa: E402
from scipy.ndimage import binary_dilation, find_objects  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
# v2 = land-cover mask (global_mask_v2.py). The v1 (NDVI) results stay in data/out/contours_r8/.
# Workers are spawned processes, so the mask path travels in an environment variable.
# Hexagon resolution travels in HEX_RES (spawned workers inherit it); unset = r8, the original run.
H3_RES = int(os.environ.get("HEX_RES", "8"))
OUT_ROOT = ROOT / "data" / "out" / ("contours_r8_v2" if H3_RES == 8 else f"contours_r{H3_RES}_v2")
KEPT = Path(os.environ.get("CONTOURS_MASK", ROOT / "data" / "out" / "global_mask_v2" / "kept.tif"))
BUCKET = "https://copernicus-dem-30m.s3.amazonaws.com"

REMOVE_AT = 0.9       # drop a hexagon when this share of its area is removed land
SAMPLE_DEG = 0.001    # sample grid for the removed-area share (~110 m in latitude)
R_M = 6371007.180918475
M_PER_DEG = math.pi / 180 * R_M
NODATA = -32767.0
MIN_FREE_GB = 25      # stop a run before the disk fills
MAX_TRIES = 3         # per tile, per run
MIN_AVAIL_RAM_GB = 0.5   # below this, Windows pages heavily (slow, not a crash)
MIN_COMMIT_GB = 4.0      # commit headroom (RAM + pagefile): running out of this is what crashes; a full tile peaks ~0.5 GB

# Overview index inside the Copernicus COGs (2x, 4x, 8x); None = full 30 m (1 arc-second).
LEVELS = {"8x": 2, "4x": 1, "2x": 0, "full": None}

HEX_SCHEMA = pa.schema([
    ("hex", pa.uint64()), ("lat", pa.float64()), ("lon", pa.float64()),
    ("removed_frac", pa.float32()), ("n_px", pa.int32()),
    ("elev_min_m", pa.float32()), ("elev_mean_m", pa.float32()), ("elev_max_m", pa.float32()),
    ("n_lines", pa.int32()),
])
LINE_SCHEMA = pa.schema([
    ("hex", pa.uint64()), ("level_m", pa.float32()), ("closed", pa.bool_()),
    ("x_m", pa.list_(pa.float32())), ("y_m", pa.list_(pa.float32())),
])


def tile_name(lat: int, lon: int) -> str:
    """Copernicus tile whose south-west corner is (lat, lon)."""
    return (f"Copernicus_DSM_COG_10_{'N' if lat >= 0 else 'S'}{abs(lat):02d}_00_"
            f"{'E' if lon >= 0 else 'W'}{abs(lon):03d}_00_DEM")


def tile_url(name: str) -> str:
    return f"/vsicurl/{BUCKET}/{name}/{name}.tif"


def existing_tiles() -> set[str]:
    cache = ROOT / "data" / "raw" / "global" / "copdem30_tileList.txt"
    if not cache.exists():
        r = requests.get(f"{BUCKET}/tileList.txt", timeout=120)
        r.raise_for_status()
        cache.write_text(r.text)
    return set(cache.read_text().split())


_KEPT = None


def kept_mask() -> np.ndarray:
    global _KEPT
    if _KEPT is None:
        with rasterio.open(KEPT) as src:
            _KEPT = src.read(1).astype(bool)
    return _KEPT


def plan(existing: set[str]) -> tuple[list[tuple[int, int]], list[str]]:
    """Tiles touching kept land (dilated one mask pixel, so hexagons spilling over a tile edge
    aren't missed). Antarctica (south of 60S) goes last."""
    k = binary_dilation(kept_mask(), iterations=1)
    touch = k.reshape(180, 20, 360, 20).any(axis=(1, 3))
    tiles, missing = [], []
    for r, c in zip(*np.nonzero(touch)):
        lat, lon = 89 - int(r), int(c) - 180
        (tiles if tile_name(lat, lon) in existing else missing).append((lat, lon))
    tiles.sort(key=lambda t: (t[0] < -60, -t[0], t[1]))
    return tiles, [tile_name(*t) for t in missing]


def hex_polygons(cells: list[str], lon_ref: float) -> list[dict]:
    polys = []
    for c in cells:
        ring = [(lon_ref + ((lo - lon_ref + 180) % 360 - 180), la) for la, lo in h3.cell_to_boundary(c)]
        polys.append({"type": "Polygon", "coordinates": [ring + ring[:1]]})
    return polys


def removed_fraction(polys: list[dict], bounds, lat_mid: float) -> np.ndarray:
    w, s, e, n = bounds
    dy = SAMPLE_DEG
    dx = SAMPLE_DEG / max(math.cos(math.radians(lat_mid)), 0.02)
    width, height = math.ceil((e - w) / dx), math.ceil((n - s) / dy)
    t = from_origin(w, n, dx, dy)
    labels = rasterize(((p, i + 1) for i, p in enumerate(polys)), out_shape=(height, width),
                       transform=t, fill=0, dtype="int32")
    lat = n - (np.arange(height) + 0.5) * dy
    lon = w + (np.arange(width) + 0.5) * dx
    mr = np.clip(((90.0 - lat) / 0.05).astype(int), 0, 3599)
    mc = (np.floor(((lon + 180.0) % 360.0) / 0.05).astype(int)) % 7200
    removed = ~kept_mask()[mr[:, None], mc[None, :]]
    cnt = np.bincount(labels.ravel(), minlength=len(polys) + 1)[1:]
    rem = np.bincount(labels.ravel(), weights=removed.ravel(), minlength=len(polys) + 1)[1:]
    return np.where(cnt > 0, rem / np.maximum(cnt, 1), 1.0)


def read_elevation(bounds, overview, existing: set[str]):
    """Mosaic of every tile touching `bounds` at one overview level, on the grid of the tile
    holding the bounds' centre (neighbours above 50 deg can have other column spacings).
    The up-to-9 remote tiles are opened and read in parallel threads: each open/read is a few
    HTTP round trips, and doing them one after another left the CPU idle half the time."""
    w, s, e, n = bounds
    names = [tile_name(la, lo) for la in range(math.floor(s), math.floor(n - 1e-9) + 1)
             for lo in range(math.floor(w), math.floor(e - 1e-9) + 1)
             if -180 <= lo <= 179]
    names = [nm for nm in names if nm in existing]
    kw = {} if overview is None else {"overview_level": overview}
    centre = tile_name(math.floor((s + n) / 2), math.floor((w + e) / 2))

    def fetch(nm):
        with rasterio.open(tile_url(nm), **kw) as src:
            left, bottom = max(w, src.bounds.left), max(s, src.bounds.bottom)
            right, top = min(e, src.bounds.right), min(n, src.bounds.top)
            if right - left < src.res[0] or top - bottom < src.res[1]:
                return None  # neighbour only grazes the bounds (tiles overlap by ~half a pixel)
            win = from_bounds(left, bottom, right, top, src.transform)
            win = win.round_offsets().round_lengths()
            arr = src.read(1, window=win).astype("float32")
            return nm, arr, src.window_transform(win), src.res, src.crs

    with ThreadPoolExecutor(len(names)) as tp:
        parts = [p for p in tp.map(fetch, names) if p is not None]
    ref = next((p for p in parts if p[0] == centre), parts[0])
    rx, ry = ref[3]
    T = from_origin(w, n, rx, ry)
    out = np.full((max(round((n - s) / ry), 1), max(round((e - w) / rx), 1)), np.nan, np.float32)
    for _, arr, t_, _, crs in parts:
        if arr.size == 0:
            continue
        reproject(arr, out, src_transform=t_, src_crs=crs, dst_transform=T, dst_crs=crs,
                  src_nodata=np.nan, dst_nodata=np.nan, resampling=Resampling.nearest, init_dest_nodata=False)
    return out, T, ref[3]


def process_tile(lat: int, lon: int, level: str, interval: float, out_dir: str) -> dict:
    t0 = time.time()
    name = tile_name(lat, lon)
    out = Path(out_dir)
    existing = existing_tiles()

    shape = h3.LatLngPoly([(lat, lon), (lat, lon + 1), (lat + 1, lon + 1), (lat + 1, lon)])
    cells = sorted(h3.polygon_to_cells(shape, H3_RES))
    hex_rows = {f.name: [] for f in HEX_SCHEMA}
    pts_x, pts_y, offs, l_hex, l_lev, l_closed = [], [], [0], [], [], []

    if cells:
        lon_ref = lon + 0.5
        polys = hex_polygons(cells, lon_ref)
        allx = [x for p in polys for x, _ in p["coordinates"][0]]
        ally = [y for p in polys for _, y in p["coordinates"][0]]
        frac = removed_fraction(polys, (min(allx), min(ally), max(allx), max(ally)), lat + 0.5)
        keep = np.nonzero(frac < REMOVE_AT)[0]
    else:
        keep = np.array([], int)

    if keep.size:
        kpolys = [polys[i] for i in keep]
        kx = [x for p in kpolys for x, _ in p["coordinates"][0]]
        ky = [y for p in kpolys for _, y in p["coordinates"][0]]
        pad = 0.002
        bounds = (min(kx) - pad, max(min(ky) - pad, -90), max(kx) + pad, min(max(ky) + pad, 90))
        elev, T, (rx, ry) = read_elevation(bounds, LEVELS[level], existing)
        labels = rasterize(((p, j + 1) for j, p in enumerate(kpolys)), out_shape=elev.shape,
                           transform=T, fill=0, dtype="int32")
        slices = find_objects(labels, max_label=len(kpolys))

        for j, i in enumerate(keep):
            cell = cells[i]
            clat, clon = h3.cell_to_latlng(cell)
            clon = lon_ref + ((clon - lon_ref + 180) % 360 - 180)
            sl = slices[j]
            n_px, stats, n_lines = 0, (np.nan, np.nan, np.nan), 0
            if sl is not None:
                sub = elev[sl]
                inside = labels[sl] == j + 1
                valid = inside & np.isfinite(sub)
                n_px = int(valid.sum())
                if n_px:
                    v = sub[valid]
                    stats = (float(v.min()), float(v.mean()), float(v.max()))
                if n_px and min(sub.shape) >= 2 and stats[2] > stats[0]:
                    rows = np.arange(sl[0].start, sl[0].stop)
                    cols = np.arange(sl[1].start, sl[1].stop)
                    x = ((T.c + (cols + 0.5) * T.a - clon) * math.cos(math.radians(clat)) * M_PER_DEG)
                    y = (T.f + (rows + 0.5) * T.e - clat) * M_PER_DEG
                    z = np.ma.masked_array(np.where(valid, sub, 0.0), ~valid)
                    levels = np.arange(math.ceil(stats[0] / interval) * interval, stats[2], interval)
                    if levels.size:
                        gen = contourpy.contour_generator(x, y, z, line_type="ChunkCombinedOffset")
                        for lev, (points, offsets) in zip(levels, gen.multi_lines(levels)):
                            p, o = points[0], offsets[0]
                            if p is None:
                                continue
                            for a, b in zip(o[:-1], o[1:]):
                                seg = p[a:b]
                                pts_x.append(seg[:, 0].astype(np.float32))
                                pts_y.append(seg[:, 1].astype(np.float32))
                                offs.append(offs[-1] + (b - a))
                                l_hex.append(h3.str_to_int(cell))
                                l_lev.append(lev)
                                l_closed.append(bool(np.array_equal(seg[0], seg[-1])))
                                n_lines += 1
            for k_, v_ in zip(HEX_SCHEMA.names, (h3.str_to_int(cell), clat, clon, float(frac[i]), n_px,
                                                 *stats, n_lines)):
                hex_rows[k_].append(v_)

    o = np.asarray(offs, np.int32)
    xs = np.concatenate(pts_x) if pts_x else np.zeros(0, np.float32)
    ys = np.concatenate(pts_y) if pts_y else np.zeros(0, np.float32)
    lines = pa.table([
        pa.array(l_hex, pa.uint64()), pa.array(l_lev, pa.float32()), pa.array(l_closed, pa.bool_()),
        pa.ListArray.from_arrays(pa.array(o), pa.array(xs)), pa.ListArray.from_arrays(pa.array(o), pa.array(ys)),
    ], schema=LINE_SCHEMA)
    hexes = pa.table({k_: pa.array(v_, HEX_SCHEMA.field(k_).type) for k_, v_ in hex_rows.items()}, schema=HEX_SCHEMA)

    for tbl, suffix in ((hexes, "hexes"), (lines, "lines")):
        final = out / f"{name}.{suffix}.parquet"
        tmp = final.with_suffix(".tmp")
        pq.write_table(tbl, tmp, compression="zstd")
        os.replace(tmp, final)
    return {"tile": name, "hexes_in_tile": len(cells), "hexes_kept": int(keep.size),
            "lines": len(l_hex), "points": int(xs.size), "seconds": round(time.time() - t0, 2)}


def memory_ok() -> bool:
    """Room to start another tile? Windows: physical RAM available and commit headroom."""
    if os.name != "nt":
        return os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") >= MIN_AVAIL_RAM_GB * 1e9
    import ctypes

    class MemStatus(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    m = MemStatus()
    m.dwLength = ctypes.sizeof(m)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.ullAvailPhys >= MIN_AVAIL_RAM_GB * 1e9 and m.ullAvailPageFile >= MIN_COMMIT_GB * 1e9


def write_manifest(path: Path, info: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(info, indent=2))
    os.replace(tmp, path)


def run_level(level: str, interval: float, tiles, missing, workers: int, root: Path = OUT_ROOT) -> None:
    base = root / f"{level}_i{interval:g}m"
    out = base / "tiles"
    out.mkdir(parents=True, exist_ok=True)
    done_path, err_path = base / "done.txt", base / "errors.txt"
    done = set(done_path.read_text().split()) if done_path.exists() else set()
    todo = [t for t in tiles if tile_name(*t) not in done]
    info = json.loads((base / "manifest.json").read_text()) if (base / "manifest.json").exists() else {}
    totals = info.get("totals", {"hexes_kept": 0, "lines": 0, "points": 0})
    info.update({
        "level": level, "overview_index": LEVELS[level],
        "nominal_pixel_m": {"8x": 240, "4x": 120, "2x": 60, "full": 30}[level],
        "contour_interval_m": interval, "h3_res": H3_RES, "remove_if_removed_frac_ge": REMOVE_AT,
        "tiles_total": len(tiles), "tiles_without_dem": missing, "status": "running",
        "started": info.get("started", datetime.now(timezone.utc).isoformat(timespec="seconds")),
    })
    print(f"[{level}] {len(todo)} of {len(tiles)} tiles to do", flush=True)
    t_start, last, n_ok = time.time(), 0.0, 0
    fails: dict[tuple[int, int], int] = {}
    # A worker killed by the OS (e.g. out of memory) breaks the whole pool; start a new pool
    # with the unfinished tiles. A tile that itself fails MAX_TRIES times is left for a rerun.
    while todo and info["status"] == "running":
        broken = False
        with ProcessPoolExecutor(workers) as ex,                 open(done_path, "a") as dl, open(err_path, "a") as el:
            # Hand out tiles one at a time, at most `workers` in flight, and only while memory
            # has headroom (other runs and apps share it); otherwise wait for a tile to finish.
            queue, futs, waited = list(todo), {}, False
            while queue or futs:
                while queue and len(futs) < workers and info["status"] == "running":
                    if futs and not memory_ok():
                        if not waited:
                            print(f"[{level}] low memory: holding new tiles ({len(futs)} in flight)", flush=True)
                            waited = True
                        break
                    waited = False
                    la, lo = queue.pop(0)
                    try:
                        futs[ex.submit(process_tile, la, lo, level, interval, str(out))] = (la, lo)
                    except BrokenProcessPool:  # a worker died between results; restart the pool
                        broken = True
                        break
                if broken:
                    break
                if not futs:
                    if not queue or info["status"] != "running":
                        break
                    time.sleep(5)  # memory short with nothing running: let other processes free some
                    continue
                finished, _ = wait(futs, timeout=10, return_when=FIRST_COMPLETED)
                for f in finished:
                    la, lo = futs.pop(f)
                    if shutil.disk_usage(base).free < MIN_FREE_GB * 1e9 and info["status"] == "running":
                        info["status"] = "paused_low_disk"
                        print(f"[{level}] free disk below {MIN_FREE_GB} GB: stopping after in-flight tiles", flush=True)
                    try:
                        r = f.result()
                    except BrokenProcessPool:
                        broken = True
                        continue
                    except Exception:
                        fails[(la, lo)] = fails.get((la, lo), 0) + 1
                        el.write(f"{tile_name(la, lo)}\n{traceback.format_exc()}\n")
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
                    write_manifest(base / "manifest.json", info)
                    print(f"[{level}] {len(done)}/{len(tiles)} tiles, {totals['hexes_kept']:,} hexes, "
                          f"{totals['lines']:,} lines, eta {info['eta_hours']} h", flush=True)
        todo = [t for t in todo if tile_name(*t) not in done and fails.get(t, 0) < MAX_TRIES]
        if broken:
            print(f"[{level}] worker pool crashed (likely out of memory); restarting with {len(todo)} tiles", flush=True)
        elif todo:
            print(f"[{level}] retrying {len(todo)} failed tiles", flush=True)
    ndone = len(set(done_path.read_text().split()))
    status = "complete" if ndone == len(tiles) else ("paused_low_disk" if info["status"] == "paused_low_disk" else "incomplete")
    info.update({"tiles_done": ndone, "totals": totals, "status": status,
                 "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    write_manifest(base / "manifest.json", info)
    print(f"[{level}] {info['status']}: {ndone}/{len(tiles)} tiles", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--levels", default="8x,4x,2x,full")
    ap.add_argument("--interval", type=float, default=20.0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--tiles", help="comma-separated tile names (testing)")
    ap.add_argument("--limit", type=int, help="first N planned tiles only (testing)")
    ap.add_argument("--out", type=Path, default=OUT_ROOT)
    ap.add_argument("--mask", type=Path, help="kept.tif of the global mask (default: v2)")
    a = ap.parse_args()
    if a.mask:
        global KEPT
        KEPT = a.mask
        os.environ["CONTOURS_MASK"] = str(a.mask)

    existing = existing_tiles()
    tiles, missing = plan(existing)
    if a.tiles:
        want = set(a.tiles.split(","))
        tiles = [t for t in tiles if tile_name(*t) in want]
    if a.limit:
        tiles = tiles[: a.limit]
    for level in a.levels.split(","):
        run_level(level, a.interval, tiles, missing, a.workers, a.out)
        if json.loads((a.out / f"{level}_i{a.interval:g}m" / "manifest.json").read_text())["status"] == "paused_low_disk":
            break


if __name__ == "__main__":
    main()
