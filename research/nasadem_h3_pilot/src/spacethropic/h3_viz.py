"""Map of H3 cells coloured by area-weighted mean slope, with the analysis bounds marked.

Only the observed part of each cell (cell polygon intersect analysed footprint) is
coloured. The rest of a partial hexagon is drawn as an outline over a neutral
fill, so the map never suggests data outside the analysed area.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from matplotlib.collections import PolyCollection
from matplotlib.colors import Normalize, to_rgb
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle

from . import geodesy
from .viz import AXIS, BLUE, SURFACE, TEXT, TEXT_2, _colorbar, _deg_fmt, _style

UNOBSERVED = "#ecebe7"  # neutral: outside the analysed footprint, no data
EDGE = "#52514e"
BOUNDS = "#0b0b0b"
MAX_VALUE_LABELS = 40  # print the value in each cell only when there are few cells


def _relative_luminance(rgb) -> float:
    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(c) for c in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def plot_mean_slope(result, run_summary: dict, path: Path, dpi: int = 150) -> Path:
    recs = result.records
    geoms = result.geometries
    slope = np.array([np.nan if r["slope_mean_deg"] is None else r["slope_mean_deg"] for r in recs])
    finite = slope[np.isfinite(slope)]
    vmax = float(finite.max()) if finite.size else 1.0
    norm = Normalize(0.0, vmax if vmax > 0 else 1.0)
    cmap = BLUE

    allpts = np.vstack([g.boundary_lonlat for g in geoms])
    aoi = run_summary["aoi"]
    req = aoi["requested_bbox_deg"]
    lon0 = min(allpts[:, 0].min(), req["west"])
    lon1 = max(allpts[:, 0].max(), req["east"])
    lat0 = min(allpts[:, 1].min(), req["south"])
    lat1 = max(allpts[:, 1].max(), req["north"])
    pad_lon, pad_lat = 0.03 * (lon1 - lon0), 0.03 * (lat1 - lat0)
    mid_lat = 0.5 * (lat0 + lat1)
    aspect = float(geodesy.metres_per_degree_lat(mid_lat) / geodesy.metres_per_degree_lon(mid_lat))
    width_in = 8.6
    map_h = min(max(width_in * 0.78 * aspect * (lat1 - lat0) / (lon1 - lon0), 4.0), 9.0)

    fig = Figure(figsize=(width_in, map_h + 1.9), facecolor=SURFACE, layout="constrained")
    ax = fig.subplots()
    _style(ax, "")

    ax.add_collection(PolyCollection([g.boundary_lonlat for g in geoms], facecolors=UNOBSERVED, edgecolors="none"))
    colours = [cmap(norm(v)) if math.isfinite(v) else to_rgb(UNOBSERVED) for v in slope]
    observed = [g.overlap_lonlat for g in geoms]
    ax.add_collection(PolyCollection(observed, facecolors=colours, edgecolors="none"))
    ax.add_collection(PolyCollection([g.boundary_lonlat for g in geoms], facecolors="none", edgecolors=EDGE,
                                     linewidths=0.9 if len(geoms) <= MAX_VALUE_LABELS else 0.45))
    ax.add_patch(Rectangle((req["west"], req["south"]), req["east"] - req["west"], req["north"] - req["south"],
                           fill=False, edgecolor=BOUNDS, linewidth=2.2, zorder=5))

    if len(geoms) <= MAX_VALUE_LABELS:
        for g, v, c in zip(geoms, slope, colours):
            if not math.isfinite(v) or g.overlap_area_m2 < 0.08 * g.area_m2:
                continue  # too small a sliver to hold a label
            x, y = g.overlap_lonlat.mean(axis=0)
            ink = "#ffffff" if _relative_luminance(c) < 0.25 else TEXT
            ax.text(x, y, f"{v:.1f}°", ha="center", va="center", fontsize=8, color=ink, zorder=6)

    ax.set_xlim(lon0 - pad_lon, lon1 + pad_lon)
    ax.set_ylim(lat0 - pad_lat, lat1 + pad_lat)
    ax.set_aspect(aspect)
    _colorbar(fig, ax, norm, cmap, "Mean slope (°), area-weighted over observed samples")

    t = result.totals
    lon_f, lat_f = _deg_fmt(("E", "W")), _deg_fmt(("N", "S"))
    tiles = ", ".join(gr["tile_id"] for gr in run_summary["source"]["granules"])
    fig.suptitle(
        f"Mean slope per H3 cell · resolution {result.resolution} · NASADEM_HGT {tiles} · AOI '{aoi['name']}'\n"
        f"{t['n_cells']} cells ({t['n_cells_complete']} complete, {t['n_cells_partial']} partial); "
        f"{t['n_samples']:,} samples, {t['sampled_area_km2']:.2f} km²; "
        f"slope = 1″ Horn 3×3, computed before assignment",
        color=TEXT, fontsize=10,
    )
    handles = [
        Line2D([], [], color=BOUNDS, linewidth=2.2,
               label=f"Analysis bounds {lon_f(req['west'], 0)} to {lon_f(req['east'], 0)}, "
                     f"{lat_f(req['south'], 0)} to {lat_f(req['north'], 0)}"),
        Patch(facecolor="none", edgecolor=EDGE, label="H3 cell boundary"),
        Patch(facecolor=UNOBSERVED, edgecolor=AXIS, label="Part of cell outside the bounds (no data)"),
    ]
    fig.legend(handles=handles, loc="outside lower center", ncols=2, frameon=False, labelcolor=TEXT_2, fontsize=8.5)
    fig.savefig(path, dpi=dpi, facecolor=SURFACE)
    return path
