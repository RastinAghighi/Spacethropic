"""Zip a finished dataset as ONE file (user 2026-11-15: "we may send in 1 go").

Replaces the dataset's old export: deletes data/export/<dataset>/ (part zips + part folders) and
any old data/export/<dataset>.zip, then writes data/export/<dataset>.zip uncompressed (Parquet is
already zstd-compressed) with the dataset's README, manifest, done.txt and tiles/. Refuses to start
unless the disk has room for the zip plus a margin. Written to .tmp first, then renamed.
Usage: uv run python analysis/zip_single.py data/out/contours_r8_v2/8x_i20m [--readme PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARGIN_GB = 10


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", type=Path)
    ap.add_argument("--readme", type=Path, help="README to include (default: the dataset's parent README.md)")
    ap.add_argument("--prefix", default="", help="zip/export name prefix, e.g. r7_ (folder names repeat across resolutions)")
    a = ap.parse_args()

    src = a.dataset.resolve()
    if json.loads((src / "manifest.json").read_text()).get("status") != "complete":
        raise SystemExit(f"{src.name} is not complete")
    readme = a.readme or src.parent / "README.md"
    files = [readme, src / "manifest.json", src / "done.txt", *sorted((src / "tiles").glob("*.parquet"))]
    size = sum(f.stat().st_size for f in files)

    export = ROOT / "data" / "export"
    name = a.prefix + src.name
    old = [p for p in (export / name, export / f"{name}.zip") if p.exists()]
    freed = sum(f.stat().st_size for p in old for f in ([p] if p.is_file() else p.rglob("*.zip")))
    free = shutil.disk_usage(export).free
    if free + freed < size + MARGIN_GB * 1e9:
        raise SystemExit(f"not enough disk: need {size / 1e9:.1f} GB + {MARGIN_GB} GB margin, "
                         f"have {free / 1e9:.1f} GB (+{freed / 1e9:.1f} GB from the old export)")
    for p in old:
        shutil.rmtree(p) if p.is_dir() else p.unlink()
        print(f"deleted old export {p}", flush=True)

    out = export / f"{name}.zip"
    tmp = out.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
        for f in files:
            arc = Path(src.name) / (f.name if f.parent != src / "tiles" else Path("tiles") / f.name)
            z.write(f, arc)
    os.replace(tmp, out)
    print(f"{out}: {len(files)} files, {out.stat().st_size / 1e9:.2f} GB", flush=True)


if __name__ == "__main__":
    main()
