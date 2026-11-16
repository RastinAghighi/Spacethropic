"""Optional bounded local-DEM contour stage keyed by candidate H3 ID.

Adapted from contours_r8.py (475bf4e), separate from eligibility: no DEM never
removes a candidate. One input Parquet partition and a local DEM per invocation.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from collections import Counter
from pathlib import Path

import contourpy
import h3
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import rasterio
from core import atomic_json, digest
from pyproj import Transformer
from rasterio.features import geometry_mask
from rasterio.windows import Window, from_bounds
from run import run_lock

LINE_SCHEMA = pa.schema(
    [
        ("h3_cell", pa.string()),
        ("resolution", pa.int8()),
        ("level_m", pa.float64()),
        ("closed", pa.bool_()),
        ("x", pa.list_(pa.float64())),
        ("y", pa.list_(pa.float64())),
    ]
)
COVER_SCHEMA = pa.schema(
    [
        ("h3_cell", pa.string()),
        ("status", pa.string()),
        ("valid_pixels", pa.int32()),
        ("lines", pa.int32()),
    ]
)


def contours_for_cell(src, cell, interval):
    boundary = h3.cell_to_boundary(cell)
    # Local DEM operation: polar/date-line cells are explicit pending coverage,
    # not sent through a planar polygon that spans the globe.
    if np.ptp([lo for _, lo in boundary]) > 180:
        return [], dict(
            h3_cell=cell, status="needs_polar_or_dateline_dem", valid_pixels=0, lines=0
        )
    tr = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
    xy = [tr.transform(lo, la) for la, lo in boundary]
    xs, ys = np.asarray(xy).T
    w = from_bounds(xs.min(), ys.min(), xs.max(), ys.max(), src.transform)
    c0, r0 = math.floor(w.col_off) - 1, math.floor(w.row_off) - 1
    c1, r1 = math.ceil(w.col_off + w.width) + 1, math.ceil(w.row_off + w.height) + 1
    c0, r0, c1, r1 = max(c0, 0), max(r0, 0), min(c1, src.width), min(r1, src.height)
    if c0 >= c1 or r0 >= r1:
        return [], dict(h3_cell=cell, status="no_dem_coverage", valid_pixels=0, lines=0)
    if (r1 - r0) * (c1 - c0) > 4_000_000:
        raise ValueError("Cell DEM window exceeds 4 million pixels; use a coarser DEM")
    window = Window(c0, r0, c1 - c0, r1 - r0)
    z = src.read(1, window=window, masked=True).astype(np.float64)
    t = src.window_transform(window)
    inside = geometry_mask(
        [dict(type="Polygon", coordinates=[xy + xy[:1]])],
        out_shape=z.shape,
        transform=t,
        invert=True,
    )
    valid = inside & ~np.ma.getmaskarray(z) & np.isfinite(z.data)
    count = int(valid.sum())
    lines = []
    if count and min(z.shape) >= 2:
        x = t.c + (np.arange(z.shape[1]) + 0.5) * t.a
        y = t.f + (np.arange(z.shape[0]) + 0.5) * t.e
        levels = np.arange(
            math.ceil(z.data[valid].min() / interval) * interval,
            z.data[valid].max(),
            interval,
        )
        if len(levels) > 10000:
            raise ValueError(
                "Over 10000 contour levels per cell; increase interval or check DEM units"
            )
        gen = contourpy.contour_generator(
            x=x, y=y, z=np.ma.array(z.data, mask=~valid), line_type="Separate"
        )
        for level in levels:
            for line in gen.lines(float(level)):
                if len(line) > 1:
                    lines.append(
                        dict(
                            h3_cell=cell,
                            resolution=h3.get_resolution(cell),
                            level_m=float(level),
                            closed=bool(np.array_equal(line[0], line[-1])),
                            x=line[:, 0].tolist(),
                            y=line[:, 1].tolist(),
                        )
                    )
    status = "covered" if count else "no_valid_dem"
    # Raster edge clipping may leave only partial cell coverage.
    if count and (
        w.col_off < 0
        or w.row_off < 0
        or w.col_off + w.width > src.width
        or w.row_off + w.height > src.height
    ):
        status = "partial_dem_coverage"
    return lines, dict(
        h3_cell=cell, status=status, valid_pixels=count, lines=len(lines)
    )


def execute(cells, dem, output, interval=20):
    if interval <= 0:
        raise ValueError("Contour interval must be positive")
    config = dict(
        cells_sha256=digest(cells),
        dem_sha256=digest(dem),
        interval_m=interval,
        code_sha256=digest(__file__),
    )
    output.mkdir(parents=True, exist_ok=True)
    with run_lock(output):
        mp = output / "manifest.json"
        if mp.exists():
            old = json.loads(mp.read_text())
            if old["config"] != config:
                raise ValueError("Changed contour inputs; use a new output directory")
            if old["status"] == "complete":
                for name, sha in old["files"].items():
                    if digest(output / name) != sha:
                        raise ValueError("Corrupt contour output")
                return old
        atomic_json(mp, dict(status="running", config=config))
        start = time.perf_counter()
        counts = Counter()
        nlines = 0
        with (
            rasterio.open(dem) as src,
            pq.ParquetWriter(
                output / "lines.tmp", LINE_SCHEMA, compression="zstd"
            ) as writer,
            pq.ParquetWriter(
                output / "coverage.tmp", COVER_SCHEMA, compression="zstd"
            ) as coverage_writer,
        ):
            if (
                not src.crs
                or src.transform.b
                or src.transform.d
                or src.transform.a <= 0
                or src.transform.e >= 0
            ):
                raise ValueError("Expected georeferenced north-up DEM in meters")
            crs = src.crs.to_wkt()
            for batch in pq.ParquetFile(cells).iter_batches(batch_size=128):
                for row in batch.to_pylist():
                    if row.get("decision") == "excluded":
                        continue
                    lines, coverage = contours_for_cell(src, row["h3_cell"], interval)
                    counts[coverage["status"]] += 1
                    nlines += len(lines)
                    if lines:
                        writer.write_table(
                            pa.Table.from_pylist(lines, schema=LINE_SCHEMA)
                        )
                    coverage_writer.write_table(
                        pa.Table.from_pylist([coverage], schema=COVER_SCHEMA)
                    )
        for name in ("lines", "coverage"):
            os.replace(output / f"{name}.tmp", output / f"{name}.parquet")
        result = dict(
            status="complete",
            config=config,
            coverage=dict(counts),
            lines=nlines,
            coordinate_crs_wkt=crs,
            z_units="meters; caller must verify source vertical datum",
            seconds=time.perf_counter() - start,
            files={
                name: digest(output / name)
                for name in ("lines.parquet", "coverage.parquet")
            },
            limits=[
                "masked DEM pixel centers; no interpolation across missing data",
                "partial coverage does not remove candidate",
                "local DEM only; polar/date-line needs dedicated mosaic",
            ],
        )
        atomic_json(mp, result)
        print(json.dumps(result, indent=2))
        return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cells", type=Path, required=True)
    p.add_argument("--dem", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--interval", type=float, default=20)
    a = p.parse_args()
    execute(a.cells, a.dem, a.output, a.interval)
