"""Task 1: validate the downloaded datasets in place (nothing is downloaded).

Checks filenames, counts, product versions, years, readability (every file is opened and the
analysed band is fully decoded), expected bands, fill values and coordinate systems.
The only network call is an optional CMR *metadata* query (granule names, no data) used to
confirm the MCD12Q1 tile list is complete; pass --offline to skip it.

Outputs: results/dataset_validation.json and results/dataset_validation_report.md
Usage:   .venv/Scripts/python.exe -I scripts/01_validate_datasets.py [--data DIR] [--offline]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import warnings
import zipfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

import numpy as np  # noqa: E402

warnings.filterwarnings("ignore", category=Warning, module="rasterio")
CHECKS: list[dict] = []
FACTS: dict = {}


def check(dataset: str, name: str, ok: bool | None, observed, expected="") -> None:
    status = "PASS" if ok else ("INFO" if ok is None else "FAIL")
    CHECKS.append({"dataset": dataset, "check": name, "status": status,
                   "observed": str(observed), "expected": str(expected)})
    print(f"[{status}] {dataset}: {name}: {observed}" + (f" (expected {expected})" if expected else ""), flush=True)


def warn(dataset: str, name: str, observed, expected="") -> None:
    CHECKS.append({"dataset": dataset, "check": name, "status": "WARN",
                   "observed": str(observed), "expected": str(expected)})
    print(f"[WARN] {dataset}: {name}: {observed}", flush=True)


def crc32_file(p: Path) -> int:
    c = 0
    with open(p, "rb") as f:
        while chunk := f.read(1 << 24):
            c = zlib.crc32(chunk, c)
    return c & 0xFFFFFFFF


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(1 << 24):
            h.update(chunk)
    return h.hexdigest()


def odl_value(text: str, key: str) -> str | None:
    """VALUE of an ODL OBJECT (HDF-EOS CoreMetadata), e.g. SHORTNAME -> MCD12C1."""
    m = re.search(rf"OBJECT\s*=\s*{key}\b.*?VALUE\s*=\s*\"?([^\"\n]+)\"?", text, re.S)
    return m.group(1).strip() if m else None


def struct_value(text: str, key: str) -> str | None:
    m = re.search(rf"{key}=([^\n\t]+)", text)
    return m.group(1).strip() if m else None


# --- Natural Earth -----------------------------------------------------------------------------

def natural_earth(data: Path) -> None:
    ds = "natural-earth"
    p = data / C.NE_ZIP
    files = sorted(p.parent.iterdir())
    check(ds, "files in folder", [f.name for f in files] == ["10m_physical.zip"], [f.name for f in files], "10m_physical.zip")
    with zipfile.ZipFile(p) as z:
        bad = z.testzip()
        check(ds, "zip CRC test (all members)", bad is None, "all members OK" if bad is None else f"corrupt: {bad}")
        names = set(z.namelist())
        need = {f"ne_10m_land.{e}" for e in ("shp", "shx", "dbf", "prj", "cpg")}
        check(ds, "ne_10m_land shapefile components", need <= names, sorted(need & names))
        version = z.read("ne_10m_land.VERSION.txt").decode().strip() if "ne_10m_land.VERSION.txt" in names else None
        prj = z.read("ne_10m_land.prj").decode(errors="replace")
        check(ds, "layer count in archive", None, f"{len([n for n in names if n.endswith('.shp')])} shapefiles")
    check(ds, "ne_10m_land version", version is not None, version)
    check(ds, "coordinate system (.prj)", "WGS_1984" in prj and "GEOGCS" in prj, prj[:80] + "...", "GEOGCS WGS 84 (EPSG:4326)")
    r, geoms = C.ne_land_shapes(data)
    check(ds, "geometry type", r.shapeType == 5, r.shapeTypeName, "POLYGON")
    check(ds, "feature count", len(r) > 0, len(r))
    bbox = [round(float(b), 3) for b in r.bbox]
    check(ds, "bbox (lon/lat degrees)", -180.01 <= bbox[0] and bbox[2] <= 180.01 and bbox[1] >= -90.01, bbox)
    area = C.pixel_area_km2()
    land = C.ne_land_mask(data)
    south = C.south_mask()
    land_km2 = C.area_sum(land, area)
    land_s60 = C.area_sum(land & south, area)
    FACTS["ne_land_km2"] = land_km2
    FACTS["ne_land_south_of_60S_km2"] = land_s60
    FACTS["ne_version"] = version
    check(ds, "land area at 0.05 deg, pixel-centre rule", 1.40e8 < land_km2 < 1.55e8,
          f"{land_km2:,.0f} km2 (south of 60S: {land_s60:,.0f})", "~1.47e8 km2 incl. Antarctica")


# --- GHSL --------------------------------------------------------------------------------------

def ghsl(data: Path) -> None:
    import rasterio
    from rasterio.windows import Window

    ds = "ghsl-population"
    d = data / "ghsl-population"
    zp = d / "GHS_POP_E2020_GLOBE_R2023A_4326_30ss_V1_0.zip"
    check(ds, "archive present", zp.exists(), zp.name)
    m = re.match(r"GHS_POP_E(\d{4})_GLOBE_(R\d{4}A)_(\d+)_(\d+ss)_V(\d+_\d+)\.zip", zp.name)
    check(ds, "filename: epoch / release / CRS / resolution / version", bool(m) and m.groups() == ("2020", "R2023A", "4326", "30ss", "1_0"),
          m.groups() if m else None, "('2020', 'R2023A', '4326', '30ss', '1_0')")
    with zipfile.ZipFile(zp) as z:
        t0 = time.time()
        bad = z.testzip()
        check(ds, "zip CRC test (all members)", bad is None, f"OK in {time.time() - t0:.0f} s" if bad is None else f"corrupt: {bad}")
        members = {i.filename: (i.file_size, i.CRC) for i in z.infolist()}
    ex = d / "extracted"
    for name, (size, crc) in members.items():
        q = ex / name
        if not q.exists():
            check(ds, f"extracted {name}", False, "missing")
            continue
        same = q.stat().st_size == size and crc32_file(q) == crc
        check(ds, f"extracted {name} matches zip (size + CRC32)", same, f"{q.stat().st_size:,} bytes")
    extra = sorted(p.name for p in ex.iterdir() if p.name not in members)
    check(ds, "no extra files in extracted/", not extra, extra or "none")

    tif = ex / "GHS_POP_E2020_GLOBE_R2023A_4326_30ss_V1_0.tif"
    with rasterio.open(tif) as s:
        check(ds, "driver / band count", s.driver == "GTiff" and s.count == 1, f"{s.driver}, {s.count} band")
        check(ds, "CRS", s.crs is not None and s.crs.to_epsg() == 4326, s.crs.to_string() if s.crs else None, "EPSG:4326")
        res = (s.transform.a, -s.transform.e)
        check(ds, "pixel size", all(abs(r - 1 / 120) < 1e-9 for r in res), f"{res[0]:.10f} x {res[1]:.10f} deg", "30 arcsec = 0.0083333333 deg")
        check(ds, "size / bounds", True, f"{s.width} x {s.height}; bounds {tuple(round(b, 4) for b in s.bounds)}")
        nodata_tag = s.nodata
        total, n_nodata, n_neg, vmax, t0 = 0.0, 0, 0, 0.0, time.time()
        for r in range(0, s.height, 1200):
            n = min(1200, s.height - r)
            a = s.read(1, window=Window(0, r, s.width, n))
            nod = a == s.nodata
            n_nodata += int(nod.sum())
            v = a[~nod]
            n_neg += int((v < 0).sum())
            v = v[v > 0]
            total += float(v.sum(dtype=np.float64))
            vmax = max(vmax, float(v.max()) if v.size else 0.0)
        FACTS["ghsl_population_total"] = total
        check(ds, "full band decoded; total population 2020", 7.0e9 < total < 8.5e9,
              f"{total:,.0f} people ({time.time() - t0:.0f} s)", "~7.8e9")
        if nodata_tag is None:
            warn(ds, "dtype / nodata tag", f"{s.dtypes[0]}, no nodata tag in the GeoTIFF. Harmless here: the full read "
                 f"found {n_neg} negative values, so there is no sentinel to mask (global_mask.py also drops values <= 0)")
        check(ds, "nodata pixels / negative values", n_neg == 0, f"{n_nodata:,} nodata, {n_neg} negative, max {vmax:,.1f} people per pixel")
        has_ovr = (ex / (tif.name + ".ovr")).exists()
        check(ds, "external overview (.ovr) present", None, has_ovr)


# --- MCD12C1 -----------------------------------------------------------------------------------

def mcd12c1(data: Path) -> None:
    from pyhdf.SD import SD, SDC

    ds = "modis-mcd12c1-2023"
    files = sorted((data / ds).iterdir())
    check(ds, "file count", len(files) == 1, [f.name for f in files], "1 file")
    p = files[0]
    m = re.match(r"MCD12C1\.A(\d{4})(\d{3})\.(\d{3})\.(\d{13})\.hdf$", p.name)
    check(ds, "filename: year / DOY / collection", bool(m) and m.group(1, 2, 3) == ("2023", "001", "061"),
          m.group(1, 2, 3) if m else p.name, "('2023', '001', '061')")
    f = SD(str(p), SDC.READ)
    ga = f.attributes()
    core = "".join(str(ga[k]) for k in sorted(ga) if k.startswith("CoreMetadata"))
    struct = "".join(str(ga[k]) for k in sorted(ga) if k.startswith("StructMetadata"))
    check(ds, "product DOI", ga.get("identifier_product_doi") == "10.5067/MODIS/MCD12C1.061", ga.get("identifier_product_doi"))
    check(ds, "ShortName", odl_value(core, "SHORTNAME") == "MCD12C1", odl_value(core, "SHORTNAME"))
    rng = (odl_value(core, "RANGEBEGINNINGDATE"), odl_value(core, "RANGEENDINGDATE"))
    check(ds, "temporal range", rng == ("2023-01-01", "2023-12-31"), rng)
    check(ds, "production time", None, odl_value(core, "PRODUCTIONDATETIME"))
    proj = (struct_value(struct, "Projection"), struct_value(struct, "XDim"), struct_value(struct, "YDim"),
            struct_value(struct, "UpperLeftPointMtrs"), struct_value(struct, "LowerRightMtrs"))
    check(ds, "grid: projection, XDim, YDim, corners (packed DMS)",
          proj == ("GCTP_GEO", "7200", "3600", "(-180000000.000000,90000000.000000)", "(180000000.000000,-90000000.000000)"),
          proj, "GCTP_GEO 7200 x 3600, -180..180 / 90..-90 => 0.05 deg lat/lon (WGS84 geographic)")
    sds = f.datasets()
    for name, shape, fill, vr in (("Land_Cover_Type_1_Percent", (3600, 7200, 17), 255, [0, 100]),
                                  ("Majority_Land_Cover_Type_1", (3600, 7200), 255, [0, 16])):
        a = f.select(name)
        att = a.attributes()
        ok = name in sds and tuple(sds[name][1]) == shape and sds[name][2] == 21 and att.get("_FillValue") == fill \
            and list(att.get("valid_range")) == vr
        check(ds, f"band {name}", ok, f"shape {tuple(sds[name][1])}, uint8, fill {att.get('_FillValue')}, valid {att.get('valid_range')}",
              f"{shape}, uint8, fill {fill}, valid {vr}")
        arr = a[:]
        bad = int(((arr > vr[1]) & (arr != fill)).sum())
        check(ds, f"{name}: full decode, values outside valid range (non-fill)", bad == 0,
              f"{bad} bad; {int((arr == fill).sum()):,} fill values")
        del arr
    f.end()
    check(ds, "other bands present", None, ", ".join(sorted(sds)))


# --- MCD12Q1 -----------------------------------------------------------------------------------

Q1_RE = re.compile(r"MCD12Q1\.A(\d{4})(\d{3})\.h(\d{2})v(\d{2})\.(\d{3})\.(\d{13})\.hdf$")


def cmr_mcd12q1() -> set[str] | None:
    import urllib.request

    url = ("https://cmr.earthdata.nasa.gov/search/granules.json?short_name=MCD12Q1&version=061"
           "&page_size=2000&temporal=2023-01-01T00:00:00Z,2023-01-02T00:00:00Z")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "landcover-audit"}), timeout=60) as r:
            entries = json.load(r)["feed"]["entry"]
        return {next(l["href"] for l in e["links"] if l["href"].endswith(".hdf")).rsplit("/", 1)[-1] for e in entries}
    except Exception as e:  # offline or CMR down: not fatal
        print("CMR query failed:", e)
        return None


def mcd12q1(data: Path, offline: bool) -> None:
    from pyhdf.SD import SD, SDC

    ds = "modis-mcd12q1-2023"
    files = sorted((data / ds).iterdir())
    hdf = [p for p in files if p.suffix == ".hdf"]
    check(ds, "file count", len(hdf) == 315 and len(files) == 315, f"{len(hdf)} .hdf of {len(files)} files", "315 (CMR count for 2023)")
    parsed = [Q1_RE.match(p.name) for p in hdf]
    bad_names = [p.name for p, m in zip(hdf, parsed) if not m]
    check(ds, "filenames match MCD12Q1.A2023001.hHHvVV.061.<prod>.hdf", not bad_names, bad_names or "all")
    good = [m for m in parsed if m]
    years = sorted({m.group(1) + m.group(2) for m in good})
    colls = sorted({m.group(5) for m in good})
    check(ds, "year / DOY", years == ["2023001"], years)
    check(ds, "collection", colls == ["061"], colls)
    tiles = [(int(m.group(3)), int(m.group(4))) for m in good]
    check(ds, "unique h/v tiles", len(set(tiles)) == len(tiles), f"{len(set(tiles))} unique of {len(tiles)}")
    FACTS["mcd12q1_tiles"] = sorted(f"h{h:02d}v{v:02d}" for h, v in tiles)
    vs = [v for _, v in tiles]
    check(ds, "tile rows covered (v)", None, f"v{min(vs):02d}..v{max(vs):02d}; tiles with v>=14 (south of ~50S): "
          + ", ".join(f"h{h:02d}v{v:02d}" for h, v in sorted(tiles) if v >= 14))

    if not offline:
        remote = cmr_mcd12q1()
        if remote is not None:
            local = {p.name for p in hdf}
            check(ds, "matches CMR granule list (metadata query)", remote == local,
                  f"CMR {len(remote)}, local {len(local)}, missing locally {sorted(remote - local)[:5]}, extra {sorted(local - remote)[:5]}")
        else:
            warn(ds, "CMR granule list", "query failed; completeness checked by count only")

    t0, problems, attrs_bad, hist = time.time(), [], [], np.zeros(256, np.int64)
    for p, m in zip(hdf, parsed):
        h, v = int(m.group(3)), int(m.group(4))
        try:
            f = SD(str(p), SDC.READ)
            ga = f.attributes()
            struct = "".join(str(ga[k]) for k in sorted(ga) if k.startswith("StructMetadata"))
            core = "".join(str(ga[k]) for k in sorted(ga) if k.startswith("CoreMetadata"))
            sel = f.select("LC_Type1")
            att = sel.attributes()
            lc = sel[:]
            f.end()
        except Exception as e:
            problems.append(f"{p.name}: {e}")
            continue
        ul = struct_value(struct, "UpperLeftPointMtrs")
        x0, y0 = (float(t) for t in ul.strip("()").split(","))
        ok = (lc.shape == (2400, 2400) and lc.dtype == np.uint8 and att.get("_FillValue") == 255
              and list(att.get("valid_range")) == [1, 17]
              and struct_value(struct, "Projection") == "GCTP_SNSOID"
              and struct_value(struct, "ProjParams").startswith("(6371007.181")
              and abs(x0 - (-20015109.354 + h * C.TILE_M)) < 1 and abs(y0 - (10007554.677 - v * C.TILE_M)) < 1
              and odl_value(core, "SHORTNAME") == "MCD12Q1"
              and (odl_value(core, "RANGEBEGINNINGDATE"), odl_value(core, "RANGEENDINGDATE")) == ("2023-01-01", "2023-12-31")
              and ga.get("identifier_product_doi") == "10.5067/MODIS/MCD12Q1.061")
        if not ok:
            attrs_bad.append(p.name)
        hist += np.bincount(lc.ravel(), minlength=256)
    check(ds, "every file opens and LC_Type1 fully decodes", not problems, problems or f"315/315 in {time.time() - t0:.0f} s")
    check(ds, "per-file metadata: LC_Type1 2400x2400 uint8, fill 255, valid 1..17, sinusoidal R=6371007.181, "
              "UL corner matches h/v, ShortName, 2023 range, DOI", not attrs_bad, attrs_bad or "all 315 consistent")
    out_of_range = {int(k): int(hist[k]) for k in np.nonzero(hist)[0] if not (1 <= k <= 17 or k == 255)}
    check(ds, "LC_Type1 values outside 1..17 and fill 255", not out_of_range, out_of_range or "none",)
    FACTS["mcd12q1_fill_pixels"] = int(hist[255])
    check(ds, "fill (255) pixels across tiles", None, f"{int(hist[255]):,} (tile corners outside the sinusoidal globe and unmapped areas)")

    dup = data / "duplicates"
    if dup.exists():
        d_files = sorted(dup.iterdir())
        same, differ, orphan = 0, [], []
        for q in d_files:
            orig = data / ds / q.name.replace(" (1)", "")
            if not orig.exists():
                orphan.append(q.name)
            elif sha256(q) == sha256(orig):
                same += 1
            else:
                differ.append(q.name)
        check("duplicates", "every file is a byte-identical copy of a tile in modis-mcd12q1-2023 (SHA-256)",
              not differ and not orphan, f"{same}/{len(d_files)} identical; differ {differ}; no original {orphan}")
    inc = data / "incoming"
    if inc.exists():
        check("incoming", "folder empty", not any(inc.iterdir()), [p.name for p in inc.iterdir()] or "empty")


# --- VIIRS VNP13C2 -----------------------------------------------------------------------------

V_RE = re.compile(r"VNP13C2\.A(\d{4})(\d{3})\.(\d{3})\.(\d{13})\.h5$")
MONTH_DOY = ["001", "032", "060", "091", "121", "152", "182", "213", "244", "274", "305", "335"]
NDVI = "HDFEOS/GRIDS/VIIRS_Grid_monthly_VI_CMG/Data_Fields/CMG_0.05_Deg_monthly_NDVI"


def viirs(data: Path) -> None:
    import calendar

    import rasterio

    ds = "viirs-2023"
    files = sorted((data / ds).iterdir())
    check(ds, "file count", len(files) == 12, len(files), 12)
    parsed = [V_RE.match(p.name) for p in files]
    check(ds, "filenames match VNP13C2.A2023DDD.002.<prod>.h5", all(parsed), [p.name for p, m in zip(files, parsed) if not m] or "all")
    doys = sorted(m.group(2) for m in parsed if m)
    check(ds, "one granule per month (DOY of month start, 2023)", doys == MONTH_DOY and all(m.group(1) == "2023" for m in parsed if m), doys)
    check(ds, "collection", all(m.group(3) == "002" for m in parsed if m), sorted({m.group(3) for m in parsed if m}))
    rows, bad = [], []
    for i, p in enumerate(files):
        with rasterio.open(p) as s:
            t = s.tags()
        pre = "HDFEOS_GRIDS_VIIRS_Grid_monthly_VI_CMG_Data_Fields_CMG_0.05_Deg_monthly_NDVI_"
        fill, scale, vr = t.get(pre + "_FillValue"), t.get(pre + "scale_factor"), t.get(pre + "valid_range")
        last = calendar.monthrange(2023, i + 1)[1]
        meta_ok = (t.get("ShortName") == "VNP13C2" and t.get("VersionID") == "002"
                   and t.get("RangeBeginningDate") == f"2023-{i + 1:02d}-01"
                   and t.get("RangeEndingDate") == f"2023-{i + 1:02d}-{last:02d}"
                   and t.get("DataResolution") == "0.05deg"
                   and (t.get("NorthBoundingCoord"), t.get("SouthBoundingCoord"), t.get("WestBoundingCoord"), t.get("EastBoundingCoord")) == ("90", "-90", "-180", "180"))
        with rasterio.open(f'HDF5:"{p}"://{NDVI}') as s:
            a = s.read(1)
        lo, hi = (int(float(x)) for x in vr.split()) if vr else (-10000, 10000)
        valid = (a >= lo) & (a <= hi)
        fill_codes = [int(float(x)) for x in fill.split()] if fill else []
        n_fill = int(np.isin(a, fill_codes).sum())
        other = int(a.size - valid.sum() - n_fill)
        if not (meta_ok and a.shape == (3600, 7200) and a.dtype == np.int16):
            bad.append(p.name)
        rows.append((p.name[:16], fill, scale, vr, round(100 * valid.mean(), 2), n_fill, other))
        del a, valid
    check(ds, "metadata: ShortName VNP13C2, VersionID 002, month range, 0.05deg, global bounds; NDVI 3600x7200 int16",
          not bad, bad or "all 12 consistent")
    fills = sorted({r[1] for r in rows}); scales = sorted({r[2] for r in rows}); vrs = sorted({r[3] for r in rows})
    check(ds, "NDVI fill / scale / valid range", fills == ["-15000 -14000 -13000 -12000"] and scales == ["0.0001"]
          and vrs == ["-10000 10000"], f"fill {fills}, scale {scales}, valid {vrs}",
          "four fill codes, scale 0.0001, valid -10000..10000 (global_mask.py keeps a > -10000, which excludes all four)")
    check(ds, "NDVI full decode: % valid pixels per month (Jan..Dec)", all(r[6] == 0 for r in rows),
          ", ".join(f"{r[4]}" for r in rows) + f"; non-fill out-of-range: {sum(r[6] for r in rows)}")
    check(ds, "coordinate system", None, "HDF-EOS5 CMG: no GDAL geotransform; grid implied by attributes "
          "(0.05 deg, 90..-90, -180..180, geographic WGS84), same as MCD12C1")


def render(path: Path) -> None:
    by_ds: dict[str, list[dict]] = {}
    for c in CHECKS:
        by_ds.setdefault(c["dataset"], []).append(c)
    n = {s: sum(c["status"] == s for c in CHECKS) for s in ("PASS", "FAIL", "WARN", "INFO")}
    lines = ["# Dataset validation report", "",
             f"Generated by `scripts/01_validate_datasets.py` on {time.strftime('%Y-%m-%d %H:%M')}. "
             "Datasets read in place from the dataset root (`--data`); no data was downloaded "
             "(one NASA CMR metadata query listed the MCD12Q1 granule names to confirm the tile set is complete).", "",
             f"**{n['PASS']} pass, {n['FAIL']} fail, {n['WARN']} warn, {n['INFO']} info.**", ""]
    for d, cs in by_ds.items():
        lines += [f"## {d}", "", "| Status | Check | Observed | Expected |", "|---|---|---|---|"]
        for c in cs:
            obs = c["observed"].replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {c['status']} | {c['check']} | {obs} | {c['expected'].replace('|', '/')} |")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, default=C.DEFAULT_DATA)
    ap.add_argument("--offline", action="store_true", help="skip the CMR metadata query")
    a = ap.parse_args()
    t0 = time.time()
    for fn in (natural_earth, ghsl, mcd12c1, viirs):
        fn(a.data)
    mcd12q1(a.data, a.offline)
    C.RESULTS.mkdir(parents=True, exist_ok=True)
    (C.RESULTS / "dataset_validation.json").write_text(json.dumps({"checks": CHECKS, "facts": FACTS}, indent=1))
    render(C.RESULTS / "dataset_validation_report.md")
    print(f"done in {time.time() - t0:.0f} s; {sum(c['status'] == 'FAIL' for c in CHECKS)} failures")


if __name__ == "__main__":
    main()
