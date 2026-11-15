# Why does the global filter keep 85.8 M km²? A MODIS 2023 land-cover audit

*2026-11-15. Scripts in `scripts/`, numbers in `results/`. Land-cover data only: GHSL population
and Esri land cover are **not** included, so nothing here reproduces the full filter exactly.*

## The short answer

The filter keeps so much land because its rule treats **grassland, savanna and snow/ice** as
analog ground, together with barren land and open shrubland. These five MODIS classes cover
95.05 M km², 65% of all land. There is no bug in how the data is read.

- With MODIS 2023 land cover alone, the current v2 rule keeps **94,029,740 km² (64.08% of land)**.
  The full filter's reported 85.8 M km² (58.47%) is 8.23 M km² lower. That gap comes from the
  parts not tested here: GHSL population removal and averaging with Esri.
- Of those 94.03 M km²:
  - grasslands: 28.96 M
  - barren: 20.28 M
  - snow/ice: 14.59 M (12.25 M of it in Antarctica)
  - savannas: 12.93 M
  - open shrublands: 12.91 M
  - non-analog cover inside pixels that pass the 50% rule (woody savanna, cropland, forest, water):
    4.34 M
- Only about 1/3 of the kept area is barren or sparsely vegetated.
- Ruled out as causes:
  - Missing data adds only 21,023 km².
  - The class percentages are read correctly.
  - The two MODIS products agree within 0.1%.

## 1. Data validation

Full report: [results/dataset_validation_report.md](results/dataset_validation_report.md).
51 checks pass, 0 fail, 1 warning (harmless). Nothing was downloaded.

| Dataset | Files | Product / version / period | Grid / CRS | Fill values | Result |
|---|---|---|---|---|---|
| Natural Earth | `10m_physical.zip` (50 layers) | `ne_10m_land` v5.1.1, 11 polygons | WGS 84 geographic | none | Pass. Land at 0.05°: **146,735,718 km²** (12,258,282 south of 60°S) |
| GHSL | zip + 4 extracted files (CRC-identical to the zip) | GHS-POP E2020 R2023A V1-0, 30″ | EPSG:4326, 43,202 × 21,384 | No nodata tag, but no negative values either | Pass (1 warning). Whole band read: 7,840,952,947 people |
| MCD12C1 | 1 | v061, 2023-01-01 to 2023-12-31 | 0.05° geographic, 7200 × 3600 | 255 (none present) | Pass. Every pixel's 17 class percentages sum to exactly 100 |
| MCD12Q1 | 315 (+ 29 duplicates) | v061, 2023 | MODIS sinusoidal (R = 6,371,007.181 m), 2400 × 2400 tiles | 255 (34,122 pixels inside the globe = 7,325 km²) | Pass. All 315 decode; the set matches NASA's CMR list exactly (315/315); the 29 "(1)" duplicates are byte-identical copies |
| VIIRS VNP13C2 | 12 (one per month) | v002, Jan–Dec 2023 | 0.05° CMG (no embedded geotransform; grid given by attributes) | NDVI: −15000, −14000, −13000, −12000 | Pass. The teammate's `a > -10000` test excludes all four fill codes. VIIRS isn't used further here (it fed the old v1 NDVI rule) |

**Are the class percentages read correctly?** Yes. MCD12C1 numbers water as class **0** and
barren as **16**. MCD12Q1 uses 1–17 with water as **17**. Three checks confirm the mapping:

- Percent layer *k* is class *k*. Its argmax equals NASA's majority class in all 25,912,179
  unambiguous pixels; 7,821 pixels tie and were skipped.
- Reference points are classed as expected: open ocean is water, the Sahara and the Rub al Khali
  are barren, the Amazon is evergreen broadleaf, Antarctica and Greenland are snow/ice, and Iowa
  is cropland. One taiga point I chose turned out to be woody savanna in both bands, so my guess
  was off, not the data.
- MCD12Q1, counted independently, agrees with MCD12C1 within 2.3% for every land class and
  within 0.01% for total land.

## 2. How much of Earth is each land cover (MCD12C1 2023, area-weighted)

Each 0.05° pixel is weighted by its exact area on the sphere. Pixels shrink toward the poles,
so high latitudes are not over-counted. Earth = 510,065,622 km². "Land" = Natural Earth land.
All 17 original classes, plus the MCD12Q1 comparison, are in
[results/global_landcover_class_area.csv](results/global_landcover_class_area.csv).

| Category (IGBP classes) | Area, km² | % of Earth | % of land |
|---|---:|---:|---:|
| Barren (16) | 20,417,875 | 4.00 | 13.86 |
| Grassland (10) | 31,006,067 | 6.08 | 21.05 |
| Open shrubland (7) | 13,118,763 | 2.57 | 8.93 |
| Savanna: woody savannas (8) 11,402,976 + savannas (9) 15,810,401 | 27,213,377 | 5.34 | 18.48 |
| Forest (1–5) | 22,544,493 | 4.42 | 15.28 |
| Cropland: croplands (12) 11,885,475 + crop/natural mosaic (14) 1,409,626 | 13,295,101 | 2.61 | 9.05 |
| Urban (13) | 868,194 | 0.17 | 0.58 |
| Water (0) | 365,000,709 | 71.56 | 1.61 (lakes, coast) |
| Snow or ice (15) | 14,687,590 | 2.88 | 9.96 |
| Other classified: closed shrublands (6) 460,667 + permanent wetlands (11) 1,452,783 | 1,913,450 | 0.38 | 1.19 |
| Unclassified / no data | 0 (MCD12Q1: 7,325) | 0.00 | 0.00 |

Grassland is the largest land class on Earth in MODIS. It includes Arctic tundra, steppe and
pasture, not just dry rangeland. Of the 14.69 M km² of snow/ice, 12.27 M km² is south of 60°S.

## 3. Land kept under each policy

Every policy uses the v2 rule structure. A pixel is removed if it is outside Natural Earth land,
or if any of these holds:

- water ≥ 50%
- built-up ≥ 25%
- non-analog land ≥ 50%
- water + built-up + non-analog ≥ 50%

In effect, a pixel is kept when more than half of it is "analog" classes. The policies differ
only in which classes count as analog. "Sparse vegetation" is taken as **open shrublands**:
IGBP has no sparse-vegetation class, and savannas and grasslands can be dense.

Source: MCD12Q1 binned to 0.05° exactly as the teammate's `landcover_fractions.py` does
(the input the filter used). MCD12C1 gives the same answer within 0.25%. Both are in
[results/filter_policy_comparison.csv](results/filter_policy_comparison.csv).

| Policy | Analog classes | Kept, km² | % of land | of which north of 60°S | ≈ r7 cells |
|---|---|---:|---:|---:|---:|
| Reported v2 (MODIS + Esri, GHSL, NE). *Not reproduced here* | | 85,800,000 | 58.47 | | ≈ 16.6 M |
| **P1 Current v2 land-cover rule** | open shrub, savanna, grassland, snow/ice, barren | **94,029,740** | **64.08** | 81,782,385 | ≈ 18.2 M |
| P1b Current classes, non-analog ≥ 25% removes | same | 87,382,976 | 59.55 | 75,135,631 | ≈ 16.9 M |
| P1c Current classes, pixel ≥ 90% analog | same | 79,936,393 | 54.48 | 67,770,824 | ≈ 15.5 M |
| P2 Drop savanna | open shrub, grassland, snow/ice, barren | 77,872,242 | 53.07 | 65,624,887 | ≈ 15.1 M |
| P3 Drop savanna + grassland | open shrub, snow/ice, barren | 47,961,675 | 32.69 | 35,714,328 | ≈ 9.3 M |
| **P4 Barren + sparse vegetation** | barren, open shrub | **33,253,204** | **22.66** | 33,232,294 | ≈ 6.4 M |
| P5 Non-vegetated only | barren, snow/ice | 34,761,863 | 23.69 | 22,514,515 | ≈ 6.7 M |
| **P6 Barren only** | barren | **20,056,718** | **13.67** | 20,035,808 | ≈ 3.9 M |

Land = 146,735,718 km². The r7 counts are kept area ÷ 5.161 km² (the mean r7 cell area), for
scale only. No H3 cells were generated.

**How much each class adds**, going from P6 (barren only) up to P1 (the current rule):

| Class added | Extra land kept |
|---|---:|
| Open shrubland | +13.20 M km² |
| Snow/ice (almost all of it Antarctica and Greenland) | +14.71 M km² |
| Grassland | +29.91 M km² |
| Savanna | +16.16 M km² |

**The 50% rule.** Whole pixels are kept or removed, so P1's kept area contains 4.34 M km² of
non-analog cover, and pixels it removes contain about 5.0 M km² of analog cover. The fractional
area of the analog classes on land (94.66 M km²) is therefore close to the kept area. Tightening the
thresholds lowers the total by 7–14 M km² (P1b, P1c). Changing the class list lowers it by up to 74 M km².

**What the numbers suggest** (the choices are the team's to make):

- To get far below about 80 M km², the class list has to change. Tightening thresholds isn't enough.
- Grassland is the largest single lever.
- Antarctica alone is 12.25 M km² of kept land under every policy that includes snow/ice.

## 4. H3 resolution 7

This analysis is independent of H3: it works on 0.05° rasters and reports km². The global H3
generation (`contours_r8.py`), the geographic filtering step (each hexagon's removed share,
measured against the mask), and the terrain database must all move to **resolution 7** in a
separate integration task. The places where r8 is hard-coded are listed in
[H3_RESOLUTION_7_INVENTORY.md](H3_RESOLUTION_7_INVENTORY.md). An r7 cell (mean 5.161 km²) is
7× an r8 cell. For comparison: the reported 85.8 M km² is about 116 M r8 cells (the teammate's
8x run produced 114.2 M) but only about 16.6 M r7 cells.

## 5. Limitations

- **Land cover only.** GHSL population (≥ 50 people/km² removes), Esri 10 m land cover and Dynamic
  World are not included, so P1 is not a reproduction of the 85.8 M km² filter. The 8.23 M km²
  gap between them is not broken down here.
- The reported 85.8 M km² is itself provisional. An earlier check today found that the Esri query
  in `landcover_fractions.py` (`datetime="2023"`) returns 2022 and 2023 items together
  (1,512 instead of 756).
- **MODIS class accuracy.** IGBP classes are reported to be roughly 70–75% accurate overall.
  Grassland, savanna and open shrubland are among the classes most often confused, so the gaps
  between P2, P3 and P4 carry real classification uncertainty.
- **Resolution.** Decisions are made per 0.05° pixel (about 5.6 km wide, 31 km² at the equator),
  with whole-pixel keep/remove, as in the filter. Results are for 2023 only.
- **Natural Earth version.** Land comes from the `10m_physical` shapefile (v5.1.1). The
  teammate's run used the NE GeoJSON from GitHub; land area agrees with their figures within
  rounding.
- **Spherical areas.** Areas are on the authalic sphere (R = 6,371.007 km, the same as the
  pipeline), which preserves the total area of the Earth. Local differences from the ellipsoid
  are small.
- **The r7 cell counts** are area ÷ mean cell area. Real counts depend on cell-edge rules and on
  how cell area varies with latitude.
