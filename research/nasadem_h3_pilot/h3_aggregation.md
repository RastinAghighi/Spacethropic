# H3 aggregation of NASADEM terrain (DRUMHELLER-PILOT-03)

2026-11-14 · Granule `NASADEM_HGT_n51w113.zip` (SHA-256 `a414b5a2…fdfa`) · AOI `drumheller_badlands` (112.80–112.60°W, 51.40–51.52°N) · spacethropic 0.1.0, h3-py 4.5.0 (H3 C 4.5.0), numpy 2.5.4, Python 3.12.10

## Verdict

- The validated per-pixel terrain layers are now assigned to H3 cells and aggregated by one reusable implementation. The same code ran at resolution 6 (the planned worldwide baseline) and resolution 8.
- **The cell results reconcile exactly with the existing Drumheller summary** wherever reconciliation is mathematically possible. This holds at both resolutions, against both the stored `terrain_summary.json` and a fresh run, with 22/22 checks each:
  - Every one of the 311,040 samples is assigned exactly once.
  - Areas add up to 185.580753005 km², and counts add up.
  - Area-weighted cell means recompose the AOI means, and cell extremes give the AOI extremes.
  - Pooling the cells' samples reproduces the AOI percentiles.
- **No material differences.** The largest relative mean difference is at the 1e-12 level, i.e. float rounding.
- **No validated file changed.** The existing outputs, validation reports, pipeline modules and tests are byte-identical to before.

## 1. Method

Order of operations (`src/spacethropic/h3_pipeline.py`):

1. **Derivatives first.** `pipeline.analyze_granule` (unchanged) reads the granule and computes slope (Horn), TRI and 3×3 detrended roughness on the native 1″ grid. It reads a one-sample halo, so every AOI pixel has its full neighbourhood. Cells never recompute derivatives from cropped pixels.
2. **Assignment** (`h3grid.py`). Each sample goes to the H3 cell holding its centre: `latlng_to_cell(lat, lng, res)`, latitude first.
   - Samples are pixel-is-point, so the centre is the sample position.
   - H3 does **not** reject swapped arguments. `latlng_to_cell(-112.71, 51.46, 8)` returns a valid cell thousands of km away, so the order is tested explicitly.
   - Each resolution is assigned directly from the samples. H3 cells are not exactly nested: on a test grid some samples fall outside the res-6 parent of their res-8 cell.
3. **Aggregation** (`aggregation.py`, dataset- and H3-agnostic).
   - One stable sort groups samples by cell. The existing `stats.summarize` then runs on each cell's own samples, so the definitions are those of the AOI summaries:
     - means weighted by WGS 84 ground area;
     - weighted inverted-CDF percentiles from the cell's pooled samples, **never averages of percentiles**;
     - plain min and max.
   - Water (SWB = 255), void and undefined-derivative samples are excluded and counted.
4. **Geometry and coverage** (`h3grid.py`).
   - Each cell polygon is clipped exactly against the *analysed pixel footprint*: the union of the analysed pixels, half a pixel south-west of the requested bbox because of the half-open selection rule.
   - Areas use the WGS 84 cylindrical equal-area plane, consistent with the pixel areas.
   - The cells' exact overlaps, plus thin zero-sample slivers along the bounds, tile the footprint exactly. That makes the exact area budget checkable.

Per-cell coverage fields separate the two estimates:

| Field | Meaning |
|---|---|
| `cell_area_km2` | WGS 84 ellipsoidal area of the full hexagon |
| `h3_spherical_cell_area_km2` | `h3.cell_area` on H3's authalic sphere. This is 0.37% smaller here; the ratio runs from 0.9955 at the equator to 1.0074 at 70°N, so coverage fractions use the ellipsoidal area |
| `overlap_area_km2`, `coverage_fraction_exact_overlap` | exact polygon ∩ footprint area, and its fraction of the cell |
| `sampled_area_km2`, `coverage_fraction_pixel_centre` | area of the pixels whose centres fall in the cell (pixel-centre approximation) |
| `valid_coverage_fraction` | area with valid derivatives ÷ cell area |
| `coverage_status` | `complete` if the footprint covers the whole hexagon, else `partial` |

**Partial cells are never extrapolated.** Their statistics describe only the observed part. They carry `partial_coverage` in `quality_flags`, and the map colours only the observed part.

Quality flags:
- `partial_coverage`
- `water_excluded`
- `void_samples`
- `missing_derivatives`
- `no_valid_derivatives`
- the advisory quantisation floors from `scientific_validation.md` §5.1: median slope < 0.5°, or mean detrended roughness < 0.30 m.

## 2. Results

| | Resolution 6 | Resolution 8 |
|---|---|---|
| Cells with samples | **12** (1 complete, 11 partial) | **296** (220 complete, 76 partial) |
| Zero-sample sliver cells (overlap but no pixel centre) | 0 | 1 (48.7 m²) |
| Samples | 311,040 | 311,040 |
| Sampled area (km²) | 185.580753005 | 185.580753005 |
| Exact footprint area (km²) | 185.580753005 | 185.580753005 |
| Samples per cell | 3 – 59,102 | 3 – 1,211 |
| Mean slope range across cells (°) | 1.76 – 7.57 | 1.38 – 14.40 |
| Pixel-centre ÷ exact coverage, complete cells | 0.99996 (1 cell) | 0.9969 – 1.0030 |
| Pixel-centre − exact area, any cell | −0.0015 to +0.0029 km² | −0.0022 to +0.0022 km² |
| Global cell count at this resolution (`h3.get_num_cells`) | 14,117,882 | 691,776,122 |

- The Drumheller bbox is about 14 km × 13 km, so at resolution 6 (about 36 km² per cell) only one cell lies wholly inside it.
- Two res-6 cells cover under 2% of their hexagon. One cell holds only 3 samples. Use the coverage fields to filter such cells before any ranking.
- No cell in this AOI has water, voids or missing derivatives. A synthetic granule in the tests exercises those paths.
- At resolution 8, one cell (mean detrended roughness below 0.30 m) is flagged as at the quantisation floor.

Resolution 6 cells:

| H3 cell | Status | Exact coverage | Pixel-centre coverage | Samples | Elev. mean (m) | Slope mean / p50 / p95 (°) | TRI mean (m) | Detr. rough. mean (m) |
|---|---|---|---|---|---|---|---|---|
| `8612ebc07ffffff` | partial | 0.0228 | 0.0228 | 1,347 | 694.5 | 4.23 / 3.50 / 10.79 | 5.46 | 0.521 |
| `8612ebc0fffffff` | partial | 0.8086 | 0.8086 | 47,730 | 804.9 | 5.04 / 2.78 / 20.58 | 6.25 | 0.544 |
| `8612ebc27ffffff` | partial | 0.0141 | 0.0141 | 834 | 790.5 | 5.20 / 3.99 / 12.68 | 6.39 | 0.520 |
| `8612ebc2fffffff` | partial | 0.9192 | 0.9192 | 54,369 | 770.3 | 5.15 / 3.11 / 16.61 | 6.26 | 0.541 |
| `8612ebc47ffffff` | partial | 0.5763 | 0.5763 | 34,038 | 730.0 | 7.57 / 4.94 / 21.09 | 9.06 | 0.684 |
| `8612ebc57ffffff` | partial | 0.4875 | 0.4875 | 28,763 | 824.3 | 2.94 / 2.03 / 8.13 | 3.81 | 0.406 |
| `8612ebc67ffffff` | partial | 0.5150 | 0.5150 | 30,481 | 810.2 | 3.53 / 2.41 / 12.17 | 4.35 | 0.426 |
| `8612ebc77ffffff` | complete | 1.0000 | 1.0000 | 59,102 | 741.1 | 6.86 / 4.39 / 20.71 | 8.55 | 0.657 |
| `8612ebce7ffffff` | partial | 0.1169 | 0.1169 | 6,887 | 840.7 | 1.76 / 1.61 / 3.81 | 2.49 | 0.331 |
| `8612ebd4fffffff` | partial | 0.0974 | 0.0974 | 5,774 | 793.5 | 4.08 / 2.69 / 13.38 | 5.33 | 0.488 |
| `8612ebd57ffffff` | partial | 0.0001 | 0.0001 | 3 | 816.0 | 2.08 / 2.12 / 3.21 | 3.02 | 0.440 |
| `8612ebd5fffffff` | partial | 0.7044 | 0.7044 | 41,712 | 793.0 | 5.14 / 3.03 / 16.78 | 6.13 | 0.557 |

## 3. Reconciliation with the Drumheller summary

| Quantity | AOI summary | Re-composed from cells (res 6 and res 8) | Applicable? |
|---|---|---|---|
| Samples / valid counts (all 4 measurements) | 311,040 | 311,040 | yes (sum) |
| Water / void / derivative-undefined samples | 0 / 0 / 0 | 0 / 0 / 0 | yes (sum) |
| Valid area (km²) | 185.580753005 | 185.580753005 | yes (sum) |
| Elevation mean / min / max (m) | 779.32535362 / 670 / 861 | 779.32535362 / 670 / 861 | yes (area-weighted mean of means; extremes) |
| Slope mean (°) | 5.25905199974 | 5.25905199974 | yes |
| TRI mean (m) | 6.4662541822 | 6.4662541822 | yes |
| Detrended roughness mean (m) | 0.551973082082 | 0.551973082082 | yes |
| Slope p50 / p95 (°), pooled cell samples | 3.03258 / 18.20673 | 3.03258 / 18.20673 | yes (pooling) |
| Slope p50 / p95, **area-weighted average of cell percentiles** | 3.03258 / 18.20673 | res 6: 3.286 / 16.911; res 8: 4.277 / 12.882 | **no**, shown only to illustrate the error |

The last row is why the code never averages percentiles. Averaging cell medians overstates the AOI median by 8–41%, and averaging cell p95s understates the p95 by 7–29%. The size of the error depends on the resolution.

## 4. Verification

- **Tests.** `tests/test_h3_aggregation.py` adds 22 tests. The full suite gives 80 passed, 1 skipped (the optional rasterio cross-check, as before). Expected values come from hand calculations, numpy's own weighted percentiles, or H3's string and `cells_to_geo` APIs, not from the code under test. Coverage:
  - assignment against pointwise calls;
  - every pixel centre inside its own cell polygon and no other;
  - latitude/longitude order, including H3's silent acceptance of swapped arguments;
  - counter-clockwise GeoJSON rings;
  - exclusion of water, voids and undefined derivatives, with a synthetic granule whose AOI touches the tile's south-west corner;
  - hand-computed weighted means;
  - pooled versus averaged percentiles;
  - random cells against numpy;
  - input-order independence and byte-identical CSVs;
  - count and area conservation;
  - partial versus complete cells;
  - exact rectangle areas and clipping;
  - ellipsoid versus H3-sphere areas;
  - the straight-edge model versus great-circle edges (area differs by < 1e-7 at res 6);
  - non-nested H3 parents;
  - CLI reconciliation against the original terrain CLI;
  - real-data reconciliation and spot checks.
- **Mutation check.** The tests fail when any of these bugs is injected:
  - latitude and longitude swapped;
  - rows assigned south to north;
  - GeoJSON rings left in (lat, lng) order;
  - area weights ignored;
  - water not excluded.
- **Determinism.** A second run, with the resolutions requested in the other order, gives byte-identical CSVs and identical GeoJSON and run summaries apart from `generated_utc`.
- **Preservation.** SHA-256 hashes of all prior outputs, `scientific_validation.md`, `validation/` and the validated modules and tests are unchanged.

## 5. Limitations

1. **Pixel-centre assignment.** Boundary pixels go wholly to one cell. For complete res-8 cells this changes the sampled area by up to ±0.3%. In thin partial cells the relative effect reaches about 7%; it is recorded per cell.
2. **Partial cells.** They describe only their observed part. At res 6, 11 of 12 cells are partial because the AOI is small compared with a 36 km² hexagon. These are not representative res-6 values.
3. **1 m quantisation** sets a noise floor: slope below about 0.5° and detrended roughness below about 0.3 m.
4. **TRI and detrended roughness** depend on the 1″ spacing, the 19.3 m × 30.9 m pixel aspect and latitude. Slope is metric-correct but depends on its baseline. A common metric baseline is still needed before cross-latitude or Moon/Mars comparison (`scientific_validation.md` §5.2).
5. **Single granule.** Derivatives on tile south/west edges are undefined without neighbours, and cells crossing tile edges would be incomplete.
6. **NASADEM coverage** is about 60°N to 56°S. Part of the planned roughly 4.09 million land cells at res 6 lies outside that range and will have no NASADEM terrain.
7. **Other data issues:**
   - SWB misses some river channels (the Red Deer River is analysed as land).
   - Absolute height accuracy is unverified.
   - Cells crossing the antimeridian, and polar cells, raise `NotImplementedError`.

## 6. What scaling up would need (not implemented)

**Multi-granule processing**
- A granule index (tile id → ZIP) and a mosaic window reader. `analyze_granule` currently rejects AOIs that leave one tile.
- The half-open ownership rule already gives every sample exactly one tile, so per-tile assignments partition the samples.
- Cells that straddle tiles must merge contributions across tiles (see the streaming item).
- `source_granules` becomes the list of contributing tiles (the field is already `;`-separated).
- The coverage footprint becomes a union of tile rectangles. Clip per tile and sum, since tiles are disjoint.

**Incremental and streaming aggregation**
- Counts, areas, Σ(area·value) and min/max are mergeable. Keep per-cell accumulators keyed by H3 index and merge tile by tile.
- Percentiles are not mergeable. Either:
  - (a) buffer per-sample (value, area) only for *open* cells and finalise a cell once every tile that intersects its polygon has been processed. This is exact, with memory limited to the processing front.
  - (b) use mergeable fixed-bin weighted histograms or quantile sketches. These are approximate, with a stated bin error.
- Within a tile, assign and accumulate in row strips. Holding a whole 3601² tile's per-sample arrays (ids, sort and inverse indices, areas, four float32 layers, masks) needs roughly 0.7 GB, which is too much for this laptop.
- Persist per-tile partial accumulators so the job can restart.
- Assignment costs about 1 µs per sample (about 13 s per tile per resolution), so global runs should be parallelised by tile.

**Cross-tile terrain derivatives**
- Read a one-sample halo from the neighbouring tiles: the south neighbour's row 1, the west neighbour's column 3599, and the south-west corner sample.
- Pass the mosaic window to the unchanged `derive_layers`. This removes the 7,199 undefined edge samples per tile.
- Shared edge rows should be checked for agreement. NUM code 251 marks edges that NASADEM averaged between quads.
- Missing neighbours (ocean, no tile) remain NaN, as now.

**Datasets with other resolutions or data types**
- `aggregation.aggregate_samples` already takes any integer cell keys, positive per-sample areas, values and masks. `h3grid.assign_points` takes arbitrary lat/lon arrays.
- Projected grids (UTM, polar stereographic) need per-pixel centre coordinates and per-pixel areas (not per-row). That probably means a projection library, i.e. a new dependency.
- Pixels comparable to or larger than a cell (for example 1 km climate grids at res 8, 0.74 km²) cannot use pixel-centre assignment. They need area-weighted fractional overlap; `clip_ring_to_bbox` is the starting point.
- Categorical layers (land cover, geology) need class-fraction or mode aggregators, not means or percentiles.
- Integer or scaled products need explicit fill-value and scale-factor handling before the NaN-based validity rule applies.
- Time-varying products need a time key in the accumulators.

## 7. Reproduce

```powershell
.\.venv\Scripts\python -I -m pytest      # 80 passed, 1 skipped
$zip = "NASADEM_HGT_001-20261114_161823\NASADEM_HGT_n51w113.zip"
.\.venv\Scripts\python -I -m spacethropic.h3_cli $zip --bbox -112.80 51.40 -112.60 51.52 --name drumheller_badlands `
    --resolutions 6 8 --reference-summary outputs\n51w113_drumheller_badlands\terrain_summary.json
```

Outputs in `outputs/n51w113_drumheller_badlands_h3/`, for each resolution `N`:
- `h3_resN_cells.csv`: one row per cell, sorted by H3 index;
- `h3_resN_cells.geojson`: RFC 7946, [longitude, latitude];
- `h3_resN_run_summary.json`: methodology, provenance, checks and reconciliation;
- `h3_resN_mean_slope.png`: the map.

The run takes about 5 s.
