"""Import terrain artifacts, list runs, and export candidate metadata to Parquet."""

import argparse
import json
import sys
import time
from pathlib import Path

import duckdb

from .database import export_parquet, import_artifacts, list_runs, terrain_selection


def build_parser():
    p = argparse.ArgumentParser(prog="spacethropic-db", description=__doc__)
    p.add_argument("--database", type=Path, required=True, help="local DuckDB file")
    sub = p.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import", help="atomically import one or more CSV/summary pairs")
    imp.add_argument("--pair", nargs=2, action="append", required=True, metavar=("CSV", "SUMMARY"))
    sub.add_parser("list-runs")
    exp = sub.add_parser("export", help="export candidate metadata, including partial cells")
    exp.add_argument("--run-id", required=True)
    exp.add_argument("--resolution", type=int, required=True, choices=range(16))
    exp.add_argument("--output", type=Path, required=True)
    select = sub.add_parser("select-terrain", help="terrain-only diagnostic selection; eligibility remains unknown")
    select.add_argument("--run-id", required=True)
    select.add_argument("--resolution", type=int, required=True, choices=range(16))
    select.add_argument("--columns", nargs="+", required=True, help="original CSV fields; identity always included")
    select.add_argument("--limit", type=int, required=True)
    select.add_argument("--min-exact-coverage", type=float)
    select.add_argument("--min-valid-slope", type=int)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "import":
            args.database.parent.mkdir(parents=True, exist_ok=True)
        with duckdb.connect(str(args.database), read_only=args.command != "import") as conn:
            if args.command == "import":
                print(json.dumps(import_artifacts(conn, args.pair), indent=2))
            elif args.command == "list-runs":
                print(json.dumps([dict(zip(("run_id", "h3_resolution", "n_cells", "n_samples", "complete", "partial"), row))
                                  for row in list_runs(conn)], indent=2))
            elif args.command == "select-terrain":
                started = time.perf_counter()
                relation = terrain_selection(conn, args.run_id, args.resolution, args.columns, args.limit,
                                             args.min_exact_coverage, args.min_valid_slope)
                names = relation.columns
                rows = [dict(zip(names, row)) for row in relation.fetchall()]
                seconds = time.perf_counter() - started
                print(json.dumps({"status": "terrain_only_eligibility_unknown", "mask_version": None,
                                  "query_seconds": seconds, "selected_count": len(rows), "candidates": rows,
                                  "elevation_read_seconds": None, "matcher_seconds": None}, indent=2))
            else:
                print(f"wrote candidate metadata: {export_parquet(conn, args.run_id, args.resolution, args.output)}")
        return 0
    except (ValueError, OSError, duckdb.Error) as exc:
        print(f"spacethropic-db: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
