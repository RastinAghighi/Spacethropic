"""Export small MCD12Q1 LC_Type1 GeoTIFFs (native 500 m sinusoidal grid, nodata 255) around a few
validation sites, so the regional pilot's exact pixel/hexagon overlap code (script 08, pilot venv,
which has h3 but no HDF4 reader) can be smoke-tested at H3 r7 on real local land cover.

Nothing is resampled: the GeoTIFF is the MODIS grid itself (MODIS sinusoidal sphere, R = 6371007.181 m).
Outputs: work/pilot_inputs/<site>_mcd12q1_lc.tif
Usage:   .venv/Scripts/python.exe -I scripts/07_export_pilot_rasters.py [--data DIR]
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
import validation_sites as VS  # noqa: E402

import numpy as np  # noqa: E402
import rasterio  # noqa: E402
from rasterio.transform import from_origin  # noqa: E402
from rasterio.warp import Resampling, calculate_default_transform, reproject  # noqa: E402

_spec = importlib.util.spec_from_file_location("sv", Path(__file__).resolve().parent / "05_site_validation.py")
SV = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SV)

SITES = ("hanksville_mdrs", "drumheller", "atacama_yungay", "probe_konza_grassland", "mcmurdo_beacon")
HALF_DEG = 0.12
SINU = "+proj=sinu +lon_0=0 +x_0=0 +y_0=0 +R=6371007.181 +units=m +no_defs"


def main() -> None:
    a = C.args(__doc__)
    out = C.WORK / "pilot_inputs"
    out.mkdir(parents=True, exist_ok=True)
    reader = SV.Q1Reader(a.data)
    for s in VS.SITES:
        if s["id"] not in SITES:
            continue
        dlon = HALF_DEG / max(np.cos(np.radians(s["lat"])), 0.05)
        lats = np.linspace(s["lat"] - HALF_DEG, s["lat"] + HALF_DEG, 25)
        lons = np.linspace(s["lon"] - dlon, s["lon"] + dlon, 25)
        LA, LO = np.meshgrid(lats, lons)
        gi, gj = SV.latlon_to_gij(LA.ravel(), LO.ravel())
        gi0, gi1, gj0, gj1 = int(gi.min()) - 3, int(gi.max()) + 4, int(gj.min()) - 3, int(gj.max()) + 4
        lc, _ = reader.window(gi0, gi1, gj0, gj1)
        t = from_origin(SV.X0 + gj0 * C.PIX_M, SV.Y0 - gi0 * C.PIX_M, C.PIX_M, C.PIX_M)
        p = out / f"{s['id']}_mcd12q1_lc.tif"
        with rasterio.open(p, "w", driver="GTiff", width=lc.shape[1], height=lc.shape[0], count=1, dtype="uint8",
                           crs=SINU, transform=t, nodata=255, compress="deflate") as dst:
            dst.write(lc, 1)
            dst.update_tags(source="MCD12Q1.061 2023 LC_Type1 (IGBP 1-17, 255 fill)", site=s["id"])
        # Nearest-neighbour copy on the site's UTM grid at 100 m (the pilot's raster contract allows
        # nearest-neighbour only). Each 463 m MODIS pixel becomes ~21 pixels; class areas shift only
        # at pixel edges.
        zone = int((s["lon"] + 180) // 6) + 1
        utm = f"EPSG:{32600 + zone if s['lat'] >= 0 else 32700 + zone}"
        dst_t, dw, dh = calculate_default_transform(SINU, utm, lc.shape[1], lc.shape[0],
                                                    *rasterio.transform.array_bounds(lc.shape[0], lc.shape[1], t),
                                                    resolution=100.0)
        u = np.full((dh, dw), 255, np.uint8)
        reproject(lc, u, src_transform=t, src_crs=SINU, dst_transform=dst_t, dst_crs=utm,
                  resampling=Resampling.nearest, src_nodata=255, dst_nodata=255)
        pu = out / f"{s['id']}_mcd12q1_lc_utm100m.tif"
        with rasterio.open(pu, "w", driver="GTiff", width=dw, height=dh, count=1, dtype="uint8",
                           crs=utm, transform=dst_t, nodata=255, compress="deflate") as dst:
            dst.write(u, 1)
            dst.update_tags(source="MCD12Q1.061 2023 LC_Type1, nearest-neighbour to UTM 100 m", site=s["id"])
        print(p.name, lc.shape, pu.name, u.shape, utm)


if __name__ == "__main__":
    main()
