"""Task 2c: land retained under the current v2 land-cover rule and stricter vegetation policies.

Every policy uses the structure of pipeline/analysis/global_mask_v2.py (teammate, commit 475bf4e),
with only the land-cover inputs (no GHSL population, no Esri, no Dynamic World). A 0.05 deg
pixel is REMOVED if any of:
    outside Natural Earth 1:10m land (pixel centre)        - same as v2
    water share >= 0.5                                     - same as v2
    built share >= 0.25                                    - same as v2
    non-analog land share >= veg_max                       - v2: veg >= 0.5
    water + built + non-analog land share >= mixed_max     - v2: mixed rule, 0.5
where "non-analog land" = every land class not in the policy's analog set. The v2 analog set is
{open shrublands, savannas, grasslands, snow/ice, barren}; the stricter policies shrink it or
tighten the thresholds. As in v2, a land pixel with no land-cover data has all shares 0 and is
therefore KEPT; that area is reported separately (nodata_land_kept_km2).

Kept pixels count with their whole area, as in the filter. The fractional area of analog
classes is also given, to show how much non-analog cover rides along inside kept pixels.

Two land-cover sources:
  mcd12q1 - the 500 m tiles binned to 0.05 deg exactly like landcover_fractions.py (the MODIS
            input the teammate used; from script 02)
  mcd12c1 - NASA's own 0.05 deg aggregate (independent check)

Streams 100-row slabs (one slab of each source in memory at a time).
Outputs: results/filter_policy_comparison.csv, results/filter_policy_kept_composition.csv
Usage:   .venv/Scripts/python.exe -I scripts/04_policy_scenarios.py [--data DIR]   (after 02)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

import numpy as np  # noqa: E402
from pyhdf.SD import SD, SDC  # noqa: E402

NCLS, SLAB = 17, 100
V2_ANALOG = (7, 9, 10, 15, 16)
POLICIES = [  # id, label, analog classes, veg_max, mixed_max
    ("P1", "Current v2 rule (analog = open shrubland, savanna, grassland, snow/ice, barren)", V2_ANALOG, 0.5, 0.5),
    ("P1b", "Current classes, stricter vegetation threshold (non-analog >= 0.25 removes)", V2_ANALOG, 0.25, 0.5),
    ("P1c", "Current classes, pixel must be >= 90% analog", V2_ANALOG, 0.5, 0.1),
    ("P2", "Drop savanna (analog = open shrubland, grassland, snow/ice, barren)", (7, 10, 15, 16), 0.5, 0.5),
    ("P3", "Drop savanna + grassland (analog = open shrubland, snow/ice, barren)", (7, 15, 16), 0.5, 0.5),
    ("P4", "Barren + sparse vegetation (analog = barren, open shrubland)", (7, 16), 0.5, 0.5),
    ("P5", "Non-vegetated only (analog = barren, snow/ice)", (15, 16), 0.5, 0.5),
    ("P6", "Barren only", (16,), 0.5, 0.5),
]
WATER, BUILT = 0, 13
REPORTED_V2_KEPT_KM2 = 85.8e6  # pipeline/README.md, global mask v2 (MODIS + Esri mean, GHSL, NE)


def counts_c1(pct: np.ndarray):
    """MCD12C1 integer percents as per-class counts (17, h, W) and their per-pixel total."""
    return np.moveaxis(pct, 2, 0), pct.sum(axis=2, dtype=np.int32)


def counts_q1(counts: np.ndarray):
    """MCD12Q1 500 m pixel counts per class (17, h, W) and the valid-pixel total."""
    return counts, counts.sum(axis=0, dtype=np.int32)


def share(c: np.ndarray, total: np.ndarray) -> np.ndarray:
    """float32 count / total, 0 where there is no data: the same float32 division as
    landcover_fractions.Accumulator.save() followed by global_mask_v2's nan_to_num(0)."""
    out = c.astype(np.float32) / np.maximum(total, 1).astype(np.float32)
    out[total == 0] = 0.0
    return out


def main() -> None:
    a = C.args(__doc__)
    area = C.pixel_area_km2()
    land = C.ne_land_mask(a.data)
    q1 = np.load(C.WORK / "mcd12q1_counts_0p05.npy", mmap_mode="r")
    f = SD(str(C.mcd12c1_path(a.data)), SDC.READ)
    pct_sds = f.select("Land_Cover_Type_1_Percent")

    srcs = ("mcd12q1", "mcd12c1")
    acc = {(p[0], s): {"kept": 0.0, "kept_s60": 0.0, "nodata_kept": 0.0, "analog_frac_land": 0.0,
                       "analog_frac_land_s60": 0.0, "analog_in_kept": 0.0, "comp": np.zeros(NCLS)}
           for p in POLICIES for s in srcs}
    cov = {s: {"nodata_on_ne_land": 0.0, "nodata_on_ne_land_s60": 0.0, "lc_land_outside_ne": 0.0} for s in srcs}

    for r0 in range(0, C.H, SLAB):
        r1 = min(C.H, r0 + SLAB)
        ar, ln = area[r0:r1], land[r0:r1]
        south = r0 >= C.SOUTH_60_ROW
        for src in srcs:
            if src == "mcd12c1":
                cnt, total = counts_c1(pct_sds[r0:r1])
            else:
                cnt, total = counts_q1(np.asarray(q1[:, r0:r1, :]))
            valid = total > 0
            c_w, c_b = cnt[WATER].astype(np.int32), cnt[BUILT].astype(np.int32)
            water, built = share(c_w, total), share(c_b, total)
            cov[src]["nodata_on_ne_land"] += C.area_sum(ln & ~valid, ar)
            if south:
                cov[src]["nodata_on_ne_land_s60"] += C.area_sum(ln & ~valid, ar)
            cov[src]["lc_land_outside_ne"] += C.area_sum(np.where(ln, 0.0, 1.0 - water) * valid, ar)
            cls_share = [share(cnt[k], total) for k in range(NCLS)]   # for the composition table
            for pid, _, analog, veg_max, mixed_max in POLICIES:
                c_al = cnt[list(analog)].sum(axis=0, dtype=np.int32)
                c_na = total - c_w - c_b - c_al                       # exact integer count
                al, non_analog = share(c_al, total), share(c_na, total)
                removed = ~ln | (water >= 0.5) | (built >= 0.25) | (non_analog >= veg_max)                     | ((water + built + non_analog) >= mixed_max)     # same float32 order as v2
                kept = ~removed
                d = acc[(pid, src)]
                k_km2 = C.area_sum(kept, ar)
                d["kept"] += k_km2
                d["nodata_kept"] += C.area_sum(kept & ~valid, ar)
                d["analog_frac_land"] += C.area_sum(np.where(ln, al, 0.0), ar)
                d["analog_in_kept"] += C.area_sum(np.where(kept, al, 0.0), ar)
                if south:
                    d["kept_s60"] += k_km2
                    d["analog_frac_land_s60"] += C.area_sum(np.where(ln, al, 0.0), ar)
                for k in range(NCLS):
                    d["comp"][k] += C.area_sum(np.where(kept, cls_share[k], 0.0), ar)
            del cnt, total, valid, cls_share
        if r0 % 600 == 0:
            print(f"rows {r0}-{r1}", flush=True)
    f.end()

    land_km2 = C.area_sum(land, area)
    land_s60 = C.area_sum(land & C.south_mask(), area)
    land_n60 = land_km2 - land_s60
    rows, comp_rows = [], []
    for pid, label, analog, veg_max, mixed_max in POLICIES:
        for src in srcs:
            d = acc[(pid, src)]
            kept_n60 = d["kept"] - d["kept_s60"]
            rows.append({
                "policy": pid, "description": label,
                "analog_classes_mcd12c1": " ".join(map(str, analog)),
                "analog_class_names": "; ".join(C.IGBP[k] for k in analog),
                "veg_max": veg_max, "mixed_max": mixed_max, "landcover_source": src,
                "kept_km2": round(d["kept"]), "kept_pct_of_ne_land": round(100 * d["kept"] / land_km2, 2),
                "kept_north_of_60S_km2": round(kept_n60),
                "kept_north_of_60S_pct_of_ne_land_north_of_60S": round(100 * kept_n60 / land_n60, 2),
                "kept_south_of_60S_km2": round(d["kept_s60"]),
                "nodata_land_kept_km2": round(d["nodata_kept"]),
                "analog_class_area_inside_kept_km2": round(d["analog_in_kept"]),
                "non_analog_area_inside_kept_km2": round(d["kept"] - d["analog_in_kept"] - d["nodata_kept"]),
                "analog_class_area_on_ne_land_km2": round(d["analog_frac_land"]),
                "analog_class_area_on_ne_land_pct": round(100 * d["analog_frac_land"] / land_km2, 2),
                "ne_land_km2": round(land_km2),
            })
            for k in range(NCLS):
                comp_rows.append({"policy": pid, "landcover_source": src, "mcd12c1_class": k, "class_name": C.IGBP[k],
                                  "analog_in_policy": k in analog, "area_inside_kept_pixels_km2": round(d["comp"][k]),
                                  "pct_of_kept": round(100 * d["comp"][k] / d["kept"], 2) if d["kept"] else ""})
            comp_rows.append({"policy": pid, "landcover_source": src, "mcd12c1_class": "nodata",
                              "class_name": "No land-cover data (kept by default)", "analog_in_policy": "",
                              "area_inside_kept_pixels_km2": round(d["nodata_kept"]),
                              "pct_of_kept": round(100 * d["nodata_kept"] / d["kept"], 2) if d["kept"] else ""})
    blank = {k: "" for k in rows[0]}
    rows.append({**blank, "policy": "REF", "description": "Reported v2 result (pipeline/README.md): MODIS+Esri mean, GHSL, NE; not reproduced here",
                 "landcover_source": "mcd12q1+esri (+GHSL)", "kept_km2": round(REPORTED_V2_KEPT_KM2),
                 "kept_pct_of_ne_land": round(100 * REPORTED_V2_KEPT_KM2 / land_km2, 2), "ne_land_km2": round(land_km2)})
    for src in srcs:
        rows.append({**blank, "policy": "COVERAGE", "landcover_source": src,
                     "description": "NE land with no land-cover data (kept by default under every policy) / of it south of 60S",
                     "kept_km2": round(cov[src]["nodata_on_ne_land"]), "kept_south_of_60S_km2": round(cov[src]["nodata_on_ne_land_s60"]),
                     "analog_class_area_on_ne_land_km2": f"land-cover land outside NE land: {round(cov[src]['lc_land_outside_ne'])}",
                     "ne_land_km2": round(land_km2)})
    C.write_csv(C.RESULTS / "filter_policy_comparison.csv", rows)
    C.write_csv(C.RESULTS / "filter_policy_kept_composition.csv", comp_rows)
    for r in rows:
        print(f"{r['policy']:8s} {r['landcover_source']:22s} kept {r['kept_km2']!s:>12} km2  {r['kept_pct_of_ne_land']!s:>6}% "
              f"| N of 60S {r['kept_north_of_60S_km2']!s:>12} | S {r['kept_south_of_60S_km2']!s:>11} | nodata {r['nodata_land_kept_km2']!s:>10}")


if __name__ == "__main__":
    main()
