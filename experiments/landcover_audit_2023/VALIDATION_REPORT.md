# Does the prefilter keep the analogs and drop the rest? Site validation and H3 r7 readiness

*2026-11-15. Scripts `scripts/05`–`08`, numbers in `results/`. Local data only, nothing downloaded,
no global H3 cells generated, the teammate's pipeline read but not changed.*

**Recommendation: GO WITH LIMITATIONS** for a regional H3 r7 pilot (reasons in §7).

## How to read this

- **The filter tested** is the teammate's v2 rule (`global_mask_v2.py`, commit `475bf4e`),
  re-applied from local data: Natural Earth land, GHSL 2020 population (≥ 50 people/km² removes)
  and MODIS MCD12Q1 2023. The v2 run also averaged in Esri 10 m land cover, and Esri is **not on this
  laptop**. Every decision below is therefore "v2, MODIS-only". Sanity check: the land-cover part
  reproduces the audit's P1 total exactly (94,029,740 km²).
- **Esri sensitivity.** v2 averages MODIS and Esri with equal weight. A site whose MODIS non-analog
  share is *m* flips only if Esri's share is at least 1 − *m*. For the barren analog sites *m* = 0,
  so Esri would have to call them 100% vegetation or water. Those decisions are robust.
- **The consultation** is [Spacethropic_Landcover_Consultation_2026-11-15.md](Spacethropic_Landcover_Consultation_2026-11-15.md).
  §6b answers its checks one by one. Its mission profiles map to the ones used here:
  - Profile A (exposed surface, Moon-like) = MOON_SURF
  - Profile B (Mars field operations) = MARS_DRY
  - Profile C (polar/icy) = MARS_ICE
  - FIELD_GEO is added for sites used for crew geology training or subsurface access.

  The gate and validation design also follow the 13 Nov research consultation (§4 and §10).

## 1. Downstream ranking: it does not exist yet

The prefilter is currently the **only** land-cover, vegetation or human-disturbance check in the
system. Every branch was searched (`main`, `data/cleaning`, `frontend`, `feat/terrain-database`,
this branch):

| Component | What it does | Land-cover / vegetation / human check? |
|---|---|---|
| `frontend/src/lib/search.ts` (`origin/frontend`) | POSTs to `/api/search`. That route doesn't exist, so it falls back to a fixed sample list (`candidates.ts`, `SAMPLE_ORDER`) | None. "Relevance and match explanations arrive with the real search logic" |
| `pipeline/AGENTS.md` (`data/cleaning`) | "weighting and the searcher itself are out of scope so far"; "Searcher weighting: deferred" | n/a |
| `pipeline/analysis/feature_importance.py` | Scores single features on 35/70 calibration edges (AUC) | Evaluation only, not a ranker |
| `research/nasadem_h3_pilot/.../database.py` `terrain_selection` | "NOT an eligible/matcher selection", `ORDER BY h3_cell` | None. `INTEGRATION_STATUS.md`: "No real search, mask join ... or matcher invocation" |
| Earth hexagon tables (`contours_r8.py` `HEX_SCHEMA`, `hex_terrain.py`, `hex_features.py`) | Columns: `removed_frac`, elevation, contour count, slope/TRI stats, temperature, weather, insolation | **Only `removed_frac`** (share of the hexagon in removed mask pixels). No class shares, NDVI, population or reason bits. Albedo and FeO are Moon/Mars only (`BODIES` rule) |

So a false positive that passes the mask (grassland, savanna, tundra, ice sheet) enters the H3
database with nothing downstream that could reject it.

## 2. Site validation (30 points)

Script `05_site_validation.py`; full table in `results/site_validation.csv`, per-pixel detail in
`results/site_validation_detail.json`. "Pixel" means the 0.05° mask pixel that holds the documented
coordinate. "Region" means every pixel within 10 km (Drumheller: the NASADEM pilot box). Mission
profiles are defined in `scripts/validation_sites.py`. Each site is judged only against the profile
it is documented for.

### Analogs

| Site (profile) | Pixel decision | Region kept | MODIS 0.05° pixel | Peak NDVI | Missing / QC | Reasonable? |
|---|---|---:|---|---:|---|---|
| Atacama, Yungay (MARS_DRY) | kept | 100% | barren 100% | 0.09 | none | **Yes**, robust |
| Hanksville, MDRS (MARS_DRY) | kept | 100% | barren 100% | 0.11 | none | **Yes**, robust |
| Dumont Dunes (MARS_DRY) | kept | 100% | barren 100% | 0.08 | none | **Yes** |
| Lut, Dalangtan, Dallol (MARS_DRY) | kept | 100% | barren 100% | 0.05–0.10 | none | **Yes** |
| **Drumheller badlands** (MARS_DRY) | **removed: populated** (GHSL 287/km², the town) | 37.5% | grass 48%, crop 46%, urban 7% | 0.41 | none | **Partly.** 22 of 36 rugged NASADEM r8 cells (slope ≥ 10°) are kept, and 3 of 4 rugged r7 cells. MODIS sees **no barren at 500 m**: the badlands are narrower than a MODIS pixel. The kept pixels survive only because grassland counts as analog, and with 24–47 people/km², just under the cut. Esri could remove them (it would need ≥ 0.57–0.79 non-analog) |
| Mauna Kea summit (MOON_SURF) | kept | 100% | barren 90% | 0.07 | none | **Yes** |
| Mauna Kea, Hale Pōhaku 2,800 m (MOON_SURF) | kept | 100% | barren 57%, grass 30% | 0.24 | none | **Yes**. Nearby lava next to closed shrubland is removed (§4) |
| Black Point Lava Flow (MOON_SURF) | kept | 100% | grass 78%, open shrub 21%, barren 1% | 0.25 | none | **Yes, but only because grassland counts as analog** |
| Craters of the Moon, Kilbourne Hole, Pinacate (MOON_SURF) | kept | 100% | barren 59% / open shrub 98% / open shrub 46% | 0.16–0.31 | none | **Yes** |
| Beacon Valley, McMurdo (MARS_ICE) | kept | 100% | **snow/ice 74%**, barren 23% | no valid month | **QC=6 on 92% of region pixels** | **Yes for MARS_ICE**, but the ice-free valley is labelled ice (§3) |
| Don Juan Pond, McMurdo (MARS_ICE) | kept | 100% | snow/ice 70%, barren 30% | no valid month | QC=6 on 82% | **Yes for MARS_ICE**, same caveat |
| Haughton crater (MARS_ICE) | kept | 100% | barren 97% | 0.16 (10/12 months) | none | **Yes** |
| Bockfjord, Svalbard (MARS_ICE) | removed: water (fjord 85%) | 67.9% | water 85%, barren 15% | 0.23 (9/12) | QC=2 on most of the pixel | **Yes at region level.** The coordinate is approximate and falls in the fjord. 15 of 19 r7 cells are kept. Two pixels are removed as "urban" with zero population (a MODIS urban-class artefact) |
| Lava Beds (FIELD_GEO) | kept | 93% | grass 100% | 0.32 | none | Yes (lava tubes) |
| Rio Tinto (FIELD_GEO) | removed: built 26% (Minas de Riotinto) | 68.7% | savanna, grass, urban | 0.38 | none | Partly. Removed for human disturbance |
| Sudbury (FIELD_GEO) | removed: vegetated | 0% | forest 100% | 0.83 | none | Right for terrain search, a **loss** for field-geology training |
| Lonar crater (FIELD_GEO) | removed: populated + vegetated | 0% | crop 87%, town 1,019/km² | 0.75 | none | Same. The 1.8 km crater is smaller than one pixel |

**Totals.** Of the 17 points with a surface profile (MARS_DRY / MARS_ICE / MOON_SURF), **15 have
their pixel kept**. The other 2 (Drumheller, Bockfjord) keep part of their region. **None is lost
entirely.** Of the 4 field-geology-only sites, 2 are lost (Sudbury, Lonar), one is partial (Rio
Tinto) and one is kept (Lava Beds). MCD12C1 gives the same decision as MCD12Q1 at all 30 pixels.
No site pixel or region has QC=1 or MODIS fill. The 500 m valid-pixel count matches the expected
count everywhere.

### Negative controls and probes

| Point | Decision | Why | Correct? |
|---|---|---|---|
| Amazon forest | removed | vegetated (evergreen broadleaf 100%, NDVI 0.85) | Yes |
| Iowa cropland | removed | vegetated (cropland 100%, NDVI 0.88) | Yes |
| Phoenix downtown | removed | populated (1,361/km², urban 100%) | Yes |
| Cairo centre | removed | populated (34,976/km²) | Yes |
| Pacific Ocean | removed | water | Yes |
| **Konza Prairie** (grazed tallgrass) | **kept** | MODIS grassland 100%, NDVI **0.81** | **False positive** |
| **Serengeti near Seronera** | **kept** | MODIS grassland 100%, NDVI **0.74**, 28 people/km² | **False positive** |
| **Toolik tundra** | **kept** | MODIS *open shrubland* 100%, NDVI **0.66** | **False positive** |
| **Concordia, Dome C** | **kept** | snow/ice 100% (QC=6), no NDVI | False positive for terrain profiles |

All 5 negative controls are removed, and none of the 4 probes is.

## 3. MCD12Q1 quality flags (39 sampled tiles, not the whole globe)

Script `06_qc_and_mixed_pixels.py`, results in `results/qc_sampled_tiles.csv` and `qc_flip_summary.csv`.
The sample is every tile holding a validation site plus 19 regional tiles: deserts, rainforests, ice
sheets, high mountains, boreal and tundra. It covers 39 of 315 tiles and 31.36 M km² of MODIS land
(about 21% of all land). QC meanings are from the MCD12 C6.1 User Guide, Table 11.

| QC | Meaning (guide) | Sampled area | Effect on the v2 decision |
|---|---|---:|---|
| **1** | Unclassified land (missing data) "labelled as barren" | **5,340 km² (0.017%)** | Treating it as missing flips **34** of the 2,055 pixels it touches (kept → removed). Even the worst case, treating it all as cropland, flips 161 pixels (3,741 km²). **Not material.** Only 41.6% of QC=1 pixels actually carry the barren label in v061; 38.1% are snow/ice and 8.4% evergreen forest. They cluster in the Patagonian Andes, Pamir/Hindu Kush, Tibet, New Guinea and Borneo |
| **7** | Snow/ice relabelled barren (minimum temperature > 1 °C) | **45 km²** (Patagonia 43, Australia 1.5) | None possible: snow/ice and barren are both analog in v2. Negligible anyway |
| 6 | Other class relabelled snow/ice (maximum temperature < 1 °C) | 2,016,971 km² (6.4%): 99.7% of Antarctic land, 54% of the Greenland tile, 8.5% of Iceland | None in v2. But this is why the **McMurdo Dry Valleys read as 70–74% snow/ice**. A bare-ground gate or a barren-only policy would delete them |
| 5 | Classified as water on land, given its second label | 25,652 km² | Provides most "barren" in Antarctica (83% of it in tile h21v16) and the small barren share in the Amazon tile (river sand bars) |
| 8 / 9 / 10 | Backfilled / forest type changed / no data | 18,774 / 90,534 / 456 km² | Minor |

**Conclusion.** QC=1 and QC=7 don't justify a global QC scan or a pipeline change. QC=6 matters
only for gates that separate ice from bare ground, and in Antarctica MODIS can't make that
distinction at all.

## 4. Barren terrain lost in coarse mixed pixels

The whole globe is covered here from the cached 0.05° counts (land-cover rule only, as in P1).
Results are in `results/mixed_pixel_barren.csv`. The sampled-tile detail is in
`mixed_pixel_flag_examples.csv`.

- Of 20.35 M km² of MODIS barren land, **70,824 km² (0.35%)** lies inside removed pixels:
  - removed for water ≥ 50%: 35,447 km²
  - removed for built ≥ 25%: 11,872 km²
  - removed for vegetation ≥ 50%: 14,492 km²
  - removed by the mixed rule: 9,014 km²
- 3,031 removed pixels hold at least 24 barren 500 m pixels (5.15 km², about one r7 cell). In the
  sampled tiles, 678 of 786 such pixels contain an 8-connected barren patch of that size, so most
  of this is coherent ground, not scattered pixels.
- **What it is** (inspected by location):
  - The largest patches sit in **desert-city pixels**: Aden, Khartoum, Calama, Copiapó, Las Vegas,
    Cairo, Marrakesh. Removing them is right.
  - **Salt-lake and playa margins** removed as water: Qaidam/Tibetan lakes (202 flagged pixels in
    one tile), Great Salt Lake, Salton Sea, Lake Natron, Red Sea and Atacama coasts. Some of these
    are genuinely valuable Mars analogs.
  - **Young Hawaiian lava next to closed shrubland**, removed for vegetation (Mauna Loa–Mauna Kea
    saddle, 19.6°N 155.4°W). Lunar-relevant.
- **Recommended flag, not refinement now:** `barren_in_removed` = removed for water, vegetation
  or the mixed rule, and at least 24 barren 500 m pixels. That is **2,254 pixels, 58,050 km²,
  about 11,200 r7 cells**, 0.07% of an r7 database. A selective 500 m pass over only those cells is
  cheap. At r7 a cell holds 21–27 MODIS pixels (at r8 only 3–4), so per-cell 500 m fractions become
  meaningful at r7. **It isn't needed for the pilot.** The tests show the documented analogs
  survive without it.
- **500 m won't rescue badlands.** Drumheller has no barren pixel at 500 m. Features narrower than
  about 1 km need 10 m data (Esri / Dynamic World), which is what the regional pilot is designed for.

## 5. Vegetation check: an NDVI gate works, a stricter class list doesn't

The kept-pixel decision at each site under the audit's policies, and under P1 plus VIIRS 2023 peak
NDVI < 0.5 (the v1 threshold, from data already on disk):

| | P1 (current) | P3 (no grass, no savanna) | P4 (barren + open shrub) | P6 (barren only) | **P1 + NDVI < 0.5** |
|---|---|---|---|---|---|
| Surface analog pixels kept (of 17) | 15 | 14 | 12 | 10 | **15** |
| Analogs lost (vs P1) | none | Black Point pixel; Drumheller and Lava Beds regions go to 0% | + Beacon Valley, Don Juan Pond (QC=6) | + Kilbourne Hole, Pinacate | **none** |
| Probes removed (of 4) | 0 | 2 | 3 | 4 | **3** (all but Concordia) |

- Peak NDVI is **≤ 0.41 at every surface analog** (the highest is Drumheller) and **≥ 0.66 at every
  vegetated probe**.
- Globally, adding the gate to P1 (`results/ndvi_gate_global.csv`):
  - kept land drops from 94.03 M to **55.84 M km²**, about 10.8 M r7 cells
  - it removes 16.8 M km² of grassland, 12.6 M of savanna and 4.9 M of open shrubland
  - it costs only **67,329 km² of barren** (0.33%)
- Antarctica (12.25 M km²) has no NDVI and stays kept, so ice sheets still need a mission rule.
- The thresholds are calibrated on 30 points only. Treat 0.4–0.55 as "uncertain", not as a hard edge.

## 6. H3 r7 readiness (regional only)

Script `08_r7_readiness.py`, run in the regional pilot's venv (h3 4.5.0). Results in
`results/r7_hex_filter_sites.csv`, `r7_drumheller_terrain.csv` and `r7_pilot_smoketest.csv`.

**What works at r7**

- **The hexagon filter step** (`contours_r8.py`: drop a hexagon when ≥ 90% of its 0.001° samples
  are removed):
  - The site-cell decision is identical at r7 and r8 for all 30 sites, with 373–491 samples per r7
    cell and no sample outside the kept-flag windows.
  - In mixed landscapes, r7 keeps a little **more** area. Kept area within the 19 r7 cells (2 rings)
    around each site: Drumheller 45.2 vs 34.4 km² (r8), Rio Tinto 44.3 vs 37.2, Bockfjord 72.1 vs
    65.2, Konza 97.1 vs 90.9. That is the conservative direction for analogs.
- **The regional pilot's functions** (`ring_cells(resolution=7)`, `cell_polygon`,
  `aggregate_polygon`, `decision`) run at r7 on real MCD12Q1 data, and the pilot's own tests pass
  (26 passed).
- **Drumheller terrain:** the 36 rugged r8 cells shrink to 4 rugged r7 cells, because averaging
  dilutes narrow badlands. Rank on the within-cell p90 slope that `hex_terrain.py` already stores,
  not on the mean.

**Incompatibilities to fix inside the pilot task** (most are already listed in
`H3_RESOLUTION_7_INVENTORY.md`):

1. `pilot.run()` calls `ring_cells(lat, lon, ring)` without a resolution, the CLI has no
   `--resolution`, and rows and the manifest hard-code 8. `contours_r8.py` has `H3_RES = 8`.
2. **No input raster for the pilot exists locally.** It accepts only Dynamic World and Esri, and
   neither is on this laptop. MODIS isn't one of its schemes.
3. On the **native MODIS sinusoidal grid, `aggregate_polygon` rejected 26 of 70 cells** with
   "Overcounted overlapping raster areas". The discrepancy is at most 5.8 × 10⁻⁶ of the cell area,
   but the tolerance is 10⁻⁷. A nearest-neighbour UTM copy (allowed by the pilot's raster contract)
   runs every cell. Either use such a copy or loosen the tolerance to about 10⁻⁵.
4. **The pilot's rules aren't v2's.** It uses an 80% threshold and no population layer, and
   grass, shrub and snow are never excluded. Drumheller's site r7 cell (21% built) is *retained* by
   the pilot but *removed* by v2, and Konza is retained by both. Decide whether the pilot should
   reproduce v2 or deliberately differ, and write that down.

## 6b. The consultation's checks

**Acceptance criteria (consultation §8)**

| Criterion | Result |
|---|---|
| No silent unknown → suitable | **Fails, but small.** 21,023 km² of Natural Earth land with no MODIS data is kept by default (20,827 km² of it south of 60°S). QC=1 pixels count as observed classes (0.017% of sampled land). Missing NDVI (12.60 M km², mostly Antarctica) must become `unknown` if an NDVI gate is added, not `pass`. The regional pilot already has an explicit `review` state. A hexagon with no samples is removed, which is conservative |
| Known barren controls survive the permissive profile | **Pass**: every barren-dominated analog is kept (§2) |
| Obvious water and city controls excluded | **Pass**: ocean, Phoenix and Cairo removed |
| Mixed and coastal controls flagged or explained | **Pass**: Drumheller (mixed) and Bockfjord (coastal) explained in §2 |
| No raw data in Git; no global r7 grid; teammate pipelines untouched | **Pass**: rasters only under the ignored `work/`, only regional cells built, `pilot.py` and `data/cleaning` imported or read only |

**Mathematical checks**

- **M1, denominators.** In REPORT.md §2, "Area, km²" is the global class area, while "% of land" is
  the class area *on Natural Earth land* ÷ NE land (barren 20,343,693 / 146,735,718 = 13.864%).
  The arithmetic is right but the column label is misleading. Fix the label. No number changes.
- **M2, NE land vs MODIS land.** The 1,670,808 km² gap is MODIS water inside NE land polygons
  (2,363,768 km²: lakes and coastal pixels) minus MODIS land outside NE polygons (692,962 km²).
  The two definitions of land reconcile to within 2 km². Safe to leave, now documented.
- **M3, latitude weighting.** Verified: a 0.05° pixel at 60°N has 0.5004 × the equatorial area,
  and all pixels sum to 4πR² (510,065,622 km²).
- **M4, double counting.** The kept area is computed as flags = 0, a union, so nothing is counted
  twice. The teammate's `summary.json` `removed_*_any` figures are standalone and overlap, so they
  don't sum to the total. Don't add them up.
- **M5, spatial agreement.** P1 + NDVI is a subset of P1, so their area-weighted IoU is
  55.84 / 94.03 = 0.59. MCD12Q1 and MCD12C1 agree at 30/30 site pixels. IoU against the reported v2
  raster can't be computed here, because the raster is on the teammate's machine.
- **M6, the 85.8 M km² figure.** The 8.23 M km² gap to MODIS-only remains **unattributed**. GHSL and
  Esri are the plausible causes, but that isn't proven.

**Theory and data notes**

- **T9, VIIRS.** The NDVI gate uses the documented scale (× 10⁻⁴) and fill codes, as v1 did, but
  not the VI quality layer. Peak compositing is fairly robust to cloud, because clouds lower NDVI.
  Add the quality layer before calling it QA-aware.
- **Not tuning on the validation sites.** The 0.5 NDVI threshold is v1's existing value, not tuned
  on these sites.

## 7. Recommendation

**GO WITH LIMITATIONS: proceed to the regional r7 pilot.** The mask preserves every documented
surface analog in the sample (15/17 site pixels kept, the other 2 partially). It removes every
negative control. Nothing in the QC or mixed-pixel results requires changing it first. The
limitations:

- **Essential before submission (not before the pilot):**
  1. A gate stage must exist before any ranking or candidate list. Carry per-cell `peak_ndvi`,
     valid-month count, MODIS class shares, GHSL density and removal-reason bits into the r7 table,
     for example as a new `hex_features.py` group, so mission gates can reject grassland, savanna and
     tundra. Without it, the false positives above can be shown as analogs.
  2. Snow/ice cells count only for ice or polar profiles. They need another source for ice-free
     ground in Antarctica (MODIS QC=6).
  3. Mark the reported 85.8 M km² as provisional: the Esri query mixed 2022 and 2023. Either rerun
     it on the teammate's machine or disclose it.
  4. State the scope as surface-terrain analogs, or add a whitelist of documented field-geology
     sites (Sudbury, Lonar, Rio Tinto) that bypasses the mask.
  5. Add an explicit `unknown` state for land with no land-cover data, and for missing NDVI once
     an NDVI gate exists (§6b). It is small in area, but it is one of the consultation's
     acceptance criteria.
  6. Relabel the "% of land" column in REPORT.md §2 (M1).
- **Before the pilot runs:** the four r7 incompatibilities in §6. They are small, but they touch
  `pilot.py` and `contours_r8.py`, so they need your go-ahead.
- **Don't do:**
  - tighten the class list. P3 and P4 lose Black Point, Drumheller and Lava Beds (P4 also the Dry
    Valleys) and still keep the tundra probe. P6 drops tundra but also loses Kilbourne Hole and
    Pinacate. The NDVI gate does better than all three
  - a global QC scan
  - global 500 m refinement (keep the `barren_in_removed` flag for later)
  - global H3 generation

**Discrepancies that can safely remain:**

- the 8.23 M km² gap between MODIS-only and the reported v2 (unattributed, M6)
- the Natural Earth vs MODIS land difference (M2, explained)
- the difference between MCD12Q1 and MCD12C1 (same decision at 30/30 sites, totals within 0.25%)
- QC=1, QC=6 and QC=7 in the prefilter (§3)
- authalic-sphere areas, the 0.001° point sampling in `removed_frac`, and r7 counts estimated as
  area ÷ mean cell area
- float32 share arithmetic
- the pilot's ppm-level polygon-area mismatch (the tolerance is the problem, not the math)
- the slightly more permissive 90% hexagon rule at r7

## Reproduce

```powershell
cd experiments\landcover_audit_2023          # after scripts 01-04 (work\mcd12q1_counts_0p05.npy)
.venv\Scripts\python.exe -I scripts\05_site_validation.py        # ~30 s
.venv\Scripts\python.exe -I scripts\06_qc_and_mixed_pixels.py    # ~3 min (39 tiles + one global pass of the cached counts + 12 VIIRS months)
.venv\Scripts\python.exe -I scripts\07_export_pilot_rasters.py   # small GeoTIFFs in work\pilot_inputs
..\global_filter\regional_pilot\.venv\Scripts\python.exe -I scripts\08_r7_readiness.py   # ~10 s, imports pilot.py read-only
```

Coordinate sources are listed per site in `scripts/validation_sites.py`. The frontend sample
coordinates are approximate and uncited in the repo.
