# Terrain, eligibility and search integration status

**Start with [the teammate handoff](TERRAIN_DATABASE.md)** for branch/source
availability, fresh setup and import. This page is the detailed integration
record; its source-ref findings are from the pinned inspection below, not a
claim about uninspected later team changes. Ignored `local/` databases must be
regenerated after cloning. Run IDs in historical results are byte-dependent.

Reviewed the current `feat/terrain-database` workspace and fetched origin refs.
The importer/full Parquet exporter are preserved. The user confirmed that the
generated eligibility mask, matcher branch and accepted matcher sample are not
yet available. **No real search, mask join, elevation read or matcher invocation
can be verified.** The new command below is a terrain-only handoff probe, with
eligibility explicitly unknown. It does not invent a mask or matcher contract.

## Inspected revisions and evidence

| Ref | Pinned commit | Relevant path |
|---|---|---|
| `origin/data/cleaning` | `b073e8da9d5eaeb17aca9ee7db8e23ee853e0cbd` | `pipeline/` |
| `origin/feat/global-r8-filter` | `657c432695a06509a2f265ee71d8cf36483ef938` | `experiments/global_filter/pipeline/` |
| `origin/frontend` | `64e90c71140b1f7f3d0664f3228ff0bfbe8efac8` | `frontend/src/` |

The newer global-r8-filter commit is titled "Add global H3 r8 land-cover filtering
workspace", but the following files are byte-identical to data/cleaning:

- `analysis/global_mask.py`: Git blob `ef99f0cb6970cdd1981a7a666ade1f57e4628a39`.
- `analysis/global_mask_download.py`: `ebf9d4e6aabbc0af013279dedf10135fb5653a79`.
- `analysis/elevation_r8.py`: `c107f9b4d9f2c8d9b5dc592920d5208619c3c0b1`.
- Pipeline README: `44e41e737c33d666c35b7a4fc29473d284685297`.

Thus the available latest workspace still contains the **0.05-degree raster mask
implementation**, not an H3-r8 output implementation. The `r8 conversion + map`
commit title does not establish a raster-to-H3 eligibility conversion. We cannot
identify the revision of an unprovided generated asset; request its manifest.
Read the pipeline AGENTS/README and workspace CLAUDE instructions; no remote
pipeline/frontend files were modified or merged into this branch.

## Actual mask generator contract (source-verified, artifacts unavailable)

See `origin/data/cleaning:pipeline/analysis/global_mask.py:28` and `:136` through
the output writer; the global-r8-filter copy implements the same behavior.

| Property | Actual source behavior |
|---|---|
| Output directory | `pipeline/data/out/global_mask/` relative to the generator's pipeline root |
| `exclusion_flags.tif` | One uint8 GeoTIFF band; bit 1 ocean, 2 populated, 4 vegetated; **0 = kept** |
| `kept.tif` | One uint8 GeoTIFF band; **1 = kept**, 0 = excluded |
| Raster geometry | EPSG:4326, 7200 columns × 3600 rows; 0.05° pixels; origin (-180°,90°); north-to-south rows |
| Nodata | `None` on both outputs; no output unknown/invalid category |
| Ocean rule | Outside Natural Earth 1:10m land polygons using pixel-centre rasterization |
| Population rule | GHSL epoch 2020 counts summed by source pixel centre into output pixels; divide by authalic spherical area; exclude density **>=50 people/km²** |
| Vegetation rule | VIIRS Jan–Dec 2023 monthly peak NDVI, scaled by 1e-4; exclude peak **>=0.5**, unitless |
| Combine rules | Bitwise OR; any nonzero flag excludes; reasons overlap |
| Other outputs | `summary.json`, `map_before_land.png`, `map_after_filtered.png`, `map_reasons.png` |
| Summary fields | `inputs`, `thresholds.pop_per_km2_max`, `thresholds.ndvi_peak_max`, `pixel_deg`, `area_km2`, `people_on_kept_land`, `people_total`, `reduction_pct`, `sanity`, `sites` |
| Per-site summary fields | `id`, `kept`, `removed_by`, `pop_per_km2`, `peak_ndvi` (site pixel only, not H3 rows) |
| Version / H3 key | No explicit mask version, no `h3_cell`, no H3 resolution or per-cell decision |

Important missing-data behavior, directly from code:

- GHSL nodata and nonpositive values are replaced by zero. Output pixels with no
  population contributions therefore have zero population, not unknown.
- VIIRS values failing `a > -10000` are ignored; peak over valid months is used.
  All-missing months become NaN. `NaN >= 0.5` is false, so no vegetation exclusion
  is set. The summary may show `peak_ndvi: null`; the output flags do not preserve
  that missingness. A valid subset of months is not flagged as incomplete.
- Required input files being absent causes failure; it does not produce an
  unknown raster. Full output rasters have every pixel assigned kept/excluded.
- No separate urban layer or inland-water exclusion exists. The README explicitly
  warns that large lakes can remain kept; the Caspian is treated as ocean. These
  outputs do not satisfy a blanket large-water-body exclusion requirement.
- Missing H3 rows have **no defined semantics**, since no H3 table exists.

### Can we run a small Drumheller mask now?

No. `global_mask.py` has no AOI, bbox, input-root or output-root CLI arguments;
`W/H/RES/TRANSFORM`, input and output paths are fixed globally. `site_report()`
samples configured sites only after constructing the global arrays. There is no
local Drumheller raw-data cache, generated mask, or Rasterio in the pilot venv.
No synthetic raster was substituted for real data and no multi-GB authenticated
download was started.

Exact inputs expected under the source workspace's `pipeline/data/raw/global/`:

1. `ne_10m_land.geojson`.
2. A TIFF matching `GHS_POP_E2020_GLOBE_R2023A_4326_30ss*.tif` (the downloader uses
   `GHS_POP_E2020_GLOBE_R2023A_4326_30ss_V1_0.zip`).
3. Exactly twelve `vnp13c2/VNP13C2.A2023*.h5` files, containing the HDF5 dataset
   `//HDFEOS/GRIDS/VIIRS_Grid_monthly_VI_CMG/Data_Fields/CMG_0.05_Deg_monthly_NDVI`.

The downloader requires an Earthdata token configured locally by its owner.
Do not share the token in a handoff. Prefer requesting a generated georeferenced
crop plus provenance instead of downloading/rebuilding the global sources.

## Exact raster-to-H3 boundary still required

A raster cannot join directly to `terrain_observations.h3_cell`. The pilot has
296 observed resolution-8 cells, including 220 full-footprint cells. Coordinate
inspection shows their centres occupy **22 distinct mask raster pixels**. This
verifies the grids can be spatially related, not any eligibility value. Some
partial H3 centres lie outside the requested AOI: request a crop covering the
**full cell polygons plus a pixel border**, not just the original bbox.

The data team must select and version one conversion policy:

- **Centre sampling:** for a centre `(lat,lon)`, sample row
  `floor((90-lat)/0.05)`, column `floor((lon+180)/0.05)`; handle the global
  boundary/antimeridian explicitly. This gives one raster flag per cell but says
  nothing about excluded parts elsewhere inside it. The 22-pixel observation
  above uses this formula as coordinate QA only.
- **Area overlap:** intersect the full H3 polygon with raster-pixel polygons,
  preserve the bitmask classes, accumulate eligible/excluded/observed areas in a
  stated Earth area model, then apply an explicit agreed eligible-fraction or
  any-exclusion rule. Do not average categorical flag bytes or sum overlapping
  reason fractions as if disjoint.

Also decide whether decisions describe the full cell or a candidate patch, how
water/lakes are handled, how crop-outside/invalid/partially observed cells behave,
and whether source missingness should remain permissive or become unknown.
The current two output rasters cannot recover missing NDVI/population validity.
That requires validity products or generator changes by the data team.

**Proposed eventual join contract, not implemented:** one decision per
`(mask_version, h3_resolution, h3_cell)`, with status/reasons, observed fraction,
policy and provenance. Reject duplicate decisions rather than silently choosing
one. Join only an explicitly selected run/resolution/version; filter according
to the agreed status/missing policy inside SQL. Keep exact-overlap terrain
coverage separate from eligibility. Until supplied, no mask version can be
selected and no eligible-candidate count can be reported.

## Frontend request trace and matcher gap

This source is on origin/frontend, not the starter frontend currently checked
out. No `/api/search` route exists in the inspected refs.

1. `frontend/src/components/SearchBar.tsx:138`: trims text, makes
   `q = {text, target}`, calls `ui.startSearch(q)` and then `findCandidates()`.
2. `frontend/src/lib/search.ts:32`: POSTs JSON to `/api/search` with an abort
   signal. `AnalogQuery` is `{text: string, target: "moon"|"mars"}`. It contains
   no terrain run, resolution, mask version, patch, numeric filter or candidate ID.
3. `search.ts:15`: declared response `AnalogResult[]` fields are `id`, `name`,
   `lat`, `lon`, `score` (0..1), `summary`. No H3 resolution or elevation format.
4. `search.ts:82`: live results are mapped through the bundled `SITES` map by
   `result.id`. Unknown IDs are dropped; other returned metadata is not used to
   create candidates. A raw H3 ID would currently disappear unless catalogued.
5. Network failure or 404/405 raises `SearchUnavailableError`; `findCandidates`
   waits 1100ms and returns `sampleCandidates()` with `source: "sample"`.
   This fallback does not query the database or read elevation data.
6. `SearchBar.tsx:152` passes the resulting candidates/source to `ui.showResults`.

This traces the available source path; no live HTTP search was run. The API types
are a UI contract, **not a matcher input contract**. There is no evidence for
when a matcher reads elevation or how it carries a terrain H3 ID into results.
The inspected `pipeline/run.py` reads raster bands during feature aggregation;
`analysis/feature_importance.py` reads calibration Parquets and compares site
distributions. Neither is a 3D matcher/search request entry point.

The data team's `analysis/elevation_r8.py` is an elevation **producer**: GeoTIFFs
`data/out/elevation_r8/<site>.tif`, float32 band 1 `elevation_m` (metres), band 2
`source_index` (1-based source registry, zero unfilled), NaN nodata, site-local
azimuthal-equidistant grid. Pixels are square, about 858.68 m per side, based on
Earth's mean H3-r8 area. These are **not H3 cell rows**. README reports 71×71
grids; neither those TIFFs nor `data/export/elevation_r8_all_sites.zip` is tracked
in the inspected refs. We have no evidence a matcher accepts this format.

## Verified implementation available now

`database.terrain_selection()` / CLI `select-terrain` selects an explicit terrain
run/resolution, projects requested existing fields, always retains `h3_cell`,
`run_id`, `h3_resolution`, and applies optional exact-overlap/valid-slope-count
filters plus deterministic ordering and a required limit **inside SQL before
Python materialization**. Columns are allowlisted and values parameterized.
It avoids the batch benchmark's all-column/all-row retrieval. These are caller
chosen diagnostic filters, not agreed matcher filters or eligibility rules.

The response says `terrain_only_eligibility_unknown`, `mask_version: null`, and
uses null timings for unperformed elevation/matcher stages. It cannot be used
as proof of a completed search. Full candidate Parquet export remains unchanged.

PowerShell from the repository root:

Prerequisite: complete the [handoff setup/import](TERRAIN_DATABASE.md) first.
The example uses that walkthrough's new output directory; substitute your own.

```powershell
cd research/nasadem_h3_pilot
$database = 'local/handoff_demo_01/terrain.duckdb'
$runs = .\.venv\Scripts\python -m spacethropic.db_cli --database $database list-runs | ConvertFrom-Json
$r8 = ($runs | Where-Object { $_.h3_resolution -eq 8 }).run_id
.\.venv\Scripts\python -m spacethropic.db_cli --database $database select-terrain `
  --run-id $r8 --resolution 8 --limit 1000 --min-exact-coverage 1 --min-valid-slope 1 `
  --columns centre_lat_deg centre_lon_deg slope_mean_deg coverage_fraction_exact_overlap coverage_fraction_pixel_centre n_valid_slope
$r6 = ($runs | Where-Object { $_.h3_resolution -eq 6 }).run_id
.\.venv\Scripts\python -m spacethropic.db_cli --database $database select-terrain `
  --run-id $r6 --resolution 6 --limit 1000 --min-exact-coverage 1 --min-valid-slope 1 `
  --columns centre_lat_deg centre_lon_deg slope_mean_deg coverage_fraction_exact_overlap coverage_fraction_pixel_centre n_valid_slope
.\.venv\Scripts\python -m pytest tests/test_terrain_selection.py tests/test_database.py -q
.\.venv\Scripts\python -m pytest -q
```

Field types/units in this diagnostic: `h3_cell`/`run_id` strings, resolution
integer; centres WGS84 degrees, slope degrees; coverage fractions dimensionless;
`n_valid_slope` integer samples. No grid, patch, mask or similarity score is emitted.

Measured one probe per resolution (Python 3.12.10 / DuckDB 2.0.0, existing real
database, warm filesystem state). Times include run validation, query binding,
SQL filtering and Python fetch/dictionary construction; exclude connection,
process startup and JSON printing. They are not search-latency benchmarks.

| Resolution | Terrain observations | After exact coverage >=1 | After valid slope count >=1 / returned | Query seconds |
|---|---:|---:|---:|---:|
| 6 | 12 | 1 | 1 | 0.0068902 |
| 8 | 296 | 220 | 220 | 0.0071453 |

Selected ID lists exactly match independent filtering of the real pilot CSVs,
with no duplicates. Res-6 returns `8612ebc77ffffff`; first res-8 IDs are
`8812ebc081fffff`, `8812ebc083fffff`, `8812ebc085fffff`. The latter includes a
pixel-centre coverage above 1, preserved without clamping. Local ignored records:
`local/integration_trace_v1/{selection_res6,selection_res8,verification}.json`.
Before/after hashes verify the existing DB and both full Parquets are unchanged.
Eligible counts, matcher-returned IDs and elevation/matcher timings are **not
available**, rather than zero measurements.

Verification: selection/database focused tests **23 passed**; full pilot suite
**101 passed, 5 skipped** in 32.72 s (unavailable raw-ZIP/optional Rasterio checks).
`git diff --check` passed. Probe JSON stays in the ignored pilot `local/` directory.

## Exact next handoffs

**Data team:** supply `exclusion_flags.tif`, `kept.tif`, `summary.json` (or a
georeferenced Drumheller crop covering all pilot polygons), immutable version,
source hashes/dates and generator commit. Confirm band polarity/flags and whether
to preserve current permissive missing-source behavior. Supply validity bands if
unknowns must remain distinguishable. Choose centre versus overlap conversion,
threshold, boundary coverage, missing/outside-cell policy and lake/urban rules.
Alternatively supply already converted resolution-8 rows and their exact schema,
unique key and decision policy. A filename/branch title alone is insufficient.

**Search team:** supply actual entry point/commit, invocation and dependencies;
one accepted Earth candidate and target input with all associated files; actual
format, shape, CRS, spacing, units/datum, band names, registration/orientation,
nodata/validity, preprocessing and padding requirements; candidate filters/limit;
and one expected output showing candidate IDs. State where elevation is read and
whether candidates with missing patches are skipped or fail. Until that sample
arrives, do not convert summaries into guessed elevation arrays.

**Frontend/API owner:** decide how explicit terrain run/resolution/mask version
are supplied/configured, how IDs map to H3/patches, and how live candidates absent
from bundled `SITES` survive rendering. Preserve backend IDs rather than silently
dropping unknown sites. No frontend/API behavior was changed in this milestone.
