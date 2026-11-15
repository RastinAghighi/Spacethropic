"""Shared constants and helpers for the 2023 land-cover audit of the global filter.

Grid: the same 0.05 deg global grid (7200 x 3600, origin -180 / +90) as the teammate's
global_mask.py / global_mask_v2.py, with the same exact spherical pixel areas.
"""

from __future__ import annotations

import argparse
import io
import os
import zipfile
from pathlib import Path

import numpy as np

EXP = Path(__file__).resolve().parents[1]          # experiments/landcover_audit_2023
RESULTS = EXP / "results"
WORK = EXP / "work"                                  # git-ignored intermediates
DEFAULT_DATA = Path(os.environ.get("SPACETHROPIC_DATASETS", r"C:\Dev\Spacethropic-datasets"))

RES, W, H = 0.05, 7200, 3600
R_KM = 6371.007180918475   # authalic radius, same constant as pipeline/analysis/global_mask.py
SOUTH_60_ROW = int(150 / RES)  # first row whose top edge is at 60 S (rows >= this are south of 60 S)

# MODIS sinusoidal grid (MCD12Q1), same constants as pipeline/analysis/landcover_fractions.py
R_SIN = 6371007.181
TILE_M = 1111950.5197665233
PIX_M = TILE_M / 2400
PIX_KM2 = (PIX_M / 1000.0) ** 2   # every 500 m sinusoidal pixel has this exact area

# IGBP classes. MCD12C1 Land_Cover_Type_1_Percent layer index k == class k, with 0 = water.
# MCD12Q1 LC_Type1 uses 1..16 for the same land classes and 17 for water.
IGBP = {
    0: "Water bodies",
    1: "Evergreen needleleaf forests",
    2: "Evergreen broadleaf forests",
    3: "Deciduous needleleaf forests",
    4: "Deciduous broadleaf forests",
    5: "Mixed forests",
    6: "Closed shrublands",
    7: "Open shrublands",
    8: "Woody savannas",
    9: "Savannas",
    10: "Grasslands",
    11: "Permanent wetlands",
    12: "Croplands",
    13: "Urban and built-up lands",
    14: "Cropland/natural vegetation mosaics",
    15: "Permanent snow and ice",
    16: "Barren",
}
BROAD = {0: "water", 1: "forest", 2: "forest", 3: "forest", 4: "forest", 5: "forest",
         6: "shrubland", 7: "shrubland", 8: "savanna", 9: "savanna", 10: "grassland",
         11: "wetland", 12: "cropland", 13: "urban", 14: "cropland", 15: "snow_ice", 16: "barren"}

# The teammate's grouping (pipeline/analysis/landcover_fractions.py, MODIS_IGBP), translated to
# MCD12C1 numbering (class 0 = water). "other" is what the v2 filter treats as analog ground.
TEAM_GROUP = {0: "water", 13: "built", 7: "other", 9: "other", 10: "other", 15: "other", 16: "other"}
for _k in (1, 2, 3, 4, 5, 6, 8, 11, 12, 14):
    TEAM_GROUP[_k] = "veg"


def q1_to_c1(v: int) -> int:
    """MCD12Q1 LC_Type1 value -> MCD12C1 class index (17 water -> 0)."""
    return 0 if v == 17 else v


def pixel_area_km2() -> np.ndarray:
    """(H, 1) exact pixel areas on the authalic sphere (identical to global_mask.pixel_area_km2)."""
    edges = np.radians(90.0 - RES * np.arange(H + 1))
    return (R_KM ** 2 * np.radians(RES) * (np.sin(edges[:-1]) - np.sin(edges[1:])))[:, None]


def area_sum(weight: np.ndarray, area: np.ndarray) -> float:
    """km^2 covered by a (H, W) boolean mask or 0..1 weight: row sums (float64) dot row areas."""
    return float(np.asarray(weight).sum(axis=1, dtype=np.float64) @ area[:, 0])


def south_mask() -> np.ndarray:
    s = np.zeros((H, 1), bool)
    s[SOUTH_60_ROW:] = True
    return s


def args(desc: str) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=desc)
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA,
                    help=f"dataset root (default {DEFAULT_DATA}; env SPACETHROPIC_DATASETS)")
    return ap.parse_args()


# --- Natural Earth land, rasterised exactly like global_mask.land_mask() ------------------------

NE_ZIP = Path("natural-earth") / "10m_physical.zip"


def ne_land_shapes(data: Path):
    import shapefile  # pyshp

    with zipfile.ZipFile(data / NE_ZIP) as z:
        parts = {ext: io.BytesIO(z.read(f"ne_10m_land.{ext}")) for ext in ("shp", "shx", "dbf")}
    r = shapefile.Reader(shp=parts["shp"], shx=parts["shx"], dbf=parts["dbf"])
    return r, [s.__geo_interface__ for s in r.shapes()]


def ne_land_mask(data: Path) -> np.ndarray:
    """Boolean (H, W): pixel centre inside Natural Earth 1:10m land (cached in work/)."""
    cache = WORK / "ne_10m_land_0p05.npy"
    if cache.exists():
        return np.load(cache)
    from rasterio.features import rasterize
    from rasterio.transform import from_origin

    _, geoms = ne_land_shapes(data)
    m = rasterize(((g, 1) for g in geoms), out_shape=(H, W), transform=from_origin(-180.0, 90.0, RES, RES),
                  fill=0, dtype="uint8").astype(bool)
    WORK.mkdir(parents=True, exist_ok=True)
    np.save(cache, m)
    return m


# --- MCD12C1 -----------------------------------------------------------------------------------

def mcd12c1_path(data: Path) -> Path:
    files = sorted((data / "modis-mcd12c1-2023").glob("MCD12C1.A2023001.061.*.hdf"))
    if len(files) != 1:
        raise SystemExit(f"expected exactly one MCD12C1 2023 v061 file, found {len(files)}")
    return files[0]


def read_mcd12c1_percent(data: Path) -> np.ndarray:
    """Land_Cover_Type_1_Percent as uint8 (H, W, 17); 255 = fill."""
    from pyhdf.SD import SD, SDC

    f = SD(str(mcd12c1_path(data)), SDC.READ)
    a = f.select("Land_Cover_Type_1_Percent")[:]
    f.end()
    return a


def read_mcd12c1_majority(data: Path) -> np.ndarray:
    from pyhdf.SD import SD, SDC

    f = SD(str(mcd12c1_path(data)), SDC.READ)
    a = f.select("Majority_Land_Cover_Type_1")[:]
    f.end()
    return a


def write_csv(path: Path, rows: list[dict]) -> None:
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
