# Spacethropic — Global Land-Cover Audit: Technical Consultation Notes

**Date:** November 15, 2026  
**Project:** NASA Space Apps Challenge 2026 — Spacethropic  
**Status:** Initial 2023 global land-cover audit completed and reportedly pushed to GitHub; H3 resolution-7 migration planned, not implemented.  
**Scope:** Mathematical checks, scientific interpretation, practical recommendations, and questions for teammates. This note is based on the Claude Code experiment summary shared in chat, **not** on a line-by-line inspection or independent rerun of the local source code.

## One-minute summary

**We do not need a perfect global land-cover filter.** Its job is to cheaply reject obviously unusable areas and leave enough plausible locations for later terrain analysis and ranking. A *false positive* (an unsuitable place that gets through) is often tolerable if later checks reject it; a *false negative* (a suitable place discarded early) can never be recovered downstream. Therefore, prefer a **permissive first pass with clearly recorded uncertainty**, followed by mission-specific, higher-resolution decisions.

The audit's main result is meaningful: the current MODIS-only policy retains **94,029,740 km², or 64.08% of Natural Earth land**. This is largely explained by accepting grassland, savanna, open shrubland, barren ground, and snow/ice—not obviously by broken data decoding. No scientific requirement says the team must exclude 80% of Earth. Exclusion rates are an outcome of a mission definition, not the target.

**Recommended next move:** define two practical mission profiles, test them on a small set of obvious positive/negative geographic controls, and then reproduce the teammate's complete 85.8-million-km² v2 pipeline only if needed to select or explain the final policy. Do not block the H3 r7 prototype on small rounding/percentage inconsistencies; do fix any issue that can silently erase useful terrain or count unknown data as suitable.

## 1. Findings already supported by the reported experiment

- Datasets reported readable/validated: Natural Earth land, GHSL population raster, 315 unique MODIS MCD12Q1 2023 tiles, one MODIS MCD12C1 2023 file, and twelve monthly VIIRS VNP13C2 2023 files. Claude Code reported 51 passing checks, no failed checks, and separate verification of 29 identical duplicate MODIS files.
- MODIS MCD12C1 is an aggregated/reprojected product derived from MCD12Q1. Close agreement between the two is a **consistency check, not independent validation of ground truth**.
- The 0.05° area-weighted experiment is intentionally **independent of H3**. Changing from H3 resolution 8 to resolution 7 has been documented but not implemented in the teammate's global filter or regional pilot.
- The 85.8-million-km² teammate v2 figure is not reproduced by this audit. It includes GHSL and Esri-related steps not included in the MODIS-only 94.03-million-km² comparison; previous inspection also identified mixed-year Esri 2022/2023 observations.

### Reported MODIS-only kept area

| Component | Retained area (million km²) | Share of retained area |
|---|---:|---:|
| Grassland | 28.96 | 30.8% |
| Barren | 20.28 | 21.6% |
| Snow / ice | 14.59 | 15.5% |
| Savanna | 12.93 | 13.8% |
| Open shrubland | 12.91 | 13.7% |
| Other cover in mixed accepted pixels | 4.34 | 4.6% |
| **Total** | **94.03** | **100% (rounding)** |

Key implication: the typical retained place is not necessarily a barren desert. The classification currently accepts substantial vegetation-related land cover.

### Reported policy sensitivity

| MODIS-only policy | Retained land (million km²) | Share of Natural Earth land |
|---|---:|---:|
| Current rule | 94.03 | 64.08% |
| Current classes, stricter vegetation limit | 87.38 | 59.55% |
| Current classes, require >=90% accepted cover | 79.94 | 54.48% |
| Drop savanna | 77.87 | 53.07% |
| Drop savanna and grassland | 47.96 | 32.69% |
| Barren + open shrubland | 33.25 | 22.66% |
| Barren + snow/ice | 34.76 | 23.69% |
| Barren only | 20.06 | 13.67% |

**Interpretation:** Which classes we accept changes the retained area much more than a modest threshold adjustment. However, choosing the smallest retained area does not automatically make the candidate set better.

## 2. What a 1% error really means

The percentage **must specify its denominator and its error type**:

- 1% of all Earth's surface (reported 510,065,622 km²) = **5,100,656 km²**.
- 1% of Natural Earth land (reported 146,735,718 km²) = **1,467,357 km²**.
- 1% of the currently retained MODIS-only land (94,029,740 km²) = **940,297 km²**.
- Converting these areas using H3 resolution-7's **average** cell area (5.16129336 km²) gives approximately 988,000, 284,000 and 182,000 *cell-equivalents*, respectively. They are **not exact counts of H3 indices**: actual cell areas vary and boundaries cut through cells.

A 1% difference in global *area totals* also does **not** mean only 1% of geographic positions are wrong. Two maps can have exactly the same retained area and disagree on millions of square kilometres of *which* places are retained. Evaluate **spatial overlap and false-negative rate on relevant analog sites**, not only total area.

### Example A: false positive — often tolerable

A vegetated field is incorrectly accepted by the coarse land-cover mask. Downstream NDVI/vegetation, slope, imagery or other mission constraints reject it. The impact is extra compute and possibly additional ranking noise, but a final recommendation need not be wrong **if** later checks actually catch it.

### Example B: false negative — potentially serious

A rocky, unvegetated patch is inside a coarse grid pixel labelled mostly grassland. An early 'exclude grasslands' rule deletes the whole pixel. The rocky patch is never examined for slope, geology or analog suitability. No ranking algorithm can recover a candidate that it was never given.

### Example C: mixed 0.05° pixel — resolution matters

At the equator, a 0.05° by 0.05° pixel has approximately **30.9 km²** of area (spherical approximation). Suppose it contains **51% barren land and 49% forest**. A rule that keeps the *whole* pixel when its accepted fraction exceeds 50% would pass around **15.1 km² of forest** inside that pixel. Conversely, if 49% were an excellent barren patch but the majority class were disallowed, a hard rejection might lose the patch. MODIS MCD12C1 describes class proportions *within coarse pixels*, not precise positions of the smaller patches. An H3 r7 cell averages 5.16 km², so attaching the same coarse-pixel decision to smaller hexagons does **not** magically resolve the underlying details.

```
Schematic (not to scale):

  One 0.05-degree pixel
  +--------------------------+
  | barren barren barren     |  coarse summary: 51% barren
  | barren barren barren     |                  49% forest
  | barren barren forest     |
  | forest forest forest     |  whole-pixel pass -> some forest passed
  | forest forest forest     |  whole-pixel fail -> some barren lost
  +--------------------------+

  Later H3 r7 indexing divides the geography into smaller addresses,
  but without higher-resolution evidence it cannot locate the subpixel classes.
```

**Practical policy:** make the cheap first stage conservative *about exclusions*, not conservative *about retaining sites*. An uncertain/mixed place can be flagged for later verification instead of deleted.

## 3. Mathematical corrections and checks

### M1. Reconcile denominators in the global class-area table — LOW urgency, EASY FIX

The report gives Natural Earth land as **146,735,718 km²**. Some reported '% of land' figures are not arithmetic fractions of that value:

| Class | Reported global area (km²) | Reported land % | Area / 146,735,718 |
|---|---:|---:|---:|
| Barren | 20,417,875 | 13.86% | **13.91%** |
| Grassland | 31,006,067 | 21.05% | **21.13%** |
| Savanna (both types) | 27,213,377 | 18.48% | **18.55%** |
| Other | 1,913,450 | 1.19% | **1.30%** |

Likely explanation: the table used a different definition of 'land' or a different denominator. Do not arbitrarily change percentages until identifying that denominator. State the denominator in the output and make it an automatic test. These small percentage disagreements are unlikely to change a site shortlist on their own.

### M2. Explain the land-mask discrepancy — MEDIUM urgency, SMALL INVESTIGATION

All reported global class areas, including water, sum to **510,065,619 km²**, only **3 km²** below the stated Earth area of 510,065,622 km² (a good closure check). However, their total **excluding MODIS-classified water** is **145,064,910 km²**, versus Natural Earth land **146,735,718 km²**, a difference of **1,670,808 km²** (about **1.14%** of Natural Earth land).

These are **different definitions of land**. Raster water boundaries, coastal and inland-water treatment, grid resolution, and polygon/raster conventions can disagree. Do not add or subtract the discrepancy as if it were a measured filter error; make a small cross-tabulation of **Natural Earth land vs MODIS water** by area to explain it. Prefer a well-defined and documented land denominator in every result.

### M3. Check latitude-aware area weighting — HIGH correctness value, one focused test

For a geographic grid cell with longitude bounds lambda1/lambda2 and latitude bounds phi1/phi2 (radians), a spherical area approximation is:

`A = R² (lambda2 - lambda1) [sin(phi2) - sin(phi1)]`.

Thus a 0.05° longitude span occupies progressively less area near the poles. Never aggregate global class proportions by **counting grid pixels equally**. The area audit reportedly used latitude adjustment; preserve a unit test for its hemispheric behavior, e.g., the same-sized degree pixel at 60° latitude has about half the equatorial area.

### M4. Prevent double-counting when combining masks — HIGH value if computing individual effects

An area excluded by forest *and* population screening must be counted **once** in the total excluded area. The combined exclusion is a set union: `Excluded = Water ∪ Vegetation ∪ HumanFootprint ∪ ...`. If explaining contributors, report (a) the *standalone* exclusion area, (b) pairwise overlaps if useful, and (c) the *incremental* area each stage excludes in a stated order. Stage-by-stage increments must sum to the final total excluded area; standalone areas generally will not.

### M5. Separate absolute-area disagreement from geographic disagreement — HIGH value for actual recommendation quality

Calculate retained-area totals *and* spatial agreement metrics. For masks A and B, use a consistently area-weighted intersection over union:

`IoU = area(A ∩ B) / area(A ∪ B)`.

Two policies can both retain 80 million km² but disagree substantially about the locations. Ask whether benchmark analog sites survive filtering, not merely whether the global percentage looks right.

### M6. Reproduce the teammate's 85.8-million-km² result carefully — MEDIUM priority, not an immediate blocker

`94,029,740 − 85,800,000 = 8,229,740 km²`, but this **does not prove** that GHSL and Esri caused that difference: v2 may use another set of thresholds, combining rules, clipping decisions, dataset years, missing-data defaults, or geographic aggregation. To attribute the difference, rerun the **same grid, same policy, same spatial mask and deterministic stages** while enabling one data source at a time. Fix or document Esri's 2022/2023 temporal mix first. Do not treat the provisional 85.8-million figure as ground truth.

### M7. Avoid treating accuracy as '1% error' without a definition — HIGH conceptual value

At least five different errors exist: (1) area/denominator arithmetic error, (2) satellite land-cover classification error, (3) spatial discretization/coastline error, (4) policy error (which class should qualify for a mission), and (5) ranking/evaluation error. They have different consequences. A 1% arithmetic discrepancy is not a 1% false-negative rate on scientifically valuable analog locations.

## 4. Scientific/theory changes

### T1. Do not treat 'grassland', 'open shrubland', or 'savanna' as 'barren' — HIGH priority

IGBP land-cover categories describe **land-cover type**, not directly analog quality. In the MCD12Q1 IGBP legend: open shrublands have roughly 10–60% woody perennial cover; savannas have 10–30% tree cover; woody savannas have 30–60% tree cover; and grasslands are dominated by herbaceous vegetation. 'Barren' itself is a map class, not proof of lunar-like soil mechanics, chemistry or geology. These categories are not interchangeable with vegetation density or suitability. Preserve the actual class fractions and make accept/exclude decisions per mission.

### T2. Create at least two mission profiles, not one 'Mars/Moon' mask — HIGH priority

**Profile A: strict exposed-surface prospecting (Moon-like)**. Strongly prefer barren and exposed rock/soil; reject confidently mapped water, forests, cropland and built-up land; generally reject extensive vegetation but keep mixed/uncertain cells available for higher-resolution review. Snow and ice should be an explicit choice, not silently accepted.

**Profile B: Mars field-operations (broader)**. Permit barren, arid shrublands and some grassland *as candidates* when other evidence shows sparse vegetation or suitable soil; avoid assuming all savanna qualifies. Downstream slope, geology, accessibility and seasonal vegetation conditions determine final ranking. 'Mars-like' can mean geology, field operations, robotics mobility, environmental stress or a combination—define the analog objective before the exact classes.

**Optional Profile C: polar/icy environments**. Accept snow/ice where relevant. Antarctica's area can dominate the answer, so report polar results separately and note practical accessibility constraints. Do not globally discard or globally accept Antarctica for all missions.

These are **provisional design rules**, not experimentally validated mission tolerances. Let the team agree on target analog characteristics and success criteria before hardcoding a final list of classes.

### T3. Preserve 'unknown' — HIGH priority, low implementation effort

At minimum, classify `eligible`, `excluded`, and `unknown` separately. An area with missing/low-quality observations should not become **confirmed suitable**. At the same time, don't let missingness eliminate a potentially strong analog unless safety and task requirements make that necessary. Record `reason_codes` and `source_coverage` so downstream decisions are explainable.

### T4. Keep information instead of only a boolean mask — HIGH priority for the database schema

For each coarse pixel or aggregated H3 cell, retain relevant features such as class proportions, valid-data fraction, source/year, land/water fraction, dominant class and exclusion reasons. For terrain, do **not** store only mean elevation or mean slope: keep distributions or quantiles (min, median, p90/p95, max where meaningful), terrain roughness and source resolution/coverage. A terrain average can hide a steep crater wall, cliff or locally flat landing zone.

### T5. Combine datasets without assuming independence — MEDIUM priority

MCD12C1 is an aggregate derivative of MCD12Q1, not independent corroboration. MODIS, VIIRS and Esri measurements can have correlated errors and different observation dates. Do not invent a probability or confidence by averaging their class votes without calibration. Treat cross-source disagreement as a reason for review, and preserve source dates. GHSL E2020 is from a different reference year from the 2023 land-cover audit; this can be documented rather than perfectly synchronized for the hackathon.

### T6. Coarse-to-fine filtering and defensible uncertainty — HIGH priority

A good staged architecture is:

1. **Coarse global prefilter**: Natural Earth land, obvious water, clearly urban/intensely agricultural areas, and confidently incompatible broad cover. Retain uncertain/mixed cells.
2. **H3 resolution-7 candidate index**: summarize available measurements and their quality; resolution-7 is the team's selected working scale, **not** a claim that all raw measurements have this precision.
3. **Higher-resolution local analysis**: use original source pixels, DEM/terrain derivatives, detailed vegetation/human footprint and site constraints to vet interesting cells.
4. **Mission-specific rank and explain**: only rank locations that have passed the profile-specific requirements; expose unknowns, ranking assumptions, and sensitivity to thresholds.

Avoid making an r7 Boolean from a coarse pixel and then describing all r7 subcells as accurately classified. If storage allows, represent fractional cell overlap, quality and mixed cover; otherwise mark uncertain cells for later inspection.

### T7. Human footprint needs separate consideration — MEDIUM priority

GHSL population is not the same as all human disturbance. Remote roads, mines, quarries, airstrips and industrial corridors can affect analog suitability even with near-zero residential population. Rather than obtaining every global infrastructure layer immediately, add this as a **later-stage veto/check** for shortlisted sites. Preserve room in the schema for `human_footprint_status` and evidence source.

### T8. Separate analog relevance from logistics — MEDIUM priority

A location can be geomorphologically excellent but impractical, restricted, environmentally sensitive or dangerous. 'Scientific analog similarity' and 'mission practicality/access' should be separate dimensions. Access may be preferable to rank *after* the scientific match, depending on the mission. Do not use land cover alone to declare a NASA-ready site.

### T9. Use VIIRS correctly when adding vegetation seasonality — MEDIUM priority

The 12 monthly VIIRS 2023 files can help assess seasonal vegetation activity, but vegetation indices are not the same as land-cover class percentages or exact fractional vegetation cover. Use their documented scale factors, QA, nodata and cloud/snow conventions before deriving max/median or seasonal variability. The audit confirms their availability, **not** that these indices are already integrated into the filter.

### T10. Protect the global r7 migration from implicit behavior changes — MEDIUM priority

Keep the 0.05° audit untouched and independent of H3. The inventory identified H3 resolution 8 settings in the teammate's global filter and regional pilot, r6 terrain benchmarking, and r7 already used in calibration. Migration should first specify a common configuration and schema, convert one **small regional pilot**, verify indexing/geometry and retained-area behavior, and only then generate global r7 outputs. H3's average r7 hexagon area is ~5.161 km² (r8 ~0.737 km²); actual cell areas vary considerably, so `area / average_cell_area` is an estimate, not a precise cell count.

## 5. Priority list: what to do now vs what not to overthink

| Priority | Item | Why |
|---|---|---|
| **Do now** | Prevent unknown data from silently passing as suitable | Incorrect evidence claim; easy guardrail |
| **Do now** | Agree on two mission profiles | Determines which classes should actually be retained |
| **Do now** | Test a small suite of known good/bad locations | Directly tests false-negative risk |
| **Do now** | Document denominators and add area closure test | Prevents confusing reports; low cost |
| **Do soon** | Reconcile Natural Earth/MODIS land boundary | Clarifies ~1.67 M km² difference |
| **Do soon** | Validate class fractions, overlap accounting, quality/QA | Protects scientific interpretation |
| **Do soon** | Reproduce GHSL+Esri v2 with consistent dates and stages | Explains 85.8 M km² if still important |
| **After policy is agreed** | Migrate a small regional pilot to H3 r7 | Tests schema and geometry without global cost |
| **Later** | Global detailed human footprint; sophisticated probability calibration | Valuable improvements, not prerequisites for the first credible demonstration |
| **Avoid** | Tuning policy just to exclude 80%+, redownloading present datasets, regenerating global H3 prematurely | Wastes time without improving accuracy |

## 6. Minimal validation experiment for the team

Choose roughly 8–12 **verified geographic controls** rather than hundreds of random pixels. Include several strongly barren/exposed regions, several vegetated controls, cropland, urban/built-up, open water, ice/polar terrain and at least one deliberately mixed/coastal cell. For each, record location and geographic point, ground-truth rationale/source, expected result **for each mission profile**, observed mask result, 'eligible/excluded/unknown', and the reason code.

**Most important metric:** among known good analog sites, how many does the **first-stage filter** incorrectly remove (false-negative count/recall)? Also count obvious negative controls that pass, but tolerate some for later processing. Check interesting errors in surrounding pixels because geolocation and coarse boundaries may affect individual point samples.

A particularly convincing demonstration would show three maps: (1) raw coarse land-cover categories, (2) permissive candidate mask + unknowns, and (3) final ranked candidates after fine-scale terrain checks. These need only cover **one local study region**, not the globe.

If outcomes change substantially when allowing open shrublands or grassland, report that sensitivity honestly. Do not calibrate threshold rules using only the very sites that will be used as independent validation controls.

## 7. Questions for teammate consultation

1. **What makes a place a 'good analog' for our first demo?** Geological morphology, rover traversability, barren appearance, polar operations, or research accessibility? Pick a precise mission profile and top two or three criteria.
2. **Which mistakes do we care about most?** A missed high-quality site, or extra processing for an unsuitable site? What is our realistic compute budget for the second stage?
3. **What level of vegetation is acceptable in a Mars field-ops analog?** Do we use MODIS category only for coarse screening and a separate QA-aware vegetation index for verification?
4. **Should Antarctica/snow/ice be a separate search mode?** It accounts for a large fraction of the current retained area.
5. **Do we permit mixed pixels to proceed with an uncertainty flag?** That minimizes early false negatives but increases later processing.
6. **Can we supply a small independent list of positive/negative control sites?** Prefer locations teammates can verify from satellite imagery or existing analog field studies.
7. **What do we need from the final H3 record?** At least coverage/quality, land-cover fractions, terrain distributions, mission-specific eligibility and explicit reasons.
8. **Is reproducing the 85.8 M km² result necessary for scientific comparison, or can it stay a known limitation while we build a credible pilot?**

## 8. Suggested immediate action and acceptance criteria

**Next milestone (lightweight): `LC-POLICY-01 — mission-specific filter + geographic sanity check`.** Do not repeat the full dataset validation or begin a global H3 build.

Deliver a small policy configuration file, a clear `eligible/excluded/unknown` implementation for the current coarse grid, a CSV with 8–12 independently checked sites, and a summary showing where each profile passes/fails and why. Add tests demonstrating that missing data cannot become 'confirmed suitable' and that area-weighting handles latitude. Update the report's denominator labels. Stop there unless the results reveal a consequential failure.

**Acceptance criteria:** no silent unknown→suitable conversions; known barren controls survive the permissive profile; obvious water/city controls are excluded; mixed/coastal controls are flagged or explained; no raw datasets in Git; no global r7 grid generated; current teammate pipelines remain untouched.

## 9. Provenance and references

**Project evidence:** the user's pasted Claude Code audit summary (land-cover statistics, dataset validation counts, policy comparisons, H3 inventory, existing pipeline limitations). Source code and regenerated CSVs were **not** independently inspected in preparing this consultation note.

**External technical references:**

- NASA Open Data: MCD12C1 V061, 0.05° aggregated and reprojected MCD12Q1, subpixel class fractions: https://data.nasa.gov/dataset/modis-terraaqua-land-cover-type-yearly-l3-global-0-05deg-cmg-v061-bc7b8
- NASA/LP DAAC MODIS MCD12Q1 & MCD12C1 User Guide, class meanings, QA and land-cover classifications: https://lpdaac.usgs.gov/documents/1409/MCD12_User_Guide_V61.pdf
- H3 official resolution statistics: https://h3geo.org/docs/core-library/restable/

**Unresolved / not asserted:** numerical ground-truth accuracy of each MODIS class, correctness of the teammate's full 85.8 M km² v2 pipeline, raw-code correctness of 51 checks, Esri temporal consistency after future fixes, absolute quality of final analog selections. Those require independent validation rather than inference from passing tests.
