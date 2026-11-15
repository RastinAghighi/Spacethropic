"""Writers for analysis summaries: full JSON, and long-format CSV for concatenation."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

CSV_FIELDS = (
    "source_file", "tile_id", "aoi_name", "west", "south", "east", "north",
    "exclude_water", "measurement", "statistic", "value", "unit",
)
_SKIP_STAT_KEYS = {"units", "definition", "count_total", "count_excluded"}


def _clean(obj):
    """Make floats JSON-safe (NaN/inf -> null) and round away float noise."""
    if isinstance(obj, float):
        return None if not math.isfinite(obj) else float(f"{obj:.12g}")
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    return obj


def write_json(summary: dict, path: Path) -> Path:
    path.write_text(json.dumps(_clean(summary), indent=2) + "\n", encoding="utf-8")
    return path


def summary_rows(summary: dict) -> list[dict]:
    aoi = summary["aoi"]
    base = {
        "source_file": summary["source_file"],
        "tile_id": summary["granule"]["tile_id"],
        "aoi_name": aoi["name"],
        **aoi["requested_bbox_deg"],
        "exclude_water": summary["parameters"]["exclude_water"],
    }
    rows = []
    for measurement, stats in summary["measurements"].items():
        for key, value in stats.items():
            if key in _SKIP_STAT_KEYS:
                continue
            unit = {"count_valid": "samples", "valid_area_km2": "km2"}.get(key, stats["units"])
            rows.append({**base, "measurement": measurement, "statistic": key, "value": _clean(value), "unit": unit})
    return rows


def write_csv(summary: dict, path: Path) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(summary_rows(summary))
    return path
