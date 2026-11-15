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
from affine import Affine
from pyproj import Transformer
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject, transform_bounds
from rasterio.windows import Window, from_bounds

from config import Site, geographic_crs, local_crs, raster_half_extent_m


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


def site_grid(site: Site, pixel_m: float):
    half = raster_half_extent_m(site)
    n = math.ceil(2 * half / pixel_m)
    return n, from_origin(-half, half, pixel_m, pixel_m)


def warp_array(
    paths: list[str],
    site: Site,
    pixel_m: float,
    scale: float | None = None,
    offset: float = 0.0,
    resampling: Resampling = Resampling.average,
    read_res_m: float | None = None,
) -> np.ndarray:
    """Resample sources onto the square site-local grid (float32, NaN = no data).

    `paths` are opened in order; later ones only fill pixels the earlier ones left empty.
    `scale`/`offset` override the file's own (GDAL's PDS label parsing can add an unwanted
    offset). `read_res_m` reads a projected source decimated to about that pixel size, letting
    GDAL use COG overviews instead of fetching full-resolution tiles.
    """
    n, dst_transform = site_grid(site, pixel_m)
    half = raster_half_extent_m(site)
    dst_crs = local_crs(site)
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
            factor = max(read_res_m / src.res[0], 1.0) if read_res_m else 1.0
            shape = (max(round(win.height / factor), 1), max(round(win.width / factor), 1))
            arr = src.read(1, window=win, out_shape=shape, masked=True, resampling=resampling)
            arr = arr.astype(np.float32).filled(np.nan)
            k = scale if scale is not None else src.scales[0]
            off = offset if scale is not None else src.offsets[0]
            arr = arr * np.float32(k) + np.float32(off)
            src_transform = src.window_transform(win) * Affine.scale(win.width / shape[1], win.height / shape[0])

            part = np.full((n, n), np.nan, np.float32)
            reproject(
                arr,
                part,
                src_transform=src_transform,
                src_crs=src.crs,
                src_nodata=np.nan,
                dst_transform=dst_transform,
                dst_crs=dst_crs,
                dst_nodata=np.nan,
                resampling=resampling,
            )
            dst = np.where(np.isnan(dst), part, dst)
    return dst


def warp_to_site(paths: list[str], site: Site, out_path: Path, pixel_m: float, scale: float | None = None) -> dict:
    """`warp_array`, written as a GeoTIFF; returns grid metadata for the manifest."""
    _, transform = site_grid(site, pixel_m)
    return _write(warp_array(paths, site, pixel_m, scale), site, out_path, pixel_m, transform)


def write_array(arr: np.ndarray, site: Site, out_path: Path, pixel_m: float) -> dict:
    _, transform = site_grid(site, pixel_m)
    return _write(arr.astype(np.float32), site, out_path, pixel_m, transform)


def write_site_raster(site: Site, out_path: Path, pixel_m: float, value_at, bands: tuple[str, ...] | None = None) -> dict:
    """Rasterise a function of (lat, lon) arrays onto the site-local grid. Used for tabular
    or computed sources that aren't rasters themselves. With `bands`, `value_at` returns
    (len(bands), h, w) and each band is named in the GeoTIFF."""
    half = raster_half_extent_m(site)
    n = math.ceil(2 * half / pixel_m)
    transform = from_origin(-half, half, pixel_m, pixel_m)
    centres = -half + (np.arange(n) + 0.5) * pixel_m
    X, Y = np.meshgrid(centres, -centres)
    to_geo = Transformer.from_crs(local_crs(site), geographic_crs(site.body), always_xy=True)
    lon, lat = to_geo.transform(X, Y)
    lon = (lon + 180) % 360 - 180  # [-180, 180); sources re-wrap if they use 0..360
    return _write(np.asarray(value_at(lat, lon), np.float32), site, out_path, pixel_m, transform, bands)


def _write(arr: np.ndarray, site: Site, out_path: Path, pixel_m: float, transform, bands: tuple[str, ...] | None = None) -> dict:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    arr = arr if arr.ndim == 3 else arr[None]
    profile = {
        "driver": "GTiff",
        "width": arr.shape[2],
        "height": arr.shape[1],
        "count": arr.shape[0],
        "dtype": "float32",
        "crs": local_crs(site),
        "transform": transform,
        "nodata": np.nan,
        "compress": "deflate",
    }
    with rasterio.open(out_path, "w", **profile) as out:
        out.write(arr)
        if bands:
            out.descriptions = tuple(bands)
    return {
        "grid_pixel_m": pixel_m,
        "grid_size_px": arr.shape[1],
        **({"bands": list(bands)} if bands else {}),
        "valid_fraction": float(np.isfinite(arr).mean()),
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
