"""Fetch a small real Copernicus GLO-30 overview crop for the Drumheller contour demo."""

import argparse
from pathlib import Path

import numpy as np
import rasterio
import requests
from core import atomic_json, digest
from rasterio.enums import Resampling
from rasterio.windows import from_bounds

TILE = "Copernicus_DSM_COG_10_N51_00_W113_00_DEM"
URL = f"https://copernicus-dem-30m.s3.amazonaws.com/{TILE}/{TILE}.tif"


def fetch(out):
    if out.exists():
        raise FileExistsError(f"Demo raster already exists: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    bounds = (-112.85, 51.35, -112.55, 51.57)
    with rasterio.Env(
        GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
        GDAL_HTTP_MAX_RETRY="3",
        GDAL_HTTP_TIMEOUT="60",
        CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
    ):
        with rasterio.open(URL) as src:
            win = from_bounds(*bounds, src.transform).round_offsets().round_lengths()
            height, width = max(2, round(win.height / 8)), max(2, round(win.width / 8))
            z = src.read(
                1,
                window=win,
                out_shape=(height, width),
                resampling=Resampling.average,
                masked=True,
            )
            tr = src.window_transform(win) * rasterio.Affine.scale(
                win.width / width, win.height / height
            )
            with rasterio.open(
                out,
                "w",
                driver="GTiff",
                width=width,
                height=height,
                count=1,
                dtype="float32",
                crs=src.crs,
                transform=tr,
                nodata=-32767,
                compress="deflate",
            ) as dst:
                dst.write(z.filled(-32767).astype(np.float32), 1)
                dst.update_tags(
                    source_url=URL,
                    vertical_datum="EGM2008",
                    overview="8x; nominal 240m latitude",
                )
    r = requests.head(URL, timeout=30)
    r.raise_for_status()
    atomic_json(
        out.with_suffix(".json"),
        dict(
            url=URL,
            etag=r.headers.get("ETag"),
            source_last_modified=r.headers.get("Last-Modified"),
            sha256=digest(out),
            bounds=list(bounds),
            shape=[height, width],
            product="Copernicus DEM GLO-30",
            vertical_datum="EGM2008",
            resampling="average at approximately 8x overview; DSM not bare-earth terrain",
        ),
    )
    print(f"Downloaded real DEM crop: {out}, {height} x {width}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    fetch(p.parse_args().output)
