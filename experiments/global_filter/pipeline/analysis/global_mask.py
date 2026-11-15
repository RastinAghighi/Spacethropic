"""Whole-Earth exclusion mask: drop every pixel that is ocean, densely populated or densely vegetated.

Pixel-by-pixel on the VIIRS 0.05 deg CMG raster (7200 x 3600, ~5.6 km at the equator), the
coarsest of the three inputs. Areas are exact spherical pixel areas, so high latitudes are not
over-counted.

Rules (a pixel is removed if ANY holds):
  ocean      pixel centre outside Natural Earth 1:10m land polygons (lakes count as land)
  populated  GHSL 2020 population density >= POP_MAX people/km^2 over the pixel
  vegetated  2023 peak monthly VIIRS NDVI >= NDVI_MAX

Inputs come from analysis/global_mask_download.py. Outputs go to data/out/global_mask/.
Usage: uv run python analysis/global_mask.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio
import yaml
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.windows import Window

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "global"
OUT = ROOT / "data" / "out" / "global_mask"

# GHSL Degree of Urbanisation: grid cells under 50 people/km^2 are "very low density rural".
POP_MAX = 50.0
# Standard NDVI split: < 0.2 bare/sparse, 0.2-0.5 shrub/grassland, >= 0.5 dense (forest, crops).
NDVI_MAX = 0.5

RES = 0.05
W, H = 7200, 3600
TRANSFORM = from_origin(-180.0, 90.0, RES, RES)
R_KM = 6371.007180918475  # Earth authalic radius, same as sites.yaml

OCEAN, POPULATED, VEGETATED = 1, 2, 4
NDVI_DATASET = "//HDFEOS/GRIDS/VIIRS_Grid_monthly_VI_CMG/Data_Fields/CMG_0.05_Deg_monthly_NDVI"


def pixel_area_km2() -> np.ndarray:
    """(H, 1) column of exact pixel areas on the authalic sphere."""
    edges = np.radians(90.0 - RES * np.arange(H + 1))
    return (R_KM**2 * np.radians(RES) * (np.sin(edges[:-1]) - np.sin(edges[1:])))[:, None]


def land_mask() -> np.ndarray:
    gj = json.loads((RAW / "ne_10m_land.geojson").read_text(encoding="utf-8"))
    shapes = ((f["geometry"], 1) for f in gj["features"])
    return rasterize(shapes, out_shape=(H, W), transform=TRANSFORM, fill=0, dtype="uint8").astype(bool)


def population_density(area: np.ndarray) -> np.ndarray:
    """Sum GHSL 30" counts into the 0.05 deg pixel holding each source pixel centre, then divide
    by pixel area. GHSL's grid is offset ~1 source pixel from -180 and starts at ~89.1N, so
    pixels are binned by centre coordinate rather than as fixed 6 x 6 blocks."""
    path = next(RAW.glob("GHS_POP_E2020_GLOBE_R2023A_4326_30ss*.tif"))
    people = np.zeros(H * W, dtype="float64")
    with rasterio.open(path) as src:
        t = src.transform
        lon = t.c + (np.arange(src.width) + 0.5) * t.a
        cols = np.floor(((lon + 180.0) % 360.0) / RES).astype(np.int64) % W
        nodata = src.nodata
        step = 600
        for r in range(0, src.height, step):
            n = min(step, src.height - r)
            a = src.read(1, window=Window(0, r, src.width, n)).astype("float64")
            if nodata is not None:
                a[a == nodata] = 0.0
            a[~(a > 0)] = 0.0
            lat = t.f + (r + np.arange(n) + 0.5) * t.e
            rows = np.clip(np.floor((90.0 - lat) / RES).astype(np.int64), 0, H - 1)
            idx = (rows[:, None] * W + cols[None, :]).ravel()
            people += np.bincount(idx, weights=a.ravel(), minlength=H * W)
    people = people.reshape(H, W)
    return people / area, people


def peak_ndvi() -> np.ndarray:
    peak = np.full((H, W), -np.inf, dtype="float32")
    files = sorted((RAW / "vnp13c2").glob("VNP13C2.A2023*.h5"))
    assert len(files) == 12, f"expected 12 months, have {len(files)}"
    for p in files:
        with rasterio.open(f'HDF5:"{p}":{NDVI_DATASET}') as src:
            a = src.read(1)
        assert a.shape == (H, W), a.shape
        v = np.where(a > -10000, a.astype("float32") * 1e-4, -np.inf)  # fill is -15000
        np.maximum(peak, v, out=peak)
    peak[~np.isfinite(peak)] = np.nan
    return peak


def write_png(path: Path, rgb: np.ndarray) -> None:
    with rasterio.open(path, "w", driver="PNG", width=rgb.shape[2], height=rgb.shape[1],
                       count=3, dtype="uint8") as dst:
        dst.write(rgb)


def colourise(flags: np.ndarray, show_reasons: bool) -> np.ndarray:
    rgb = np.empty((3, H, W), dtype="uint8")
    def paint(m, c):
        for i in range(3):
            rgb[i][m] = c[i]
    paint(np.ones_like(flags, bool), (18, 32, 56))                   # ocean
    land = (flags & OCEAN) == 0
    if show_reasons:
        paint(land & ((flags & VEGETATED) > 0), (58, 110, 62))         # dense vegetation
        paint(land & ((flags & POPULATED) > 0), (196, 64, 52))         # populated (drawn on top)
    else:
        paint(land & (flags > 0), (40, 44, 52))                        # removed land, dark grey
    paint(flags == 0, (226, 176, 120))                                 # kept: analog candidate land
    return rgb


def site_report(flags, density, ndvi):
    sites = yaml.safe_load((ROOT / "sites.yaml").read_text())["sites"]
    rows = []
    for s in sites:
        if s["body"] != "earth":
            continue
        r = min(int((90.0 - s["lat"]) / RES), H - 1)
        c = min(int((s["lon"] + 180.0) / RES), W - 1)
        f = int(flags[r, c])
        why = [n for b, n in ((OCEAN, "ocean"), (POPULATED, "populated"), (VEGETATED, "vegetated")) if f & b]
        rows.append({"id": s["id"], "kept": f == 0, "removed_by": why,
                     "pop_per_km2": round(float(density[r, c]), 1),
                     "peak_ndvi": None if np.isnan(ndvi[r, c]) else round(float(ndvi[r, c]), 3)})
    return rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    area = pixel_area_km2()
    full = np.broadcast_to(area, (H, W))

    land = land_mask()
    density, people = population_density(area)
    ndvi = peak_ndvi()

    flags = np.zeros((H, W), dtype="uint8")
    flags[~land] |= OCEAN
    flags[density >= POP_MAX] |= POPULATED
    flags[ndvi >= NDVI_MAX] |= VEGETATED

    def km2(m):
        return float(full[m].sum())

    earth = km2(np.ones((H, W), bool))
    land_km2 = km2(land)
    kept = flags == 0
    kept_km2 = km2(kept)
    antarctica = np.zeros((H, W), bool)
    antarctica[int((90 + 60) / RES):] = True  # south of 60S

    stats = {
        "inputs": {
            "ocean": "Natural Earth 1:10m land polygons (pixel centre test)",
            "population": "GHSL GHS-POP R2023A epoch 2020, 30 arcsec, summed to 0.05 deg",
            "vegetation": "VIIRS VNP13C2 v002 monthly NDVI 0.05 deg, peak of Jan-Dec 2023",
        },
        "thresholds": {"pop_per_km2_max": POP_MAX, "ndvi_peak_max": NDVI_MAX},
        "pixel_deg": RES,
        "area_km2": {
            "earth": earth,
            "land": land_km2,
            "ocean": km2(~land),
            "land_removed_populated_only": km2(land & (flags == POPULATED)),
            "land_removed_vegetated_only": km2(land & (flags == VEGETATED)),
            "land_removed_both": km2(land & (flags == POPULATED | VEGETATED)),
            "land_removed_populated_any": km2(land & ((flags & POPULATED) > 0)),
            "land_removed_vegetated_any": km2(land & ((flags & VEGETATED) > 0)),
            "kept": kept_km2,
            "kept_excluding_south_of_60S": km2(kept & ~antarctica),
            "land_excluding_south_of_60S": km2(land & ~antarctica),
        },
        "people_on_kept_land": float(people[kept].sum()),
        "people_total": float(people.sum()),
        "reduction_pct": {
            "vs_whole_earth": 100 * (1 - kept_km2 / earth),
            "vs_land": 100 * (1 - kept_km2 / land_km2),
        },
        "sanity": {"earth_area_expected_km2": 4 * np.pi * R_KM**2},
        "sites": site_report(flags, density, ndvi),
    }
    a = stats["area_km2"]
    stats["reduction_pct"]["vs_land_excluding_south_of_60S"] = 100 * (
        1 - a["kept_excluding_south_of_60S"] / a["land_excluding_south_of_60S"])

    profile = dict(driver="GTiff", width=W, height=H, count=1, crs="EPSG:4326",
                   transform=TRANSFORM, compress="deflate")
    with rasterio.open(OUT / "exclusion_flags.tif", "w", dtype="uint8", nodata=None, **profile) as dst:
        dst.write(flags, 1)
        dst.update_tags(bits="1=ocean 2=populated 4=vegetated; 0=kept")
    with rasterio.open(OUT / "kept.tif", "w", dtype="uint8", nodata=None, **profile) as dst:
        dst.write(kept.astype("uint8"), 1)

    before = np.where(land, 0, OCEAN).astype("uint8")
    write_png(OUT / "map_before_land.png", colourise(before, False))
    write_png(OUT / "map_after_filtered.png", colourise(flags, False))
    write_png(OUT / "map_reasons.png", colourise(flags, True))

    (OUT / "summary.json").write_text(json.dumps(stats, indent=2))
    print(json.dumps({k: stats[k] for k in ("area_km2", "reduction_pct", "sites")}, indent=1))


if __name__ == "__main__":
    main()
