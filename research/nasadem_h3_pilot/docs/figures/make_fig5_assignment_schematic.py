"""Schematic: pixel-centre assignment of NASADEM 1-arc-second samples to H3 resolution-8 cells.

Geometry only. It uses the real NASADEM sample lattice (lat = 52 - r/3600, lon = -113 + c/3600
for tile n51w113) and real H3 v4 cell boundaries near Drumheller. It reads NO elevation data and
shows no measured values. Output: one PNG (path given as argv[1]).
"""

from __future__ import annotations

import sys
from pathlib import Path

import h3
import numpy as np
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle

from spacethropic import geodesy

OUT = Path(sys.argv[1])
RES = 8
TOWN = (51.4636, -112.7106)  # approximate Drumheller town coordinates, as in scientific_validation.md 5.4
HALF_ROWS, HALF_COLS = 5, 8  # window of 11 x 17 samples (about 310 m x 330 m)

SURFACE, TEXT, TEXT_2, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#c9c8c3"
NEUTRAL_FILL, NEUTRAL_DOT = "#e4e3df", "#8e8d88"
EDGE = "#0b0b0b"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]  # categorical slots 1-3 (validated all-pairs, light mode)
MARKERS = ["o", "s", "^"]

cell0 = h3.latlng_to_cell(*TOWN, RES)
v_lat, v_lon = h3.cell_to_boundary(cell0)[0]  # a vertex shared by three cells
r0 = round((52.0 - v_lat) * 3600)
c0 = round((v_lon + 113.0) * 3600)
rows = np.arange(r0 - HALF_ROWS, r0 + HALF_ROWS + 1)
cols = np.arange(c0 - HALF_COLS, c0 + HALF_COLS + 1)
lats = 52.0 - rows / 3600.0
lons = -113.0 + cols / 3600.0

m_lat = float(geodesy.metres_per_degree_lat(v_lat))
m_lon_rows = geodesy.metres_per_degree_lon(lats)  # east-west metres per degree, per row


def to_xy(lat, lon):
    """Local metres east/north of the shared H3 vertex (adequate over a few hundred metres)."""
    return (np.asarray(lon) - v_lon) * float(geodesy.metres_per_degree_lon(v_lat)), (np.asarray(lat) - v_lat) * m_lat


assign = np.array([[h3.latlng_to_cell(la, lo, RES) for lo in lons] for la in lats])  # latitude first
cells = sorted(set(assign.ravel().tolist()))
if len(cells) > 3:
    raise SystemExit(f"window holds {len(cells)} cells; shrink it")
colour = {c: SERIES[i] for i, c in enumerate(cells)}
marker = {c: MARKERS[i] for i, c in enumerate(cells)}

dy_m = m_lat / 3600.0
xs, ys = np.broadcast_arrays(*to_xy(lats[:, None], lons[None, :]))
dx_rows = m_lon_rows / 3600.0

# A sample whose footprint is clearly cut by a cell edge (two of its four corners lie in another
# cell), chosen on the lower-right edge so its label can sit below the grid.
straddle = None
best = 1e9
h = 0.5 / 3600.0
for i, la in enumerate(lats):
    for j, lo in enumerate(lons):
        corner_cells = [h3.latlng_to_cell(la + a, lo + b, RES) for a in (-h, h) for b in (-h, h)]
        n_other = sum(cc != assign[i, j] for cc in corner_cells)
        if n_other == 2:
            d = np.hypot(xs[i, j] - 110.0, ys[i, j] + 35.0)
            if d < best:
                best, straddle = d, (i, j)
# A 3x3 derivative window whose nine samples span more than one cell.
win = None
for i in range(1, len(lats) - 1):
    for j in range(1, len(lons) - 1):
        if len(set(assign[i - 1 : i + 2, j - 1 : j + 2].ravel().tolist())) >= 2 and abs(i - HALF_ROWS) <= 2 and j < HALF_COLS - 3:
            win = (i, j)
            break
    if win:
        break

fig = Figure(figsize=(10.6, 7.6), facecolor=SURFACE, layout="constrained")
axes = fig.subplots(1, 2, sharex=True, sharey=True)


def draw_pixels(ax, coloured: bool) -> None:
    for i in range(len(lats)):
        for j in range(len(lons)):
            c = assign[i, j]
            w, h = dx_rows[i], dy_m
            fill = NEUTRAL_FILL
            if coloured:
                rgb = np.array([int(colour[c][k : k + 2], 16) for k in (1, 3, 5)]) / 255.0
                fill = tuple(0.72 * np.ones(3) + 0.28 * rgb)  # light tint of the cell colour
            ax.add_patch(Rectangle((xs[i, j] - w / 2, ys[i, j] - h / 2), w, h, facecolor=fill,
                                   edgecolor=SURFACE, linewidth=1.2, zorder=1))
    for c in cells:
        sel = assign == c
        ax.scatter(xs[sel], ys[sel], s=26, marker=marker[c] if coloured else "o",
                   c=colour[c] if coloured else NEUTRAL_DOT, edgecolors=SURFACE, linewidths=0.6, zorder=3)


def draw_window(ax) -> None:
    i, j = win
    x0 = xs[i, j - 1] - dx_rows[i] / 2
    y0 = ys[i + 1, j] - dy_m / 2
    ax.add_patch(Rectangle((x0, y0), 3 * dx_rows[i], 3 * dy_m, fill=False, edgecolor=EDGE,
                           linewidth=1.8, linestyle=(0, (4, 2)), zorder=4))


def draw_boundaries(ax) -> None:
    for c in cells:
        ring = np.asarray(h3.cell_to_boundary(c))
        ring = np.vstack([ring, ring[:1]])
        bx, by = to_xy(ring[:, 0], ring[:, 1])  # cell_to_boundary returns (lat, lng)
        ax.plot(bx, by, color=EDGE, linewidth=2.0, zorder=5)


def style(ax, title: str) -> None:
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", color=TEXT, fontsize=10.5)
    ax.tick_params(colors=AXIS, labelcolor=TEXT_2, labelsize=8.5)
    for s in ax.spines.values():
        s.set_color(AXIS)
    ax.set_xlabel("metres east of the shared H3 vertex", color=TEXT_2, fontsize=9)
    ax.set_aspect("equal")


left, right = axes
draw_pixels(left, coloured=False)
draw_window(left)
style(left, "1  Native NASADEM samples (pixel-is-point, 1″ lattice)")
left.set_ylabel("metres north of the shared H3 vertex", color=TEXT_2, fontsize=9)
i, j = win
left.annotate("3×3 window for slope, TRI and roughness: computed\non the full grid BEFORE any H3 step, so it may\nuse samples that end up in neighbouring cells",
              xy=(xs[i + 1, j], ys[i + 1, j] - dy_m / 2), xytext=(xs[-1, 0] - dx_rows[-1] / 2, ys[-1, 0] - 1.0 * dy_m),
              fontsize=8.5, color=TEXT, ha="left", va="top",
              arrowprops=dict(arrowstyle="-", color=TEXT_2, linewidth=0.9), zorder=6)
j0 = len(lons) - 1
left.add_patch(Rectangle((xs[0, j0] - dx_rows[0] / 2, ys[0, j0] - dy_m / 2), dx_rows[0], dy_m, fill=False,
                         edgecolor=EDGE, linewidth=1.6, zorder=4))
left.annotate(f"one sample footprint ≈ {dx_rows[HALF_ROWS]:.1f} m E–W × {dy_m:.1f} m N–S",
              xy=(xs[0, j0], ys[0, j0] + dy_m / 2), xytext=(xs[0, j0] + dx_rows[0] / 2, ys[0, j0] + 1.2 * dy_m),
              fontsize=8.5, color=TEXT, ha="right", va="bottom",
              arrowprops=dict(arrowstyle="-", color=TEXT_2, linewidth=0.9), zorder=6)

draw_pixels(right, coloured=True)
draw_window(right)
draw_boundaries(right)
style(right, "2  Each sample assigned to the H3 cell holding its centre")
for k, c in enumerate(cells):
    sel = assign == c
    cx, cy = xs[sel].mean() - (50.0 if k == 2 else 0.0), ys[sel].mean()  # keep the third label off the leader line
    right.text(cx, cy, c, ha="center", va="center", fontsize=8.5, color=TEXT, zorder=7,
               bbox=dict(boxstyle="round,pad=0.25", facecolor=SURFACE, edgecolor=colour[c], linewidth=1.4))
si, sj = straddle
right.add_patch(Rectangle((xs[si, sj] - dx_rows[si] / 2, ys[si, sj] - dy_m / 2), dx_rows[si], dy_m, fill=False,
                          edgecolor=EDGE, linewidth=1.8, zorder=6))
right.annotate("this footprint is cut by a cell edge but is counted\nwholly in the cell that holds its centre (pixel-centre rule)",
               xy=(xs[si, sj], ys[si, sj] - dy_m / 2), xytext=(xs[-1, -1] + dx_rows[-1] / 2, ys[-1, 0] - 1.0 * dy_m),
               fontsize=8.5, color=TEXT, ha="right", va="top",
               arrowprops=dict(arrowstyle="-", color=TEXT_2, linewidth=0.9), zorder=8)

pad = 1.0
for ax in axes:
    ax.set_xlim(xs.min() - dx_rows.max() / 2 - pad, xs.max() + dx_rows.max() / 2 + pad)
    ax.set_ylim(ys.min() - 2.6 * dy_m, ys.max() + 2.6 * dy_m)

handles = [Line2D([], [], color=c_, marker=m_, linestyle="none", markersize=7, label=f"sample assigned to {c}")
           for c, c_, m_ in zip(cells, SERIES, MARKERS)]
handles += [Line2D([], [], color=EDGE, linewidth=2.0, label="H3 resolution-8 cell boundary"),
            Patch(facecolor="none", edgecolor=EDGE, linestyle="--", label="example 3×3 derivative window")]
fig.legend(handles=handles, loc="outside lower center", ncols=3, frameon=False, labelcolor=TEXT_2, fontsize=8.5)
fig.suptitle(
    "SCHEMATIC (geometry only, no measured values): how NASADEM samples become H3 cell members\n"
    f"Real n51w113 1″ sample positions and real H3 v4 resolution-8 boundaries at a cell vertex near Drumheller "
    f"({v_lat:.4f}°N, {abs(v_lon):.4f}°W).\n"
    "A resolution-8 cell holds about 1,200 samples, so only the corner where three cells meet is shown.",
    color=TEXT, fontsize=10,
)
fig.savefig(OUT, dpi=150, facecolor=SURFACE)
print(f"cells {cells}; vertex {v_lat:.6f}, {v_lon:.6f}; straddle {straddle}; window {win}; wrote {OUT}")
