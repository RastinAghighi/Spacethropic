"""Build pre-joined external feature tables per H3 cell for Earth, the Moon and Mars.

Output: ``out/features.duckdb`` (override with --out), one table per body:

* ``earth_features``: every Earth H3 r7 cell whose centre lies on land kept by the global filter
  (``kept.tif``, 0.05 deg), with ShadowAstra place measurements, the 18 target match scores and
  the 32 nasc layers of the 0.5 deg cell holding the H3 centre.
* ``moon_features`` / ``mars_features``: every H3 cell of the body (no land-cover filter applies)
  with ShadowAstra's terrain-AI Earth twins (ranks 1-5) of the 1 deg cell holding the centre, and
  the nearest ShadowAstra target with its great-circle distance on the body's own radius.

Choices made without the owner (flagged, all CLI options):
* Earth cell kept if the mask pixel at its centre is kept (pixel-centre rule, as main's pilot assigns samples).
* Moon/Mars use H3 resolution 6: its cell area is the closest to Earth r7's 5.161 km^2
  (Moon r6 ~2.69 km^2, Mars r6 ~10.2 km^2, Mars r7 ~1.46 km^2), because H3 fixes a cell count, not a size.

Resumable: cells are generated in batches recorded in ``build_progress``; a rerun skips finished
batches. Run from the repository root with the terrain pilot's environment:

    research/nasadem_h3_pilot/.venv/Scripts/python.exe experiments/external_analog_features/build_features.py \
        --mask pipeline/data/out/global_mask_v2/kept.tif
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import duckdb
import h3
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import external_features as ef  # noqa: E402

RADIUS_KM = {"earth": 6371.0088, "moon": 1737.4, "mars": 3389.5}
MASK_DEG = 0.05
TILE_DEG = 1.0
LOG: Path | None = None


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    if LOG:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def init(conn) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS build_progress (body VARCHAR, batch VARCHAR, cells BIGINT, "
                 "seconds DOUBLE, PRIMARY KEY (body, batch))")
    for body in RADIUS_KM:
        conn.execute(f"CREATE TABLE IF NOT EXISTS {body}_cells (h3_cell VARCHAR, centre_lat_deg DOUBLE, "
                     "centre_lon_deg DOUBLE)")


def done_batches(conn, body: str) -> set[str]:
    return {r[0] for r in conn.execute("SELECT batch FROM build_progress WHERE body=?", [body]).fetchall()}


def insert(conn, body: str, batch: str, cells: list[str], t0: float) -> None:
    if cells:
        ll = np.array([h3.cell_to_latlng(c) for c in cells], dtype=np.float64)
        conn.register("b", {"h3_cell": np.array(cells), "centre_lat_deg": ll[:, 0], "centre_lon_deg": ll[:, 1]})
        conn.execute(f"INSERT INTO {body}_cells SELECT * FROM b")
        conn.unregister("b")
    conn.execute("INSERT INTO build_progress VALUES (?,?,?,?)", [body, batch, len(cells), time.time() - t0])


# ------------------------------------------------------------------ cells
def earth_cells(conn, mask_path: Path, res: int, max_tiles: int | None) -> None:
    kept = np.array(Image.open(mask_path))
    if kept.shape != (3600, 7200):
        raise ValueError(f"unexpected mask shape {kept.shape}; expected the 0.05 deg global grid")
    k = int(TILE_DEG / MASK_DEG)
    any_kept = kept.reshape(180, k, 360, k).any(axis=(1, 3))  # 1 deg tiles holding any kept pixel
    tiles = [(i, j) for i, j in zip(*np.nonzero(any_kept))]
    done = done_batches(conn, "earth")
    todo = [t for t in tiles if f"{t[0]:03d}_{t[1]:03d}" not in done][:max_tiles]
    log(f"earth: {len(tiles)} tiles with kept land, {len(done)} done, {len(todo)} to do this run (r{res})")
    t_start, n_cells = time.time(), 0
    conn.execute("BEGIN")
    for n, (i, j) in enumerate(todo, 1):
        t0 = time.time()
        north, west = 90 - i * TILE_DEG, -180 + j * TILE_DEG
        poly = h3.LatLngPoly([(north, west), (north, west + TILE_DEG), (north - TILE_DEG, west + TILE_DEG),
                              (north - TILE_DEG, west)])
        cand = list(h3.polygon_to_cells(poly, res))
        keep = []
        for c in cand:
            lat, lon = h3.cell_to_latlng(c)
            r = min(int((90 - lat) / MASK_DEG), 3599)
            q = min(int((lon + 180) / MASK_DEG), 7199)
            if kept[r, q]:
                keep.append(c)
        insert(conn, "earth", f"{i:03d}_{j:03d}", keep, t0)
        n_cells += len(keep)
        if n % 200 == 0 or n == len(todo):
            conn.execute("COMMIT")
            el = time.time() - t_start
            log(f"earth: {n}/{len(todo)} tiles, {n_cells:,} kept cells, {el:.0f} s, "
                f"eta {el / n * (len(todo) - n) / 60:.1f} min")
            conn.execute("BEGIN")
    conn.execute("COMMIT")


def planet_cells(conn, body: str, res: int, max_batches: int | None) -> None:
    done = done_batches(conn, body)
    todo = [c for c in sorted(h3.get_res0_cells()) if c not in done][:max_batches]
    log(f"{body}: 122 base cells, {len(done)} done, {len(todo)} to do (r{res}, {h3.get_num_cells(res):,} cells total)")
    t_start, n_cells = time.time(), 0
    for n, base in enumerate(todo, 1):
        t0 = time.time()
        conn.execute("BEGIN")
        cells = list(h3.cell_to_children(base, res))
        insert(conn, body, base, cells, t0)
        conn.execute("COMMIT")
        n_cells += len(cells)
        if n % 10 == 0 or n == len(todo):
            el = time.time() - t_start
            log(f"{body}: {n}/{len(todo)} base cells, {n_cells:,} cells, {el:.0f} s, "
                f"eta {el / n * (len(todo) - n) / 60:.1f} min")


# ------------------------------------------------------------------ features
def load_sources(conn, records: list[dict]) -> None:
    """Source tables (small): ShadowAstra places/scores/twins/targets and nasc, plus provenance."""
    sa = (ef.DATA / "shadowastra").as_posix()
    conn.execute("CREATE OR REPLACE TABLE ext_sources (source_id VARCHAR, file VARCHAR, url VARCHAR, sha256 VARCHAR, "
                 "bytes BIGINT, licence VARCHAR, citation VARCHAR)")
    conn.executemany("INSERT INTO ext_sources VALUES (?,?,?,?,?,?,?)",
                     [[r["source_id"], r["file"], r["url"], r["sha256"], r["bytes"],
                       ef.SOURCES[r["source_id"]]["licence"], ef.SOURCES[r["source_id"]]["citation"]] for r in records])
    cols = [c[0] for c in conn.execute(f"DESCRIBE SELECT * FROM '{sa}/places.parquet'").fetchall()]
    keep = ", ".join(f'"{c}" AS "sa_{c}"' for c in cols if c not in ("lat", "lon"))
    conn.execute(f"""CREATE OR REPLACE TABLE ext_shadowastra_places AS SELECT CAST(lat AS DOUBLE) AS grid_lat,
        CAST(lon AS DOUBLE) AS grid_lon, {keep} FROM '{sa}/places.parquet'""")
    targets = [t[0] for t in conn.execute(f"SELECT DISTINCT target FROM '{sa}/target_scores.parquet' ORDER BY 1").fetchall()]
    wide = ", ".join(f"max(match_score) FILTER (WHERE target='{t}') AS \"sa_match_{t.replace('-', '_')}\"" for t in targets)
    conn.execute(f"CREATE OR REPLACE TABLE ext_shadowastra_scores AS SELECT cell AS sa_cell, {wide} "
                 f"FROM '{sa}/target_scores.parquet' GROUP BY cell")
    nasc = ef._as_arrowless(ef._nasc_table(ef.DATA))
    conn.register("n", nasc)
    conn.execute("CREATE OR REPLACE TABLE ext_nasc_cells AS SELECT * FROM n")
    conn.unregister("n")
    ranks = ", ".join(f"max(earth_cell) FILTER (WHERE rank={r}) AS sa_twin{r}_earth_cell, "
                      f"max(earth_lat) FILTER (WHERE rank={r}) AS sa_twin{r}_earth_lat, "
                      f"max(earth_lon) FILTER (WHERE rank={r}) AS sa_twin{r}_earth_lon" for r in range(1, 6))
    conn.execute(f"""CREATE OR REPLACE TABLE ext_shadowastra_twins AS SELECT body, CAST(lat AS DOUBLE) AS grid_lat,
        CAST(lon AS DOUBLE) AS grid_lon, {ranks} FROM '{sa}/ai_twins.parquet' GROUP BY body, lat, lon""")
    conn.execute(f"CREATE OR REPLACE TABLE ext_shadowastra_targets AS SELECT * FROM read_csv_auto('{sa}/targets.csv')")


def snap(col: str, deg: float) -> str:
    return f"floor({col} / {deg}) * {deg} + {deg / 2}"


def earth_features(conn) -> None:
    conn.execute(f"""CREATE OR REPLACE TABLE earth_features AS
        WITH l AS (SELECT h3_cell, centre_lat_deg, centre_lon_deg, {snap('centre_lat_deg', 0.5)} AS g_lat,
                   {snap('centre_lon_deg', 0.5)} AS g_lon FROM earth_cells)
        SELECT l.h3_cell, l.centre_lat_deg, l.centre_lon_deg, l.g_lat AS ext_grid_lat, l.g_lon AS ext_grid_lon,
               p.* EXCLUDE (grid_lat, grid_lon), s.* EXCLUDE (sa_cell), n.* EXCLUDE (grid_lat, grid_lon)
        FROM l
        LEFT JOIN ext_shadowastra_places p ON l.g_lat = p.grid_lat AND l.g_lon = p.grid_lon
        LEFT JOIN ext_shadowastra_scores s ON p.sa_cell = s.sa_cell
        LEFT JOIN ext_nasc_cells n ON l.g_lat = n.grid_lat AND l.g_lon = n.grid_lon
        ORDER BY l.h3_cell""")


def planet_features(conn, body: str) -> None:
    r = RADIUS_KM[body]
    # nearest ShadowAstra target on the body (haversine on the body's own radius)
    conn.execute(f"""CREATE OR REPLACE TABLE {body}_features AS
        WITH l AS (SELECT h3_cell, centre_lat_deg, centre_lon_deg, {snap('centre_lat_deg', 1.0)} AS g_lat,
                   {snap('centre_lon_deg', 1.0)} AS g_lon FROM {body}_cells),
        t AS (SELECT id, radians(lat) AS la, radians(lon) AS lo FROM ext_shadowastra_targets WHERE body = '{body}'),
        d AS (SELECT h3_cell, arg_min(id, dist) AS nearest_target, min(dist) AS nearest_target_km
              FROM (SELECT l.h3_cell, t.id, 2 * {r} * asin(least(1, sqrt(
                       pow(sin((t.la - radians(l.centre_lat_deg)) / 2), 2) + cos(t.la) * cos(radians(l.centre_lat_deg))
                       * pow(sin((t.lo - radians(l.centre_lon_deg)) / 2), 2)))) AS dist
                    FROM l CROSS JOIN t) x
              GROUP BY h3_cell)
        SELECT l.h3_cell, l.centre_lat_deg, l.centre_lon_deg, l.g_lat AS ext_grid_lat, l.g_lon AS ext_grid_lon,
               w.* EXCLUDE (body, grid_lat, grid_lon), d.nearest_target AS sa_nearest_target,
               d.nearest_target_km AS sa_nearest_target_km
        FROM l
        LEFT JOIN ext_shadowastra_twins w ON w.body = '{body}' AND l.g_lat = w.grid_lat AND l.g_lon = w.grid_lon
        LEFT JOIN d USING (h3_cell)
        ORDER BY l.h3_cell""")


def summarise(conn, body: str) -> dict:
    t = f"{body}_features"
    probe = "sa_cell" if body == "earth" else "sa_twin1_earth_cell"
    n, nulls = conn.execute(f"SELECT count(*), count(*) FILTER (WHERE {probe} IS NULL) FROM {t}").fetchone()
    dup = conn.execute(f"SELECT count(*) - count(DISTINCT h3_cell) FROM {t}").fetchone()[0]
    out = {"rows": n, "rows_without_primary_source": nulls, "duplicate_h3_cells": dup,
           "columns": len(conn.execute(f"DESCRIBE {t}").fetchall())}
    if body == "earth":
        out["rows_without_nasc"] = conn.execute(f"SELECT count(*) FROM {t} WHERE nasc_tmean IS NULL").fetchone()[0]
    return out


def main() -> int:
    global LOG
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mask", type=Path, required=True, help="0.05 deg kept-land GeoTIFF (1 = kept)")
    ap.add_argument("--out", type=Path, default=HERE / "out" / "features.duckdb")
    ap.add_argument("--bodies", nargs="+", default=["earth", "moon", "mars"], choices=list(RADIUS_KM))
    ap.add_argument("--earth-res", type=int, default=7)
    ap.add_argument("--planet-res", type=int, default=6)
    ap.add_argument("--max-batches", type=int, default=None, help="smoke test: stop cell generation after N batches")
    ap.add_argument("--skip-cells", action="store_true", help="only (re)build feature tables from existing cells")
    a = ap.parse_args()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    LOG = a.out.with_suffix(".log")
    conn = duckdb.connect(str(a.out))
    conn.execute("SET preserve_insertion_order = false")
    init(conn)
    t0 = time.time()
    records = ef.fetch()
    load_sources(conn, records)
    log(f"sources loaded ({time.time() - t0:.1f} s)")
    manifest = {"earth_res": a.earth_res, "planet_res": a.planet_res, "mask": str(a.mask.resolve()),
                "mask_rule": "cell kept if the mask pixel at its centre is 1", "bodies": {}}
    for body in a.bodies:
        t1 = time.time()
        if not a.skip_cells:
            if body == "earth":
                earth_cells(conn, a.mask, a.earth_res, a.max_batches)
            else:
                planet_cells(conn, body, a.planet_res, a.max_batches)
        t2 = time.time()
        log(f"{body}: building {body}_features")
        (earth_features if body == "earth" else lambda c: planet_features(c, body))(conn)
        conn.execute("CHECKPOINT")
        s = summarise(conn, body)
        s.update(cells_s=round(t2 - t1, 1), features_s=round(time.time() - t2, 1))
        manifest["bodies"][body] = s
        log(f"{body}: done {json.dumps(s)}")
    conn.execute("CREATE OR REPLACE TABLE build_manifest (json VARCHAR)")
    conn.execute("INSERT INTO build_manifest VALUES (?)", [json.dumps(manifest)])
    conn.close()
    manifest["db_bytes"] = a.out.stat().st_size
    a.out.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log(f"all done in {(time.time() - t0) / 60:.1f} min, {manifest['db_bytes'] / 1e9:.2f} GB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
