# Feature importance: which features separate true from wrong analog edges?

Date: 2026-11-14. Inputs: the 8 site tables in `data/out/` as of this date (terrain, albedo,
FeO only). The SHA-256 prefix of each input file is in `feature_importance_meta.json`, so later
runs can tell whether they read the same data.

**Short answer: none of the current features separates the 5 true edges from the 10 wrong ones.**
The best AUC is 0.56 (`albedo__p10`), with a permutation p of 0.39. Most terrain features
score *below* 0.5, meaning true edges are, if anything, slightly *farther* apart than wrong
ones. With 15 edges, this rules out a strong single-feature signal. It does not rule out
weak ones.

## Reproduce

```bash
cd pipeline
python -m uv run python analysis/feature_importance.py
```

- The script is read-only on `data/` and writes only into `pipeline/analysis/`.
- It runs in about 5 s.
- It is deterministic: permutation tests are exact enumerations, and bootstraps use seed 20261114.
- Two runs gave byte-identical outputs.

Outputs:

| File | Contents |
|---|---|
| `feature_importance_results.csv` | One row per feature, with every metric below for both distance methods (`mean_*`, `w1_*`) |
| `feature_importance_dimensions.csv` | Per-dimension summary and composite distance |
| `edge_distances_mean.csv`, `edge_distances_w1.csv` | The standardised 15 × 17 distance matrices |
| `feature_importance_meta.json` | Input hashes, seed, and multivariate model scores |

## Method

1. **Site summaries.** Each feature column `<layer>__<stat>` is summarised per site in two
   ways: the mean over cells, and the full cell distribution.
2. **Edge distances**, standardised so features are comparable:
   - `mean`: |site mean(Earth) − site mean(target)| divided by the SD of the 8 site means.
   - `w1`: the 1-D Wasserstein distance between the two sites' cell distributions, divided by
     the SD of all pooled cells.
3. **Univariate separation.**
   - **AUC** = P(true-edge distance < wrong-edge distance), over all 5 × 10 = 50 pairs, with
     ties counted as ½. An AUC of 0.5 is chance; 1 means perfect separation.
   - **Permutation p-values**, by exact enumeration of the label assignments:
     - `p_plain`: all C(15,5) = 3,003 ways to choose 5 true edges.
     - `p_constrained`: all 3⁵ = 243 assignments where each planetary target has exactly one
       true Earth partner, as in the real labels. This is the more honest null. The smallest
       p it can give is 0.004.
   - **Hit rate**: the share of the 5 targets whose true Earth partner is the closest of the
     3 Earth sites. Chance is 0.33.
4. **Stability** (top-3 by AUC; tied features share a rank):
   - **Leave-one-site-out (LOSO)**: drop each of the 8 sites in turn, together with its edges
     and its effect on the standardisation.
   - **Bootstrap**, 2,000 resamples each:
     - over edges, stratified to keep 5 true and 10 wrong;
     - over planetary targets, resampling the 5 targets with their 3 edges each. This respects
       the fact that edges share sites.
5. **Multivariate** (overfit-prone, reported only as a check):
   - L2 logistic regression (λ = 1) on the 16 complete features.
   - Validated by leave-one-edge-out and leave-one-target-out.
   - Permutation importance, measured in-sample.

## Ranked table (mean-based distance; W1 in brackets)

| # | Feature | Dim | AUC | p plain | p constr. | Hit rate | LOSO top-3 | Boot top-3 (edge / target) | Edge-boot 95% AUC |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `albedo__p10` | 1 | 0.56 (0.54) | 0.38 | 0.39 | 2/5 | 6/8 | 0.64 / 0.70 | 0.20–0.94 |
| 2 | `albedo__std` | 1 | 0.50 (0.50) | 0.52 | 0.49 | 2/5 | 4/8 | 0.44 / 0.53 | 0.16–0.82 |
| 2 | `slope_deg__std` | 2 | 0.50 (0.50) | 0.52 | 0.54 | 1/5 | 5/8 | 0.48 / 0.56 | 0.16–0.84 |
| 2 | `tri_m__std` | 2 | 0.50 (0.48) | 0.52 | 0.54 | 1/5 | 4/8 | 0.45 / 0.54 | 0.20–0.80 |
| 5 | `albedo__mean` (= `__p50`) | 1 | 0.46 (0.46) | 0.62 | 0.63 | 1/5 | 3/8 | 0.44 / 0.43 | 0.14–0.80 |
| 7 | `slope_deg__p90`, `tri_m__mean`, `tri_m__p90` | 2 | 0.42 (0.40) | 0.70 | 0.82–0.86 | 1/5 | 1/8 | 0.23 / 0.28 | 0.14–0.74 |
| … | `tri_m__p50`, `slope_deg__mean`, `slope_deg__p50`, `albedo__p90`, `tri_m__p10` | 1–2 | 0.34–0.40 | 0.74–0.85 | 0.84–0.98 | 0–1/5 | 0/8 | ≤ 0.09 / ≤ 0.13 | — |
| 16 | `elevation_m__std` | 2 | 0.32 (0.30) | 0.87 | 0.92 | 1/5 | 0/8 | 0.01 / 0.04 | 0.08–0.62 |
| 17 | `slope_deg__p10` | 2 | 0.30 (0.28) | 0.90 | 0.95 | 0/5 | 0/8 | 0.01 / 0.02 | 0.08–0.60 |
| — | `feo_wt_pct__mean` | 1 | n/a | — | — | — | — | — | No Earth values: 0 of 15 edges usable |

Every bootstrap interval includes 0.5. No p-value is below 0.38.

## Per dimension

| Dimension | Usable features | Best (AUC) | Median AUC | Composite AUC (p constr.) | Composite hit rate |
|---|---|---|---|---|---|
| 1 Geology (albedo, FeO) | 5 of 6 (FeO unusable) | `albedo__p10` (0.56) | 0.46 | 0.44 (0.66) | 1/5 |
| 2 Terrain | 11 of 11 | `slope_deg__std` (0.50) | 0.40 | 0.38 (0.89) | 1/5 |
| 3–8 | not built yet | — | — | — | — |

The composite is the mean of a dimension's standardised distances.

## Multivariate check (do not use as weights)

- In-sample AUC is 0.82. Leave-one-target-out AUC falls to **0.34**, and leave-one-edge-out
  to **0.04**.
- The near-zero leave-one-edge-out score is a known artefact of leave-one-out with tiny
  classes, but either way the model does not generalise.
- In-sample permutation importance puts `albedo__p90` and `albedo__p10` on top, with large
  coefficients of opposite sign. That is the model fitting noise in two near-collinear columns.

## Why the features fail, edge by edge

These come from `edge_distances_mean.csv`:

- **Haughton–Shackleton (true)** is one of the *largest* terrain distances (about 2.3 SD).
  Shackleton is far rougher and steeper than any Earth site (mean slope 12° against 2–4°),
  so all three Earth edges to it are far. The true partner is not the nearest.
- **Sudbury–Apollo 16 (true)** has the second-largest albedo distance. Sudbury is forest and
  lakes (0.12), while Apollo 16 is highland regolith (0.29).
- **Atacama–Viking 1 (true)**: Viking 1 is extremely flat (mean slope 0.34°). Sudbury, not
  Atacama, is the closest in terrain.
- **Hits:** `albedo__p10` gets Atacama–Viking 2 and Haughton–Phoenix right. This is the only
  reason it ranks first.

## Caveats

- **n = 15, with 5 positives, and the edges are not independent.** Each site appears in 3 or
  5 edges, so one unusual site (Shackleton, or Viking 1) moves many edges at once. The
  target-cluster bootstrap and LOSO are the more honest stability measures. Even they rest
  on only 5 to 8 units.
- **Two of the five labels are team-chosen**, not historical: Haughton–Shackleton and
  Haughton–Phoenix. Haughton–Shackleton is also the edge that hurts terrain most.
- **Body-dependent features:**
  - Albedo definitions differ by body: Sentinel-2 broadband, LOLA 1064 nm, TES bolometric.
  - Planetary albedo sources are 3–7 km per pixel, so `albedo__std` and the gap between
    p10 and p90 are about 0 on the Moon and Mars because of resolution, not because the
    surface is uniform. Any "signal" in `albedo__std`, `__p10` or `__p90` may partly reflect
    this resolution difference rather than the surface.
  - `elevation_m__std` uses the H3 cell window, whose area differs by body (Earth 5.2, Moon
    2.7, Mars 10.3 km²).
  - Slope and TRI use a shared 200 m baseline and a fixed 6 km² window, so they are the
    cleanest cross-body features.
- **FeO is unusable on every edge:** it is empty at all 3 Earth sites (and at Phoenix). The
  script reports this as missing and does not impute it.
- **Redundant features:** `albedo__mean` and `albedo__p50` give identical rankings, and
  slope and TRI statistics are nearly collinear. The 17 rows are really about 5 independent
  signals.
- **Missing dimensions:** temperature/illumination and dimensions 4–8 are not in the data
  yet. Atacama's real analog basis (dimension 6, soil chemistry and habitability) is not
  represented at all.
- **Multiple comparisons:** 17 features × 2 methods were tested. Even a p of about 0.05 on
  one feature would not have been convincing.

## What this suggests

- With today's features, **terrain and albedo similarity do not explain the chosen analog
  pairs**, alone or combined. That matches the historical rationale: the pairs were picked
  for geology/process (impact breccia, soil oxidants, ground ice), not for matching slope
  or brightness at 6 km² scale.
- **Weighting terrain heavily would likely make the searcher worse at these labels.** Terrain
  distance mostly encodes "Shackleton is rough and Viking 1 is flat".
- `albedo__p10` and the within-cell spread features (`slope_deg__std`, `tri_m__std`) are the
  only ones that stay in the top 3 in at least half of the LOSO runs. Their AUCs are still
  indistinguishable from chance. Treat them as "not yet ruled out", not as "important".
- **Rerun this study once dimension 3 (temperature, insolation) and later dimensions are
  built.** The script picks up new `<layer>__<stat>` columns automatically.
- **Earth FeO**, if added, would make dimension 1 testable on all edges except those that
  involve Phoenix.
