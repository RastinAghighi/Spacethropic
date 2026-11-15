# Feature importance rerun: Earth–Moon temperature, sunlight and weather, plus Haughton–Shackleton ablation

2026-11-14. Inputs are in `snapshot/`, a copy of `data/out/` taken before the Mars merge; checksums are in
`snapshot_checksums.tsv`. The Earth and Moon files have the 8 new columns. The 3 Mars files are stale,
with terrain, albedo and FeO only. The preliminary run in `pipeline/analysis/` is unchanged.

## Short answer

**Temperature and sunlight**
- On the 6 Earth–Moon edges, insolation, day-max temperature and night-min temperature each reach
  AUC 0.75. The constrained p is 0.22 for insolation and 0.33 for the two temperatures.
- That comes from a single hit: Shackleton's closest Earth site is Haughton, the polar site. Apollo 16
  is closest to Atacama, not Sudbury.
- It is essentially latitude, and close to circular, because Haughton–Shackleton was chosen as a polar
  crater pair.

**Weather**
- Weather does not separate true from wrong. Wind gives AUC 0.50 and pressure 0.25.
- Both are body artefacts, because the Moon's values are 0.

**Terrain and albedo**
- These are unchanged from the preliminary run: `albedo__p10` has AUC 0.56 and p 0.39.
- Dropping or relabelling Haughton–Shackleton does not rescue terrain. B and C look better only because
  Shackleton's wrong edges are far apart.
- With Shackleton removed entirely (B2), the true edges are farther apart than the wrong ones: ratio
  1.37 and AUC 0.22.

**Significance**
- Nothing is significant. The smallest constrained p in any run is 0.22 (A) or 0.31 (B2).

## Ablation table

Ratio is true-edge over wrong-edge mean of the equal-weight standardised distances. The 16-feature
column uses only the features present on every edge, so it is the like-for-like comparison.

| Run | Edges (true) | Ratio, all (AUC, p constrained) | Ratio, 16 features (AUC, p constrained) | `albedo__p10` AUC (p constrained) | Hit rate |
|---|---|---|---|---|---|
| A: all edges | 15 (5) | 1.04 (0.44, 0.80) | 1.09 (0.36, 0.86) | 0.56 (0.39) | 2/5 |
| B: drop haughton–shackleton | 14 (4) | 0.87 (0.50, 0.86) | 0.88 (0.425, 0.86) | 0.675 (0.33) | 1/4 |
| B2: drop all Shackleton edges | 12 (4) | 1.24 (0.25, 0.95) | 1.37 (0.22, 0.94) | 0.625 (0.31) | 0/4 |
| C: relabel haughton–shackleton wrong | 15 (4) | 0.81 (0.55, 0.86) | 0.82 (0.48, 0.86) | 0.68 (0.38) | 1/4 |

Top features per run:

| Run | Top features | Wind artefact? |
|---|---|---|
| A | insolation and temperatures, AUC 0.75 | — |
| B | wind 0.875, temperatures 0.75 | yes |
| B2 | wind 1.0, temperatures 0.5 | yes |
| C | wind 0.90, insolation 0.80 | yes |

With the Moon at 0, wind just picks the calmest Earth site (Sudbury). With the Haughton–Shackleton
label gone, temperature has no hit on Apollo 16, and falls to 0.5 in B2.

How targets without a true partner (B, C) were handled:
- Shackleton's leftover edges count as wrong edges in the AUC and the aggregate.
- Hit rate skips Shackleton.
- The constrained null fixes Shackleton to zero positives (3⁴ = 81 labelings).
- B2 also drops Shackleton from the standardisation.

## Statistical power with 6 edges

- AUC moves in steps of 1/8.
- The plain null has 15 labelings and the constrained null 9, so the smallest possible p is 0.067 and
  0.111. No result can reach p < 0.05.
- The multivariate model fits perfectly in-sample (AUC 1.0) and scores 0.0 under leave-one-target-out,
  so it is meaningless.

## Pressure and wind

- Monotone transforms (log1p, rank) cannot change the per-feature results, because the Moon's value is
  a constant 0. This was confirmed.
- They only change the aggregate weighting: under log1p, the Earth–Moon aggregate goes from AUC 0.625 to
  0.75 (p 0.11, the minimum possible).
- Recommendation: exclude pressure and wind from Earth–Moon similarity, and model "no atmosphere" as
  its own feature.

## Caveats

- Very few edges: 6 for the new features, and only 1 true Earth–Moon edge left in B, B2 and C (smallest
  possible p 0.33).
- Mars data is stale; rerun once the merged Mars data is in.
- Body-dependent features: temperature sources differ, the Earth–Moon gap dominates the
  standardisation, insolation ignores terrain shadow, and planetary albedo spread reflects resolution.
- Circularity between latitude and the Haughton–Shackleton label.
- Multiple testing: about 24 features × 2 methods × 10 runs.
- Two of the five labels are team-chosen.

## Code changes and backwards-compatibility check

`analysis/feature_importance.py` gained optional `--data-dir`, `--out-dir`, `--targets`, repeatable
`--exclude-edge EARTH:TARGET`, `--relabel-false EARTH:TARGET` and `--transform PREFIX=log1p|rank`.

- **Exact nulls:** now enumerated over only the edges that have values for that feature. The committed
  script silently dropped labelings instead. This changes `p_plain` only for features with missing
  edges (e.g. 0.268 becomes 0.267, 0.548 becomes 0.600).
- **Generalised constrained null:** handles targets with zero positives.
- **New outputs:** `aggregate_distance.csv` and `aggregate_distance_edges.csv`.
- **Backwards compatibility:** with no arguments, the script reproduces all 4 committed CSVs
  byte-for-byte. This was checked on the preliminary inputs rebuilt from the snapshot.

## Reproduce

From `pipeline/`:

```bash
S="--data-dir analysis/runs/2026-11-14_earth-moon-temps/snapshot"
O=analysis/runs/2026-11-14_earth-moon-temps
python -m uv run python analysis/feature_importance.py $S --out-dir $O/full
python -m uv run python analysis/feature_importance.py $S --out-dir $O/earth_moon --targets apollo16,shackleton
python -m uv run python analysis/feature_importance.py $S --out-dir $O/ablation_A
python -m uv run python analysis/feature_importance.py $S --out-dir $O/ablation_B --exclude-edge haughton:shackleton
python -m uv run python analysis/feature_importance.py $S --out-dir $O/ablation_B2 --exclude-edge haughton:shackleton --exclude-edge sudbury:shackleton --exclude-edge atacama:shackleton
python -m uv run python analysis/feature_importance.py $S --out-dir $O/ablation_C --relabel-false haughton:shackleton
# transforms: add --transform pressure_mean_pa=KIND --transform wind_=KIND (KIND = log1p or rank),
# plus --targets apollo16,shackleton for the Earth–Moon variants; outputs in $O/transforms/{full,earth_moon}_{log1p,rank}
```

`ablation_A/` is byte-identical to `full/`.
