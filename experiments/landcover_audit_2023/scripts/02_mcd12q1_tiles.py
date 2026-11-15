"""Task 2a: MCD12Q1 2023 (500 m tiles), streamed one tile row at a time.

1. Exact class areas: every MCD12Q1 sinusoidal pixel has the same area (PIX_KM2 = 0.2147 km^2),
   so a class's area is (pixel count) x PIX_KM2. Fill pixels are split into "outside the
   sinusoidal globe" (tile corners, not Earth surface) and "inside the globe" (unclassified).
2. 0.05 deg class counts, binned exactly as pipeline/analysis/landcover_fractions.py does
   (500 m pixel centre -> 0.05 deg pixel), but per IGBP class instead of per group, so the
   teammate's MODIS rule can be re-applied (script 04) and stricter policies compared.

Memory: tile row v covers latitudes [80 - 10v, 90 - 10v] exactly (sinusoidal y = R * lat), i.e.
0.05 deg rows 200v .. 200v + 199. Each band is accumulated (17 x 200 x 7200 uint16, ~50 MB),
then written to an on-disk memmap; no global array is held in RAM.

Outputs: work/mcd12q1_counts_0p05.npy  uint8 (17, 3600, 7200), layer k = MCD12C1 class k (0 water)
         work/mcd12q1_class_totals.json
Usage:   .venv/Scripts/python.exe -I scripts/02_mcd12q1_tiles.py [--data DIR]
"""

from __future__ import annotations

import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

import numpy as np  # noqa: E402
from pyhdf.SD import SD, SDC  # noqa: E402

NCLS = 17
BAND = 200  # 0.05 deg rows per 10 deg tile row
Q1_RE = re.compile(r"MCD12Q1\.A2023001\.h(\d{2})v(\d{2})\.061\.\d{13}\.hdf$")
# MCD12Q1 value (1..17, 255) -> MCD12C1 class index (0..16), -1 = fill
Q1_TO_C1 = np.full(256, -1, np.int64)
for _v in range(1, 18):
    Q1_TO_C1[_v] = C.q1_to_c1(_v)

ROWS = np.arange(2400) + 0.5


def tile_latlon(h: int, v: int):
    """Pixel-centre lat/lon, same formulas as landcover_fractions.modis(); NaN outside the globe."""
    y = 10007554.677 - (v * 2400 + ROWS) * C.PIX_M
    x = -20015109.354 + (h * 2400 + ROWS) * C.PIX_M
    lat = np.broadcast_to(np.degrees(y / C.R_SIN)[:, None], (2400, 2400))
    lon = np.degrees(x[None, :] / (C.R_SIN * np.maximum(np.cos(np.radians(lat)), 1e-9)))
    lon[np.abs(lon) > 180] = np.nan
    return lat, lon


def bin_tile(lat, lon, cls, v: int, band: np.ndarray) -> None:
    ok = (cls >= 0) & np.isfinite(lon)
    lat, lon, cls = lat[ok], lon[ok], cls[ok]
    r = np.clip(((90.0 - lat) / C.RES).astype(np.int64), 0, C.H - 1) - BAND * v
    assert r.min() >= 0 and r.max() < BAND, (v, r.min(), r.max())
    c = (np.floor(((lon + 180.0) % 360.0) / C.RES).astype(np.int64)) % C.W
    r0, r1 = int(r.min()), int(r.max()) + 1
    if c.max() - c.min() > C.W // 2:   # straddles the antimeridian: full width
        c0, c1 = 0, C.W
    else:
        c0, c1 = int(c.min()), int(c.max()) + 1
    hh, ww = r1 - r0, c1 - c0
    flat = (r - r0) * ww + (c - c0)
    for k in np.unique(cls):            # one small bincount per class present
        sub = np.bincount(flat[cls == k], minlength=hh * ww).reshape(hh, ww)
        band[k, r0:r1, c0:c1] += sub.astype(np.uint16)


def main() -> None:
    a = C.args(__doc__)
    tiles = defaultdict(list)
    for p in sorted((a.data / "modis-mcd12q1-2023").glob("MCD12Q1.A2023001.h*v*.061.*.hdf")):
        m = Q1_RE.match(p.name)
        if m:
            tiles[int(m.group(2))].append((int(m.group(1)), p))
    n_tiles = sum(len(t) for t in tiles.values())
    if n_tiles != 315:
        raise SystemExit(f"expected 315 tiles, found {n_tiles}")

    C.WORK.mkdir(parents=True, exist_ok=True)
    out_path = C.WORK / "mcd12q1_counts_0p05.npy"
    tmp_path = C.WORK / "mcd12q1_counts_0p05.npy.part"
    grid = np.lib.format.open_memmap(tmp_path, mode="w+", dtype=np.uint8, shape=(NCLS, C.H, C.W))
    counts = np.zeros(256, np.int64)                  # raw LC_Type1 histogram
    fill_inside = 0
    south60 = np.zeros(NCLS, np.int64)                # pixel counts with lat < -60
    t0, done, max_count = time.time(), 0, 0
    for v in range(18):
        band = np.zeros((NCLS, BAND, C.W), np.uint16)
        for h, p in tiles.get(v, []):
            f = SD(str(p), SDC.READ)
            lc = f.select("LC_Type1")[:]
            f.end()
            lat, lon = tile_latlon(h, v)
            counts += np.bincount(lc.ravel(), minlength=256)
            inside = np.isfinite(lon)
            fill_inside += int(((lc == 255) & inside).sum())
            cls = Q1_TO_C1[lc]
            s = (lat < -60) & inside & (cls >= 0)
            south60 += np.bincount(cls[s], minlength=NCLS)[:NCLS]
            bin_tile(lat, lon, cls, v, band)
            done += 1
            del lc, lat, lon, cls, inside, s
        max_count = max(max_count, int(band.max()))
        if band.max() > 255:
            raise SystemExit(f"count overflow in tile row v{v}: {band.max()}")
        grid[:, BAND * v:BAND * (v + 1), :] = band.astype(np.uint8)
        print(f"tile row v{v:02d}: {len(tiles.get(v, []))} tiles, {done}/315 done, {time.time() - t0:.0f} s", flush=True)
    grid.flush()
    del grid
    tmp_path.replace(out_path)

    totals = {
        "pixel_km2": C.PIX_KM2,
        "tiles": n_tiles,
        "class_pixels_c1_index": {str(C.q1_to_c1(v)): int(counts[v]) for v in range(1, 18)},
        "class_area_km2_c1_index": {str(C.q1_to_c1(v)): float(counts[v] * C.PIX_KM2) for v in range(1, 18)},
        "class_area_south_of_60S_km2_c1_index": {str(k): float(south60[k] * C.PIX_KM2) for k in range(NCLS)},
        "fill_pixels_total": int(counts[255]),
        "fill_pixels_inside_globe": fill_inside,
        "fill_area_inside_globe_km2": fill_inside * C.PIX_KM2,
        "unexpected_values": {str(k): int(counts[k]) for k in np.nonzero(counts)[0] if not (1 <= k <= 17 or k == 255)},
        "max_pixels_per_0p05_cell": max_count,
        "seconds": round(time.time() - t0, 1),
    }
    totals["covered_area_km2"] = float((counts[1:18].sum() + fill_inside) * C.PIX_KM2)
    (C.WORK / "mcd12q1_class_totals.json").write_text(json.dumps(totals, indent=1))
    print(json.dumps({k: totals[k] for k in ("fill_pixels_inside_globe", "covered_area_km2", "max_pixels_per_0p05_cell",
                                             "unexpected_values", "seconds")}, indent=1))


if __name__ == "__main__":
    main()
