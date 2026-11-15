"""Add feature columns to every hexagon table (Earth, Moon, Mars), one feature group at a time.

User rule: "upgrade" the existing hexagon tables (contour outputs) with the pipeline's feature
columns, and do each feature on all three bodies together. Column names and definitions are the
site pipeline's (layers.py); a coarse source value is assigned the way the site pipeline did:

  group        Earth                              Moon                                Mars
  temperature  MERRA-2 2023, containing cell      Diviner GCP, containing 0.5 deg     Ames GCM, bilinear
  weather      MERRA-2 2023, containing cell      known absent: 0                     Ames GCM, bilinear
  insolation   analytic annual-mean TOA from latitude and orbit (all bodies)

Each tile's <tile>.hexes.parquet is rewritten atomically with the group's columns added (or
replaced); provenance goes into the dataset's manifest.json under "features".
Usage: uv run python analysis/hex_features.py temperature [--workers 15]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from functools import cache
from pathlib import Path

for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from layers import KNOWN_ABSENT  # noqa: E402
from sources.climate import BANDS, WEATHER_BANDS, annual_mean_insolation, mgcm_interpolators  # noqa: E402

OUT = ROOT / "data" / "out"
INTERIM = ROOT / "data" / "interim" / "global"
RES = int(os.environ.get("HEX_RES", "8"))  # same switch as the contour scripts
if RES == 8:
    DATASETS = {
        "earth": [OUT / "contours_r8_v2" / "8x_i20m", OUT / "contours_r8_v2" / "4x_i20m"],
        "moon": [OUT / "contours_planet" / "moon_240m_i20m", OUT / "contours_planet" / "moon_native_i20m"],
        "mars": [OUT / "contours_planet" / "mars_240m_i20m", OUT / "contours_planet" / "mars_native_i20m"],
    }
else:  # user (2026-11-15): r7 for Earth 8x, Moon 240m, Mars 240m only
    _P = OUT / f"contours_planet_r{RES}"
    DATASETS = {"earth": [OUT / f"contours_r{RES}_v2" / "8x_i20m"], "moon": [_P / "moon_240m_i20m"], "mars": [_P / "mars_240m_i20m"]}
GROUPS = {
    "temperature": BANDS,
    "weather": WEATHER_BANDS,
    "insolation": ("insolation_wm2",),
    "feo": ("feo_wt_pct",),
    "albedo": ("albedo",),
}
# Non-Earth features (user): Earth tables don't get these columns.
BODIES = {"feo": ("moon", "mars"), "albedo": ("moon", "mars")}
PLANET = ROOT / "data" / "raw" / "global" / "planet"
PROVENANCE = {
    ("temperature", "earth"): "MERRA-2 M2T1NXSLV hourly skin temperature TS, 2023 (same reanalysis as NASA POWER), 0.5 x 0.625 deg, containing cell; day = 6 <= local solar time < 18",
    ("temperature", "moon"): "LRO Diviner Global Cumulative Product bolometric temperature, 0.5 deg x 0.25 h local time, containing cell",
    ("temperature", "mars"): "NASA Ames Legacy Mars GCM ACTIVECLDS climatology (model output), 5 x 6 deg, bilinear",
    ("weather", "earth"): "MERRA-2 M2T1NXSLV hourly PS and 10 m wind (U10M, V10M), 2023, containing cell",
    ("weather", "moon"): "known absent (no atmosphere): 0",
    ("weather", "mars"): "NASA Ames Legacy Mars GCM: surface pressure, lowest-layer wind (model output), bilinear",
    ("insolation", "earth"): "analytic annual-mean top-of-atmosphere insolation from latitude and orbit",
    ("insolation", "moon"): "analytic annual-mean top-of-atmosphere insolation from latitude and orbit",
    ("insolation", "mars"): "analytic annual-mean top-of-atmosphere insolation from latitude and orbit",
    ("feo", "moon"): "Lunar Prospector GRS (Prettyman et al.), 2 deg equal-area bins, FeO wt%, containing bin (one empty bin = NaN)",
    ("feo", "mars"): "Mars Odyssey GRS Fe 5x5 deg x 1.2865 = FeO-equivalent wt%, containing bin; polar regions masked (NaN)",
    ("albedo", "moon"): "LOLA 1064 nm normal albedo: LDAM_50S_1000M south of 55S, else LDAM_10 (10 px/deg); containing pixel",
    ("albedo", "mars"): "MGS TES Lambert albedo global mosaic (~7.4 km), containing pixel",
}


@cache
def merra():
    z = np.load(INTERIM / "merra2_2023_climate.npz")
    return {k: z[k] for k in z.files}


@cache
def diviner():
    z = np.load(INTERIM / "diviner_temperature_grid.npz")
    return {k: z[k] for k in z.files}


def merra_cells(lat, lon):
    m = merra()
    la, lo = m["lat"], m["lon"]
    i = np.clip(np.rint((lat - la[0]) / (la[1] - la[0])).astype(int), 0, la.size - 1)
    j = np.rint((lon - lo[0]) / (lo[1] - lo[0])).astype(int) % lo.size
    return i, j


@cache
def feo_grid(body):
    z = np.load(INTERIM / "planet_feo_grids.npz")
    g = z[f"{body}_feo"].copy()
    g[g == 0] = np.nan  # an empty bin, not a measurement
    return g, float(z[f"{body}_lon0"]), float(z["res"])


@cache
def raster(name):
    import rasterio
    from pyproj import Transformer
    with rasterio.open(PLANET / name) as s:
        a = s.read(1, masked=True).astype(np.float32).filled(np.nan) * np.float32(s.scales[0]) + np.float32(s.offsets[0])
        R = s.crs.to_dict().get("R") or s.crs.ellipsoid.semi_major_metre
        tr = Transformer.from_crs(f"+proj=longlat +R={R} +no_defs", s.crs, always_xy=True)
        return a, s.transform, tr


def sample(name, lat, lon):
    a, T, tr = raster(name)
    x, y = tr.transform(lon, lat)
    c = np.floor((np.asarray(x) - T.c) / T.a).astype(int)
    r = np.floor((np.asarray(y) - T.f) / T.e).astype(int)
    ok = (r >= 0) & (r < a.shape[0]) & (c >= 0) & (c < a.shape[1])
    out = np.full(lat.shape, np.nan, np.float32)
    out[ok] = a[r[ok], c[ok]]
    return out


def values(group: str, body: str, lat: np.ndarray, lon: np.ndarray) -> dict[str, np.ndarray]:
    cols = GROUPS[group]
    if group == "feo":
        g, lon0, res = feo_grid(body)
        i = np.clip(np.floor((lat + 90) / res).astype(int), 0, g.shape[0] - 1)
        j = np.floor(((lon - lon0) % 360) / res).astype(int) % g.shape[1]
        return {"feo_wt_pct": g[i, j]}
    if group == "albedo":
        if body == "mars":
            return {"albedo": sample("mars_tes_albedo.tif", lat, lon)}
        v = sample("moon_ldam10.lbl", lat, lon)
        south = lat <= -55
        if south.any():
            v[south] = sample("moon_ldam50s.lbl", lat[south], lon[south])
        return {"albedo": v}
    if group == "insolation":
        return {"insolation_wm2": annual_mean_insolation(lat, body)}
    if body == "earth":
        i, j = merra_cells(lat, lon)
        return {c: merra()[c][i, j] for c in cols}
    if body == "moon" and group == "temperature":
        d = diviner()
        i = np.clip(np.floor((lat + 90) / 0.5).astype(int), 0, 359)
        j = np.clip(np.floor((lon + 180) / 0.5).astype(int), 0, 719)
        return {c: d[c][i, j] for c in cols}
    if body == "moon" and group == "weather":
        return {c: np.full(lat.size, KNOWN_ABSENT[(c, "moon")]) for c in cols}
    if body == "mars":
        gcm = {"temperature": ("tsurf_day_max", "tsurf_night_max", "tsurf_night_min", "tsurf_mean"),
               "weather": ("psurf_mean_pa", "wind_mean_ms", "wind_max_ms")}[group]
        value_at, _ = mgcm_interpolators(gcm)
        v = value_at(lat, lon)
        return dict(zip(cols, v))
    raise ValueError((group, body))


def update_tile(path: str, group: str, body: str) -> int:
    t = pq.read_table(path)
    lat, lon = t.column("lat").to_numpy(), t.column("lon").to_numpy()
    new = values(group, body, lat, lon) if t.num_rows else {c: np.zeros(0) for c in GROUPS[group]}
    for c, v in new.items():
        arr = pa.array(np.asarray(v, np.float32), pa.float32())
        t = t.set_column(t.schema.get_field_index(c), c, arr) if c in t.column_names else t.append_column(c, arr)
    tmp = path + ".tmp"
    pq.write_table(t, tmp, compression="zstd")
    os.replace(tmp, path)
    return t.num_rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("group", choices=list(GROUPS))
    ap.add_argument("--workers", type=int, default=15)
    ap.add_argument("--bodies", default=None)
    a = ap.parse_args()
    a.bodies = a.bodies or ",".join(BODIES.get(a.group, ("earth", "moon", "mars")))

    jobs = []
    for body in a.bodies.split(","):
        for ds in DATASETS[body]:
            if (ds / "done.txt").exists():
                for tile in (ds / "done.txt").read_text().split():
                    jobs.append((str(ds / "tiles" / f"{tile}.hexes.parquet"), body, ds))
    # interleave bodies so all three advance together
    by_body = {b: [j for j in jobs if j[1] == b] for b in a.bodies.split(",")}
    order = []
    while any(by_body.values()):
        for b in list(by_body):
            if by_body[b]:
                order.append(by_body[b].pop(0))
    print(f"{a.group}: {len(order)} tile tables", flush=True)

    t0, rows, done = time.time(), 0, 0
    per_body = {}
    with ProcessPoolExecutor(a.workers) as ex:
        futs = {ex.submit(update_tile, p, a.group, b): (p, b, ds) for p, b, ds in order}
        for f in as_completed(futs):
            p, b, ds = futs[f]
            n = f.result()
            rows += n
            done += 1
            per_body[b] = per_body.get(b, 0) + n
            if done % 2000 == 0 or done == len(order):
                print(f"{a.group}: {done}/{len(order)} tables, {rows:,} hexagons {per_body}, {time.time() - t0:.0f} s", flush=True)

    for body in a.bodies.split(","):
        for ds in DATASETS[body]:
            mpath = ds / "manifest.json"
            if mpath.exists():
                m = json.loads(mpath.read_text())
                m.setdefault("features", {})[a.group] = {"columns": list(GROUPS[a.group]), "source": PROVENANCE[(a.group, body)]}
                tmp = mpath.with_suffix(".tmp")
                tmp.write_text(json.dumps(m, indent=2))
                os.replace(tmp, mpath)
    print(f"{a.group}: done", flush=True)


if __name__ == "__main__":
    main()
