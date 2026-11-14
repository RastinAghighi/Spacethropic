"""Elevation sources (dimension 2: terrain). Each writes a DEM on the site-local grid at the
shared terrain baseline, so slope and roughness are computed at the same scale on every body."""
import math
from pathlib import Path

import requests

from config import RAW, Site, raster_half_extent_m, settings
from sources.base import Source
from sources.raster import http_provenance, warp_to_site

COPDEM = "https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM/Copernicus_DSM_COG_10_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM.tif"
LOLA_GLOBAL = "https://planetarymaps.usgs.gov/mosaic/Lunar_LRO_LOLA_Global_LDEM_118m_Mar2014.tif"
LOLA_POLAR_DIR = "https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/polar/img/"
LOLA_POLAR = "ldem_875s_20m"  # polar stereographic, 87.5°S to the pole
HRSC_MOLA = "https://planetarymaps.usgs.gov/mosaic/Mars/HRSC_MOLA_Blend/Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif"
MOLA = "https://planetarymaps.usgs.gov/mosaic/Mars_MGS_MOLA_DEM_mosaic_global_463m.tif"


def _baseline() -> float:
    return float(settings()["terrain_baseline_m"])


class CopernicusDEM(Source):
    id = "copdem30"
    group = "terrain"
    bodies = {"earth"}
    product = "Copernicus DEM GLO-30 (ESA/Airbus), 1 arc-second, heights above EGM2008"
    native_res = "~30 m"

    def fetch(self, site: Site, out: Path) -> dict:
        # 1° tiles touching the site raster; tiles over open ocean don't exist and are skipped.
        reach_km = site.radius_km + 10
        dlat = reach_km / 111.0
        dlon = reach_km / (111.0 * max(math.cos(math.radians(site.lat)), 0.05))
        tiles = []
        for lat in range(math.floor(site.lat - dlat), math.floor(site.lat + dlat) + 1):
            for lon in range(math.floor(site.lon - dlon), math.floor(site.lon + dlon) + 1):
                url = COPDEM.format(ns="N" if lat >= 0 else "S", lat=abs(lat), ew="E" if lon >= 0 else "W", lon=abs(lon))
                if requests.head(url, timeout=60).status_code == 200:
                    tiles.append(url)
        if not tiles:
            raise RuntimeError(f"no Copernicus DEM tiles found around {site.id}")
        meta = warp_to_site(["/vsicurl/" + u for u in tiles], site, out, _baseline())
        return {**meta, "inputs": [http_provenance(u) for u in tiles]}


class LolaPolar(Source):
    id = "lola_polar20"
    group = "terrain"
    bodies = {"moon"}
    product = "LRO LOLA LDEM_875S_20M, polar stereographic, heights relative to 1737.4 km sphere"
    native_res = "20 m"

    def covers(self, site: Site) -> bool:
        # Product spans 87.5°S to the pole (~75.8 km); the whole site raster must fit inside it.
        km_per_deg = 2 * math.pi * site.body.radius_m / 1000 / 360
        from_pole_km = (90 + site.lat) * km_per_deg
        return site.lat < 0 and from_pole_km + raster_half_extent_m(site) / 1000 <= 2.5 * km_per_deg

    def fetch(self, site: Site, out: Path) -> dict:
        cache = RAW / "_shared" / "lola_polar"
        cache.mkdir(parents=True, exist_ok=True)
        files = {}
        for ext in ("lbl", "img"):
            url = f"{LOLA_POLAR_DIR}{LOLA_POLAR}.{ext}"
            local = cache / f"{LOLA_POLAR}.{ext}"
            if not local.exists():
                with requests.get(url, stream=True, timeout=600) as r:
                    r.raise_for_status()
                    tmp = local.with_suffix(".part")
                    with open(tmp, "wb") as f:
                        for chunk in r.iter_content(1 << 20):
                            f.write(chunk)
                    tmp.replace(local)
            files[ext] = (url, local)
        # The label points at LDEM_875S_20M.IMG; the case-insensitive Windows/macOS filesystem
        # resolves that to the lower-case download. HEIGHT = DN * 0.5 (the label's OFFSET is the
        # reference radius, which we deliberately leave out).
        meta = warp_to_site([str(files["lbl"][1])], site, out, _baseline(), scale=0.5)
        return {**meta, "inputs": [http_provenance(files[e][0]) for e in ("lbl", "img")]}


class LolaGlobal(Source):
    id = "lola118"
    group = "terrain"
    bodies = {"moon"}
    product = "LRO LOLA global LDEM 118 m (USGS mosaic, Mar 2014), heights relative to 1737.4 km sphere"
    native_res = "~118 m"

    def fetch(self, site: Site, out: Path) -> dict:
        meta = warp_to_site(["/vsicurl/" + LOLA_GLOBAL], site, out, _baseline())
        return {**meta, "inputs": [http_provenance(LOLA_GLOBAL)]}


class HrscMolaBlend(Source):
    id = "hrsc_mola200"
    group = "terrain"
    bodies = {"mars"}
    product = "Mars HRSC + MOLA blended DEM v2 (USGS), 200 m, heights relative to the MOLA areoid"
    native_res = "200 m (where HRSC exists; MOLA-derived elsewhere)"

    def fetch(self, site: Site, out: Path) -> dict:
        meta = warp_to_site(["/vsicurl/" + HRSC_MOLA], site, out, _baseline())
        return {**meta, "inputs": [http_provenance(HRSC_MOLA)]}


class Mola(Source):
    id = "mola463"
    group = "terrain"
    bodies = {"mars"}
    product = "MGS MOLA global DEM 463 m (USGS mosaic), heights relative to the MOLA areoid"
    native_res = "~463 m"

    def fetch(self, site: Site, out: Path) -> dict:
        meta = warp_to_site(["/vsicurl/" + MOLA], site, out, _baseline())
        return {**meta, "inputs": [http_provenance(MOLA)]}
