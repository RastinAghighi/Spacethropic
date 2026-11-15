"""Global land-cover shares on the 0.05 deg mask grid (7200 x 3600), one file per source.

For every 0.05 deg pixel, the share of the source's valid area in four groups:
  water   - open water
  built   - built-up / urban
  veg     - dense vegetation: forest, woody savanna, closed shrubland, crops, wetlands
  other   - everything an analog can be: bare, sparse shrub/grass/rangeland, savanna, snow/ice

Sources (year 2023, the same year as the earlier VIIRS NDVI):
  modis - MODIS MCD12Q1 v061, IGBP classes (LC_Type1), 500 m sinusoidal tiles (Earthdata token)
  esri  - Esri / Impact Observatory 10 m annual LULC v02, read at its 320 m overview from the
          Microsoft Planetary Computer copy (same data as the ArcGIS Living Atlas layer)

Output: data/interim/global/landcover_<source>_2023.npz with float32 arrays water, built, veg,
other (area shares, 0..1) and valid (count of source pixels behind the shares).
Usage: uv run python analysis/landcover_fractions.py modis|esri [--workers 8]
"""

from __future__ import annotations

import argparse
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import rasterio
import requests
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "global"
OUT = ROOT / "data" / "interim" / "global"
YEAR = 2023
RES, W, H = 0.05, 7200, 3600
GROUPS = ("water", "built", "veg", "other")

# Class -> group index (0 water, 1 built, 2 veg, 3 other); unlisted classes are no data.
MODIS_IGBP = {
    1: 2, 2: 2, 3: 2, 4: 2, 5: 2,  # forests
    6: 2,                          # closed shrublands (> 60 % woody cover)
    7: 3,                          # open shrublands
    8: 2,                          # woody savannas (30-60 % tree cover)
    9: 3,                          # savannas (10-30 %)
    10: 3,                         # grasslands
    11: 2,                         # permanent wetlands
    12: 2,                         # croplands
    13: 1,                         # urban and built-up
    14: 2,                         # cropland / natural vegetation mosaic
    15: 3,                         # permanent snow and ice
    16: 3,                         # barren
    17: 0,                         # water bodies
}
ESRI_LULC = {1: 0, 2: 2, 4: 2, 5: 2, 7: 1, 8: 3, 9: 3, 11: 3}  # 10 = clouds -> no data


def local_counts(lat: np.ndarray, lon: np.ndarray, group: np.ndarray):
    """Per-group pixel counts in the global-grid bbox of one source item: (r0, c0, counts).
    Done in the worker so only a small array comes back to the main thread."""
    ok = (group >= 0) & np.isfinite(lat) & np.isfinite(lon)
    if not ok.any():
        return None
    lat, lon, group = lat[ok], lon[ok], group[ok]
    r = np.clip(((90.0 - lat) / RES).astype(np.int64), 0, H - 1)
    c = (np.floor(((lon + 180.0) % 360.0) / RES).astype(np.int64)) % W
    r0, r1 = int(r.min()), int(r.max()) + 1
    if c.max() - c.min() > W // 2:  # item straddles the antimeridian: use the full width
        c0, c1 = 0, W
    else:
        c0, c1 = int(c.min()), int(c.max()) + 1
    h, w = r1 - r0, c1 - c0
    flat = (group * h + (r - r0)) * w + (c - c0)
    sub = np.bincount(flat, minlength=len(GROUPS) * h * w).reshape(len(GROUPS), h, w).astype(np.float32)
    return r0, c0, sub


class Accumulator:
    """Per-group pixel counts on the global grid."""

    def __init__(self):
        self.counts = np.zeros((len(GROUPS), H, W), np.float32)

    def add(self, part) -> None:
        if part is None:
            return
        r0, c0, sub = part
        self.counts[:, r0:r0 + sub.shape[1], c0:c0 + sub.shape[2]] += sub

    def save(self, path: Path) -> None:
        valid = self.counts.sum(axis=0)
        path.parent.mkdir(parents=True, exist_ok=True)
        out = {"valid": valid}
        for i, g in enumerate(GROUPS):  # in place, one group at a time, to keep peak memory low
            share = self.counts[i]
            np.divide(share, np.maximum(valid, 1), out=share)
            share[valid == 0] = np.nan
            out[g] = share
        np.savez_compressed(path, **out)


def lut(mapping: dict[int, int]) -> np.ndarray:
    t = np.full(256, -1, np.int64)
    for k, v in mapping.items():
        t[k] = v
    return t


# --- MODIS MCD12Q1 -----------------------------------------------------------------------

R_SIN = 6371007.181
TILE_M = 1111950.5197665233
PIX_M = TILE_M / 2400


def token() -> str:
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("EARTHDATA_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("EARTHDATA_TOKEN missing from pipeline/.env")


def modis(workers: int, limit: int | None = None, out: Path | None = None) -> None:
    from pyhdf.SD import SD, SDC

    d = RAW / "mcd12q1"
    d.mkdir(parents=True, exist_ok=True)
    granules = requests.get("https://cmr.earthdata.nasa.gov/search/granules.json", params={
        "short_name": "MCD12Q1", "version": "061", "page_size": 2000,
        "temporal": f"{YEAR}-01-01T00:00:00Z,{YEAR}-01-02T00:00:00Z"}, timeout=120).json()["feed"]["entry"]
    urls = [next(l["href"] for l in g["links"] if l["href"].endswith(".hdf")) for g in granules][:limit]
    auth = {"Authorization": f"Bearer {token()}"}
    table = lut(MODIS_IGBP)
    acc = Accumulator()
    rows = np.arange(2400) + 0.5

    def fetch(url: str):
        dest = d / Path(url).name
        if not dest.exists():
            with requests.get(url, headers=auth, stream=True, timeout=300) as r:
                r.raise_for_status()
                tmp = dest.with_suffix(".part")
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                os.replace(tmp, dest)
        h, v = int(dest.name.split(".")[2][1:3]), int(dest.name.split(".")[2][4:6])
        lc = SD(str(dest), SDC.READ).select("LC_Type1")[:]
        y = 10007554.677 - (v * 2400 + rows) * PIX_M
        x = -20015109.354 + (h * 2400 + rows) * PIX_M
        lat = np.broadcast_to(np.degrees(y / R_SIN)[:, None], (2400, 2400))
        lon = np.degrees(x[None, :] / (R_SIN * np.maximum(np.cos(np.radians(lat)), 1e-9)))
        lon[np.abs(lon) > 180] = np.nan  # outside the sinusoidal globe (tile corners)
        return local_counts(lat.ravel(), lon.ravel(), table[lc.ravel()])

    t0 = time.time()
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(fetch, u) for u in urls}
        for n, fut in enumerate(as_completed(futs), 1):
            acc.add(fut.result())
            futs.discard(fut)
            if n % 25 == 0 or n == len(urls):
                print(f"modis {n}/{len(urls)} tiles, {time.time() - t0:.0f} s", flush=True)
    acc.save(out or OUT / f"landcover_modis_{YEAR}.npz")
    print("modis done", flush=True)


# --- Esri / Impact Observatory 10 m LULC ---------------------------------------------------

PC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
PC_TOKEN = "https://planetarycomputer.microsoft.com/api/sas/v1/token/io-lulc-annual-v02"
_tok = {"value": None, "at": 0.0}


def sas() -> str:
    if time.time() - _tok["at"] > 20 * 60:
        _tok["value"] = requests.get(PC_TOKEN, timeout=60).json()["token"]
        _tok["at"] = time.time()
    return _tok["value"]


def esri(workers: int, limit: int | None = None, out: Path | None = None) -> None:
    from pystac_client import Client

    items = list(Client.open(PC_STAC).search(collections=["io-lulc-annual-v02"], datetime=str(YEAR)).items())
    hrefs = [i.assets["data"].href for i in items][:limit]
    table = lut(ESRI_LULC)
    acc = Accumulator()

    def read(href: str):
        for attempt in range(5):
            try:
                with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="5"), \
                        rasterio.open(f"/vsicurl/{href}?{sas()}", overview_level=4) as s:  # 32x = 320 m
                    a = s.read(1)
                    t, crs = s.transform, s.crs
                break
            except rasterio.errors.RasterioIOError:
                if attempt == 4:
                    raise
                time.sleep(5 * (attempt + 1))
        rr, cc = np.nonzero(a)  # 0 = no data
        xs = t.c + (cc + 0.5) * t.a
        ys = t.f + (rr + 0.5) * t.e
        lon, lat = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform(xs, ys)
        return local_counts(np.asarray(lat), np.asarray(lon), table[a[rr, cc]])

    t0 = time.time()
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(read, h) for h in hrefs}
        for n, fut in enumerate(as_completed(futs), 1):
            acc.add(fut.result())
            futs.discard(fut)
            if n % 50 == 0 or n == len(hrefs):
                print(f"esri {n}/{len(futs)} items, {time.time() - t0:.0f} s", flush=True)
    acc.save(out or OUT / f"landcover_esri_{YEAR}.npz")
    print("esri done", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("source", choices=["modis", "esri"])
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, help="first N tiles/items only (testing)")
    ap.add_argument("--out", type=Path, help="output .npz (default data/interim/global/)")
    a = ap.parse_args()
    {"modis": modis, "esri": esri}[a.source](a.workers, a.limit, a.out)
