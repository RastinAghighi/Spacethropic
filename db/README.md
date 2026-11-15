# Analog search database

One DuckDB file, `out/analogs.duckdb`, rebuilt from the CSVs in `sources/` in about 20 s:

```bash
py -3.12 -m venv db/.venv && db/.venv/Scripts/python -m pip install -r db/requirements.txt
db/.venv/Scripts/python db/build.py
```

Scope: Nevada, H3 resolution 7, environment features only (no elevation match).

| Table | Rows | What |
|---|---|---|
| `cells` | 52,852 | Earth H3 cells: `h3` (UBIGINT), `region`, centre `lat`/`lon`, `area_km2`, Earth features |
| `grid_points` | 19,920 | Source grids per `body` (earth 10°, mars MCD, moon 2°), all features, NULL where a body has none |
| `features` | 16 | Name, label, unit, which bodies have it |
| `meta` | | Build time, sources, interpolation, source file hashes |

Features use the column names from `planets.py` (`tsurf_mean`, `tsurf_min`, `tsurf_max`, `tsurf_range`, `tair_mean`, `tair_range`, `ps`, `wind`, `rh`, `sw`, `cloud`, `dust_aod`, `dust_conc`, plus Mars `tau`, `mtot`, `icetot`), in K, Pa, m/s.

Earth values are bilinear between the land points of the 10° grid (ocean neighbours dropped), so they change smoothly across the state. `cells.src_points` says how many grid points fed each cell. A finer grid drops in by replacing `sources/earth_features.csv` and `sources/earth_grid_elevation.csv`.

Example search, a Moon or Mars target's grid point, then Earth cells under limits:

```sql
SELECT * FROM grid_points WHERE body = 'mars'
ORDER BY (lat - 18.44)^2 + (lon - 77.45)^2 LIMIT 1;          -- Jezero

SELECT h3::VARCHAR, lat, lon, tsurf_range, rh, cloud
FROM cells WHERE rh < 40 AND cloud < 45
ORDER BY tsurf_range DESC LIMIT 20;
```
