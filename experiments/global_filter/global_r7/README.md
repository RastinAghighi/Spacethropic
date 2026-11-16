# Global H3 r7 geographic filter

**2026-11-15: resumable implementation and real-observation regional run completed;
global candidate dataset blocked by missing MODIS.** Public Natural Earth and GHSL
inputs have been downloaded and processed. No global suitability total or global
candidate count is claimed. See [RUN_REPORT.md](RUN_REPORT.md) and the exact
[teammate transfer request](TRANSFER_REQUEST.md).

This adapts the geographic logic of `data/cleaning` commit `475bf4e`
(`global_mask_v2.py`, `contours_r8.py`) into a separate bounded pipeline. It leaves
the old NDVI experiment and archived terrain results intact. The regional pilot
also now accepts `--resolution`, default 7; its separate 80% mission policy is
**not** used here. The terrain database can join these rows on `h3_cell` and
`resolution`; no ranking or terrain-database ingestion is performed.

## Policy and accuracy

The reproducible coarse baseline is Natural Earth 1:10m land at 0.05 degree pixel
centers; MODIS MCD12Q1 2023 v061 class counts on that grid; and GHSL E2020 R2023A
V1-0 population, binned by source pixel center (the GHSL grid is offset).

A coarse pixel fails for ocean, population **>=50 people/km²**, water **>=50%**,
built **>=25%**, dense vegetation **>=50%**, or water+built+dense vegetation
**>=50%**. Dense vegetation classes are IGBP 1–6, 8, 11, 12, 14. Open shrubland,
savanna, grassland, snow/ice, and barren remain permissive. **No NDVI gate.**
Esri is absent, so this is **MODIS-only, not the complete original v2**.
`--mcd12c1` is an explicit alternative using the 2023 v061 percentage product;
its manifest distinguishes it from Q1 counts. It does not reproduce Q1 exactly.

The inherited H3 rule removes cells with >=90% excluded area. Three separately
recorded safeguards retain uncertainty without silently declaring suitability:

* Missing population or land cover becomes uncertain, unless a known exclusion
  already decides that part of the cell. Known exclusion covering >=90% can still
  exclude a cell with a small unknown remainder.
* Cells within 1 percentage point of the 90% cutoff are retained as uncertain
  (`--threshold-margin 0` disables the band). This is a conservative review band,
  **not a proven numerical error bound**.
* Q1 coarse pixels removed for water/vegetation/mixed causes, holding >=24 barren
  500m pixels, are flagged `barren_in_removed`. Touching cells become uncertain.
  Ocean, built and population failures do not trigger this rescue. The location
  of that barren patch within the coarse pixel remains unknown. C1 has no counts,
  so this flag is unavailable on the C1 path.

`baseline_kept` preserves the original 90% Boolean decision before these review
safeguards (including the legacy treatment of missing observations as not excluded).
Use `decision` and the three area fractions for downstream work.

H3 cells are partitioned by their **logical H3 parent**, not polygon fills: every
cell occurs exactly once, including pentagons, poles and the date line. At default
r3 parents / r7 outputs, at most 2,401 IDs and 256 output rows are buffered.
All 98,825,162 Earth r7 cells are visited; excluded cells need no individual rows.
This avoids dependence on DEM tile coverage, especially in Antarctica.

Each spherical H3 polygon is divided into triangles, then 8² subtriangles per
edge triangle (usually 384 samples). Exact spherical subtriangle areas weight
their centroid samples. Repeated coarse pixel lookups are coalesced. This replaces
the legacy 0.001 degree raster sampling with latitude-independent sampling;
it is **approximate mask integration**, not exact pixel intersection. Total H3
area is verified independently; this does not prove exact fractions at boundaries.
For refinement use `--subdivisions 16` and compare decisions. No r7 detail is
invented inside the much coarser MODIS aggregate pixels.

## Reproduce on Windows (repository root)

Tested on Python 3.14.2, Windows, using the exact versions in `requirements-lock.txt`.
The root `.venv` is ignored. Equivalent commands work on Linux with `bin/python`;
Linux wheel availability has not been verified with this lock.

```powershell
python -m venv .venv
$py = '.\.venv\Scripts\python.exe'
$code = 'experiments/global_filter/global_r7'
$data = 'W:\Spacethropic-data' # choose an external data directory on your computer
& $py -m pip install -r "$code/requirements-lock.txt"
& $py -m pytest "$code/tests" experiments/global_filter/regional_pilot/tests -q
```

Check `$LASTEXITCODE` after each command; stop if nonzero. Download exact public
versions (ZIP CRC and SHA-256 receipts; interrupted ZIP downloads support ranges):

```powershell
& $py "$code/fetch_inputs.py" --root "$data/raw"
& $py "$code/prepare.py" public `
  --natural-earth "$data/raw/natural-earth/ne_10m_land.zip" `
  --ghsl "$data/raw/ghsl/GHS_POP_E2020_GLOBE_R2023A_4326_30ss_V1_0.tif" `
  --output "$data/prepared-public"
```

`fetch_inputs.py` inventories the protected MODIS granules; it does not download
them or read credentials. Public preparation writes disk-backed `land.npy`,
`density.npy`, `people.npy`, and a checksummed manifest. It preserves invalid and
uncovered population cells as NaN. No full global H3 array is allocated.

Run the already-available real audit snapshot regression:

```powershell
& $py "$code/validate.py" --output "$data/deliverables" `
  --public "$data/prepared-public" --benchmark-repeats 100 --partitioned
& $py "$code/export_example.py" --source "$data/deliverables/audit_sample.geojson" `
  --output "$data/example.geojson"
```

This produces **95 regional rows / 86 candidate rows**, with explicit sparse
observation gaps, not a global MODIS result. Repeating it verifies and reuses its
95 tiny r7-parent Parquet checkpoints. Global runs use r3 parents for efficiency.

After receiving the Q1 counts cache:

```powershell
& $py "$code/prepare.py" mask --base "$data/prepared-public" `
  --counts "$data/raw/modis-cache/mcd12q1_counts_0p05.npy" --output "$data/mask-q1"
& $py "$code/validate.py" --mask "$data/mask-q1" --output "$data/validation-q1"
& $py "$code/benchmark.py" --mask "$data/mask-q1" --output "$data/benchmark-q1"
# Inspect validation.json and benchmark.json before scaling.
& $py "$code/run.py" --mask "$data/mask-q1" --output "$data/global-r7-q1" --limit 10
# Exact same command without --limit continues from checked partitions:
& $py "$code/run.py" --mask "$data/mask-q1" --output "$data/global-r7-q1"
```

The global-data validation and representative benchmark have **not** been run
here because the counts are missing. The benchmark visits 12 complete r3
partitions across deserts, mixed badlands, forest, cropland, urban, ice, coast,
date line, and poles. Extrapolations are planning estimates, not measured global
runtime or storage. Current snapshot-kernel measurements suggest about 13 hours
single-process before global I/O overhead. Running fewer subdivisions changes
the method and requires renewed convergence checks.

The preparation mask path also accepts `--mcd12c1 PATH.hdf` instead of `--counts`.
Use new output directories and repeat validation/benchmark for that alternative.

## Outputs, restart and reading

* `mask-q1/manifest.json`: exact spherical coarse-grid eligible/uncertain/excluded
  **land** areas, sources/hashes, overlapping reason totals, and policy.
  `flags.tif` is a compact global raster suitable for mapping exclusions.
* `global-r7-q1/cells/parent=<id>/part-0.parquet`: eligible and uncertain rows;
  H3 ID, resolution, actual H3 area, land/eligible/uncertain/excluded fractions,
  all 17 IGBP fractions, group fractions, observed population density/coverage,
  reason bits/fractions, mixed and review flags, and provenance ID.
* `checkpoints/<parent>.json`: evaluated/candidate counts, areas, duration, bytes,
  SHA-256. Written atomically **after** Parquet; an interrupted partition alone
  is recomputed. A stale OS lock is released automatically on process exit.
* `manifest.json`: `partial` versus `complete`, global versus selected scope,
  actual counts, storage and processing seconds. Resume refuses changed input,
  configuration, code, or software, and detects corrupt Parquet. A full global
  completion must account for H3's exact global cell count.

Fractions use the **whole H3 cell** denominator (not just observed land).
Class fractions sum to class-observed fraction; unobserved mass is not divided
away. The snapshot cannot supply individual IGBP fractions, so they are null.
Population means are conditional on observed population coverage. Whole candidate
cell footprints must not be reported as retained land. H3 `sampled_excluded`
includes ocean; obtain excluded **land** from the prepared mask summary.
Reason bits are independent/overlapping: 1 ocean, 2 water, 4 built, 8 population,
16 vegetation, 32 mixed, 64 missing land cover, 128 missing population, 256 barren
review. Do not sum reason totals as if mutually exclusive.

Memory-mapped raster arrays remain on disk; no process pool multiplies them.
The driver stops between partitions if free disk drops below 5 GB, configurable
with `--min-free-gb`. `--limit N` bounds new partitions, not total partitions.
Preparation stages are short and restart as a stage after interruption; only the
long H3 stage has per-parent checkpoints. Verify complete prepared inputs before
running downstream stages. Do not change input files during a running process.

Read single files or stream batches to avoid loading the entire table:

```python
from pathlib import Path
import pyarrow.parquet as pq
for path in Path("W:/Spacethropic-data/global-r7-q1/cells").glob("parent=*/*.parquet"):
    for batch in pq.ParquetFile(path).iter_batches(batch_size=65536):
        pass  # insert/aggregate this batch in your terrain database
```

The parent column is in the Hive directory name. `ParquetFile` avoids the
`pyarrow.dataset` DLL issue recorded on the original development machine.

## Optional contours

Eligibility is independent of elevation availability. H3 boundaries are implicit
in the IDs. `contours.py` writes elevation isolines and per-cell coverage, one
candidate Parquet partition plus local DEM per invocation. Repeating the same
invocation verifies its checkpoint; changed inputs require a new directory.
DEM values must be meters; preserve the source vertical datum in the handoff.
Outputs store x/y in the DEM CRS, specified in the manifest. Date-line/polar
cells require dedicated DEM mosaics and are explicitly flagged, not dropped.

```powershell
& $py "$code/demo_dem.py" --output "$data/demo/drumheller_copdem_8x.tif"
& $py "$code/contours.py" --cells "$data/deliverables/audit_sample.parquet" `
  --dem "$data/demo/drumheller_copdem_8x.tif" --interval 20 `
  --output "$data/deliverables/contours"
```

The real demo uses a small Copernicus GLO-30 8x overview crop (DSM, EGM2008,
approximately 240 m latitude spacing); it is not the NASADEM pilot or full
global elevation integration. Open `examples/audit_sample.geojson` in QGIS as
EPSG:4326, style on `decision`, and consult the source/scope properties.

## Known scientific limits

No Esri, NDVI gate, global QC refinement, ranking, or terrain eligibility gate.
Q1 cached counts include the audit's known QC=1 ambiguity; no per-pixel QC is
available in that cache. McMurdo snow/ice remains eligible and must not be read
as proof of bare ground. Fine badlands cannot be resolved by 0.05 degree fractions.
The center-based Natural Earth raster misses subpixel islands/coastline detail.
Sampling and review margins are conservative approximations; review flags are
not validated probabilities. Keep uncertain records for later refinement.
