# Execution and validation report — 2026-11-15

**Global candidate processing is not complete: the required MODIS input is absent.**
The tested resumable code, public input preparation, regional real-observation
dataset, and real DEM contour demonstration are complete. No global retained or
excluded land total, global candidate count, or global processing time is claimed.

## Machine and inputs

Windows; Python 3.14.2; 16 logical CPUs; 34,276,777,984 bytes RAM (31.9 GiB).
Initial free space: C: 23.5 GB, D: 40.5 GB, S: 64.5 GB, W: 197.0 GB,
X: 134.4 GB. Large outputs are outside Git at `W:\Spacethropic-data`.
The project started clean on `main`; work is on `feat/global-r7-handoff`.
The audit, validation report, r7 inventory, original `475bf4e` filter/contours,
regional pilot and terrain-database contract were inspected before implementation.

| Input | Result |
|---|---|
| Natural Earth 1:10m land v5.1.1 | Downloaded; 3,269,070-byte ZIP, CRC and SHA-256 verified |
| GHSL GHS-POP E2020 R2023A 4326 30ss V1-0 | Downloaded; 482,351,880-byte ZIP; 382,936,052-byte extracted GeoTIFF; verified |
| NASA CMR metadata | 315 MCD12Q1 and 1 MCD12C1 granules for 2023 v061; inventory saved |
| MODIS pixels/counts | **Missing**; protected Earthdata downloads, no local credentials or transferred cache |
| Esri | Absent; not used |
| Copernicus GLO-30 demo crop | Real 99 × 90 pixel overview crop, 30,193-byte GeoTIFF; URL/ETag/hash recorded |

Public preparation took **17.61 seconds**, excluding downloads. It reproduced
**146,735,718.315 km²** Natural Earth land and **7,840,952,947.014 people** in GHSL,
agreeing with the audit. **31,462.765 km²** of land lacks population coverage and
is explicitly unknown. Test-site pixel population agrees within 0.042 people/km²
with the audit's one-decimal values. The scientific audit was not repeated.
See [public-inputs.json](results/public-inputs.json) for checksums/configuration.

## Actual regional data

The tracked `site_validation_detail.json` contains genuine rounded coarse-pixel
observations from the completed audit. These were processed into real r7 geometry.
This is **regression using committed observations**, not fresh raw-MODIS extraction
or fabricated imagery. Unreported pixels are unknown. Individual IGBP fractions
are null in this sample; only reported group fractions are available. A completed
full-input run populates all 17 class columns.

| Region, 19 r7 cells each | Eligible | Uncertain | Excluded | Site coordinate |
|---|---:|---:|---:|---|
| Drumheller | 6 | 4 | 9 | Excluded, consistent with populated town pixel |
| Atacama, Yungay | 19 | 0 | 0 | Eligible |
| Hanksville, MDRS | 19 | 0 | 0 | Eligible |
| McMurdo, Beacon Valley | 19 | 0 | 0 | Eligible |
| McMurdo, Don Juan Pond | 19 | 0 | 0 | Eligible |
| **Total** | **82** | **4** | **9** | **86 sample candidates** |

The committed Drumheller JSON has only eight coarse pixels. Four r7 cells extend
beyond this footprint; the earlier report used a larger untracked window and had
nine kept cells. Those regional totals are **not directly comparable**. All five
site decisions agree and every region retains eligible cells. Request
`site_kept_windows.npz` for exact reproduction of the old ring results.

The 95 cells cover 478.156 km² in whole-cell footprints. Weighted sampled eligible
area is **410.334 km²**, sampled excluded area **59.533 km²**, and unobserved area
**8.290 km²**. The 86 candidates' whole footprints cover 432.989 km²; that is not
the eligible land area. These figures are regional, never global estimates.

Actual artifacts under `W:\Spacethropic-data\deliverables`:

| Artifact | Size / processing |
|---|---|
| `audit_sample.parquet` | 95 rows, **20,126 bytes**, includes exclusions for inspection |
| `audit_sample.geojson` | 95 polygons, **286,357 bytes**, regional visualization only |
| `partitioned/cells/` | **86 candidate rows** across 95 test partitions including empty exclusions; **1,339,425 bytes** |
| `partitioned/manifest.json` | **0.475 seconds** summed partition processing; peak sampled RSS **54.4 MB** |
| `contours/lines.parquet` | **74 real 20m contour segments**, **23,683 bytes** |
| `contours/coverage.parquet` | 10 Drumheller candidates covered; 76 others explicitly lack coverage in the demo crop |

These tiny per-cell partitions exercise checkpoints; default global r3 partitions
contain up to 2,401 r7 cells. A repeat verified existing files and processed **zero
new partitions**. Partition timing excludes setup and hash verification.
The contour stage took approximately **0.11 seconds**, excluding DEM retrieval.
The Copernicus surface model is an approximately 8x overview, EGM2008. These are
coarse demonstration contours, not full-resolution NASADEM terrain. No global
DEM download or global elevation contour run was attempted.

## Verification and benchmark

**39 tests passed** across the new global suite and existing regional pilot suite
(38-test combined run, then the additional mask-preparation integration test).
Synthetic fixtures verify mechanics separately from the genuine audit regression:

* Sphere area conservation and sample membership at both poles, the date line,
  all 12 pentagons, and resolutions 0, 7 and 8.
* Complete low-resolution global enumeration with no missing/duplicate IDs.
* Thresholds, missingness, known exclusions overriding unknowns, barren review.
* Partial execution/resume, changed configuration rejection, corrupt checkpoint
  detection, byte-identical independent Parquet runs and empty partitions.
* r7 CLI/row/manifest consistency; explicit r8 remains supported.
* Analytic DEM ramp contours, missing DEM coverage and contour checkpoint reuse.
* Synthetic mask preparation through actual memmaps/GeoTIFF, missingness and
  exclusion flags, land-area accounting, loader indexing, and preparation reuse.

On the 95 observed cells, increasing quadrature from 8 to 16 subdivisions changed
excluded fractions by at most **0.00586** (0.586 percentage points), with **zero
decision changes**. Pole/date-line/pentagon area errors are below **9.1 × 10⁻⁹
relative**. This validates geometry and this sample's convergence, not a universal
fraction accuracy guarantee.

The final kernel benchmark repeated 95 real cells 100 times: **9,500 evaluations
in 4.604 seconds**, **2,064 cells/s**, approximately **53.5 MB RSS**. Naively
extrapolated to 98,825,162 r7 cells, this is **13.3 hours** single-process, excluding
global memory-map I/O, writing and checkpoint overhead. It is **not a representative
global-data benchmark or a promise of completion**. `benchmark.py` is ready to
measure 12 diverse complete r3 partitions once MODIS arrives. Storage/RAM do not
appear to be the immediate blocker; missing data are.

## Remaining gate and limitations

Obtain the **441 MB Q1 counts cache**, totals JSON and hashes specified in
[TRANSFER_REQUEST.md](TRANSFER_REQUEST.md). Then prepare the mask, validate the
sites using those complete inputs, benchmark, and execute the global command.
Global mask construction and the representative benchmark are implemented but
have **not** been exercised on real global MODIS in this session.

The permissive baseline remains, with missing/threshold/barren safeguards labelled
separately. Snow/ice, grassland and savanna remain potential false positives; QC=1
ambiguity is inherited from the cache and McMurdo ice/barren remains unresolved.
H3 fractions sample a coarse raster, not native 500m/10m geography. Esri is absent.
The local contour path needs dedicated mosaics for polar/date-line cells. There is
no ranking, mission calibration, database ingestion or full global terrain stage.
See [README.md](README.md) for exact semantics, commands and restart behavior.
