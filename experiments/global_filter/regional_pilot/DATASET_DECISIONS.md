# Dataset decisions as of 2026-11-14 (verification notes)

**Observation dates are not release dates. Never assert latest granule availability
based only on catalog temporal coverage.** Verify actual granule IDs during runs.

1. **NASA MODIS MCD12Q1.061 (annual 500m, global):** NASA LP DAAC staff
   confirmed 2025 observation-year product available October 20, 2026.
   Native MODIS sinusoidal HDF4; Earthdata Search + Earthdata login for direct
   granules. Google Earth Engine's catalog still displayed 2024 as the last
   indexed observation year at the time of review. NASA open data; attribution.
   Use for *coarse independent baseline*, not fine H3 fraction adjudication.
   Sources: https://forum.earthdata.nasa.gov/viewtopic.php?t=8231
   https://developers.google.com/earth-engine/datasets/catalog/MODIS_061_MCD12Q1

2. **Google Dynamic World V1 (near-real-time 10m; from 2015, through Nov 13,
   2026 in live catalog at review):** nine classes with probability bands;
   individual predictions correspond to optical Sentinel-2 scenes, with clouds
   and cloud shadows masked. Google Earth Engine ImageCollection
   `GOOGLE/DYNAMICWORLD/V1`; CC BY 4.0 with required attribution. Strongest for
   pilot and separate grass/shrub fractions. Coverage and observation count must
   be measured per AOI. Avoid a single arbitrary image as a "year" summary.
   Source: https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_DYNAMICWORLD_V1

3. **Impact Observatory / Esri 10m annual 9-class land cover (2017 onward):**
   ArcGIS ImageServer listed temporal extent through Dec 31, 2025; publicly
   documented AWS bucket/STAC registry still described downloadable COGs through
   2024. CC BY 4.0. Must confirm 2025 STAC tiles actually accessible before
   selecting it for pilot. Its `rangeland` class does not distinguish grass from
   shrubs. The source GeoTIFF must contain original class codes, not RGB.
   Sources: https://ic.imagery1.arcgis.com/arcgis/rest/services/Sentinel2_10m_LandCover/ImageServer
   https://registry.opendata.aws/io-lulc/

4. **NASA OPERA DSWx-HLS / DSWx-S1 (30m, near-global excluding Antarctica):**
   HLS record starts April 2023, S1 record September 2024. COG GeoTIFFs via
   Earthdata/PO.DAAC and CMR STAC. NASA open data with attribution. Dynamic
   surface-water detection useful for uncertain inland-water cases, but a
   single visit does not prove water permanence. Optical and SAR products are
   not fully harmonized. DIST-HLS and DIST-S1 are *disturbance* products, not
   complete static land-cover classifications; reserve them for later.
   Sources: https://www.jpl.nasa.gov/go/opera/products/
   https://www.jpl.nasa.gov/go/opera/products/dswx-product-suite/

5. **VIIRS snow:** Suomi NPP VNP10A1F V2 covers 2012 to 2026, but its
   spacecraft ceased new science observations Nov 2, 2026. Prefer continuing
   JPSS-1/NOAA-20 `VJ110A1F` (from 2018) or JPSS-2/NOAA-21 `VJ210A1F`
   (from 2023). Daily 375m sinusoidal HDF-EOS5, through Earthdata/NSIDC,
   citation required. Gap-filled snow is an estimate, and polar night creates
   observation limitations. Compute multi-season snow persistence; do not
   confuse snow with permanent glacial ice.
   Sources: https://nsidc.org/data/vj110a1f/versions/2
   https://nsidc.org/data/vj210a1f/versions/2
   https://nsidc.org/data/vnp10a1f/versions/2

6. **DLR/MindEarth World Settlement Footprint Tracker:** dataset released
   Nov 6, 2026, 10m, CC BY 4.0. Geographic stated extent -60 to 78 degrees
   latitude, despite "global" marketing. Historical biannual series through
   Jan 1, 2026 in publicly documented current GeoZarr asset; a 2026 release
   does not imply Nov 2026 observations. HTTP COG distribution also described.
   Useful for urban validation outside high latitudes, not a primary mission
   mask. Sources: https://e.geoservice.dlr.de/web/maps/eoc:wsf_tracker
   https://worldsettlementfootprint.com/raster-download

7. **GHSL:** 2025 release/projected epoch is not necessarily 2025 *observed*
   built-up data; e.g. EMC-BUILT R2025A draws from Sentinel-2 year 2022.
   EU reuse with attribution; various raster resolutions and downloads via
   GHSL wizard. Optional cross-check, not authoritative for observed 2025
   settlement alone.
   Source: https://human-settlement.emergency.copernicus.eu/downloadWizard.php

8. **ESA WorldCover:** excellent independent 10m 11-class map (trees, shrubs,
   grass, crops, bare, built, ice), but latest published classification map is
   2021 rather than a 2025/26 observation map. Use selectively for class-schema
   cross-check, not current change detection. COG delivery, open attribution.
   Source: https://esa-worldcover.org/en/data-access

The prototype currently supports Dynamic World 0..8 labels and the Esri/IO
9-class codes. It does **not** download Earth Engine or STAC assets itself.
