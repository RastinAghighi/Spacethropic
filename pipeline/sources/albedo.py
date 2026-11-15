"""Surface albedo (dimension 1: geology / surface materials).

Each body's best calibrated product measures a slightly different albedo:
  Earth  Sentinel-2 L2A surface reflectance -> broadband shortwave albedo (Liang 2001 weights)
  Moon   LOLA 1064 nm normal albedo (active laser, so it also sees permanently shadowed floors)
  Mars   MGS TES Lambert albedo (bolometric, ~0.3–2.9 µm)
All are "fraction of light reflected" on a 0–1 scale, but not identical definitions; see README.
"""
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from pystac_client import Client
from rasterio.warp import Resampling, transform_bounds

from config import Site, geographic_crs, local_crs, raster_half_extent_m
from sources.base import Source
from sources.raster import http_provenance, warp_array, warp_to_site, write_array

PIXEL_M = 200.0  # same grid as terrain

LDAM = "https://imbrium.mit.edu/DATA/LOLA_GDR/"
LDAM_GLOBAL = LDAM + "CYLINDRICAL/FLOAT_IMG/LDAM_10_FLOAT"  # 10 px/deg (~3 km)
LDAM_SOUTH = LDAM + "POLAR/FLOAT_IMG/LDAM_50S_1000M_FLOAT"  # 50°S to pole, 1 km
TES_ALBEDO = "https://planetarymaps.usgs.gov/mosaic/Mars_MGS_TES_Albedo_mosaic_global_7410m.tif"

EARTH_SEARCH = "https://earth-search.aws.element84.com/v1"
# Clear-sky, snow-free season per Earth site (local summer; any season works in the Atacama).
SEASONS = {
    "sudbury": ["2023-07-01/2023-08-31", "2024-07-01/2024-08-31"],
    "haughton": ["2023-07-15/2023-08-25", "2024-07-15/2024-08-25"],
    "atacama": ["2023-11-01/2024-03-31"],
}
MAX_SCENES = 8
MAX_CLOUD_PCT = 20
# Liang (2001) narrow-to-broadband shortwave albedo, Landsat weights mapped to Sentinel-2 bands.
LIANG = {"blue": 0.356, "red": 0.130, "nir": 0.373, "swir16": 0.085, "swir22": 0.072}
LIANG_INTERCEPT = -0.0018
SCL_CLEAR = {2, 4, 5, 6, 7}  # dark area, vegetation, bare soil, water, unclassified (not cloud/shadow/snow)


class Sentinel2Albedo(Source):
    id = "s2_albedo"
    group = "albedo"
    bodies = {"earth"}
    product = "Sentinel-2 L2A surface reflectance (Element 84 Earth Search, AWS COGs); per-pixel median of clear summer scenes; Liang (2001) broadband shortwave albedo"
    native_res = "10–20 m (read via COG overviews at ~160 m)"

    def covers(self, site: Site) -> bool:
        return site.id in SEASONS

    def fetch(self, site: Site, out: Path) -> dict:
        half = raster_half_extent_m(site)
        bbox = transform_bounds(local_crs(site), geographic_crs(site.body), -half, -half, half, half, densify_pts=51)
        client = Client.open(EARTH_SEARCH)
        items = []
        for window in SEASONS[site.id]:
            items += list(
                client.search(
                    collections=["sentinel-2-l2a"],
                    bbox=bbox,
                    datetime=window,
                    query={"eo:cloud_cover": {"lt": MAX_CLOUD_PCT}},
                    max_items=200,
                ).items()
            )
        # Lowest cloud first; several tiles may be needed to cover the site, so keep scenes
        # until each pixel has enough clear looks or the budget runs out.
        items.sort(key=lambda it: it.properties.get("eo:cloud_cover", 100))
        stack, used = [], []
        for it in items:
            if len(used) >= MAX_SCENES * 4:
                break
            scl = warp_array([it.assets["scl"].href], site, PIXEL_M, resampling=Resampling.mode, read_res_m=160)
            clear = np.isin(scl, list(SCL_CLEAR))
            if not clear.any():
                continue
            # Earth Search already removed the baseline-04.00 +1000 DN shift when this flag is
            # true, yet still lists offset -0.1 in raster:bands; applying it would subtract twice.
            already_harmonised = it.properties.get("earthsearch:boa_offset_applied", False)
            albedo = np.full(scl.shape, LIANG_INTERCEPT, np.float32)
            for band, w in LIANG.items():
                rb = it.assets[band].extra_fields["raster:bands"][0]
                offset = 0.0 if already_harmonised else rb.get("offset", 0.0)
                refl = warp_array([it.assets[band].href], site, PIXEL_M, scale=rb["scale"], offset=offset, read_res_m=160)
                albedo += np.float32(w) * refl
            albedo[~clear] = np.nan
            stack.append(albedo)
            used.append({"id": it.id, "datetime": it.properties["datetime"], "cloud_cover": it.properties.get("eo:cloud_cover"), "scl_href": it.assets["scl"].href})
            looks = np.isfinite(np.stack(stack)).sum(axis=0)
            if len(used) >= MAX_SCENES and np.percentile(looks, 5) >= 3:
                break
        if not stack:
            raise RuntimeError(f"no clear Sentinel-2 scenes found for {site.id}")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # pixels with no clear look -> NaN
            median = np.nanmedian(np.stack(stack), axis=0)
        meta = write_array(median, site, out, PIXEL_M)
        return {
            **meta,
            "stac_api": EARTH_SEARCH,
            "seasons": SEASONS[site.id],
            "scenes": used,
            "searched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }


class LolaAlbedoSouthPole(Source):
    id = "lola_albedo_s1000"
    group = "albedo"
    bodies = {"moon"}
    product = "LRO LOLA 1064 nm normal albedo, LDAM_50S_1000M (float), polar stereographic 50°S to pole"
    native_res = "1 km"

    def covers(self, site: Site) -> bool:
        return site.lat <= -55

    def fetch(self, site: Site, out: Path) -> dict:
        meta = warp_to_site(["/vsicurl/" + LDAM_SOUTH + ".LBL"], site, out, PIXEL_M)
        return {**meta, "inputs": [http_provenance(LDAM_SOUTH + ".LBL"), http_provenance(LDAM_SOUTH + ".IMG")]}


class LolaAlbedoGlobal(Source):
    id = "lola_albedo_10ppd"
    group = "albedo"
    bodies = {"moon"}
    product = "LRO LOLA 1064 nm normal albedo, LDAM_10 (float), global cylindrical"
    native_res = "10 px/deg (~3 km)"

    def fetch(self, site: Site, out: Path) -> dict:
        meta = warp_to_site(["/vsicurl/" + LDAM_GLOBAL + ".LBL"], site, out, PIXEL_M)
        return {**meta, "inputs": [http_provenance(LDAM_GLOBAL + ".LBL"), http_provenance(LDAM_GLOBAL + ".IMG")]}


class TesAlbedo(Source):
    id = "tes_albedo"
    group = "albedo"
    bodies = {"mars"}
    product = "MGS TES Lambert albedo global mosaic (USGS Astrogeology)"
    native_res = "~7.4 km"

    def fetch(self, site: Site, out: Path) -> dict:
        meta = warp_to_site(["/vsicurl/" + TES_ALBEDO], site, out, PIXEL_M)
        return {**meta, "inputs": [http_provenance(TES_ALBEDO)]}
