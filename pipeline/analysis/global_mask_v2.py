"""Whole-Earth exclusion mask v2: land-cover based (replaces v1's VIIRS NDVI rule).

Same 0.05 deg pixels and exact spherical areas as v1 (global_mask.py). A pixel is removed if
ANY holds:
  water      outside Natural Earth land (ocean), OR mean land-cover water share >= 0.5 (lakes)
  populated  GHSL 2020 >= 50 people/km^2, OR mean built-up share >= BUILT_MAX
  vegetated  mean dense-vegetation share >= 0.5
             (or the three non-analog groups together >= 0.5; then the largest one is the reason)
"Mean share" averages the land-cover sources that have data in the pixel
(data/interim/global/landcover_<src>_2023.npz from landcover_fractions.py): MODIS MCD12Q1,
Esri 10 m LULC, and Dynamic World when its file exists.

Outputs in data/out/global_mask_v2/: exclusion_flags.tif (1 water, 2 populated, 4 vegetated),
kept.tif, map_*.png, summary.json (incl. comparison with v1).
Usage: uv run python analysis/global_mask_v2.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parent))
import global_mask as v1  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LC = ROOT / "data" / "interim" / "global"
OUT = ROOT / "data" / "out" / "global_mask_v2"
SOURCES = ("modis", "esri", "dynamicworld")

WATER_MAX = 0.5
BUILT_MAX = 0.25   # a quarter of a ~5 km pixel built up = town or city
VEG_MAX = 0.5
NON_ANALOG_MAX = 0.5
OCEAN, POPULATED, VEGETATED = v1.OCEAN, v1.POPULATED, v1.VEGETATED


def mean_shares():
    used, stack = [], {g: [] for g in ("water", "built", "veg")}
    for s in SOURCES:
        p = LC / f"landcover_{s}_2023.npz"
        if p.exists():
            z = np.load(p)
            used.append(s)
            for g in stack:
                stack[g].append(z[g])
    if not used:
        raise SystemExit("no land-cover files; run analysis/landcover_fractions.py first")
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            m = {g: np.nanmean(np.stack(v), axis=0) for g, v in stack.items()}
    return used, m


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    H, W = v1.H, v1.W
    area = v1.pixel_area_km2()
    full = np.broadcast_to(area, (H, W))

    land = v1.land_mask()
    density, people = v1.population_density(area)
    used, m = mean_shares()
    water, built, veg = (np.nan_to_num(m[g], nan=0.0) for g in ("water", "built", "veg"))
    has_lc = np.isfinite(m["water"])

    flags = np.zeros((H, W), np.uint8)
    flags[~land | (water >= WATER_MAX)] |= OCEAN
    flags[(density >= v1.POP_MAX) | (built >= BUILT_MAX)] |= POPULATED
    flags[veg >= VEG_MAX] |= VEGETATED
    mixed = (flags == 0) & (water + built + veg >= NON_ANALOG_MAX)
    biggest = np.argmax(np.stack([water, built, veg]), axis=0)
    for i, bit in enumerate((OCEAN, POPULATED, VEGETATED)):
        flags[mixed & (biggest == i)] |= bit
    kept = flags == 0

    def km2(mask):
        return float(full[mask].sum())

    with rasterio.open(ROOT / "data" / "out" / "global_mask" / "kept.tif") as s:
        kept_v1 = s.read(1).astype(bool)
    earth, land_km2, kept_km2 = km2(np.ones((H, W), bool)), km2(land), km2(kept)
    south = np.zeros((H, W), bool)
    south[int(150 / v1.RES):] = True

    stats = {
        "inputs": {
            "ocean": "Natural Earth 1:10m land polygons (pixel centre test)",
            "population": "GHSL GHS-POP R2023A epoch 2020, 30 arcsec, summed to 0.05 deg",
            "land_cover": {s: f"data/interim/global/landcover_{s}_2023.npz" for s in used},
            "land_cover_missing": [s for s in SOURCES if s not in used],
        },
        "thresholds": {"pop_per_km2_max": v1.POP_MAX, "water_share_max": WATER_MAX,
                       "built_share_max": BUILT_MAX, "veg_share_max": VEG_MAX,
                       "non_analog_share_max": NON_ANALOG_MAX},
        "pixel_deg": v1.RES,
        "area_km2": {
            "earth": earth, "land": land_km2,
            "removed_water_on_land (lakes etc.)": km2(land & ((flags & OCEAN) > 0)),
            "removed_populated_any": km2(land & ((flags & POPULATED) > 0)),
            "removed_vegetated_any": km2(land & ((flags & VEGETATED) > 0)),
            "removed_by_mixed_rule": km2(land & mixed),
            "land_without_land_cover_data": km2(land & ~has_lc),
            "kept": kept_km2,
            "kept_excluding_south_of_60S": km2(kept & ~south),
            "land_excluding_south_of_60S": km2(land & ~south),
        },
        "reduction_pct": {
            "vs_whole_earth": 100 * (1 - kept_km2 / earth),
            "vs_land": 100 * (1 - kept_km2 / land_km2),
        },
        "vs_v1": {
            "kept_v1_km2": km2(kept_v1),
            "kept_both_km2": km2(kept & kept_v1),
            "kept_only_v2_km2": km2(kept & ~kept_v1),
            "kept_only_v1_km2": km2(~kept & kept_v1),
        },
        "people_on_kept_land": float(people[kept].sum()),
        "sites": v1.site_report(flags, density, np.where(has_lc, veg, np.nan)),
    }
    a = stats["area_km2"]
    stats["reduction_pct"]["vs_land_excluding_south_of_60S"] = 100 * (
        1 - a["kept_excluding_south_of_60S"] / a["land_excluding_south_of_60S"])
    for row in stats["sites"]:
        row["veg_share"] = row.pop("peak_ndvi")

    profile = dict(driver="GTiff", width=W, height=H, count=1, crs="EPSG:4326",
                   transform=v1.TRANSFORM, compress="deflate")
    with rasterio.open(OUT / "exclusion_flags.tif", "w", dtype="uint8", **profile) as dst:
        dst.write(flags, 1)
        dst.update_tags(bits="1=water 2=populated 4=vegetated; 0=kept")
    with rasterio.open(OUT / "kept.tif", "w", dtype="uint8", **profile) as dst:
        dst.write(kept.astype("uint8"), 1)

    v1.write_png(OUT / "map_after_filtered.png", v1.colourise(flags, False))
    v1.write_png(OUT / "map_reasons.png", v1.colourise(flags, True))
    # lakes on land show as water in the reasons map
    rgb = v1.colourise(flags, True)
    lake = land & ((flags & OCEAN) > 0)
    for i, c in enumerate((70, 130, 180)):
        rgb[i][lake] = c
    v1.write_png(OUT / "map_reasons.png", rgb)

    change = np.empty((3, H, W), np.uint8)
    for i, c in enumerate((18, 32, 56)):
        change[i] = c
    for msk, col in ((land, (40, 44, 52)), (kept & kept_v1, (226, 176, 120)),
                     (kept & ~kept_v1, (90, 200, 120)), (~kept & kept_v1, (220, 80, 200))):
        for i in range(3):
            change[i][msk] = col[i]
    v1.write_png(OUT / "map_change_vs_v1.png", change)

    (OUT / "summary.json").write_text(json.dumps(stats, indent=2))
    print(json.dumps({k: stats[k] for k in ("inputs", "area_km2", "reduction_pct", "vs_v1")}, indent=1))
    print([(s["id"], s["kept"], s["removed_by"]) for s in stats["sites"]])


if __name__ == "__main__":
    main()
