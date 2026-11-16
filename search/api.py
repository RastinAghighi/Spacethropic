"""
Analog search API: a Moon or Mars point -> Earth sites with the closest terrain shape.

    .venv/Scripts/python -m uvicorn api:app --port 8787

POST /search   {"body": "moon"|"mars", "lat": .., "lon": .., "filters": {...}?}
               -> {"target": {...}, "sites": [Candidate-shaped objects]}
GET  /imagery/{h3}.jpg, /imagery/{h3}_thumb.jpg   Sentinel-2 cloudless around the cell

The candidate set is whatever out/nevada_patches.npz holds (Nevada for now; the
eligible-land cells later). Target terrain is read at query time from the global
USGS DEM mosaics, so any point works, not just named sites.
"""

from __future__ import annotations

import io
import math
import os
import threading
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif")

import duckdb
import h3
import numpy as np
import rasterio
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel
from pyproj import Transformer

from compare import compare
from shape import ANGLES, MASK, NPIX, PX_M, Index, bilinear, target_variants
from soil import Soil

import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "db"))
from lookup import point as climate_at  # noqa: E402  Moon/Mars/Earth grids from planets.py

DB = ROOT.parent / "db" / "out" / "analogs.duckdb"
IMG = ROOT / "cache" / "imagery_24km"
IMG.mkdir(parents=True, exist_ok=True)

DEMS = {
    "moon": ("https://planetarymaps.usgs.gov/mosaic/Lunar_LRO_LOLA_Global_LDEM_118m_Mar2014.tif", 1737400.0, "LRO LOLA 118 m DEM"),
    "mars": ("https://planetarymaps.usgs.gov/mosaic/Mars/HRSC_MOLA_Blend/Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif", 3396190.0, "HRSC + MOLA 200 m DEM"),
}
SITES = 8
MIN_RESULTS = 5  # if the limits leave fewer, fill with the closest near misses
MIN_SEP_KM = 25  # distinct sites, not neighbouring cells
# Field spans (match the frontend's slider ranges): how far outside a limit counts as "far"
SPAN = {"slope": 30, "roughness": 4, "elevation": 3500, "meanTemp": 65, "coldMin": 75, "humidity": 100, "wind": 6, "solar": 11,
        "relief": 150, "dayNight": 40, "cloud": 100, "dust": 0.5,
        "slopeMax": 45, "heightRange": 600, "concavity": 200, "hotMax": 70, "pressure": 110,
        "flatGround": 100, "airDayNight": 30, "dustConc": 100, "match": 100}
# Near misses rank on meeting the limits first; terrain shape only breaks ties
SHAPE_WEIGHT_RELAXED = 0.25
# Satellite frame: the renderer expects a 16:9 frame and reads scale off a 1350 px height
FRAME_W_M, FRAME_H_M = 24000.0, 13500.0
IMG_W, IMG_H = 1920, 1080
IMAGERY = "Sentinel-2 cloudless 2016 by EOX (CC BY 4.0)"
UA = {"User-Agent": "spacethropic/1.0 (NASA Space Apps prototype)"}


# --- candidates ---------------------------------------------------------------
d = np.load(ROOT / "out" / "nevada_patches.npz")
CELLS, LAT, LON, PATCHES = d["h3"], d["lat"], d["lon"], d["patches"].astype(np.float64)
INDEX = Index(PATCHES)


def _slope(p):
    gy, gx = np.gradient(p, PX_M)
    return np.degrees(np.arctan(np.hypot(gx, gy)))[MASK].mean()


_ii, _jj = np.mgrid[-(MASK.shape[0] // 2):MASK.shape[0] // 2 + 1, -(MASK.shape[1] // 2):MASK.shape[1] // 2 + 1]
_R = np.hypot(_ii, _jj)
CORE, RIM = _R <= 2.0, MASK & (_R >= 5.0)


def _slope_p90(p):
    gy, gx = np.gradient(p, PX_M)
    return np.percentile(np.degrees(np.arctan(np.hypot(gx, gy)))[MASK], 90)


def _concavity(p):
    """Centre minus rim height (m): negative is a bowl (crater, basin), positive a dome (mound, ridge)."""
    return p[CORE].mean() - p[RIM].mean()


def _flat(p, deg=5.0):
    """Share of the cell (%) gentle enough to land or drive on."""
    gy, gx = np.gradient(p, PX_M)
    return 100 * (np.degrees(np.arctan(np.hypot(gx, gy)))[MASK] < deg).mean()


def _range(p):
    return p[MASK].max() - p[MASK].min()


def _rough(p):
    a = np.abs(np.diff(p, axis=0))[MASK[1:] & MASK[:-1]]
    b = np.abs(np.diff(p, axis=1))[MASK[:, 1:] & MASK[:, :-1]]
    return np.concatenate([a, b]).mean()


con = duckdb.connect(str(DB), read_only=True)
_cols = [c[0] for c in con.execute("SELECT * FROM cells LIMIT 0").description]
_rows = {r[_cols.index("h3")]: dict(zip(_cols, r)) for r in con.execute("SELECT * FROM cells WHERE body = 'earth'").fetchall()}
con.close()
ENV = [_rows.get(h3.str_to_int(str(c))) for c in CELLS]
# Per-cell values the refine drawers can limit on (same units as the frontend's FIELDS)
FIELD = {
    "slope": np.array([_slope(p) for p in PATCHES]),
    "roughness": np.array([_rough(p) for p in PATCHES]),
    "elevation": np.array([p[MASK].mean() for p in PATCHES]),
    "meanTemp": np.array([e["tair_mean"] - 273.15 for e in ENV]),
    "coldMin": np.array([e["tsurf_min"] - 273.15 for e in ENV]),
    "humidity": np.array([e["rh"] for e in ENV]),
    "wind": np.array([e["wind"] for e in ENV]),
    "solar": np.array([e["sw"] * 24 / 1000 for e in ENV]),
    "relief": INDEX.std.copy(),
    "slopeMax": np.array([_slope_p90(p) for p in PATCHES]),
    "flatGround": np.array([_flat(p) for p in PATCHES]),
    "airDayNight": np.array([e["tair_range"] for e in ENV]),
    "dustConc": np.array([e["dust_conc"] for e in ENV]),
    "heightRange": np.array([_range(p) for p in PATCHES]),
    "concavity": np.array([_concavity(p) for p in PATCHES]),
    "hotMax": np.array([e["tsurf_max"] - 273.15 for e in ENV]),
    "pressure": np.array([e["ps"] / 1000 for e in ENV]),
    "dayNight": np.array([e["tsurf_max"] - e["tsurf_min"] for e in ENV]),
    "cloud": np.array([e["cloud"] for e in ENV]),
    "dust": np.array([e["dust_aod"] for e in ENV]),
}

# Surface material: WRB 2006 soil group -> what it offers as a Moon or Mars analog
MATERIAL = {
    "Leptosols": ("rock", "Thin soil over hard rock: the nearest Earth surface to regolith over bedrock"),
    "Regosols": ("regolith", "Loose, weakly developed mineral debris, like unconsolidated regolith"),
    "Arenosols": ("sand", "Loose sand: dune fields, wheel traction and wind transport"),
    "Andosols": ("basalt", "Volcanic ash and glass, like basaltic mare and Martian plains"),
    "Solonchaks": ("evaporite", "Salt crusts left by evaporating brines, like Martian chloride deposits"),
    "Solonetz": ("evaporite", "Sodium-rich salty clay"),
    "Gypsisols": ("sulfate", "Gypsum accumulation, like Mars's sulfate-bearing layers"),
    "Calcisols": ("carbonate", "Carbonate accumulation, like the carbonates in Jezero crater"),
    "Durisols": ("hardpan", "Silica-cemented hardpan, a duricrust analog"),
    "Vertisols": ("clay", "Swelling smectite clays, like Mars's phyllosilicate terrains"),
    "Cryosols": ("ice", "Permafrost: ground ice within 1 m of the surface"),
}
SOIL = Soil()
_soil = [SOIL.dominant(float(a), float(b)) for a, b in zip(LAT, LON)]
GROUP = np.array([g or "" for g, _ in _soil])
MAT = np.array([MATERIAL.get(g, ("soil", ""))[0] if g else "" for g in GROUP])
# How many cells of each material the whole search area holds (a filter for one with none can't be met)
MATERIALS = {str(k): int(n) for k, n in zip(*np.unique(MAT[MAT != ""], return_counts=True))}


def soil_info(i: int) -> dict | None:
    g, share = _soil[i]
    if not g:
        return None
    key, note = MATERIAL.get(g, ("soil", "Biologically developed soil, unlike any lunar or Martian surface"))
    return {"group": g, "share": round(share, 2), "material": key, "note": note}


# --- place names (GeoNames cities1000, offline, worldwide) ---------------------
with zipfile.ZipFile(ROOT / "geonames" / "cities1000.zip") as z:
    _g = [l.split("\t") for l in z.read("cities1000.txt").decode("utf8").splitlines()]
G_NAME = np.array([r[1] for r in _g])
G_LAT = np.radians(np.array([float(r[4]) for r in _g]))
G_LON = np.radians(np.array([float(r[5]) for r in _g]))
G_ADM = np.array([f"{r[8]}.{r[10]}" for r in _g])
G_CC = np.array([r[8] for r in _g])
ADMIN1 = {l.split("\t")[0]: l.split("\t")[1] for l in (ROOT / "geonames" / "admin1CodesASCII.txt").read_text(encoding="utf8").splitlines()}


def place(lat: float, lon: float) -> tuple[str, str]:
    la, lo = math.radians(lat), math.radians(lon)
    h = np.sin((G_LAT - la) / 2) ** 2 + np.cos(la) * np.cos(G_LAT) * np.sin((G_LON - lo) / 2) ** 2
    km = 2 * 6371 * np.arcsin(np.sqrt(h))
    i = int(km.argmin())
    region = f"{ADMIN1.get(G_ADM[i], G_CC[i])}, {G_CC[i]}"
    name = f"Near {G_NAME[i]}" if km[i] < 15 else f"{km[i]:.0f} km from {G_NAME[i]}"
    return name, region


# --- target terrain -----------------------------------------------------------
_dem_lock = threading.Lock()


@lru_cache(maxsize=4)
def _dem(body: str):
    url, _, _ = DEMS[body]
    return rasterio.open("/vsicurl/" + url)


@lru_cache(maxsize=256)
def target(body: str, lat: float, lon: float):
    """The target's 200 m local raster around (lat, lon), and its rotations."""
    url, R, _ = DEMS[body]
    half = 20  # 41 x 41 px covers the disk at any rotation
    jj, ii = np.meshgrid(np.arange(-half, half + 1), np.arange(-half, half + 1))
    aeqd = f"+proj=aeqd +lat_0={lat} +lon_0={lon} +R={R} +units=m +no_defs"
    with _dem_lock:
        src = _dem(body)
        tf = Transformer.from_crs(aeqd, src.crs.to_proj4(), always_xy=True)
        x, y = tf.transform(jj * PX_M, -ii * PX_M)
        col, row = ~src.transform * (x, y)
        r0, r1 = int(np.floor(row.min())) - 1, int(np.ceil(row.max())) + 2
        c0, c1 = int(np.floor(col.min())) - 1, int(np.ceil(col.max())) + 2
        r0, c0 = max(r0, 0), max(c0, 0)
        r1, c1 = min(r1, src.height), min(c1, src.width)
        nodata, scale, offset = src.nodata, src.scales[0], src.offsets[0]
        start = int(src.get_tag_item(f"BLOCK_OFFSET_0_{r0}", "TIFF", bidx=1))
        row_bytes = src.width * np.dtype(src.dtypes[0]).itemsize
        width = src.width
    # The mosaics are uncompressed with one row per strip, stored back to back: fetch just the
    # needed columns of each needed row, as parallel ranged requests (GDAL's reads take ~40 s).
    item = 2

    def fetch(r):
        a = start + (r - r0) * row_bytes + c0 * item
        req = urllib.request.Request(url, headers={"Range": f"bytes={a}-{a + (c1 - c0) * item - 1}", **UA})
        for _ in range(3):
            try:
                return np.frombuffer(urllib.request.urlopen(req, timeout=30).read(), dtype="<i2")
            except Exception:
                pass
        raise HTTPException(502, f"{body} elevation service unavailable")

    with ThreadPoolExecutor(32) as ex:
        z = np.array(list(ex.map(fetch, range(r0, r1))), dtype=np.float64)
    z = np.where(z == nodata, np.nan, z * scale + offset)
    raster = bilinear(z, row - r0 - 0.5, col - c0 - 0.5)
    if np.isnan(raster).any():
        raise HTTPException(422, f"No {body} elevation data at {lat:.3f}, {lon:.3f}")
    T, P = target_variants(raster, half, half)
    return T, P


def target_metrics(body: str, lat: float, lon: float) -> dict:
    """The target's own values, in the same fields and units as the Earth cells'."""
    _, P = target(body, round(lat, 4), round(lon, 4))
    p = P[0]
    m = {"slope": _slope(p), "relief": float(np.sqrt(((p[MASK] - p[MASK].mean()) ** 2).mean())), "roughness": _rough(p),
         "slopeMax": _slope_p90(p), "heightRange": _range(p), "concavity": _concavity(p), "flatGround": _flat(p)}
    c = climate_at(body, lat, lon)
    if c["tsurf_mean"] is not None:
        m["meanTemp"] = c["tsurf_mean"] - 273.15  # surface: the Moon has no air, Mars barely
        m["coldMin"] = c["tsurf_min"] - 273.15
        m["dayNight"] = c["tsurf_range"]
        m["hotMax"] = c["tsurf_max"] - 273.15
    if c.get("tair_range") is not None:
        m["airDayNight"] = c["tair_range"]
    if c.get("ps") is not None:
        m["pressure"] = c["ps"] / 1000
    if c.get("wind") is not None:
        m["wind"] = c["wind"]
    if c.get("tau") is not None:
        m["dust"] = c["tau"]
    return {k: round(float(v), 3) for k, v in m.items()}


# --- imagery ------------------------------------------------------------------
def frame(lat: float, lon: float) -> list[float]:
    dlat = FRAME_H_M / 2 / 111320
    dlon = FRAME_W_M / 2 / (111320 * math.cos(math.radians(lat)))
    return [lat - dlat, lon - dlon, lat + dlat, lon + dlon]


_img_locks: dict[str, threading.Lock] = {}
_img_pool = ThreadPoolExecutor(8)
NEUTRAL = [128, 112, 92]


def ensure_imagery(cell: str, lat: float, lon: float) -> None:
    """Fetch and cache the frame around a cell (one fetch per cell, however many ask)."""
    full, thumb = IMG / f"{cell}.jpg", IMG / f"{cell}_thumb.jpg"
    with _img_locks.setdefault(cell, threading.Lock()):
        if full.exists():
            return
        s, w, n, e = frame(lat, lon)
        q = urllib.parse.urlencode({"service": "WMS", "request": "GetMap", "version": "1.1.1", "layers": "s2cloudless",
                                    "srs": "EPSG:4326", "bbox": f"{w},{s},{e},{n}", "width": IMG_W, "height": IMG_H, "format": "image/jpeg"})
        b = urllib.request.urlopen(urllib.request.Request(f"https://tiles.maps.eox.at/wms?{q}", headers=UA), timeout=60).read()
        im = Image.open(io.BytesIO(b)).convert("RGB")
        im.save(full, quality=90)
        c = im.crop(((IMG_W - IMG_H) // 2, 0, (IMG_W + IMG_H) // 2, IMG_H)).resize((256, 256), Image.LANCZOS)
        c.save(thumb, quality=88)


def avg_color(cell: str) -> list[int]:
    thumb = IMG / f"{cell}_thumb.jpg"
    if not thumb.exists():
        return NEUTRAL
    return [int(v) for v in np.asarray(Image.open(thumb)).reshape(-1, 3).mean(0)]


# --- search -------------------------------------------------------------------
def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def grid(p: np.ndarray) -> list:
    v = p - p[MASK].mean()
    return [[round(float(v[i, j]), 1) if MASK[i, j] else None for j in range(p.shape[1])] for i in range(p.shape[0])]


class Query(BaseModel):
    body: str
    lat: float
    lon: float
    name: str | None = None
    filters: dict | None = None


app = FastAPI(title="Spacethropic analog search")


@app.get("/health")
def health():
    return {"ok": True, "cells": len(CELLS)}


@app.post("/search")
def search(q: Query):
    if q.body not in DEMS:
        raise HTTPException(400, "body must be moon or mars")
    T, P = target(q.body, round(q.lat, 4), round(q.lon, 4))
    t_std = float(np.sqrt((T[0] ** 2).sum() / NPIX))
    # The researcher's limits cut the candidate set before ranking
    raw = (q.filters or {}).get("ranges") or {}
    ranges = {k: r for k, r in raw.items() if k in FIELD and r}
    # Shape match is per query: score = exp(-(rmse / target relief)^2) >= m  <=>  rmse <= relief * sqrt(-ln m)
    m_min = max(0.0, min(0.999, (raw.get("match") or [0, 100])[0] / 100))
    rmse_cap = t_std * math.sqrt(-math.log(m_min)) if m_min > 0 else math.inf
    miss = np.zeros(len(CELLS))  # how far outside the limits, in field spans
    missed = {k: np.zeros(len(CELLS), bool) for k in ranges}
    for k, (lo, hi) in ranges.items():
        over = np.maximum(lo - FIELD[k], 0) + np.maximum(FIELD[k] - hi, 0)
        miss += over / SPAN[k]
        missed[k] = over > 0
    geo = [g for g in ((q.filters or {}).get("geology") or []) if isinstance(g, str)]
    geo_miss = ~np.isin(MAT, geo) if geo else np.zeros(len(CELLS), bool)
    miss += geo_miss  # a whole span: the wrong material is a full miss
    allowed = miss == 0

    def distinct(order, rmse_of, rot_of, picks, strict):
        for i in order:
            if len(picks) == SITES:
                break
            if strict and rmse_of[i] > rmse_cap:
                break  # ranked by rmse: nothing further meets the match limit
            if all(km((LAT[i], LON[i]), (LAT[j], LON[j])) >= MIN_SEP_KM for j, *_ in picks):
                picks.append((int(i), float(rmse_of[i]), int(rot_of[i]), not allowed[i] or rmse_of[i] > rmse_cap))
        return picks

    picks, evaluated = [], 0
    if allowed.any():
        top, rmse, rot, evaluated = INDEX.search(T, k=min(1500, int(allowed.sum())), allowed=allowed)
        r_of, o_of = dict(zip(top, rmse)), dict(zip(top, rot))
        picks = distinct(top, r_of, o_of, picks, strict=True)
    if len(picks) < MIN_RESULTS:
        # Too specific: weaken the terrain match and rank on hitting the mission's limits
        rmse_all, rot_all = INDEX.exact(T)
        evaluated = len(CELLS)
        score_all = np.exp(-((rmse_all / max(t_std, 1e-6)) ** 2))
        cost = miss + np.maximum(m_min - score_all, 0) + SHAPE_WEIGHT_RELAXED * rmse_all / max(t_std, 1e-6)
        taken = {i for i, *_ in picks}
        cost[list(taken)] = np.inf
        order = [i for i in np.argsort(cost) if np.isfinite(cost[i])]
        picks = distinct(order, rmse_all, rot_all, picks, strict=False)

    # Imagery starts downloading now; the browser's image requests wait on it
    for i, *_ in picks:
        _img_pool.submit(ensure_imagery, str(CELLS[i]), float(LAT[i]), float(LON[i]))
    sites = []
    for i, e, o, relaxed in picks:
        cell, env, p = str(CELLS[i]), ENV[i], PATCHES[i]
        name, region = place(float(LAT[i]), float(LON[i]))
        sites.append({
            "id": f"cell-{cell}",
            "name": name,
            "region": region,
            "lat": round(float(LAT[i]), 5),
            "lon": round(float(LON[i]), 5),
            "targetName": q.name or f"a point on the {q.body.capitalize()}",
            "targetLat": q.lat,
            "targetLon": q.lon,
            "targets": [q.body],
            "tags": "terrain shape search",
            "summary": f"H3 cell {cell}. Its terrain is within {e:.1f} m RMS of the target once the target is turned {int(ANGLES[o])}°.",
            "why": [f"Terrain within {e:.1f} m RMS of the target over the same 5.16 km² disk",
                    f"Relief {INDEX.std[i]:.0f} m against the target's {t_std:.0f} m"],
            "breaks": ["Climate values come from a 10° grid and barely vary across a region"],
            "soil": soil_info(i),
            "imagery": {"source": IMAGERY, "layer": "s2cloudless", "date": "2016",
                        "bbox": [round(v, 5) for v in frame(float(LAT[i]), float(LON[i]))], "metersPerPixel": round(FRAME_H_M / 1350, 2)},
            "avgColor": avg_color(cell),
            "climate": {
                "elevationM": round(float(FIELD["elevation"][i]), 1),
                "meanTempC": round(float(FIELD["meanTemp"][i]), 1),
                "coldestMonthMinC": round(float(FIELD["coldMin"][i]), 1),
                "hottestMonthMaxC": round(env["tsurf_max"] - 273.15, 1),
                "precipMmYr": 200,
                "solarKwhM2Day": round(float(FIELD["solar"][i]), 2),
                "humidityPct": round(float(FIELD["humidity"][i])),
                "windMs": round(float(FIELD["wind"][i]), 1),
                "source": "ERA5 10° grid via planets.py, interpolated; rainfall placeholder",
                "period": "2025 sample weeks",
            },
            "traits": {"slope": round(float(FIELD["slope"][i]), 1), "roughness": round(float(FIELD["roughness"][i]), 1),
                       "geology": [MAT[i]] if MAT[i] else [], "roadKm": 10, "protectedArea": False, "access": "Not assessed yet"},
            "missed": ([k for k in ranges if missed[k][i]] + (["geology"] if geo_miss[i] else []) + (["match"] if e > rmse_cap else [])) if relaxed else [],
            "metrics": {k: round(float(v[i]), 3) for k, v in FIELD.items()},
            "shape": {"rmseM": round(e, 2), "rotationDeg": int(ANGLES[o]), "score": round(float(np.exp(-((e / max(t_std, 1e-6)) ** 2))), 3),
                      "reliefM": round(float(INDEX.std[i]), 1), "targetReliefM": round(t_std, 1), "pxM": PX_M,
                      "target": grid(P[o]), "match": grid(p), "dem": DEMS[q.body][2], "cell": cell},
        })
    tm = target_metrics(q.body, q.lat, q.lon)
    # Reasoning for the first sites starts now, so it's ready by the end of the dive
    for site in sites[:3]:
        _llm_pool.submit(_safe_compare, q.body, site["targetName"], tm, site)
    return {"target": {"reliefM": round(t_std, 1), "dem": DEMS[q.body][2], "metrics": tm},
            "evaluated": evaluated, "cells": len(CELLS), "materials": MATERIALS, "sites": sites}


_llm_pool = ThreadPoolExecutor(4)


def _safe_compare(*a):
    try:
        compare(*a)
    except Exception:
        pass


@app.get("/target")
def target_info(body: str, lat: float, lon: float):
    if body not in DEMS:
        raise HTTPException(400, "body must be moon or mars")
    return {"metrics": target_metrics(body, lat, lon), "dem": DEMS[body][2]}


class Compare(BaseModel):
    body: str
    targetName: str
    targetMetrics: dict = {}
    site: dict


@app.post("/compare")
def compare_route(c: Compare):
    """Where the analogy holds and breaks, written by Gemini from the measured values only."""
    try:
        return compare(c.body, c.targetName, c.targetMetrics, c.site)
    except Exception as e:
        raise HTTPException(503, f"Reasoning unavailable: {e}")


@app.get("/imagery/{name}")
def imagery(name: str):
    cell = name.removesuffix(".jpg").removesuffix("_thumb")
    f = IMG / name
    try:
        la, lo = h3.cell_to_latlng(cell)
    except Exception:
        raise HTTPException(404)
    ensure_imagery(cell, la, lo)
    return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})
