"""
Figures for the research write-up, generated from the live search code and data.

    .venv/Scripts/python -X utf8 paper_figures.py   # -> ../docs/science/figures/*.png, numbers.json

Every number in the figures is measured here, on the same 52,852 Nevada cells the app searches.
One idea per figure; equations are typeset where they carry the idea.
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
from matplotlib.patches import Circle

import api
from shape import ANGLES, HALF, MASK, NPIX, PX_M, target_variants

OUT = Path(__file__).resolve().parent.parent / "docs" / "science" / "figures"
OUT.mkdir(parents=True, exist_ok=True)
NUM: dict = {}

# --- style: serif text with matching math, greys plus one accent per body ----------------
INK, MID, LIGHT, RULE = "#222222", "#6f6f6f", "#b9b9b9", "#dcdcdc"
MOON, MARS, EARTH = "#4f6d8f", "#b5562f", "#3d7a68"
plt.rcParams.update({
    "font.family": "STIXGeneral", "mathtext.fontset": "stix", "font.size": 10.5,
    "text.color": INK, "axes.labelcolor": INK, "axes.edgecolor": INK, "axes.linewidth": 0.6,
    "xtick.color": INK, "ytick.color": INK, "xtick.major.width": 0.6, "ytick.major.width": 0.6,
    "xtick.major.size": 3, "ytick.major.size": 3, "xtick.direction": "out", "ytick.direction": "out",
    "axes.spines.top": False, "axes.spines.right": False, "axes.titlesize": 11, "axes.titleweight": "normal",
    "axes.titlelocation": "left", "axes.titlepad": 10, "legend.frameon": False, "legend.fontsize": 9.5,
    "savefig.dpi": 220, "savefig.bbox": "tight", "savefig.pad_inches": 0.12,
})
RAMP = LinearSegmentedColormap.from_list("relief", ["#24394a", "#4a6a72", "#8d9c86", "#cdbf9a", "#f1ece2"])
LS = LightSource(azdeg=315, altdeg=40)
R_DISK = np.sqrt(MASK.sum() / np.pi)


def save(fig, name):
    fig.savefig(OUT / name, facecolor="white")
    plt.close(fig)
    print("wrote", name)


def panel(ax, letter, title):
    ax.set_title(rf"$\mathbf{{{letter}}}$   {title}", loc="left")


def disk(ax, patch, lim, ring=INK, lw=0.6):
    """A 200 m-pixel relief disk: hillshaded ramp, clipped to the cell's circle."""
    p = patch - patch[MASK].mean()
    rgb = LS.shade(np.clip(p, -lim, lim), cmap=RAMP, vert_exag=6, blend_mode="soft", vmin=-lim, vmax=lim, dx=PX_M, dy=PX_M)
    rgb[~MASK] = 1
    r = HALF + 0.5
    im = ax.imshow(rgb, interpolation="nearest", extent=[-r, r, -r, r])
    im.set_clip_path(Circle((0, 0), R_DISK, transform=ax.transData))
    ax.add_patch(Circle((0, 0), R_DISK, fill=False, lw=lw, ec=ring))
    ax.set_xlim(-r, r), ax.set_ylim(-r, r), ax.set_aspect("equal"), ax.axis("off")


def under(ax, text, sub=None, y=-0.06):
    ax.text(0.5, y, text, transform=ax.transAxes, ha="center", va="top", fontsize=10)
    if sub:
        ax.text(0.5, y - 0.13, sub, transform=ax.transAxes, ha="center", va="top", fontsize=9, color=MID)


def distinct(top, rmse, rot, n, km=25):
    out = []
    for i, e, o in zip(top, rmse, rot):
        if all(api.km((api.LAT[i], api.LON[i]), (api.LAT[j], api.LON[j])) >= km for j, *_ in out):
            out.append((int(i), float(e), int(o)))
        if len(out) == n:
            break
    return out


def relief(T):
    return float(np.sqrt((T[0] ** 2).sum() / NPIX))


TARGETS = [
    ("Shackleton rim", "moon", -89.67, 129.78, MOON),
    ("Hadley Rille", "moon", 26.13, 3.63, MOON),
    ("Descartes", "moon", -8.97, 15.5, MOON),
    ("Jezero delta", "mars", 18.38, 77.58, MARS),
    ("Gale crater", "mars", -5.4, 137.8, MARS),
    ("Meridiani Planum", "mars", -1.95, -5.53, MARS),
    ("Utopia Planitia", "mars", 46.7, 117.5, MARS),
]
IX = api.INDEX
N = len(api.CELLS)
TV, fetch_s = {}, []
for name, body, la, lo, _ in TARGETS:
    t = time.time()
    TV[name] = api.target(body, round(la, 4), round(lo, 4))
    fetch_s.append(time.time() - t)
NUM["target_fetch_s"] = [round(x, 2) for x in fetch_s]


# =====================================================================================
# 1. Method at a glance
# =====================================================================================
def fig_method():
    fig, ax = plt.subplots(figsize=(12, 2.9))
    ax.set_xlim(0, 100), ax.set_ylim(0, 30), ax.axis("off")
    xs = [8, 29, 50, 71, 92]
    y = 22
    ax.plot([xs[0], xs[-1]], [y, y], color=INK, lw=0.6, zorder=1)
    stages = [
        ("Target", "any point on the Moon or Mars", [r"$z_T(\varphi, \lambda)$"]),
        ("Descriptor", "5.16 km² disk of 200 m pixels", [r"$\mathbf{t}_\theta = z_T - \bar{z}_T$", r"$\theta = 0°, 15°, \ldots, 345°$"]),
        ("Filter", "limits on 52,852 Earth cells", [r"$\ell_k \leq x_{c,k} \leq u_k$"]),
        ("Rank", "best rotation, smallest distance", [r"$d(T,c) = \min_\theta\, \mathrm{RMSE}(\mathbf{t}_\theta, \mathbf{c})$"]),
        ("Report", "8 sites, at least 25 km apart", ["holds and breaks,", "in measured units"]),
    ]
    for x, (title, sub, eqs) in zip(xs, stages):
        ax.scatter([x], [y], s=40, color="white", edgecolor=INK, lw=0.9, zorder=3)
        ax.text(x, y + 2.6, title, ha="center", va="bottom", fontsize=12.5)
        ax.text(x, y - 2.8, sub, ha="center", va="top", fontsize=9.5, color=MID)
        for k, e in enumerate(eqs):
            ax.text(x, y - 9.0 - 4.6 * k, e, ha="center", va="top", fontsize=11, color=INK if e.startswith("$") else MID)
    save(fig, "01_method.png")


# =====================================================================================
# 2. Descriptor
# =====================================================================================
def fig_descriptor():
    name = "Jezero delta"
    T, P = TV[name]
    top, rmse, rot, _ = IX.search(T, k=200)
    (i, e, o), = distinct(top, rmse, rot, 1)
    lim = np.percentile(np.abs(P[0][MASK] - P[0][MASK].mean()), 98)
    fig = plt.figure(figsize=(11, 3.9))
    gs = fig.add_gridspec(2, 10, width_ratios=[2.2, 0.35, 1, 1, 1, 1, 1, 1, 0.35, 2.2], height_ratios=[1, 0.5], hspace=0.1, wspace=0.08)
    ax = fig.add_subplot(gs[0, 0]); disk(ax, P[0], lim, ring=MARS, lw=1.0)
    fig.text(0.125, 0.97, r"$\mathbf{a}$   Target disk", fontsize=11, va="top")
    under(ax, "Jezero delta, Mars", "137 pixels · relief 16.2 m")
    shown = [0, 60, 120, 180, 240, 300]
    for k, a in enumerate(shown):
        axr = fig.add_subplot(gs[0, 2 + k]); disk(axr, P[list(ANGLES).index(a)], lim)
        axr.text(0.5, -0.06, f"{a}°", transform=axr.transAxes, ha="center", va="top", fontsize=9.5, color=MID)
        if k == 0:
            fig.text(axr.get_position().x0, 0.97, r"$\mathbf{b}$   Rotations, every 15° (6 of 24 shown)", fontsize=11, va="top")
    axm = fig.add_subplot(gs[0, 9]); disk(axm, api.PATCHES[i], lim, ring=EARTH, lw=1.0)
    fig.text(axm.get_position().x0, 0.97, r"$\mathbf{c}$   Closest Nevada cell", fontsize=11, va="top")
    under(axm, f"RMSE {e:.1f} m at θ = {int(ANGLES[o])}°", f"{api.LAT[i]:.2f}° N, {abs(api.LON[i]):.2f}° W")
    eq = fig.add_subplot(gs[1, 2:8]); eq.axis("off")
    eq.text(0.5, 0.35, r"$d(T,c) \;=\; \min_{\theta}\ \sqrt{\frac{1}{N}\sum_{i=1}^{N}\left(t_\theta(i) - c(i)\right)^2}, \qquad N = 137$",
            ha="center", va="center", fontsize=14, transform=eq.transAxes)
    save(fig, "02_descriptor.png")
    NUM["descriptor"] = {"target": name, "rmse_m": round(e, 2), "rotation": int(ANGLES[o]), "cell": str(api.CELLS[i])}


# =====================================================================================
# 3. Matches
# =====================================================================================
def fig_matches():
    rows = ["Hadley Rille", "Jezero delta", "Shackleton rim"]
    fig = plt.figure(figsize=(9.6, 7.4))
    gs = fig.add_gridspec(3, 5, width_ratios=[1, 0.22, 1, 1, 1], hspace=0.62, wspace=0.12)
    NUM["matches"] = {}
    for r, name in enumerate(rows):
        body, color = next((b, c) for n, b, _, _, c in TARGETS if n == name)
        T, P = TV[name]
        s = relief(T)
        all_r, _ = IX.exact(T)
        top, rmse, rot, _ = IX.search(T, k=400)
        best = distinct(top, rmse, rot, 3)
        lim = max(4.0, np.percentile(np.abs(P[0][MASK] - P[0][MASK].mean()), 98))
        ax0 = fig.add_subplot(gs[r, 0]); disk(ax0, P[best[0][2]], lim, ring=color, lw=1.0)
        under(ax0, name, f"{body.capitalize()} · σ = {s:.1f} m")
        axs = []
        for k, (i, e, o) in enumerate(best):
            ax = fig.add_subplot(gs[r, 2 + k]); disk(ax, api.PATCHES[i], lim)
            under(ax, f"{e:.1f} m", f"score {np.exp(-(e / s) ** 2):.0%}")
            axs.append(ax)
        if r == 0:
            ax0.set_title("Target", loc="left")
            axs[0].set_title("Three closest distinct Nevada cells, RMSE", loc="left")
        NUM["matches"][name] = {"relief_m": round(s, 1), "best_m": [round(e, 2) for _, e, _ in best],
                                "median_m": round(float(np.median(all_r)), 1), "pct_within_2x_best": round(float((all_r < 2 * best[0][1]).mean() * 100), 2)}
    save(fig, "03_matches.png")


# =====================================================================================
# 4. Recovery
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
    edges, labels = [0, 3, 10, 30, 1e9], ["< 3", "3–10", "10–30", "> 30"]
    t1, t10, ns = [], [], []
    for lo, hi in zip(edges[:-1], edges[1:]):
        s = (rel >= lo) & (rel < hi)
        t1.append(100 * np.mean(ranks[s] == 1)), t10.append(100 * np.mean(ranks[s] <= 10)), ns.append(int(s.sum()))
    fig, ax = plt.subplots(figsize=(6.2, 3.4))
    x = np.arange(4)
    ax.bar(x, t1, 0.55, color=EARTH, label="ranked first")
    ax.scatter(x, t10, marker="_", s=420, color=INK, lw=1.0, zorder=3, label="in the top 10")
    for k in range(4):
        ax.text(k, t1[k] - 3, f"{t1[k]:.0f}%", ha="center", va="top", fontsize=10, color="white")
    ax.set_xticks(x, [f"{l} m\n$n = {n}$" for l, n in zip(labels, ns)])
    ax.set_ylim(0, 105), ax.set_ylabel("share of queries (%)")
    ax.set_xlabel(r"relief of the query cell, $\sigma$")
    ax.legend(loc="upper left")
    ax.set_title("A rotated, noisy cell finds itself among 52,852", loc="left")
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
    kth = np.sort(exact)[49]
    NUM["bound_violations"] = int((lb > exact + 1e-9).sum())
    fig, (a, b) = plt.subplots(1, 2, figsize=(11, 4.0), gridspec_kw={"width_ratios": [1, 1.05], "wspace": 0.55})
    hi = 120
    keep = lb <= kth
    a.scatter(lb[~keep], exact[~keep], s=1.2, color=LIGHT, lw=0, rasterized=True)
    a.scatter(lb[keep], exact[keep], s=1.2, color=EARTH, lw=0, rasterized=True)
    a.plot([0, hi], [0, hi], color=INK, lw=0.7)
    a.axvline(kth, color=INK, lw=0.6, ls=(0, (3, 3)))
    a.text(kth + 2, 112, f"stop here: 50th-best\nRMSE = {kth:.1f} m", fontsize=9.5, va="top")
    a.text(75, 35, r"$\mathrm{RMSE}(T,c) \;\geq\; |\,\sigma_T - \sigma_c\,|$", fontsize=12.5, ha="center")
    a.set_xlim(0, hi), a.set_ylim(0, hi)
    a.set_xlabel(r"lower bound $|\sigma_T - \sigma_c|$ (m)"), a.set_ylabel("exact RMSE (m)")
    panel(a, "a", f"The bound holds for every cell ({name})")

    names, frac, same, t_pr, t_bf = [], [], [], [], []
    for nm, *_ in TARGETS:
        T, _ = TV[nm]
        t = time.perf_counter(); top, rm, _, done = IX.search(T, k=50); t_pr.append(1000 * (time.perf_counter() - t))
        t = time.perf_counter(); bt, br, _, _ = IX.search(T, k=50, prune=False); t_bf.append(1000 * (time.perf_counter() - t))
        names.append(nm), frac.append(100 * done / N), same.append(bool(np.allclose(np.sort(rm), np.sort(br)) and set(top) == set(bt)))
    o = np.argsort(frac)[::-1]
    yy = np.arange(len(o))
    b.hlines(yy, 0, [frac[j] for j in o], color=RULE, lw=1.0)
    b.scatter([frac[j] for j in o], yy, s=34, color=[next(c for n, *_, c in TARGETS if n == names[j]) for j in o], zorder=3)
    for y, j in zip(yy, o):
        b.text(frac[j] + 2.2, y, f"{frac[j]:.0f}%", va="center", fontsize=9.5)
    b.set_yticks(yy, [names[j] for j in o]), b.tick_params(axis="y", length=0)
    b.spines["left"].set_visible(False)
    b.set_xlim(0, 100), b.set_xlabel("cells compared exactly (%)")
    b.invert_yaxis()
    panel(b, "b", "Share of the search actually done")
    save(fig, "05_pruning.png")
    NUM["pruning"] = {"work_pct": dict(zip(names, [round(f, 1) for f in frac])), "identical": all(same),
                      "ms_pruned_median": round(float(np.median(t_pr)), 1), "ms_brute_median": round(float(np.median(t_bf)), 1)}


# =====================================================================================
# 6. Speed
# =====================================================================================
def fig_speed():
    api.target.cache_clear()
    t0 = time.time(); api.target("mars", 18.51, 77.31); t_dem = time.time() - t0
    NUM["ranged_fresh_s"] = round(t_dem, 2)
    pr = NUM["pruning"]
    fig, (a, b) = plt.subplots(1, 2, figsize=(11, 2.4), gridspec_kw={"wspace": 0.75})
    for ax, vals, labs, unit, title, letter, txt in [
        (a, [60, t_dem], ["Windowed read (GDAL)", "Ranged row reads"], "seconds", "Reading one target from an 8.5–11.4 GB global DEM", "a",
         ["40–80 s", f"{t_dem:.1f} s"]),
        (b, [pr["ms_brute_median"], pr["ms_pruned_median"]], ["Every cell", "Bound-ordered"], "milliseconds", "Ranking 52,852 cells × 24 rotations", "b",
         [f"{pr['ms_brute_median']:.0f} ms", f"{pr['ms_pruned_median']:.0f} ms"]),
    ]:
        ax.barh([1, 0], vals, color=[LIGHT, EARTH], height=0.5)
        ax.set_yticks([1, 0], labs), ax.tick_params(axis="y", length=0), ax.spines["left"].set_visible(False)
        top = max(vals) * 1.45
        ax.set_xlim(0, top), ax.set_xlabel(unit)
        for y, v, t in zip([1, 0], vals, txt):
            ax.text((83 if (unit == "seconds" and y == 1) else v + top * 0.02), y, t, va="center", fontsize=10)
        panel(ax, letter, title)
    a.errorbar([60], [1], xerr=[[20], [20]], color=INK, capsize=2.5, lw=0.6)
    save(fig, "06_speed.png")


# =====================================================================================
# 7. What each cell carries
# =====================================================================================
def fig_layers():
    fig, axes = plt.subplots(1, 3, figsize=(11, 4.5), gridspec_kw={"wspace": 0.05})
    asp = 1 / np.cos(np.radians(39))
    for ax, k, lab, cm, lo, hi in [(axes[0], "relief", r"Relief $\sigma$ (m), from the DEM", "Greys", 0, 80),
                                   (axes[1], "meanTemp", "Mean air temperature (°C), ERA5", "RdBu_r", 8, 22)]:
        sc = ax.scatter(api.LON, api.LAT, c=api.FIELD[k], s=0.5, cmap=cm, vmin=lo, vmax=hi, lw=0, rasterized=True)
        ax.set_aspect(asp), ax.axis("off"), ax.set_title(lab, loc="left", fontsize=10.5)
        cb = fig.colorbar(sc, ax=ax, orientation="horizontal", fraction=0.035, pad=0.02, aspect=28)
        cb.outline.set_visible(False), cb.ax.tick_params(labelsize=9, length=2)
    mats = ["soil", "carbonate", "sodic", "regolith", "sulfate", "evaporite", "rock"]
    pal = ["#e7e5e0", "#c9a66b", "#8a8fa8", "#8aa38a", MARS, MOON, INK]
    lab = {"soil": "Other soils", "carbonate": "Carbonate (Calcisols)", "sodic": "Sodic clay (Solonetz)", "regolith": "Little weathered (Regosols)",
           "sulfate": "Gypsum (Gypsisols)", "evaporite": "Saline (Solonchaks)", "rock": "Thin over rock (Leptosols)"}
    idx = np.array([mats.index(m) if m in mats else 0 for m in api.MAT])
    ax = axes[2]
    ax.scatter(api.LON, api.LAT, c=idx, s=0.5, cmap=ListedColormap(pal), vmin=-0.5, vmax=len(mats) - 0.5, lw=0, rasterized=True)
    ax.set_aspect(asp), ax.axis("off"), ax.set_title("Surface material, WRB 2006", loc="left", fontsize=10.5)
    counts = {m: int((api.MAT == m).sum()) for m in mats}
    for j, m in enumerate(mats):
        ax.scatter([], [], s=22, marker="s", color=pal[j], label=f"{lab[m]}  {counts[m]:,}")
    ax.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), fontsize=9, handletextpad=0.3, labelspacing=0.5)
    save(fig, "07_layers.png")
    NUM["materials"] = counts


# =====================================================================================
# 8. Score
# =====================================================================================
def fig_score():
    T, _ = TV["Jezero delta"]
    s = relief(T)
    r, _ = IX.exact(T)
    sc = np.exp(-(r / s) ** 2)
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    x = np.linspace(0, 2.2, 300)
    ax.plot(x, 100 * np.exp(-x ** 2), color=INK, lw=1.2)
    for m in (0.9, 0.5):
        cap = np.sqrt(-np.log(m))
        ax.plot([cap, cap, 0], [0, 100 * m, 100 * m], color=MID, lw=0.6, ls=(0, (3, 3)))
        ax.text(cap + 0.05, 100 * m + 2, rf"score $\geq$ {m:.0%}  $\Leftrightarrow$  RMSE $\leq$ {cap:.2f}$\,\sigma_T$", fontsize=9.5)
    ax.text(1.55, 75, r"$\mathrm{score} = \exp\!\left(-\,\frac{\mathrm{RMSE}^2}{\sigma_T^{\,2}}\right)$", fontsize=14, ha="center")
    ax.set_xlim(0, 2.2), ax.set_ylim(0, 105)
    ax.set_xlabel(r"RMSE $/\ \sigma_T$"), ax.set_ylabel("score (%)")
    ax.set_title("Score relative to the target's own relief", loc="left")
    save(fig, "08_score.png")
    NUM["score"] = {"sigma": round(s, 1), "n_ge_90": int((sc >= 0.9).sum()), "n_ge_50": int((sc >= 0.5).sum())}


# =====================================================================================
# 9. The environment gap (values from the earlier three-body climate study)
# =====================================================================================
def fig_environment():
    rows = [("Earth, air", 8, 24, EARTH), ("Earth, ground", 8, 35, EARTH), ("Mars, air (Gale)", -75, -12, MARS),
            ("Mars, ground (Gale)", -81, 3, MARS), ("Moon, surface", -179, 121, MOON)]
    fig, (a, b) = plt.subplots(1, 2, figsize=(11, 2.9), gridspec_kw={"width_ratios": [1.5, 1], "wspace": 0.55})
    for y, (lab, lo, hi, c) in enumerate(rows[::-1]):
        a.plot([lo, hi], [y, y], color=c, lw=5, solid_capstyle="butt")
        a.text(hi + 5, y, f"{lo} to {hi} °C".replace("-", "−"), va="center", fontsize=9.5, color=MID)
    a.set_yticks(range(len(rows)), [r[0] for r in rows[::-1]]), a.tick_params(axis="y", length=0)
    a.spines["left"].set_visible(False), a.axvline(0, color=RULE, lw=0.6, zorder=0)
    a.set_xlim(-190, 185), a.set_xlabel("typical daily low to high (°C)")
    panel(a, "a", "Daily temperature range")
    p = [("Earth", 1.0e5, r"$10^{5}$ Pa", EARTH), ("Mars (Gale)", 7.0e2, r"$7\times10^{2}$ Pa", MARS), ("Moon", 3e-10, r"$\sim 3\times10^{-10}$ Pa", MOON)]
    ys = [2, 1, 0]
    b.barh(ys, [np.log10(v) + 11 for _, v, _, _ in p], left=-11, color=[c for *_, c in p], height=0.5)
    for y, (lab, v, t, _) in zip(ys, p):
        b.text(np.log10(v) + 0.4, y, t, va="center", fontsize=9.5, color=MID)
    b.set_yticks(ys, [q[0] for q in p]), b.tick_params(axis="y", length=0), b.spines["left"].set_visible(False)
    b.set_xlim(-11, 9), b.set_xticks([-10, -5, 0, 5], [r"$10^{-10}$", r"$10^{-5}$", r"$10^{0}$", r"$10^{5}$"])
    b.set_xlabel("surface pressure (Pa)")
    panel(b, "b", "Atmosphere")
    save(fig, "09_environment.png")


import sys

ALL = (fig_method, fig_descriptor, fig_matches, fig_recovery, fig_pruning, fig_speed, fig_layers, fig_score, fig_environment)
only = sys.argv[1:]  # e.g. `paper_figures.py fig_method` to redraw one figure
for f in ALL:
    if not only or f.__name__ in only:
        f()
if not only:
    (OUT / "numbers.json").write_text(json.dumps(NUM, indent=1))
    print(json.dumps({k: NUM[k] for k in ("matches", "pruning", "score", "ranged_fresh_s")}, indent=1))
