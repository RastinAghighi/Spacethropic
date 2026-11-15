"""Merge every source into one complete table per site.

Fill order per layer and cell:
  1. measured     the site's primary source
  2. fallback     the next source in sources.REGISTRY that has a value for the cell
  3. interpolated mean of neighbouring cells that are already filled (repeated outward)
  4. physical     a known-absent value (layers.KNOWN_ABSENT), when no source exists for the body
  5. proxy        another layer standing in (layers.PROXIES), when nothing measures it
Every value carries its fill kind in `<layer>__source`.
"""
import json
import subprocess
from datetime import datetime, timezone
from hashlib import sha256

import h3
import numpy as np
import pandas as pd
import yaml

import grid
from config import INTERIM, OUT, RAW, ROOT, Site, settings, sites
from layers import DIMENSIONS, KNOWN_ABSENT, LAYERS, PROXIES
from sources import sources_for


def _interpolate(table: pd.DataFrame, cols: list[str], source: pd.Series) -> None:
    """Fill empty cells from the mean of filled neighbours, one ring at a time (in place)."""
    while True:
        empty = table.index[table[cols].isna().any(axis=1)]
        if empty.empty:
            return
        filled = table[cols].dropna()
        updates = {}
        for cell in empty:
            nbrs = [c for c in h3.grid_ring(cell, 1) if c in filled.index]
            if nbrs:
                updates[cell] = filled.loc[nbrs].mean()
        if not updates:
            return  # isolated from every filled cell; left empty and reported
        for cell, vals in updates.items():
            table.loc[cell, cols] = vals.to_numpy()
            source[cell] = "interpolated"


def merge_site(site: Site) -> tuple[pd.DataFrame, list[dict]]:
    cells = grid.site_cells(site).set_index("cell")
    table = cells.copy()
    coverage = []
    for layer in LAYERS:
        cols = layer.columns()
        values = pd.DataFrame(np.nan, index=cells.index, columns=cols)
        source = pd.Series(pd.NA, index=cells.index, dtype="string")

        srcs = sources_for(site, layer.group)
        for rank, src in enumerate(srcs):
            path = INTERIM / site.id / f"{src.id}.parquet"
            if not path.exists():
                raise SystemExit(f"{path} missing; run `grid {site.id}` first")
            part = pd.read_parquet(path).set_index("cell").reindex(cells.index)
            take = values[cols].isna().all(axis=1) & part[cols].notna().all(axis=1)
            values.loc[take, cols] = part.loc[take, cols]
            source[take] = f"{'measured' if rank == 0 else 'fallback'}:{src.id}"

        if not srcs and (layer.name, site.body.name) in KNOWN_ABSENT:
            v = KNOWN_ABSENT[(layer.name, site.body.name)]
            values[cols] = [0.0 if s == "std" else v for s in layer.stats]
            source[:] = "physical"
        elif not srcs and (layer.name, site.body.name) in PROXIES:
            stand_in = PROXIES[(layer.name, site.body.name)]
            values[cols] = table[[c.replace(layer.name, stand_in, 1) for c in cols]].to_numpy()
            source[:] = f"proxy:{stand_in}"
        else:
            _interpolate(values, cols, source)

        table[cols] = values
        table[f"{layer.name}__source"] = source
        kinds = source.fillna("unfilled").str.split(":").str[0].value_counts()
        coverage.append(
            {
                "site": site.id,
                "body": site.body.name,
                "dimension": layer.dimension,
                "layer": layer.name,
                "status": "implemented",
                "gaps_allowed": layer.allow_gaps,
                "cells": len(cells),
                **{k: int(kinds.get(k, 0)) for k in ("measured", "fallback", "interpolated", "physical", "proxy", "unfilled")},
            }
        )
    return table.reset_index(), coverage


def _pairs() -> pd.DataFrame:
    cfg = yaml.safe_load((ROOT / "pairs.yaml").read_text(encoding="utf-8"))
    true = {(e["earth"], e["target"]): e["basis"] for e in cfg["true_edges"]}
    earth = [s for s in sites().values() if s.body.name == "earth"]
    targets = [s for s in sites().values() if s.body.name != "earth"]
    return pd.DataFrame(
        [
            {"earth": e.id, "target": t.id, "target_body": t.body.name, "true": (e.id, t.id) in true, "basis": true.get((e.id, t.id), "")}
            for e in earth
            for t in targets
        ]
    )


def _git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def merge_all(selected: list[Site]) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    coverage, manifest_sites = [], {}
    for site in selected:
        table, cov = merge_site(site)
        table.to_parquet(OUT / f"{site.id}.parquet", index=False)
        coverage += cov
        manifest_sites[site.id] = {
            "body": site.body.name,
            "lat": site.lat,
            "lon": site.lon,
            "radius_km": site.radius_km,
            "h3_res": site.body.h3_res,
            "cells": len(table),
            "sources": {
                src.id: {
                    "product": src.product,
                    "native_res": src.native_res,
                    **json.loads((RAW / site.id / f"{src.id}.json").read_text(encoding="utf-8")),
                }
                for g in {l.group for l in LAYERS}
                for src in sources_for(site, g)
            },
        }

    cov = pd.DataFrame(coverage)
    implemented = {l.dimension for l in LAYERS}
    cell_counts = {r["site"]: r["cells"] for r in coverage}
    kinds = ("measured", "fallback", "interpolated", "physical", "proxy")
    missing_dims = [
        # No layers exist yet, so every cell is unfilled for this dimension.
        {"site": s.id, "body": s.body.name, "dimension": d, "layer": DIMENSIONS[d], "status": "not_implemented",
         "gaps_allowed": False, "cells": cell_counts[s.id], **dict.fromkeys(kinds, 0), "unfilled": cell_counts[s.id]}
        for s in selected
        for d in DIMENSIONS
        if d not in implemented
    ]
    pd.concat([cov, pd.DataFrame(missing_dims)], ignore_index=True).sort_values(["site", "dimension", "layer"]).to_csv(OUT / "coverage.csv", index=False)
    _pairs().to_csv(OUT / "pairs.csv", index=False)

    lock = ROOT / "uv.lock"
    (OUT / "manifest.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "git_commit": _git_commit(),
                "uv_lock_sha256": sha256(lock.read_bytes()).hexdigest() if lock.exists() else None,
                "settings": settings(),
                "sites": manifest_sites,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(cov.to_string(index=False))
    allowed = int(cov.loc[cov["gaps_allowed"], "unfilled"].sum())
    if allowed:
        print(f"\n{allowed} cell-layer values left empty in gap-allowed layers (expected); see coverage.csv")
    unfilled = int(cov.loc[~cov["gaps_allowed"], "unfilled"].sum())
    if unfilled:
        print(f"\n{unfilled} cell-layer values could not be filled; see coverage.csv")
        return 1
    return 0
