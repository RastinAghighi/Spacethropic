"""Versioned local terrain metadata storage. No raw NASADEM ZIP is required."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from pathlib import Path

import duckdb
import h3

SCHEMA = "spacethropic.h3_terrain_cells/v1"
TEXT_FIELDS = "h3_cell coverage_status quality_flags source_collection source_granules".split()
COUNT_FIELDS = "n_samples n_analysis n_excluded_water n_excluded_void n_derivative_missing n_valid_elevation n_valid_slope n_valid_roughness_tri n_valid_roughness_detrended".split()
FLOAT_FIELDS = "centre_lat_deg centre_lon_deg coverage_fraction_exact_overlap coverage_fraction_pixel_centre valid_coverage_fraction cell_area_km2 h3_spherical_cell_area_km2 overlap_area_km2 sampled_area_km2 analysis_area_km2 valid_derivative_area_km2 elevation_mean_m elevation_min_m elevation_max_m slope_mean_deg slope_p50_deg slope_p95_deg roughness_tri_mean_m roughness_detrended_mean_m".split()
# Explicit contract, independent of the first input row and its inferred types.
FIELD_TYPES = {**dict.fromkeys(TEXT_FIELDS, "VARCHAR"), **dict.fromkeys(COUNT_FIELDS, "BIGINT"),
               **dict.fromkeys(FLOAT_FIELDS, "DOUBLE"), "h3_resolution": "INTEGER", "is_pentagon": "BOOLEAN"}
CELL_FIELDS = "h3_cell h3_resolution centre_lat_deg centre_lon_deg is_pentagon".split()
OBS_FIELDS = [k for k in FIELD_TYPES if k not in CELL_FIELDS]


class ImportError(ValueError):
    """An artifact violates the terrain export contract."""


def initialize(conn):
    """Create the milestone schema inside the caller's transaction."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS source_metadata (
            source_id VARCHAR PRIMARY KEY, collection VARCHAR NOT NULL,
            zip_sha256 VARCHAR NOT NULL, metadata_json JSON NOT NULL,
            UNIQUE(collection, zip_sha256));
        CREATE TABLE IF NOT EXISTS terrain_runs (
            run_id VARCHAR PRIMARY KEY, h3_resolution INTEGER NOT NULL,
            csv_sha256 VARCHAR NOT NULL, summary_sha256 VARCHAR NOT NULL,
            csv_path VARCHAR NOT NULL, summary_path VARCHAR NOT NULL,
            run_summary_json JSON NOT NULL);
        CREATE TABLE IF NOT EXISTS run_sources (
            run_id VARCHAR REFERENCES terrain_runs(run_id),
            source_id VARCHAR REFERENCES source_metadata(source_id),
            PRIMARY KEY(run_id, source_id));
    """)
    cols = ", ".join(f'"{k}" {FIELD_TYPES[k]} NOT NULL' for k in CELL_FIELDS)
    conn.execute(f"CREATE TABLE IF NOT EXISTS h3_cells ({cols}, PRIMARY KEY(h3_cell))")
    cols = ", ".join(f'"{k}" {FIELD_TYPES[k]}' for k in OBS_FIELDS)
    conn.execute(f"""CREATE TABLE IF NOT EXISTS terrain_observations (
        run_id VARCHAR REFERENCES terrain_runs(run_id),
        h3_cell VARCHAR REFERENCES h3_cells(h3_cell), {cols},
        PRIMARY KEY(run_id, h3_cell))""")


def _require(ok, message):
    if not ok:
        raise ImportError(message)


def _parse(name, value):
    if name in TEXT_FIELDS:
        return value
    if value == "":
        return None
    if name == "is_pentagon":
        _require(value in ("True", "False"), "is_pentagon must be True or False")
        return value == "True"
    if FIELD_TYPES[name] in ("BIGINT", "INTEGER"):
        _require(bool(re.fullmatch(r"\d+", value)), f"{name} must be a nonnegative integer")
        return int(value)
    number = float(value)
    _require(math.isfinite(number), f"{name} must be finite or blank (NULL)")
    return number


def _close(a, b, label):
    _require(math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-10), f"{label}: {a} differs from {b}")


def read_artifacts(csv_path, summary_path):
    """Strictly type and validate one v1 CSV/summary pair before insertion."""
    csv_path, summary_path = Path(csv_path), Path(summary_path)
    csv_bytes, summary_bytes = csv_path.read_bytes(), summary_path.read_bytes()
    run = json.loads(summary_bytes)
    _require(run["schema"] == SCHEMA, f"unsupported schema; expected {SCHEMA}")
    for key in ("generated_utc", "software", "source", "aoi", "h3", "methodology", "results"):
        _require(bool(run[key]), f"summary.{key} is required")
    for key in ("horizontal_crs", "vertical_datum", "native_sampling"):
        _require(bool(run["source"][key]), f"source.{key} is required")
    for measurement, unit in (("elevation", "m"), ("slope", "degrees"),
                              ("roughness_tri", "m"), ("roughness_detrended", "m")):
        definition = run["methodology"]["measurement_definitions"][measurement]
        _require(definition["units"] == unit and bool(definition["definition"]),
                 f"unexpected units/definition for {measurement}; expected {unit}")
    _require(run["all_checks_passed"] is True, "summary reports failed checks")
    _require(bool(run["conservation_checks"]) and all(c["passed"] is True for c in run["conservation_checks"]),
             "summary conservation checks failed or absent")
    _require(all(r["all_passed"] is True and all(c["passed"] is True for c in r["checks"])
                 for r in run["reconciliation"]), "summary reconciliation failed")
    res = run["h3"]["resolution"]
    _require(type(res) is int and 0 <= res <= 15, "summary H3 resolution must be an integer 0..15")
    source = run["source"]
    granules = source["granules"]
    _require(bool(granules), "source.granules is empty")
    for g in granules:
        _require(bool(re.fullmatch(r"[0-9a-f]{64}", g["zip_sha256"])), "invalid reported ZIP SHA-256")
        _require(g["all_granule_checks_passed"] is True, "source granule checks failed")
    names = {g["zip_file"] for g in granules}
    reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8-sig")))
    _require(reader.fieldnames is not None and len(reader.fieldnames) == len(FIELD_TYPES)
             and set(reader.fieldnames) == set(FIELD_TYPES),
             f"CSV columns must be exactly: {', '.join(FIELD_TYPES)}")
    rows, seen = [], set()
    for line, raw in enumerate(reader, 2):
        try:
            _require(None not in raw and all(v is not None for v in raw.values()), "wrong column count")
            row = {k: _parse(k, v) for k, v in raw.items()}
            cell = row["h3_cell"]
            _require(bool(re.fullmatch(r"[0-9a-f]{15}", cell)) and h3.is_valid_cell(cell), f"invalid H3 ID {cell!r}")
            _require(cell not in seen, f"duplicate H3 cell {cell}")
            seen.add(cell)
            _require(row["h3_resolution"] == res == h3.get_resolution(cell), "H3 resolution mismatch")
            _require(row["is_pentagon"] == h3.is_pentagon(cell), "is_pentagon mismatch")
            lat, lon = h3.cell_to_latlng(cell)
            for key, expected in (("centre_lat_deg", lat), ("centre_lon_deg", lon)):
                _require(row[key] is not None, f"{key} is required")
                _close(row[key], expected, key)
            _require(row["source_collection"] == source["collection"], "source collection mismatch")
            _require(set(row["source_granules"].split(";")) == names, "source granule references mismatch")
            _require(row["coverage_status"] in ("complete", "partial"), "invalid coverage_status")
            for k in COUNT_FIELDS:
                _require(row[k] is not None, f"{k} is required")
            for k in FLOAT_FIELDS[2:11]:
                _require(row[k] is not None and row[k] >= 0, f"{k} must be nonnegative and present")
            _require(row["cell_area_km2"] > 0, "cell_area_km2 must be positive")
            _require(0 <= row["coverage_fraction_exact_overlap"] <= 1, "exact overlap must be in [0,1]")
            _require(row["n_samples"] > 0, "zero-sample slivers belong in run metadata, not observations")
            _require(row["n_samples"] == row["n_analysis"] + row["n_excluded_water"] + row["n_excluded_void"], "sample partition mismatch")
            _require(row["n_valid_elevation"] == row["n_analysis"], "valid elevation count mismatch")
            _require(all(row[k] == row["n_analysis"] - row["n_derivative_missing"] for k in
                         ("n_valid_slope", "n_valid_roughness_tri", "n_valid_roughness_detrended")), "derivative count mismatch")
            for fraction, area in (("coverage_fraction_exact_overlap", "overlap_area_km2"),
                                   ("coverage_fraction_pixel_centre", "sampled_area_km2"),
                                   ("valid_coverage_fraction", "valid_derivative_area_km2")):
                _close(row[fraction], row[area] / row["cell_area_km2"], fraction)
            _require((row["coverage_status"] == "complete") == (row["coverage_fraction_exact_overlap"] >= 1 - 1e-9), "coverage status mismatch")
            rows.append(row)
        except (ValueError, TypeError) as exc:
            raise ImportError(f"CSV line {line}: {exc}") from exc
    totals = run["results"]
    _require(len(rows) == totals["n_cells"] and rows, "CSV row count differs from results.n_cells or is empty")
    for k in ("n_samples", "n_analysis", "n_excluded_water", "n_excluded_void", "n_derivative_missing",
              "sampled_area_km2", "analysis_area_km2", "valid_derivative_area_km2"):
        if k.startswith("n_"):
            _require(type(totals[k]) is int and sum(r[k] for r in rows) == totals[k], f"results.{k} count mismatch")
        else:
            _close(sum(r[k] for r in rows), totals[k], f"results.{k}")
    for status in ("complete", "partial"):
        _require(sum(r["coverage_status"] == status for r in rows) == totals[f"n_cells_{status}"], f"{status} count mismatch")
    _require(len(totals["sliver_cells"]) == totals["n_sliver_cells_without_samples"], "sliver count mismatch")
    _require(all(h3.is_valid_cell(c) and h3.get_resolution(c) == res and c not in seen for c in totals["sliver_cells"]), "invalid sliver IDs")
    _close(sum(r["overlap_area_km2"] for r in rows) + totals["sliver_overlap_area_km2"],
           totals["footprint_area_km2_exact"], "footprint overlap including slivers")
    _close(totals["sampled_area_km2"], run["aoi"]["area_km2"], "AOI area")
    _require(totals["n_samples"] == math.prod(run["aoi"]["shape"]), "AOI shape/sample count mismatch")
    hashes = [hashlib.sha256(b).hexdigest() for b in (csv_bytes, summary_bytes)]
    run_id = hashlib.sha256((SCHEMA + ":" + ":".join(hashes)).encode()).hexdigest()
    return run_id, hashes, run, summary_bytes.decode("utf-8"), rows


def import_artifacts(conn, pairs):
    """Import all supplied pairs in ONE transaction, including schema creation."""
    conn.execute("BEGIN TRANSACTION")
    try:
        initialize(conn)
        results = []
        for csv_path, summary_path in pairs:
            try:
                run_id, hashes, run, raw_summary, rows = read_artifacts(csv_path, summary_path)
                exists = conn.execute("SELECT 1 FROM terrain_runs WHERE run_id = ?", [run_id]).fetchall()
                if not exists:
                    conn.execute("INSERT INTO terrain_runs VALUES (?, ?, ?, ?, ?, ?, ?)",
                                 [run_id, run["h3"]["resolution"], *hashes, str(Path(csv_path).resolve()),
                                  str(Path(summary_path).resolve()), raw_summary])
                    for granule in run["source"]["granules"]:
                        source_id = hashlib.sha256((run["source"]["collection"] + ":" + granule["zip_sha256"]).encode()).hexdigest()
                        conn.execute("INSERT INTO source_metadata VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
                                     [source_id, run["source"]["collection"], granule["zip_sha256"], json.dumps(run["source"])])
                        conn.execute("INSERT INTO run_sources VALUES (?, ?)", [run_id, source_id])
                    for row in rows:
                        conn.execute(f"INSERT INTO h3_cells VALUES ({','.join('?' for _ in CELL_FIELDS)}) ON CONFLICT DO NOTHING",
                                     [row[k] for k in CELL_FIELDS])
                    fields = ["run_id", "h3_cell", *OBS_FIELDS]
                    conn.executemany(f"INSERT INTO terrain_observations ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})",
                                     [[run_id, row["h3_cell"], *[row[k] for k in OBS_FIELDS]] for row in rows])
                results.append({"run_id": run_id, "resolution": run["h3"]["resolution"], "rows": len(rows), "status": "existing" if exists else "imported"})
            except (KeyError, TypeError, ValueError, OSError, duckdb.Error) as exc:
                raise ImportError(f"{csv_path} + {summary_path}: {exc}") from exc
        conn.execute("COMMIT")
        return results
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def list_runs(conn):
    return conn.execute("""SELECT r.run_id, r.h3_resolution, count(*) AS n_cells,
        sum(o.n_samples) AS n_samples,
        count(*) FILTER (WHERE o.coverage_status='complete') AS complete,
        count(*) FILTER (WHERE o.coverage_status='partial') AS partial
        FROM terrain_runs r JOIN terrain_observations o USING(run_id)
        GROUP BY r.run_id, r.h3_resolution ORDER BY r.h3_resolution, r.run_id""").fetchall()


def candidate_relation(conn, run_id, resolution):
    """Production candidate selection, shared by export and the local benchmark."""
    _require(conn.execute("SELECT 1 FROM terrain_runs WHERE run_id=? AND h3_resolution=?", [run_id, resolution]).fetchall(),
             "run/resolution not found; use list-runs and pass its exact run ID and resolution")
    fields = ", ".join(f'c."{k}"' if k in CELL_FIELDS else f'o."{k}"' for k in FIELD_TYPES)
    query = f"""SELECT {fields}, o.run_id, 'unknown' AS eligibility_status,
        r.csv_sha256, r.summary_sha256,
        (SELECT list(s.zip_sha256 ORDER BY s.zip_sha256) FROM run_sources rs
         JOIN source_metadata s USING(source_id) WHERE rs.run_id=o.run_id) AS source_zip_sha256
        FROM terrain_observations o JOIN h3_cells c USING(h3_cell)
        JOIN terrain_runs r USING(run_id) WHERE o.run_id=? AND c.h3_resolution=? ORDER BY c.h3_cell"""
    return conn.sql(query, params=[run_id, resolution])


def terrain_selection(conn, run_id, resolution, columns, limit,
                      min_exact_coverage=None, min_valid_slope=None):
    """Projected, bounded terrain-only handoff; NOT an eligible/matcher selection.

    Caller-chosen diagnostic filters execute in SQL before rows reach Python.
    The actual mask policy and matcher contract must be supplied before either
    can be integrated. Full candidate_relation/export behavior is independent.
    """
    _require(conn.execute("SELECT 1 FROM terrain_runs WHERE run_id=? AND h3_resolution=?",
                          [run_id, resolution]).fetchall(), "run/resolution not found; use list-runs")
    identity = ["h3_cell", "run_id", "h3_resolution"]
    _require(all(k in FIELD_TYPES or k == "run_id" for k in columns),
             "unknown terrain column; use the original CSV field names or run_id")
    _require(type(limit) is int and limit > 0, "limit must be a positive integer")
    fields = list(dict.fromkeys([*identity, *columns]))
    projection = ", ".join(f'{"c" if k in CELL_FIELDS else "o"}."{k}"' for k in fields)
    conditions = ["o.run_id=?", "c.h3_resolution=?"]
    params = [run_id, resolution]
    if min_exact_coverage is not None:
        _require(math.isfinite(min_exact_coverage) and 0 <= min_exact_coverage <= 1,
                 "min_exact_coverage must be finite and in [0,1]")
        conditions.append("o.coverage_fraction_exact_overlap >= ?")
        params.append(min_exact_coverage)
    if min_valid_slope is not None:
        _require(type(min_valid_slope) is int and min_valid_slope >= 0,
                 "min_valid_slope must be a nonnegative integer")
        conditions.append("o.n_valid_slope >= ?")
        params.append(min_valid_slope)
    params.append(limit)
    return conn.sql(f"""SELECT {projection}
        FROM terrain_observations o JOIN h3_cells c USING(h3_cell)
        WHERE {' AND '.join(conditions)} ORDER BY c.h3_cell LIMIT ?""", params=params)


def export_parquet(conn, run_id, resolution, output):
    """Export all cells for an explicit run/resolution; never infer eligibility."""
    relation = candidate_relation(conn, run_id, resolution)
    output = Path(output)
    _require(not output.exists(), f"output already exists: {output}; choose a new path")
    output.parent.mkdir(parents=True, exist_ok=True)
    # DuckDB's relation writer handles path escaping, including Windows paths.
    relation.write_parquet(str(output), compression="zstd")
    return output
