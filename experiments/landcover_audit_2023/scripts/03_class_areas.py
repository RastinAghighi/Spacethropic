"""Task 2b: area of every IGBP class on Earth from MCD12C1 2023, cross-checked with MCD12Q1.

Area weighting: each 0.05 deg pixel has its exact area on the authalic sphere (it shrinks with
cos(latitude)); class area = sum over pixels of pixel_area x class_percent / pixel_percent_sum.
Dividing by the per-pixel sum (normally 100) keeps the total equal to the Earth's area even
where the integer percentages are rounded to 99 or 101.

Interpretation checks (MCD12C1 percent layer k must be IGBP class k, with 0 = water, not 17):
  - argmax of the 17 percentages vs Majority_Land_Cover_Type_1 (should agree when no tie)
  - reference points with a known class (Sahara, Amazon, Antarctica, open ocean, ...)
  - per-pixel percentage sums

Streams MCD12C1 in slabs of 200 rows (~25 MB); only the Natural Earth mask (26 MB) is global.

Outputs: results/global_landcover_class_area.csv (one row per original class + no data + totals)
         results/global_landcover_broad_area.csv (the requested categories)
         work/mcd12c1_checks.json
Usage:   .venv/Scripts/python.exe -I scripts/03_class_areas.py [--data DIR]   (after 02)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

import numpy as np  # noqa: E402
from pyhdf.SD import SD, SDC  # noqa: E402

NCLS, SLAB = 17, 200
REF_POINTS = [  # (name, lat, lon, expected MCD12C1 class)
    ("Pacific Ocean", 0.0, -150.0, 0), ("Sahara (Algeria)", 25.0, 5.0, 16), ("Rub al Khali", 20.0, 50.0, 16),
    ("Central Amazon", -3.0, -62.0, 2), ("East Antarctica", -80.0, 60.0, 15), ("Greenland ice sheet", 72.0, -40.0, 15),
    ("Siberian taiga", 62.0, 100.0, 3), ("US Corn Belt (Iowa)", 42.0, -93.5, 12),
]
BROAD_ORDER = [  # requested categories -> classes (MCD12C1 numbering)
    ("Barren", [16]), ("Grassland", [10]), ("Open shrubland", [7]), ("Savanna (woody savannas + savannas)", [8, 9]),
    ("Forest", [1, 2, 3, 4, 5]), ("Cropland (croplands + cropland/natural mosaics)", [12, 14]), ("Urban", [13]),
    ("Water", [0]), ("Snow or ice", [15]), ("Other classified (closed shrublands + permanent wetlands)", [6, 11]),
]


def main() -> None:
    a = C.args(__doc__)
    area = C.pixel_area_km2()
    land = C.ne_land_mask(a.data)
    earth_km2 = float(area.sum() * C.W)

    c1 = {k: np.zeros(NCLS) for k in ("frac", "frac_raw", "ne_land", "ne_ocean", "south60", "majority")}
    nodata = {"all": 0.0, "ne_land": 0.0}
    sum_hist = np.zeros(17 * 100 + 1, np.int64)
    agree = disagree = ties = 0

    f = SD(str(C.mcd12c1_path(a.data)), SDC.READ)
    pct_sds, maj_sds = f.select("Land_Cover_Type_1_Percent"), f.select("Majority_Land_Cover_Type_1")
    ref = []
    for r0 in range(0, C.H, SLAB):
        r1 = min(C.H, r0 + SLAB)
        pct = pct_sds[r0:r1]                     # (h, W, 17) uint8
        maj = maj_sds[r0:r1]
        ar = area[r0:r1]                         # (h, 1) km2
        ln = land[r0:r1]
        s = pct.sum(axis=2, dtype=np.uint16)
        has_fill = (pct == 255).any(axis=2)      # validation found none; guarded anyway
        sum_hist += np.bincount(np.minimum(s.ravel(), sum_hist.size - 1), minlength=sum_hist.size)
        valid = (s > 0) & ~has_fill
        inv = np.where(valid, 1.0 / np.maximum(s, 1), 0.0).astype(np.float32)
        nodata["all"] += C.area_sum(~valid, ar)
        nodata["ne_land"] += C.area_sum(~valid & ln, ar)
        south = r0 >= C.SOUTH_60_ROW         # slabs are 200 rows, 60 S is row 3000: slab-aligned
        for k in range(NCLS):
            pk = pct[:, :, k]
            share = pk * inv                     # float32 (h, W), 0..1
            c1["frac"][k] += C.area_sum(share, ar)
            c1["frac_raw"][k] += C.area_sum(pk.astype(np.float32) / 100.0, ar)
            c1["ne_land"][k] += C.area_sum(np.where(ln, share, 0), ar)
            c1["ne_ocean"][k] += C.area_sum(np.where(ln, 0, share), ar)
            if south:
                c1["south60"][k] += C.area_sum(share, ar)
            c1["majority"][k] += C.area_sum((maj == k) & valid, ar)
        top = pct.max(axis=2)
        n_top = (pct == top[:, :, None]).sum(axis=2)
        am = pct.argmax(axis=2)
        clear = valid & (n_top == 1)
        agree += int((clear & (am == maj)).sum())
        disagree += int((clear & (am != maj)).sum())
        ties += int((valid & (n_top > 1)).sum())
        for name, lat, lon, exp in REF_POINTS:
            r, c = int((90 - lat) / C.RES), int((lon + 180) / C.RES)
            if r0 <= r < r1:
                p = pct[r - r0, c]
                ref.append({"point": name, "lat": lat, "lon": lon, "expected": exp, "expected_name": C.IGBP[exp],
                            "majority": int(maj[r - r0, c]), "argmax_percent": int(p.argmax()),
                            "percent_of_expected": int(p[exp]), "ok": int(maj[r - r0, c]) == exp == int(p.argmax())})
        del pct, maj, s, valid, inv
    f.end()

    q1 = json.loads((C.WORK / "mcd12q1_class_totals.json").read_text())
    q1_area = {int(k): v for k, v in q1["class_area_km2_c1_index"].items()}
    q1_s60 = {int(k): v for k, v in q1["class_area_south_of_60S_km2_c1_index"].items()}
    land_km2 = C.area_sum(land, area)
    modis_land = float(c1["frac"][1:].sum())               # every class except water
    q1_land = float(sum(v for k, v in q1_area.items() if k != 0))

    rows = []
    for k in range(NCLS):
        grp = C.TEAM_GROUP[k]
        rows.append({
            "mcd12c1_class": k, "mcd12q1_value": 17 if k == 0 else k, "class_name": C.IGBP[k], "broad_category": C.BROAD[k],
            "global_filter_v2_group": grp,
            "global_filter_v2_treatment": "kept as analog" if grp == "other" else "counts toward removal",
            "area_km2": round(c1["frac"][k]), "pct_of_earth": round(100 * c1["frac"][k] / earth_km2, 3),
            "pct_of_modis_land": "" if k == 0 else round(100 * c1["frac"][k] / modis_land, 3),
            "area_on_ne_land_km2": round(c1["ne_land"][k]), "pct_of_ne_land": round(100 * c1["ne_land"][k] / land_km2, 3),
            "area_south_of_60S_km2": round(c1["south60"][k]),
            "majority_pixel_area_km2": round(c1["majority"][k]),
            "area_km2_unnormalised_pct_div_100": round(c1["frac_raw"][k]),
            "mcd12q1_area_km2": round(q1_area[k]),
            "mcd12q1_area_south_of_60S_km2": round(q1_s60[k]),
            "mcd12q1_vs_mcd12c1_pct_diff": "" if k == 0 else round(100 * (q1_area[k] - c1["frac"][k]) / c1["frac"][k], 2),
        })
    blank = {key: "" for key in rows[0]}
    rows.append({**blank, "mcd12c1_class": "nodata", "class_name": "Unclassified / no data", "broad_category": "unclassified",
                 "area_km2": round(nodata["all"]), "pct_of_earth": round(100 * nodata["all"] / earth_km2, 3),
                 "area_on_ne_land_km2": round(nodata["ne_land"]), "pct_of_ne_land": round(100 * nodata["ne_land"] / land_km2, 3),
                 "mcd12q1_area_km2": round(q1["fill_area_inside_globe_km2"])})
    rows.append({**blank, "mcd12c1_class": "total_land", "class_name": "All land classes (1-16)",
                 "area_km2": round(modis_land), "pct_of_earth": round(100 * modis_land / earth_km2, 3),
                 "area_on_ne_land_km2": round(float(c1["ne_land"][1:].sum())), "mcd12q1_area_km2": round(q1_land),
                 "mcd12q1_vs_mcd12c1_pct_diff": round(100 * (q1_land - modis_land) / modis_land, 2)})
    rows.append({**blank, "mcd12c1_class": "earth", "class_name": "Whole Earth (authalic sphere)",
                 "area_km2": round(earth_km2), "pct_of_earth": 100.0, "area_on_ne_land_km2": round(land_km2),
                 "mcd12q1_area_km2": round(q1["covered_area_km2"])})
    C.write_csv(C.RESULTS / "global_landcover_class_area.csv", rows)

    broad, covered = [], set()
    for name, ks in BROAD_ORDER:
        covered |= set(ks)
        km2 = float(sum(c1["frac"][k] for k in ks))
        nl = float(sum(c1["ne_land"][k] for k in ks))
        broad.append({"category": name, "mcd12c1_classes": " ".join(map(str, ks)), "area_km2": round(km2),
                      "pct_of_earth": round(100 * km2 / earth_km2, 3),
                      "pct_of_modis_land": "" if ks == [0] else round(100 * km2 / modis_land, 3),
                      "area_on_ne_land_km2": round(nl), "pct_of_ne_land": round(100 * nl / land_km2, 3),
                      "area_south_of_60S_km2": round(float(sum(c1["south60"][k] for k in ks))),
                      "mcd12q1_area_km2": round(sum(q1_area[k] for k in ks))})
    assert covered == set(range(NCLS))
    broad.append({"category": "Unclassified / no data", "mcd12c1_classes": "", "area_km2": round(nodata["all"]),
                  "pct_of_earth": round(100 * nodata["all"] / earth_km2, 3), "pct_of_modis_land": "",
                  "area_on_ne_land_km2": round(nodata["ne_land"]), "pct_of_ne_land": round(100 * nodata["ne_land"] / land_km2, 3),
                  "area_south_of_60S_km2": "", "mcd12q1_area_km2": round(q1["fill_area_inside_globe_km2"])})
    C.write_csv(C.RESULTS / "global_landcover_broad_area.csv", broad)

    nz = np.nonzero(sum_hist)[0]
    checks = {
        "earth_km2": earth_km2, "ne_land_km2": land_km2, "modis_land_km2": modis_land,
        "sum_of_class_areas_plus_nodata_km2": float(c1["frac"].sum() + nodata["all"]),
        "percent_sum_histogram": {str(int(k)): int(sum_hist[k]) for k in nz},
        "argmax_vs_majority": {"agree": agree, "disagree": disagree, "ties_skipped": ties,
                               "agree_pct": 100 * agree / max(agree + disagree, 1)},
        "reference_points": ref,
        "nodata_km2": nodata,
    }
    (C.WORK / "mcd12c1_checks.json").write_text(json.dumps(checks, indent=1))
    print(json.dumps({k: checks[k] for k in ("earth_km2", "ne_land_km2", "modis_land_km2",
                                             "sum_of_class_areas_plus_nodata_km2", "percent_sum_histogram",
                                             "argmax_vs_majority", "nodata_km2")}, indent=1))
    for r in ref:
        print(r)
    for b in broad:
        print(f"{b['category'][:40]:40s} {b['area_km2']:>14,} km2  {b['pct_of_earth']:7.3f}% Earth  {b['pct_of_ne_land']:7.3f}% NE land")


if __name__ == "__main__":
    main()
