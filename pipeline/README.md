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
| Black Point Lava Flow, Arizona | Apollo 15, Hadley Rille (Moon) | NASA Desert RATS simulated lunar missions on basalt lava terrain (2008–2012); the counterpart is our choice |
| Dumont Dunes, California | Bagnold Dunes, Gale crater (Mars) | Curiosity's "Scarecrow" test rover drove these dunes (2012) to plan driving at the Bagnold dunes |

Contributors and coding agents: [AGENTS.md](AGENTS.md) records the current state, the
decisions made so far and who made them, open questions, and known pitfalls.

Every Earth site is paired with every planetary site, giving 70 edges (`data/out/pairs.csv`). Five Earth sites are random controls (`rand_*`, seeded random land points) with no analog association, so all their edges are wrong:
7 true analogs and 28 wrong. A calibrated searcher should place true edges at a
lower distance than wrong ones.

## Status

| Dimension | Status |
|---|---|
| 1. Geology: FeO (`feo_wt_pct`) | Implemented for the Moon and Mars. Empty on Earth (no source yet) and at Phoenix (polar mask); gaps allowed |
| 1. Geology: albedo (`albedo`) | Implemented, every cell filled (4 Haughton cells interpolated) |
| 2. Terrain (elevation spread, slope, roughness) | Implemented, every cell filled |
| 3. Temperature (day max, night max, night min, mean) + sunlight | Implemented for all 17 sites, every cell filled (Mars from model output) |
| 5. Weather (mean pressure, mean and max wind) | Implemented for all 17 sites: Earth measured, Moon known-absent 0, Mars model |
| 4, 6–8 | Not yet implemented; listed as `not_implemented` in `coverage.csv` |

A preliminary feature-importance study of the merged features is in
[analysis/feature_importance.md](analysis/feature_importance.md). Reproduce it with
`python -m uv run python analysis/feature_importance.py`.
The latest run covers all 35 edges (5 Earth × 7 targets) and all built dimensions:
[analysis/runs/2026-11-14_full-35-edges/report.md](analysis/runs/2026-11-14_full-35-edges/report.md).
Each feature is scored alone as a distance: |site-mean difference| / SD of the site means, or
1-D Wasserstein / pooled SD. The best AUC is 0.57 (p ≥ 0.18), so no single feature separates
true from wrong edges.
With the 5 random controls (70 edges, [run](analysis/runs/2026-11-14_with-random-controls/)) the best is
`albedo__p10` at AUC 0.64 (p 0.08). Random-control edges are farther than analog-site edges, but
true and wrong analog edges are equally close.

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
Missing features at some locations are allowed (user decision). Every layer has `allow_gaps=True` unless set otherwise, so `merge` reports leftover gaps in `coverage.csv` and still exits 0. It exits non-zero only for unfilled values in a layer explicitly marked `allow_gaps=False` (none currently).

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
6. **Statistics:** each layer gets `mean`, `std`, `p10`, `p50` and `p90` per cell, unless
   the layer keeps only a subset (`Layer.stats`). A cell or window with fewer than 50% valid
   pixels counts as having no value for that source.
   - **Albedo (`albedo`)** is the fraction of light reflected, 0–1. Each body uses its best
     calibrated product, and the definitions aren't identical:
     - Earth: broadband shortwave albedo from Sentinel-2. Liang (2001) weights:
       0.356·B2 + 0.130·B4 + 0.373·B8 + 0.085·B11 + 0.072·B12 − 0.0018. It's the per-pixel
       median of clear scenes, with cloud, shadow and snow removed using the scene
       classification (SCL) band.
     - Moon: LOLA 1064 nm normal albedo. It's an active laser measurement, so it also works in
       permanently shadowed craters.
     - Mars: TES bolometric Lambert albedo (~0.3–2.9 µm).

     Sentinel-2 seasons (snow-free, mostly clear):
     - Sudbury: Jul–Aug 2023 and 2024
     - Haughton: 15 Jul–25 Aug 2023 and 2024
     - Atacama: Nov 2023–Mar 2024
     - Black Point, Dumont: Apr–Oct 2023
     - Random controls: Jul–Aug 2023/2024 (NWT, Québec), Jun–Sep 2023/2024 (Kunlun),
       Jul–Oct 2023/2024 dry season (Amazon), Apr–Oct 2023 (Oklahoma)
   - **Temperature** (`temp_*_k`): from a year of surface temperature samples. Day is local
     solar time 6–18 h; night is the rest.
     - Day max: maximum of the day samples. Night max and night min: maximum and minimum of
       the night samples. Mean: average of all samples.
     - Earth uses hourly reanalysis, the Moon Diviner's 15-min local-time bins, and Mars
       1.5-hourly model output (every 6th 10-sol file, so its extremes are slightly too mild).
   - **Sunlight** (`insolation_wm2`): annual-mean top-of-atmosphere insolation, the same
     orbital calculation on every body. It ignores terrain shadowing and atmosphere, so
     Shackleton's real illumination is not captured.
   - **Weather** (`pressure_mean_pa`, `wind_mean_ms`, `wind_max_ms`): Earth wind at 10 m,
     Mars wind at the lowest GCM layer, Moon known-absent 0 (no atmosphere).
   - **`feo_wt_pct` keeps only `mean`:** the gamma-ray bins (60–300 km) are larger than the whole site, so spread and percentiles carry no information.
   - **`elevation_m` keeps only `std`** (within-cell relief). Each body measures height from a
     different reference (EGM2008 geoid, 1737.4 km sphere, MOLA areoid), so absolute heights
     (mean, percentiles) aren't comparable across bodies and are dropped.
7. **Gap filling** (`merge.py`), in order:

   | `<layer>__source` | Meaning |
   |---|---|
   | `measured:<source>` | From the site's primary source |
   | `fallback:<source>` | From a lower-priority source for the same quantity, where the primary had no value |
   | `interpolated` | Mean of already-filled neighbouring cells, repeated outward. Used only when no source has a value |
   | `physical` | A known value where no source exists for the body (e.g. wind on the Moon = 0) |
   | `proxy:<layer>` | Another layer standing in for a quantity nothing measures (e.g. hydrated minerals for Mars habitability) |

   Gaps are allowed by default (`Layer.allow_gaps=True` in `layers.py`). Fallbacks and
   interpolation still run first. Cells nothing can reach stay empty, shown as `<NA>` in
   `<layer>__source` and as `unfilled` in `coverage.csv`. The searcher has to handle missing
   values.

## Datasets

### Used by the pipeline

Every dataset below is read directly by `run.py download`, with no login and no manual
download. Source ids match the files in `data/raw/<site>/` and the keys in `manifest.json`.
Within each body, sources are listed in fill order (primary first).
`data/README.md` maps each source id to the output feature columns it produces. It sits in
the git-ignored data folder so it travels with the data.

#### Full datasets (entire products)

Use these to get or inspect a whole dataset; the pipeline never needs the full download.

| Source id | Dataset | Native res | Height reference | Entire dataset | Landing page / docs |
|---|---|---|---|---|---|
| `copdem30` | Copernicus DEM GLO-30, ESA / Airbus | 1″ (~30 m) | EGM2008 geoid | S3 bucket `s3://copernicus-dem-30m/`: 26,450 global 1° COG tiles, listed in [tileList.txt](https://copernicus-dem-30m.s3.amazonaws.com/tileList.txt) | [AWS registry](https://registry.opendata.aws/copernicus-dem/), [bucket readme](https://copernicus-dem-30m.s3.amazonaws.com/readme.html), [Copernicus Data Space](https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM) |
| `lola_polar20` | LRO LOLA LDEM_875S_20M, polar stereographic, 87.5°S to pole | 20 m | 1737.4 km sphere | [ldem_875s_20m.img](https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/polar/img/ldem_875s_20m.img) (115 MB) + [.lbl](https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/polar/img/ldem_875s_20m.lbl); [all LOLA polar products](https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/polar/img/) | [PDS Geosciences LOLA page](https://pds-geosciences.wustl.edu/missions/lro/lola.htm) |
| `lola118` | LRO LOLA global LDEM 118 m, Mar 2014 | ~118 m | 1737.4 km sphere | [Lunar_LRO_LOLA_Global_LDEM_118m_Mar2014.tif](https://planetarymaps.usgs.gov/mosaic/Lunar_LRO_LOLA_Global_LDEM_118m_Mar2014.tif) (8.5 GB) | [USGS Astropedia](https://astrogeology.usgs.gov/search/map/moon_lro_lola_dem_118m) |
| `hrsc_mola200` | Mars Express HRSC + MGS MOLA blended DEM v2 | 200 m | MOLA areoid | [Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif](https://planetarymaps.usgs.gov/mosaic/Mars/HRSC_MOLA_Blend/Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif) (11.4 GB) | [USGS Astropedia](https://astrogeology.usgs.gov/search/map/mars_mgs_mola_mex_hrsc_blended_dem_global_200m) |
| `mola463` | MGS MOLA global DEM | ~463 m | MOLA areoid | [Mars_MGS_MOLA_DEM_mosaic_global_463m.tif](https://planetarymaps.usgs.gov/mosaic/Mars_MGS_MOLA_DEM_mosaic_global_463m.tif) (2.1 GB) | [USGS Astropedia](https://astrogeology.usgs.gov/search/map/mars_mgs_mola_dem_463m) |
| `s2_albedo` | Sentinel-2 L2A surface reflectance, Cloud-Optimized GeoTIFFs (ESA Copernicus, hosted by AWS / Element 84) | 10–20 m | — | Whole archive: `s3://sentinel-cogs/sentinel-s2-l2a-cogs/`, searchable via the [Earth Search STAC API](https://earth-search.aws.element84.com/v1/collections/sentinel-2-l2a) | [AWS registry](https://registry.opendata.aws/sentinel-2-l2a-cogs/) |
| `lola_albedo_s1000` | LRO LOLA 1064 nm normal albedo, LDAM_50S_1000M (float), 50°S to pole | 1 km | — | [LDAM_50S_1000M_FLOAT.IMG](https://imbrium.mit.edu/DATA/LOLA_GDR/POLAR/FLOAT_IMG/LDAM_50S_1000M_FLOAT.IMG) + [.LBL](https://imbrium.mit.edu/DATA/LOLA_GDR/POLAR/FLOAT_IMG/LDAM_50S_1000M_FLOAT.LBL); [all polar float products](https://imbrium.mit.edu/DATA/LOLA_GDR/POLAR/FLOAT_IMG/) | [LOLA GDR albedo index](https://imbrium.mit.edu/BROWSE/LOLA_GDR/ALBEDO/) |
| `lola_albedo_10ppd` | LRO LOLA 1064 nm normal albedo, LDAM_10 (float), global | 10 px/deg (~3 km) | — | [LDAM_10_FLOAT.IMG](https://imbrium.mit.edu/DATA/LOLA_GDR/CYLINDRICAL/FLOAT_IMG/LDAM_10_FLOAT.IMG) + [.LBL](https://imbrium.mit.edu/DATA/LOLA_GDR/CYLINDRICAL/FLOAT_IMG/LDAM_10_FLOAT.LBL); [all cylindrical float products (4/8/10 ppd)](https://imbrium.mit.edu/DATA/LOLA_GDR/CYLINDRICAL/FLOAT_IMG/) | [LOLA GDR albedo index](https://imbrium.mit.edu/BROWSE/LOLA_GDR/ALBEDO/) |
| `tes_albedo` | MGS TES Lambert albedo global mosaic | ~7.4 km | — | [Mars_MGS_TES_Albedo_mosaic_global_7410m.tif](https://planetarymaps.usgs.gov/mosaic/Mars_MGS_TES_Albedo_mosaic_global_7410m.tif) (17 MB) | [USGS planetary maps](https://planetarymaps.usgs.gov/mosaic/Mars_MGS_TES_Albedo_mosaic_global_7410m.tif) |
| `power_ts_hourly` | NASA POWER hourly earth skin temperature `TS` (MERRA-2 reanalysis), 2023, local solar time | 0.5° × 0.625° (~55 km) | — | Any point via the [POWER hourly API](https://power.larc.nasa.gov/api/temporal/hourly/point?parameters=TS&community=RE&latitude=46.6&longitude=-81.2&start=20230101&end=20231231&format=JSON&time-standard=LST) (example: Sudbury); global grids via the [POWER Data Access Viewer](https://power.larc.nasa.gov/data-access-viewer/) | [NASA POWER docs](https://power.larc.nasa.gov/docs/) |
| `power_weather_hourly` | NASA POWER hourly surface pressure `PS` and 10 m wind `WS10M`, 2023 | 0.5° × 0.625°, hourly | — | Same API, `parameters=PS,WS10M` | [NASA POWER docs](https://power.larc.nasa.gov/docs/) |
| `diviner_gcp` | LRO Diviner Global Cumulative Products (Williams et al. 2017): bolometric temperature per 0.5° cell and 15-min local-time bin, 2009–2015 | 0.5° (~15 km), 0.25 h | — | [All 18 latitude-band tables](https://pds-geosciences.wustl.edu/lro/urn-nasa-pds-lro_diviner_derived1/data_derived_gcp/) (~156 MB each); used: `global_cumul_avg_cyl_10s00s_002.tab` (Apollo 16), `global_cumul_avg_cyl_90s80s_002.tab` (Shackleton) | [PDS Geosciences Diviner](https://pds-geosciences.wustl.edu/missions/lro/diviner.htm) |
| `mgcm_tsurf`, `mgcm_weather` | NASA Ames Legacy Mars GCM, ACTIVECLDS reference run (Haberle et al. 2019), one Mars year: `tsurf`, `psurf`, lowest-layer `ucomp`/`vcomp` (also `dst_mass`, `h2o_vap_mass` for later). Model output, not measurements | 5° × 6°, 1.5 h | — | [67 × ~293 MB NetCDF-3 files](https://data.nas.nasa.gov/legacygcm/legacygcm/ACTIVECLDS_NCDF/) (~20 GB), plus a one-year concatenation | [MCMC data portal](https://data.nas.nasa.gov/mcmcref/legacygcm/), [README](https://data.nas.nasa.gov/legacygcm/legacygcm/README_Legacy.txt) |
| `orbital_insolation` | Annual-mean top-of-atmosphere sunlight computed from latitude and orbital elements (solar constant 1361 W/m²) | analytic | — | Computed in `sources/climate.py`; nothing to download | — |
| `lp_grs_feo` | Lunar Prospector GRS elemental abundances (MgO, Al₂O₃, SiO₂, CaO, TiO₂, FeO, K, Th, U), high-altitude phase; column `W_FEO` (g/g) is used | 2° equal-area bins (~60 km) | — | [All bin sizes (2°/5°/20°) + labels](https://pds-geosciences.wustl.edu/Lunar/lp-l-grs-5-elem-abundance-v1/lp_9001/data/); used: [lpgrs_high1_elem_abundance_2deg.tab](https://pds-geosciences.wustl.edu/Lunar/lp-l-grs-5-elem-abundance-v1/lp_9001/data/lpgrs_high1_elem_abundance_2deg.tab) (10 MB) | [PDS Geosciences Lunar Prospector](https://pds-geosciences.wustl.edu/missions/lunarp/) |
| `ody_grs_fe` | Mars Odyssey GRS element concentrations (Cl, Fe, H₂O, K, Si, Th); Fe wt%, ×1.2865 → FeO-equivalent | 5° bins, boxcar-smoothed (~300 km); poles masked (`9999.999`) | — | [Smoothed + unsmoothed (2°/5°/10°) tables](https://pds-geosciences.wustl.edu/ody/ody-m-grs-5-elements-v1/odgm_xxxx/data/); used: [fe_sr_5x5.tab](https://pds-geosciences.wustl.edu/ody/ody-m-grs-5-elements-v1/odgm_xxxx/data/smoothed/fe_sr_5x5.tab) | [PDS Geosciences Odyssey GRS](https://pds-geosciences.wustl.edu/missions/odyssey/grs_elements.html) |

#### Cropped versions (what the pipeline reads per site)

The pipeline reads only a ~62 km square around each site (25 km radius plus margin), over
HTTP range requests. It saves that square locally, averaged to 200 m on a site-centred map.
These crops aren't hosted anywhere; rebuild them with `run.py download <site>`.

| Source id | Sites | What is fetched | Local crop |
|---|---|---|---|
| `copdem30` | all Earth sites (analogs and `rand_*` controls) | Only the 1° tiles touching the site: `https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_<N\|S><lat>_00_<E\|W><lon>_00_DEM/…_DEM.tif`, e.g. [N46 W082](https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_N46_00_W082_00_DEM/Copernicus_DSM_COG_10_N46_00_W082_00_DEM.tif) for Sudbury. Exact tiles per site are in `manifest.json` | `data/raw/<site>/copdem30.tif` |
| `lola_polar20` | shackleton | Whole file, downloaded once (small), cached in `data/raw/_shared/lola_polar/` | `data/raw/shackleton/lola_polar20.tif` |
| `lola118` | apollo16, shackleton (fallback) | Rows covering the site window only (~65–100 MB of the 8.5 GB file) | `data/raw/<site>/lola118.tif` |
| `hrsc_mola200` | viking1, viking2, phoenix | Rows covering the site window only (~67 MB per site) | `data/raw/<site>/hrsc_mola200.tif` |
| `mola463` | viking1, viking2, phoenix (fallback) | Rows covering the site window only (~13 MB per site) | `data/raw/<site>/mola463.tif` |
| `s2_albedo` | all Earth sites (analogs and `rand_*` controls) | STAC search over the site box for the season below (cloud < 20%), lowest-cloud first, up to 32 scenes. Per scene: SCL + 5 bands read through COG overviews at ~160 m, averaged to 200 m. Scene ids and dates are in `data/raw/<site>/s2_albedo.json` and `manifest.json` | `data/raw/<site>/s2_albedo.tif` |
| `lola_albedo_s1000` | shackleton | Window of the polar map | `data/raw/shackleton/lola_albedo_s1000.tif` |
| `lola_albedo_10ppd` | apollo16, shackleton (fallback) | Window of the global map | `data/raw/<site>/lola_albedo_10ppd.tif` |
| `tes_albedo` | viking1, viking2, phoenix | Window of the global map | `data/raw/<site>/tes_albedo.tif` |
| `power_ts_hourly`, `power_weather_hourly` | all Earth sites (analogs and `rand_*` controls) | One year of hourly values for each POWER grid cell touching the site (1–4 cells), via the API. Query URLs in `manifest.json` | `data/raw/<site>/power_*.tif` (multi-band) |
| `diviner_gcp` | apollo16, shackleton | The site's 10° band table, downloaded once to `data/raw/_shared/diviner/`, reduced per 0.5° cell | `data/raw/<site>/diviner_gcp.tif` (4 bands) |
| `mgcm_tsurf`, `mgcm_weather` | viking1, viking2, phoenix | Every 6th file (12 of 67, ~3.5 GB), each reduced on the whole GCM grid then deleted. Result cached in `data/raw/_shared/mgcm/mgcm_climatology_step6.npz` (per-file partials in `partials/`). Interpolated bilinearly to the site | `data/raw/<site>/mgcm_*.tif` |
| `orbital_insolation` | all 8 | Computed per pixel from latitude | `data/raw/<site>/orbital_insolation.tif` |
| `lp_grs_feo` | apollo16, shackleton | Whole table, downloaded once, cached in `data/raw/_shared/geochem/`; bins rasterised onto a 500 m site grid | `data/raw/<site>/lp_grs_feo.tif` |
| `ody_grs_fe` | viking1, viking2, phoenix | Whole table, downloaded once, cached in `data/raw/_shared/geochem/`; bins rasterised onto a 500 m site grid | `data/raw/<site>/ody_grs_fe.tif` (all empty for phoenix) |

Notes:

- **Scaling:** LOLA files store heights as integer counts × 0.5 m. The polar label also gives
  an `OFFSET` equal to the 1737.4 km reference radius, which the pipeline deliberately
  ignores so values stay heights rather than radii.
- **Height references differ by body**, so only within-cell elevation spread
  (`elevation_m__std`), slope and ruggedness are output; absolute heights are not.
- **Licences:**
  - The Copernicus DEM is free to use with attribution: "© DLR e.V. 2010–2014 and © Airbus
    Defence and Space GmbH 2014–2018, provided under COPERNICUS by the European Union and ESA."
  - The NASA/USGS planetary products are public domain.

### Evaluated for dimension 1 (geology), not yet used

All links below were checked for this pipeline but aren't wired in yet. See the status
column.

| Body | Dataset | Native res | Link | Status |
|---|---|---|---|---|
| Moon | Clementine UVVIS 750 nm global mosaic | ~118 m | [Lunar_Clementine_UVVIS_750nm_Global_Mosaic_118m_v2.tif](https://planetarymaps.usgs.gov/mosaic/Lunar_Clementine_UVVIS_750nm_Global_Mosaic_118m_v2.tif) | Rejected: 8-bit display image, not calibrated reflectance |
| Moon | LRO LOLA roughness maps (LDRM), global 16 ppd and polar 1 km | ~1–2 km | [ldrm_16.lbl](https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/cylindrical/img/ldrm_16.lbl), [ldrm_40s_1000m.lbl](https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/polar/img/ldrm_40s_1000m.lbl) | Not geology; possible later input for terrain/landing (#2, #8) |

No orbital FeO map exists for Earth. **Decided:** Earth FeO will come from published
ground-sample geochemistry, one value per Earth site (not yet sourced or built).

### Site coordinates

These come from published references and are listed per site in `sites.yaml`: the Earth
Impact Database, Navarro-González et al. (2003), NASA Apollo 16 records, the USGS Gazetteer
of Planetary Nomenclature (Shackleton), the Viking 1 location revised by Morris & Jones
(1980), and the Viking 2 and Phoenix landing records.

## Global Earth exclusion mask (`analysis/global_mask.py`)

Whole-Earth, pixel-by-pixel filter (no H3 grid) that removes every 0.05° pixel (~5.6 km at the
equator; the VIIRS CMG grid, the coarsest input) that is **ocean**, **densely populated** or
**densely vegetated**. Areas are exact spherical pixel areas.

| Rule | Data | Removed when |
|---|---|---|
| Ocean | [Natural Earth 1:10m land](https://www.naturalearthdata.com/) (GeoJSON), pixel-centre test | outside land (lakes count as land; the Caspian counts as ocean) |
| Populated | [GHSL GHS-POP R2023A](https://human-settlement.emergency.copernicus.eu/), epoch 2020, 30″, summed per pixel | ≥ 50 people/km² (GHSL "very low density rural" bound) |
| Vegetated | [VIIRS VNP13C2 v002](https://lpdaac.usgs.gov/products/vnp13c2v002/) monthly NDVI 0.05°, 2023 peak | peak NDVI ≥ 0.5 (dense: forest, crops) |

```bash
uv run python analysis/global_mask_download.py   # ~2.3 GB; VIIRS needs EARTHDATA_TOKEN in .env
uv run python analysis/global_mask.py            # ~25 s
```

Result (2026-11-14), in `data/out/global_mask/` (`summary.json`, `exclusion_flags.tif` bits
1 ocean / 2 populated / 4 vegetated, `kept.tif`, `map_before_land.png`, `map_after_filtered.png`,
`map_reasons.png`):

| | Area (M km²) |
|---|---|
| Earth | 510.07 |
| Land | 146.74 |
| Kept | **56.38** (44.12 excluding south of 60°S) |

Reduction: **88.9 % vs the whole Earth**, **61.6 % vs land**, 67.2 % vs land excluding
Antarctica. Vegetation removes 88.4 M km² of land and population 15.6 M km² (13.6 overlap).
Kept land holds 59 M of 7.84 bn people. Earth analog sites kept: Atacama, Haughton, Black
Point, Dumont, rand_kunlun. Removed (vegetation): **Sudbury** (peak NDVI 0.83) and four random
controls. Known caveat: large lakes (Great Lakes, Victoria) are kept, since they are inside the
land polygons and not green.

## Elevation at Earth-r8 size (`analysis/elevation_r8.py`)

Every site's elevation recomputed from the original DEM products onto square pixels with the
area of Earth's mean H3 r8 cell (0.7373 km², **858.68 m** side). The **same physical size is
used on the Moon and Mars** (H3 r8 there would be smaller cells). Area-average resampling, same
site-local grid and source fill order as the pipeline; 71 × 71 px per site, all 17 sites 100 %
valid. Outputs: `data/out/elevation_r8/<site>.tif` (band 1 `elevation_m`, band 2
`source_index`), per-source rasters + provenance, `summary.csv`, and
`data/export/elevation_r8_all_sites.zip`. Run: `uv run python analysis/elevation_r8.py all`
(~9 min, remote range reads).

## Outputs (`data/out/`)

- **`<site>.parquet`:** one row per H3 cell, with:
  - the cell's position, `area_km2` and `dist_km` from the site centre
  - `<layer>__<stat>` columns
  - `<layer>__source` columns
- **`coverage.csv`:** one row per site and layer, giving how many cells came from each fill
  kind. Each of the 8 dimensions has at least one row per site. Dimensions with no layers yet
  have `status = not_implemented`, with every cell counted as `unfilled`. The `gaps_allowed`
  column marks layers allowed to stay partly empty. Neither kind of row makes `merge` fail;
  only unfilled values in other implemented layers do.
- **`pairs.csv`:** the 15 calibration edges, with `true` labels.
- **`manifest.json`:**
  - the git commit, the `uv.lock` hash and the settings used
  - per site and source: the product, its URL, ETag / Last-Modified / size at retrieval time,
    and the retrieval timestamp

To confirm a rerun used identical inputs, compare the source ETags in the new manifest with
the old one. The upstream mosaics are versioned files, so matching ETags mean identical
statistics.

## Expected results

- **Cell counts per site:**
  - Earth: Sudbury 346, Atacama 378, Haughton 350, Black Point 338, Dumont 343
  - Moon: Apollo 16 663, Shackleton 679, Apollo 15 697
  - Mars: Viking 1 205, Viking 2 229, Phoenix 199, Bagnold 165
- **Terrain:** every value filled.
- **Temperature, sunlight and weather** (site averages; K, W/m², Pa, m/s):

  | Site | Day max | Night max | Night min | Mean | Sunlight | Pressure | Wind mean / max |
  |---|---|---|---|---|---|---|---|
  | Sudbury | 305.5 | 300.4 | 231.8 | 277.9 | 300 | 97,330 | 2.4 / 7.8 |
  | Atacama | 318.6 | 294.6 | 273.6 | 293.0 | 383 | 82,490 | 3.6 / 9.7 |
  | Haughton | 286.4 | 283.1 | 227.6 | 257.9 | 185 | 99,350 | 3.9 / 13.6 |
  | Apollo 16 | 388.1 | 127.0 | 93.2 | 200.7 | 428 | 0 | 0 / 0 |
  | Shackleton | 211.2 | 170.0 | 55.5 | 118.6 | 12 | 0 | 0 / 0 |
  | Viking 1 | 277.8 | 219.8 | 184.5 | 219.7 | 167 | 780 | 7.7 / 21.6 |
  | Viking 2 | 267.7 | 221.7 | 153.3 | 198.1 | 128 | 866 | 5.9 / 21.4 |
  | Phoenix | 249.3 | 228.2 | 149.1 | 180.7 | 91 | 822 | 10.5 / 33.2 |

  New sites (site averages):

  | Site | Albedo | FeO wt% | Slope ° | Day max K | Night min K | Mean K | Sunlight | Pressure Pa | Wind mean |
  |---|---|---|---|---|---|---|---|---|---|
  | Black Point | 0.18 | — | 2.5 | 322.3 | 257.1 | 285.9 | 345 | 84,450 | 3.4 |
  | Dumont | 0.23 | — | 5.2 | 331.0 | 266.8 | 290.9 | 345 | 89,990 | 3.6 |
  | Apollo 15 | 0.22 | 13.2 | 10.5 | 381.0 | 91.8 | 197.4 | 389 | 0 | 0 |
  | Bagnold | 0.23 | 19.3 | 6.1 | 289.5 | 181.7 | 222.7 | 178 | 635 | 7.1 |

  Apollo 15's FeO (13%, mare basalt) is about twice Apollo 16's (6%, highlands), as expected.
  Bagnold's 635 Pa is below what Curiosity measures on the Gale floor (~700–900 Pa). The GCM's
  5° × 6° cell averages the deep crater floor with Mount Sharp and the surrounding highlands.
  Mars pressures match the landers (Viking 1 measured ~690–900 Pa). Phoenix's night minimum
  sits at the CO₂ frost point (~148 K).
- **Albedo (`albedo__mean`, site average):**
  - Earth: Sudbury 0.12 (forest and lakes), Atacama 0.28, Haughton 0.23
  - Moon: Apollo 16 0.29, Shackleton 0.38
  - Mars: Viking 1 0.22, Viking 2 0.24, Phoenix 0.20
  - All cells filled; 4 Haughton cells had no clear look and are interpolated.
- **FeO (`feo_wt_pct__mean`):**
  - Apollo 16: 4.8–6.8 wt% (mean 6.0)
  - Shackleton: 4.5–5.3 (mean 4.9)
  - Viking 1: 19.9; Viking 2: 18.5. One value per site, because a 5° bin covers it.
  - Empty at the 3 Earth sites and Phoenix (1,273 cell values, all expected).

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
