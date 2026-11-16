"""
Proofs on Nevada that the shape search finds matching terrain.

    .venv/Scripts/python test_nevada.py     # -> figures/*.png, prints results

1. Recovery: a Nevada cell, rotated by a random angle with 2 m noise added, is
   used as the query; the search should return that cell (or one that fits as well).
2. Lossless pruning: for Moon and Mars targets the pruned search returns exactly
   the brute-force top 50.
3. Moon and Mars targets: each target patch beside its best Nevada matches, rotated
   into alignment, with the RMSE against the whole of Nevada.
"""

import os
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import tifffile

from prepare import DEM, Mosaic
from shape import ANGLES, HALF, MASK, NPIX, PX_M, Index, target_variants

ROOT = Path(__file__).parent
FIG = ROOT / "figures"
SITES = Path(os.environ.get("SITE_GRIDS", ROOT / "sites" / "raw_200m_site_grid"))
TARGETS = [  # site, source raster, label
    ("shackleton", "lola_polar20", "Shackleton rim, Moon"),
    ("apollo15", "lola118", "Apollo 15 Hadley Rille, Moon"),
    ("apollo16", "lola118", "Apollo 16 Descartes, Moon"),
    ("bagnold", "hrsc_mola200", "Bagnold dunes (Gale), Mars"),
    ("phoenix", "hrsc_mola200", "Phoenix lander, Mars"),
    ("viking1", "hrsc_mola200", "Viking 1, Mars"),
    ("viking2", "hrsc_mola200", "Viking 2, Mars"),
]
rng = np.random.default_rng(7)


def show(ax, patch, vmin, vmax, title):
    p = np.where(MASK, patch - patch[MASK].mean(), np.nan)
    ax.imshow(p, cmap="terrain", vmin=vmin, vmax=vmax, extent=[-HALF * 0.2, HALF * 0.2, -HALF * 0.2, HALF * 0.2])
    ax.set_title(title, fontsize=8)
    ax.set_xticks([])
    ax.set_yticks([])


def main():
    FIG.mkdir(exist_ok=True)
    d = np.load(ROOT / "out" / "nevada_patches.npz")
    h3s, lat, lon, patches = d["h3"], d["lat"], d["lon"], d["patches"]
    t = time.time()
    ix = Index(patches)
    print(f"index: {len(patches):,} Nevada cells, {NPIX} px per patch, built in {time.time() - t:.1f}s")

    # 1. Recovery
    m = Mosaic(DEM)
    picks = rng.choice(len(patches), 300, replace=False)
    ranks, same_fit, ex = [], [], []
    for i in picks:
        ang = rng.uniform(0, 360)
        q = m.raster(lat[i], lon[i], 20, angle=ang) + rng.normal(0, 2.0, (41, 41))
        T, P = target_variants(q, 20, 20)
        top, rm, rot, _ = ix.search(T, k=10)
        true_rmse = ix.exact(T, np.array([i]))[0][0]
        ranks.append(int(np.flatnonzero(top == i)[0]) + 1 if i in top else 99)
        same_fit.append(rm[0] <= true_rmse + 1e-6)
        if len(ex) < 4 and ix.std[i] > 15:
            ex.append((i, ang, P[rot[0]], top[0], rm[0]))
    ranks = np.array(ranks)
    rel = ix.std[picks]
    print(f"recovery: top-1 {np.mean(ranks == 1):.1%}, top-10 {np.mean(ranks <= 10):.1%}; "
          f"best match fits at least as well as the true cell in {np.mean(same_fit):.1%}")
    print(f"  cells with relief std > 10 m: top-1 {np.mean(ranks[rel > 10] == 1):.1%} (n={np.sum(rel > 10)}); "
          f"flat cells (< 3 m): top-1 {np.mean(ranks[rel < 3] == 1):.1%} (n={np.sum(rel < 3)})")

    fig, axes = plt.subplots(2, 5, figsize=(13, 5.6), gridspec_kw={"width_ratios": [1, 1, 1, 1, 1.4]})
    for k, (i, ang, qp, found, rm) in enumerate(ex):
        lim = np.nanmax(np.abs(patches[i][MASK] - patches[i][MASK].mean()))
        show(axes[0, k], qp, -lim, lim, f"query: cell rotated {ang:.0f}°\n+2 m noise")
        show(axes[1, k], patches[found], -lim, lim, f"found {'= original' if found == i else 'other cell'}\nRMSE {rm:.1f} m")
    gs = axes[0, 4].get_gridspec()
    for a in axes[:, 4]:
        a.remove()
    a = fig.add_subplot(gs[:, 4])
    bins = [(0, 3), (3, 10), (10, 30), (30, 1e9)]
    vals = [np.mean(ranks[(rel >= lo) & (rel < hi)] == 1) * 100 for lo, hi in bins]
    ns = [np.sum((rel >= lo) & (rel < hi)) for lo, hi in bins]
    a.bar(range(4), vals, color="#4c78a8")
    a.set_xticks(range(4), [f"{lo:g}-{hi:g} m\nn={n}" if hi < 1e8 else f">{lo:g} m\nn={n}" for (lo, hi), n in zip(bins, ns)], fontsize=8)
    a.set_ylabel("original cell ranked #1 (%)")
    a.set_xlabel("cell relief (std of height)")
    a.set_ylim(0, 105)
    for x, v in enumerate(vals):
        a.text(x, v + 2, f"{v:.0f}%", ha="center", fontsize=8)
    a.set_title("Recovery of 300 rotated Nevada cells", fontsize=9)
    fig.suptitle("Proof 1: a rotated, noisy copy of a cell finds the original among 52,852", fontsize=11)
    fig.tight_layout()
    fig.savefig(FIG / "1_recovery.png", dpi=130)
    plt.close(fig)

    # 2 + 3. Moon and Mars targets
    for site, src, label in TARGETS:
        r = tifffile.imread(SITES / site / f"{src}.tif").astype(np.float64)
        c = (r.shape[0] - 1) / 2
        T, P = target_variants(r, c, c)
        t = time.time()
        b_i, b_r, _, _ = ix.search(T, k=50, prune=False)
        tb = time.time() - t
        t = time.time()
        p_i, p_r, p_rot, done = ix.search(T, k=50)
        tp = time.time() - t
        same = set(b_i) == set(p_i) and np.allclose(np.sort(b_r), np.sort(p_r), atol=1e-6)
        all_r, _ = ix.exact(T)
        tstd = np.sqrt((T[0] ** 2).sum() / NPIX)
        print(f"{label}: relief std {tstd:.1f} m | best RMSE {p_r[0]:.1f} m (Nevada median {np.median(all_r):.1f} m) | "
              f"pruned == brute top-50: {same} | exact on {done:,}/{len(patches):,} cells | {tp * 1e3:.0f} ms vs {tb * 1e3:.0f} ms")

        fig = plt.figure(figsize=(14, 6.2))
        gs = fig.add_gridspec(2, 6, height_ratios=[1, 1.05])
        lim = np.nanmax(np.abs(P[0][MASK] - P[0][MASK].mean()))
        for k in range(5):
            show(fig.add_subplot(gs[0, k]), P[p_rot[k]], -lim, lim, f"{label.split(',')[0]}\nturned {ANGLES[p_rot[k]]}°")
        ax = fig.add_subplot(gs[0, 5])
        ax.hist(all_r, bins=80, color="#bbb")
        for k in range(5):
            ax.axvline(p_r[k], color="#d62728", lw=0.8)
        ax.set_title("RMSE to every Nevada cell\n(red: top 5)", fontsize=8)
        ax.set_xlabel("m", fontsize=8)
        ax.tick_params(labelsize=7)
        for k in range(5):
            i = p_i[k]
            show(fig.add_subplot(gs[1, k]), patches[i], -lim, lim,
                 f"#{k + 1} {lat[i]:.3f}, {lon[i]:.3f}\nRMSE {p_r[k]:.1f} m")
        ax = fig.add_subplot(gs[1, 5])
        ax.scatter(lon, lat, s=0.2, c="#ddd", rasterized=True)
        ax.scatter(lon[p_i], lat[p_i], s=8, c="#d62728")
        ax.set_title("Top 50 in Nevada", fontsize=8)
        ax.set_aspect(1 / np.cos(np.radians(39)))
        ax.tick_params(labelsize=7)
        fig.suptitle(f"{label}: target (top row, rotated to each match) vs best Nevada cells (bottom); "
                     f"same colour scale, height minus mean, ±{lim:.0f} m; disk = Earth-sized res-7 cell (5.16 km²)", fontsize=9)
        fig.tight_layout()
        fig.savefig(FIG / f"2_{site}.png", dpi=130)
        plt.close(fig)

    # Filter before ranking: e.g. only gentle cells (relief std < 20 m), the search ranks only those
    r = tifffile.imread(SITES / "viking1" / "hrsc_mola200.tif").astype(np.float64)
    T, _ = target_variants(r, 151.5, 151.5)
    allowed = ix.std < 20
    f_i, f_r, _, done = ix.search(T, k=10, allowed=allowed)
    print(f"filter demo (Viking 1, relief std < 20 m): {allowed.sum():,} cells allowed, exact on {done:,}, "
          f"all results pass: {bool(allowed[f_i].all())}, best RMSE {f_r[0]:.1f} m")


if __name__ == "__main__":
    main()
