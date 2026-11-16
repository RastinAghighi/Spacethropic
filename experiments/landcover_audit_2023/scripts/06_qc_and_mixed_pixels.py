"""QC flags in sampled MCD12Q1 tiles, barren land lost in mixed pixels, and an NDVI cross-check.

A. QC flags (sampled tiles only, not the whole globe). MCD12 C6.1 User Guide, Table 11:
     1 unclassified land: missing data, land per the water mask, LABELLED BARREN
     6 omitted snow/ice: classified as something else, max annual temperature < 1 C, relabelled snow/ice
     7 misclassified snow/ice: classified as snow, min annual temperature > 1 C, RELABELLED BARREN
     (0 classified land, 2/3 water, 4 sea ice, 5 misclassified water, 8 backfilled, 9 forest type, 10 no data)
   Tiles: every tile holding a validation site, plus regional samples (deserts, rainforests, ice sheets,
   high mountains, boreal, tundra). Per tile: QC x class table. Per 0.05 deg pixel touched: does the
   v2 land-cover decision change if QC=1 pixels are treated as missing, or as non-analog?
   QC=7 and QC=6 move pixels between barren and snow/ice, both analog in v2, so they cannot change a
   v2 decision; their area is reported because a barren-only or bare-ground gate would see them.
B. Barren land inside removed 0.05 deg pixels (whole globe, from the cached 0.05 deg counts of
   script 02; land-cover rule only, as in the audit's P1). Removed pixels with >= 24 barren 500 m
   pixels (5.2 km2, about one r7 cell) are the candidate flag for selective 500 m refinement. In the
   sampled tiles, the largest 8-connected barren patch inside each flagged pixel is measured.
C. Independent vegetation check: VIIRS VNP13C2 2023 peak monthly NDVI (v1's input). Kept area of P1,
   and of P1 AND peak NDVI < 0.5, with the class make-up of what the NDVI gate removes.

Outputs: results/qc_sampled_tiles.csv, results/qc_flip_summary.csv, results/mixed_pixel_barren.csv,
         results/mixed_pixel_flag_examples.csv, results/ndvi_gate_global.csv, work/06_summary.json
Usage:   .venv/Scripts/python.exe -I scripts/06_qc_and_mixed_pixels.py [--data DIR]   (after 02)
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
import validation_sites as VS  # noqa: E402

import numpy as np  # noqa: E402
import rasterio  # noqa: E402
from pyhdf.SD import SD, SDC  # noqa: E402

_spec = importlib.util.spec_from_file_location("sv", Path(__file__).resolve().parent / "05_site_validation.py")
SV = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SV)

VEG = np.array(SV.VEG_CLASSES)
BARREN_FLAG_PX = 24          # 24 x 0.2147 km2 = 5.15 km2, about one H3 r7 cell (5.161 km2)
NDVI_MAX = 0.5               # v1 threshold
REGIONAL_TILES = {           # (h, v): label
    (18, 6): "Sahara (Algeria)", (22, 7): "Rub al Khali", (25, 5): "Tibetan Plateau", (25, 4): "Gobi",
    (25, 6): "Himalaya / Ganges", (11, 9): "Amazon", (20, 8): "Congo basin", (29, 8): "Borneo",
    (31, 9): "New Guinea", (30, 11): "Australian interior", (16, 1): "Greenland ice sheet",
    (17, 2): "Iceland", (22, 2): "Central Siberia", (19, 17): "East Antarctic interior",
    (12, 13): "Patagonia", (13, 3): "Canadian Shield (Quebec)", (20, 5): "Anatolia / Mediterranean",
    (21, 3): "European Russia", (10, 2): "Canadian Arctic / NWT",
}


def v2_lc_removed(cnt: np.ndarray, land: np.ndarray):
    """cnt (17, ...) counts -> (removed, reason code) with v2's land-cover thresholds, float32 shares.
    reason: 0 kept, 1 not NE land, 2 water, 3 built, 4 vegetated, 5 mixed (largest group listed after)."""
    tot = cnt.sum(axis=0, dtype=np.int32)
    den = np.maximum(tot, 1).astype(np.float32)
    has = tot > 0
    w = np.where(has, cnt[0].astype(np.float32) / den, 0).astype(np.float32)
    b = np.where(has, cnt[13].astype(np.float32) / den, 0).astype(np.float32)
    v = np.where(has, cnt[VEG].sum(axis=0, dtype=np.int32).astype(np.float32) / den, 0).astype(np.float32)
    reason = np.zeros(tot.shape, np.int8)
    mixed = (w + b + v) >= SV.NON_ANALOG_MAX
    reason[mixed] = 5
    reason[v >= SV.VEG_MAX] = 4
    reason[w >= SV.WATER_MAX] = 2
    reason[b >= SV.BUILT_MAX] = 3
    reason[~land] = 1
    return reason > 0, reason


REASONS = {0: "kept", 1: "not NE land", 2: "water >= 0.5", 3: "built >= 0.25", 4: "vegetation >= 0.5", 5: "mixed >= 0.5"}


def site_tiles() -> dict:
    out = {}
    for s in VS.SITES:
        gi, gj = SV.latlon_to_gij(s["lat"], s["lon"])
        out.setdefault((int(gj) // 2400, int(gi) // 2400), []).append(s["id"])
    return out


def components_max(mask: np.ndarray) -> int:
    return max((len(c) for c in SV.components(mask)), default=0)


def part_a_and_c_tiles(data: Path, q1, land):
    paths = SV.q1_tiles(data)
    st = site_tiles()
    tiles = {k: "site: " + ", ".join(v) for k, v in st.items()}
    for k, lab in REGIONAL_TILES.items():
        tiles[k] = (tiles[k] + "; " if k in tiles else "") + lab
    rows, flips, patch_rows = [], [], []
    rr = np.arange(2400)
    for (h, v), label in sorted(tiles.items()):
        p = paths.get((h, v))
        if p is None:
            rows.append({"tile": f"h{h:02d}v{v:02d}", "label": label, "status": "no MCD12Q1 tile (ocean)"})
            continue
        f = SD(str(p), SDC.READ)
        lc, qc = f.select("LC_Type1")[:], f.select("QC")[:]
        f.end()
        GI, GJ = np.meshgrid(v * 2400 + rr, h * 2400 + rr, indexing="ij")
        lat, lon = SV.gij_to_latlon(GI, GJ)
        ok = np.isfinite(lon)
        cls = SV.Q1_TO_C1[lc]
        landpx = ok & np.isin(qc, (0, 1, 5, 6, 7, 8, 9))           # land per the MODIS water mask
        n_land = int(landpx.sum())
        row = {"tile": f"h{h:02d}v{v:02d}", "label": label, "status": "ok", "land_px": n_land,
               "land_km2": round(n_land * C.PIX_KM2)}
        for q in (1, 5, 6, 7, 8, 9, 10):
            m = ok & (qc == q)
            row[f"qc{q}_km2"] = round(int(m.sum()) * C.PIX_KM2, 1)
            row[f"qc{q}_pct_land"] = round(100 * int(m.sum()) / max(n_land, 1), 3)
        for q in (1, 7):
            m = ok & (qc == q)
            labs = np.bincount(cls[m & (cls >= 0)], minlength=17)
            row[f"qc{q}_labels"] = "; ".join(f"{C.IGBP[k]} {int(labs[k])}" for k in np.nonzero(labs)[0]) or "-"
            if m.any():
                row[f"qc{q}_lat_range"] = f"{np.nanmin(lat[m]):.2f}..{np.nanmax(lat[m]):.2f}"
                row[f"qc{q}_lon_range"] = f"{np.nanmin(lon[m]):.2f}..{np.nanmax(lon[m]):.2f}"
            else:
                row[f"qc{q}_lat_range"] = row[f"qc{q}_lon_range"] = "-"
        barren = ok & (lc == 16)
        nb = int(barren.sum())
        for q in (1, 5, 7):
            row[f"barren_from_qc{q}_pct"] = round(100 * int((barren & (qc == q)).sum()) / max(nb, 1), 2)
        row["barren_km2"] = round(nb * C.PIX_KM2, 1)
        snow = ok & (lc == 15)
        row["snow_ice_from_qc6_pct"] = round(100 * int((snow & (qc == 6)).sum()) / max(int(snow.sum()), 1), 2)
        rows.append(row)

        # --- QC=1 decision flips on the 0.05 deg pixels this tile touches --------------------
        pr, pc = SV.bin_rc(np.where(ok, lat, 0), np.where(ok, lon, 0))
        key = (pr * C.W + pc)[ok]
        q1m = (qc == 1)[ok]
        if q1m.any():
            keys, n1 = np.unique(key[q1m], return_counts=True)
            r_, c_ = keys // C.W, keys % C.W
            cnt = np.asarray(q1[:, r_, c_], np.int64)                  # (17, n) full-pixel counts
            ln = land[r_, c_]
            base, _ = v2_lc_removed(cnt, ln)
            miss = cnt.copy()
            miss[16] -= n1                                            # QC=1 as missing
            as_veg = miss.copy()
            as_veg[12] += n1                                          # QC=1 as cropland (non-analog)
            alt1, _ = v2_lc_removed(miss, ln)
            alt2, _ = v2_lc_removed(as_veg, ln)
            area = C.pixel_area_km2()[r_, 0]
            flips.append({"tile": row["tile"], "label": label, "pixels_with_qc1": int(len(keys)),
                          "qc1_km2": round(int(n1.sum()) * C.PIX_KM2, 1),
                          "kept_to_removed_if_missing": int((~base & alt1).sum()),
                          "removed_to_kept_if_missing": int((base & ~alt1).sum()),
                          "kept_to_removed_if_nonanalog": int((~base & alt2).sum()),
                          "kept_to_removed_if_nonanalog_km2": round(float(area[~base & alt2].sum()), 1),
                          "pixels_all_qc1": int((n1 >= cnt.sum(axis=0)).sum())})

        # --- barren patches inside flagged removed pixels (part B detail) --------------------
        tk = np.unique(key)
        r_, c_ = tk // C.W, tk % C.W
        cnt = np.asarray(q1[:, r_, c_], np.int64)
        rem, why = v2_lc_removed(cnt, land[r_, c_])
        flag = rem & (why != 1) & (cnt[16] >= BARREN_FLAG_PX)
        if flag.any():
            flat = np.full(lc.size, -1, np.int64)
            flat[ok.ravel()] = key
            order = np.argsort(flat, kind="stable")
            sk = flat[order]
            bar_flat, qc_flat = barren.ravel(), qc.ravel()
            for k, w_ in zip(tk[flag], why[flag]):
                lo, hi = np.searchsorted(sk, k), np.searchsorted(sk, k, side="right")
                idx = order[lo:hi]
                ii, jj = idx // 2400, idx % 2400
                sub = np.zeros((ii.max() - ii.min() + 1, jj.max() - jj.min() + 1), bool)
                sub[ii - ii.min(), jj - jj.min()] = bar_flat[idx]
                full = np.asarray(q1[:, k // C.W, k % C.W], np.int64)
                nonan = [j for j in np.argsort(-full) if C.TEAM_GROUP[j] in ("veg", "water", "built") and full[j] > 0][:2]
                patch_rows.append({"tile": row["tile"], "lat": round(90 - (k // C.W + 0.5) * C.RES, 3),
                                   "lon": round(-180 + (k % C.W + 0.5) * C.RES, 3), "reason": REASONS[int(w_)],
                                   "barren_px": int(full[16]), "barren_pct": round(100 * full[16] / max(full.sum(), 1), 1),
                                   "largest_patch_px": components_max(sub), "main_non_analog": "; ".join(
                                       f"{C.IGBP[j]} {100 * full[j] / full.sum():.0f}%" for j in nonan),
                                   "qc1_px_in_pixel": int((qc_flat[idx] == 1).sum())})
        print(f"{row['tile']} {label[:60]:60s} qc1 {row.get('qc1_pct_land', 0):6.3f}% qc7 {row.get('qc7_pct_land', 0):6.3f}% "
              f"qc6 {row.get('qc6_pct_land', 0):6.2f}%  flagged {int(flag.sum()) if flag.any() else 0}", flush=True)
    return rows, flips, patch_rows


def part_b_c_global(data: Path, q1, land):
    area = C.pixel_area_km2()
    peak = np.full((C.H, C.W), -np.inf, np.float32)
    nvalid = np.zeros((C.H, C.W), np.uint8)
    for p in sorted((data / "viirs-2023").glob("VNP13C2.A2023*.h5")):
        with rasterio.open(f'HDF5:"{p}":{SV.NDVI_DATASET}') as src:
            a = src.read(1)
        ok = a > -10000
        nvalid += ok
        np.maximum(peak, np.where(ok, a.astype(np.float32) * 1e-4, -np.inf), out=peak)
        del a, ok
    peak[~np.isfinite(peak)] = np.nan

    acc = {"barren_removed": {k: 0.0 for k in REASONS}, "flag_px": {k: 0 for k in REASONS},
           "flag_area": {k: 0.0 for k in REASONS}, "flag_barren": {k: 0.0 for k in REASONS},
           "flag10_px": 0, "flag10_area": 0.0, "barren_kept": 0.0, "barren_all_land": 0.0}
    nd = {"p1_kept": 0.0, "p1_kept_s60": 0.0, "p1_ndvi_kept": 0.0, "p1_ndvi_kept_s60": 0.0,
          "ndvi_removed_comp": np.zeros(17), "ndvi_missing_kept": 0.0, "barren_lost_to_ndvi": 0.0}
    for r0 in range(0, C.H, 100):
        r1 = min(C.H, r0 + 100)
        cnt = np.asarray(q1[:, r0:r1, :], np.int64)
        ln = land[r0:r1]
        rem, why = v2_lc_removed(cnt, ln)
        ar = np.broadcast_to(area[r0:r1], ln.shape)
        bar_km2 = cnt[16] * C.PIX_KM2
        acc["barren_all_land"] += float(bar_km2[ln].sum())
        acc["barren_kept"] += float(bar_km2[~rem].sum())
        for k in range(2, 6):
            m = ln & (why == k)
            acc["barren_removed"][k] += float(bar_km2[m].sum())
            fm = m & (cnt[16] >= BARREN_FLAG_PX)
            acc["flag_px"][k] += int(fm.sum())
            acc["flag_area"][k] += float(ar[fm].sum())
            acc["flag_barren"][k] += float(bar_km2[fm].sum())
        tot = np.maximum(cnt.sum(axis=0), 1)
        f10 = ln & rem & (why != 1) & (cnt[16] / tot >= 0.10)
        acc["flag10_px"] += int(f10.sum())
        acc["flag10_area"] += float(ar[f10].sum())
        # NDVI gate on top of P1
        kept = ~rem
        pk = peak[r0:r1]
        gate = np.isfinite(pk) & (pk >= NDVI_MAX)
        south = r0 >= C.SOUTH_60_ROW
        nd["p1_kept"] += float(ar[kept].sum())
        nd["p1_ndvi_kept"] += float(ar[kept & ~gate].sum())
        if south:
            nd["p1_kept_s60"] += float(ar[kept].sum())
            nd["p1_ndvi_kept_s60"] += float(ar[kept & ~gate].sum())
        nd["ndvi_missing_kept"] += float(ar[kept & ~np.isfinite(pk)].sum())
        lost = kept & gate
        share = cnt / tot
        for k in range(17):
            nd["ndvi_removed_comp"][k] += float((share[k] * ar)[lost].sum())
        nd["barren_lost_to_ndvi"] += float(bar_km2[lost].sum())
    return acc, nd


def main() -> None:
    a = C.args(__doc__)
    land = C.ne_land_mask(a.data)
    q1 = np.load(C.WORK / "mcd12q1_counts_0p05.npy", mmap_mode="r")

    rows, flips, patches = part_a_and_c_tiles(a.data, q1, land)
    C.write_csv(C.RESULTS / "qc_sampled_tiles.csv", [{k: r.get(k, "") for k in max(rows, key=len)} for r in rows])
    if flips:
        C.write_csv(C.RESULTS / "qc_flip_summary.csv", flips)
    if patches:
        patches.sort(key=lambda r: -r["largest_patch_px"])
        C.write_csv(C.RESULTS / "mixed_pixel_flag_examples.csv", patches)

    acc, nd = part_b_c_global(a.data, q1, land)
    out = []
    for k in range(2, 6):
        out.append({"removed_by": REASONS[k], "barren_km2_in_removed_pixels": round(acc["barren_removed"][k]),
                    f"pixels_with_ge_{BARREN_FLAG_PX}_barren_500m": acc["flag_px"][k],
                    "flagged_pixel_area_km2": round(acc["flag_area"][k]),
                    "barren_km2_in_flagged_pixels": round(acc["flag_barren"][k]),
                    "r7_cells_to_refine_approx": round(acc["flag_area"][k] / 5.161)})
    out.append({"removed_by": "ALL (land-cover reasons)", "barren_km2_in_removed_pixels": round(sum(acc["barren_removed"].values())),
                f"pixels_with_ge_{BARREN_FLAG_PX}_barren_500m": sum(acc["flag_px"].values()),
                "flagged_pixel_area_km2": round(sum(acc["flag_area"].values())),
                "barren_km2_in_flagged_pixels": round(sum(acc["flag_barren"].values())),
                "r7_cells_to_refine_approx": round(sum(acc["flag_area"].values()) / 5.161)})
    out.append({"removed_by": "reference: barren in kept pixels", "barren_km2_in_removed_pixels": round(acc["barren_kept"])})
    out.append({"removed_by": "reference: barren on all NE land", "barren_km2_in_removed_pixels": round(acc["barren_all_land"])})
    out.append({"removed_by": "alt flag: removed pixels with barren share >= 10%",
                f"pixels_with_ge_{BARREN_FLAG_PX}_barren_500m": acc["flag10_px"], "flagged_pixel_area_km2": round(acc["flag10_area"]),
                "r7_cells_to_refine_approx": round(acc["flag10_area"] / 5.161)})
    C.write_csv(C.RESULTS / "mixed_pixel_barren.csv", [{k: r.get(k, "") for k in out[0]} for r in out])

    comp = nd["ndvi_removed_comp"]
    ndrows = [
        {"quantity": "P1 kept (land-cover rule only; audit value 94,029,740)", "km2": round(nd["p1_kept"])},
        {"quantity": "P1 kept south of 60S", "km2": round(nd["p1_kept_s60"])},
        {"quantity": f"P1 AND peak NDVI < {NDVI_MAX} kept (missing NDVI kept, as in v1)", "km2": round(nd["p1_ndvi_kept"])},
        {"quantity": "  of which south of 60S", "km2": round(nd["p1_ndvi_kept_s60"])},
        {"quantity": "  of which has no valid NDVI month", "km2": round(nd["ndvi_missing_kept"])},
        {"quantity": "Removed by the NDVI gate", "km2": round(nd["p1_kept"] - nd["p1_ndvi_kept"])},
        {"quantity": "  barren 500 m area inside those pixels", "km2": round(nd["barren_lost_to_ndvi"])},
    ] + [{"quantity": f"  NDVI-gate removal, class {C.IGBP[k]}", "km2": round(comp[k])} for k in np.argsort(-comp) if comp[k] > 1000]
    C.write_csv(C.RESULTS / "ndvi_gate_global.csv", ndrows)
    (C.WORK / "06_summary.json").write_text(json.dumps({"mixed": out, "ndvi": ndrows}, indent=1), encoding="utf-8")
    for r in out + ndrows:
        print(r)


if __name__ == "__main__":
    main()
