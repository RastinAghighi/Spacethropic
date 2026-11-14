"""Pipeline CLI.

    uv run python run.py download <site|all>   fetch each source onto the site-local grid
    uv run python run.py grid <site|all>       per-cell statistics for each source
    uv run python run.py merge                 fill gaps, write data/out/
    uv run python run.py all <site|all>        all three in order
"""
import argparse
import json
import sys

import rasterio

import grid
from config import INTERIM, RAW, Site, select, sites
from aggregate import aggregate
from features import EXTRACTORS
from layers import LAYERS
from merge import merge_all
from sources import sources_for

GROUPS = sorted({l.group for l in LAYERS})


def download(site: Site, force: bool) -> None:
    for group in GROUPS:
        for src in sources_for(site, group):
            tif, meta = RAW / site.id / f"{src.id}.tif", RAW / site.id / f"{src.id}.json"
            if tif.exists() and meta.exists() and not force:
                print(f"[{site.id}] {src.id}: cached")
                continue
            print(f"[{site.id}] {src.id}: fetching {src.product}")
            info = src.fetch(site, tif)
            meta.write_text(json.dumps(info, indent=2), encoding="utf-8")
            print(f"[{site.id}] {src.id}: {info['valid_fraction']:.1%} of grid has data")


def grid_site(site: Site) -> None:
    cells = grid.site_cells(site)
    for group in GROUPS:
        for src in sources_for(site, group):
            tif = RAW / site.id / f"{src.id}.tif"
            if not tif.exists():
                raise SystemExit(f"{tif} missing; run `download {site.id}` first")
            with rasterio.open(tif) as r:
                features = EXTRACTORS[group](r.read(1), r.transform.a)
                table = aggregate(site, cells, features, r.transform)
            out = INTERIM / site.id / f"{src.id}.parquet"
            out.parent.mkdir(parents=True, exist_ok=True)
            table.to_parquet(out, index=False)
            print(f"[{site.id}] {src.id}: {len(table)} cells")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["download", "grid", "merge", "all"])
    p.add_argument("site", nargs="?", default="all", help=f"all or one of: {', '.join(sites())}")
    p.add_argument("--force", action="store_true", help="re-download even if cached")
    args = p.parse_args()
    selected = select(args.site)

    if args.command in ("download", "all"):
        for s in selected:
            download(s, args.force)
    if args.command in ("grid", "all"):
        for s in selected:
            grid_site(s)
    if args.command in ("merge", "all"):
        return merge_all(selected)
    return 0


if __name__ == "__main__":
    sys.exit(main())
