"""Feature-importance study: which features separate the 5 true analog edges from the 10 wrong ones.

Read-only with respect to the pipeline: reads data/out/<site>.parquet and data/out/pairs.csv,
writes only into pipeline/analysis/. Deterministic: permutation tests are exact enumerations,
and bootstraps use a fixed seed.

Run from pipeline/:
    python -m uv run python analysis/feature_importance.py
"""
from __future__ import annotations

import hashlib
import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import wasserstein_distance

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent
OUT = PIPE / "data" / "out"
SEED = 20261114
N_BOOT = 2000
TOP_K = 3
NON_FEATURE = {"cell", "lat", "lon", "area_km2", "dist_km"}

EARTH = ["sudbury", "atacama", "haughton"]
TARGETS = ["apollo16", "shackleton", "viking1", "viking2", "phoenix"]
SITES = EARTH + TARGETS

# Layer -> dimension, from layers.py if importable (read only), otherwise a fixed fallback.
try:
    sys.path.insert(0, str(PIPE))
    from layers import DIMENSIONS, LAYERS  # noqa: E402

    LAYER_DIM = {l.name: l.dimension for l in LAYERS}
except Exception:  # pragma: no cover
    DIMENSIONS = {1: "Geology, mineralogy, and surface materials",
                  2: "Terrain, elevation, slope, roughness, craters"}
    LAYER_DIM = {"feo_wt_pct": 1, "albedo": 1, "elevation_m": 2, "slope_deg": 2, "tri_m": 2}

# Cross-body comparability notes (from README / AGENTS.md and the data itself).
COMPARABILITY = {
    "slope_deg": "comparable: shared 200 m baseline, fixed 6 km2 window on every body",
    "tri_m": "comparable: shared 200 m baseline, fixed 6 km2 window on every body",
    "elevation_m": "partly: cell window, and cell area differs by body (Earth 5.2, Moon 2.7, Mars 10.3 km2)",
    "albedo": "partly: definitions differ (S2 broadband / LOLA 1064 nm / TES bolometric)",
    "feo_wt_pct": "comparable quantity, but no Earth values, so unusable on any edge",
}
ALBEDO_SPREAD_NOTE = ("planetary albedo sources are 3-7 km/px, so within-cell spread is ~0 there "
                      "by resolution, not by surface")


# ---------------------------------------------------------------- data
def load():
    pairs = pd.read_csv(OUT / "pairs.csv")
    pairs["true"] = pairs["true"].astype(str).str.lower().eq("true")
    pairs = pairs.set_index(["earth", "target"]).loc[
        [(e, t) for e in EARTH for t in TARGETS]].reset_index()
    cells, digests = {}, {}
    for s in SITES:
        p = OUT / f"{s}.parquet"
        digests[s] = hashlib.sha256(p.read_bytes()).hexdigest()[:12]
        cells[s] = pd.read_parquet(p)
    feats = sorted({c for d in cells.values() for c in d.columns
                    if "__" in c and not c.endswith("__source") and c not in NON_FEATURE})
    return pairs, cells, feats, digests


def site_values(cells, feats):
    """Per site and feature: array of non-missing cell values (may be empty)."""
    vals = {}
    for s, d in cells.items():
        for f in feats:
            x = d[f].to_numpy(dtype=float) if f in d else np.array([])
            vals[s, f] = x[np.isfinite(x)]
    return vals


def edge_distances(pairs, vals, feats, sites):
    """Standardised distances per edge (rows) and feature (cols), two methods.

    mean: |site mean_E - site mean_P| / SD of the site means (over `sites` that have values).
    w1:   1-D Wasserstein between the two sites' cell distributions / SD of all pooled cells.
    NaN where either side has no values.
    """
    D = {m: pd.DataFrame(np.nan, index=pairs.index, columns=feats) for m in ("mean", "w1")}
    for f in feats:
        means = {s: vals[s, f].mean() for s in sites if vals[s, f].size}
        if len(means) < 2:
            continue
        sd_means = np.std(list(means.values()), ddof=1)
        pooled = np.concatenate([vals[s, f] for s in means])
        sd_cells = pooled.std(ddof=1)
        for i, (e, t) in enumerate(zip(pairs["earth"], pairs["target"])):
            if e not in means or t not in means:
                continue
            if sd_means > 0:
                D["mean"].iat[i, feats.index(f)] = abs(means[e] - means[t]) / sd_means
            if sd_cells > 0:
                D["w1"].iat[i, feats.index(f)] = wasserstein_distance(vals[e, f], vals[t, f]) / sd_cells
    return D


# ---------------------------------------------------------------- metrics
def auc_smaller(d, y):
    """P(distance of a true edge < distance of a wrong edge), ties count 1/2."""
    ok = np.isfinite(d)
    pos, neg = d[ok & y], d[ok & ~y]
    if pos.size == 0 or neg.size == 0:
        return np.nan
    diff = neg[None, :] - pos[:, None]
    return float(((diff > 0) + 0.5 * (diff == 0)).mean())


def all_labelings_plain(n, k):
    out = []
    for idx in itertools.combinations(range(n), k):
        y = np.zeros(n, bool)
        y[list(idx)] = True
        out.append(y)
    return np.array(out)


def all_labelings_constrained(pairs):
    """Every labelling where each planetary target has exactly one true Earth partner
    (the structure of the real labels): 3^5 = 243."""
    out = []
    for choice in itertools.product(EARTH, repeat=len(TARGETS)):
        m = dict(zip(TARGETS, choice))
        out.append((pairs["earth"] == pairs["target"].map(m)).to_numpy())
    return np.array(out)


def perm_p(d, y, labelings):
    obs = auc_smaller(d, y)
    if not np.isfinite(obs):
        return np.nan
    null = np.array([auc_smaller(d, yy) for yy in labelings])
    null = null[np.isfinite(null)]
    return float((null >= obs - 1e-12).mean())


def hit_rate(d, pairs):
    """For each target with data: does its true Earth partner have the smallest distance?
    Ties at the minimum count fractionally (1/number tied)."""
    hits, n, ranks = 0.0, 0, []
    for t in TARGETS:
        sub = pairs.index[pairs["target"] == t]
        dd = d[sub]
        yy = pairs.loc[sub, "true"].to_numpy()
        if not np.isfinite(dd).all() or yy.sum() != 1:
            continue
        n += 1
        dt = dd[yy][0]
        tied = (dd == dt).sum()
        if (dd < dt).sum() == 0:
            hits += 1.0 / tied
        ranks.append(1 + (dd < dt).sum() + 0.5 * (tied - 1))
    return (hits / n if n else np.nan), n, (float(np.mean(ranks)) if ranks else np.nan)


def top_k_flags(aucs: pd.Series, k=TOP_K):
    """True where a feature ranks in the top k by AUC (ties share the better rank)."""
    r = aucs.rank(ascending=False, method="min")
    return (r <= k) & aucs.notna()


# ---------------------------------------------------------------- multivariate (flagged)
def fit_logreg(X, y, lam=1.0):
    """L2-regularised logistic regression (intercept unpenalised), deterministic L-BFGS."""
    n, p = X.shape

    def f(w):
        z = X @ w[1:] + w[0]
        ll = np.logaddexp(0, z) - y * z
        return ll.sum() + 0.5 * lam * (w[1:] ** 2).sum()

    def g(w):
        z = X @ w[1:] + w[0]
        r = 1 / (1 + np.exp(-z)) - y
        return np.concatenate([[r.sum()], X.T @ r + lam * w[1:]])

    return minimize(f, np.zeros(p + 1), jac=g, method="L-BFGS-B").x


def predict(w, X):
    return X @ w[1:] + w[0]


def multivariate(D, y, pairs, rng, lam=1.0, n_rep=50):
    cols = [c for c in D.columns if D[c].notna().all()]
    X = D[cols].to_numpy()
    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1
    Xs = (X - mu) / sd
    yf = y.astype(float)
    # Leave-one-target-out: hold out the 3 edges of one planetary site at a time.
    loto = np.empty(len(y))
    for t in TARGETS:
        te = (pairs["target"] == t).to_numpy()
        w = fit_logreg(Xs[~te], yf[~te], lam)
        loto[te] = predict(w, Xs[te])
    looe = np.empty(len(y))
    for i in range(len(y)):
        tr = np.arange(len(y)) != i
        looe[i] = predict(fit_logreg(Xs[tr], yf[tr], lam), Xs[i:i + 1])[0]
    w_full = fit_logreg(Xs, yf, lam)
    score_full = predict(w_full, Xs)
    # AUC of "true edges have higher score" == auc_smaller on -score.
    auc_in = auc_smaller(-score_full, y)
    imp = {}
    for j, c in enumerate(cols):
        drops = []
        for _ in range(n_rep):
            Xp = Xs.copy()
            Xp[:, j] = rng.permutation(Xp[:, j])
            drops.append(auc_in - auc_smaller(-predict(w_full, Xp), y))
        imp[c] = float(np.mean(drops))
    return {
        "features": cols,
        "lambda": lam,
        "auc_in_sample": auc_in,
        "auc_leave_one_edge_out": auc_smaller(-looe, y),
        "auc_leave_one_target_out": auc_smaller(-loto, y),
        "coef": dict(zip(cols, w_full[1:])),
        "perm_importance": imp,
    }


# ---------------------------------------------------------------- main
def main():
    pairs, cells, feats, digests = load()
    vals = site_values(cells, feats)
    y = pairs["true"].to_numpy()
    rng = np.random.default_rng(SEED)
    plain = all_labelings_plain(len(y), int(y.sum()))
    constr = all_labelings_constrained(pairs)

    D = edge_distances(pairs, vals, feats, SITES)
    res = pd.DataFrame(index=feats)
    res["layer"] = [f.split("__")[0] for f in feats]
    res["stat"] = [f.split("__")[1] for f in feats]
    res["dimension"] = res["layer"].map(LAYER_DIM)
    res["cross_body"] = res["layer"].map(COMPARABILITY)
    res.loc[res["layer"].eq("albedo") & ~res["stat"].eq("mean") & ~res["stat"].eq("p50"),
            "cross_body"] += "; " + ALBEDO_SPREAD_NOTE
    res["sites_with_values"] = [";".join(s for s in SITES if vals[s, f].size) for f in feats]
    res["sites_missing"] = [";".join(s for s in SITES if not vals[s, f].size) for f in feats]

    for m in ("mean", "w1"):
        d_all = D[m]
        res[f"{m}_n_edges"] = d_all.notna().sum().values
        res[f"{m}_n_true_edges"] = [int((d_all[f].notna() & y).sum()) for f in feats]
        res[f"{m}_auc"] = [auc_smaller(d_all[f].to_numpy(), y) for f in feats]
        res[f"{m}_p_plain"] = [perm_p(d_all[f].to_numpy(), y, plain) for f in feats]
        res[f"{m}_p_constrained"] = [perm_p(d_all[f].to_numpy(), y, constr) for f in feats]
        hr = [hit_rate(d_all[f].to_numpy(), pairs) for f in feats]
        res[f"{m}_hit_rate"] = [h[0] for h in hr]
        res[f"{m}_hit_n_targets"] = [h[1] for h in hr]
        res[f"{m}_true_partner_mean_rank"] = [h[2] for h in hr]
        res[f"{m}_top3"] = top_k_flags(res[f"{m}_auc"]).values

        # Leave-one-site-out: drop the site, its edges, and its contribution to the spreads.
        lo_auc, lo_top = [], []
        for s in SITES:
            keep = ~(pairs["earth"].eq(s) | pairs["target"].eq(s)).to_numpy()
            pk = pairs[keep].reset_index(drop=True)
            Dk = edge_distances(pk, vals, feats, [x for x in SITES if x != s])[m]
            a = pd.Series({f: auc_smaller(Dk[f].to_numpy(), pk["true"].to_numpy()) for f in feats})
            lo_auc.append(a)
            lo_top.append(top_k_flags(a))
        lo_auc, lo_top = pd.concat(lo_auc, axis=1), pd.concat(lo_top, axis=1)
        res[f"{m}_loso_auc_min"] = lo_auc.min(axis=1)
        res[f"{m}_loso_auc_max"] = lo_auc.max(axis=1)
        res[f"{m}_loso_top3_frac"] = lo_top.mean(axis=1)

        # Bootstrap over edges (stratified 5 true / 10 wrong) and over planetary targets
        # (cluster bootstrap: resample targets, keep their 3 edges; respects shared sites).
        pos_i, neg_i = np.flatnonzero(y), np.flatnonzero(~y)
        tgt_idx = {t: np.flatnonzero(pairs["target"].eq(t)) for t in TARGETS}
        Dm = d_all.to_numpy()
        for kind in ("edge", "target"):
            aucs = np.full((N_BOOT, len(feats)), np.nan)
            for b in range(N_BOOT):
                if kind == "edge":
                    idx = np.concatenate([rng.choice(pos_i, pos_i.size), rng.choice(neg_i, neg_i.size)])
                else:
                    idx = np.concatenate([tgt_idx[t] for t in rng.choice(TARGETS, len(TARGETS))])
                for j in range(len(feats)):
                    aucs[b, j] = auc_smaller(Dm[idx, j], y[idx])
            A = pd.DataFrame(aucs, columns=feats)
            tops = A.apply(top_k_flags, axis=1)
            with np.errstate(all="ignore"):
                res[f"{m}_boot_{kind}_auc_lo"] = np.nanpercentile(aucs, 2.5, axis=0)
                res[f"{m}_boot_{kind}_auc_hi"] = np.nanpercentile(aucs, 97.5, axis=0)
            res[f"{m}_boot_{kind}_top3_frac"] = tops.mean().values
            res.loc[res[f"{m}_auc"].isna(),
                    [f"{m}_boot_{kind}_auc_lo", f"{m}_boot_{kind}_auc_hi"]] = np.nan

    # Multivariate (overfit-prone; reported, not trusted).
    mv = {m: multivariate(D[m], y, pairs, rng) for m in ("mean", "w1")}
    for m in mv:
        res[f"{m}_logreg_coef"] = res.index.map(mv[m]["coef"])
        res[f"{m}_logreg_perm_importance"] = res.index.map(mv[m]["perm_importance"])

    res = res.sort_values(["mean_auc", "w1_auc"], ascending=False, na_position="last")
    res.index.name = "feature"
    res.round(4).to_csv(HERE / "feature_importance_results.csv")

    # Per-dimension composites: mean of the dimension's standardised distances.
    dims = []
    for dim, grp in res.groupby("dimension"):
        row = {"dimension": int(dim), "name": DIMENSIONS.get(int(dim), ""),
               "features": len(grp), "usable": int(grp["mean_auc"].notna().sum())}
        for m in ("mean", "w1"):
            cols = [f for f in grp.index if D[m][f].notna().all()]
            comp = D[m][cols].mean(axis=1).to_numpy() if cols else np.full(len(y), np.nan)
            row[f"{m}_best"] = grp[f"{m}_auc"].idxmax() if grp[f"{m}_auc"].notna().any() else ""
            row[f"{m}_best_auc"] = grp[f"{m}_auc"].max()
            row[f"{m}_median_auc"] = grp[f"{m}_auc"].median()
            row[f"{m}_composite_auc"] = auc_smaller(comp, y)
            row[f"{m}_composite_p_constrained"] = perm_p(comp, y, constr)
            row[f"{m}_composite_hit_rate"] = hit_rate(comp, pairs)[0]
        dims.append(row)
    dims = pd.DataFrame(dims)
    dims.round(4).to_csv(HERE / "feature_importance_dimensions.csv", index=False)

    D["mean"].assign(earth=pairs["earth"], target=pairs["target"], true=y).round(4).to_csv(
        HERE / "edge_distances_mean.csv", index=False)
    D["w1"].assign(earth=pairs["earth"], target=pairs["target"], true=y).round(4).to_csv(
        HERE / "edge_distances_w1.csv", index=False)

    meta = {
        "inputs_sha256_12": digests,
        "seed": SEED, "n_boot": N_BOOT, "top_k": TOP_K,
        "n_plain_labelings": int(len(plain)), "n_constrained_labelings": int(len(constr)),
        "multivariate": {m: {k: (v if not isinstance(v, float) else round(v, 4))
                             for k, v in mv[m].items() if k not in ("coef", "perm_importance")}
                         for m in mv},
    }
    (HERE / "feature_importance_meta.json").write_text(json.dumps(meta, indent=2))

    show = ["dimension", "mean_auc", "mean_p_plain", "mean_p_constrained", "mean_hit_rate",
            "mean_loso_top3_frac", "mean_boot_target_top3_frac", "w1_auc", "w1_p_constrained",
            "w1_hit_rate", "w1_loso_top3_frac"]
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print(res[show].round(3))
        print(dims.round(3))
        print(json.dumps(meta["multivariate"], indent=1))


if __name__ == "__main__":
    main()
