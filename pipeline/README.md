# Analog calibration pipeline

Builds the calibration dataset for Spacethropic's analog searcher. Three Earth sites that NASA
actually used as Moon/Mars analogs are paired with their planetary counterparts. Open Earth,
Moon and Mars data around all eight sites is summarised onto a shared [H3](https://h3geo.org)
grid, producing one complete feature table per site.

| Earth site | Planetary counterpart(s) | Historical basis |
|---|---|---|
| Sudbury impact structure, Ontario | Apollo 16, Descartes highlands (Moon) | Apollo 16 crew trained here and recognised the Cayley breccia as impact breccia |
| Yungay, Atacama hyper-arid core | Viking 1 and Viking 2 landing sites (Mars) | Viking-style soil experiments on Yungay soils (Navarro-González et al. 2003) |
| Haughton crater, Devon Island | Shackleton crater (Moon), Phoenix landing site (Mars) | Haughton-Mars Project; the specific counterparts are our choice |

Every Earth site is paired with every planetary site, giving 15 edges (`data/out/pairs.csv`).
Five are true analogs and ten are wrong. A calibrated searcher should place true edges at a
lower distance than wrong ones.

## Status

| Dimension | Status |
|---|---|
| 2. Terrain (elevation, slope, roughness) | Implemented |
| 1, 3–8 | Not yet implemented; listed as `(not implemented)` in `coverage.csv` |

## Reproduce

Prerequisites: Python 3.12 and [uv](https://docs.astral.sh/uv/). GDAL ships inside the
`rasterio` wheel, so no system GDAL install is needed. Expect ~600 MB of network transfer for
terrain, most of it from the planetary mosaics. They store each row across the whole globe, so
even a small window reads every row it touches in full. Only ~120 MB stays on disk, mostly the
cached lunar polar DEM.

```bash
cd pipeline
uv sync                               # exact versions from uv.lock
uv run python run.py download all     # fetch every source around every site
uv run python run.py grid all         # per-cell statistics for each source
uv run python run.py merge            # fill gaps, write data/out/
uv run pytest                         # checks, including zonal spot-checks against the rasters
```

`run.py all <site>` runs all three steps for one site, and `--force` re-downloads cached data.
`merge` exits non-zero if any value could not be filled.

### Accounts

None are needed for terrain: every elevation source is publicly downloadable. Later
dimensions will need logins, read from a git-ignored `.env` (copy `.env.example`):

| Variable | Account | Used for |
|---|---|---|
| `EARTHDATA_USERNAME`, `EARTHDATA_PASSWORD` | [NASA Earthdata Login](https://urs.earthdata.nasa.gov) | HLS, ASTER, MODIS, SMAP, POWER |
| `CDSE_USERNAME`, `CDSE_PASSWORD` | [Copernicus Data Space](https://dataspace.copernicus.eu) | Sentinel-1/2/3 |
| `EODMS_USERNAME`, `EODMS_PASSWORD` | [CSA EODMS](https://www.eodms-sgdot.nrcan-rncan.gc.ca) | RADARSAT-1 (RCM is skipped unless openly accessible) |
| `GPORTAL_USERNAME`, `GPORTAL_PASSWORD` | [JAXA G-Portal](https://gportal.jaxa.jp) | GCOM-C, AMSR2, GSMaP |

## How the aggregation works

Each step below is a fixed rule. Changing any of them changes the output.

1. **Sites** (`sites.yaml`)
   - Latitudes are planetocentric and longitudes east-positive.
   - The Viking coordinates were published as planetographic and are converted; at ~48°N the
     difference is ~0.33° (~20 km on Mars).
   - Each site covers a fixed **25 km radius**.
2. **Grid** (`grid.py`)
   - The target is **~6 km² cells**, using the nearest H3 resolution on each body: Earth r7
     (~5.2 km²), Moon r6 (~2.7 km²), Mars r6 (~10.3 km²).
   - The same H3 resolution gives smaller cells on smaller bodies, because H3 fixes the
     number of cells, not their size.
   - H3's km-based helpers assume Earth's radius. All areas and distances are therefore
     computed in radians and scaled by the body radius (Moon 1737.4 km, Mars 3396.19 km,
     IAU 2015).
3. **Download** (`sources/`)
   - Each source is read only around the site (HTTP range requests), then averaged onto a
     square site-centred grid.
   - That grid uses an azimuthal equidistant projection, so the poles need no special case.
   - Terrain is resampled to a shared **200 m baseline** on every body: the native resolution
     of the coarsest primary elevation source (Mars HRSC + MOLA).
4. **Features** (`features.py`)
   - Elevation.
   - Slope, from the gradient at the 200 m baseline.
   - Terrain ruggedness index: mean absolute height difference to the 8 neighbouring pixels.
5. **Windows** (`aggregate.py`, `layers.py`)
   - **Cell window** (`elevation_m`): the pixels whose centres fall inside the H3 cell.
   - **Fixed window** (`slope_deg`, `tri_m`): a disk of exactly 6 km² (radius 1.38 km)
     centred on the cell. Scale-sensitive features are therefore measured over the same
     physical area on every body, even though cell sizes differ.
6. **Statistics:** each layer gets `mean`, `std`, `p10`, `p50` and `p90` per cell. A cell or
   window with fewer than 50% valid pixels counts as having no value for that source.
7. **Gap filling** (`merge.py`), in order:

   | `<layer>__source` | Meaning |
   |---|---|
   | `measured:<source>` | From the site's primary source |
   | `fallback:<source>` | From a lower-priority source for the same quantity, where the primary had no value |
   | `interpolated` | Mean of already-filled neighbouring cells, repeated outward. Used only when no source has a value |
   | `physical` | A known value where no source exists for the body (e.g. wind on the Moon = 0) |
   | `proxy:<layer>` | Another layer standing in for a quantity nothing measures (e.g. hydrated minerals for Mars habitability) |

### Terrain sources, in fill order

| Body | Source id | Product | Native res |
|---|---|---|---|
| Earth | `copdem30` | Copernicus DEM GLO-30 (AWS open data) | ~30 m |
| Moon (south pole) | `lola_polar20` | LRO LOLA LDEM_875S_20M, PDS Geosciences | 20 m |
| Moon | `lola118` | LRO LOLA global LDEM 118 m, USGS | ~118 m |
| Mars | `hrsc_mola200` | HRSC + MOLA blended DEM v2, USGS | 200 m |
| Mars | `mola463` | MGS MOLA global DEM, USGS | ~463 m |

Elevation datums differ by body (EGM2008 geoid, 1737.4 km sphere, MOLA areoid), so absolute
`elevation_m` isn't comparable across bodies; relief, slope and ruggedness are.

## Outputs (`data/out/`)

- **`<site>.parquet`:** one row per H3 cell, with:
  - the cell's position, `area_km2` and `dist_km` from the site centre
  - `<layer>__<stat>` columns
  - `<layer>__source` columns
- **`coverage.csv`:** one row per site and layer, giving how many cells came from each fill
  kind. Each of the 8 dimensions has at least one row per site. Dimensions with no layers yet
  have `status = not_implemented`, with every cell counted as `unfilled`. These rows don't make
  `merge` fail; only unfilled values in implemented layers do.
- **`pairs.csv`:** the 15 calibration edges, with `true` labels.
- **`manifest.json`:**
  - the git commit, the `uv.lock` hash and the settings used
  - per site and source: the product, its URL, ETag / Last-Modified / size at retrieval time,
    and the retrieval timestamp

To confirm a rerun used identical inputs, compare the source ETags in the new manifest with
the old one. The upstream mosaics are versioned files, so matching ETags mean identical
statistics.

## Expected results (terrain)

Cell counts per site: Sudbury 346, Atacama 378, Haughton 350, Apollo 16 663, Shackleton 679,
Viking 1 205, Viking 2 229, Phoenix 199. Every terrain value is filled.

## Extending

- **New site:** add it to `sites.yaml`, and add a true edge to `pairs.yaml` if it is a known
  analog.
- **New source:**
  1. Subclass `sources.base.Source`, implementing `fetch` (and `covers` if its coverage is
     partial). `sources.raster.warp_to_site` does the windowed read and reprojection.
  2. Register it in `sources/__init__.py`. Its position in the list is its fill priority.
- **New layer:**
  1. Add a `Layer` to `layers.py`.
  2. Add an extractor for its group in `features.py`.
  3. Where a body has no source for it, add a `KNOWN_ABSENT` value or a `PROXIES` stand-in.
