"""Static 2 x 2 overview figure of an AOI's terrain layers, for visual inspection."""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from matplotlib.cm import ScalarMappable
from matplotlib.colors import LinearSegmentedColormap, Normalize, to_rgb
from matplotlib.figure import Figure
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter, MaxNLocator

from . import geodesy

if TYPE_CHECKING:
    from .pipeline import TerrainLayers

SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
AXIS = "#c9c8c3"
WATER = "#8e8d88"  # neutral: water is a mask, not a magnitude
# Single-hue sequential ramps, light -> dark.
BLUE = LinearSegmentedColormap.from_list(
    "spacethropic_blue", ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
)
ORANGE = LinearSegmentedColormap.from_list(
    "spacethropic_orange", ["#fde8dd", "#f6b493", "#eb6834", "#b4471c", "#6b2a10"]
)
MAX_DISPLAY_PX = 1500


def _deg_fmt(hemis: tuple[str, str]):
    def fmt(v, _pos):
        text = f"{abs(v):.3f}".rstrip("0").rstrip(".")
        return f"{text}°{hemis[0] if v >= 0 else hemis[1]}"

    return FuncFormatter(fmt)


def _style(ax, title: str) -> None:
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", color=TEXT, fontsize=10)
    ax.tick_params(colors=AXIS, labelcolor=TEXT_2, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(AXIS)
    ax.xaxis.set_major_locator(MaxNLocator(nbins=4))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
    ax.xaxis.set_major_formatter(_deg_fmt(("E", "W")))
    ax.yaxis.set_major_formatter(_deg_fmt(("N", "S")))


def _colorbar(fig, ax, norm, cmap, label: str, extend: str = "neither") -> None:
    cb = fig.colorbar(ScalarMappable(norm=norm, cmap=cmap), ax=ax, shrink=0.85, extend=extend)
    cb.set_label(label, color=TEXT_2, fontsize=9)
    cb.ax.tick_params(colors=AXIS, labelcolor=TEXT_2, labelsize=8)
    cb.outline.set_edgecolor(AXIS)


def plot_overview(layers: "TerrainLayers", summary: dict, path: Path, dpi: int = 150) -> Path:
    g = layers.grid
    step = max(1, math.ceil(max(g.nrows, g.ncols) / MAX_DISPLAY_PX))
    sub = (slice(None, None, step), slice(None, None, step))
    z = layers.elevation_m[sub]
    mask = layers.analysis_mask[sub]
    water = layers.water[sub]
    hs = layers.hillshade[sub]

    extent = [g.west - g.lon_step / 2, g.east + g.lon_step / 2, g.south - g.lat_step / 2, g.north + g.lat_step / 2]
    mid_lat = 0.5 * (g.north + g.south)
    aspect = float(geodesy.metres_per_degree_lat(mid_lat) / geodesy.metres_per_degree_lon(mid_lat))
    # Size panels to the AOI's true ground shape (height / width in metres).
    panel_w = 4.6
    panel_h = min(max(panel_w * aspect * (extent[3] - extent[2]) / (extent[1] - extent[0]), 2.5), 8.0)

    fig = Figure(figsize=(2 * panel_w + 3.0, 2 * panel_h + 1.6), facecolor=SURFACE, layout="constrained")
    axes = fig.subplots(2, 2)
    water_rgba = np.zeros(z.shape + (4,))
    water_rgba[water] = (*to_rgb(WATER), 1.0)

    # Elevation coloured on a single-hue ramp, modulated by hillshade.
    ax = axes[0, 0]
    zmask = z[mask & np.isfinite(z)]
    lo, hi = (np.percentile(zmask, [0.5, 99.5]) if zmask.size else (0.0, 1.0))
    norm = Normalize(lo, hi)
    rgb = ORANGE(norm(np.nan_to_num(z, nan=lo)))[..., :3]
    shade = 0.45 + 0.55 * np.nan_to_num(hs, nan=math.sin(math.radians(45.0)))
    rgb = rgb * shade[..., None]
    rgb[~np.isfinite(z)] = to_rgb(SURFACE)
    rgb[water] = to_rgb(WATER)
    ax.imshow(rgb, extent=extent, origin="upper")
    _style(ax, "Elevation (m above EGM96 geoid), hillshaded")
    _colorbar(fig, ax, norm, ORANGE, "Elevation (m)", extend="both")
    ax.set_aspect(aspect)

    panels = (
        (axes[0, 1], layers.slope_deg[sub], "Slope (degrees)", "Slope (°)"),
        (axes[1, 0], layers.tri_m[sub], "Terrain Ruggedness Index, Riley 1999 (m)", "TRI (m)"),
        (axes[1, 1], layers.roughness_m[sub], "Detrended roughness, 3×3 plane-fit RMS (m)", "Roughness (m)"),
    )
    for ax, data, title, label in panels:
        shown = np.where(mask, data, np.nan)
        vals = shown[np.isfinite(shown)]
        vmax = float(np.percentile(vals, 99)) if vals.size else 1.0
        norm = Normalize(0.0, vmax if vmax > 0 else 1.0)
        cmap = BLUE.with_extremes(bad=(0, 0, 0, 0))
        ax.imshow(shown, extent=extent, origin="upper", cmap=cmap, norm=norm)
        ax.imshow(water_rgba, extent=extent, origin="upper")
        _style(ax, title)
        _colorbar(fig, ax, norm, BLUE, label, extend="max")
        ax.set_aspect(aspect)

    aoi = summary["aoi"]
    b = aoi["requested_bbox_deg"]
    exclude = summary["parameters"]["exclude_water"]
    lon_f, lat_f = _deg_fmt(("E", "W")), _deg_fmt(("N", "S"))
    fig.suptitle(
        f"NASADEM_HGT {summary['granule']['tile_id']} · AOI '{aoi['name']}' · "
        f"{lon_f(b['west'], 0)} to {lon_f(b['east'], 0)}, {lat_f(b['south'], 0)} to {lat_f(b['north'], 0)}\n"
        f"Hillshade z×{summary['parameters']['visualisation_hillshade_z_factor']:g} (display only); "
        f"slope/roughness colour scales clipped at the 99th percentile"
        + (f"; display decimated {step}x" if step > 1 else ""),
        color=TEXT,
        fontsize=11,
    )
    if water.any():
        label = "Water (SWB mask), excluded from statistics" if exclude else "Water (SWB mask)"
        fig.legend(handles=[Patch(facecolor=WATER, label=label)], loc="outside lower center", frameon=False,
                   labelcolor=TEXT_2, fontsize=9)
    fig.savefig(path, dpi=dpi, facecolor=SURFACE)
    return path
