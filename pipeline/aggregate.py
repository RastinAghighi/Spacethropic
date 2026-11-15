"""Summarise per-pixel features into per-cell distribution statistics."""
import h3
import numpy as np
import pandas as pd
from pyproj import Transformer
from rasterio import Affine

from config import Site, geographic_crs, local_crs, settings, window_radius_m
from layers import LAYERS, STATS


def _stats(values: np.ndarray, expected: int) -> list[float]:
    valid = values[np.isfinite(values)]
    if expected == 0 or valid.size / expected < settings()["min_valid_fraction"]:
        return [np.nan] * len(STATS)
    p10, p50, p90 = np.percentile(valid, [10, 50, 90])
    return [float(valid.mean()), float(valid.std()), float(p10), float(p50), float(p90)]


def aggregate(site: Site, cells: pd.DataFrame, features: dict[str, np.ndarray], transform: Affine) -> pd.DataFrame:
    h, w = next(iter(features.values())).shape
    px = transform.a
    xs = transform.c + (np.arange(w) + 0.5) * px
    ys = transform.f + (np.arange(h) + 0.5) * transform.e
    X, Y = np.meshgrid(xs, ys)

    # Which H3 cell each pixel centre falls in ("cell" windows).
    to_geo = Transformer.from_crs(local_crs(site), geographic_crs(site.body), always_xy=True)
    lon, lat = to_geo.transform(X.ravel(), Y.ravel())
    res = site.body.h3_res
    pixel_cell = np.array([h3.latlng_to_cell(la, lo, res) for la, lo in zip(lat, lon)])
    order = np.argsort(pixel_cell, kind="stable")
    sorted_cells = pixel_cell[order]
    starts = np.searchsorted(sorted_cells, cells["cell"].to_numpy(), side="left")
    ends = np.searchsorted(sorted_cells, cells["cell"].to_numpy(), side="right")

    # Cell centres on the local grid ("fixed" windows).
    to_xy = Transformer.from_crs(geographic_crs(site.body), local_crs(site), always_xy=True)
    cx, cy = to_xy.transform(cells["lon"].to_numpy(), cells["lat"].to_numpy())
    r = window_radius_m()
    rp = int(np.ceil(r / px)) + 1

    layers = [l for l in LAYERS if l.name in features]
    flat = {l.name: features[l.name].ravel() for l in layers}
    rows = []
    for i in range(len(cells)):
        row = {"cell": cells["cell"].iat[i]}
        in_cell = order[starts[i] : ends[i]]
        col = int((cx[i] - transform.c) / px)
        rowi = int((cy[i] - transform.f) / transform.e)
        r0, r1, c0, c1 = max(rowi - rp, 0), min(rowi + rp + 1, h), max(col - rp, 0), min(col + rp + 1, w)
        disk = (X[r0:r1, c0:c1] - cx[i]) ** 2 + (Y[r0:r1, c0:c1] - cy[i]) ** 2 <= r * r
        for layer in layers:
            if layer.window == "cell":
                vals, expected = flat[layer.name][in_cell], in_cell.size
            else:
                vals, expected = features[layer.name][r0:r1, c0:c1][disk], int(np.pi * r * r / (px * px))
            stats = dict(zip(STATS, _stats(vals, expected)))
            row.update({f"{layer.name}__{s}": stats[s] for s in layer.stats})
        rows.append(row)
    return pd.DataFrame(rows)
