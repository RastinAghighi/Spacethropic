"""Windowed reads of remote or local rasters, warped onto a site-local grid.

Only the rows/columns around a site are read (via HTTP range requests for /vsicurl/ URLs),
so multi-GB global mosaics never have to be downloaded whole.
"""
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
import requests
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject, transform_bounds
from rasterio.windows import Window, from_bounds

from config import Site, local_crs, raster_half_extent_m


def http_provenance(url: str) -> dict:
    """Identity of a remote file at retrieval time, so a rerun can tell if it changed."""
    head = requests.head(url, allow_redirects=True, timeout=60)
    head.raise_for_status()
    return {
        "url": url,
        "etag": head.headers.get("ETag"),
        "last_modified": head.headers.get("Last-Modified"),
        "content_length": int(head.headers["Content-Length"]) if "Content-Length" in head.headers else None,
    }


def warp_to_site(
    paths: list[str],
    site: Site,
    out_path: Path,
    pixel_m: float,
    scale: float | None = None,
) -> dict:
    """Average each source onto a square site-local grid and write a float32 GeoTIFF.

    `paths` are opened in order; later ones only fill pixels the earlier ones left empty.
    `scale` overrides the file's own scale factor (needed where GDAL's label parsing adds an
    unwanted offset). Returns grid metadata for the manifest.
    """
    half = raster_half_extent_m(site)
    n = math.ceil(2 * half / pixel_m)
    dst_crs = local_crs(site)
    dst_transform = from_origin(-half, half, pixel_m, pixel_m)
    dst = np.full((n, n), np.nan, np.float32)

    for path in paths:
        with rasterio.open(path) as src:
            left, bottom, right, top = transform_bounds(dst_crs, src.crs, -half, -half, half, half, densify_pts=101)
            win = from_bounds(left, bottom, right, top, src.transform)
            col0, row0 = max(math.floor(win.col_off) - 2, 0), max(math.floor(win.row_off) - 2, 0)
            col1 = min(math.ceil(win.col_off + win.width) + 2, src.width)
            row1 = min(math.ceil(win.row_off + win.height) + 2, src.height)
            if col1 <= col0 or row1 <= row0:
                continue
            win = Window(col0, row0, col1 - col0, row1 - row0)
            arr = src.read(1, window=win, masked=True).astype(np.float32).filled(np.nan)
            k = scale if scale is not None else src.scales[0]
            off = 0.0 if scale is not None else src.offsets[0]
            arr = arr * np.float32(k) + np.float32(off)

            part = np.full((n, n), np.nan, np.float32)
            reproject(
                arr,
                part,
                src_transform=src.window_transform(win),
                src_crs=src.crs,
                src_nodata=np.nan,
                dst_transform=dst_transform,
                dst_crs=dst_crs,
                dst_nodata=np.nan,
                resampling=Resampling.average,
            )
            dst = np.where(np.isnan(dst), part, dst)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "width": n,
        "height": n,
        "count": 1,
        "dtype": "float32",
        "crs": dst_crs,
        "transform": dst_transform,
        "nodata": np.nan,
        "compress": "deflate",
    }
    with rasterio.open(out_path, "w", **profile) as out:
        out.write(dst, 1)
    return {
        "grid_pixel_m": pixel_m,
        "grid_size_px": n,
        "valid_fraction": float(np.isfinite(dst).mean()),
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
