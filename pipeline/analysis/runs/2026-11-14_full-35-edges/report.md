# Feature importance, full 35-edge graph (2026-11-14)

Input: `data/out/` after the full merge. 5 Earth sites × 7 planetary targets = 35 edges, 7 of them
true. 24 features score; `feo_wt_pct__mean` can't score because it has no Earth values.
Reproduce from `pipeline/`:

    python -m uv run python analysis/feature_importance.py --out-dir analysis/runs/2026-11-14_full-35-edges

## How distances are calculated

Each feature is used alone as the distance (univariate). For edge (Earth site E, target P) and feature f:

- **mean method** (`edge_distances_mean.csv`): d = |mean_E − mean_P| / SD(site means).
  - mean_X is the average of f over the H3 cells within 25 km of site X.
  - The SD is taken over the 12 site means. That makes features in different units
    comparable, and d ≈ 1 means "one typical site-to-site spread apart".
- **w1 method** (`edge_distances_w1.csv`): d = W1(cells_E, cells_P) / SD(all pooled cells).
  - W1 is the 1-D Wasserstein (earth-mover) distance between the two sites' cell-value
    distributions. It compares the whole histogram, not just the centre.
- Missing values: an edge gets no distance for f if either site has no values for it.

## How importance is scored

- **AUC:** P(a true edge is closer than a wrong edge), with ties counted as ½. 0.5 is chance,
  and values below 0.5 mean true edges are farther apart.
- **p_plain:** permutation p of the AUC against 100,000 seeded random labelings that keep 7 true
  edges. Exact enumeration would be C(35,7) ≈ 6.7 M.
- **p_constrained:** the same null, but each target keeps exactly one true Earth partner. It
  enumerates all 5^7 = 78,125 labelings exactly.
- **hit rate:** the fraction of the 7 targets whose true partner is the nearest Earth site.
  Chance is 1/5 = 0.2.
- **Robustness:** leave-one-site-out AUC range, plus edge and target (cluster) bootstrap 95% intervals.

## Results

| Feature | Dim | AUC (mean) | p_constr | hit rate | target-bootstrap 95% CI |
|---|---|---|---|---|---|
| wind_mean_ms__mean | 5 | 0.571 | 0.18 | 0.29 | 0.40–0.73 |
| albedo__p10 | 1 | 0.561 | 0.29 | 0.14 | 0.36–0.77 |
| insolation_wm2__mean | 3 | 0.546 | 0.32 | 0.29 | 0.31–0.77 |
| temp_day_max_k__mean | 3 | 0.546 | 0.27 | 0.29 | 0.36–0.75 |
| temp_night_max_k__mean | 3 | 0.536 | 0.27 | 0.29 | 0.40–0.70 |
| tri_m__mean | 2 | 0.536 | 0.32 | 0.14 | 0.37–0.72 |
| … 18 more | | 0.41–0.51 | ≥ 0.46 | | |

The full table is in `feature_importance_results.csv`.

- **No feature separates true from wrong edges.** The best AUC is 0.57, no p is below 0.18, and
  every bootstrap interval spans 0.5.
- **The top feature is an artefact.** Lunar wind is a physical 0, so every Moon edge's
  wind distance is just "how calm the Earth site is". Sudbury is the calmest Earth site, so it
  happens to match Apollo 16.
- **Aggregates** (equal-weight mean of all 24 distances): AUC 0.49, true/wrong distance ratio
  1.00, hit rate 1/7. The temperature/sunlight/weather subset gives AUC 0.54 (p_constr 0.24) and
  hit rate 3/7.
- **Logistic regression on all 24 features:** in-sample AUC 0.76, but 0.24 leave-one-target-out
  and 0.03 leave-one-edge-out. It's pure overfitting.

True-edge distances (mean method) for the top features:

| Edge | wind | albedo p10 | insolation | day max T | TRI |
|---|---|---|---|---|---|
| sudbury–apollo16 | 0.74 | 2.91 | 0.95 | 1.63 | 0.55 |
| atacama–viking1 | 1.26 | 0.58 | 1.59 | 0.80 | 0.90 |
| atacama–viking2 | 0.70 | 0.25 | 1.88 | 1.00 | 0.43 |
| haughton–shackleton | 1.19 | 2.49 | 1.27 | 1.48 | 2.29 |
| haughton–phoenix | 1.98 | 0.05 | 0.69 | 0.73 | 0.85 |
| blackpoint–apollo15 | 1.03 | 0.93 | 0.32 | 1.16 | 2.17 |
| dumont–bagnold | 1.06 | 0.38 | 1.23 | 0.82 | 0.14 |

Each true pair matches on one or two features and is far apart on others. Dumont–Bagnold is close
on roughness, Haughton–Phoenix on albedo, Black Point–Apollo 15 on sunlight. No single feature is
the shared reason across all the true pairs. That fits the historical record: each analog was
chosen for a specific dimension.
