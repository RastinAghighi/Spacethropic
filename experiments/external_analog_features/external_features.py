"""Approach E, first pass: join published analog datasets onto the terrain database's H3 cells.

Nothing is recomputed. Two open datasets that already score Earth for Moon/Mars analog work are
loaded as side tables in the same DuckDB file and linked to every H3 cell by its centre:

* ShadowAstra Atlas (CC BY 4.0): 80,206 land cells, 0.5 deg, measured terrain/climate/surface/EMIT
  minerals/context, plus match scores for 18 Moon and Mars targets.
* Analog Atlas / nasc (MIT): 88,648 land cells, 0.5 deg, 32 NASA POWER / ETOPO1 / solar-geometry /
  geology-distance layers.

Both grids share the same cell centres (x.25 / x.75 deg), so one key links an H3 cell to both:
the 0.5 deg cell holding the H3 cell's centre. The teammates' tables and functions in
research/nasadem_h3_pilot are read, never changed; the new tables are all prefixed ``ext_``.
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
GRID_DEG = 0.5

HF = "https://huggingface.co/datasets/ABRUBAB/shadowastra-atlas/resolve/main/"
NASC = "https://raw.githubusercontent.com/clickTwice26/nasc/claude/vigilant-ride-444dbx/"
SOURCES = {
    "shadowastra": {
        "title": "ShadowAstra Atlas open dataset",
        "licence": "CC BY 4.0",
        "citation": "Team ShadowAstra, ShadowAstra Atlas (NASA Space Apps Challenge 2026)",
        "files": {"places.parquet": HF + "places.parquet", "target_scores.parquet": HF + "target_scores.parquet",
                  "targets.csv": HF + "targets.csv", "ai_twins.parquet": HF + "ai_twins.parquet",
                  "README.md": HF + "README.md"},
    },
    "nasc": {
        "title": "Analog Atlas Earth feature grid (pipeline/build.py output)",
        "licence": "MIT",
        "citation": "Analog Atlas contributors, github.com/clickTwice26/nasc",
        "files": {"earth.bin": NASC + "data/earth.bin", "earth.json": NASC + "data/earth.json",
                  "LICENSE": NASC + "LICENSE"},
    },
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(data_dir: Path = DATA) -> list[dict]:
    """Download missing source files; return one provenance record per file."""
    records = []
    for source_id, src in SOURCES.items():
        folder = data_dir / source_id
        folder.mkdir(parents=True, exist_ok=True)
        for name, url in src["files"].items():
            path = folder / name
            if not path.exists():
                with urllib.request.urlopen(url, timeout=300) as r, open(path.with_suffix(".part"), "wb") as f:
                    f.write(r.read())
                path.with_suffix(".part").replace(path)
            records.append({"source_id": source_id, "file": name, "url": url, "sha256": sha256(path),
                            "bytes": path.stat().st_size})
    return records


def _nasc_table(data_dir: Path) -> dict[str, np.ndarray]:
    """Decode nasc's earth.bin: Uint32 cell index[N], Uint16 feature planes, Uint16 categorical planes."""
    meta = json.loads((data_dir / "nasc" / "earth.json").read_text(encoding="utf-8"))
    n, g = meta["count"], meta["grid"]
    buf = (data_dir / "nasc" / "earth.bin").read_bytes()
    idx = np.frombuffer(buf, "<u4", n, 0)
    off = 4 * n
    cols = {"grid_lat": (g["lat0"] - (idx // g["nx"]) * g["res"]).astype(np.float64),
            "grid_lon": (g["lon0"] + (idx % g["nx"]) * g["res"]).astype(np.float64)}
    for fm in meta["features"]:
        q = np.frombuffer(buf, "<u2", n, off)
        off += 2 * n
        cols["nasc_" + fm["id"]] = (fm["offset"] + q * fm["scale"]).astype(np.float32)
    for name in meta["categorical"]:
        q = np.frombuffer(buf, "<u2", n, off)
        off += 2 * n
        if name == "koppen":  # codes 1..32 index the zone table
            zones = np.array([""] + meta["koppen"], dtype=object)
            cols["nasc_koppen"] = zones[np.clip(q, 0, len(zones) - 1)]
    if off != len(buf):
        raise ValueError(f"earth.bin length {len(buf)} != expected {off}")
    return cols


def build(conn, data_dir: Path = DATA, records: list[dict] | None = None) -> dict:
    """(Re)create the ext_* tables and the H3 link for every cell in h3_cells."""
    records = records if records is not None else fetch(data_dir)
    sa = (data_dir / "shadowastra").as_posix()
    snap = lambda col: f"floor({col} / {GRID_DEG}) * {GRID_DEG} + {GRID_DEG / 2}"
    conn.execute("BEGIN")
    try:
        conn.execute("""CREATE OR REPLACE TABLE ext_sources (source_id VARCHAR, file VARCHAR, url VARCHAR,
            sha256 VARCHAR, bytes BIGINT, licence VARCHAR, citation VARCHAR, loaded_utc VARCHAR)""")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn.executemany("INSERT INTO ext_sources VALUES (?,?,?,?,?,?,?,?)",
                         [[r["source_id"], r["file"], r["url"], r["sha256"], r["bytes"],
                           SOURCES[r["source_id"]]["licence"], SOURCES[r["source_id"]]["citation"], now]
                          for r in records])
        # ShadowAstra: measured columns get an sa_ prefix; the grid key is the cell centre itself.
        cols = [c[0] for c in conn.execute(f"DESCRIBE SELECT * FROM '{sa}/places.parquet'").fetchall()]
        keep = ", ".join(f'"{c}" AS "sa_{c}"' for c in cols if c not in ("lat", "lon"))
        conn.execute(f"""CREATE OR REPLACE TABLE ext_shadowastra_places AS
            SELECT CAST(lat AS DOUBLE) AS grid_lat, CAST(lon AS DOUBLE) AS grid_lon, {keep}
            FROM '{sa}/places.parquet'""")
        # One wide row per cell: match score for every target, so a query never pivots at run time.
        targets = [t[0] for t in conn.execute(
            f"SELECT DISTINCT target FROM '{sa}/target_scores.parquet' ORDER BY target").fetchall()]
        wide = ", ".join(f"max(match_score) FILTER (WHERE target='{t}') AS \"sa_match_{t.replace('-', '_')}\""
                         for t in targets)
        conn.execute(f"""CREATE OR REPLACE TABLE ext_shadowastra_scores AS
            SELECT cell AS sa_cell, {wide} FROM '{sa}/target_scores.parquet' GROUP BY cell""")
        nasc = _nasc_table(data_dir)
        conn.register("nasc_df", _as_arrowless(nasc))
        conn.execute("CREATE OR REPLACE TABLE ext_nasc_cells AS SELECT * FROM nasc_df")
        conn.unregister("nasc_df")
        conn.execute(f"""CREATE OR REPLACE TABLE ext_h3_link AS
            SELECT h3_cell, {snap('centre_lat_deg')} AS grid_lat, {snap('centre_lon_deg')} AS grid_lon
            FROM h3_cells""")
        # Pre-joined variant: one row per H3 cell with every external column. Rebuild after each import.
        conn.execute(f"""CREATE OR REPLACE TABLE ext_h3_features AS
            {_live_join_sql()} ORDER BY l.h3_cell""")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return {"targets": targets, "nasc_rows": len(nasc["grid_lat"]),
            "links": conn.execute("SELECT count(*) FROM ext_h3_link").fetchone()[0]}


def _as_arrowless(cols: dict[str, np.ndarray]):
    """DuckDB can scan a dict of NumPy arrays directly; no pandas/pyarrow needed (not in the lock file)."""
    return {k: (v if v.dtype != object else v.astype(str)) for k, v in cols.items()}


def _live_join_sql() -> str:
    """h3_cell -> every external column, through the 0.5 deg link (LEFT joins: no cell is dropped)."""
    return """SELECT l.h3_cell, l.grid_lat AS ext_grid_lat, l.grid_lon AS ext_grid_lon,
            p.* EXCLUDE (grid_lat, grid_lon), s.* EXCLUDE (sa_cell), n.* EXCLUDE (grid_lat, grid_lon)
        FROM ext_h3_link l
        LEFT JOIN ext_shadowastra_places p ON l.grid_lat = p.grid_lat AND l.grid_lon = p.grid_lon
        LEFT JOIN ext_shadowastra_scores s ON p.sa_cell = s.sa_cell
        LEFT JOIN ext_nasc_cells n ON l.grid_lat = n.grid_lat AND l.grid_lon = n.grid_lon"""


def joined_selection(conn, relation, mode: str = "prejoined"):
    """Left-join external features onto a terrain relation (e.g. database.terrain_selection(...)).

    mode "prejoined": one join against ext_h3_features (built in build()).
    mode "live": the four-table join at query time (always current, slower).
    Cells whose centre falls in no published land cell keep their terrain row with NULL externals.
    """
    ext = conn.table("ext_h3_features") if mode == "prejoined" else conn.sql(_live_join_sql())
    rel = relation.set_alias("t").join(ext.set_alias("x"), "t.h3_cell = x.h3_cell", how="left")
    return rel.select("t.*, x.* EXCLUDE (h3_cell)")
