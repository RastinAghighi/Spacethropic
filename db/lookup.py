"""
Environment features at any point on Earth, the Moon or Mars, interpolated
from the source grids in grid_points. The grids are small (20k points), so
this answers instantly with no tiling.

    db/.venv/Scripts/python db/lookup.py moon -89.9 0
"""

from __future__ import annotations

import sys
from functools import cache
from pathlib import Path

import duckdb
import numpy as np

from build import NAMES, OF, Grid

DB = Path(__file__).parent / "out" / "analogs.duckdb"


@cache
def grid(body: str) -> Grid:
    con = duckdb.connect(str(DB), read_only=True)
    df = con.execute("SELECT * FROM grid_points WHERE body = ?", [body]).df()
    con.close()
    if df.empty:
        raise ValueError(f"no grid for {body!r}")
    return Grid(df, OF[body])


def point(body: str, lat: float, lon: float) -> dict[str, float | None]:
    """Features at (lat, lon); a feature the body doesn't have is None."""
    v = grid(body)(np.array([float(lat)]), np.array([float(lon)]))
    out = {n: (float(v[n][0]) if n in v and np.isfinite(v[n][0]) else None) for n in NAMES}
    if out["tsurf_max"] is not None and out["tsurf_min"] is not None:
        out["tsurf_range"] = out["tsurf_max"] - out["tsurf_min"]
    return out


if __name__ == "__main__":
    body, lat, lon = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
    for k, v in point(body, lat, lon).items():
        if v is not None:
            print(f"{k:12} {v:12.3f}")
