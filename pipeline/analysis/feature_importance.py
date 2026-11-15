"""Feature-importance study: which features separate the true analog edges from the wrong ones.

Read-only with respect to the pipeline: reads data/out/<site>.parquet and data/out/pairs.csv,
writes only into pipeline/analysis/. Sites come from pairs.csv (Earth sites x planetary targets).
Deterministic: permutation tests are exact enumerations when there are at most MAX_ENUM
labelings, otherwise MC_DRAWS seeded Monte Carlo draws; bootstraps use a fixed seed.

Run from pipeline/:
    python -m uv run python analysis/feature_importance.py

Optional arguments (defaults reproduce the committed preliminary run):
    --data-dir DIR             read <site>.parquet and pairs.csv from DIR (default data/out)
    --out-dir DIR              write results into DIR (default analysis/)
    --targets T1,T2            restrict to these planetary targets (e.g. apollo16,shackleton)
    --exclude-edge E:T         drop one Earth-target edge entirely (repeatable)
    --relabel-false E:T        keep the edge but label it wrong (repeatable)
    --transform PREFIX=KIND    apply log1p or rank to the cell values of every feature whose
                               name starts with PREFIX, before distances (repeatable)

Missing values: a feature is scored only on the edges where both sites have values. Its
permutation null enumerates labelings of exactly those edges (same number of true edges, and
for the constrained null the same per-target structure). Targets without exactly one true edge
are skipped by the per-target metrics (hit rate) and contribute only negatives elsewhere.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import rankdata, wasserstein_distance

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent
OUT = PIPE / "data" / "out"
SEED = 20261114
N_BOOT = 2000
TOP_K = 3
MAX_ENUM = 200_000   # exact permutation null up to this many labelings
MC_DRAWS = 100_000   # otherwise this many seeded random labelings
NON_FEATURE = {"cell", "lat", "lon", "area_km2", "dist_km"}

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
    "temp_day_max_k": "comparable quantity (surface K); sources differ (POWER / Diviner / Mars GCM)",
    "temp_night_max_k": "comparable quantity (surface K); sources differ (POWER / Diviner / Mars GCM)",
    "temp_night_min_k": "comparable quantity (surface K); sources differ (POWER / Diviner / Mars GCM)",
    "temp_mean_k": "comparable quantity (surface K); sources differ (POWER / Diviner / Mars GCM)",
    "insolation_wm2": "comparable: same orbital calculation on every body; ignores terrain shadow and atmosphere",
    "pressure_mean_pa": "body-dependent: Moon is a physical 0, Earth ~1e5 Pa; the body gap dominates the SD",
    "wind_mean_ms": "body-dependent: Moon is a physical 0; Earth at 10 m, Mars lowest GCM layer",
    "wind_max_ms": "body-dependent: Moon is a physical 0; Earth at 10 m, Mars lowest GCM layer",
}
ALBEDO_SPREAD_NOTE = ("planetary albedo sources are 3-7 km/px, so within-cell spread is ~0 there "
                      "by resolution, not by surface")


# ---------------------------------------------------------------- data
def site_lists(out=OUT):
    """Earth sites and planetary targets in pairs.csv order."""
    pairs = pd.read_csv(out / "pairs.csv")
    return list(dict.fromkeys(pairs["earth"])), list(dict.fromkeys(pairs["target"]))


def load(out=OUT, targets=None, exclude=(), relabel_false=()):
    earth, all_targets = site_lists(out)
    targets = targets or all_targets
    pairs = pd.read_csv(out / "pairs.csv")
    pairs["true"] = pairs["true"].astype(str).str.lower().eq("true")
    pairs = pairs.set_index(["earth", "target"]).loc[
        [(e, t) for e in earth for t in targets]].reset_index()
    for e, t in list(exclude) + list(relabel_false):
        if not ((pairs["earth"] == e) & (pairs["target"] == t)).any():
            raise SystemExit(f"edge {e}:{t} is not in pairs")
    for e, t in relabel_false:
        pairs.loc[(pairs["earth"] == e) & (pairs["target"] == t), "true"] = False
    if exclude:
        drop = pd.Series(False, index=pairs.index)
        for e, t in exclude:
            drop |= (pairs["earth"] == e) & (pairs["target"] == t)
        pairs = pairs[~drop].reset_index(drop=True)
    cells, digests = {}, {}
    for s in earth + list(targets):
        p = out / f"{s}.parquet"
        digests[s] = hashlib.sha256(p.read_bytes()).hexdigest()[:12]
        cells[s] = pd.read_parquet(p)
    feats = sorted({c for d in cells.values() for c in d.columns
                    if "__" in c and not c.endswith("__source") and c not in NON_FEATURE})
    return pairs, cells, feats, digests


def site_values(cells, feats, transforms=None, sites=None):
    """Per site and feature: array of non-missing cell values (may be empty).

    transforms: {feature prefix: "log1p" | "rank"}. rank replaces each cell value by its
    average rank among the pooled cells of `sites` (all loaded sites by default)."""
    vals = {}
    for s, d in cells.items():
        for f in feats:
            x = d[f].to_numpy(dtype=float) if f in d else np.array([])
            vals[s, f] = x[np.isfinite(x)]
    for prefix, kind in (transforms or {}).items():
        hit = [f for f in feats if f.startswith(prefix)]
        if not hit:
            raise SystemExit(f"--transform {prefix}: no feature matches")
        for f in hit:
            if kind == "log1p":
                for s in cells:
                    vals[s, f] = np.log1p(vals[s, f])
            else:  # rank
                ss = [s for s in (sites or list(cells)) if vals[s, f].size]
                r = rankdata(np.concatenate([vals[s, f] for s in ss]))
                i = 0
                for s in ss:
                    n = vals[s, f].size
                    vals[s, f], i = r[i:i + n], i + n
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


def auc_many(d, labelings):
    """auc_smaller for every row of a (m, n) boolean labeling matrix at once, via midranks
    (Mann-Whitney U): AUC = (sum of wrong-edge ranks - n_w(n_w+1)/2) / (n_t n_w)."""
    r = rankdata(d)
    L = labelings.astype(float)
    n_t = L.sum(1)
    n_w = d.size - n_t
    with np.errstate(all="ignore"):
        return ((1 - L) @ r - n_w * (n_w + 1) / 2) / (n_t * n_w)


def _mc_rng(n, k):
    return np.random.default_rng([SEED, n, k])


def all_labelings_plain(n, k):
    """Every labelling with k true edges among n; seeded Monte Carlo draws if there are more
    than MAX_ENUM."""
    if math.comb(n, k) > MAX_ENUM:
        rng = _mc_rng(n, k)
        keys = rng.random((MC_DRAWS, n))
        idx = np.argpartition(keys, k - 1, axis=1)[:, :k]
        out = np.zeros((MC_DRAWS, n), bool)
        np.put_along_axis(out, idx, True, axis=1)
        return out
    out = []
    for idx in itertools.combinations(range(n), k):
        y = np.zeros(n, bool)
        y[list(idx)] = True
        out.append(y)
    return np.array(out)


def all_labelings_constrained(pairs, y=None):
    """Every labelling with the per-target structure of the real labels: each planetary
    target keeps its number of true edges (normally exactly one true Earth partner, so
    3^5 = 243), placed on any of its edges. A target with no true edge stays all-wrong."""
    y = pairs["true"].to_numpy() if y is None else y
    t_arr = pairs["target"].to_numpy()
    per_t = []
    for t in dict.fromkeys(t_arr):
        idx = np.flatnonzero(t_arr == t)
        per_t.append([list(c) for c in itertools.combinations(idx, int(y[idx].sum()))])
    if math.prod(len(c) for c in per_t) > MAX_ENUM:
        rng = _mc_rng(len(pairs), int(y.sum()) + 1000)
        out = np.zeros((MC_DRAWS, len(pairs)), bool)
        for choices in per_t:
            pick = rng.integers(len(choices), size=MC_DRAWS)
            for j, c in enumerate(choices):
                rows = np.flatnonzero(pick == j)
                for e in c:
                    out[rows, e] = True
        return out
    out = []
    for choice in itertools.product(*per_t):
        yy = np.zeros(len(pairs), bool)
        for c in choice:
            yy[c] = True
        out.append(yy)
    return np.array(out)


def perm_p(d, y, labelings, kind=None, pairs=None):
    """Exact permutation p of the AUC. If some edges have no distance (missing feature) and
    `kind` is given ("plain"/"constrained"), the null is re-enumerated over the edges with
    values only, keeping their number of true edges (and per-target structure)."""
    obs = auc_smaller(d, y)
    if not np.isfinite(obs):
        return np.nan
    ok = np.isfinite(d)
    if kind is not None and not ok.all():
        d, y = d[ok], y[ok]
        if kind == "plain":
            labelings = all_labelings_plain(len(y), int(y.sum()))
        else:
            labelings = all_labelings_constrained(pairs[ok].reset_index(drop=True), y)
    null = auc_many(d, labelings)
    null = null[np.isfinite(null)]
    return float((null >= obs - 1e-12).mean())


def hit_rate(d, pairs, targets):
    """For each target with data: does its true Earth partner have the smallest distance?
    Ties at the minimum count fractionally (1/number tied). Targets without exactly one true
    edge, or with a missing distance, are skipped."""
    hits, n, ranks = 0.0, 0, []
    for t in targets:
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


def multivariate(D, y, pairs, rng, targets, lam=1.0, n_rep=50):
    cols = [c for c in D.columns if D[c].notna().all()]
    X = D[cols].to_numpy()
    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1
    Xs = (X - mu) / sd
    yf = y.astype(float)
    # Leave-one-target-out: hold out all edges of one planetary site at a time.
    loto = np.empty(len(y))
    for t in targets:
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
def _edge(s):
    e, _, t = s.partition(":")
    if not e or not t:
        raise argparse.ArgumentTypeError(f"expected EARTH:TARGET, got {s!r}")
    return e, t


def _transform(s):
    k, _, v = s.partition("=")
    if not k or v not in ("log1p", "rank"):
        raise argparse.ArgumentTypeError(f"expected PREFIX=log1p|rank, got {s!r}")
    return k, v


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", type=Path, default=OUT,
                    help="directory with <site>.parquet and pairs.csv (default data/out)")
    ap.add_argument("--out-dir", type=Path, default=HERE,
                    help="where results are written (default analysis/)")
    ap.add_argument("--targets", type=lambda s: [x for x in s.split(",") if x], default=None,
                    help="comma-separated planetary targets to keep (default all in pairs.csv)")
    ap.add_argument("--exclude-edge", type=_edge, action="append", default=[],
                    metavar="EARTH:TARGET", help="drop this edge entirely (repeatable)")
    ap.add_argument("--relabel-false", type=_edge, action="append", default=[],
                    metavar="EARTH:TARGET", help="label this edge wrong (repeatable)")
    ap.add_argument("--transform", type=_transform, action="append", default=[],
                    metavar="PREFIX=log1p|rank", help="transform matching features (repeatable)")
    return ap.parse_args(argv)


NEW_LAYERS = {"temp_day_max_k", "temp_night_max_k", "temp_night_min_k", "temp_mean_k",
              "insolation_wm2", "pressure_mean_pa", "wind_mean_ms", "wind_max_ms"}


def aggregate(D, feats_sets, y, pairs, plain, constr, targets):
    """Equal-weight mean of the standardised distances per edge, over the features that have
    a value on that edge; then true-edge mean vs wrong-edge mean."""
    rows, per_edge = [], {}
    for m in ("mean", "w1"):
        for name, cols in feats_sets.items():
            cols = [c for c in cols if D[m][c].notna().any()]
            if not cols:
                continue
            X = D[m][cols]
            agg = X.mean(axis=1, skipna=True).to_numpy()
            per_edge[f"{m}_{name}"] = agg
            per_edge[f"{m}_{name}_n_features"] = X.notna().sum(axis=1).to_numpy()
            ok = np.isfinite(agg)
            tm, wm = float(np.mean(agg[ok & y])), float(np.mean(agg[ok & ~y]))
            hr = hit_rate(agg, pairs, targets)
            rows.append({
                "method": m, "feature_set": name, "n_features": len(cols),
                "n_edges": int(ok.sum()), "n_true_edges": int((ok & y).sum()),
                "true_mean_dist": tm, "wrong_mean_dist": wm, "ratio_true_over_wrong": tm / wm,
                "auc": auc_smaller(agg, y),
                "p_plain": perm_p(agg, y, plain, "plain", pairs),
                "p_constrained": perm_p(agg, y, constr, "constrained", pairs),
                "hit_rate": hr[0], "hit_n_targets": hr[1], "true_partner_mean_rank": hr[2],
            })
    return pd.DataFrame(rows), pd.DataFrame(per_edge)


def main(argv=None):
    args = parse_args(argv)
    earth, all_targets = site_lists(args.data_dir)
    targets = args.targets or all_targets
    for t in targets:
        if t not in all_targets:
            raise SystemExit(f"unknown target {t}")
    outdir = args.out_dir
    outdir.mkdir(parents=True, exist_ok=True)
    pairs, cells, feats, digests = load(args.data_dir, targets, args.exclude_edge,
                                        args.relabel_false)
    # Sites that still have an edge; a target whose edges were all excluded also drops out
    # of the standardisation.
    sites = earth + [t for t in targets if (pairs["target"] == t).any()]
    targets = [t for t in targets if t in sites]
    transforms = dict(args.transform)
    vals = site_values(cells, feats, transforms, sites)
    y = pairs["true"].to_numpy()
    rng = np.random.default_rng(SEED)
    plain = all_labelings_plain(len(y), int(y.sum()))
    constr = all_labelings_constrained(pairs)

    D = edge_distances(pairs, vals, feats, sites)
    res = pd.DataFrame(index=feats)
    res["layer"] = [f.split("__")[0] for f in feats]
    res["stat"] = [f.split("__")[1] for f in feats]
    res["dimension"] = res["layer"].map(LAYER_DIM)
    res["cross_body"] = res["layer"].map(COMPARABILITY)
    res.loc[res["layer"].eq("albedo") & ~res["stat"].eq("mean") & ~res["stat"].eq("p50"),
            "cross_body"] += "; " + ALBEDO_SPREAD_NOTE
    res["sites_with_values"] = [";".join(s for s in sites if vals[s, f].size) for f in feats]
    res["sites_missing"] = [";".join(s for s in sites if not vals[s, f].size) for f in feats]

    for m in ("mean", "w1"):
        d_all = D[m]
        res[f"{m}_n_edges"] = d_all.notna().sum().values
        res[f"{m}_n_true_edges"] = [int((d_all[f].notna() & y).sum()) for f in feats]
        res[f"{m}_auc"] = [auc_smaller(d_all[f].to_numpy(), y) for f in feats]
        res[f"{m}_p_plain"] = [perm_p(d_all[f].to_numpy(), y, plain, "plain", pairs)
                               for f in feats]
        res[f"{m}_p_constrained"] = [perm_p(d_all[f].to_numpy(), y, constr, "constrained", pairs)
                                     for f in feats]
        hr = [hit_rate(d_all[f].to_numpy(), pairs, targets) for f in feats]
        res[f"{m}_hit_rate"] = [h[0] for h in hr]
        res[f"{m}_hit_n_targets"] = [h[1] for h in hr]
        res[f"{m}_true_partner_mean_rank"] = [h[2] for h in hr]
        res[f"{m}_top3"] = top_k_flags(res[f"{m}_auc"]).values

        # Leave-one-site-out: drop the site, its edges, and its contribution to the spreads.
        lo_auc, lo_top = [], []
        for s in sites:
            keep = ~(pairs["earth"].eq(s) | pairs["target"].eq(s)).to_numpy()
            pk = pairs[keep].reset_index(drop=True)
            Dk = edge_distances(pk, vals, feats, [x for x in sites if x != s])[m]
            a = pd.Series({f: auc_smaller(Dk[f].to_numpy(), pk["true"].to_numpy()) for f in feats})
            lo_auc.append(a)
            lo_top.append(top_k_flags(a))
        lo_auc, lo_top = pd.concat(lo_auc, axis=1), pd.concat(lo_top, axis=1)
        res[f"{m}_loso_auc_min"] = lo_auc.min(axis=1)
        res[f"{m}_loso_auc_max"] = lo_auc.max(axis=1)
        res[f"{m}_loso_top3_frac"] = lo_top.mean(axis=1)

        # Bootstrap over edges (stratified true / wrong) and over planetary targets
        # (cluster bootstrap: resample targets, keep all their edges; respects shared sites).
        pos_i, neg_i = np.flatnonzero(y), np.flatnonzero(~y)
        tgt_idx = {t: np.flatnonzero(pairs["target"].eq(t)) for t in targets}
        Dm = d_all.to_numpy()
        for kind in ("edge", "target"):
            aucs = np.full((N_BOOT, len(feats)), np.nan)
            for b in range(N_BOOT):
                if kind == "edge":
                    idx = np.concatenate([rng.choice(pos_i, pos_i.size), rng.choice(neg_i, neg_i.size)])
                else:
                    idx = np.concatenate([tgt_idx[t] for t in rng.choice(targets, len(targets))])
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
    mv = {m: multivariate(D[m], y, pairs, rng, targets) for m in ("mean", "w1")}
    for m in mv:
        res[f"{m}_logreg_coef"] = res.index.map(mv[m]["coef"])
        res[f"{m}_logreg_perm_importance"] = res.index.map(mv[m]["perm_importance"])

    res = res.sort_values(["mean_auc", "w1_auc"], ascending=False, na_position="last")
    res.index.name = "feature"
    res.round(4).to_csv(outdir / "feature_importance_results.csv")

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
            row[f"{m}_composite_p_constrained"] = perm_p(comp, y, constr, "constrained", pairs)
            row[f"{m}_composite_hit_rate"] = hit_rate(comp, pairs, targets)[0]
        dims.append(row)
    dims = pd.DataFrame(dims)
    dims.round(4).to_csv(outdir / "feature_importance_dimensions.csv", index=False)

    D["mean"].assign(earth=pairs["earth"], target=pairs["target"], true=y).round(4).to_csv(
        outdir / "edge_distances_mean.csv", index=False)
    D["w1"].assign(earth=pairs["earth"], target=pairs["target"], true=y).round(4).to_csv(
        outdir / "edge_distances_w1.csv", index=False)

    meta = {
        "inputs_sha256_12": digests,
        "seed": SEED, "n_boot": N_BOOT, "top_k": TOP_K,
        "n_plain_labelings": int(len(plain)), "n_constrained_labelings": int(len(constr)),
        "multivariate": {m: {k: (v if not isinstance(v, float) else round(v, 4))
                             for k, v in mv[m].items() if k not in ("coef", "perm_importance")}
                         for m in mv},
    }
    nondefault = {
        "data_dir": str(args.data_dir) if args.data_dir != OUT else None,
        "targets": args.targets,
        "exclude_edge": [":".join(e) for e in args.exclude_edge] or None,
        "relabel_false": [":".join(e) for e in args.relabel_false] or None,
        "transform": transforms or None,
    }
    nondefault = {k: v for k, v in nondefault.items() if v}
    if nondefault:
        # Only for non-default runs, so a default run keeps the committed meta layout.
        meta["run"] = {**nondefault, "n_edges": int(len(y)), "n_true_edges": int(y.sum()),
                       "standardisation_sites": sites, "targets_used": targets}
    (outdir / "feature_importance_meta.json").write_text(json.dumps(meta, indent=2))

    # Aggregate true-vs-wrong distance over: all features with values, the features complete
    # on every edge, temperature/sunlight/weather only, and terrain/albedo/FeO only.
    fsets = {"all": feats,
             "complete": [f for f in feats if D["mean"][f].notna().all()],
             "temp_sun_weather": [f for f in feats if f.split("__")[0] in NEW_LAYERS],
             "terrain_albedo": [f for f in feats if f.split("__")[0] not in NEW_LAYERS]}
    agg, agg_edges = aggregate(D, fsets, y, pairs, plain, constr, targets)
    agg.round(4).to_csv(outdir / "aggregate_distance.csv", index=False)
    agg_edges.assign(earth=pairs["earth"], target=pairs["target"], true=y).round(4).to_csv(
        outdir / "aggregate_distance_edges.csv", index=False)

    show = ["dimension", "mean_auc", "mean_p_plain", "mean_p_constrained", "mean_hit_rate",
            "mean_loso_top3_frac", "mean_boot_target_top3_frac", "w1_auc", "w1_p_constrained",
            "w1_hit_rate", "w1_loso_top3_frac"]
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print(res[show].round(3))
        print(dims.round(3))
        print(json.dumps(meta["multivariate"], indent=1))
        print(agg.round(3))


if __name__ == "__main__":
    main()
