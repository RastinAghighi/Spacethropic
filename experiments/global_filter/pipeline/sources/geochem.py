"""Orbital gamma-ray geochemistry (dimension 1: geology). These are tables of lat/lon bins
(2°–5°, i.e. 60–300 km), far larger than an H3 cell, so each site gets one or a few values."""
from pathlib import Path

import numpy as np
import requests

from config import RAW, Site
from sources.base import Source
from sources.raster import http_provenance, write_site_raster

LP_GRS = "https://pds-geosciences.wustl.edu/Lunar/lp-l-grs-5-elem-abundance-v1/lp_9001/data/lpgrs_high1_elem_abundance_2deg.tab"
ODY_GRS_FE = "https://pds-geosciences.wustl.edu/ody/ody-m-grs-5-elements-v1/odgm_xxxx/data/smoothed/fe_sr_5x5.tab"
FE_TO_FEO = 1.2865  # mass ratio FeO / Fe: express total iron as FeO
PIXEL_M = 500.0  # bins are tens of km; this only needs enough pixels per H3 cell


def _cached(url: str) -> Path:
    local = RAW / "_shared" / "geochem" / url.rsplit("/", 1)[1]
    if not local.exists():
        local.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get(url, timeout=300)
        r.raise_for_status()
        local.write_bytes(r.content)
    return local


def _lookup(bins: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """bins: rows of (lat0, lat1, lon0, lon1, value); lon in the same convention as `lon`."""
    out = np.full(lat.shape, np.nan, np.float32)
    for lat0, lat1, lon0, lon1, v in bins:
        m = (lat >= lat0) & (lat < lat1) & (lon >= lon0) & (lon < lon1)
        out[m] = v
    return out


class LunarProspectorGRS(Source):
    id = "lp_grs_feo"
    group = "geochem"
    bodies = {"moon"}
    product = "Lunar Prospector GRS elemental abundances (Prettyman et al.), high-altitude phase, 2° equal-area bins; FeO weight fraction"
    native_res = "2° equal-area bins (~60 km)"

    def fetch(self, site: Site, out: Path) -> dict:
        t = np.loadtxt(_cached(LP_GRS), usecols=(1, 2, 3, 4, 12))
        bins = t.copy()
        bins[:, 4] *= 100  # g/g -> wt%
        meta = write_site_raster(site, out, PIXEL_M, lambda lat, lon: _lookup(bins, lat, lon))
        return {**meta, "inputs": [http_provenance(LP_GRS)]}


class OdysseyGRS(Source):
    id = "ody_grs_fe"
    group = "geochem"
    bodies = {"mars"}
    product = "Mars Odyssey GRS Fe concentration, 5°×5° boxcar-smoothed (Boynton et al.); converted to FeO-equivalent total iron"
    native_res = "5° bins (~300 km); polar regions masked"

    def fetch(self, site: Site, out: Path) -> dict:
        t = np.loadtxt(_cached(ODY_GRS_FE), usecols=(0, 1, 2))
        t = t[t[:, 2] < 9999]  # 9999.999 = masked (polar ice regions)
        bins = np.column_stack([t[:, 0] - 2.5, t[:, 0] + 2.5, t[:, 1] - 2.5, t[:, 1] + 2.5, t[:, 2] * FE_TO_FEO])
        # Table longitudes are bin centres in 0..360 east.
        meta = write_site_raster(site, out, PIXEL_M, lambda lat, lon: _lookup(bins, lat, lon % 360))
        return {**meta, "inputs": [http_provenance(ODY_GRS_FE)]}
