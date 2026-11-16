"""Readiness checks for a REGIONAL H3 r7 pilot. No global cells are generated.

Runs in the regional pilot's venv (it has h3 4.5.0, shapely, pyproj, rasterio):
  ..\\global_filter\\regional_pilot\\.venv\\Scripts\\python.exe -I scripts\\08_r7_readiness.py

A. Hexagon filter step at r7 vs r8 (contours_r8.py logic, teammate commit 475bf4e): a hexagon is
   dropped when >= 90 % of a 0.001 deg sample grid inside it falls in removed 0.05 deg pixels.
   Applied to the r7 cells within 2 rings of each validation site (19 cells) and to their r8
   children (133), against the kept flags from script 05 (v2, MODIS-only + GHSL + Natural Earth).
B. Drumheller badlands: the NASADEM pilot's r8 terrain cells (research/nasadem_h3_pilot outputs)
   joined to the mask, at r8 and aggregated to r7 parents. Are the rugged badland cells kept?
C. Regional pilot smoke test at r7 (experiments/global_filter/regional_pilot/pilot.py, imported,
   NOT modified): ring_cells(..., resolution=7) + cell_polygon + aggregate_polygon + decision on the
   500 m MCD12Q1 GeoTIFFs from script 07. MODIS is not one of the pilot's schemes, so a scheme is
   added to pilot.CLASS_MAPS in memory only, for this test (mapping stated below).
Outputs: results/r7_hex_filter_sites.csv, results/r7_drumheller_terrain.csv,
         results/r7_pilot_smoketest.csv, work/08_summary.json
"""

from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
REPO = EXP.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "experiments" / "global_filter" / "regional_pilot"))
import validation_sites as VS  # noqa: E402

import h3  # noqa: E402
import numpy as np  # noqa: E402
import rasterio  # noqa: E402
from rasterio.features import rasterize  # noqa: E402
from rasterio.transform import from_origin  # noqa: E402

import pilot  # noqa: E402  (read-only use)

RES, W, H = 0.05, 7200, 3600
REMOVE_AT, SAMPLE_DEG = 0.9, 0.001          # contours_r8.py
NASADEM_R8 = REPO / "research" / "nasadem_h3_pilot" / "outputs" / "n51w113_drumheller_badlands_h3" / "h3_res8_cells.csv"
# Smoke-test mapping, IGBP (MCD12Q1 LC_Type1) -> pilot class names. Woody savanna (30-60 % trees)
# -> trees, savanna (10-30 % trees) -> grass. Chosen for this test only; not a team decision.
MODIS_SCHEME = {1: "trees", 2: "trees", 3: "trees", 4: "trees", 5: "trees", 6: "shrub_scrub", 7: "shrub_scrub",
                8: "trees", 9: "grass", 10: "grass", 11: "flooded_vegetation", 12: "cropland", 13: "built",
                14: "cropland", 15: "snow_ice_unspecified", 16: "bare", 17: "water_unspecified"}
PILOT_SITES = ("hanksville_mdrs", "drumheller", "atacama_yungay", "probe_konza_grassland", "mcmurdo_beacon")


def write_csv(path: Path, rows: list[dict]) -> None:
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


class Kept:
    """Kept flags of one site window (script 05) with the 0.05 deg indexing of contours_r8."""

    def __init__(self, z, sid):
        self.r0, self.c0 = (int(v) for v in z[f"{sid}__r0c0"])
        self.k = z[f"{sid}__kept"].astype(bool)

    def lookup(self, lat, lon):
        mr = np.clip(((90.0 - lat) / RES).astype(int), 0, H - 1) - self.r0
        mc = (np.floor(((lon + 180.0) % 360.0) / RES).astype(int)) % W - self.c0
        inside = (mr >= 0) & (mr < self.k.shape[0]) & (mc >= 0) & (mc < self.k.shape[1])
        out = np.zeros(np.broadcast(mr, mc).shape, bool)
        mrb, mcb = np.broadcast_arrays(mr, mc)
        out[inside] = self.k[mrb[inside], mcb[inside]]
        return out, inside


def removed_fraction(cells, kept: Kept):
    """contours_r8.removed_fraction(), against a site window. Returns (frac, n_samples, n_outside)."""
    lat_mid = float(np.mean([h3.cell_to_latlng(c)[0] for c in cells]))
    lon_ref = float(np.mean([h3.cell_to_latlng(c)[1] for c in cells]))
    polys = []
    for c in cells:
        ring = [(lon_ref + ((lo - lon_ref + 180) % 360 - 180), la) for la, lo in h3.cell_to_boundary(c)]
        polys.append({"type": "Polygon", "coordinates": [ring + ring[:1]]})
    xs = [x for p in polys for x, _ in p["coordinates"][0]]
    ys = [y for p in polys for _, y in p["coordinates"][0]]
    w, s, e, n = min(xs), min(ys), max(xs), max(ys)
    dy = SAMPLE_DEG
    dx = SAMPLE_DEG / max(math.cos(math.radians(lat_mid)), 0.02)
    width, height = math.ceil((e - w) / dx), math.ceil((n - s) / dy)
    labels = rasterize(((p, i + 1) for i, p in enumerate(polys)), out_shape=(height, width),
                       transform=from_origin(w, n, dx, dy), fill=0, dtype="int32")
    lat = n - (np.arange(height) + 0.5) * dy
    lon = w + (np.arange(width) + 0.5) * dx
    kept_s, inside = kept.lookup(lat[:, None], lon[None, :])
    removed = ~kept_s
    cnt = np.bincount(labels.ravel(), minlength=len(polys) + 1)[1:]
    rem = np.bincount(labels.ravel(), weights=removed.ravel(), minlength=len(polys) + 1)[1:]
    outside = np.bincount(labels.ravel(), weights=(~inside).ravel(), minlength=len(polys) + 1)[1:]
    return np.where(cnt > 0, rem / np.maximum(cnt, 1), 1.0), cnt, outside


def part_a(z) -> list[dict]:
    rows = []
    for s in VS.SITES:
        kept = Kept(z, s["id"])
        c7 = h3.latlng_to_cell(s["lat"], s["lon"], 7)
        disk7 = sorted(h3.grid_disk(c7, 2))
        disk8 = sorted(ch for c in disk7 for ch in h3.cell_to_children(c, 8))
        f7, n7, o7 = removed_fraction(disk7, kept)
        f8, n8, o8 = removed_fraction(disk8, kept)
        a7 = np.array([h3.cell_area(c, unit="km^2") for c in disk7])
        a8 = np.array([h3.cell_area(c, unit="km^2") for c in disk8])
        site_f7 = float(f7[disk7.index(c7)])
        c8 = h3.latlng_to_cell(s["lat"], s["lon"], 8)
        site_f8 = float(f8[disk8.index(c8)]) if c8 in disk8 else float("nan")
        rows.append({
            "id": s["id"], "group": s["group"], "site_r7_cell": c7,
            "site_r7_removed_frac": round(site_f7, 3), "site_r7_kept": site_f7 < REMOVE_AT,
            "site_r8_removed_frac": round(site_f8, 3), "site_r8_kept": site_f8 < REMOVE_AT,
            "r7_cells": len(disk7), "r7_kept": int((f7 < REMOVE_AT).sum()),
            "r7_kept_but_partly_removed": int(((f7 > 0) & (f7 < REMOVE_AT)).sum()),
            "r7_kept_km2": round(float(a7[f7 < REMOVE_AT].sum()), 1),
            "r8_cells": len(disk8), "r8_kept": int((f8 < REMOVE_AT).sum()),
            "r8_kept_but_partly_removed": int(((f8 > 0) & (f8 < REMOVE_AT)).sum()),
            "r8_kept_km2": round(float(a8[f8 < REMOVE_AT].sum()), 1),
            "mean_samples_per_r7_cell": round(float(n7.mean())),
            "samples_outside_window": int(o7.sum() + o8.sum()),
        })
        print(f"{s['id']:24s} r7 site kept {rows[-1]['site_r7_kept']!s:5s} ({site_f7:.2f}) ring2 r7 {rows[-1]['r7_kept']}/19 "
              f"({rows[-1]['r7_kept_km2']} km2) r8 {rows[-1]['r8_kept']}/133 ({rows[-1]['r8_kept_km2']} km2)", flush=True)
    return rows


def part_b(z) -> dict:
    kept = Kept(z, "drumheller")
    with open(NASADEM_R8, encoding="utf-8") as f:
        cells = [r for r in csv.DictReader(f) if r["slope_mean_deg"] not in ("", "nan")]
    ids = [r["h3_cell"] for r in cells]
    f8, _, out8 = removed_fraction(ids, kept)
    slope = np.array([float(r["slope_mean_deg"]) for r in cells])
    cov = np.array([float(r["valid_coverage_fraction"]) for r in cells])
    full = cov >= 0.99
    k8 = f8 < REMOVE_AT
    rugged = slope >= 10.0
    parents = {}
    for cid, sl, cv in zip(ids, slope, cov):
        parents.setdefault(h3.cell_to_parent(cid, 7), []).append((sl, cv))
    pids = sorted(parents)
    f7, _, _ = removed_fraction(pids, kept)
    p_slope = np.array([np.average([a for a, _ in parents[p]], weights=[b for _, b in parents[p]]) for p in pids])
    p_nchild = np.array([len(parents[p]) for p in pids])
    k7 = f7 < REMOVE_AT
    rug7 = p_slope >= 10.0
    out = {
        "r8_cells_with_terrain": len(ids), "r8_full_coverage": int(full.sum()),
        "r8_kept": int(k8.sum()), "r8_rugged_slope_ge_10": int(rugged.sum()),
        "r8_rugged_kept": int((rugged & k8).sum()),
        "r8_mean_slope_kept": round(float(slope[k8].mean()), 2) if k8.any() else None,
        "r8_mean_slope_removed": round(float(slope[~k8].mean()), 2) if (~k8).any() else None,
        "r7_parents": len(pids), "r7_parents_with_all_7_children": int((p_nchild == 7).sum()),
        "r7_kept": int(k7.sum()), "r7_rugged_mean_slope_ge_10": int(rug7.sum()), "r7_rugged_kept": int((rug7 & k7).sum()),
        "samples_outside_window": int(out8.sum()),
        "note": "slope_mean_deg from NASADEM 1 arc-second (research/nasadem_h3_pilot); r7 slope = coverage-weighted mean of child r8 means",
    }
    rows = [{"resolution": 7, "h3_cell": p, "n_children_with_terrain": int(nc), "slope_mean_deg": round(float(sl), 2),
             "removed_frac": round(float(fr), 3), "kept": bool(fr < REMOVE_AT)}
            for p, nc, sl, fr in zip(pids, p_nchild, p_slope, f7)]
    write_csv(EXP / "results" / "r7_drumheller_terrain.csv", rows)
    print("drumheller terrain", out, flush=True)
    return out


def sinusoidal_overcount(tif: Path, cid: str) -> float:
    """measured / polygon area - 1 inside pilot.aggregate_polygon for the native sinusoidal raster
    (the pilot raises when this exceeds 1e-7). Re-uses pilot's own projection helpers, read-only."""
    from pyproj import Transformer
    from shapely.geometry import Polygon
    lat, lon = h3.cell_to_latlng(cid)
    with rasterio.open(tif) as src:
        to_src = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True).transform
        to_area = pilot._laea_transformer(src.crs, lat, lon)
        poly = pilot._reproject(pilot.cell_polygon(cid), to_src)
        whole = pilot._reproject(poly, to_area).area
        tot = 0.0
        for r in range(src.height):
            for c in range(src.width):
                px = Polygon([src.transform @ (c, r), src.transform @ (c + 1, r),
                              src.transform @ (c + 1, r + 1), src.transform @ (c, r + 1)])
                if px.intersects(poly):
                    tot += pilot._reproject(px.intersection(poly), to_area).area
    return tot / whole - 1.0


def part_c() -> list[dict]:
    scheme = "modis_igbp_smoketest"
    pilot.CLASS_MAPS[scheme] = dict(MODIS_SCHEME)       # in memory only; pilot.py is unchanged
    rows = []
    for s in VS.SITES:
        if s["id"] not in PILOT_SITES:
            continue
        native = EXP / "work" / "pilot_inputs" / f"{s['id']}_mcd12q1_lc.tif"
        for res in (7, 8):
            for cid in pilot.ring_cells(s["lat"], s["lon"], 1, resolution=res):
                try:
                    with rasterio.open(native) as src:
                        pilot.aggregate_polygon(src, pilot.cell_polygon(cid), *h3.cell_to_latlng(cid), scheme)
                    status = "accepted"
                except ValueError as exc:
                    status = f"rejected: {exc}"
                rows.append({"id": s["id"], "resolution": res, "h3_cell": cid, "raster": "native MODIS sinusoidal 463 m",
                             "pilot_status": status, "overcount_ratio": f"{sinusoidal_overcount(native, cid):.2e}"})
        tif = EXP / "work" / "pilot_inputs" / f"{s['id']}_mcd12q1_lc_utm100m.tif"
        for res in (7, 8):
            cells = pilot.ring_cells(s["lat"], s["lon"], 1, resolution=res)
            with rasterio.open(tif) as src:
                pilot.check_categorical_raster(src, scheme)
                for cid in cells:
                    lat, lon = h3.cell_to_latlng(cid)
                    pct = pilot.aggregate_polygon(src, pilot.cell_polygon(cid), lat, lon, scheme)
                    row = {"id": s["id"], "resolution": res, "h3_cell": cid, "raster": "UTM 100 m nearest copy",
                           "pilot_status": "accepted", "is_site_cell": cid == h3.latlng_to_cell(s["lat"], s["lon"], res),
                           "cell_km2": round(h3.cell_area(cid, unit="km^2"), 3),
                           "modis_500m_px_per_cell": round(h3.cell_area(cid, unit="km^2") / 0.21466, 1)}
                    row.update({f"pct_{k}": round(v, 2) for k, v in pct.items() if v > 0.005})
                    for m in ("mars_dry", "moon_dry", "polar_analog"):
                        row[f"decision_{m}"] = pilot.decision(pct, m)[0]
                    rows.append(row)
        r7 = [r for r in rows if r["id"] == s["id"] and r["resolution"] == 7 and "decision_mars_dry" in r]
        nat = [r for r in rows if r["id"] == s["id"] and r["raster"].startswith("native")]
        print(s["id"], "native sinusoidal rejected:", sum(r["pilot_status"] != "accepted" for r in nat), "of", len(nat),
              "ratios", [r["overcount_ratio"] for r in nat], flush=True)
        print(s["id"], "r7 mars_dry:", [r["decision_mars_dry"] for r in r7],
              "bare%:", [r.get("pct_bare", 0) for r in r7], flush=True)
    return rows


def main() -> None:
    z = np.load(EXP / "work" / "site_kept_windows.npz")
    a = part_a(z)
    write_csv(EXP / "results" / "r7_hex_filter_sites.csv", a)
    b = part_b(z)
    c = part_c()
    write_csv(EXP / "results" / "r7_pilot_smoketest.csv", c)
    facts = {f"r{r}": {"mean_area_km2": h3.average_hexagon_area(r, unit="km^2"), "cells_globe": h3.get_num_cells(r)} for r in (7, 8)}
    (EXP / "work" / "08_summary.json").write_text(json.dumps({"hex_filter": a, "drumheller": b, "h3": facts,
                                                             "h3_version": h3.__version__}, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
