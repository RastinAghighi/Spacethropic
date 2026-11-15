# Analog search database

One DuckDB file, `out/analogs.duckdb`, rebuilt from the CSVs in `sources/`:

```bash
py -3.12 -m venv db/.venv && db/.venv/Scripts/python -m pip install -r db/requirements.txt
db/.venv/Scripts/python db/build.py      # ~1 s, ~7 MB
```

Scope: environment features only (no elevation match).

- **Earth is the search space**, so its cells are stored: Nevada at H3 resolution 7, 52,852 cells (~5.5 km² each).
- **The Moon and Mars are only ever the target**, one point at a time, so they aren't tiled. `lookup.py` interpolates their grids at the requested point on demand (instant after the first call). Tiling them would add rows, not information: the sources are 2° (Moon) and about 4° x 6° (Mars) grids.

| Table | What |
|---|---|
| `cells` | Earth: `body`, `h3` (UBIGINT, unique, stored in h3 order), `region`, centre `lat`/`lon`, `area_km2`, features, `src_points` |
| `grid_points` | The source grids per `body` (earth 10°, mars MCD, moon 2°), read by `lookup.py` |
| `features` | Name, label, unit, which bodies have it |
| `meta` | Build time, sources, interpolation, source file hashes |

Features use the column names from `planets.py` (`tsurf_mean`, `tsurf_min`, `tsurf_max`, `tsurf_range`, `tair_mean`, `tair_range`, `ps`, `wind`, `rh`, `sw`, `cloud`, `dust_aod`, `dust_conc`, plus Mars `tau`, `mtot`, `icetot`), in K, Pa, m/s. A feature a body doesn't have is NULL / None.

Values are bilinear between source grid points (longitude wraps; Earth cells use land points only), so they change smoothly across a region. `src_points` says how many grid points fed each cell. Finer grids drop in by replacing the CSVs in `sources/` and rebuilding.

```bash
db/.venv/Scripts/python db/lookup.py mars 18.44 77.45    # features at Jezero
```

## Pseudo-mirror search

`mirror.py` takes a Moon or Mars point and ranks Earth cells by how close their surface temperature profile is (mean, daily low, daily high, day-night range). A stand-in for the real matcher:

```bash
db/.venv/Scripts/python db/mirror.py moon -89.9 0       # Shackleton rim
db/.venv/Scripts/python db/mirror.py mars 18.44 77.45   # Jezero
```

The scores are low by design for the Moon: no Earth surface is as cold. Mars at Jezero scores higher.
