"""Stream all H3 children of disjoint parents, checkpointing one Parquet per parent."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

import h3
import numpy as np
import psutil
import pyarrow as pa
import pyarrow.parquet as pq
from core import BITS, POLICY, Mask, atomic_json, digest, evaluate


def schema():
    fields = [
        ("h3_cell", pa.string()),
        ("resolution", pa.int8()),
        ("decision", pa.string()),
        ("reason_bits", pa.uint16()),
        ("sample_count", pa.int32()),
        ("provenance_id", pa.string()),
    ]
    fields += [
        (k, pa.bool_())
        for k in ("baseline_kept", "mixed_cell", "near_threshold", "barren_in_removed")
    ]
    fields += [
        (k, pa.float64())
        for k in (
            "latitude",
            "longitude",
            "cell_area_km2",
            "land_fraction",
            "eligible_fraction",
            "uncertain_fraction",
            "excluded_fraction",
            "class_observed_fraction",
            "population_observed_fraction",
            "population_density_observed_mean",
            "quadrature_area_error",
        )
    ]
    fields += [(f"lc_{i:02d}_fraction", pa.float32()) for i in range(17)]
    fields += [
        (f"group_{k}_fraction", pa.float32())
        for k in ("water", "built", "vegetation", "other")
    ]
    fields += [(f"reason_{k}_fraction", pa.float32()) for k in BITS]
    return pa.schema(fields)


@contextmanager
def run_lock(out):
    """OS lock is automatically released on process exit, including crashes."""
    path = out / ".lock"
    with open(path, "a+b") as f:
        if f.tell() == 0:
            f.write(b"0")
            f.flush()
        f.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            f.seek(0)
            if os.name == "nt":
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f, fcntl.LOCK_UN)


def parent_ids(resolution):
    return sorted(
        c for base in h3.get_res0_cells() for c in h3.cell_to_children(base, resolution)
    )


def process_partition(
    parent, resolution, sampler, out, subdivisions, margin, batch_size
):
    started = time.perf_counter()
    cells = sorted(h3.cell_to_children(parent, resolution))
    path = out / "cells" / f"parent={parent}" / "part-0.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    counts = Counter()
    areas = Counter()
    max_error, peak_rss, buffer = 0.0, 0, []
    with pq.ParquetWriter(tmp, schema(), compression="zstd") as writer:
        for index, cell in enumerate(cells):
            row = evaluate(cell, sampler, subdivisions, margin)
            counts[row["decision"]] += 1
            a = row["cell_area_km2"]
            areas["whole_cells"] += a
            areas["sampled_land"] += a * row["land_fraction"]
            for key in ("eligible", "uncertain", "excluded"):
                areas[f"sampled_{key}"] += a * row[f"{key}_fraction"]
            if row["decision"] != "excluded":
                buffer.append(row)
                areas["candidate_whole_cells"] += a
            max_error = max(max_error, row["quadrature_area_error"])
            if (index + 1) % batch_size == 0:
                if buffer:
                    writer.write_table(pa.Table.from_pylist(buffer, schema=schema()))
                    buffer.clear()
                peak_rss = max(peak_rss, psutil.Process().memory_info().rss)
            if (index + 1) % 1000 == 0:
                print(f"{parent}: {index + 1}/{len(cells)} cells", flush=True)
        if buffer:
            writer.write_table(pa.Table.from_pylist(buffer, schema=schema()))
    os.replace(tmp, path)
    stats = dict(
        parent=parent,
        evaluated=len(cells),
        candidates=counts["eligible"] + counts["uncertain"],
        counts=dict(counts),
        area_km2=dict(areas),
        max_area_relative_error=max_error,
        seconds=time.perf_counter() - started,
        peak_rss_bytes=max(peak_rss, psutil.Process().memory_info().rss),
        parquet=dict(
            path=str(path.relative_to(out)),
            sha256=digest(path),
            bytes=path.stat().st_size,
        ),
    )
    # Commit marker last. A crash before this safely recomputes only this partition.
    atomic_json(out / "checkpoints" / f"{parent}.json", stats)
    return stats


def execute(
    sampler,
    out,
    resolution=7,
    parent_resolution=3,
    subdivisions=8,
    margin=0.01,
    batch_size=256,
    parents=None,
    limit=None,
    min_free_gb=5,
):
    if (
        not 0 <= parent_resolution <= resolution <= 9
        or resolution - parent_resolution > 4
    ):
        raise ValueError(
            "Require 0<=parent<=resolution<=9 and at most 4 levels per partition"
        )
    if (
        not 1 <= batch_size <= 10000
        or not 1 <= subdivisions <= 32
        or not 0 <= margin <= 0.1
    ):
        raise ValueError("Invalid batch size, subdivision count, or uncertainty margin")
    plan = (
        sorted(set(parents)) if parents is not None else parent_ids(parent_resolution)
    )
    if not plan or any(
        not h3.is_valid_cell(p) or h3.get_resolution(p) != parent_resolution
        for p in plan
    ):
        raise ValueError("Invalid or empty parent list")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    config = dict(
        resolution=resolution,
        parent_resolution=parent_resolution,
        subdivisions=subdivisions,
        threshold_margin=margin,
        batch_size=batch_size,
        input_id=sampler.source_id,
        input_kind=getattr(sampler, "source_kind", "test_or_custom"),
        policy=POLICY,
        parent_ids=plan,
        source_hashes={
            name: digest(Path(__file__).with_name(name))
            for name in ("core.py", "run.py")
        },
        software=dict(
            python=platform.python_version(),
            h3=h3.__version__,
            numpy=np.__version__,
            pyarrow=pa.__version__,
        ),
    )
    with run_lock(out):
        mp = out / "manifest.json"
        if mp.exists() and json.loads(mp.read_text())["config"] != config:
            raise ValueError(
                "Run configuration/code/input changed; use a new output directory"
            )
        records, todo = [], []
        for parent in plan:
            cp = out / "checkpoints" / f"{parent}.json"
            if cp.exists():
                rec = json.loads(cp.read_text())
                pp = out / rec["parquet"]["path"]
                if not pp.exists() or digest(pp) != rec["parquet"]["sha256"]:
                    raise ValueError(
                        f"Checkpoint data corrupt: {parent}; restore file or remove its checkpoint to recompute"
                    )
                if pq.ParquetFile(pp).metadata.num_rows != rec["candidates"]:
                    raise ValueError("Parquet row count mismatch")
                records.append(rec)
            else:
                todo.append(parent)
        atomic_json(
            mp,
            dict(
                status="running",
                config=config,
                partitions_complete=len(records),
                partitions_total=len(plan),
            ),
        )
        ran = 0
        for parent in todo:
            if limit is not None and ran >= limit:
                break
            if shutil.disk_usage(out).free < min_free_gb * 1e9:
                print(
                    "Stopping at checkpoint: free disk below configured minimum",
                    flush=True,
                )
                break
            rec = process_partition(
                parent, resolution, sampler, out, subdivisions, margin, batch_size
            )
            records.append(rec)
            ran += 1
            print(
                f"Completed {len(records)}/{len(plan)}; {rec['candidates']} candidates; {rec['seconds']:.2f}s",
                flush=True,
            )
        totals, areas = Counter(), Counter()
        for rec in sorted(records, key=lambda r: r["parent"]):
            totals.update(rec["counts"])
            areas.update(rec["area_km2"])
        done = len(records) == len(plan)
        full_globe = parents is None
        evaluated = sum(r["evaluated"] for r in records)
        if done and full_globe and evaluated != h3.get_num_cells(resolution):
            raise AssertionError("Incomplete or duplicated global H3 enumeration")
        manifest = dict(
            status="complete" if done else "partial",
            scope="global" if full_globe else "selected_parents",
            config=config,
            partitions_complete=len(records),
            partitions_total=len(plan),
            evaluated_cells=evaluated,
            candidate_cells=sum(r["candidates"] for r in records),
            counts=dict(totals),
            area_km2=dict(areas),
            storage_bytes=sum(r["parquet"]["bytes"] for r in records),
            processing_seconds=sum(r["seconds"] for r in records),
            peak_rss_bytes=max([r["peak_rss_bytes"] for r in records], default=0),
            max_area_relative_error=max(
                [r["max_area_relative_error"] for r in records], default=0
            ),
            area_note="whole-cell footprints are not eligible land; sampled fractions approximate the coarse raster",
            contours="candidate boundaries implicit in H3; elevation contours are optional and separate",
        )
        atomic_json(mp, manifest)
        print(
            json.dumps({k: v for k, v in manifest.items() if k != "config"}, indent=2)
        )
        return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mask", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--resolution", type=int, default=7)
    p.add_argument("--parent-resolution", type=int, default=3)
    p.add_argument("--subdivisions", type=int, default=8)
    p.add_argument("--threshold-margin", type=float, default=0.01)
    p.add_argument("--batch-size", type=int, default=256)
    p.add_argument("--parents", help="comma-separated parent H3 ids (benchmark/subset)")
    p.add_argument(
        "--limit",
        type=int,
        help="process at most this many unfinished partitions, then exit",
    )
    p.add_argument("--min-free-gb", type=float, default=5)
    a = p.parse_args()
    execute(
        Mask(a.mask),
        a.output,
        a.resolution,
        a.parent_resolution,
        a.subdivisions,
        a.threshold_margin,
        a.batch_size,
        a.parents.split(",") if a.parents else None,
        a.limit,
        a.min_free_gb,
    )


if __name__ == "__main__":
    main()
