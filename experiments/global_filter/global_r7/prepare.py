"""Prepare independent public inputs, then the MODIS-only v2 mask in row slabs."""

from __future__ import annotations

import argparse
import io
import json
import shutil
import time
import zipfile
from pathlib import Path

import numpy as np
import rasterio
import shapefile
from core import (
    BITS,
    DEG,
    EXCLUDED,
    MISSING,
    POLICY,
    VEG,
    H,
    W,
    atomic_json,
    digest,
    pixel_areas,
    pixel_indices,
    policy_flags,
)
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.windows import Window


def file_info(path):
    path = Path(path)
    return dict(
        path=str(path.resolve()), bytes=path.stat().st_size, sha256=digest(path)
    )


def mmap_new(root, name, dtype, shape):
    return np.lib.format.open_memmap(root / name, mode="w+", dtype=dtype, shape=shape)


def existing_stage(out, config):
    path = out / "manifest.json"
    if not path.exists():
        return False
    meta = json.loads(path.read_text())
    if meta["config"] != config:
        raise ValueError(
            "Different inputs in existing output; select a new output directory"
        )
    if meta["status"] == "complete":
        for name, info in meta["files"].items():
            if digest(out / name) != info["sha256"]:
                raise ValueError(f"Corrupt stage file: {name}")
        print(f"Verified complete: {out}", flush=True)
        return True
    return False


def public_inputs(ne, ghsl, out):
    t0 = time.perf_counter()
    config = dict(stage="public_v1", natural_earth=file_info(ne), ghsl=file_info(ghsl))
    out.mkdir(parents=True, exist_ok=True)
    if existing_stage(out, config):
        return
    atomic_json(out / "manifest.json", dict(status="preparing", config=config))
    with zipfile.ZipFile(ne) as z:
        names = {
            ext: next(n for n in z.namelist() if n.endswith(f"ne_10m_land.{ext}"))
            for ext in ("shp", "shx", "dbf")
        }
        reader = shapefile.Reader(
            **{ext: io.BytesIO(z.read(name)) for ext, name in names.items()}
        )
        geoms = [s.__geo_interface__ for s in reader.shapes()]
    land = rasterize(
        [(g, 1) for g in geoms],
        out_shape=(H, W),
        transform=from_origin(-180, 90, DEG, DEG),
        fill=0,
        dtype="uint8",
    )
    np.save(out / "land.npy", land)
    people = mmap_new(out, "people.npy", "float64", (H, W))
    seen = np.zeros((H, W), np.uint16)
    bad = np.zeros((H, W), np.uint16)
    with rasterio.open(ghsl) as src:
        if (
            src.crs != rasterio.crs.CRS.from_epsg(4326)
            or src.transform.b
            or src.transform.d
        ):
            raise ValueError("Expected north-up GHSL WGS84 raster")
        if not np.allclose(
            [src.transform.a, src.transform.e], [1 / 120, -1 / 120], atol=1e-9
        ):
            raise ValueError("Expected GHSL 30 arcsecond grid")
        lon = src.transform.c + (np.arange(src.width) + 0.5) * src.transform.a
        _, cols = pixel_indices(np.zeros_like(lon), lon)
        for start in range(0, src.height, 120):
            count = min(120, src.height - start)
            a = src.read(1, window=Window(0, start, src.width, count), masked=True)
            lat = src.transform.f + (start + np.arange(count) + 0.5) * src.transform.e
            rows, _ = pixel_indices(lat, np.zeros_like(lat))
            lo, hi = int(rows.min()), int(rows.max()) + 1
            idx = ((rows[:, None] - lo) * W + cols[None, :]).ravel()
            valid = (~np.ma.getmaskarray(a)) & np.isfinite(a.data) & (a.data >= 0)
            shape = (hi - lo, W)
            people[lo:hi] += np.bincount(
                idx, weights=np.where(valid, a.data, 0).ravel(), minlength=(hi - lo) * W
            ).reshape(shape)
            seen[lo:hi] += (
                np.bincount(idx, minlength=(hi - lo) * W)
                .reshape(shape)
                .astype(np.uint16)
            )
            bad[lo:hi] += (
                np.bincount(idx, weights=(~valid).ravel(), minlength=(hi - lo) * W)
                .reshape(shape)
                .astype(np.uint16)
            )
            if start % 2400 == 0:
                print(
                    f"GHSL rows {start}/{src.height}, {time.perf_counter() - t0:.1f}s",
                    flush=True,
                )
    people.flush()
    density = mmap_new(out, "density.npy", "float64", (H, W))
    ar = pixel_areas()
    for r in range(0, H, 100):
        den = people[r : r + 100] / ar[r : r + 100, None]
        den[(seen[r : r + 100] == 0) | (bad[r : r + 100] > 0)] = np.nan
        density[r : r + 100] = den
    density.flush()
    stats = dict(
        ne_land_km2=float(land.sum(axis=1) @ ar),
        people=float(people.sum()),
        land_population_unknown_km2=float(
            (land.astype(bool) & ~np.isfinite(density)).sum(axis=1) @ ar
        ),
        seconds=time.perf_counter() - t0,
    )
    files = {n: file_info(out / n) for n in ("land.npy", "density.npy", "people.npy")}
    atomic_json(
        out / "manifest.json",
        dict(status="complete", config=config, files=files, summary=stats),
    )
    print(json.dumps(stats), flush=True)


def build_mask(base, counts, c1, out):
    t0 = time.perf_counter()
    bm = json.loads((base / "manifest.json").read_text())
    if bm["status"] != "complete":
        raise ValueError("Public preparation not complete")
    for name, info in bm["files"].items():
        if digest(base / name) != info["sha256"]:
            raise ValueError(f"Public input checksum mismatch: {name}")
    source = counts or c1
    config = dict(
        stage="mask_v1",
        base_manifest=file_info(base / "manifest.json"),
        landcover=file_info(source),
        product="MCD12Q1-counts" if counts else "MCD12C1-percent",
        policy=POLICY,
    )
    out.mkdir(parents=True, exist_ok=True)
    if existing_stage(out, config):
        return
    atomic_json(out / "manifest.json", dict(status="preparing", config=config))
    for name in ("land.npy", "density.npy"):
        shutil.copyfile(base / name, out / name)
    land = np.load(out / "land.npy", mmap_mode="r")
    density = np.load(out / "density.npy", mmap_mode="r")
    dest = mmap_new(out, "counts.npy", "uint8", (17, H, W))
    flags = mmap_new(out, "flags.npy", "uint16", (H, W))
    if counts:
        raw = np.load(counts, mmap_mode="r")
        if raw.shape != (17, H, W) or raw.dtype != np.uint8:
            raise ValueError(
                "Counts must be uint8 (17,3600,7200), C1 class order 0=water"
            )
    else:
        from pyhdf.SD import SD, SDC

        if not c1.name.startswith("MCD12C1.A2023001.061."):
            raise ValueError("Expected MCD12C1 2023 v061 filename")
        hdf = SD(str(c1), SDC.READ)
        raw = hdf.select("Land_Cover_Type_1_Percent")
        if raw.info()[2] != [H, W, 17]:
            raise ValueError("Unexpected C1 dimensions")
    totals = {
        k: 0.0
        for k in (
            "land",
            "eligible_land",
            "uncertain_land",
            "excluded_land",
            "barren_review_land",
        )
    }
    reasons = {k: 0.0 for k in BITS}
    areas = pixel_areas()
    for r in range(0, H, 100):
        cnt = (
            np.array(raw[:, r : r + 100, :])
            if counts
            else np.moveaxis(raw[r : r + 100], 2, 0).copy()
        )
        if not counts:
            invalid = np.any(cnt > 100, axis=0) | (cnt.sum(axis=0) != 100)
            cnt[:, invalid] = 0
        dest[:, r : r + 100] = cnt
        total = cnt.sum(axis=0, dtype=np.int32)
        f = cnt.astype(np.float32) / np.maximum(total, 1).astype(np.float32)
        # Sum integer counts before division to reproduce original float32 thresholds.
        veg = cnt[list(VEG)].sum(axis=0).astype(np.float32) / np.maximum(
            total, 1
        ).astype(np.float32)
        ln, den = land[r : r + 100].astype(bool), density[r : r + 100]
        fl = policy_flags(
            ln,
            f[0],
            f[13],
            veg,
            den,
            total > 0,
            np.isfinite(den),
            cnt[16] if counts else None,
        )
        flags[r : r + 100] = fl
        ex = (fl & EXCLUDED) != 0
        un = ~ex & ((fl & MISSING) != 0)

        def area(m):
            return float(m.sum(axis=1) @ areas[r : r + 100])

        for key, m in dict(
            land=ln,
            eligible_land=ln & ~ex & ~un,
            uncertain_land=ln & un,
            excluded_land=ln & ex,
            barren_review_land=ln & ((fl & 256) != 0),
        ).items():
            totals[key] += area(m)
        for key, bit in BITS.items():
            reasons[key] += area(ln & ((fl & bit) != 0))
        print(f"MODIS rows {r + len(ln)}/{H}", flush=True)
    if not counts:
        hdf.end()
    dest.flush()
    flags.flush()
    # Compact global reason raster; no giant cell geometry file.
    with rasterio.open(
        out / "flags.tif",
        "w",
        driver="GTiff",
        width=W,
        height=H,
        count=1,
        dtype="uint16",
        crs="EPSG:4326",
        compress="deflate",
        tiled=True,
        transform=from_origin(-180, 90, DEG, DEG),
    ) as dst:
        for r in range(0, H, 100):
            dst.write(flags[r : r + 100], 1, window=Window(0, r, W, min(100, H - r)))
        dst.update_tags(bits=json.dumps(BITS), policy=json.dumps(POLICY))
    files = {
        n: file_info(out / n)
        for n in ("land.npy", "density.npy", "counts.npy", "flags.npy", "flags.tif")
    }
    atomic_json(
        out / "manifest.json",
        dict(
            status="complete",
            config=config,
            files=files,
            area_km2=totals,
            overlapping_reason_area_km2=reasons,
            seconds=time.perf_counter() - t0,
            limits=[
                "MODIS-only, not complete original v2",
                "0.05 degree pixel-center land mask",
                "Q1 QC=1 not removed from cached counts; QC flags unavailable",
                "C1 fallback is a distinct baseline; no count-based barren rescue"
                if c1
                else "barren rescue is a review flag, not evidence of subpixel location",
            ],
        ),
    )
    print(json.dumps(totals), flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    b = sub.add_parser("public")
    b.add_argument("--natural-earth", type=Path, required=True)
    b.add_argument("--ghsl", type=Path, required=True)
    b.add_argument("--output", type=Path, required=True)
    m = sub.add_parser("mask")
    m.add_argument("--base", type=Path, required=True)
    lc = m.add_mutually_exclusive_group(required=True)
    lc.add_argument("--counts", type=Path)
    lc.add_argument("--mcd12c1", type=Path)
    m.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.command == "public":
        public_inputs(a.natural_earth, a.ghsl, a.output)
    else:
        build_mask(a.base, a.counts, a.mcd12c1, a.output)


if __name__ == "__main__":
    main()
