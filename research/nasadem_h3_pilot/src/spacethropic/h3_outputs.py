"""Writers for H3 cell results: one-record-per-cell CSV, GeoJSON polygons and the JSON run summary.

GeoJSON follows RFC 7946: WGS 84 longitude/latitude (OGC CRS84) in that order, and
exterior rings closed and counter-clockwise. Run metadata sits in a foreign member
("metadata"), which RFC 7946 section 6.1 permits.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from .outputs import _clean, write_json

GEOJSON_CRS = "OGC CRS84 (WGS 84 longitude, latitude in degrees; RFC 7946 default)"


def record_fields(records: list[dict]) -> list[str]:
    if not records:
        raise ValueError("no cell records to write")
    fields = list(records[0])
    for rec in records:
        if list(rec) != fields:
            raise ValueError(f"record {rec.get('h3_cell')} has different fields")
    return fields


def write_cells_csv(records: list[dict], path: Path) -> Path:
    """One row per cell, in the given (ascending H3 index) order; missing values are empty."""
    fields = record_fields(records)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for rec in records:
            writer.writerow({k: ("" if v is None else v) for k, v in _clean(rec).items()})
    return path


def _ring(lonlat: np.ndarray) -> list[list[float]]:
    pts = [[float(lon), float(lat)] for lon, lat in lonlat]
    return pts + [pts[0]]  # RFC 7946: first and last positions are identical


def cells_feature_collection(result, metadata: dict) -> dict:
    """GeoJSON FeatureCollection with the full H3 cell polygons and per-cell properties."""
    features = []
    for rec, geom in zip(result.records, result.geometries):
        if rec["h3_cell"] != geom.h3_id:
            raise ValueError("records and geometries are out of step")
        features.append({
            "type": "Feature",
            "id": rec["h3_cell"],
            "geometry": {"type": "Polygon", "coordinates": [_ring(geom.boundary_lonlat)]},
            "properties": rec,
        })
    allpts = np.vstack([g.boundary_lonlat for g in result.geometries])
    bbox = [float(allpts[:, 0].min()), float(allpts[:, 1].min()), float(allpts[:, 0].max()), float(allpts[:, 1].max())]
    return {
        "type": "FeatureCollection",
        "bbox": bbox,
        "metadata": {"coordinate_reference": GEOJSON_CRS, "coordinate_order": "[longitude, latitude]", **metadata},
        "features": features,
    }


def write_cells_geojson(result, metadata: dict, path: Path) -> Path:
    path.write_text(json.dumps(_clean(cells_feature_collection(result, metadata))) + "\n", encoding="utf-8")
    return path


def write_run_summary(summary: dict, path: Path) -> Path:
    return write_json(summary, path)
