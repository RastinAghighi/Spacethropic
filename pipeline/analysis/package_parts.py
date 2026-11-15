"""Split a finished contour dataset into part folders whose zips are each <= --max-gb.

Each part gets whole tiles (hexes + lines files together), the dataset's README and manifest,
and parts.csv (tile -> part). Part folders are hard links to the original tile files (no extra
disk); each part_NN.zip is written uncompressed (Parquet is already zstd-compressed).

Output: data/export/<dataset>/part_NN/ and data/export/<dataset>/part_NN.zip
Usage: uv run python analysis/package_parts.py data/out/contours_planet/moon_240m_i20m [--max-gb 3]
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", type=Path)
    ap.add_argument("--max-gb", type=float, default=3.0)
    ap.add_argument("--readme", type=Path, help="README to include (default: the dataset's parent README.md)")
    a = ap.parse_args()

    src = a.dataset.resolve()
    manifest = json.loads((src / "manifest.json").read_text())
    if manifest.get("status") != "complete":
        raise SystemExit(f"{src.name} is not complete ({manifest.get('status')}); package it when it finishes")
    readme = a.readme or src.parent / "README.md"
    done = (src / "done.txt").read_text().split()
    limit = a.max_gb * 1e9 * 0.97 - readme.stat().st_size - (src / "manifest.json").stat().st_size - 2e6

    parts: list[list[str]] = [[]]
    used = 0.0
    for tile in done:  # done.txt order = processing order (latitude bands)
        size = sum((src / "tiles" / f"{tile}.{k}.parquet").stat().st_size for k in ("hexes", "lines"))
        if size > limit:
            raise SystemExit(f"tile {tile} alone is {size / 1e9:.2f} GB, over the part limit")
        if parts[-1] and used + size > limit:
            parts.append([])
            used = 0.0
        parts[-1].append(tile)
        used += size

    out = ROOT / "data" / "export" / src.name
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    index = [(t, f"part_{i:02d}") for i, ts in enumerate(parts, 1) for t in ts]
    with open(out / "parts.csv", "w", newline="") as f:
        csv.writer(f).writerows([("tile", "part"), *index])

    for i, tiles in enumerate(parts, 1):
        name = f"part_{i:02d}"
        d = out / name
        (d / "tiles").mkdir(parents=True)
        for tile in tiles:
            for k in ("hexes", "lines"):
                os.link(src / "tiles" / f"{tile}.{k}.parquet", d / "tiles" / f"{tile}.{k}.parquet")
        for extra in (readme, src / "manifest.json", out / "parts.csv"):
            shutil.copy2(extra, d / extra.name)
        (d / "done.txt").write_text("\n".join(tiles) + "\n")
        with zipfile.ZipFile(out / f"{name}.zip", "w", zipfile.ZIP_STORED, allowZip64=True) as z:
            for p in sorted(d.rglob("*")):
                if p.is_file():
                    z.write(p, Path(src.name) / name / p.relative_to(d))
        zsize = (out / f"{name}.zip").stat().st_size
        assert zsize <= a.max_gb * 1e9, (name, zsize)
        print(f"{name}: {len(tiles)} tiles, {zsize / 1e9:.2f} GB -> {out / (name + '.zip')}", flush=True)
    print(f"{src.name}: {len(parts)} parts in {out}", flush=True)


if __name__ == "__main__":
    main()
