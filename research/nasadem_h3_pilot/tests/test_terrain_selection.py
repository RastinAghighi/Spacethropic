"""Real terrain-only handoff tests; no invented eligibility or matcher fixture."""

import json

import duckdb
import pytest

from spacethropic.database import ImportError, import_artifacts, terrain_selection
from spacethropic.db_cli import main
from test_database import pair


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "terrain.duckdb"
    with duckdb.connect(str(path)) as conn:
        runs = import_artifacts(conn, [pair(6), pair(8)])
    return path, runs


def test_real_sql_projection_filters_and_limit(database):
    path, runs = database
    with duckdb.connect(str(path), read_only=True) as conn:
        for run, expected in zip(runs, [1, 220]):
            relation = terrain_selection(conn, run["run_id"], run["resolution"],
                                         ["slope_mean_deg", "coverage_fraction_pixel_centre"], 1000, 1, 1)
            assert relation.columns == ["h3_cell", "run_id", "h3_resolution", "slope_mean_deg", "coverage_fraction_pixel_centre"]
            rows = relation.fetchall()
            assert len(rows) == expected == len({r[0] for r in rows})
            if run["resolution"] == 6:
                assert rows[0][0] == "8612ebc77ffffff"
            else:
                assert any(r[-1] > 1 for r in rows)
            bounded = terrain_selection(conn, run["run_id"], run["resolution"], [], 1, 1, 1).fetchall()
            assert bounded == [rows[0][:3]]
        assert terrain_selection(conn, runs[0]["run_id"], 6, [], 10, 1, 1000000).fetchall() == []


@pytest.mark.parametrize("kwargs,match", [
    ({"columns": ["not_a_column"]}, "unknown terrain column"),
    ({"columns": ['h3_cell; DROP TABLE h3_cells']}, "unknown terrain column"),
    ({"limit": 0}, "positive integer"),
    ({"min_exact_coverage": 1.1}, r"\[0,1\]"),
    ({"min_exact_coverage": float('nan')}, "finite"),
    ({"min_valid_slope": -1}, "nonnegative integer"),
    ({"resolution": 8}, "run/resolution not found"),
])
def test_invalid_selection(database, kwargs, match):
    path, runs = database
    arguments = dict(run_id=runs[0]["run_id"], resolution=6, columns=[], limit=10)
    arguments.update(kwargs)
    with duckdb.connect(str(path), read_only=True) as conn:
        with pytest.raises(ImportError, match=match):
            terrain_selection(conn, **arguments)


def test_cli_reports_terrain_only_and_preserves_identity(database, capsys):
    path, runs = database
    assert main(["--database", str(path), "select-terrain", "--run-id", runs[0]["run_id"],
                 "--resolution", "6", "--columns", "slope_mean_deg", "--limit", "10",
                 "--min-exact-coverage", "1", "--min-valid-slope", "1"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "terrain_only_eligibility_unknown"
    assert report["mask_version"] is None
    assert report["selected_count"] == 1
    assert report["candidates"][0] == {"h3_cell": "8612ebc77ffffff", "run_id": runs[0]["run_id"],
                                        "h3_resolution": 6, "slope_mean_deg": 6.86219659371}
    assert report["elevation_read_seconds"] is None and report["matcher_seconds"] is None
