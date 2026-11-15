"""Small end-to-end benchmark checks; scale runs are explicit manual commands."""

import json

import duckdb
import h3
import pytest

from spacethropic.benchmark import RUN, configured, generate, main
from spacethropic.database import candidate_relation


def test_seeded_generator_uses_production_schema_and_unique_real_cells(tmp_path):
    snapshots = []
    for name, seed in (("a", 123), ("b", 123), ("c", 456)):
        directory = tmp_path/name
        directory.mkdir()
        with configured(directory/"terrain.duckdb", directory/"temp", "256MB", 2) as conn:
            generate(conn, directory, 25, seed)
            relation = candidate_relation(conn, RUN, 6)
            result = conn.execute(relation.sql_query(), [RUN, 6])
            names = [c[0] for c in result.description]
            rows = [dict(zip(names, r)) for r in result.fetchall()]
            assert len(rows) == len({r["h3_cell"] for r in rows}) == 25
            assert all(h3.is_valid_cell(r["h3_cell"]) and r["h3_resolution"] == 6 for r in rows)
            assert {r["coverage_status"] for r in rows} == {"partial", "complete"}
            assert all(r["eligibility_status"] == "unknown" for r in rows)
            assert all(r["source_collection"] == "SYNTHETIC_BENCHMARK" for r in rows)
            snapshots.append(rows)
    assert snapshots[0] == snapshots[1]
    assert snapshots[0] != snapshots[2]


def test_benchmark_command_baseline_and_all_stages(tmp_path):
    directory = tmp_path/"benchmark"
    assert main(["--directory", str(directory), "--rows", "25", "--repeats", "1",
                 "--memory", "256MB", "--threads", "2"]) == 0
    report = json.loads((directory/"results.json").read_text())
    assert [r["n_cells"] for r in report["baseline"]["runs"]] == [12,296]
    size = report["sizes"][0]
    assert size["status"] == "passed"
    for stage in ("query", "read"):
        assert size[stage]["fetched_rows"] == [25,25]
    assert size["verify"]["export_counts"] == [25,25]
    assert size["verify"]["content_differences"] == 0
    assert size["export"]["parquet_bytes"] > 0
    with pytest.raises(SystemExit):
        main(["--directory", str(directory), "--rows", "25"])
