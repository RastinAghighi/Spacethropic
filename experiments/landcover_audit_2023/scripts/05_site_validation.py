"""Site validation of the prefilter: does the existing v2 rule keep analogs and drop non-analogs?

For every site in validation_sites.py this reproduces the teammate's global_mask_v2.py decision
(commit 475bf4e) on the 0.05 deg pixel that holds the site and on every pixel of its region, from
local data only:
  Natural Earth 1:10m land        pixel-centre test (cached mask from script 01/03)
  GHSL GHS-POP E2020 30"          summed into 0.05 deg pixels by source-pixel centre, / exact area
  MODIS MCD12Q1 2023              0.05 deg class counts from script 02, binned exactly as
                                  landcover_fractions.py; shares in float32 like the teammate
  NOT AVAILABLE: Esri 10 m LULC (the v2 run averaged it with MODIS). The decision here is
  therefore "v2, MODIS-only". For each pixel the Esri non-analog share that would flip the
  decision under the equal-weight average is reported (esri_flip_*).
Cross-checks and context, not part of the v2 rule:
  MCD12C1 2023 percent layer      the same rule on NASA's own 0.05 deg aggregate
  VIIRS VNP13C2 2023              peak monthly NDVI and number of valid months (v1's input)
  MCD12Q1 500 m LC_Type1 + QC     class mix and QC flags of the 500 m pixels inside the site pixel
                                  and region; the largest 8-connected barren patch, and how much
                                  of it lies in removed 0.05 deg pixels

Outputs: results/site_validation.csv, results/site_validation_detail.json,
         work/site_kept_windows.npz (kept flags around each site, for the r7 check in script 07)
Usage:   .venv/Scripts/python.exe -I scripts/05_site_validation.py [--data DIR]   (after 02)
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
import validation_sites as VS  # noqa: E402

import numpy as np  # noqa: E402
import rasterio  # noqa: E402
from rasterio.windows import Window, from_bounds  # noqa: E402
from pyhdf.SD import SD, SDC  # noqa: E402

# --- v2 rule constants (pipeline/analysis/global_mask_v2.py, global_mask.py) ---------------------
WATER_MAX, BUILT_MAX, VEG_MAX, NON_ANALOG_MAX, POP_MAX = 0.5, 0.25, 0.5, 0.5, 50.0
OCEAN, POPULATED, VEGETATED = 1, 2, 4
VEG_CLASSES = [k for k, g in C.TEAM_GROUP.items() if g == "veg"]          # MCD12C1 numbering
OTHER_CLASSES = [k for k, g in C.TEAM_GROUP.items() if g == "other"]
WATER, BUILT, BARREN, SNOW = 0, 13, 16, 15

# --- MODIS sinusoidal grid ------------------------------------------------------------------------
X0, Y0 = -20015109.354, 10007554.677
Q1_RE = re.compile(r"MCD12Q1\.A2023001\.h(\d{2})v(\d{2})\.061\.\d{13}\.hdf$")
Q1_TO_C1 = np.full(256, -1, np.int64)
for _v in range(1, 18):
    Q1_TO_C1[_v] = C.q1_to_c1(_v)
QC_NAMES = {0: "classified land", 1: "unclassified land -> barren", 2: "classified water",
            3: "unclassified water", 4: "sea ice -> water", 5: "misclassified water -> 2nd label",
            6: "omitted snow/ice -> snow/ice", 7: "misclassified snow/ice -> barren",
            8: "backfilled label", 9: "forest type changed", 10: "no data (water mask)", 255: "fill"}
NDVI_DATASET = "//HDFEOS/GRIDS/VIIRS_Grid_monthly_VI_CMG/Data_Fields/CMG_0.05_Deg_monthly_NDVI"


def q1_tiles(data: Path) -> dict[tuple[int, int], Path]:
    out = {}
    for p in (data / "modis-mcd12q1-2023").iterdir():
        m = Q1_RE.match(p.name)
        if m:
            out[(int(m.group(1)), int(m.group(2)))] = p
    return out


class Q1Reader:
    """LC_Type1 and QC from MCD12Q1 tiles, by global sinusoidal pixel index (gi row, gj col)."""

    def __init__(self, data: Path):
        self.paths = q1_tiles(data)
        self.cache: dict[tuple[int, int], tuple[np.ndarray, np.ndarray] | None] = {}

    def tile(self, h: int, v: int):
        if (h, v) not in self.cache:
            if len(self.cache) > 12:
                self.cache.pop(next(iter(self.cache)))
            p = self.paths.get((h, v))
            if p is None:
                self.cache[(h, v)] = None
            else:
                f = SD(str(p), SDC.READ)
                self.cache[(h, v)] = (f.select("LC_Type1")[:], f.select("QC")[:])
                f.end()
        return self.cache[(h, v)]

    def window(self, gi0: int, gi1: int, gj0: int, gj1: int):
        lc = np.full((gi1 - gi0, gj1 - gj0), 255, np.uint8)
        qc = np.full_like(lc, 255)
        for v in range(gi0 // 2400, (gi1 - 1) // 2400 + 1):
            for h in range(gj0 // 2400, (gj1 - 1) // 2400 + 1):
                t = self.tile(h, v)
                if t is None:
                    continue
                a0, a1 = max(gi0, v * 2400), min(gi1, (v + 1) * 2400)
                b0, b1 = max(gj0, h * 2400), min(gj1, (h + 1) * 2400)
                lc[a0 - gi0:a1 - gi0, b0 - gj0:b1 - gj0] = t[0][a0 - v * 2400:a1 - v * 2400, b0 - h * 2400:b1 - h * 2400]
                qc[a0 - gi0:a1 - gi0, b0 - gj0:b1 - gj0] = t[1][a0 - v * 2400:a1 - v * 2400, b0 - h * 2400:b1 - h * 2400]
        return lc, qc


def latlon_to_gij(lat, lon):
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    y = np.radians(lat) * C.R_SIN
    x = np.radians(lon) * C.R_SIN * np.cos(np.radians(lat))
    return np.floor((Y0 - y) / C.PIX_M).astype(np.int64), np.floor((x - X0) / C.PIX_M).astype(np.int64)


def gij_to_latlon(gi, gj):
    y = Y0 - (np.asarray(gi) + 0.5) * C.PIX_M
    x = X0 + (np.asarray(gj) + 0.5) * C.PIX_M
    lat = np.degrees(y / C.R_SIN)
    lon = np.degrees(x / (C.R_SIN * np.maximum(np.cos(np.radians(lat)), 1e-9)))
    lon = np.where(np.abs(lon) > 180, np.nan, lon)   # outside the sinusoidal globe
    return lat, lon


def bin_rc(lat, lon):
    """0.05 deg pixel of a point, exactly as landcover_fractions.local_counts()."""
    r = np.clip(((90.0 - lat) / C.RES).astype(np.int64), 0, C.H - 1)
    c = (np.floor(((lon + 180.0) % 360.0) / C.RES).astype(np.int64)) % C.W
    return r, c


def site_rc(lat: float, lon: float) -> tuple[int, int]:
    """global_mask.site_report() indexing."""
    return min(int((90.0 - lat) / C.RES), C.H - 1), min(int((lon + 180.0) / C.RES), C.W - 1)


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 2 * C.R_KM * np.arcsin(np.sqrt(a))


def region_pixels(s: dict) -> list[tuple[int, int]]:
    r0, c0 = site_rc(s["lat"], s["lon"])
    if "box" in s:
        w, so, e, n = s["box"]
        rows = range(int((90 - n) / C.RES) - 1, int((90 - so) / C.RES) + 2)
        cols = range(int((w + 180) / C.RES) - 1, int((e + 180) / C.RES) + 2)
        px = [(r, c) for r in rows for c in cols
              if so <= 90 - (r + 0.5) * C.RES <= n and w <= -180 + (c + 0.5) * C.RES <= e]
    else:
        rad = s.get("radius_km", VS.R_DEFAULT_KM)
        dr = math.ceil(rad / 111.2 / C.RES) + 1
        dc = math.ceil(rad / (111.2 * max(math.cos(math.radians(s["lat"])), 0.05)) / C.RES) + 1
        px = []
        for r in range(r0 - dr, r0 + dr + 1):
            for c in range(c0 - dc, c0 + dc + 1):
                if 0 <= r < C.H:
                    cc = c % C.W
                    lat, lon = 90 - (r + 0.5) * C.RES, -180 + (cc + 0.5) * C.RES
                    if haversine_km(s["lat"], s["lon"], lat, lon) <= rad:
                        px.append((r, cc))
    if (r0, c0) not in px:
        px.append((r0, c0))
    return sorted(set(px))


# --- the v2 rule ----------------------------------------------------------------------------------

def shares_from_counts(cnt: np.ndarray) -> dict:
    """cnt: (17,) class counts (MCD12C1 numbering). float32 shares as landcover_fractions + v2."""
    tot = np.float32(max(int(cnt.sum()), 1))
    has = int(cnt.sum()) > 0
    f = lambda ks: np.float32(sum(int(cnt[k]) for k in ks)) / tot if has else np.float32(0.0)  # noqa: E731
    return {"water": f([WATER]), "built": f([BUILT]), "veg": f(VEG_CLASSES), "other": f(OTHER_CLASSES),
            "has_lc": has}


def v2_flags(sh: dict, land: bool, density: float) -> int:
    water, built, veg = sh["water"], sh["built"], sh["veg"]
    flags = 0
    if (not land) or water >= WATER_MAX:
        flags |= OCEAN
    if density >= POP_MAX or built >= BUILT_MAX:
        flags |= POPULATED
    if veg >= VEG_MAX:
        flags |= VEGETATED
    if flags == 0 and (water + built + veg) >= NON_ANALOG_MAX:      # mixed rule -> biggest group
        flags |= (OCEAN, POPULATED, VEGETATED)[int(np.argmax([water, built, veg]))]
    return flags


POLICIES = {  # audit policy ids (scripts/04): analog classes, MCD12C1 numbering
    "P1": (7, 9, 10, 15, 16), "P3": (7, 15, 16), "P4": (7, 16), "P6": (16,)}


def policy_kept(cnt: np.ndarray, land: bool, density: float, analog) -> bool:
    """v2 rule structure with a different analog class list (non-analog land replaces 'veg')."""
    tot = int(cnt.sum())
    if tot == 0:
        return v2_flags({"water": 0, "built": 0, "veg": 0}, land, density) == 0
    den = np.float32(tot)
    na = [k for k in range(17) if k not in analog and k not in (WATER, BUILT)]
    sh = {"water": np.float32(int(cnt[WATER])) / den, "built": np.float32(int(cnt[BUILT])) / den,
          "veg": np.float32(sum(int(cnt[k]) for k in na)) / den}
    return v2_flags(sh, land, density) == 0


def reason(flags: int) -> str:
    if flags == 0:
        return "kept"
    return "+".join(n for b, n in ((OCEAN, "water"), (POPULATED, "populated"), (VEGETATED, "vegetated")) if flags & b)


def esri_flip(sh: dict, flags: int, land: bool, density: float) -> str:
    """Esri share that would flip the decision under the equal-weight MODIS/Esri mean of v2.

    Removal by land cover is equivalent to mean(water+built+veg) >= 0.5 or mean(built) >= 0.25,
    so with MODIS share m the Esri share must reach 1 - m (or 0.5 - m_built for built-up)."""
    m = float(sh["water"] + sh["built"] + sh["veg"])
    b = float(sh["built"])
    if not land or density >= POP_MAX:
        return "cannot flip (removed by Natural Earth or GHSL)"
    if flags == 0:
        return f"removed if Esri non-analog >= {max(0.0, 1 - m):.2f} or Esri built >= {max(0.0, 2 * BUILT_MAX - b):.2f}"
    return f"kept only if Esri non-analog < {max(0.0, 1 - m):.2f} and Esri built < {max(0.0, 2 * BUILT_MAX - b):.2f}"


# --- GHSL density on selected 0.05 deg pixels -----------------------------------------------------

def ghsl_density(data: Path, pixels: list[tuple[int, int]], area: np.ndarray) -> dict:
    path = next((data / "ghsl-population" / "extracted").glob("GHS_POP_E2020_GLOBE_R2023A_4326_30ss*.tif"))
    rs, cs = [p[0] for p in pixels], [p[1] for p in pixels]
    n, s = 90 - min(rs) * C.RES, 90 - (max(rs) + 1) * C.RES
    w, e = -180 + min(cs) * C.RES, -180 + (max(cs) + 1) * C.RES
    want = set(pixels)
    people = {p: 0.0 for p in pixels}
    with rasterio.open(path) as src:
        t = src.transform
        win = from_bounds(w - 2 * t.a, s + 2 * t.e, e + 2 * t.a, n - 2 * t.e, t).round_offsets().round_lengths()
        win = win.intersection(Window(0, 0, src.width, src.height))
        a = src.read(1, window=win).astype("float64")
        if src.nodata is not None:
            a[a == src.nodata] = 0.0
        a[~(a > 0)] = 0.0
        lon = t.c + (win.col_off + np.arange(win.width) + 0.5) * t.a
        lat = t.f + (win.row_off + np.arange(win.height) + 0.5) * t.e
    rows = np.clip(np.floor((90.0 - lat) / C.RES).astype(np.int64), 0, C.H - 1)
    cols = np.floor(((lon + 180.0) % 360.0) / C.RES).astype(np.int64) % C.W
    for i, r in enumerate(rows):
        for c in np.unique(cols):
            if (r, c) in want:
                people[(r, c)] += float(a[i, cols == c].sum())
    return {p: people[p] / float(area[p[0], 0]) for p in pixels}


# --- 8-connected components (small windows) -------------------------------------------------------

def components(mask: np.ndarray) -> list[list[tuple[int, int]]]:
    seen = np.zeros_like(mask, bool)
    out = []
    H, W = mask.shape
    for i, j in zip(*np.nonzero(mask)):
        if seen[i, j]:
            continue
        comp, q = [], deque([(i, j)])
        seen[i, j] = True
        while q:
            a, b = q.popleft()
            comp.append((a, b))
            for da in (-1, 0, 1):
                for db in (-1, 0, 1):
                    x, y = a + da, b + db
                    if 0 <= x < H and 0 <= y < W and mask[x, y] and not seen[x, y]:
                        seen[x, y] = True
                        q.append((x, y))
        out.append(comp)
    return out


def comp_str(cnt: np.ndarray, top: int = 4) -> str:
    tot = cnt.sum()
    if tot == 0:
        return "no data"
    order = np.argsort(-cnt)[:top]
    return "; ".join(f"{C.IGBP[k]} {100 * cnt[k] / tot:.0f}%" for k in order if cnt[k] > 0)


def main() -> None:
    a = C.args(__doc__)
    area = C.pixel_area_km2()
    land = C.ne_land_mask(a.data)
    q1 = np.load(C.WORK / "mcd12q1_counts_0p05.npy", mmap_mode="r")
    c1f = SD(str(C.mcd12c1_path(a.data)), SDC.READ)
    c1 = c1f.select("Land_Cover_Type_1_Percent")
    viirs = sorted((a.data / "viirs-2023").glob("VNP13C2.A2023*.h5"))
    assert len(viirs) == 12, len(viirs)
    reader = Q1Reader(a.data)

    rows, detail, windows = [], {}, {}
    for s in VS.SITES:
        r0, c0 = site_rc(s["lat"], s["lon"])
        px = region_pixels(s)
        dens = ghsl_density(a.data, px, area)
        info = {}
        for (r, c) in px:
            cnt = np.asarray(q1[:, r, c], np.int64)
            sh = shares_from_counts(cnt)
            fl = v2_flags(sh, bool(land[r, c]), dens[(r, c)])
            info[(r, c)] = dict(cnt=cnt, sh=sh, flags=fl, area=float(area[r, 0]))
        site = info[(r0, c0)]
        reg_area = sum(v["area"] for v in info.values())
        kept_area = sum(v["area"] for v in info.values() if v["flags"] == 0)

        # MCD12C1 cross-check on the site pixel
        pct = np.asarray(c1[r0:r0 + 1, c0:c0 + 1, :][0, 0], np.int64)
        c1_sh = shares_from_counts(np.where(pct == 255, 0, pct))
        c1_flags = v2_flags(c1_sh, bool(land[r0, c0]), dens[(r0, c0)])

        # VIIRS peak NDVI and valid months on the site pixel, and peak NDVI on every region pixel
        rmin, rmax = min(p[0] for p in px), max(p[0] for p in px)
        cmin, cmax = min(p[1] for p in px), max(p[1] for p in px)
        stack = []
        for p in viirs:
            with rasterio.open(f'HDF5:"{p}":{NDVI_DATASET}') as src:
                stack.append(src.read(1, window=Window(cmin, rmin, cmax - cmin + 1, rmax - rmin + 1)).astype(np.int32))
        stack = np.stack(stack)
        vals = [int(v) for v in stack[:, r0 - rmin, c0 - cmin]]
        valid = [v for v in vals if v > -10000]
        peak = max(valid) * 1e-4 if valid else None
        reg_peak = np.where(stack > -10000, stack, -10 ** 6).max(axis=0) * 1e-4   # < -1 means no valid month

        # site pixel and region kept area under the audit's stricter class lists and an NDVI gate
        pol = {}
        for pid, analog in POLICIES.items():
            k = {rc: policy_kept(v["cnt"], bool(land[rc]), dens[rc], analog) for rc, v in info.items()}
            pol[pid] = k
        pk = {rc: pol["P1"][rc] and not (reg_peak[rc[0] - rmin, rc[1] - cmin] >= 0.5) for rc in info}
        pol["P1+NDVI<0.5"] = pk

        # 500 m pixels of the region
        corners = [(90 - (r + dr) * C.RES, -180 + (c + dc) * C.RES) for r, c in px for dr in (0, 1) for dc in (0, 1)]
        gi, gj = latlon_to_gij([p[0] for p in corners], [p[1] for p in corners])
        gi0, gi1, gj0, gj1 = int(gi.min()) - 2, int(gi.max()) + 3, int(gj.min()) - 2, int(gj.max()) + 3
        lc, qc = reader.window(gi0, gi1, gj0, gj1)
        GI, GJ = np.meshgrid(np.arange(gi0, gi1), np.arange(gj0, gj1), indexing="ij")
        plat, plon = gij_to_latlon(GI, GJ)
        ok = np.isfinite(plon)
        pr, pc = bin_rc(np.where(ok, plat, 0), np.where(ok, plon, 0))
        key = pr * C.W + pc
        reg_keys = np.array([r * C.W + c for r, c in px])
        in_reg = ok & np.isin(key, reg_keys)
        in_site = ok & (key == r0 * C.W + c0)
        removed_keys = np.array([r * C.W + c for (r, c), v in info.items() if v["flags"] != 0] or [-1])
        in_removed = in_reg & np.isin(key, removed_keys)
        cls = Q1_TO_C1[lc]

        def q1_comp(m):
            return np.bincount(cls[m & (cls >= 0)], minlength=17)

        def qc_counts(m):
            b = np.bincount(qc[m].astype(np.int64), minlength=256)
            return {str(k): int(b[k]) for k in list(range(11)) + [255] if b[k]}

        barren = in_reg & (lc == 16)
        comps = components(barren)
        largest = max((len(cp) for cp in comps), default=0)
        largest_removed = 0
        for cp in comps:
            ii, jj = zip(*cp)
            largest_removed = max(largest_removed, int(in_removed[list(ii), list(jj)].sum()))
        sgi, sgj = latlon_to_gij(s["lat"], s["lon"])
        slc, sqc = lc[int(sgi) - gi0, int(sgj) - gj0], qc[int(sgi) - gi0, int(sgj) - gj0]

        reg_comp = q1_comp(in_reg)
        site_comp = q1_comp(in_site)
        n_site = int(in_site.sum())
        qcs = qc_counts(in_site)
        qcr = qc_counts(in_reg)
        n_reg = int(in_reg.sum())

        rows.append({
            "id": s["id"], "group": s["group"], "profiles": " ".join(s["profiles"]), "lat": s["lat"], "lon": s["lon"],
            "pixel_rc": f"{r0},{c0}", "pixel_km2": round(site["area"], 2),
            "ne_land": bool(land[r0, c0]), "pop_per_km2": round(dens[(r0, c0)], 1),
            "modis_water": round(float(site["sh"]["water"]), 3), "modis_built": round(float(site["sh"]["built"]), 3),
            "modis_nonanalog_veg": round(float(site["sh"]["veg"]), 3), "modis_analog_other": round(float(site["sh"]["other"]), 3),
            "modis_barren": round(int(site["cnt"][BARREN]) / max(int(site["cnt"].sum()), 1), 3),
            "modis_snow_ice": round(int(site["cnt"][SNOW]) / max(int(site["cnt"].sum()), 1), 3),
            "modis_classes": comp_str(site["cnt"]),
            "v2_modis_decision": reason(site["flags"]),
            "esri_flip": esri_flip(site["sh"], site["flags"], bool(land[r0, c0]), dens[(r0, c0)]),
            "c1_decision": reason(c1_flags), "c1_classes": comp_str(np.where(pct == 255, 0, pct)),
            "region_pixels": len(px), "region_km2": round(reg_area, 1),
            "region_kept_km2": round(kept_area, 1), "region_kept_pct": round(100 * kept_area / reg_area, 1),
            "q1_500m_valid_in_pixel": int(site["cnt"].sum()), "q1_500m_expected_in_pixel": round(site["area"] / C.PIX_KM2),
            "q1_qc_in_pixel": json.dumps(qcs), "q1_qc1_pct_region": round(100 * int(((qc == 1) & in_reg).sum()) / max(n_reg, 1), 2),
            "q1_qc6_pct_region": round(100 * int(((qc == 6) & in_reg).sum()) / max(n_reg, 1), 2),
            "q1_qc7_pct_region": round(100 * int(((qc == 7) & in_reg).sum()) / max(n_reg, 1), 2),
            "site_500m_class": C.IGBP.get(int(Q1_TO_C1[slc]), "fill") if slc != 255 else "fill",
            "site_500m_qc": f"{int(sqc)} ({QC_NAMES.get(int(sqc), '?')})",
            "region_500m_classes": comp_str(reg_comp, 5),
            "region_barren_km2": round(int(barren.sum()) * C.PIX_KM2, 1),
            "region_barren_in_removed_km2": round(int((barren & in_removed).sum()) * C.PIX_KM2, 1),
            "largest_barren_patch_km2": round(largest * C.PIX_KM2, 1),
            "largest_barren_patch_in_removed_km2": round(largest_removed * C.PIX_KM2, 1),
            "viirs_valid_months": len(valid), "viirs_peak_ndvi": None if peak is None else round(peak, 3),
            "esri": "not available locally",
            **{f"site_kept_{pid}": bool(k[(r0, c0)]) for pid, k in pol.items()},
            **{f"region_kept_pct_{pid}": round(100 * sum(info[rc]["area"] for rc, ok in k.items() if ok) / reg_area, 1)
               for pid, k in pol.items()},
        })
        detail[s["id"]] = {
            "site": {k: v for k, v in s.items()},
            "pixels": [{"rc": [r, c], "km2": round(v["area"], 2), "decision": reason(v["flags"]),
                        "pop_per_km2": round(dens[(r, c)], 1), "classes": comp_str(v["cnt"], 6),
                        "shares": {k: round(float(v["sh"][k]), 3) for k in ("water", "built", "veg", "other")}}
                       for (r, c), v in sorted(info.items())],
            "site_pixel_500m_composition": {C.IGBP[k]: int(site_comp[k]) for k in range(17) if site_comp[k]},
            "site_pixel_500m_n": n_site,
            "region_500m_composition_km2": {C.IGBP[k]: round(int(reg_comp[k]) * C.PIX_KM2, 1) for k in range(17) if reg_comp[k]},
            "region_qc_counts": qcr, "site_pixel_qc_counts": qcs,
            "region_barren_patches": sorted((len(cp) for cp in comps), reverse=True)[:10],
            "viirs_monthly_raw": vals,
        }
        # kept-flag window for the r7 check (pixels outside the region are recomputed here too)
        rr, cc = [p[0] for p in px], [p[1] for p in px]
        wr0, wr1, wc0, wc1 = min(rr) - 2, max(rr) + 3, min(cc) - 2, max(cc) + 3
        wpx = [(r, c % C.W) for r in range(wr0, wr1) for c in range(wc0, wc1)]
        wd = ghsl_density(a.data, wpx, area)
        kw = np.zeros((wr1 - wr0, wc1 - wc0), np.uint8)
        for (r, c) in wpx:
            sh = shares_from_counts(np.asarray(q1[:, r, c], np.int64))
            kw[r - wr0, c - wc0 if c >= wc0 else c + C.W - wc0] = 1 if v2_flags(sh, bool(land[r, c]), wd[(r, c)]) == 0 else 0
        windows[f"{s['id']}__r0c0"] = np.array([wr0, wc0])
        windows[f"{s['id']}__kept"] = kw
        print(f"{s['id']:24s} {reason(site['flags']):22s} C1 {reason(c1_flags):12s} region kept "
              f"{rows[-1]['region_kept_pct']:5.1f}%  | {rows[-1]['modis_classes']}", flush=True)
    c1f.end()
    C.write_csv(C.RESULTS / "site_validation.csv", rows)
    (C.RESULTS / "site_validation_detail.json").write_text(json.dumps(detail, indent=1, default=str), encoding="utf-8")
    np.savez(C.WORK / "site_kept_windows.npz", **windows)


if __name__ == "__main__":
    main()
