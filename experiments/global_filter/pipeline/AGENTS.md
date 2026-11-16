# Agent handoff: analog calibration pipeline

Read this before changing anything in `pipeline/`. [README.md](README.md) is the user-facing
reproduction guide; this file records state, decisions, pitfalls, and what's next.
Last updated: 2026-11-15.

## Global r7 implementation update (2026-11-15)

The user's execution request supersedes earlier audit-only restrictions.
`../global_r7/` now implements the permissive v2 MODIS-only geographic policy,
configurable resolution (default 7), bounded spherical quadrature, checksummed
parent partitions, restart, and optional local DEM contours. See its
[run report](../global_r7/RUN_REPORT.md) and [transfer request](../global_r7/TRANSFER_REQUEST.md).
Natural Earth v5.1.1 and GHSL E2020 were downloaded on this PC and reproduce
the audit totals. Global MODIS is absent: **no completed global candidate dataset**.
The committed real audit observations produced 95 r7 cells / 86 candidates;
a real Copernicus crop produced 74 contour segments at Drumheller.
39 tests pass across the new global and regional suites. `regional_pilot` now
defaults to r7 and supports explicit r8; its mission policy stays separate.
Large files are outside Git under `W:\Spacethropic-data`. No NDVI tightening,
ranking, database ingestion, or full global elevation integration was added.
Next: obtain Q1 counts, run full-input site validation and a representative
benchmark, then launch/restart the global command. States below are historical;
this standalone addition does not change the calibration pipeline.

**Standing rule (from the user): after every completed step, update this file and
`README.md` before reporting back.**
- This file: state, decisions, open questions, next steps, pitfalls, and the date above.
- README: datasets and links, status, aggregation rules, expected results.
- Also update the root `CLAUDE.md` if folders or entry points change.

## What this is and why

This is a NASA Space Apps 2026 entry: find Earth analogs for Moon/Mars base and landing
sites ([../docs/challenge.md](../docs/challenge.md)). The eventual "searcher" ranks Earth
locations by how analogous they are to a planetary site.

No dataset links Earth to the Moon or Mars, so **historically used analogs** act as labelled
examples:

| Earth site | Planetary counterpart | Label strength |
|---|---|---|
| Sudbury | Apollo 16 (Moon) | Historical: crew trained there and recognised impact breccia |
| Atacama, Yungay | Viking 1 and Viking 2 (Mars) | Historical: Viking-style soil experiments (Navarro-González 2003) |
| Haughton | Shackleton (Moon), Phoenix (Mars) | Chosen by the team (HMP studied Haughton for both bodies, with no specific site) |
| Black Point Lava Flow | Apollo 15, Hadley Rille (Moon) | Chosen by the team (Desert RATS simulated generic lunar missions) |
| Dumont Dunes | Bagnold Dunes, Gale (Mars) | Historical: Curiosity mobility tests (2012) for those dunes |

Every Earth site is crossed with every planetary site: 10 × 7 = 70 edges, 7 true and 63 wrong (originally 3 × 5 = 15; expanded 2026-11-14). Five of the Earth sites are **random controls** (`rand_*` in `sites.yaml`) with no analog association, so all their 35 edges are wrong.
A calibrated searcher should place true edges at a lower distance. The pipeline only builds
the **feature dataset**; weighting and the searcher itself are out of scope so far.

## Current state

| Item | State |
|---|---|
| Dimension 2, terrain (elevation, slope, roughness/TRI) | **Done.** All 8 sites, 100% of cells measured, verified |
| Dimension 1, FeO (`feo_wt_pct`) | **Done** for the Moon (Lunar Prospector GRS) and Mars (Odyssey GRS). Empty on Earth (no source) and at Phoenix (GRS polar mask); allowed by the `allow_gaps` flag |
| All dimensions built so far, for the 17 sites (5 analog + 5 random-control Earth, 3 Moon, 4 Mars) | **Merged, 28 tests pass.** Only gaps: FeO on Earth and Phoenix (3,719 cell values, allowed); 38 tests pass. Bagnold's pressure (635 Pa) is low against Curiosity's ~700–900 Pa: a GCM coarse-cell artefact |
| Dimensions 3 + 5, temperature, sunlight, weather | **Done for all 12 sites**, every cell filled. Mars comes from the sampled GCM climatology (`data/raw/_shared/mgcm/mgcm_climatology_step6.npz`: 12 files, 1,920 samples), Moon weather is known-absent 0 |
| Feature importance (preliminary) | Done on terrain + albedo + FeO; see `analysis/feature_importance.md` |
| Dimension 1, albedo (`albedo`) | **Done.** Earth from Sentinel-2 (median of clear summer scenes), Moon from LOLA 1064 nm normal albedo (polar 1 km for Shackleton, global 10 ppd otherwise), Mars from TES. Every cell filled (4 Haughton cells interpolated) |
| Dimensions 4, 6–8 | **Not implemented.** They appear in `data/out/coverage.csv` as `status=not_implemented` |
| Tests | `uv run pytest`: 20 pass. The zonal spot-check compares `elevation_m__std` and now selects the terrain source explicitly; it used to take the first interim file alphabetically, which broke once other sources existed |
| Reproducibility | A fresh copy rebuilt Sudbury bit-identically, from the same input ETags |
| Data guide | `data/README.md` (git-ignored, ships with the data): source id → dataset → feature columns, folder layout, shared caches. Update it when a source or layer is added |
| Elevation export ZIP | Built 2026-11-14: `data/export/elevation_all_sites.zip` (89 MB, 17 sites): 200 m site-grid DEMs + provenance, per-cell interim parquet, terrain columns of `out/` (CSV + parquet), original LOLA polar file, manifest, data guide. Native-resolution crops and a rescaled ("normalized") tier were not made: undecided |
| Git | Committed in `d2003e2` ("data so far"). Everything after it is uncommitted: elevation std-only, FeO, `allow_gaps`, albedo, `pystac-client` dependency, and the docs |
| Global exclusion mask | **Built 2026-11-14** (`analysis/global_mask.py`, downloader `global_mask_download.py`). Pixel-by-pixel at 0.05° (user: no grid). Removes ocean, ≥ 50 people/km², 2023 peak NDVI ≥ 0.5. Kept 56.4 M km²: −88.9 % vs Earth, −61.6 % vs land. Sudbury is removed (vegetated). Lakes inside land polygons are kept (caveat). See README |
| Elevation at Earth-r8 size | **Built 2026-11-14** (`analysis/elevation_r8.py`): 858.68 m square pixels (Earth r8 mean area) on all bodies, recomputed from the original DEMs; 17 sites, 100 % valid; zip in `data/export/`. Not wired into `grid`/`merge` (still r7 cells, 200 m baseline) |
| H3 r8 land-cover pilot | **Integrated 2026-11-15, synthetic-tested only** in `../regional_pilot/` (standalone; doesn't import or change `pipeline/`, and the 0.05° mask stays the baseline). Exact pixel/hexagon area overlay, mission decision `excluded`/`review`/`retained` at an uncalibrated 80 %, hive Parquet + manifest. 25 tests pass, 1 skipped (see pitfalls: pyarrow dataset blocked). Fixed: an untagged Dynamic World raster used to count masked pixels as observed water; it is now refused. **No real land-cover raster exists locally**: next is a Dynamic World Jun–Aug 2025 export over the NASADEM Drumheller bbox (recipe in its README) |
| Frontend link | None yet. `frontend/src/data/candidates.json` is a separate hand-made sample set, and the frontend's `/api/search` was deliberately set aside |

## Decisions

The user is learning while building (VibeWise learning mode; notes live in
`../.vibe-wise/`). **Decisions are the user's.** Don't change a "user" decision without
asking. "Claude" decisions were proposed during planning or implementation and accepted,
but are open to revision.

| Decision | By | Where in code |
|---|---|---|
| The 3 historical pairs are the ground-truth labels | user | `pairs.yaml` |
| Haughton pairs with both bodies, one counterpart each (Shackleton, Phoenix) | user | `pairs.yaml` |
| Atacama pairs with both Viking landers | user | `pairs.yaml` |
| **Expanded (2026-11-14):** Black Point Lava Flow pairs with Apollo 15 / Hadley Rille (Desert RATS; the counterpart is the user's choice), and Dumont Dunes with the Bagnold Dunes / Gale (Curiosity mobility tests). Now 5 Earth × 7 planetary = 35 edges, 7 true | user | `sites.yaml`, `pairs.yaml` |
| Negatives come from bipartite cross-pairing | user | `merge._pairs` |
| **Random controls (2026-11-14):** 5 unassociated Earth sites as extra negatives | user (request); selection rule by Claude | `sites.yaml` (`role: control`) |
| Control selection: seed 20261114, uniform on the sphere, 60°S–75°N, Copernicus DEM tile present, ≥ 90% non-zero elevation in the 25 km window, ≥ 300 km from other Earth sites. Sentinel-2 seasons: local summer, Amazon dry season | Claude | `sites.yaml`, `sources/albedo.py: SEASONS` |
| The 8 challenge dimensions (numbered as in the challenge, `layers.DIMENSIONS`) | user | `layers.py` |
| **Work priority (revised 2026-11-14):** 1. weather/temperature (#3 temperature + #5 pressure/wind), 2. geology (#1), 3. elevation/terrain (#2), 4. illumination (sunlight). The remaining dimensions (#4, #6–#8) come after | user | — |
| Dimension 3 temperature features: daytime max, nighttime max, nighttime min, mean surface temperature (day = local solar time 6–18 h), plus mean sunlight | user | `layers.py`, `sources/climate.py` |
| Mars temperatures from the NASA Ames Legacy GCM (model output), labelled as such | user | `sources/climate.py` |
| Mars GCM: sample every 6th 10-sol file (12 of 67, evenly through the year) instead of the full ~20 GB. Means are ~unchanged; extremes come out slightly too mild | user | `sources/climate.py: MGCM_FILE_STEP` |
| Weather features: mean surface pressure, mean and max near-surface wind. Earth from POWER (`PS`, `WS10M`), Mars from the GCM, Moon known-absent 0 | Claude (user asked to fetch weather; exact features not specified) | `layers.py`, `sources/climate.py` |
| H3 grid; ~6 km² cells; nearest resolution per body (Earth r7, Moon r6, Mars r6) | user | `sites.yaml` |
| Scale-sensitive features use a fixed ~6 km² window on every body | user | `aggregate.py` (`window="fixed"`) |
| In-cell stats: mean, std, p10, p50, p90 | user | `layers.STATS` |
| Fixed extent radius around every site | user | `sites.yaml` |
| Python pipeline in `pipeline/`; reproducibility README | user | — |
| Goal: one merged table per site, as rich as possible. **Revised by user:** some features may be missing at some locations | user | `merge.py`, `layers.py` (`allow_gaps=True` default) |
| Gaps: fallback source first, interpolation only if no fallback | user | `merge.py` |
| Let some sites miss FeO (gaps allowed), and move on. This supersedes the earlier "published ground samples for Earth" choice for now, which stays possible later | user | `layers.py` (`allow_gaps=True`), `merge.py` |
| FeO keeps only `mean` (bins are larger than a site) | Claude | `layers.py` |
| Albedo sources and definitions: Sentinel-2 + Liang (2001) broadband weights, LOLA 1064 nm normal albedo, TES Lambert albedo; accepted although definitions differ | Claude (user said "proceed") | `sources/albedo.py` |
| Sentinel-2 seasons, cloud < 20%, ≤ 32 scenes, per-pixel median, SCL mask (cloud/shadow/snow out) | Claude | `sources/albedo.py` |
| FeO expressed as total-iron FeO wt%; Mars Fe × 1.2865 | Claude | `sources/geochem.py` |
| `elevation_m` keeps only `std`; absolute mean/percentiles dropped (height references differ by body) | user | `layers.py` (`Layer.stats`) |
| Global mask: pixel-by-pixel, no grid; Earth-r8 elevation uses the same physical pixel on every body (no per-body rescale) | user | `analysis/global_mask.py`, `analysis/elevation_r8.py` |
| Global mask thresholds (50 people/km², peak NDVI 0.5), sources (Natural Earth, GHSL 2020, VIIRS VNP13C2 2023), 0.05° pixel; r8 pixel as equal-area square (858.68 m) | Claude (user delegated the definitions: rural OK, forest not Mars-like) | same |
| 25 km radius | Claude | `sites.yaml` |
| Shared 200 m terrain baseline before slope/TRI | Claude | `sites.yaml: terrain_baseline_m` |
| TRI as the roughness metric; 50% valid-pixel threshold | Claude | `features.py`, `sites.yaml` |
| Azimuthal equidistant site-local grids; IAU sphere radii | Claude | `config.py` |
| Known-absent → physical value; no-data-anywhere → labelled proxy; per-value `__source` provenance | Claude | `merge.py`, `layers.py` |
| Parquet + `manifest.json` (URLs, ETags) + `coverage.csv` | Claude | `merge.py` |

## Open decisions (ask the user; don't decide for them)

1. **Earth FeO (deferred by user; ask before building).** If revisited: literature reports
   per rock unit, but a 25 km disk spans several units. Options: dominant exposed unit, area-weighted mix, or the
   unit most relevant to the analog. Research so far:
   - Sudbury norite ~9.1–9.3 wt% FeO (historical analyses). The disk, though, is mostly basin
     fill (Whitewater Group) and granophyre.
   - Haughton: carbonate-dominated melt breccias and targets (dolomite, limestone), so very
     low FeO; no number sourced yet.
   - Atacama, Yungay: no number sourced yet. The EarthChem gypsic-soil dataset (Cosentino &
     Jordan 2016) reports soluble elements only.
   - Two key papers' URLs had moved (Lightfoot et al. 1997 on Sudbury; Osinski et al. 2005,
     MAPS 40:1887, on Haughton).
2. **Feature rule for dimensions 1, 3–8:** each feature has to mean the same thing on every
   body. Raw instrument values (Sentinel-2 bands vs CRISM vs Diviner) aren't comparable.
   Which physical quantities to use per dimension is the user's design question; it has been
   asked but not answered.
3. **Searcher weighting** (how the dimension priority becomes weights): deferred. The
   Atacama's real match was dimension 6, which is ranked low.

## Gap-allowed layers (built)

`Layer.allow_gaps` defaults to **True** for every layer (user: "it's ok to have some
features missing from certain locations"). Fallbacks and interpolation still run first;
leftover gaps are reported in `coverage.csv` (`gaps_allowed` column) and don't fail
`merge`. Set `allow_gaps=False` only for a layer that must be complete.

## Next steps (user's revised priority: weather/temperature → geology → elevation → illumination)

1. **Dimension 1 is done** (FeO, albedo). Possible later additions, not agreed:
   - Earth FeO from literature (deferred by the user).
   - Diviner silicate mineralogy (Christiansen feature) for the Moon, TES/THEMIS mineral
     indices for Mars. These have no direct Earth equivalent, so ask the user first.
2. **Done: temperature (#3).** Earth (NASA POWER hourly), Moon (Diviner GCP) and Mars (Ames GCM climatology, built once by streaming 67 files) are written. Sunlight (analytic) is also written. Grid and merge haven't been rerun for these yet.
3. **Prefetched for #4 and #5 (dust), not wired in:** 12 sources in `data/raw/_shared/prefetch/`. See `PREFETCH.md` there (git-ignored) and the summary in `docs/HANDOFF.md`. Feature choice is the user's.
   **Done: weather (#5)**, with mean surface pressure, mean and max wind. Sources are written; Earth is fetching, Mars comes from the same GCM build, Moon is known-absent 0.
   - Wind heights differ: Earth at 10 m, Mars in the lowest GCM layer.
   - Dust (`dust_mass_*`) and water vapour (`h2o_vap_mass_mean`) are already in the GCM climatology `.npz` for later dimensions #5 and #4.
4. Then the rest of geology, elevation and illumination improvements, then dimensions #4 and #6–#8. Ideas not yet agreed:
   - Analytic top-of-atmosphere insolation from latitude (consistent on all bodies).
   - NASA POWER for Earth climate.
   - Diviner for lunar temperatures.
   - Surface pressure and wind as known-absent zero on the Moon.
5. Fix README "Expected results" and "Status" whenever coverage changes.
6. **Feature importance.** A preliminary study (2026-11-14, terrain + albedo + FeO only) is in
   `analysis/` (`feature_importance.md`, `.py`, results CSVs). Run it with
   `python -m uv run python analysis/feature_importance.py`; it's deterministic and picks up
   new feature columns automatically.
   - **Result:** no current feature separates true from wrong edges. The best is
     `albedo__p10`, with AUC 0.56 and permutation p 0.38. Terrain features score AUC < 0.5:
     true edges are slightly *farther* apart, driven by Haughton–Shackleton (Shackleton is far
     rougher) and Sudbury–Apollo 16 (albedo 0.12 vs 0.29).
   - **Multivariate fit:** AUC 0.82 in-sample but 0.34 under leave-one-target-out, so it
     doesn't generalise.
   - **Second run** (2026-11-14), in `analysis/runs/2026-11-14_earth-moon-temps/`. It used a
     snapshot taken *before* the Mars merge, so Mars has no temperature or weather in it.
     - On the 6 Earth–Moon edges, sunlight, day-max and night-min temperature reach AUC 0.75
       (p 0.22–0.33). That's a single hit, essentially latitude: Haughton is the closest
       Earth site to Shackleton. It's close to circular, since that pair was chosen as a polar
       pair.
     - Weather is an artefact: Moon pressure and wind are 0.
     - **Haughton–Shackleton ablation** (A all, B dropped, B2 all Shackleton edges dropped,
       C relabelled wrong): B and C look better only because Shackleton's wrong edges are far
       apart. B2 is worse (true/wrong ratio 1.37). Nothing reaches p < 0.22.
     - The run's `report.md` was not written: the subagent's file write was blocked. Its
       text exists only in the session, pending the user's OK to save it.
   - **Script options** (backwards compatible; defaults reproduce the committed CSVs):
     `--data-dir`, `--out-dir`, `--targets`, `--exclude-edge EARTH:TARGET`,
     `--relabel-false EARTH:TARGET`, `--transform PREFIX=log1p|rank`. Exact nulls are now
     enumerated over only the edges that have values.
   - **Third run, full graph** (2026-11-14), in `analysis/runs/2026-11-14_full-35-edges/`
     (`report.md`): 35 edges, 7 true, all built dimensions.
     - Each feature alone as the distance. Best AUC 0.57 (`wind_mean_ms__mean`, which is an
       artefact of lunar wind = 0), then `albedo__p10` 0.56 and insolation/day-max T 0.55.
     - No p_constrained < 0.18. The all-feature aggregate is AUC 0.49. Logistic regression
       gives 0.76 in-sample and 0.24 leave-one-target-out.
     - Script changes: sites are now read from `pairs.csv` (no hard-coded 3×5); `auc_many`
       vectorises the null. Permutation nulls are exact up to `MAX_ENUM` = 200k labelings,
       otherwise 100k seeded Monte Carlo draws (the plain null over 35 edges is MC; the
       constrained null, 5^7 = 78,125, stays exact).
   - **Fourth run, with random controls** (2026-11-14), `analysis/runs/2026-11-14_with-random-controls/`:
     70 edges. Best single feature is `albedo__p10` (AUC 0.64, p_constr 0.08), then
     `temp_night_max_k__mean` (0.57, p 0.06). Aggregate AUC 0.53–0.55.
     - Mean aggregate distance: true 1.26, wrong analog-site edges 1.26, random-control edges 1.44.
       So the features separate analog-like ground from random land, but not *which* target.
   - **Next:** the full study is the final step once all dimensions are built (user request).
     The full study is the final step once all dimensions are built (user request).
   Find which features contribute most to separating the 5 true edges from the 10 wrong
   ones in `pairs.csv`.
   - The method is the user's call. With only 15 labelled edges, prefer robust approaches,
     e.g. leave-one-edge-out stability or permutation importance on a simple distance model.
   - Report uncertainty.
   - The study must handle missing features (gaps are allowed).

## Pitfalls already hit (don't rediscover them)

- **GHSL 30″ WGS84 grid is offset:** origin −180.0079°, 43,202 columns, top 89.0996°N. Bin by pixel
  centre, not 6 × 6 blocks. **VNP13C2 subdataset** is `CMG_0.05_Deg_monthly_NDVI` (lower-case
  `monthly`), HDF5 (readable); MODIS C6.1 CMG files are HDF4, which this GDAL build can't read.

- **Sentinel-2 offset trap:** Earth Search v1 items with
  `earthsearch:boa_offset_applied: true` already have the baseline-04.00 +1000 DN shift
  removed. Yet their `raster:bands` still say `offset: -0.1`; applying it gives negative
  reflectance. `sources/albedo.py` uses scale only when the flag is true. Symptom: Sudbury
  albedo median 0.02 and negative values.
- **COG overview reads:** `raster.warp_array(read_res_m=...)` reads projected COGs
  decimated, so GDAL uses overviews. Use it for any 10–30 m Earth imagery, or downloads
  balloon. Categorical bands (SCL) need `Resampling.mode`, not average.
- **LOLA albedo files** are under `imbrium.mit.edu/DATA/LOLA_GDR/*/FLOAT_IMG/` (`LDAM_*`).
  The `IMG/` directories don't list them, and `ldrm_*` on PDS Geosciences is *roughness*.
- **Diviner GCP** is split into 10° latitude-band tables (~156 MB each, cached in
  `data/raw/_shared/diviner/`). A site straddling a band edge would need two files; the code
  handles one band only.
  - Use the `90s80s` band for Shackleton. The polar PCP products are 240 m but ~81 GB
    (384 files × 212 MB), so they're not used.
- **Mars GCM:**
  - The server answers range requests with 0-byte bodies, so whole files must be
    downloaded.
  - `tloc` is all fill values. Local time is (1.5·step + lon/15) mod 24, verified from
    daily peaks.
  - The vertical axis runs top-down: the near-ground layer is index −1.
  - `psurf` is in mbar.
  - The NAS portal throws intermittent `502 Bad Gateway`. The build retries with backoff
    and is resumable: per-file reductions go to `data/raw/_shared/mgcm/partials/*.npz`, so
    rerunning skips finished files. Delete `partials/` only to force a full rebuild.
- **Run the project env:** `python -c ...` outside `uv run` fails with "No module named
  yaml"; always use `python -m uv run python`.
- **GCM resolution vs deep craters:** a 5° × 6° GCM cell averages Gale's floor with Mount
  Sharp and the surrounding highlands, so Bagnold's pressure and temperature are biased
  toward the highlands. A topographic pressure correction (scale height ~11 km, using the
  site's MOLA elevation) would fix pressure; it isn't implemented.
- **Gamma-ray tables** (`sources/geochem.py`):
  - The Lunar Prospector table gives bin *bounds* in −180..180 and weight *fractions*
    (×100 for wt%).
  - The Odyssey table gives bin *centres* in 0..360 east, in wt% of Fe (not FeO), with
    `9999.999` = masked. Phoenix at 68°N is fully masked.
  - Both are rasterised onto a 500 m site grid by `raster.write_site_raster`.

- **H3 and body size:** H3 resolutions fix a cell *count*, not a size; its km helpers assume
  Earth. Always compute in radians × body radius (`grid.py`). Same resolution: Moon cells
  are ~0.07× Earth area, Mars ~0.28×.
- **Mars latitude convention:** the elevation maps are planetocentric. The Viking
  coordinates were planetographic, and the difference is ~0.33° (~20 km) at 48°N. Converted
  values and their sources are in `sites.yaml`.
- **Longitude ranges:** the USGS mosaics are −180..180, but some PDS products are 0..360
  (`ldrm_16` has `lon_0=180`). `transform_bounds` handles it as long as the CRS is correct,
  but check new sources.
- **LOLA scaling:** heights are DN × 0.5 m. The polar `.lbl` also has `OFFSET = 1737400`;
  pass `scale=0.5` explicitly (`sources/terrain.py`), or heights become radii.
- **PDS label case:** labels point at upper-case `.IMG` names while the server and our
  downloads are lower-case. It works because the Windows filesystem and the WUSTL IIS server
  are case-insensitive. It **will break on Linux**; rename locally or rewrite the pointer if
  running there.
- **Row-strip mosaics:** most USGS global mosaics are stored as full-width rows, so a 60 km
  window still reads every row it touches in full (~65–100 MB per planetary site). This is
  expected, not a bug. Copernicus DEM COGs are tiled and cheap.
- **Misleading product names:** `ldrm_*` is LOLA *roughness*, not reflectance. Read the
  `.lbl` `DESCRIPTION` before trusting a filename.
- **Sentinel-2 `s3://` hrefs:** some Earth Search items (seen at `rand_amazon`) list `s3://`
  asset hrefs, and GDAL then demands AWS credentials. `Sentinel2Albedo.fetch` runs inside
  `rasterio.Env(AWS_NO_SIGN_REQUEST="YES")`; the bucket is public.
- **New Earth sites need a Sentinel-2 season:** `Sentinel2Albedo.covers` is
  `site.id in SEASONS`, so a site missing from `SEASONS` silently gets no albedo.
- **pyarrow dataset blocked on the dev laptop (2026-11-15):** Windows Application Control
  blocks pyarrow 26.0.1's `_dataset_parquet` DLL in every environment, including the global
  Python and `pipeline/.venv`. Single-file `pd.read_parquet` / `to_parquet` work, which is all
  the pipeline uses. `pyarrow.dataset`, `ds.write_dataset` and directory reads fail. Don't
  introduce directory-dataset reads without a per-file fallback.
- **Windows tooling:** `uv` is run as `python -m uv`. On 2026-11-15, uv wasn't installed in the
  global Python; it was installed into `../regional_pilot/.venv` and run from there
  (`uv sync --frozen`). There's no system GDAL; rasterio
  bundles it. Piped Python stdout is buffered, so background logs appear only at the end.

## Credentials

`pipeline/.env` (git-ignored by the root `.gitignore` pattern `.env*`) holds
`EARTHDATA_TOKEN`, a NASA Earthdata bearer token. No current code reads it; the terrain
sources are all open.

- **Never print, log, or commit it.**
- The user pasted it in chat, so it should be treated as exposed and revoked after use.
- Use it as `Authorization: Bearer <token>` for Earthdata-hosted downloads (LP DAAC, GES DISC).
- Other planned variables are listed in `.env.example`.

## How to verify a change

```bash
cd pipeline
python -m uv run python run.py all <site>    # or: all
python -m uv run pytest                      # 20 tests; zonal spot-checks need data/ present
```

- `merge` prints per-layer coverage and exits 1 on any unfilled value in an implemented
  layer.
- Every new source needs: a `Source` subclass, registration in `sources/__init__.py` (order
  sets fill priority), and a README dataset row with a working link.
