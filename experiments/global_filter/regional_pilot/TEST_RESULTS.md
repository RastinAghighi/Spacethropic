# Executed test evidence

## 2026-11-15: local run on the development laptop

Environment: Windows 11, Python 3.12.10, project-local `.venv`, with exact versions
in `requirements-lock.txt` (h3 4.5.0, rasterio 1.5.2 / GDAL 3.12.2, shapely 2.2.0,
pyproj 3.8.0, pyarrow 26.0.1, numpy 2.5.4).

```
.venv\Scripts\python -m pytest -q -rs -W error::DeprecationWarning -W error::PendingDeprecationWarning
25 passed, 1 skipped in ~24 s
```

- The original 9 unit tests still pass, unchanged except that the test helper uses the
  non-deprecated reprojection.
- `tests/test_integration.py` adds 16 tests on **real H3 r8 cells** around Drumheller,
  using synthetic UTM 12N 10 m GeoTIFFs. Each test is listed below.

  **H3 generation and geometry**
  - Ring 0 gives 1 cell, ring 1 gives 7 and ring 5 gives 91. All are valid
    resolution 8, and swapped latitude/longitude is rejected.
  - `cell_polygon` equals `h3.cells_to_geo`, and its area is within 1 % of
    `h3.cell_area`. Antimeridian cells are rejected.

  **Area weighting**
  - Area weighting matches an independent estimate made with a 4 m point lattice
    assigned by `h3.latlng_to_cell` (±0.5 percentage points).
  - A uniform raster conserves area over 7 cells to 1e-5 %.

  **Conservative handling of missing or uncertain data**
  - An untagged Dynamic World raster is refused, because masked 0 would read as
    water. No output directory is created.
  - Tagged no-data becomes unknown and forces `review`.
  - Non-integer rasters are refused.
  - A coastal cell beyond the raster footprint is `review`, not `excluded` or ocean.
  - Mixed cells near the threshold are classified correctly, and snow/ice is never
    auto-excluded.

  **End-to-end run**
  - A CLI-equivalent ring-1 run writes hive-partitioned Parquet with the manifest,
    sha256s and software versions. Breakdown columns are typed `float64` (not
    null-typed), and the run refuses to overwrite.
  - Bad or out-of-order ISO dates and a missing raster leave no output.

- **1 skipped:** reading `cells/` with the standard `pyarrow.dataset` hive reader.
  Windows Application Control blocks pyarrow's `_dataset_parquet` DLL on this
  machine (in every environment, including the user's global Python). The layout is
  written to the same hive convention but could not be machine-checked here.
- A CLI smoke run (ring 1, synthetic raster, scratch directory) took about 10 s for
  7 cells, and its class shares match the fixture.

The existing pipeline tests (`../pipeline`, `uv sync --frozen` then `uv run pytest`)
gave **21 passed, 17 skipped**. The skipped tests are the zonal spot-checks, which
need `pipeline/data/`, absent on this machine.

**Not yet run:** no real Dynamic World, Esri or MODIS raster exists in the
repository, so no real-data pilot has been executed. Synthetic fixtures are test
inputs only. They are not observations.

## 2026-11-14: original prototype (assistant container, offline)

9 passed. H3 generation and the Parquet writer were not tested there, because `h3`
and `pyarrow` were unavailable.
