"""Export one cell per site/decision from the observed regression for a small map example."""

import argparse
import json
from pathlib import Path


def export(source, dest):
    data = json.loads(source.read_text())
    selected = {}
    fields = (
        "h3_cell",
        "resolution",
        "site",
        "decision",
        "cell_area_km2",
        "eligible_fraction",
        "uncertain_fraction",
        "excluded_fraction",
        "reason_bits",
        "data_scope",
        "provenance_id",
    )
    for feature in data["features"]:
        p = feature["properties"]
        key = (p["site"], p["decision"])
        if key not in selected:
            selected[key] = dict(
                type="Feature",
                geometry=feature["geometry"],
                properties={k: p[k] for k in fields},
            )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(
            dict(type="FeatureCollection", features=list(selected.values())), indent=2
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    export(a.source, a.output)
