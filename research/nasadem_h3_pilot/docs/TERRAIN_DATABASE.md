# Terrain database: teammate starting handoff

This milestone imports the checked-in NASADEM H3 CSV/run-summary pairs into
DuckDB 2.0.0 and exports candidate metadata to Zstandard-compressed Parquet.
It does not require the raw NASADEM ZIP. The recorded ZIP SHA-256 is **reported
provenance**, not a hash verified against a locally available raw asset.

Work on **`feat/terrain-database`**, package **`research/nasadem_h3_pilot/`**.
This is candidate metadata with **eligibility unknown**, not a working 3D search.
Use this page first; detailed guides: [integration contracts/status](INTEGRATION_STATUS.md),
[QGIS demo](QGIS_DEMO.md), [batch benchmark](TERRAIN_BENCHMARK.md),
[scientific pilot handoff](NASADEM_H3_PILOT_HANDOFF.md).

**Published:** `feat/terrain-database` was pushed to GitHub at commit `e6cd31e`.
Teammates with repository access can use the branch and follow this handoff.

`local/`, `.venv/` and `benchmarks/` are generated and ignored. **They do not
arrive after cloning.** Regenerate a database and exports from the tracked pairs:
`outputs/n51w113_drumheller_badlands_h3/h3_res{6,8}_cells.csv` and matching
`h3_res{6,8}_run_summary.json`. The tracked GeoJSON supplies map geometry.
No Earthdata login, downloaded ZIP, eligibility mask or matcher is required.

## PowerShell: setup

From the repository root:

```powershell
git switch feat/terrain-database
cd research/nasadem_h3_pilot
if (!(Test-Path src/spacethropic/db_cli.py)) { throw 'This checkout lacks the database milestone; request the published commit.' }
# Only if the virtual environment does not already exist:
py -3.12 -m venv .venv
$python = '.\.venv\Scripts\python.exe'
& $python -m pip install -r requirements-lock.txt
& $python -m pip install --no-deps -e .
& $python -c "import sys, duckdb; print(sys.version); print(duckdb.__version__)"
```

The lock file includes test dependencies and DuckDB. The package also declares
DuckDB as a runtime dependency. These commands were verified on Windows with
Python 3.12.10. The console entry point is `spacethropic-db`; the examples use
`python -m spacethropic.db_cli` so activation is unnecessary.
Install Python 3.12/the Windows Python launcher if `py -3.12` is unavailable.
The package declares >=3.10, but that is not a claim that every lock-file wheel
exists on every Python version. Stop if a native command returns nonzero.

## Import and list runs

Run from the pilot root, in the same PowerShell session. Pick a **new directory**
for a repeat walkthrough; do not replace a teammate's existing database/exports:

```powershell
$out = 'local/handoff_demo_01'
New-Item -ItemType Directory -Path $out -ErrorAction Stop | Out-Null
$artifacts = 'outputs/n51w113_drumheller_badlands_h3'
& $python -m spacethropic.db_cli --database "$out/terrain.duckdb" import `
  --pair "$artifacts/h3_res6_cells.csv" "$artifacts/h3_res6_run_summary.json" `
  --pair "$artifacts/h3_res8_cells.csv" "$artifacts/h3_res8_run_summary.json"
if ($LASTEXITCODE -ne 0) { throw 'Import failed; stop here.' }
$runs = & $python -m spacethropic.db_cli --database "$out/terrain.duckdb" list-runs | ConvertFrom-Json
$runs | Format-Table
$run6 = ($runs | Where-Object { $_.h3_resolution -eq 6 }).run_id
$run8 = ($runs | Where-Object { $_.h3_resolution -eq 8 }).run_id
if (!$run6 -or !$run8) { throw 'Expected one pilot run at each resolution.' }
# Run the import command again: both statuses become "existing"; counts stay unchanged.
```

Every `--pair` is a CSV followed by its JSON summary. All pairs in one invocation
are one transaction, including schema creation. Any failure rolls back all pairs
in that invocation. Earlier committed runs remain intact. A failed first import
may leave an empty DuckDB file, but no imported tables/data. Errors identify the
artifact pair and, for row errors, CSV line. Commands return exit code 1 on failure.

Expected counts (run IDs below are **examples from this CRLF Windows checkout**;
use the `$runs` values, never copy a hash as an environment-independent identity):

| Resolution | Run ID | Cells | Samples | Complete/partial |
|---|---|---:|---:|---|
| 6 | `37242be6a6dc92a78a4eb8000a01b57396bf5348ac0cb7f0094954d4a7dfc1be` | 12 | 311040 | 1/11 |
| 8 | `4ee8d757010c811d6a903d11343c47dddf8d26ec158b71430202d7ef970e36d0` | 296 | 311040 | 220/76 |

Run identity is SHA-256 of `schema:csv_sha256:summary_sha256`, using exact file
bytes. Paths do not affect identity. Whitespace, timestamps or other content
changes produce a distinct run. This intentionally favors immutable artifact
provenance over attempting to infer semantic equivalence. Always use `list-runs`
if artifact files have changed. Git stores the checked-in inputs with LF;
`core.autocrlf=true` checks them out here as CRLF. The tracked LF bytes instead
produce res-6 ID `d70c8281aae7caaa003799af1414a0992a29524031aecbf1962e451ec727f45e`
and res-8 ID `d7a8631c3031d7080cf94e9f4ef3713c32d108dfea6c54776a09efc72cef5883`.
Both variants import successfully and contain identical candidate values.

## Select resolution-8 terrain candidates (working command)

```powershell
& $python -m spacethropic.db_cli --database "$out/terrain.duckdb" select-terrain `
  --run-id $run8 --resolution 8 --limit 1000 `
  --min-exact-coverage 1 --min-valid-slope 1 `
  --columns centre_lat_deg centre_lon_deg slope_mean_deg coverage_fraction_exact_overlap coverage_fraction_pixel_centre n_valid_slope `
  | Set-Content -Encoding utf8 "$out/selected_res8.json"
if ($LASTEXITCODE -ne 0) { throw 'Selection failed; stop here.' }
$selection = Get-Content -Raw "$out/selected_res8.json" | ConvertFrom-Json
$selection.selected_count   # 220
$selection.status          # terrain_only_eligibility_unknown
```

The JSON is an envelope containing `candidates`, not a bare array. Each candidate
retains `h3_cell`, `run_id`, `h3_resolution` plus only the requested columns.
Predicates, sorting and LIMIT execute in SQL before Python fetch. These are
diagnostic terrain filters, not agreed matcher filters. `mask_version` and
unperformed elevation/matcher timings are null. Coverage >=1 is exact-overlap
coverage; do not substitute pixel-centre coverage or treat it as land eligibility.

## Export explicit runs

```powershell
& $python -m spacethropic.db_cli --database "$out/terrain.duckdb" export `
  --run-id $run6 --resolution 6 --output "$out/candidates_res6.parquet"
& $python -m spacethropic.db_cli --database "$out/terrain.duckdb" export `
  --run-id $run8 --resolution 8 --output "$out/candidates_res8.parquet"
```

**Full export does not inherit the selection filters.** These Parquets have
12 and **296** rows, including partial cells; the selection JSON has **220**.
The CLI has no filtered-Parquet export option. Each full run totals 311,040
assigned samples. A quick all-column read/uniqueness check, using the same env:

```powershell
& $python -c "import duckdb,sys; c=duckdb.connect(); p=c.read_parquet(sys.argv[1]); print('rows:',len(p.fetchall())); print(c.execute('SELECT count(DISTINCT h3_cell),sum(n_samples) FROM read_parquet(?)',[sys.argv[1]]).fetchall())" "$out/candidates_res8.parquet"
# rows: 296; [(296, 311040)]
```

Generated paths are `$out/terrain.duckdb`, `$out/selected_res8.json`, and
`$out/candidates_res{6,8}.parquet`. If another guide uses `local/terrain.duckdb`,
either import there explicitly or pass **your** database path. No generated
file should be assumed to exist on a teammate's machine.

Exports refuse to overwrite existing files; choose a new output path on a repeat
export. A nonexistent run or mismatched resolution is an error. Listing and
exporting open the database read-only.

There is one row per observed H3 cell, sorted by ID. All 35 existing CSV fields
are exported with explicit types, plus `run_id`, `eligibility_status`,
`csv_sha256`, `summary_sha256`, and `source_zip_sha256` (a list of reported hashes).
The original `source_collection` and semicolon-separated `source_granules` remain.
Counts use BIGINT, resolution INTEGER, IDs/text VARCHAR, booleans BOOLEAN, and
continuous values DOUBLE. Blank numeric fields become NULL. Blank quality flags
remain an empty string. Numeric units remain in column suffixes and full
definitions remain in the stored run-summary JSON.

**Partial cells are included by default.** Exact-overlap coverage and pixel-centre
coverage are separate. Pixel-centre and valid-derivative coverage can exceed 1
slightly because pixel footprints are assigned by centre. Neither is clamped.
`complete` describes footprint coverage, not eligibility or quality.

**Eligibility is always `unknown`.** Terrain coverage and Earth land eligibility
are separate. No vegetation/population/urban/ocean eligibility policy is inferred.
The data team's versioned mask is future input. The 3D matcher also needs a
separate spatial elevation-patch input after the search team supplies a real
accepted sample; these summaries cannot reconstruct elevation patches.

The res-8 zero-sample sliver `8812ebc0e1fffff` stays in
`terrain_runs.run_summary_json.results.sliver_cells`, with its area and count.
It does not become an observation or Parquet row.

## Real candidate row and map join

This is a complete projected row from `selected_res8.json` for the command above,
verified against a fresh import and Parquet read. Its run ID is the Windows CRLF
example; your discovered `$run8` may differ. The JSON envelope's status remains
`terrain_only_eligibility_unknown`.

```json
{
  "h3_cell": "8812ebc083fffff",
  "run_id": "4ee8d757010c811d6a903d11343c47dddf8d26ec158b71430202d7ef970e36d0",
  "h3_resolution": 8,
  "centre_lat_deg": 51.4354132265,
  "centre_lon_deg": -112.766278404,
  "slope_mean_deg": 2.7830072508,
  "coverage_fraction_exact_overlap": 1.0,
  "coverage_fraction_pixel_centre": 1.00127600455,
  "n_valid_slope": 1206
}
```

| Field | Meaning and units |
|---|---|
| `h3_cell` | String H3 identifier; preserve without numeric conversion |
| `run_id` | Byte-based import identity; observation key is `(run_id,h3_cell)` |
| `h3_resolution` | Integer H3 grid level, here 8 |
| `centre_lat_deg`, `centre_lon_deg` | WGS84 geographic cell centre, degrees |
| `slope_mean_deg` | Area-weighted mean Horn 3×3 native-grid slope, degrees |
| `coverage_fraction_exact_overlap` | Analysed footprint polygon overlap / full H3 cell area, dimensionless |
| `coverage_fraction_pixel_centre` | Assigned sample footprint area / full H3 cell area, dimensionless; may exceed 1 |
| `n_valid_slope` | Number of samples contributing valid slopes, integer |

Full Parquet also provides elevation/roughness in metres, areas in km²,
`slope_p50_deg`/`slope_p95_deg` in degrees, counts, flags and source references.
Elevation uses EGM96 heights; roughness/slope depend on the native 1-arc-second
3×3 baseline. These statistics cannot reconstruct a spatial elevation patch.

Join the candidate's `h3_cell` to `properties.h3_cell` (also `Feature.id`) in
`outputs/n51w113_drumheller_badlands_h3/h3_res8_cells.geojson`. The sample ID maps
to exactly one polygon. Join at matching resolution; do not compare by row order
or latitude/longitude rounding. Geometry represents the **full cell**, even for
partial observations. In the QGIS demo, all 296 polygons remain and
`selected_by_terrain_query` distinguishes 220 true / 76 false; eligibility is
`unknown` for all of them. [QGIS instructions and run discovery](QGIS_DEMO.md).

## Team handoffs: working today versus proposed integration

**Search can consume today:** the selected JSON envelope or full metadata
Parquet described above. Both preserve H3 identity and run; neither supplies an
eligibility mask, elevation grid, accepted matcher payload or similarity score.
The 4M-row benchmark is a batch baseline, not interactive search latency.

**Data team must supply real artifacts and rules:**

- Generated `exclusion_flags.tif`, `kept.tif`, `summary.json`, or a georeferenced
  Drumheller crop covering the full pilot polygons plus a pixel border. Current
  source contract: single-band uint8 GeoTIFF, EPSG:4326, 0.05° grid; flags bits
  1/2/4 = ocean/populated/vegetated, zero = kept; in `kept.tif`, one = kept.
- An immutable mask version, generator commit, input/output hashes, dataset
  versions and observation periods; actual CRS, transform, extent and band schema.
- Coverage, nodata and missing-source semantics. Current generator writes no
  nodata category and treats missing population as zero and missing NDVI as
  non-excluding. A crop-outside pixel is not automatically eligible. Supply
  validity products if unknown coverage must be preserved.
- Confirm whether inland water and urban exclusions are required; the current
  source has no separate urban rule and can retain large lakes.
- Choose centre sampling versus area overlap into H3 r8, eligible-fraction or
  any-exclusion threshold, full-cell versus patch extent and missing-cell policy.
  No such conversion/decision has been implemented in this package.

**Proposed only:** a converted H3 table with unique
`(mask_version,h3_resolution,h3_cell)` and eligibility status/reasons/coverage.
This is not an existing importer/schema/CLI. If supplying H3 rows instead of
TIFFs, provide their actual schema and verify uniqueness; do not assume these
proposed field names are already accepted.

**Search team still must supply:** an actual matcher branch/commit and invocation,
one Earth and one target elevation input that it successfully accepts (all files),
format/shape/CRS/spacing/units/datum/band order/registration/nodata, preprocessing
and padding, agreed candidate filters/limit, and a real output example carrying
the corresponding candidate ID. Specify when elevation is read and whether
missing patches are skipped or fail the request. No accepted example exists here.
The data team's elevation-r8 TIFF producer is not proof of matcher acceptance.

**Frontend caveat:** the inspected remote UI posts `{text,target}` to an absent
`/api/search` route and expects `{id,name,lat,lon,score,summary}` results. It drops
IDs absent from its bundled site catalogue. That UI response declaration is not
a matcher contract. See the pinned source trace in [integration status](INTEGRATION_STATUS.md).

### Copy-paste prompt for the data team's AI

```text
Start with research/nasadem_h3_pilot/docs/TERRAIN_DATABASE.md and
research/nasadem_h3_pilot/docs/INTEGRATION_STATUS.md on feat/terrain-database.
All following paths are relative to that pilot package. Check the actual commit;
do not assume ignored local/ files exist. Inspect the pinned global_mask.py
revisions and our real outputs/n51w113_drumheller_badlands_h3/h3_res8_cells.geojson.
Supply one real georeferenced eligibility crop plus summary/provenance, or real
unique H3-r8 decisions. State polarity, CRS/resolution, nodata/coverage, water and
missing-source rules. Obtain a decision on raster-to-H3 policy before coding it.
Verify one real join against the 296 pilot cells without duplicating candidates;
report kept/excluded/unknown counts and exact IDs. Keep terrain coverage separate
from eligibility. If an artifact or rule is missing, name it rather than mocking
a successful integration. Do not share credentials or overwrite pilot outputs.
```

### Copy-paste prompt for the search team's AI

```text
Read research/nasadem_h3_pilot/docs/TERRAIN_DATABASE.md and
research/nasadem_h3_pilot/docs/INTEGRATION_STATUS.md. All following paths are
relative to that pilot package. Rebuild the local database using the working commands
and discover run IDs; inspect src/spacethropic/db_cli.py and database.py. Res-8
has 296 full-export rows or 220 diagnostic selected rows, eligibility unknown.
Locate the actual matcher entry point and an accepted Earth/target elevation
sample; do not treat metadata summaries or the frontend API types as that sample.
Document exact input format/units/preprocessing and supply an ID-bearing result
example. Verify one real request using agreed SQL candidate filters, trace IDs
from h3_cell/run_id through elevation reads to results, and time each stage.
If mask policy, sample or code is missing, report the precise blocker. Preserve
the existing importer, full exporter and pilot artifacts.
```

## Fresh-environment documentation audit (November 15, 2026)

The audit tested a fresh Python 3.12 environment in the existing working tree;
it did not test a fresh Git clone.

Created `local/docs_audit_20261115/.venv` with `py -3.12 -m venv`, installed the
lock file and editable current package, then used the actual CLI against a new
`local/docs_audit_20261115/walkthrough/terrain.duckdb`. Nothing used the previous
`local/terrain.duckdb`. Imported both pairs, listed runs, selected res-8, exported
full res-8 Parquet and generated the QGIS layer. Results: 12/296 observations,
311,040 samples each, 220 selected, 296 unique Parquet rows and one polygon for
the real sample ID. The QGIS layer had 220 true / 76 false.

Also extracted **exact tracked LF input bytes** with `git show HEAD:<path>` into
`local/docs_audit_20261115/tracked_lf/` and repeated import/list/selection/export.
All counts and candidate values matched, with the different IDs documented above.
At the time of that documentation audit, the QGIS script failed against that LF database with
`run/resolution not found`: it then hard-coded the CRLF run ID and had no run-ID flag.
That limitation was subsequently fixed with metadata-based discovery and an
explicit `--run-id` option; [both database variants now pass](QGIS_DEMO.md#lf-and-crlf-regression-verification).
Existing database/selection tests also passed in the fresh environment:
**23 passed in 17.20 s**. The sample JSON above exactly matches the selected
candidate, both full Parquet exports have their expected counts/sample totals,
and edited local Markdown links resolve. Application code was unchanged.

## Tables and actual keys

| Table | Primary key | Other relationships |
|---|---|---|
| `source_metadata` | `source_id` | Unique `(collection, zip_sha256)` |
| `terrain_runs` | `run_id` | CSV/JSON hashes, input paths, resolution, complete original JSON |
| `run_sources` | `(run_id, source_id)` | Foreign keys to runs and sources |
| `h3_cells` | `h3_cell` | Resolution, centre and pentagon flag |
| `terrain_observations` | `(run_id, h3_cell)` | Foreign keys to runs and cells; remaining original CSV fields |

Source identity is SHA-256 of `collection:zip_sha256`. A source's metadata JSON
is the source section from its first imported run; each run retains its own full
source section (including AOI-dependent native spacing) in its complete summary.
H3 IDs intrinsically identify resolution, and imports validate that resolution.
Different AOIs or artifact versions coexist even when they share H3 cells. This
milestone does not merge their statistics or choose a preferred run.

## Validation and tests

The importer validates the v1 schema and exact column set, measurement units,
reported successful checks, source hashes/references, real H3 validity and
resolution, centre coordinates, pentagon flags, duplicate IDs, finite numeric
values, boolean spelling, count partitions, coverage ratios/status, summary
counts/areas, AOI shape and area, and sliver conservation. Required identity,
count and coverage fields cannot be blank; optional terrain statistics can be
NULL. It validates the artifact contract, not scientific accuracy against the
absent raw ZIP. It does not recompute pooled percentiles from summary rows.

```powershell
.\.venv\Scripts\python -m pytest tests/test_database.py -q
.\.venv\Scripts\python -m pytest -q
```

Database tests import both real pairs, repeat the import, compare real rows
field-for-field through Parquet (including res-8 coverage above 1), preserve the
full JSON/sliver, exercise NULL conversion, distinct runs and multi-pair rollback,
reject malformed artifacts, and exercise import/list/export. Synthetic
mutations are written only in pytest temporary directories. Raw-ZIP tests in the
older suite skip when that asset is unavailable.

`tests/test_terrain_selection.py` separately covers `select-terrain`. The audit
above verifies real command execution in a fresh Python environment, not a
fresh Git clone.

Generated `.duckdb`, `.duckdb.wal`, `.parquet`, virtual environments, caches and
editable-install metadata are ignored by Git. The local working artifacts in
this walkthrough appear under `$out` (`local/handoff_demo_01/`). Other detailed
guides may show the older `local/terrain.duckdb` defaults; those must be generated
separately or replaced by your explicit path.
