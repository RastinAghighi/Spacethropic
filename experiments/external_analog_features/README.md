# External analog features: first pass (approach E)

Joins two **published** analog datasets onto the terrain database's H3 cells
(`research/nasadem_h3_pilot`, DuckDB). Nothing is recomputed, and the pilot's
tables and code are not changed: everything new is an `ext_*` table.

| Source | Licence | Grid | What it adds per cell |
|---|---|---|---|
| [ShadowAstra Atlas](https://huggingface.co/datasets/ABRUBAB/shadowastra-atlas) | CC BY 4.0 | 0.5°, 80,206 land cells | 50 km terrain (slope histogram, height range), NASA POWER climate, MODIS surface temperature/NDVI/bare/snow, EMIT minerals, GLiM rock, volcano/crater context, learned Moon/Mars scores, match score for 18 targets |
| [Analog Atlas (nasc)](https://github.com/clickTwice26/nasc) | MIT | 0.5°, 88,648 land cells | 32 layers: MERRA-2/CERES/IMERG climate, deep soil temperature, evapotranspiration, UV, wind, ETOPO1 relief/slope, low-Sun and polar-night fractions, ice fraction, distances to ice/volcano/crater/playa/access, Köppen zone |

Credit: Team ShadowAstra, *ShadowAstra Atlas* (NASA Space Apps Challenge 2026);
Analog Atlas contributors. Both datasets cite their original NASA/ESA/USGS sources.

## How the link works

Both grids put cell centres at x.25 / x.75 degrees. Each H3 cell is linked to the
0.5° cell holding its centre (`ext_h3_link`), so the join is resolution-agnostic
(r6, r7, r8 all work). `ext_h3_features` stores the pre-joined result, one row per
H3 cell. **Rebuild it after every terrain import** (`build()`), or use `mode="live"`.

## Run

From the repository root, with the pilot's environment:

```bash
research/nasadem_h3_pilot/.venv/Scripts/python.exe experiments/external_analog_features/bench.py \
    --database research/nasadem_h3_pilot/local/external_bench/terrain.duckdb
```

The database is the pilot walkthrough's Drumheller import (r6 + r8). The script
copies it to `results/before.duckdb` and `results/after.duckdb`, downloads missing
source files into `data/` (git-ignored), and writes `results/latency.json`.

## Latency on the Drumheller sample (2026-11-15, 50 runs, median)

| Query (pilot function) | Rows | Before | After, live join | After, pre-joined |
|---|---:|---:|---:|---:|
| `terrain_selection`, r6 | 1 | 3.4 ms | 38.9 ms | 12.5 ms |
| `candidate_relation` (full), r6 | 12 | 11.0 ms | 48.6 ms | 22.6 ms |
| `terrain_selection`, r8 | 220 | 3.4 ms | 40.1 ms | 13.6 ms |
| `candidate_relation` (full), r8 | 296 | 11.9 ms | 50.1 ms | 24.9 ms |

- One-time cost: build 0.7 s; database 4.2 MB → 24.7 MB (the two source tables dominate).
- Pre-joined adds **~9–13 ms** per query; the live four-table join adds ~35–39 ms. Both return identical rows.
- Columns per row: 40 → 148. Part of the added time is fetching the extra 108 columns into Python.
- Checks: row counts unchanged, H3 cells still unique, every sample cell has ShadowAstra and nasc values.

## Limits of this first pass

- **0.5° values.** Every H3 cell inside one 55 km cell gets the same external values;
  the Drumheller sample (308 cells) touches only 2 ShadowAstra cells.
- **Earth only.** ShadowAstra publishes Moon/Mars data only for its 18 targets and 1° AI-twin cells,
  so there is nothing to join for Moon/Mars H3 cells yet.
- It is their data, not a re-run of their method, so it inherits their choices (e.g. 2023/2024 inputs,
  the 40/60 factor/learned blend in `match_score`).
- Not timed: scaling to the global r7 table (~16 M eligible cells); a coastal cell whose centre misses
  every published land cell gets NULL externals.
