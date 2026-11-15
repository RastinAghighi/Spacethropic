"""Discovery must distinguish artifact identities without guessing among runs."""

import json

import duckdb
import pytest

from spacethropic.database import import_artifacts
from spacethropic.qgis_demo import GEOMETRY, create_demo, discover_run, main
from test_database import pair


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "terrain.duckdb"
    with duckdb.connect(str(path)) as conn:
        runs = import_artifacts(conn, [pair(6), pair(8)])
    return path, runs


def test_lf_and_crlf_discover_and_export(tmp_path):
    for newline, name in ((b"\n", "lf"), (b"\r\n", "crlf")):
        directory = tmp_path / name
        directory.mkdir()
        paths = []
        for original in pair(8):
            path = directory / original.name
            path.write_bytes(original.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", newline))
            paths.append(path)
        db = directory / "terrain.duckdb"
        with duckdb.connect(str(db)) as conn:
            run = import_artifacts(conn, [paths])[0]
        result = create_demo(db, GEOMETRY, directory / "demo.geojson")
        assert result["run_id"] == run["run_id"]
        layer = json.loads((directory / "demo.geojson").read_text())
        features = layer["features"]
        assert len(features) == len({f["id"] for f in features}) == 296
        assert sum(f["properties"]["selected_by_terrain_query"] for f in features) == 220
        assert layer["metadata"]["run_id"] == run["run_id"]
        assert all(f["properties"]["run_id"] == run["run_id"] for f in features)


def test_ambiguity_requires_explicit_matching_run(database, tmp_path, capsys):
    db, runs = database
    csv_path, original = pair(8)
    summary = json.loads(original.read_text())
    summary["generated_utc"] = "2026-11-15T12:00:00+00:00"
    changed = tmp_path / "summary.json"
    changed.write_text(json.dumps(summary), encoding="utf-8")
    with duckdb.connect(str(db)) as conn:
        second = import_artifacts(conn, [(csv_path, changed)])[0]
        with pytest.raises(ValueError, match="Multiple Drumheller.*--run-id"):
            discover_run(conn)
        assert discover_run(conn, second["run_id"]) == second["run_id"]
        with pytest.raises(ValueError, match="not a matching"):
            discover_run(conn, runs[0]["run_id"])  # res-6 cannot be chosen
    output = tmp_path / "demo.geojson"
    assert main(["--database", str(db), "--output", str(output)]) == 1
    assert "--run-id" in capsys.readouterr().err and not output.exists()
    assert main(["--database", str(db), "--output", str(output), "--run-id", second["run_id"]]) == 0
    assert json.loads(capsys.readouterr().out)["run_id"] == second["run_id"]


def test_unrelated_res8_is_not_pilot(database):
    db, _ = database
    with duckdb.connect(str(db)) as conn:
        conn.execute("UPDATE terrain_runs SET run_summary_json=json_merge_patch(run_summary_json, ?) WHERE h3_resolution=8",
                     [json.dumps({"aoi": {"name": "another_aoi"}})])
        with pytest.raises(ValueError, match="No Drumheller"):
            discover_run(conn)
