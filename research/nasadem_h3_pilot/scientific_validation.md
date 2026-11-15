# Scientific validation of the NASADEM terrain pipeline (DRUMHELLER-PILOT-02)

2026-11-14 · Granule `NASADEM_HGT_n51w113.zip` (SHA-256 `a414b5a2…fdfa`) · spacethropic 0.1.0 (unchanged) · Python 3.12.10, numpy 2.5.4

## Verdict

- **The computations are correct.** An independently written reference reproduces every pipeline pixel on the full tile (12.96 M samples) and on the Drumheller AOI (311,040 samples):
  - Elevations are bit-identical.
  - The other layers differ only by float32 storage rounding: slope ≤ 1.9e-6°, TRI ≤ 3.8e-6 m, detrended roughness ≤ 2.4e-7 m.
  - All 88 published summary statistics agree within the stated tolerances. The largest difference is 3.8e-6 m (Drumheller TRI maximum).
- **No correctness problem was found, so no pipeline code changed.** The stored results in `outputs/` remain valid. A re-run of both README examples reproduced them exactly.
- **The main uncertainty is in what the numbers mean, not in the code:**
  - 1 m elevation quantisation puts a floor under slope and roughness.
  - The 3×3 window on 19.3 m × 30.9 m pixels makes TRI and detrended roughness depend on scale, aspect and latitude.
  - Source accuracy could not be assessed (no ground truth).
- **The pipeline is ready for geographic aggregation, with the conditions in §6.**

## 1. Checks and how independent they are

The reference is `validation/independent_check.py`, written for this task. Its reference part imports nothing from `spacethropic`. The pipeline is imported only at the end, to compare against it.

| Area | Reference method | Pipeline method | Independence |
|---|---|---|---|
| ZIP and HGT decoding | Own ZIP central-directory parser, raw `zlib` inflate, CRC-32 check; big-endian decoding with `struct` / `array.byteswap` (no numpy, no `zipfile`) | `zipfile` + numpy `>i2` | Independent code, same format spec |
| AOI rows/cols | Integer arc-second inequalities | Float comparisons with 1e-9° tolerance | Independent |
| dx, dy | ECEF chord between neighbouring sample centres | Radii of curvature M, N | Independent formula |
| Cell area | Exact ellipsoidal quadrangle (authalic latitude) | M·N·cosφ·Δφ·Δλ | Independent formula |
| Slope | Horn written with named neighbours a–i, chord spacings | Vectorised per-row Horn | Independent code, same definition |
| TRI | Explicit 8-neighbour sum | Loop over offsets | Same definition |
| Detrended roughness | Explicit 9×9 least-squares projector, in index coordinates **and** in true metric (trapezoidal) window coordinates | Closed-form orthogonal decomposition | Independent algebra |
| Statistics | `numpy.average`, `numpy.percentile(weights=…, method="inverted_cdf")` | `stats.summarize` | Independent implementation |
| Edges and halos | Layers computed once on the whole 3601² granule, then sliced | AOI read with a 1-sample halo, 512-row strips | Independent of the halo/strip logic |

What these checks do **not** establish:

- **Shared format interpretation.** Big-endian int16, row 0 = north edge, south-west-corner tile naming and SWB 255 = water all come from the same NASADEM User Guide.
- **Shared definitions.** The metric definitions are the same by design, and numpy and the WGS 84 constants are shared.
- **Same author.** The same engineer (Claude) wrote the pipeline and the reference, so a shared conceptual error would not be caught.
- **No third-party reader.** A GDAL/rasterio comparison would provide one, but it was not possible because Windows Smart App Control blocks GDAL's DLLs. That control was not bypassed.
- **Reuse, not independent checks.** The 46 pre-existing tests were written with the pipeline, and the reproducibility re-run uses the same code.

## 2. Tolerances

| Quantity | Tolerance | Basis |
|---|---|---|
| Elevation per pixel; elevation min/max/percentiles; all counts | exact | Integer heights |
| Slope, TRI, roughness per pixel | 1e-5 (° or m) absolute | float32 storage: half an ulp is 1.9e-6 at 45° and 3.8e-6 at 72 m |
| Mean and s.d. of float32 layers | 1e-6 relative | Mean of float32-rounded values |
| Min/max/percentiles of float32 layers | 1e-5 absolute | One float32 sample |
| Elevation mean/s.d., dx, dy, cell and AOI areas | 1e-9 relative | Formula differences are 1e-13 to 4e-10 |
| Pipeline roughness vs metric-window reference | 5e-4 m absolute | Analytic bound for the index-plane approximation (§3.5) |

## 3. Results on the real tile (40 of 40 checks passed)

### 3.1 Reader
- All three ZIP members inflate with `zlib`, and their CRC-32 values and sizes match the archive's index.
- All 12,967,201 `.hgt` samples are identical between the standard-library decode and the pipeline reader. The `.num` and `.swb` layers are identical too.
- A deterministic sample of 3,007 points gave **0 mismatches**. Each point was decoded with `struct.unpack_from(">h")` at byte offset 2·(row·3601 + col) and compared with the pipeline's float elevations.
  - The points are 2,000 tile-wide and 1,000 inside Drumheller, drawn with `random.Random(20261114)`, plus 7 fixed points.
  - Examples: 52°N 113°W = 882 m, 51.5°N 112.5°W = 879 m, Drumheller south-east corner (row 2160, col 1439) = 684 m.
- Pure-Python whole-tile summary: minimum 650 m, maximum 1095 m, unweighted mean 853.207201539 m, 0 voids. These equal the stored `inspect()` values.

### 3.2 Geometry and area weighting
- Sample coordinates agree to 7e-15°.
- dx (19.0772–19.4994 m) agrees with the chord distances to 1e-12 relative, and dy (30.9023–30.9076 m) to 4e-11.
- Per-row cell areas agree with the exact quadrangle to ≤ 4.4e-10. That figure is limited by float64 cancellation in the reference's 1-arc-second differences.
- AOI totals agree to 1e-12: tile 7725.722891125 vs 7725.722891117 km²; Drumheller 185.580753005 km² in both.
- AOI windows are identical:
  - Tile: rows 1–3600, cols 0–3599 (the half-open ownership rule).
  - Drumheller: rows 1729–2160, cols 720–1439 (432 × 720 samples).
- Inside one tile, area weighting barely matters. The weighted mean elevation is 0.044 m (tile) and 0.001 m (Drumheller) above the unweighted mean. The weighted inverted-CDF and unweighted linear percentiles differ only at the tile's p5 (753 vs 754 m). Weighting matters for aggregation across latitudes.

### 3.3 Water and invalid data
- **Water counts:**
  - 117,665 water samples (SWB = 255) in the granule (0.91%), 117,282 in the owned tile, 0 in Drumheller.
  - NUM = 0 exactly where SWB = 255.
  - The pipeline's water and analysis masks are identical to the reference's.
- **SWB is aligned with the elevation grid** (an internal-consistency check). 99.98% of east–west water–water neighbour pairs have identical heights, because NASADEM flattens mapped water. Only 47% of land–land pairs do.
- **The tile has no void samples.** The void (−32768) path is therefore exercised only by synthetic tests.
- **Shoreline land samples have a negligible effect.** 13,519 land samples have water inside their 3×3 window, so their slope uses the flattened water heights. Excluding them changes the tile's mean slope from 2.9169° to 2.9162°.

### 3.4 Boundaries
- The whole-granule reference leaves only the granule's outer rows and columns undefined. The pipeline's NaN pattern matches it pixel for pixel in both AOIs. This verifies the AOI-edge halos and the 512-row strip seams.
- In the tile, 7,199 analysed samples have no derivatives (3600 + 3600 − 1): the south row (51.0°N) and the west column (113.0°W). Their neighbours are in other tiles.
- The north row and east column are defined, because they use this granule's shared edge row and column. Drumheller has 0 undefined samples.

### 3.5 Terrain layers and statistics

Per-pixel maximum |pipeline − reference|. NaN patterns are identical.

| Layer | Full tile (12,952,801 px) | Drumheller (311,040 px) |
|---|---|---|
| Elevation | 0 | 0 |
| Slope | 1.9e-6° | 1.9e-6° |
| TRI | 3.8e-6 m | 3.8e-6 m |
| Detrended roughness (index-space plane, same definition) | 2.4e-7 m | 2.4e-7 m |
| Detrended roughness vs true metric (trapezoidal) window | 5.8e-5 m | 5.6e-5 m |

The last row measures the pipeline's documented approximation of using one dx for all three window rows. At ≤ 6e-5 m it is about 4,000× smaller than the 0.24 m rounding floor (§5.1), and it changes the mean roughness by < 1e-7 m.

Each AOI has 44 statistics (count, min, max, mean, s.d., p5–p95 and area for 4 measurements), and all are within tolerance. Selected Drumheller values:

| Measurement | Stat | Reference | Pipeline | \|Δ\| |
|---|---|---|---|---|
| Elevation (m) | mean / p50 / p95 | 779.325354 / 793 / 840 | 779.325354 / 793 / 840 | 5e-11 / 0 / 0 |
| Slope (°) | mean | 5.259052 | 5.259052 | 4.5e-10 |
| Slope (°) | p50 / p95 / max | 3.032583 / 18.206729 / 44.377580 | 3.032583 / 18.206728 / 44.377579 | ≤ 1.0e-6 |
| TRI (m) | mean / p95 / max | 6.466254 / 20.688161 / 65.238026 | 6.466254 / 20.688160 / 65.238029 | ≤ 3.8e-6 |
| Detrended roughness (m) | mean / p50 / p95 | 0.551973 / 0.430331 / 1.363094 | identical to 6 decimals | ≤ 5.9e-8 |

The full per-statistic listing for both AOIs is in `validation/results/n51w113_validation.json`.

### 3.6 Reproducibility of the existing outputs
A fresh run, and a CLI re-run of both README examples into a scratch folder, reproduce every stored value. The CSVs are byte-identical, and the JSON is identical apart from `generated_utc`. **No previously generated number changes.**

## 4. Focused tests added (`tests/test_independent_reference.py`, 12 tests)

The expected values were derived by hand, not computed with pipeline helpers.

- **Horn on curved surfaces:** exact for any quadratic surface on non-square pixels, including the cross term. On a cubic, the truncation error is exactly k·dx².
- **Roughness of a quadratic:** detrended roughness of z = Au² + Buv + Cv² is √((2A² + 4B² + 2C²)/9). Equal curvature reads (dy/dx)² ≈ 2.6× rougher along N–S than along E–W.
- **TRI of a plane:** √6·√((g_x·dx)² + (g_y·dy)²), checked at three aspects.
- **1 m rounding floor:** E[roughness²] = 1/18 m², and the Horn gradient s.d. is 1/(8·dx) and 1/(8·dy). Checked on 100,000 random rounded planes with a 2% tolerance.
- **AOI layers equal whole-granule layers** for an interior AOI crossing strip seams, a corner AOI that uses the shared halo row, and the whole tile. Aggregation depends on this property.
- **Real granule** (skipped if the ZIP is absent): the standard-library reader agrees with the pipeline reader on all samples. The Drumheller window agrees per pixel with the reference. Cell areas agree with the exact quadrangle, and `summarize` agrees with numpy's weighted percentiles.

A mutation check confirmed that the new tests fail when:
- roughness is normalised by 6 instead of 9;
- dx and dy are swapped;
- Horn's 1-2-1 weights become 1-1-1.

Planes, ramps, spikes, flat surfaces, NaN propagation and statistics were not re-tested, because `test_terrain.py` and `test_stats.py` already cover them.

## 5. Limitations and remaining uncertainty

### 5.1 Elevation quantisation (1 m integers)
This is the dominant limitation for low-relief terrain.

- **Slope:** rounding alone gives each Horn gradient component a noise of about 1/(8·spacing): 0.37° east–west and 0.23° north–south.
  - Slopes below about 0.5° are rounding-dominated (the tile's p5 is 0.44°).
  - Slope is exactly 0 on 1.5% of the tile area and 0.9% of Drumheller.
- **TRI** takes discrete values at the low end (√2, √5, 3, √18, …). The tile's p50 is exactly 3 and its p95 exactly 9.
- **Detrended roughness:**
  - Rounding a perfect plane gives an RMS of √(1/18) = 0.236 m. That value is exactly the observed p5 in both AOIs.
  - A Monte Carlo that rounds each pixel's own fitted plane gives a floor with median 0.248 m and p95 0.283 m.
  - **35% of the tile's and 25% of Drumheller's roughness values are at or below that p95.** The lower half of the roughness distribution is a quantisation signature. Only values above about 0.3 m carry terrain information.
- Integer contours cause terracing, which shows as banding in the slope map on the valley floor.

### 5.2 Spatial scale, pixel shape and latitude
- **Window size:** at 51.5°N, one arc-second is 19.3 m east–west by 30.9 m north–south. The 3×3 window spans 38.6 m × 61.8 m between its outer sample centres.
- **Scale dependence:** on a 3-arc-second decimation of the same data:
  - Mean slope falls 29% in the tile (2.92° → 2.07°) and 21% in Drumheller (5.26° → 4.16°).
  - p95 slope falls about 20%, and the maximum falls from 44.7° to 30.6°.
  - Detrended roughness rises 3–4×.
  - Part of the excess slope at 1 arc-second is rounding noise.
  - Slope and roughness values are meaningful only with their baseline attached.
- **Aspect dependence** is inherent to TRI and the 3×3 window on a lat/lon grid; it is not a code error.
  - For a plane, TRI = √6·|∇z| × (spacing along the gradient). The same slope therefore gives about 1.5–1.6× more TRI on north- or south-facing ground than on east- or west-facing ground.
  - Real data agree: for 3–15° slopes, the median TRI/(√6·|∇z|) is 21.4 m on east/west-facing slopes and 31.8 m on north/south-facing slopes. That is a ratio of 1.49; plane theory gives 1.60.
  - Detrended roughness from curvature scales with spacing², so the same feature reads 2.6× rougher when curved N–S than when curved E–W.
- **Latitude dependence:** dx ∝ cos(latitude) (30.9 m at the equator, 15.5 m at 60°). TRI and detrended roughness are therefore **not comparable across latitudes**, or with lunar and Martian DEMs on other grids, without resampling. Slope is in correct metric units but still depends on the baseline.
- **Estimator choice** also matters:
  - Zevenbergen–Thorne gives +5.0% mean slope in the tile (+2.9% in Drumheller), and an equal-weight plane gives −1%.
  - Detrended roughness is the RMS of 9 residuals. A degrees-of-freedom-corrected s.d. (dividing by 6) would be 1.22× larger.
  - Compare only results computed with the same definition.

### 5.3 Source accuracy (not validated here)
- **No ground truth was available** (GNSS, survey benchmarks or lidar). Absolute vertical and horizontal accuracy are therefore unverified. The SRTM mission specification (16 m absolute and 10 m relative vertical error, 90% linear error) is quoted from the literature, not checked.
- **Source codes (NUM):** the whole tile is SRTM-derived, with no void fill. By area, the analysed samples come from 3–7 SRTM scenes in the tile (47% from 5 scenes) and 4–7 in Drumheller (54% from 5 scenes).
- **Bound derived from these data (an inference, not a measurement):**
  - Independent per-sample height errors with s.d. σ would give E[roughness²] ≥ (6/9)σ².
  - The tile's roughness RMS is 0.47 m, which limits independent per-sample noise beyond rounding to **≤ 0.5 m**.
  - Any larger SRTM errors must therefore be spatially correlated: they would tilt or shift whole areas rather than add pixel noise.
  - These data also cannot rule out that the source processing smoothed real pixel-scale relief.
- **Datum:** heights are relative to the EGM96 geoid. This does not affect slope or roughness, but absolute elevations cannot be compared with Mars (areoid) or Moon reference surfaces.
- **Radar effects:** SRTM is C-band radar acquired in February 2000. Vegetation and snow effects were not assessed; vegetation in the badlands is sparse.

### 5.4 Artifacts and coverage gaps
- **Red Deer River:** SWB flags no water in the Drumheller AOI, although the river follows the valley floor (public geography; the valley is clearly visible in the DEM). River surfaces are therefore analysed as land. The effect has not been quantified and is probably small.
- **Tile edges:** each tile has 7,199 samples without derivatives unless the neighbouring tiles are loaded.
- **Georeferencing** was checked for plausibility only:
  - The sample at Drumheller's approximate town coordinates (51.4636°N, 112.7106°W) is 688 m.
  - That is the 7.5th percentile of the AOI (670–861 m), i.e. on the valley floor, as expected.
  - Otherwise, horizontal registration rests on the format specification.
- **Not yet tested on real data:** void handling, multi-granule mosaics and the GDAL cross-check.

## 6. Readiness for geographic aggregation

**Yes, with conditions.** The per-sample layers, area weights and half-open ownership rule are verified, and the aggregation step can use them as they are. It should also:

1. **Aggregate from per-sample layers** (or mergeable weighted histograms) using the cell-area weights. Tile percentiles cannot be averaged.
2. **Fill the derivative gaps** on each tile's south and west edges by loading the neighbouring tile's edge row or column, or record those samples as missing.
3. **Report every slope and roughness value with its baseline** (1-arc-second Horn, about a 39 m × 62 m window). Treat detrended roughness below about 0.3 m, and slopes below about 0.5°, as at the quantisation floor.
4. **Put TRI and detrended roughness on a common metric baseline** before comparing them across latitudes or with lunar and Martian DEMs, for example by resampling to a fixed metric grid. Alternatively, restrict cross-body comparisons to slope at matched baselines. This is a design decision for the next ticket and was not implemented here.

## 7. Reproduce

```powershell
.\.venv\Scripts\python -I -m pytest      # 58 passed, 1 skipped (rasterio not installed)
.\.venv\Scripts\python -I validation\independent_check.py NASADEM_HGT_001-20261114_161823\NASADEM_HGT_n51w113.zip
```

The validation script runs in about 105 s and writes `validation/results/n51w113_validation.json`. It needs about 0.8 GB of temporary disk for memory-mapped layers (deleted afterwards unless `--work-dir` is given).
