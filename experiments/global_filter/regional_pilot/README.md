# Spacethropic regional land-cover pilot (default H3 r7)

**2026-11-15 r7 integration:** the CLI accepts `--resolution` (default **7**);
rows and manifests use that resolution. Pass `--resolution 8` to reproduce the
historical commands/results below. The program name is now
`spacethropic_regional_pilot`. The 80% mission policy and categorical input
contract are unchanged; this is not the v2 global baseline.
The [separate global pipeline](../global_r7/README.md) implements that baseline,
with GHSL, MODIS fractions, checkpoints and uncertainty. Its real observations
and contour results are in [the run report](../global_r7/RUN_REPORT.md).
Current verification: 39 tests pass (28 regional, 11 global).

**Status (2026-11-15):** integrated under `experiments/global_filter/regional_pilot`
and tested locally on real H3 resolution-8 geometry with **synthetic** rasters
(25 passed, 1 skipped; see [TEST_RESULTS.md](TEST_RESULTS.md)). **No real
land-cover raster has been processed yet**: none exists in the repository.

It is standalone on purpose. It does not import or change `../pipeline`. The
0.05° global mask (`../pipeline/analysis/global_mask.py`) stays the reproducible
baseline, and the Drumheller NASADEM experiment (`research/nasadem_h3_pilot`) is
left as it is. The pilot reads one pre-existing local categorical GeoTIFF. It makes
no network, Git or download calls.

## Setup and tests

```powershell
cd C:\Dev\Spacethropic-integration\experiments\global_filter\regional_pilot
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt   # exact versions: requirements-lock.txt
.venv\Scripts\python -m pytest -q
```

`.venv/`, `data/` and `runs/` are git-ignored. Put input rasters in `data/` and
pilot outputs in `runs/`.

## Input raster contract

| Requirement | Why |
|---|---|
| Band 1 holds **original integer class codes**. Dynamic World `label` is 0–8. Esri/IO codes are 1, 2, 4, 5, 7, 8, 9, 10, 11 | RGB renders and probability bands are not class codes. Non-integer bands are refused |
| A **no-data value or mask is declared** (recommended: 255) | Earth Engine writes masked pixels as 0 unless `noData` is set, and Dynamic World 0 is *water*. An untagged DW raster is **refused**, unless `--nodata` is passed explicitly |
| A CRS is defined; north-up transform; nearest-neighbour resampling only | Class IDs must never be interpolated |
| Covers the H3 ring plus margin | Area outside the raster becomes `pct_unknown`, never a false zero |
| Real source metadata: asset id, version, **observation** window | Observation dates are not publication dates |

### First dataset: Dynamic World over Drumheller, summer 2025

This is not downloaded by any code here. To make it, run this export in the
[Earth Engine Code Editor](https://code.earthengine.google.com/). It needs a
Google account with Earth Engine access through a registered Cloud project, which is
free for noncommercial use. The bbox matches the NASADEM r8 pilot (W −112.8, S 51.40,
E −112.6, N 51.52), so the two can later be joined on the same H3 cell ids. The output
is about 1,400 × 1,350 px, a few MB.

```js
// GOOGLE/DYNAMICWORLD/V1, per-pixel mode of `label` over Jun-Aug 2025, plus valid-observation count.
var aoi = ee.Geometry.Rectangle([-112.80, 51.40, -112.60, 51.52], null, false);
var col = ee.ImageCollection('GOOGLE/DYNAMICWORLD/V1')
    .filterBounds(aoi).filterDate('2025-06-01', '2025-09-01');   // end exclusive
var label = col.select('label');
var img = label.mode().rename('label')                            // band 1: class code 0-8
    .addBands(label.count().rename('n_obs'))                      // band 2: informational
    .unmask(255).toUint8();                                       // 255 = no valid observation
print('images used', col.size());
Export.image.toDrive({
  image: img, description: 'dw_drumheller_2025JJA_label_mode', region: aoi,
  crs: 'EPSG:32612', crsTransform: [10, 0, 0, 0, -10, 0],          // UTM 12N, Sentinel-2 10 m grid
  maxPixels: 1e9, fileFormat: 'GeoTIFF', formatOptions: {cloudOptimized: true, noData: 255}
});
Export.table.toDrive({                                             // provenance: the actual scenes
  collection: ee.FeatureCollection(col.map(function (i) {
    return ee.Feature(null, {id: i.get('system:index'), time: i.date().format()}); })),
  description: 'dw_drumheller_2025JJA_images', fileFormat: 'CSV'
});
```

Save both files to `data/`. Then check the class codes and no-data value (both
should print), and run one cell, then seven:

```powershell
.venv\Scripts\python -c "import rasterio; r=rasterio.open(r'data\dw_drumheller_2025JJA_label_mode.tif'); print(r.crs, r.res, r.nodata, r.dtypes)"
.venv\Scripts\python pilot.py --raster data\dw_drumheller_2025JJA_label_mode.tif `
  --lat 51.4714 --lon -112.72 --ring 0 --scheme dynamic_world --mission mars_dry `
  --source-asset-id "GOOGLE/DYNAMICWORLD/V1 label mode, N images (data\dw_drumheller_2025JJA_images.csv)" `
  --source-version "Dynamic World V1, GEE export <export date>" `
  --observation-start 2025-06-01 --observation-end 2025-08-31 `
  --output runs\dw_drumheller_r0_001
```

If the check prints `None` for no-data, the pilot will refuse the file (masked
pixels are 255 from `unmask`, but untagged). Add `--nodata 255` in that case. Use
`--ring 1` and a new `--output` for seven cells. The coordinates are an example
inside the NASADEM AOI. They are not a validated NASA analog. The mode of labels is a
per-pixel summary over the stated window. It is **not** a class probability or a
calibrated consensus. A single cloud-free scene is also acceptable, with its own date
as the observation window. Dynamic World is CC BY 4.0, so attribute Google and the
World Resources Institute.

## Outputs

`<output>/cells/mission=<m>/decision=<d>/part-0.parquet` (hive layout; the
partition columns live in the directory names) and `<output>/manifest.json`.

- **Rows** keep every class percentage and `pct_unknown`, including for excluded
  cells. Each row also has the r8 H3 id, H3 spherical `cell_area_km2`, source
  provenance, observation dates (`date32`), threshold, mission, decision and reason.
  `ocean_pct`, `inland_water_pct`, `permanent_ice_pct` and `seasonal_snow_pct` are
  typed `float64` and always null, because this input cannot resolve them.
- **The manifest** records the cell list, decision counts, every Parquet file with
  its rows and sha256, the raster's sha256, CRS, bounds and no-data value, the class
  map, the mission's exclusion classes, and software versions.
- A run never overwrites. All validation and processing happens before the output
  directory is created, so a failed run leaves nothing behind.
- Read a run with `pilot.read_cells(<output>)`, or with any hive-aware reader
  (pyarrow.dataset, DuckDB, pandas) on `cells/`.

**Windows note:** on the development laptop, Windows Application Control blocks
pyarrow's `_dataset_parquet` DLL, in every Python environment. As a result,
`pyarrow.dataset` and directory reads through `pandas.read_parquet` fail there, while
single-file Parquet reads and writes work. The pilot therefore writes the hive files
one at a time, and `read_cells` reads them the same way.

## Decision rule (screening, uncalibrated)

Per cell, in order:
1. Observed area < `--min-observed` → `review`.
2. The mission's exclusion classes ≥ `--threshold` → `excluded`.
3. Exclusion classes + unknown ≥ threshold → `review`.
4. Otherwise → `retained`.

Both thresholds default to 80 %. Snow/ice is never an exclusion class. Water is
excluded for the dry, Moon and volcanic profiles, but it is never called ocean.

## Deliberate limitations

- This is an **exact pixel/hexagon polygon intersection** for small pilots (~2 s per
  r8 cell at 10 m; ring ≤ 5). It is not the tiled global implementation. Each overlap
  is measured in a cell-centred WGS 84 Lambert azimuthal equal-area projection. On
  real r8 cells, area is conserved to about 1e-7 %, and the result matches an
  independent H3 point-sampling estimate.
- Ocean vs inland water is **not** inferable from the class alone.
  `pct_water_unspecified` is kept, and the breakdown fields stay null.
- Seasonal snow vs permanent ice is **not** inferable from single-period land cover.
- Esri rangeland is **not** split into grass/shrub.
- Cells crossing the antimeridian are rejected; polar/dateline QA has not been done.
- A class label is not the probability that the class is correct. No threshold
  optimisation or confidence calibration has been done.
- No independent real-world validation has been run yet.

## Production architecture after regional validation

1. Keep the 0.05° coarse mask as the baseline.
2. Enumerate candidates in small H3 parent partitions (r4/r5), cover boundaries
   safely, and expand to r8 only where needed. Ocean interiors can use a compact
   exclusion mask instead of individual rows.
3. Read COG windows per raster tile or batch, compute area-weighted class fractions,
   and count missing or low-confidence observations.
4. Calibrate class confidence, mixed/coastal-cell handling and the 80 % threshold on
   labelled examples and adversarial controls.
5. Write partitioned Parquet that separates known exclusions, review cells and
   retained candidates. Record source versions, assets, QA and counts.

## Integration notes

- **H3 geometry:** `cell_polygon` is kept. It is tested to equal `h3.cells_to_geo`
  exactly, and its area is within 1 % of `h3.cell_area`. `../pipeline` has no
  cell-polygon helper; `grid.py` enumerates r7/r6 site disks scaled by body radius.
  The equivalent `h3grid.cell_boundary_lonlat` lives in the separate NASADEM
  experiment, and importing it would couple the two experiments.
- **Pixel assignment:** the pipeline's `aggregate.py` uses a pixel-centre rule for
  continuous features. This pilot uses exact area overlap, because categorical
  fractions near the 80 % threshold should not depend on where pixel centres fall.
- Source dataset notes and dates: [DATASET_DECISIONS.md](DATASET_DECISIONS.md).
  The original handoff spec: [CLAUDE_CODE_INTEGRATION_PROMPT.md](CLAUDE_CODE_INTEGRATION_PROMPT.md).
