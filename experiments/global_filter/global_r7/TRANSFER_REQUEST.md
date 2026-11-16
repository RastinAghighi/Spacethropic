# Exact request to the data teammate

The new PC has only the Git clone. Natural Earth and GHSL have now been downloaded
and processed successfully; **do not transfer them again**. Esri is optional and
is not needed to unblock the explicitly labelled MODIS-only baseline.

Please send these files from the original audit machine:

1. `experiments/landcover_audit_2023/work/mcd12q1_counts_0p05.npy`
   (likely under `C:\Dev\Spacethropic-integration\`). This is the critical file:
   `uint8`, shape `(17, 3600, 7200)`, approximately **440,640,128 bytes / 420 MiB**.
   It must be the completed 2023 v061 cache built by audit script 02, not `.part`.
   Class index 0 is water, 1–16 follow IGBP. Grid origin -180/+90, 0.05 degrees.
2. `experiments/landcover_audit_2023/work/mcd12q1_class_totals.json`
   (small provenance/check output from the same run).
3. SHA-256 of both files, the source Git commit, and confirmation that the cache
   used all 315 unique `MCD12Q1.A2023001.h??v??.061.<production timestamp>.hdf`
   tiles. Include the source tile filename/hash inventory if available.

Optional, useful for exact reproduction of the old regional checks:

* `work/site_kept_windows.npz` (the committed JSON only contains a limited
  footprint, particularly at Drumheller).
* `work/pilot_inputs/*_mcd12q1_lc.tif` for Drumheller, Atacama, Hanksville,
  Beacon Valley and Don Juan Pond, including QC files if available.
* Optional original Esri aggregate `landcover_esri_2023.npz` with its provenance
  for a **separate future** full-v2 run. This implementation does not silently
  average that file into the MODIS-only baseline.

On the source PC, hashes can be generated without changing the data:

```powershell
Get-FileHash -Algorithm SHA256 '<audit-folder>\work\mcd12q1_counts_0p05.npy'
Get-FileHash -Algorithm SHA256 '<audit-folder>\work\mcd12q1_class_totals.json'
```

Place the received cache and metadata on this PC in:

`W:\Spacethropic-data\raw\modis-cache\`

Verify the hashes against the teammate's values, then run the `prepare.py mask`,
fresh `validate.py --mask`, `benchmark.py`, and resumable `run.py` commands in
[README.md](README.md). Global execution must follow those fresh input checks.

## If the cache cannot be sent

The repository **can regenerate it** without repeating the scientific audit:
`experiments/landcover_audit_2023/scripts/02_mcd12q1_tiles.py` reads the 315 raw
HDF4 tiles, bins `LC_Type1` by source pixel center, and writes the counts plus
totals. Put the files under
`W:\Spacethropic-data\raw\modis-mcd12q1-2023\`. Then, from the repository root:

```powershell
& .\.venv\Scripts\python.exe -I experiments/landcover_audit_2023/scripts/02_mcd12q1_tiles.py `
  --data W:\Spacethropic-data\raw
```

The existing script writes the cache to the audit's Git-ignored `work/` directory.
Copy the completed `.npy` and totals JSON to the external `raw/modis-cache/`
directory; compare SHA-256 before using them. Script 02 checks 315 matching names,
streams one 10-degree tile row, and atomically replaces its completed cache.
It is not a downloader. No VIIRS, NASADEM, GHSL or Natural Earth file is needed
by script 02 itself. Do not run scripts 01–08 just to regenerate this cache.

The catalog inventory was retrieved from NASA CMR and is saved externally as
`W:\Spacethropic-data\raw\modis_2023_inventory.json` (315 Q1 URLs and one C1 URL).
Regenerate it with `fetch_inputs.py --only modis`. Download via an authorized
Earthdata account, or transfer the existing files. Never place tokens in Git.

An alternative input is the single global file
`MCD12C1.A2023001.061.2024251212901.hdf`:

[NASA Earthdata protected download](https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/MCD12C1.061/MCD12C1.A2023001.061.2024251212901/MCD12C1.A2023001.061.2024251212901.hdf).
CMR reports approximately 1,187 MiB. This route is supported with `--mcd12c1`,
but is explicitly a C1 fallback, not exact Q1 reproduction; it has no Q1
count-based barren rescue flag. The counts cache is smaller and preferable.

## Public inputs already available

* [Natural Earth 5.1.1 land ZIP](https://naturalearth.s3.amazonaws.com/5.1.1/10m_physical/ne_10m_land.zip),
  3,269,070 bytes; SHA-256
  `e547d749445eaa0964aba76738090ec88f5e63c4585122170f98c67a7ea922dc`.
* [GHSL E2020 R2023A WGS84 30 arcsecond V1-0 ZIP](https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_POP_GLOBE_R2023A/GHS_POP_E2020_GLOBE_R2023A_4326_30ss/V1-0/GHS_POP_E2020_GLOBE_R2023A_4326_30ss_V1_0.zip),
  482,351,880 bytes; SHA-256
  `8de311f475322cebb920edd870dda0f50fb1750a2a2c0f533c9ecf2f41589c45`.

Both ZIPs have CRC checks and download receipts (`.zip.json`); GHSL's extracted
GeoTIFF is 382,936,052 bytes. Raw files and the prepared public arrays live outside
Git under `W:\Spacethropic-data`.
