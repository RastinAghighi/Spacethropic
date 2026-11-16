# Shape search (Nevada test)

Click a Moon or Mars point → Earth cells whose terrain has nearly the same shape.

```bash
py -3.12 -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python prepare.py       # 20 s: Nevada GLO-90 tiles (dem/) -> out/nevada_patches.npz
.venv/Scripts/python soil.py wrb2006_points_0.02deg.csv   # 1 min: WRB soil map -> out/wrb_0.02deg.npz
.venv/Scripts/python build_index.py   # 2 s (~8 min for 10M cells): out/nevada_patches.npz -> out/index/, memory-mapped by the API
.venv/Scripts/python test_nevada.py   # 25 s: proofs -> figures/
echo GEMINI_API_KEY=... > .env        # analog reasoning (POST /compare); search works without it
.venv/Scripts/python -m uvicorn api:app --port 8787   # the frontend proxies /api/* here
```

`dem/`, `out/`, `cache/` and `geonames/` are local data and not committed. Without `out/index/` the API reads the patches file whole (fine for Nevada, not for 10M cells); rebuild the index whenever the patches file changes. For another patches file: `build_index.py <patches.npz> out/index`. The API also reads `../db/out/analogs.duckdb` for climate.

## Method (`shape.py`)

- **Unit: Earth-sized H3 res 7 everywhere.** A cell's shape is its elevation inside a disk of the res-7 cell area (5.16 km², radius 1.28 km) at 200 m pixels (137 px), mean height removed. The same physical disk is used on every body.
- **Distance:** RMSE in metres, minimised over 24 rotations of the target (every 15°). One matrix product per search.
- **Speed without losing matches:** RMSE ≥ |difference in relief std|, which rotation doesn't change. Candidates are visited in order of that bound and the search stops once it exceeds the current 50th-best exact RMSE. Identical results to brute force, checked below.
- **Filters go first:** `search(..., allowed=mask)` ranks only cells that pass the user's limits, so a strict filter never empties a top-50.

## Results on Nevada (52,852 cells)

| Target | Relief std | Best RMSE | Nevada median | Exact comparisons | Same as brute force |
|---|---:|---:|---:|---:|---|
| Shackleton rim, Moon | 31.5 m | 15.9 m | 30.4 m | 24,576 | yes |
| Apollo 15 Hadley Rille, Moon | 11.4 m | 2.1 m | 26.2 m | 8,192 | yes |
| Apollo 16 Descartes, Moon | 15.8 m | 9.7 m | 29.4 m | 20,480 | yes |
| Bagnold dunes, Mars | 31.0 m | 7.2 m | 28.2 m | 12,288 | yes |
| Phoenix lander, Mars | 10.0 m | 1.2 m | 27.0 m | 4,096 | yes |
| Viking 1, Mars | 2.1 m | 0.3 m | 33.0 m | 4,096 | yes |
| Viking 2, Mars | 16.9 m | 10.2 m | 33.4 m | 20,480 | yes |

Each search takes 13–42 ms.

Recovery test (300 random Nevada cells, rotated by a random angle, 2 m noise): the original cell ranks #1 in 85% overall, 99% for cells with > 30 m relief. When it doesn't, the top result fits at least as well as the original in 100% of cases; those are flat cells where many places are equally flat.

## Figures

- `figures/1_recovery.png`: rotated noisy queries and what they found; recovery rate by relief.
- `figures/2_<site>.png`: the target, turned to each match, above its top 5 Nevada matches on the same colour scale; RMSE histogram over all of Nevada; map of the top 50.

## Known limits

- 200 m pixels give 137 px per cell: it compares landforms at the 1–3 km scale, not boulders.
- Flat targets match many places equally well; relief tells little apart there, so the environment filters do the work.
- Earth DEM here is GLO-90 smoothed to 200 m; the teammate pipeline uses GLO-30 resampled to 200 m. Same grid, slightly different smoothing.
- Rotations only, no mirror images.
