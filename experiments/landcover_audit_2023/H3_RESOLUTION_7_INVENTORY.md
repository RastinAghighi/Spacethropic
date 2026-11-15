# H3 resolution 7: where resolution 8 is hard-coded

The team has switched the global H3 system from resolution 8 to **resolution 7** (database size,
processing speed, storage). This file lists every place found where the resolution is fixed, so
the change can be made in a **separate integration task**. Nothing here was edited.

**This land-cover audit does not depend on H3.** It works on the 0.05° raster grid (the grid of
the global mask) and reports areas in km². The global H3 generation, geographic filtering and
terrain-database stages must all move to resolution 7 later.

Scanned on 2026-11-15 (`grep` for `h3_res`, `H3_RES`, `latlng_to_cell`, `polygon_to_cells`,
`average_hexagon_area`, `cell_to_children`, `get_num_cells`, `resolution`, `r8`/`res8` in `.py`,
`.sh`, `.yaml` and `.toml` files, then each hit read in context). Data folders, `.venv`, caches
and frontend texture "resolution" code were excluded.

## Resolution facts (h3-py 4.5.0)

| | r6 | **r7** | r8 |
|---|---|---|---|
| Mean hexagon area | 36.129 km² | **5.161 km²** | 0.7373 km² |
| Mean edge length | 3.725 km | **1.406 km** | 0.531 km |
| Cells on the whole globe | 14,117,882 | **98,825,162** | 691,776,122 |
| Side of a square with the mean area | 6,010.75 m | **2,271.85 m** | 858.68 m |

An r7 cell is about 7× the area of an r8 cell, so the r7 Earth table has about 1/7 of the rows.
The 0.05° land-cover pixels behind the mask are 30.9 km² at the equator. That is still about
6× an r7 cell, so the mask stays coarser than the cells at both resolutions.

**Naming trap:** in `contours_r8.py` the levels `8x`, `4x`, `2x` and `full` are Copernicus DEM
overview levels (240 / 120 / 60 / 30 m pixels), **not** H3 resolutions. The `8x_i20m` folder
names mean "8x overview, 20 m contour interval".

## 1. Teammate branch `data/cleaning` (commit `475bf4e`, worktree `C:\Dev\Spacethropic-branch-review\data-cleaning`)

This branch has the global H3 generation, the geographic filter (v2 mask) and the per-hexagon
terrain stage.

| File:line | What is fixed at r8 | Stage | Change needed |
|---|---|---|---|
| `pipeline/analysis/contours_r8.py:65` | `H3_RES = 8`, used by `polygon_to_cells(shape, H3_RES)` at `:205` | **Global H3 generation** | Set to 7, or better, read it from config / CLI |
| `pipeline/analysis/contours_r8.py:66-67` | `REMOVE_AT = 0.9`, `SAMPLE_DEG = 0.001`: each hexagon's removed-area share is sampled against `global_mask_v2/kept.tif` | **Geographic filtering** | The rule still works at r7 (an r7 cell holds about 420 samples at 0.001°). Re-check the 0.9 threshold: an r7 cell mixes more kept and removed ground |
| `pipeline/analysis/contours_r8.py:61` | Output root `data/out/contours_r8_v2` | Output path | New root (e.g. `contours_r7_v2`) so r8 results are not mixed with r7 |
| `pipeline/analysis/contours_r8.py:324` | Manifest `"h3_res": H3_RES` | Output metadata | Follows the constant automatically |
| `pipeline/analysis/contours_r8.py:79-89` | `HEX_SCHEMA` / `LINE_SCHEMA`: key `hex` (uint64). There is **no resolution column**; the resolution is only in the manifest | Output schema | Decide whether to add an `h3_res` column. Don't rename the schema blindly: `hex_terrain.py`, `hex_features.py` and the downstream README read it |
| `pipeline/analysis/contours_r8.py` (module name) | Imported as `contours_r8` by `contours_planet.py:51` and `hex_terrain.py:34` | Code structure | Rename only together with the importers |
| `pipeline/analysis/hex_terrain.py:100` | `polygon_to_cells(shape, earth.H3_RES)` (inherits r8) | Terrain per hexagon | Follows `H3_RES` |
| `pipeline/analysis/hex_terrain.py:1, :47-48, :224` | Docstring "use R8 resolution as final" (a recorded user decision, now superseded); input paths `contours_r8_v2/8x_i20m`, `4x_i20m`; provenance text "per R8 hexagon" | Terrain per hexagon | Update the paths and text; record the new decision |
| `pipeline/analysis/hex_features.py:43` | Input paths `contours_r8_v2/8x_i20m`, `contours_r8_v2/4x_i20m` | Feature columns per hexagon | New r7 paths |
| `pipeline/analysis/contours_planet.py:57` | `AREA_M2 = h3.average_hexagon_area(8)`: Moon/Mars use regular hexagons sized like Earth's r8 cell (edge 532.7 m) | Moon/Mars hexagon generation | Use 7, giving 5.161 km² and an edge of about 1,409 m for a regular hexagon of that area |
| `pipeline/analysis/contours_planet.py:1-4, :291` | Docstring and manifest rule "Earth H3 r8 mean cell size, unchanged" | Metadata | Text follows the constant |
| `pipeline/analysis/elevation_r8.py:36-38, :66, :83, :88` | `R8_AREA_KM2 = h3.average_hexagon_area(8)`, so 858.68 m pixels; outputs `elevation_r8/`, `elevation_r8_all_sites.zip` | Elevation export for sites | 7 gives 2,271.85 m pixels; new output names |
| `pipeline/analysis/queue_2026-11-15.sh:31`, `queue_features2.sh:3` | Run `contours_r8.py`; log in `contours_r8_v2/` | Job queue | Update after the scripts |
| `pipeline/sites.yaml:8-10` | `earth: h3_res 7`, `moon/mars: h3_res 6` | Calibration pipeline (per-site cells via `config.py:20,45` → `grid.py:17-23`, `aggregate.py:30-31`, `merge.py:127`) | **Earth is already r7, and the code reads it from config.** Moon/Mars use r6: decide whether they follow "Earth-r7 size" |
| `pipeline/AGENTS.md`, `pipeline/README.md` | Describe r8 as the final grid ("R8 contour pipeline", "Elevation at Earth-r8 size") | Docs | Update when the code changes (user's standing rule) |

## 2. Integration repo, branch `feat/global-r8-filter` (commit `75a9cff`, `C:\Dev\Spacethropic-integration`)

| File:line | What is fixed at r8 | Stage | Change needed |
|---|---|---|---|
| `experiments/global_filter/regional_pilot/pilot.py:68` | `ring_cells(..., resolution: int = 8)`; no `--resolution` CLI option (`:384-400`) | **Geographic filtering** (H3 land-cover prefilter pilot) | Add a `--resolution` option, defaulting to 7 |
| `experiments/global_filter/regional_pilot/pilot.py:324` | Every Parquet row is written with `resolution=8` | Output data | Use the run's resolution. The schema at `:228` already has a `resolution` int8 column, so only the value changes |
| `experiments/global_filter/regional_pilot/pilot.py:353-355` | Manifest `program="spacethropic_r8_regional_pilot"`, `h3_resolution=8` | Output metadata / schema | Use the run's resolution; decide whether the program name changes (consumers may key on it) |
| `experiments/global_filter/regional_pilot/pilot.py:1` | Docstring "H3 r8" | Docs | Text |
| `experiments/global_filter/regional_pilot/tests/test_integration.py:42, 68, 72, 94, 111, 124, 166, 190, 230` | Tests build r8 cells and assert `get_resolution(c) == 8` and `manifest["h3_resolution"] == 8` | Tests | Parametrise over 7 (keep 8 if both stay supported) |
| `experiments/global_filter/pipeline/analysis/elevation_r8.py:36` | Same as section 1 (copy) | Elevation export | Same change |
| `experiments/global_filter/pipeline/sites.yaml:8` | Earth `h3_res: 7` (already r7) | Calibration pipeline | None for Earth |
| `research/nasadem_h3_pilot/src/spacethropic/h3_pipeline.py:384-387` | Run-summary metadata `"planned_global_baseline": {"resolution": 6, "global_cells_including_ocean": h3.get_num_cells(6)}` | Terrain metadata | Now outdated: it should say 7 |
| `research/nasadem_h3_pilot/src/spacethropic/h3_cli.py:29` | `--resolutions` default `[6]` | Terrain H3 aggregation | Default to 7. The functions themselves take any resolution (`h3grid.validate_resolution`) |
| `research/nasadem_h3_pilot/outputs/*/h3_res6_*`, `h3_res8_*` | Committed pilot artefacts at r6 and r8, no r7 | Pilot outputs | Regenerate at r7 when needed (not part of this task) |
| Branch name `feat/global-r8-filter` | | Git | Rename or replace when integrating |

## 3. Terrain-database branch (commit `6abae2c`, worktree `C:\Dev\Spacethropic-branch-review\terrain-database`)

Most of the database code already handles **any resolution**:
- `database.py:22-23, 39` stores `h3_resolution` per cell and per run.
- `database.py:103, 124, 163` checks `h3.get_resolution(cell) == res`.
- `db_cli.py:23, 27` requires `--resolution` (0–15).

These need no change. The hard-coded parts:

| File:line | What is fixed | Stage | Change needed |
|---|---|---|---|
| `src/spacethropic/benchmark.py:83` | Global benchmark IDs from `h3.cell_to_children(base, 6)` (all 14.1 M r6 cells) | **Terrain-database sizing** | Re-benchmark at r7 (98.8 M cells globally, about 7× r6) to size the r7 database |
| `src/spacethropic/benchmark.py:270` | Argument check against `h3.get_num_cells(6)` | Benchmark | 7 |
| `src/spacethropic/qgis_demo.py:14, :85` | `h3_res8_cells.geojson` and `"h3_resolution": 8` | QGIS demo | Point at an r7 run |
| `src/spacethropic/h3_pipeline.py:385-386`, `h3_cli.py:29` | Same as section 2 (r6 "planned baseline", default `[6]`) | Terrain | 7 |
| `tests/test_database.py:44, 47, 62, 110`; `test_qgis_demo.py:17, 26, 45, 64`; `test_terrain_selection.py:17`; `test_h3_aggregation.py:114-169, 293, 466` | Fixtures at r6 and r8 | Tests | Add r7 fixtures (they come from pilot artefacts, so these need an r7 pilot run first) |
| `docs/TERRAIN_DATABASE.md:57-132, 231-263`, `TERRAIN_BENCHMARK.md:64-72`, `INTEGRATION_STATUS.md:21-196` | Commands and run IDs for r6/r8 | Docs | Update after the r7 run |

## 4. Not affected

- **This experiment** (`experiments/landcover_audit_2023`): 0.05° raster statistics, no H3.
  The report converts kept area into rough r7 cell counts (area ÷ 5.161 km²), for scale only.
- Frontend: no H3 use found (`frontend/src`. The "resolution" hits are texture/GPU adaptive
  resolution).
- `global_mask.py` / `global_mask_v2.py` / `landcover_fractions.py`: pure 0.05° rasters (`RES = 0.05`
  is degrees, not H3). The mask itself doesn't change with the H3 resolution. Only the step that
  turns it into hexagons does (`contours_r8.py` `REMOVE_AT`).
