# QGIS demo: terrain selection with eligibility unknown

First complete [the teammate handoff setup/import](TERRAIN_DATABASE.md).
`local/` is ignored: neither a database nor a demo map arrives after cloning.
The example below uses that walkthrough's database and a new output file.

The helper discovers the run using the existing `list_runs()` logic and stored
source/AOI metadata: res-8, `drumheller_badlands`, requested bbox
(-112.8,51.4,-112.6,51.52), collection `NASADEM_HGT.001`, tile `n51w113`.
Run IDs are byte-dependent, so LF and CRLF imports are both supported without
changing source data or line endings. If multiple runs match, the helper stops
and lists their IDs; choose one explicitly with `--run-id`. It never silently
chooses the first/latest run. An explicit ID must still match the pilot.

From the repository root, after the setup/import:

```powershell
cd research/nasadem_h3_pilot
$database = 'local/handoff_demo_01/terrain.duckdb'
.\.venv\Scripts\python -m spacethropic.qgis_demo `
  --database $database --output local/handoff_demo_01/drumheller_database_demo.geojson
```

For an ambiguous database, inspect the runs and copy the intended matching ID:

```powershell
.\.venv\Scripts\python -m spacethropic.db_cli --database $database list-runs
# Replace the placeholder with a matching ID printed above/by the helper:
.\.venv\Scripts\python -m spacethropic.qgis_demo `
  --database $database --run-id '<matching-run-id>' --output local/demo_explicit_run.geojson
```

Walkthrough output: `local/handoff_demo_01/drumheller_database_demo.geojson`.
The command refuses to overwrite an existing file. To rerun without replacing
it, pass a new `--output` filename. With no arguments the script instead expects
`local/terrain.duckdb` and writes `local/drumheller_database_demo.geojson`;
those defaults are not populated by the isolated walkthrough.

The script opens the specified database read-only and uses `terrain_selection()`.
It selects the discovered/explicit run at resolution 8, minimum exact coverage 1,
minimum valid slope count 1, limit 1000. The chosen run ID is reported on stdout
and retained in GeoJSON metadata and every feature's properties.
It fetches all 296 cells' attributes through the selector separately, so unselected
cells retain their database values. Only geometry comes from
`outputs/n51w113_drumheller_badlands_h3/h3_res8_cells.geojson`.

All 35 original CSV-contract fields plus `run_id` come from DuckDB. Added fields:

- `selected_by_terrain_query`: JSON boolean, 220 true / 76 false.
- `eligibility_status`: `unknown` on every polygon.

The ID join is one-to-one, selected IDs are unique, all selected IDs have a polygon,
and original full-cell geometry is unchanged. Coordinates are WGS84 longitude,
latitude. Slope is degrees, elevations/roughness metres, areas km², and coverage
fractions dimensionless. Pixel-centre coverage above 1 is preserved. These are
terrain filters, not an eligibility mask or matcher output.

Verified locally: 296 polygons, 220 selected, 76 unselected. SHA-256 checks before
and after generation confirmed the original database and all 14 pilot output
files were unchanged. The generated GeoJSON is ignored by Git under `local/`.

## LF and CRLF regression verification

Both databases were available and tested on November 15, 2026. From the pilot
root, these exact commands generated separate new files (choose a different
output directory to repeat them):

```powershell
.\.venv\Scripts\python -m spacethropic.qgis_demo `
  --database local/docs_audit_20261115/tracked_lf/terrain.duckdb `
  --output local/qgis_run_discovery_v1/lf.geojson
.\.venv\Scripts\python -m spacethropic.qgis_demo `
  --database local/terrain.duckdb `
  --output local/qgis_run_discovery_v1/crlf.geojson
.\.venv\Scripts\python -m pytest tests/test_qgis_demo.py -q
```

| Database | Discovered res-8 run ID | Polygons | Selected / unselected |
|---|---|---:|---|
| Fresh tracked LF audit | `d7a8631c3031d7080cf94e9f4ef3713c32d108dfea6c54776a09efc72cef5883` | 296 | 220 / 76 |
| Original CRLF | `4ee8d757010c811d6a903d11343c47dddf8d26ec158b71430202d7ef970e36d0` | 296 | 220 / 76 |

Verified unique H3 IDs, unchanged geometry, matching chosen run IDs on all
features, and unchanged SHA-256 for both databases and source geometry.
Three focused tests also cover LF/CRLF generation, ambiguity/error reporting,
explicit selection, rejection of res-6 and unrelated res-8 runs. Audit databases
are local artifacts, not fresh-clone prerequisites; these tests generate their
own temporary databases from tracked pilot inputs.
Full regression suite: **104 passed, 5 skipped** in 37.02 s. The skips concern
unavailable raw-ZIP/optional Rasterio checks. `git diff --check` passed.

## Open and style in QGIS

1. Drag the generated `local/handoff_demo_01/drumheller_database_demo.geojson`
   into QGIS (or the output path you chose). If asked for its CRS,
   choose **EPSG:4326 — WGS 84**.
2. Rename the layer **Terrain selection — eligibility unknown**.
3. Right-click the layer → **Properties → Symbology**. Choose **Categorized**.
4. Set **Value** to `selected_by_terrain_query`, then click **Classify**.
5. Colour the true category orange and the false category light grey. QGIS may
   display these boolean categories as true/false or 1/0. Use a thin dark outline.
   Any optional “all other values” category should have no features.
6. Click **Apply**, then **OK**. Right-click the layer → **Zoom to Layer**.
7. Open the attribute table: there should be 296 rows. Use **Select by Expression**
   with `"selected_by_terrain_query" = TRUE` to check that 220 rows are selected.
   Clear that interactive selection afterward to see the category colours.

Optional: identify a hexagon and inspect `h3_cell`, `slope_mean_deg`,
`coverage_fraction_exact_overlap`, `coverage_fraction_pixel_centre` and
`eligibility_status`. Keep the “eligibility unknown” label visible in any screenshot.
