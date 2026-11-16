"""
Figures for the research write-up, generated from the live search code and data.

    .venv/Scripts/python paper_figures.py      # -> ../docs/science/figures/*.png, prints the numbers used

Every number in the figures is measured here, on the same 52,852 Nevada cells the app searches.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LightSource, LinearSegmentedColormap, ListedColormap
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch

import api
from shape import ANGLES, HALF, MASK, NPIX, PX_M, Index, target_variants

OUT = Path(__file__).resolve().parent.parent / "docs" / "science" / "figures"
OUT.mkdir(parents=True, exist_ok=True)
NUM: dict = {}

# --- style -------------------------------------------------------------------------
INK, MUTED, FAINT, RULE = "#1d1f24", "#6b7079", "#a9adb4", "#e6e7ea"
MOON, MARS, EARTH, AMBER = "#6a7fa8", "#c8643b", "#2f7d6d", "#d79a2b"
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9, "text.color": INK, "axes.labelcolor": MUTED,
    "axes.edgecolor": RULE, "axes.linewidth": 0.8, "xtick.color": MUTED, "ytick.color": MUTED,
    "xtick.major.size": 0, "ytick.major.size": 0, "axes.spines.top": False, "axes.spines.right": False,
    "axes.titlesize": 10, "axes.titleweight": "medium", "axes.titlecolor": INK, "axes.titlelocation": "left",
    "axes.titlepad": 8, "figure.dpi": 100, "savefig.dpi": 200, "savefig.bbox": "tight", "savefig.pad_inches": 0.15,
    "legend.frameon": False, "axes.grid": False,
})
RAMP = LinearSegmentedColormap.from_list("relief", ["#1e3a4c", "#2f6670", "#7f9f7a", "#d5c08c", "#f3eee4"])
LS = LightSource(azdeg=315, altdeg=40)


def save(fig, name):
    fig.savefig(OUT / name, facecolor="white")
    plt.close(fig)
    print("wrote", name)


def disk(ax, patch, lim, ring=None, label=None, sub=None):
    """A 200 m-pixel relief disk: hillshaded ramp, clipped to the cell's circle."""
    p = patch - patch[MASK].mean()
    rgb = LS.shade(np.clip(p, -lim, lim), cmap=RAMP, vert_exag=6, blend_mode="soft", vmin=-lim, vmax=lim, dx=PX_M, dy=PX_M)
    rgb[~MASK] = 1
    r = HALF + 0.5
    im = ax.imshow(rgb, interpolation="nearest", extent=[-r, r, -r, r])
    c = Circle((0, 0), np.sqrt(MASK.sum() / np.pi), transform=ax.transData)
    im.set_clip_path(c)
    ax.add_patch(Circle((0, 0), np.sqrt(MASK.sum() / np.pi), fill=False, lw=1.6 if ring else 0.6, ec=ring or RULE))
    ax.set_xlim(-r, r), ax.set_ylim(-r, r), ax.set_aspect("equal"), ax.axis("off")
    if label:
        ax.text(0, -r - 1.2, label, ha="center", va="top", fontsize=8.5, color=INK)
    if sub:
        ax.text(0, -r - 3.4, sub, ha="center", va="top", fontsize=7.5, color=MUTED)


def distinct(top, rmse, rot, n, km=25):
    out = []
    for i, e, o in zip(top, rmse, rot):
        if all(api.km((api.LAT[i], api.LON[i]), (api.LAT[j], api.LON[j])) >= km for j, *_ in out):
            out.append((i, e, o))
        if len(out) == n:
            break
    return out


TARGETS = [
    ("Shackleton rim", "moon", -89.67, 129.78, MOON),
    ("Hadley Rille (Apollo 15)", "moon", 26.13, 3.63, MOON),
    ("Descartes (Apollo 16)", "moon", -8.97, 15.5, MOON),
    ("Jezero delta", "mars", 18.38, 77.58, MARS),
    ("Gale crater", "mars", -5.4, 137.8, MARS),
    ("Meridiani Planum", "mars", -1.95, -5.53, MARS),
    ("Utopia Planitia", "mars", 46.7, 117.5, MARS),
]
IX = api.INDEX
N = len(api.CELLS)

# --- fetch targets (timed: this is the live ranged read from USGS) ---------------------
TV = {}
fetch_s = []
for name, body, la, lo, _ in TARGETS:
    t = time.time()
    TV[name] = api.target(body, round(la, 4), round(lo, 4))
    fetch_s.append(time.time() - t)
NUM["target_fetch_s"] = [round(x, 2) for x in fetch_s]


# =====================================================================================
# 1. Pipeline
# =====================================================================================
def fig_pipeline():
    fig, ax = plt.subplots(figsize=(12, 4.3))
    ax.set_xlim(0, 120), ax.set_ylim(0, 43), ax.axis("off")

    def box(x, y, w, h, title, body, color=INK, fill="#f6f7f8"):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.4,rounding_size=1.6", fc=fill, ec=RULE, lw=0.8))
        ax.add_patch(FancyBboxPatch((x, y + h - 0.25), 3.2, 0.5, boxstyle="round,pad=0,rounding_size=0.25", fc=color, ec="none"))
        ax.text(x + 0.2, y + h - 1.9, title, fontsize=9.5, weight="medium", va="top", color=INK)
        ax.text(x + 0.2, y + h - 5.0, body, fontsize=7.1, va="top", color=MUTED, linespacing=1.5)

    def arrow(a, b, rad=0.0):
        ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=9, lw=0.9, color=FAINT, connectionstyle=f"arc3,rad={rad}"))

    box(1, 25, 24, 15, "Target point", "Any Moon or Mars lat/lon:\na named site or a dropped pin.\nUSGS LOLA 118 m (Moon),\nHRSC+MOLA 200 m (Mars).", MARS)
    box(1, 2, 24, 15, "Earth candidates", "H3 resolution-7 cells\n(Earth-sized, 5.16 km² each).\nNevada pilot: 52,852 cells,\nCopernicus GLO-90 DEM.", EARTH)
    box(32, 25, 24, 15, "Shape descriptor", "Elevation in a 5.16 km² disk\nat 200 m (137 px), mean removed.\nTarget turned 24 ways (15°).", INK)
    box(32, 2, 24, 15, "Per-cell measurements", "Terrain: slope, relief, roughness.\nClimate: ERA5 reanalysis, CAMS dust.\nSurface: WRB 2006 soil map.\nTarget climate: Diviner, MCD.", INK)
    box(63, 13.5, 24, 15, "Filter, then rank", "Limits cut the candidate set first.\nRotation-invariant RMSE, visited\nin order of a lossless lower bound.\nSame top 50 as brute force.", AMBER)
    box(94, 25, 25, 15, "8 distinct sites", "≥ 25 km apart. If limits leave < 5,\nnearest near-misses fill in,\nflagged with what they miss.", INK)
    box(94, 2, 25, 15, "Characterise", "Sentinel-2 imagery of the site.\nMeasured gaps vs the target.\nLLM writes holds / breaks / use\nfrom the numbers only.", INK)
    arrow((25.8, 32.5), (31.2, 32.5))
    arrow((25.8, 9.5), (31.2, 9.5))
    arrow((56.8, 32.5), (62.2, 23))
    arrow((56.8, 9.5), (62.2, 19))
    arrow((87.8, 23), (93.2, 32.5))
    arrow((106.5, 24.2), (106.5, 17.8))
    save(fig, "01_pipeline.png")


# =====================================================================================
# 2. Descriptor: from a raster to a rotation-invariant shape
# =====================================================================================
def fig_descriptor():
    name = "Jezero delta"
    T, P = TV[name]
    top, rmse, rot, _ = IX.search(T, k=200)
    (i, e, o), = distinct(top, rmse, rot, 1)
    lim = np.percentile(np.abs(P[0][MASK] - P[0][MASK].mean()), 98)
    fig = plt.figure(figsize=(12, 3.6))
    gs = fig.add_gridspec(2, 9, width_ratios=[1.6, 0.25, 1, 1, 1, 1, 0.25, 1.15, 1.15], hspace=0.55, wspace=0.12)

    ax = fig.add_subplot(gs[:, 0])
    d = disk(ax, P[0], lim, ring=MARS, label="Target disk", sub="5.16 km², 137 px of 200 m")
    ax.set_title("a  One cell's shape", loc="left")
    for k, a in enumerate([0, 45, 90, 135, 180, 225, 270, 315]):
        axr = fig.add_subplot(gs[k // 4, 2 + k % 4])
        disk(axr, P[list(ANGLES).index(a)], lim, ring=MARS if list(ANGLES).index(a) == o else None)
        axr.set_title(f"{a}°", fontsize=7.5, color=MARS if list(ANGLES).index(a) == o else MUTED, loc="center", pad=2)
        if k == 0:
            axr.text(-HALF - 1, HALF + 5.5, "b  Turned every 15° (8 of 24 shown)", fontsize=10, weight="medium")
    axt = fig.add_subplot(gs[:, 7])
    disk(axt, P[o], lim, ring=MARS, label=f"{name}", sub=f"turned {int(ANGLES[o])}°")
    axt.set_title("c  Best fit", loc="left")
    axe = fig.add_subplot(gs[:, 8])
    disk(axe, api.PATCHES[i], lim, ring=EARTH, label="Nevada cell", sub=f"RMSE {e:.1f} m of {np.sqrt((T[0]**2).sum()/NPIX):.1f} m relief")
    save(fig, "02_descriptor.png")
    NUM["descriptor"] = {"target": name, "rmse_m": round(float(e), 2), "rotation": int(ANGLES[o]), "cell": str(api.CELLS[i])}


# =====================================================================================
# 3. Matches: targets against their best Nevada cells
# =====================================================================================
def fig_matches():
    rows = ["Shackleton rim", "Hadley Rille (Apollo 15)", "Jezero delta"]
    fig = plt.figure(figsize=(12, 7.6))
    gs = fig.add_gridspec(len(rows), 6, width_ratios=[1, 0.18, 1, 1, 1, 2.1], hspace=0.6, wspace=0.12)
    NUM["matches"] = {}
    for r, name in enumerate(rows):
        body, color = next((b, c) for n, b, _, _, c in TARGETS if n == name)
        T, P = TV[name]
        t_std = float(np.sqrt((T[0] ** 2).sum() / NPIX))
        all_r, _ = IX.exact(T)
        top, rmse, rot, _ = IX.search(T, k=400)
        best = distinct(top, rmse, rot, 3)
        lim = max(4.0, np.percentile(np.abs(P[0][MASK] - P[0][MASK].mean()), 98))
        disk(fig.add_subplot(gs[r, 0]), P[best[0][2]], lim, ring=color, label=name, sub=f"{body.capitalize()} · relief {t_std:.0f} m")
        for k, (i, e, o) in enumerate(best):
            disk(fig.add_subplot(gs[r, 2 + k]), api.PATCHES[i], lim, ring=EARTH if k == 0 else None,
                 label=f"#{k + 1} · {e:.1f} m", sub=f"{api.LAT[i]:.2f}°, {api.LON[i]:.2f}°")
        ax = fig.add_subplot(gs[r, 5])
        bins = np.linspace(0, np.percentile(all_r, 99), 60)
        ax.hist(all_r, bins=bins, color="#d9dbe0", edgecolor="white", lw=0.3)
        ax.axvline(best[0][1], color=color, lw=1.4)
        ax.axvline(np.median(all_r), color=MUTED, lw=0.8, ls=(0, (2, 2)))
        ax.text(best[0][1], ax.get_ylim()[1] * 0.92, f" best {best[0][1]:.1f} m", color=color, fontsize=7.5, va="top")
        ax.text(np.median(all_r), ax.get_ylim()[1] * 0.75, f" median {np.median(all_r):.0f} m", color=MUTED, fontsize=7.5, va="top")
        ax.set_yticks([])
        ax.spines["left"].set_visible(False)
        ax.set_xlabel("RMSE to every Nevada cell (m)" if r == len(rows) - 1 else "")
        if r == 0:
            ax.set_title("Where the best match sits among all 52,852", loc="left")
        NUM["matches"][name] = {"relief_m": round(t_std, 1), "best_m": [round(float(e), 2) for _, e, _ in best],
                                "median_m": round(float(np.median(all_r)), 1), "pct_below_best2x": round(float((all_r < 2 * best[0][1]).mean() * 100), 2)}
    fig.text(0.125, 0.94, "Target (turned to fit #1)", fontsize=10, weight="medium")
    fig.text(0.31, 0.94, "Best distinct Nevada cells (≥ 25 km apart), same height scale", fontsize=10, weight="medium")
    save(fig, "03_matches.png")


# =====================================================================================
# 4. Recovery: does the search find a cell that is already known to match?
# =====================================================================================
def fig_recovery():
    from prepare import DEM, Mosaic
    rng = np.random.default_rng(7)
    m = Mosaic(DEM)
    picks = rng.choice(N, 300, replace=False)
    ranks, fit = [], []
    for i in picks:
        q = m.raster(api.LAT[i], api.LON[i], 20, angle=rng.uniform(0, 360)) + rng.normal(0, 2.0, (41, 41))
        T, _ = target_variants(q, 20, 20)
        top, rm, _, _ = IX.search(T, k=10)
        true = IX.exact(T, np.array([i]))[0][0]
        ranks.append(int(np.flatnonzero(top == i)[0]) + 1 if i in top else 99)
        fit.append(rm[0] <= true + 1e-6)
    ranks, rel = np.array(ranks), IX.std[picks]
    edges = [0, 3, 10, 30, 1e9]
    labels = ["< 3 m", "3–10 m", "10–30 m", "> 30 m"]
    fig, (a, b) = plt.subplots(1, 2, figsize=(10.5, 3.4), gridspec_kw={"width_ratios": [1.35, 1], "wspace": 0.35})
    t1, t10, ns = [], [], []
    for lo, hi in zip(edges[:-1], edges[1:]):
        s = (rel >= lo) & (rel < hi)
        t1.append(100 * np.mean(ranks[s] == 1)), t10.append(100 * np.mean(ranks[s] <= 10)), ns.append(int(s.sum()))
    x = np.arange(4)
    a.bar(x, t10, 0.62, color="#e4e6ea", label="in top 10")
    a.bar(x, t1, 0.62, color=EARTH, label="ranked #1")
    for k in range(4):
        a.text(k, t1[k] + 2, f"{t1[k]:.0f}%", ha="center", fontsize=8.5, color=INK)
    a.set_xticks(x, [f"{l}\nn = {n}" for l, n in zip(labels, ns)]), a.set_ylim(0, 108), a.set_ylabel("share of queries (%)")
    a.set_xlabel("relief of the cell (std of height)")
    a.set_title("a  A rotated, noisy copy finds its original", loc="left")
    a.legend(loc="upper left", fontsize=8)
    b.axis("off")
    b.set_title("b  Setup", loc="left")
    txt = [("300", "random Nevada cells used as queries"), ("random", "rotation, 0–360°"), ("± 2 m", "Gaussian height noise added"),
           (f"{np.mean(ranks == 1):.0%}", "ranked #1 among 52,852"), (f"{np.mean(fit):.0%}", "best result fits at least as well\nas the true cell")]
    for k, (big, small) in enumerate(txt):
        y = 0.9 - k * 0.2
        b.text(0, y, big, fontsize=13, weight="medium", color=EARTH if k >= 3 else INK, va="center", transform=b.transAxes)
        b.text(0.33, y, small, fontsize=8.5, color=MUTED, va="center", transform=b.transAxes)
    save(fig, "04_recovery.png")
    NUM["recovery"] = {"top1": round(float(np.mean(ranks == 1)), 3), "top10": round(float(np.mean(ranks <= 10)), 3),
                       "fits_as_well": round(float(np.mean(fit)), 3), "by_relief_top1": [round(v, 1) for v in t1], "n": ns}


# =====================================================================================
# 5. Lossless pruning
# =====================================================================================
def fig_pruning():
    name = "Jezero delta"
    T, _ = TV[name]
    exact, _ = IX.exact(T)
    ts = np.sqrt((T ** 2).sum(1) / NPIX)
    lb = np.maximum(0, np.maximum(ts.min() - IX.std, IX.std - ts.max()))
    k = 50
    kth = np.sort(exact)[k - 1]
    fig, (a, b, c) = plt.subplots(1, 3, figsize=(12.5, 3.7), gridspec_kw={"width_ratios": [1.25, 1.2, 0.9], "wspace": 0.4})
    sel = np.random.default_rng(0).choice(N, 12000, replace=False)
    skip = lb[sel] > kth
    a.scatter(lb[sel][~skip], exact[sel][~skip], s=2, color=EARTH, alpha=0.45, lw=0, rasterized=True)
    a.scatter(lb[sel][skip], exact[sel][skip], s=2, color="#c9ccd2", alpha=0.45, lw=0, rasterized=True)
    hi = np.percentile(exact, 99.5)
    a.plot([0, hi], [0, hi], color=INK, lw=0.8)
    a.axvline(kth, color=AMBER, lw=1.1)
    a.text(hi * 0.62, hi * 0.5, "bound = RMSE", rotation=38, fontsize=7.5, color=INK)
    a.text(kth, hi * 0.97, f"  50th-best RMSE {kth:.1f} m:\n  everything right of here\n  can't make the top 50", fontsize=7.5, color=AMBER, va="top")
    a.set_xlim(0, hi), a.set_ylim(0, hi)
    a.set_xlabel("lower bound |σ target − σ cell| (m)"), a.set_ylabel("exact RMSE (m)")
    a.set_title(f"a  The bound never exceeds the RMSE ({name})", loc="left")
    NUM["bound_violations"] = int((lb > exact + 1e-9).sum())

    names, frac, same, t_pr, t_bf = [], [], [], [], []
    for nm, *_ in TARGETS:
        T, _ = TV[nm]
        t = time.perf_counter(); top, rm, _, done = IX.search(T, k=k); t_pr.append(1000 * (time.perf_counter() - t))
        t = time.perf_counter(); bt, br, _, _ = IX.search(T, k=k, prune=False); t_bf.append(1000 * (time.perf_counter() - t))
        names.append(nm), frac.append(100 * done / N), same.append(bool(np.allclose(np.sort(rm), np.sort(br)) and set(top) == set(bt)))
    o = np.argsort(frac)
    colors = [next(c for n, *_, c in TARGETS if n == names[j]) for j in o]
    b.barh(np.arange(len(o)), [100] * len(o), color="#eef0f2", height=0.62)
    b.barh(np.arange(len(o)), [frac[j] for j in o], color=colors, height=0.62)
    for y, j in enumerate(o):
        b.text(frac[j] + 1.5, y, f"{frac[j]:.0f}%", va="center", fontsize=8)
    b.set_yticks(np.arange(len(o)), [names[j] for j in o], fontsize=8)
    b.set_xlim(0, 100), b.set_xlabel("cells needing an exact comparison (%)\nblocks of 4,096 cells, so 7.7% is the floor")
    b.set_title("b  Work done, top 50 (identical to brute force)", loc="left")

    c.bar([0, 1], [np.median(t_bf), np.median(t_pr)], color=["#c9ccd2", EARTH], width=0.6)
    for x, v in zip([0, 1], [np.median(t_bf), np.median(t_pr)]):
        c.text(x, v * 1.03, f"{v:.0f} ms", ha="center", fontsize=8.5)
    c.set_xticks([0, 1], ["brute force", "pruned"]), c.set_ylabel("median search time (ms)")
    c.set_title("c  52,852 cells × 24 rotations", loc="left")
    save(fig, "05_pruning.png")
    NUM["pruning"] = {"work_pct": dict(zip(names, [round(f, 1) for f in frac])), "identical": all(same),
                      "ms_pruned_median": round(float(np.median(t_pr)), 1), "ms_brute_median": round(float(np.median(t_bf)), 1)}


# =====================================================================================
# 6. Speed: what a query costs
# =====================================================================================
def fig_latency():
    # A fresh point so nothing is cached, end to end as the app runs it
    from compare import compare
    api.target.cache_clear()
    t0 = time.time(); T, P = api.target("mars", 18.51, 77.31); t_dem = time.time() - t0
    t0 = time.time(); top, rm, rot, _ = IX.search(T, k=50); t_search = time.time() - t0
    i = int(top[0])
    cell = str(api.CELLS[i])
    for f in api.IMG.glob(f"{cell}*"):
        f.unlink()
    t0 = time.time(); api.ensure_imagery(cell, float(api.LAT[i]), float(api.LON[i])); t_img = time.time() - t0
    rel = float(np.sqrt((T[0] ** 2).sum() / NPIX))
    site = {"id": f"cell-{cell}-paper", "lat": float(api.LAT[i]), "lon": float(api.LON[i]), "targetLat": 18.51, "targetLon": 77.31,
            "metrics": {k: float(v[i]) for k, v in api.FIELD.items()}, "soil": api.soil_info(i),
            "shape": {"rmseM": round(float(rm[0]), 2), "rotationDeg": int(ANGLES[rot[0]]), "score": float(np.exp(-(rm[0] / rel) ** 2)),
                      "reliefM": float(IX.std[i]), "targetReliefM": rel}}
    t0 = time.time()
    try:
        compare("mars", "Jezero crater", api.target_metrics("mars", 18.51, 77.31), site)
        t_llm = time.time() - t0
    except Exception as e:
        print("llm failed", e)
        t_llm = 6.0
    NUM["latency_s"] = {"dem": round(t_dem, 2), "search": round(t_search, 3), "imagery": round(t_img, 2), "llm": round(t_llm, 2)}

    fig, (a, b) = plt.subplots(1, 2, figsize=(12.5, 3.1), gridspec_kw={"width_ratios": [0.85, 1.6], "wspace": 0.42})
    a.barh([1, 0], [60, t_dem], color=["#c9ccd2", EARTH], height=0.55)
    a.errorbar([60], [1], xerr=[[20], [20]], color=MUTED, capsize=3, lw=0.8)
    a.text(82, 1, "  40–80 s", va="center", fontsize=8.5, color=MUTED)
    a.text(t_dem, 0, f"  {t_dem:.1f} s", va="center", fontsize=8.5, color=EARTH)
    a.set_yticks([1, 0], ["GDAL windowed read\n(/vsicurl)", "Parallel ranged reads,\nneeded columns only"])
    a.set_xlabel("time to read one target's terrain (s)"), a.set_xlim(0, 105)
    a.set_title("a  One point from an 8.5–11.4 GB global DEM", loc="left")

    resp = t_dem + t_search + 0.1
    dive0 = resp + t_img
    steps = [("Target terrain, USGS ranged read", 0, t_dem, MARS),
             ("Filter + shape search", t_dem, max(t_search, 0.04), EARTH),
             ("Imagery for the top site (Sentinel-2)", resp, t_img, "#8a93a3"),
             ("Dive animation", dive0, 2.4, "#c9ccd2"),
             ("LLM reasoning, prefetched for the top 3", resp, t_llm, AMBER)]
    for y, (lab, s0, d, col) in enumerate(steps[::-1]):
        if col == AMBER:  # observed range, not one run
            b.barh(y, 3, left=s0, color=col, height=0.55)
            b.barh(y, 22, left=s0 + 3, color=col, alpha=0.25, height=0.55)
            b.text(s0 + 25.2, y, lab + " (3–25 s observed)", va="center", fontsize=8)
            continue
        b.barh(y, d, left=s0, color=col, height=0.55)
        b.text(s0 + d + 0.35, y, lab, va="center", fontsize=8)
    b.axvline(dive0 + 1.55, color=INK, lw=0.7, ls=(0, (2, 2)))
    b.text(dive0 + 1.65, -0.75, "evidence panel appears", fontsize=7.5, color=INK, va="center")
    b.set_yticks([]), b.spines["left"].set_visible(False)
    b.set_xlabel("seconds after clicking Find (one uncached run)")
    b.set_xlim(0, resp + 40)
    b.set_title("b  The slow steps overlap the transition", loc="left")
    save(fig, "06_latency.png")


# =====================================================================================
# 7. What each cell carries
# =====================================================================================
def fig_layers():
    keys = [("slope", "Mean slope (°)", "viridis"), ("relief", "Relief, std of height (m)", "magma"), ("meanTemp", "Mean air temperature (°C)", "coolwarm")]
    fig, axes = plt.subplots(1, 4, figsize=(12.5, 4.0), gridspec_kw={"wspace": 0.08})
    for ax, (k, lab, cm) in zip(axes, keys):
        v = api.FIELD[k]
        lo, hi = np.percentile(v, [2, 98])
        sc = ax.scatter(api.LON, api.LAT, c=v, s=0.6, cmap=cm, vmin=lo, vmax=hi, lw=0, rasterized=True)
        ax.set_aspect(1 / np.cos(np.radians(39))), ax.axis("off")
        ax.set_title(lab, loc="left", fontsize=9)
        cb = fig.colorbar(sc, ax=ax, orientation="horizontal", fraction=0.04, pad=0.02, aspect=30)
        cb.outline.set_visible(False), cb.ax.tick_params(labelsize=7, colors=MUTED)
    mats = ["soil", "carbonate", "evaporite", "sodic", "regolith", "sulfate", "rock"]
    pal = ["#d9dbe0", "#e0a458", "#5b8fb9", "#9b7fb6", "#7aa37a", "#c8643b", INK]
    lab = {"soil": "Other soils", "carbonate": "Carbonate", "evaporite": "Saline", "sodic": "Sodic clay", "regolith": "Little weathered", "sulfate": "Gypsum", "rock": "Thin over rock"}
    idx = np.array([mats.index(m) if m in mats else 0 for m in api.MAT])
    ax = axes[3]
    ax.scatter(api.LON, api.LAT, c=idx, s=0.6, cmap=ListedColormap(pal), vmin=-0.5, vmax=len(mats) - 0.5, lw=0, rasterized=True)
    ax.set_aspect(1 / np.cos(np.radians(39))), ax.axis("off")
    ax.set_title("Surface material (WRB 2006)", loc="left", fontsize=9)
    counts = {m: int((api.MAT == m).sum()) for m in mats}
    for j, m in enumerate(mats):
        ax.scatter([], [], s=18, color=pal[j], label=f"{lab[m]}  {counts[m]:,}")
    ax.legend(loc="lower left", bbox_to_anchor=(0.0, -0.32), fontsize=7, ncol=2, handletextpad=0.2, columnspacing=0.8)
    save(fig, "07_layers.png")
    NUM["materials"] = counts


# =====================================================================================
# 8. From RMSE to a score, and how a "match ≥ x%" limit becomes an RMSE cap
# =====================================================================================
def fig_score():
    name = "Jezero delta"
    T, _ = TV[name]
    s = float(np.sqrt((T[0] ** 2).sum() / NPIX))
    r, _ = IX.exact(T)
    fig, (a, b) = plt.subplots(1, 2, figsize=(10.5, 3.2), gridspec_kw={"wspace": 0.35})
    x = np.linspace(0, 2.2, 300)
    a.plot(x, 100 * np.exp(-x ** 2), color=INK, lw=1.4)
    for m, col in [(0.9, EARTH), (0.5, AMBER)]:
        cap = np.sqrt(-np.log(m))
        a.plot([cap, cap, 0], [0, 100 * m, 100 * m], color=col, lw=0.9, ls=(0, (2, 2)))
        a.text(cap + 0.04, 100 * m + 3, f"match ≥ {m:.0%} ⇔ RMSE ≤ {cap:.2f} σ", color=col, fontsize=8)
    a.set_xlabel("RMSE / target relief σ"), a.set_ylabel("score (%)"), a.set_ylim(0, 105), a.set_xlim(0, 2.2)
    a.set_title("a  score = exp(−(RMSE/σ)²)", loc="left")
    sc = 100 * np.exp(-(r / s) ** 2)
    b.hist(sc, bins=np.linspace(0, 100, 51), color="#d9dbe0", edgecolor="white", lw=0.3)
    for m, col in [(90, EARTH), (50, AMBER)]:
        n = int((sc >= m).sum())
        b.axvline(m, color=col, lw=1)
        b.text(m - 1, b.get_ylim()[1] * 0.9, f"{n:,} cell{'s' if n != 1 else ''} ≥ {m}%  ", color=col, fontsize=8, ha="right")
    b.set_yticks([]), b.spines["left"].set_visible(False)
    b.set_xlabel(f"score of every Nevada cell against {name} (σ = {s:.1f} m)")
    b.set_title("b  Most of Nevada is a poor shape match", loc="left")
    save(fig, "08_score.png")
    NUM["score"] = {"sigma": round(s, 1), "n_ge_90": int((sc >= 90).sum()), "n_ge_50": int((sc >= 50).sum())}


fig_pipeline()
fig_descriptor()
fig_matches()
fig_recovery()
fig_pruning()
fig_latency()
fig_layers()
fig_score()
(OUT / "numbers.json").write_text(json.dumps(NUM, indent=1))
print(json.dumps(NUM, indent=1))
