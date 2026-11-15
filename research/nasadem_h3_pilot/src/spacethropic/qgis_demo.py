"""Build the real Drumheller QGIS layer: terrain selection, eligibility unknown."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import duckdb

from .database import FIELD_TYPES, list_runs, terrain_selection

PILOT = Path(__file__).resolve().parents[2]
GEOMETRY = PILOT / "outputs/n51w113_drumheller_badlands_h3/h3_res8_cells.geojson"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def discover_run(conn, run_id=None):
    """Identify the pilot by source/AOI metadata, independent of artifact bytes."""
    matches = []
    for candidate, resolution, *_ in list_runs(conn):
        if resolution != 8:
            continue
        raw = conn.execute("SELECT run_summary_json FROM terrain_runs WHERE run_id=?", [candidate]).fetchall()[0][0]
        summary = json.loads(raw)
        aoi, source = summary.get("aoi", {}), summary.get("source", {})
        if (aoi.get("name") == "drumheller_badlands"
                and aoi.get("requested_bbox_deg") == {"west": -112.8, "south": 51.4, "east": -112.6, "north": 51.52}
                and summary.get("h3", {}).get("resolution") == 8
                and source.get("collection") == "NASADEM_HGT.001"
                and {g.get("tile_id") for g in source.get("granules", [])} == {"n51w113"}):
            matches.append(candidate)
    if run_id is not None:
        if run_id not in matches:
            raise ValueError(f"Run {run_id} is not a matching Drumheller NASADEM resolution-8 pilot run; use list-runs")
        return run_id
    if not matches:
        raise ValueError("No Drumheller NASADEM resolution-8 pilot run found; import the pilot CSV/summary pair first")
    if len(matches) > 1:
        raise ValueError(f"Multiple Drumheller pilot runs match; specify --run-id explicitly. Matching IDs: {', '.join(matches)}")
    return matches[0]


def create_demo(database, geometry, output, run_id=None):
    """Join database values to existing polygons; never write to source assets."""
    database, geometry, output = map(Path, (database, geometry, output))
    if output.resolve() in (database.resolve(), geometry.resolve()) or output.exists():
        raise ValueError(f"Choose a new output path; refusing to overwrite {output}")
    before = {path: digest(path) for path in (database, geometry)}
    collection = json.loads(geometry.read_text(encoding="utf-8"))
    features = collection["features"]
    ids = [feature["properties"]["h3_cell"] for feature in features]
    if len(features) != 296 or len(set(ids)) != 296:
        raise ValueError("Expected 296 polygons with unique h3_cell values")
    if any(f["geometry"]["type"] != "Polygon" or f["id"] != cell
           for f, cell in zip(features, ids)):
        raise ValueError("Geometry must be H3 polygons with matching feature/property IDs")
    with duckdb.connect(str(database), read_only=True) as conn:
        run_id = discover_run(conn, run_id)
        # Fetch attributes for unselected cells too. No GeoJSON numeric attributes
        # are reused: terrain/coverage values below come exclusively from DuckDB.
        all_cells = terrain_selection(conn, run_id, 8, list(FIELD_TYPES), len(features) + 1)
        columns = all_cells.columns
        rows = [dict(zip(columns, row)) for row in all_cells.fetchall()]
        selected = terrain_selection(conn, run_id, 8, [], 1000,
                                     min_exact_coverage=1, min_valid_slope=1).fetchall()
    by_id = {row["h3_cell"]: row for row in rows}
    selected_ids = {row[0] for row in selected}
    if len(rows) != len(by_id) or set(by_id) != set(ids):
        raise ValueError("Database observations and geometry must match one-to-one")
    if len(selected) != len(selected_ids) or len(selected_ids) != 220 or not selected_ids <= set(ids):
        raise ValueError("Expected 220 unique selected IDs, each matching exactly one polygon")
    output_features = []
    for feature, cell in zip(features, ids):
        properties = {**by_id[cell], "selected_by_terrain_query": cell in selected_ids,
                      "eligibility_status": "unknown"}
        output_features.append({"type": "Feature", "id": cell,
                                "geometry": feature["geometry"], "properties": properties})
    demo = {"type": "FeatureCollection", "name": "Terrain selection - eligibility unknown",
            "bbox": collection["bbox"], "features": output_features,
            "metadata": {"label": "Terrain selection with eligibility unknown",
                         "run_id": run_id, "h3_resolution": 8,
                         "geometry_file": geometry.name, "geometry_sha256": before[geometry],
                         "selection": {"min_exact_coverage": 1, "min_valid_slope": 1, "limit": 1000},
                         "n_polygons": 296, "n_selected": 220, "n_unselected": 76,
                         "coordinates": "WGS 84 longitude, latitude (RFC 7946)",
                         "note": "Full cell polygons; terrain coverage is not land eligibility."}}
    # Round-trip before writing: ensures JSON booleans, finite values and geometry.
    encoded = json.dumps(demo, indent=2, allow_nan=False) + "\n"
    checked = json.loads(encoded)
    assert sum(f["properties"]["selected_by_terrain_query"] is True for f in checked["features"]) == 220
    assert [f["geometry"] for f in checked["features"]] == [f["geometry"] for f in features]
    assert before == {path: digest(path) for path in before}, "Source assets changed"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(encoded)
    return {"output": str(output.resolve()), "run_id": run_id, "polygons": 296, "selected": 220,
            "unselected": 76, "id_join": "one-to-one", "eligibility_status": "unknown"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=PILOT / "local/terrain.duckdb")
    parser.add_argument("--geometry", type=Path, default=GEOMETRY)
    parser.add_argument("--output", type=Path, default=PILOT / "local/drumheller_database_demo.geojson")
    parser.add_argument("--run-id", help="explicit Drumheller res-8 run; required if discovery finds multiple matches")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(create_demo(args.database, args.geometry, args.output, args.run_id), indent=2))
        return 0
    except (ValueError, OSError, duckdb.Error) as exc:
        print(f"spacethropic.qgis_demo: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
