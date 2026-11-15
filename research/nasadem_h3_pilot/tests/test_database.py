"""Database behavior exercised against checked-in scientific artifacts, without raw ZIPs."""

import csv
import json
from pathlib import Path

import duckdb
import pytest

from spacethropic.database import ImportError, export_parquet, import_artifacts, list_runs
from spacethropic.db_cli import main

ARTIFACTS = Path(__file__).resolve().parents[1] / "outputs/n51w113_drumheller_badlands_h3"


def pair(res):
    return ARTIFACTS / f"h3_res{res}_cells.csv", ARTIFACTS / f"h3_res{res}_run_summary.json"


def altered(tmp_path, *, field=None, value=None, summary_change=None, duplicate=False):
    source, summary = pair(6)
    with source.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields, rows = reader.fieldnames, list(reader)
    if field:
        rows[0][field] = value
    if duplicate:
        rows[-1] = rows[0].copy()
    out = tmp_path / "cells.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    run = json.loads(summary.read_text())
    if summary_change:
        summary_change(run)
    meta = tmp_path / "summary.json"
    meta.write_text(json.dumps(run), encoding="utf-8")
    return out, meta


def test_real_import_idempotency_provenance_and_parquet(tmp_path):
    with duckdb.connect(str(tmp_path / "terrain.duckdb")) as conn:
        imported = import_artifacts(conn, [pair(6), pair(8)])
        assert [r["status"] for r in imported] == ["imported", "imported"]
        assert [r[2:] for r in list_runs(conn)] == [(12, 311040, 1, 11), (296, 311040, 220, 76)]
        again = import_artifacts(conn, [pair(6), pair(8)])
        assert [r["run_id"] for r in again] == [r["run_id"] for r in imported]
        assert all(r["status"] == "existing" for r in again)
        assert conn.execute("SELECT count(*) FROM terrain_observations").fetchone()[0] == 308
        assert conn.execute("SELECT count(*) FROM source_metadata").fetchone()[0] == 1
        for item in imported:
            res, run_id = item["resolution"], item["run_id"]
            stored = conn.execute("SELECT run_summary_json FROM terrain_runs WHERE run_id=?", [run_id]).fetchone()[0]
            assert json.loads(stored) == json.loads(pair(res)[1].read_text())
            output = export_parquet(conn, run_id, res, tmp_path / f"res{res}.parquet")
            parquet = conn.read_parquet(str(output))
            assert parquet.count("*").fetchall()[0][0] == item["rows"]
            with pair(res)[0].open() as f:
                rows = list(csv.DictReader(f))
            samples = [rows[0]]
            if res == 8:
                samples.append(next(r for r in rows if float(r["coverage_fraction_pixel_centre"]) > 1))
                assert json.loads(stored)["results"]["sliver_cells"] == ["8812ebc0e1fffff"]
            for sample in samples:
                result = conn.execute("SELECT * FROM read_parquet(?) WHERE h3_cell=?", [str(output), sample["h3_cell"]])
                got = dict(zip([c[0] for c in result.description], result.fetchone()))
                for key, value in sample.items():
                    if key in ("h3_cell", "coverage_status", "quality_flags", "source_collection", "source_granules"):
                        assert got[key] == value
                    elif key == "is_pentagon":
                        assert got[key] is (value == "True")
                    else:
                        assert got[key] == float(value)
                assert got["eligibility_status"] == "unknown"
                assert got["run_id"] == run_id
                assert got["source_zip_sha256"] == ["a414b5a27c9a66e9c8c28bc5d56bfd46d4ce86b7897a2a48c9be34fadfc9edfa"]
            with pytest.raises(ImportError, match="already exists"):
                export_parquet(conn, run_id, res, output)
        with pytest.raises(ImportError, match="run/resolution not found"):
            export_parquet(conn, imported[0]["run_id"], 8, tmp_path / "wrong.parquet")


def test_null_and_distinct_run_coexist(tmp_path):
    changed = altered(tmp_path, field="slope_mean_deg", value="")
    with duckdb.connect() as conn:
        original = import_artifacts(conn, [pair(6)])[0]
        new = import_artifacts(conn, [changed])[0]
        assert original["run_id"] != new["run_id"]
        assert conn.execute("SELECT count(*) FROM terrain_observations").fetchone()[0] == 24
        output = export_parquet(conn, new["run_id"], 6, tmp_path / "null.parquet")
        assert conn.execute("SELECT count(*) FROM read_parquet(?) WHERE slope_mean_deg IS NULL", [str(output)]).fetchone()[0] == 1


@pytest.mark.parametrize("change,match", [
    ({"field": "h3_cell", "value": "bogus"}, "invalid H3 ID"),
    ({"field": "h3_resolution", "value": "8"}, "resolution mismatch"),
    ({"field": "is_pentagon", "value": "yes"}, "True or False"),
    ({"field": "n_samples", "value": "1.5"}, "integer"),
    ({"field": "slope_mean_deg", "value": "nan"}, "finite"),
    ({"field": "source_granules", "value": "other.zip"}, "granule references"),
    ({"duplicate": True}, "duplicate H3"),
    ({"summary_change": lambda r: r["results"].update(n_cells=13)}, "row count"),
    ({"summary_change": lambda r: r.update(schema="v99")}, "unsupported schema"),
    ({"summary_change": lambda r: r.update(all_checks_passed=False)}, "failed checks"),
])
def test_failed_batch_rolls_back_every_table(tmp_path, change, match):
    bad = altered(tmp_path, **change)
    with duckdb.connect() as conn:
        import_artifacts(conn, [pair(8)])
        before = {table: conn.execute(f"SELECT * FROM {table} ORDER BY ALL").fetchall() for table in
                  ("source_metadata", "run_sources", "terrain_runs", "h3_cells", "terrain_observations")}
        # A valid new run is inserted first; the second pair must undo it too.
        with pytest.raises(ImportError, match=match):
            import_artifacts(conn, [pair(6), bad])
        for table, records in before.items():
            assert conn.execute(f"SELECT * FROM {table} ORDER BY ALL").fetchall() == records


def test_bad_header_and_new_database_rollback(tmp_path):
    cells, summary = altered(tmp_path)
    cells.write_text(cells.read_text().replace("slope_mean_deg", "unexpected", 1))
    with duckdb.connect() as conn:
        with pytest.raises(ImportError, match="CSV columns"):
            import_artifacts(conn, [(cells, summary)])
        assert conn.execute("SHOW TABLES").fetchall() == []


def test_cli_end_to_end_and_actionable_failure(tmp_path, capsys):
    db = str(tmp_path / "cli.duckdb")
    base = ["--database", db]
    assert main([*base, "import", "--pair", *map(str, pair(6))]) == 0
    run_id = json.loads(capsys.readouterr().out)[0]["run_id"]
    assert main([*base, "list-runs"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["n_cells"] == 12
    assert main([*base, "export", "--run-id", run_id, "--resolution", "6", "--output", str(tmp_path / "cli.parquet")]) == 0
    capsys.readouterr()
    assert main([*base, "import", "--pair", "missing.csv", "missing.json"]) == 1
    assert "missing.csv" in capsys.readouterr().err
