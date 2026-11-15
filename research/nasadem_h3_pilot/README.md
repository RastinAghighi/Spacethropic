# Spacethropic: NASADEM ingestion and terrain analysis (SPACETHROPIC-01)

Validates one NASADEM_HGT V001 granule, read in place from its ZIP, and measures
elevation, slope and roughness for a configurable area of interest (AOI).
It writes JSON, CSV and a PNG overview.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-lock.txt
.\.venv\Scripts\python -m pip install --no-deps -e .
```

Optional GDAL cross-check of the native reader: `pip install -e .[rasterio]`.

## Run

```powershell
$zip = "NASADEM_HGT_001-20261114_161823\NASADEM_HGT_n51w113.zip"
# whole tile (the tile's own half-open extent 51-52 N, 113-112 W)
.\.venv\Scripts\python -m spacethropic.cli $zip --out-dir outputs
# AOI: --bbox WEST SOUTH EAST NORTH (degrees, WGS 84)
.\.venv\Scripts\python -m spacethropic.cli $zip --bbox -112.80 51.40 -112.60 51.52 --name drumheller_badlands
```

Options: `--include-water` (default excludes SWB water), `--no-plot`,
`--rasterio-crosscheck auto|yes|no`. Outputs go to `outputs/<tile>_<name>/`:

- `terrain_summary.json`: granule metadata, validation checks, parameters and all statistics, with units.
- `terrain_summary.csv`: long format (one row per measurement and statistic); safe to concatenate across granules.
- `terrain_overview.png`: elevation with hillshade, slope, TRI and detrended roughness.

## Test

```powershell
.\.venv\Scripts\python -m pytest
```

The tests use synthetic grids with analytically known answers. They also check
geodesy against independent WGS 84 formulas.

## Validation

`scientific_validation.md` reports the real-data validation (DRUMHELLER-PILOT-02):
checks, tolerances, results and limitations. To re-run the independent
standard-library reader and reference implementation against the pipeline (about 2 min):

```powershell
.\.venv\Scripts\python -I validation\independent_check.py NASADEM_HGT_001-20261114_161823\NASADEM_HGT_n51w113.zip
```

## H3 aggregation (DRUMHELLER-PILOT-03)

The validated per-pixel layers can be assigned to H3 hexagons and summarised per cell at any resolution (6 is the planned worldwide baseline):

```powershell
.\.venv\Scripts\python -m spacethropic.h3_cli $zip --bbox -112.80 51.40 -112.60 51.52 --name drumheller_badlands `
    --resolutions 6 8 --reference-summary outputs\n51w113_drumheller_badlands\terrain_summary.json
```

How it works:
- Derivatives are computed first, on the full grid with its halo. Each sample is then assigned to the cell containing its centre: `latlng_to_cell(lat, lng, res)`, latitude first.
- Per-cell statistics use the existing area-weighted definitions on the cell's own samples. Percentiles are never averaged.
- Partial cells are labelled with exact and pixel-centre coverage fractions. Their statistics describe only the observed part.

Outputs go to `outputs/<tile>_<name>_h3/`, with one set per resolution:
- `h3_resN_cells.csv`
- `h3_resN_cells.geojson` (longitude, latitude)
- `h3_resN_run_summary.json` (methodology, provenance, conservation and reconciliation checks)
- `h3_resN_mean_slope.png`

The method, results, limitations and scaling notes are in `h3_aggregation.md`.

## Conventions

| Item | Choice |
|---|---|
| Format | `.hgt` = big-endian int16, 3601 x 3601, metres above the **EGM96 geoid**. `.num` = source codes. `.swb` = 0 land / 255 water (NASADEM User Guide, Tables 1-2) |
| Georeferencing | Tile name = **south-west** corner; samples are pixel-is-point on whole arc-seconds; horizontal CRS EPSG:4326 |
| No-data | `-32768` -> NaN (NASADEM_HGT is void-filled, so none are expected). A 3x3 derivative is NaN if any of its 9 samples is missing or the window crosses the granule edge |
| Ownership | AOIs select samples with `south <= lat < north`, `west <= lon < east`, so a tile owns 3600 x 3600 of its 3601 x 3601 samples and adjacent tiles never double-count |
| Distances | Per-row WGS 84 ground spacing: dx = N cos(lat) dlon (~19.3 m at 51.5 N), dy = M dlat (~30.9 m) |
| Slope | Horn (1981) 3x3 gradient, in degrees |
| Roughness | TRI (Riley et al. 1999), in m; detrended roughness = RMS residual about the 3x3 least-squares plane, in m |
| Statistics | Weighted by cell ground area; weighted inverted-CDF percentiles |

## Package layout

`src/spacethropic/`:

- `geodesy.py`: WGS 84 radii and cell areas
- `nasadem.py`: ZIP members, grid geometry, validation, streamed reading
- `terrain.py`: slope, TRI, detrended roughness, hillshade
- `stats.py`: weighted statistics
- `pipeline.py`: AOI analysis, computed in row strips
- `outputs.py`: JSON and CSV writers
- `viz.py`: the overview figure
- `cli.py`: the command line
- `h3grid.py`: H3 v4 assignment of sample centres, cell polygons, exact overlap and ellipsoidal areas
- `aggregation.py`: per-cell area-weighted statistics for any integer cell key (dataset-agnostic)
- `h3_pipeline.py`: terrain layers to H3 cells, coverage, conservation and reconciliation checks, run summary
- `h3_outputs.py`, `h3_viz.py`, `h3_cli.py`: CSV/GeoJSON/JSON writers, the mean-slope map, the H3 command line
