"""Elevation for every site at Earth's H3 resolution-8 size, identical on all bodies.

The pixel is a square with the area of Earth's average r8 cell (0.7373 km^2, 858.68 m side).
The same physical size is used on the Moon and Mars; H3 r8 there would give smaller cells,
because H3 fixes the cell count, not the size.

Recomputed from each terrain source's original product (not from the 200 m pipeline rasters),
with area-average resampling, on the same site-local azimuthal-equidistant grid. Sources fill
in registry order (primary first, fallbacks only where it is empty), as in merge.py.

Outputs: data/out/elevation_r8/<site>.tif (band 1 elevation_m, band 2 source index),
per-source rasters + provenance, summary.csv, and data/export/elevation_r8_all_sites.zip.
Usage: uv run python analysis/elevation_r8.py [site|all]
"""

from __future__ import annotations

import json
import math
import sys
import zipfile
from pathlib import Path

import h3
import numpy as np
import pandas as pd
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sources.terrain as terrain  # noqa: E402
from config import DATA, select  # noqa: E402
from sources import sources_for  # noqa: E402
from sources.raster import write_array  # noqa: E402

R8_AREA_KM2 = h3.average_hexagon_area(8, unit="km^2")  # Earth's average r8 cell
PIXEL_M = math.sqrt(R8_AREA_KM2) * 1000.0
OUT = DATA / "out" / "elevation_r8"


def build(site) -> dict:
    d = OUT / site.id
    d.mkdir(parents=True, exist_ok=True)
    srcs = sources_for(site, "terrain")
    elev = idx = None
    used = []
    for i, src in enumerate(srcs, start=1):
        tif = d / f"{src.id}.tif"
        meta = src.fetch(site, tif)
        (d / f"{src.id}.json").write_text(json.dumps(meta, indent=2))
        with rasterio.open(tif) as r:
            a = r.read(1)
        if elev is None:
            elev, idx = a.copy(), np.where(np.isfinite(a), i, 0).astype(np.float32)
        else:
            fill = np.isnan(elev) & np.isfinite(a)
            elev[fill], idx[fill] = a[fill], i
        used.append(src.id)
        if np.isfinite(elev).all():
            break

    write_array(np.stack([elev, idx]), site, OUT / f"{site.id}.tif", PIXEL_M)
    with rasterio.open(OUT / f"{site.id}.tif", "r+") as r:
        r.descriptions = ("elevation_m", "source_index")
        r.update_tags(source_index=" ".join(f"{i}={s}" for i, s in enumerate(used, start=1)),
                      pixel_m=f"{PIXEL_M:.4f}", basis="Earth H3 r8 mean cell area, same on every body")
    v = elev[np.isfinite(elev)]
    return {"site": site.id, "body": site.body.name, "pixel_m": round(PIXEL_M, 3),
            "grid_px": elev.shape[0], "valid_fraction": round(float(v.size / elev.size), 4),
            "sources": "+".join(used), "elev_min_m": float(v.min()), "elev_max_m": float(v.max()),
            "elev_std_m": float(v.std())}


def main() -> None:
    terrain._baseline = lambda: PIXEL_M  # every terrain source warps at this pixel size
    rows = []
    for site in select(sys.argv[1] if len(sys.argv) > 1 else "all"):
        rows.append(build(site))
        print(rows[-1], flush=True)
    summary = pd.DataFrame(rows)
    summary.to_csv(OUT / "summary.csv", index=False)

    zpath = DATA / "export" / "elevation_r8_all_sites.zip"
    zpath.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(OUT.rglob("*")):
            if p.is_file():
                z.write(p, Path("elevation_r8") / p.relative_to(OUT))
    print(summary.to_string(index=False))
    print(f"zip: {zpath} ({zpath.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
