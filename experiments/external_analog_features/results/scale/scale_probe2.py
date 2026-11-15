import sys, time, json
from pathlib import Path
import duckdb, h3, numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import external_features as ef

def med(fn, n=7):
    ms = []
    for _ in range(n):
        t0 = time.perf_counter(); fn(); ms.append((time.perf_counter() - t0) * 1000)
    return round(sorted(ms)[n // 2], 1)

def run(n_deg):
    db = Path(__file__).parent / f"probe2_{n_deg}.duckdb"; db.unlink(missing_ok=True)
    poly = h3.LatLngPoly([(40, -120), (40 + n_deg, -120), (40 + n_deg, -120 + n_deg), (40, -120 + n_deg)])
    cells = sorted(h3.polygon_to_cells(poly, 7)); ll = np.array([h3.cell_to_latlng(c) for c in cells])
    conn = duckdb.connect(str(db))
    conn.register("c", {"h3_cell": np.array(cells), "centre_lat_deg": ll[:, 0], "centre_lon_deg": ll[:, 1]})
    conn.execute("CREATE TABLE h3_cells AS SELECT * FROM c"); conn.unregister("c")
    ef.build(conn)
    conn.execute("CREATE TABLE sel1000 AS SELECT * FROM h3_cells USING SAMPLE 1000 ROWS (reservoir, 42)")
    out = {"cells": len(cells)}
    for label, tbl in (("1000", "sel1000"), ("all", "h3_cells")):
        for mode in ("live", "prejoined"):
            rel = lambda: ef.joined_selection(conn, conn.table(tbl), mode)
            out[f"{label}_{mode}_db_only_ms"] = med(lambda: rel().aggregate("count(*), sum(sa_mean_slope_deg), sum(nasc_tmean)").fetchall())
            out[f"{label}_{mode}_to_python_ms"] = med(lambda: rel().fetchall())
        out[f"{label}_baseline_to_python_ms"] = med(lambda: conn.table(tbl).fetchall())
    t0 = time.perf_counter(); conn.execute(f"CREATE OR REPLACE TABLE ext_h3_features AS {ef._live_join_sql()} ORDER BY l.h3_cell")
    out["prejoin_rebuild_s"] = round(time.perf_counter() - t0, 3)
    conn.close(); db.unlink()
    return out

print(json.dumps([run(6), run(12)], indent=1))
