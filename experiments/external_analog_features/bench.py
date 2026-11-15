"""Before/after latency of adding external analog features to the terrain database (small sample).

Run with the terrain pilot's environment, from the repository root:

    research/nasadem_h3_pilot/.venv/Scripts/python.exe experiments/external_analog_features/bench.py \
        --database research/nasadem_h3_pilot/local/external_bench/terrain.duckdb

The source database (Drumheller r6 + r8 import) is copied twice and never modified:
``before.duckdb`` stays as imported, ``after.duckdb`` gets the ext_* tables.
"""
from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
import time
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "research" / "nasadem_h3_pilot" / "src"))
import external_features as ef  # noqa: E402
from spacethropic import database as db  # noqa: E402

COLUMNS = ["centre_lat_deg", "centre_lon_deg", "slope_mean_deg", "coverage_fraction_exact_overlap",
           "coverage_fraction_pixel_centre", "n_valid_slope"]


def timed(fn, repeats: int, warmup: int = 3) -> dict:
    for _ in range(warmup):
        fn()
    ms = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        ms.append((time.perf_counter() - t0) * 1000)
    ms.sort()
    return {"median_ms": round(statistics.median(ms), 3), "p95_ms": round(ms[int(0.95 * (len(ms) - 1))], 3),
            "min_ms": round(ms[0], 3)}


def queries(conn, runs, mode: str | None):
    """The teammates' two read paths, optionally wrapped by the external join (mode live/prejoined)."""
    wrap = (lambda rel: ef.joined_selection(conn, rel, mode)) if mode else (lambda rel: rel)
    out = {}
    for run_id, res in runs:
        out[f"select_terrain_r{res}"] = lambda r=run_id, s=res: wrap(db.terrain_selection(
            conn, r, s, COLUMNS, 1000, min_exact_coverage=1, min_valid_slope=1)).fetchall()
        out[f"candidates_full_r{res}"] = lambda r=run_id, s=res: wrap(db.candidate_relation(conn, r, s)).fetchall()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--database", required=True, type=Path)
    ap.add_argument("--repeats", type=int, default=50)
    ap.add_argument("--out", type=Path, default=HERE / "results")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    before_db, after_db = a.out / "before.duckdb", a.out / "after.duckdb"
    for p in (before_db, after_db):
        p.unlink(missing_ok=True)
        shutil.copyfile(a.database, p)

    report = {"repeats": a.repeats, "duckdb": duckdb.__version__}
    with duckdb.connect(str(before_db)) as conn:
        runs = [(r[0], r[1]) for r in db.list_runs(conn)]
        report["before"] = {k: timed(f, a.repeats) for k, f in queries(conn, runs, None).items()}
        report["before_rows"] = {k: len(f()) for k, f in queries(conn, runs, None).items()}

    t0 = time.perf_counter()
    records = ef.fetch()  # files are cached; this is hashing time, not download time
    report["one_time_fetch_hash_s"] = round(time.perf_counter() - t0, 3)
    with duckdb.connect(str(after_db)) as conn:
        t0 = time.perf_counter()
        report["build"] = ef.build(conn, records=records)
        report["one_time_build_s"] = round(time.perf_counter() - t0, 3)
    report["db_bytes"] = {"before": before_db.stat().st_size, "after": after_db.stat().st_size}

    with duckdb.connect(str(after_db)) as conn:
        for mode in ("live", "prejoined"):
            report[f"after_{mode}"] = {k: timed(f, a.repeats) for k, f in queries(conn, runs, mode).items()}
            report[f"after_{mode}_rows"] = {k: len(f()) for k, f in queries(conn, runs, mode).items()}
        live = {k: sorted(f()) for k, f in queries(conn, runs, "live").items()}
        pre = {k: sorted(f()) for k, f in queries(conn, runs, "prejoined").items()}
        report["live_equals_prejoined"] = live == pre
        rel = ef.joined_selection(conn, db.candidate_relation(conn, runs[-1][0], runs[-1][1]))
        names = rel.columns
        report["after_columns"] = len(names)
        report["before_columns_full"] = len(db.candidate_relation(conn, runs[-1][0], runs[-1][1]).columns)
        i_sa, i_n, i_cell = names.index("sa_cell"), names.index("nasc_tmean"), names.index("h3_cell")
        full = rel.fetchall()
        report["checks"] = {
            "unique_h3_after_join": len({r[i_cell] for r in full}) == len(full),
            "sa_cells_hit": sorted({r[i_sa] for r in full if r[i_sa] is not None}),
            "rows_without_shadowastra": sum(r[i_sa] is None for r in full),
            "rows_without_nasc": sum(r[i_n] is None for r in full),
        }
        sample = rel.select("h3_cell, ext_grid_lat, ext_grid_lon, sa_region, sa_rock_type_glim, sa_mean_slope_deg, "
                            "sa_match_jezero, sa_match_shackleton, nasc_tmean, nasc_d_crater").limit(3).fetchall()
        report["sample_rows"] = [list(map(str, r)) for r in sample]

    report["added_latency_ms_median"] = {
        mode: {k: round(report[f"after_{mode}"][k]["median_ms"] - report["before"][k]["median_ms"], 3)
               for k in report["before"]} for mode in ("live", "prejoined")}
    (a.out / "latency.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
