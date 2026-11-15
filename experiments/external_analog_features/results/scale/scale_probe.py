"""Scale probe: build cost, storage and query cost of prejoined vs live join on real r7 cells."""
import os, sys, time, json
from pathlib import Path
import duckdb, h3, numpy as np
HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
import external_features as ef

def run(n_deg):
    db = Path(__file__).parent / f"probe_{n_deg}.duckdb"; db.unlink(missing_ok=True)
    poly = h3.LatLngPoly([(45, -120), (45 + n_deg, -120), (45 + n_deg, -120 + n_deg), (45, -120 + n_deg)])
    cells = sorted(h3.polygon_to_cells(poly, 7))
    ll = np.array([h3.cell_to_latlng(c) for c in cells])
    conn = duckdb.connect(str(db))
    conn.register("c", {"h3_cell": np.array(cells), "centre_lat_deg": ll[:, 0], "centre_lon_deg": ll[:, 1]})
    conn.execute("CREATE TABLE h3_cells AS SELECT * FROM c"); conn.unregister("c")
    conn.execute("CHECKPOINT"); base = db.stat().st_size
    t0 = time.perf_counter(); ef.build(conn); build_s = time.perf_counter() - t0
    conn.execute("CHECKPOINT"); after = db.stat().st_size
    feat_bytes = conn.execute("SELECT sum(total_bytes) FROM (SELECT estimated_size AS total_bytes FROM duckdb_tables() WHERE table_name='ext_h3_features')").fetchone()[0]
    # isolate prejoin table storage: drop it and measure again
    t0 = time.perf_counter(); conn.execute("CREATE OR REPLACE TABLE probe_copy AS SELECT * FROM ext_h3_features"); rebuild_s = time.perf_counter() - t0
    conn.execute("DROP TABLE probe_copy"); conn.execute("DROP TABLE ext_h3_features"); conn.execute("CHECKPOINT")
    no_pre = db.stat().st_size
    conn.execute(f"CREATE TABLE ext_h3_features AS {ef._live_join_sql()} ORDER BY l.h3_cell"); conn.execute("CHECKPOINT")
    with_pre = db.stat().st_size
    terrain = conn.table("h3_cells")
    out = {"cells": len(cells), "build_total_s": round(build_s, 2), "prejoin_rebuild_s": round(rebuild_s, 2),
           "db_before_mb": round(base / 1e6, 1), "db_with_sources_no_prejoin_mb": round(no_pre / 1e6, 1),
           "db_with_prejoin_mb": round(with_pre / 1e6, 1), "prejoin_bytes_per_cell": round((with_pre - no_pre) / len(cells), 1)}
    for label, rel in (("1000_cells", terrain.order("h3_cell").limit(1000)), ("all_cells", terrain)):
        for mode in ("live", "prejoined"):
            ms = []
            for i in range(7):
                t0 = time.perf_counter(); ef.joined_selection(conn, rel, mode).fetchall(); ms.append((time.perf_counter() - t0) * 1000)
            out[f"{label}_{mode}_ms"] = round(sorted(ms[2:])[2], 1)
    conn.close(); db.unlink()
    return out

print(json.dumps([run(2), run(6)], indent=1))
