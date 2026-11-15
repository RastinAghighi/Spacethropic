# Land-cover audit of the global filter (MODIS 2023)

Why does the global Earth filter (teammate's `global_mask_v2.py`, branch `data/cleaning`,
commit `475bf4e`) keep **85.8 M km²** of land? This experiment measures every MODIS IGBP
land-cover class on Earth and re-applies the filter's land-cover rule, then stricter
vegetation policies, from the raw 2023 MODIS files.

- **Findings:** [REPORT.md](REPORT.md)
- **H3 resolution 7:** [H3_RESOLUTION_7_INVENTORY.md](H3_RESOLUTION_7_INVENTORY.md) lists the
  places in the code where r8 is hard-coded. This analysis itself has no H3 dependency.

The teammate's pipeline is read, never changed. Raw datasets stay outside Git in
`C:\Dev\Spacethropic-datasets` (override with `--data DIR` or `SPACETHROPIC_DATASETS`).

## Layout

| Path | What |
|---|---|
| `scripts/common.py` | 0.05° grid, exact spherical pixel areas, IGBP class table, Natural Earth mask |
| `scripts/01_validate_datasets.py` | Task 1: filenames, counts, versions, years, full decode, bands, fill values, CRS |
| `scripts/02_mcd12q1_tiles.py` | MCD12Q1 500 m tiles: exact class areas, plus per-class counts binned to 0.05° the same way `landcover_fractions.py` does |
| `scripts/03_class_areas.py` | MCD12C1 class areas (area-weighted), checks on how the percent layers are read, MCD12Q1 cross-check |
| `scripts/04_policy_scenarios.py` | The v2 land-cover rule and stricter policies, with both MODIS products |
| `results/dataset_validation_report.md` (+ `.json`) | Validation report |
| `results/global_landcover_class_area.csv` | Every original IGBP class, no-data, totals |
| `results/global_landcover_broad_area.csv` | The requested categories (barren, grassland, …) |
| `results/filter_policy_comparison.csv` | Land kept per policy and source |
| `results/filter_policy_kept_composition.csv` | Which classes make up the kept area, per policy |
| `work/` (git-ignored) | Intermediates: NE land mask, MCD12Q1 0.05° counts (440 MB), logs, checks |

## Run

```powershell
cd experiments\landcover_audit_2023
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -I scripts\01_validate_datasets.py   # ~3 min (add --offline to skip the CMR metadata query)
.venv\Scripts\python.exe -I scripts\02_mcd12q1_tiles.py       # ~5 min, 315 tiles streamed one tile row at a time
.venv\Scripts\python.exe -I scripts\03_class_areas.py         # MCD12C1, 200-row slabs
.venv\Scripts\python.exe -I scripts\04_policy_scenarios.py    # 100-row slabs of both sources
```

`-I` keeps Python from importing anything from the current directory or the user site
(the scripts add their own folder to the path).

Memory: the laptop has 16 GB with about 4.5 GB free. No script holds more than one global
raster in RAM. MCD12Q1 is accumulated one 10° tile row at a time into an on-disk memmap;
MCD12C1 and the memmap are read in row slabs (about 25–50 MB each). The largest resident array
is the 26 MB Natural Earth mask.
