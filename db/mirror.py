"""
Pseudo-mirror search: a Moon or Mars point -> the Earth cells whose surface
temperature profile is closest. Stand-in for the real matcher.

    db/.venv/Scripts/python db/mirror.py moon -89.9 0      # Shackleton rim
    db/.venv/Scripts/python db/mirror.py mars 18.44 77.45  # Jezero
"""

import sys
from pathlib import Path

import duckdb

from lookup import point

DB = Path(__file__).parent / "out" / "analogs.duckdb"
# Features every body has, and the difference (K) that halves the score
SHARED = {"tsurf_mean": 40.0, "tsurf_min": 40.0, "tsurf_max": 40.0, "tsurf_range": 30.0}


def mirror(con, body: str, lat: float, lon: float, limit: int = 10):
    t = point(body, lat, lon)
    # Gaussian similarity per feature, averaged; 1 = identical profile
    terms = " + ".join(f"exp(-ln(2) * ((c.{f} - {t[f]}) / {s}) ^ 2)" for f, s in SHARED.items())
    hits = con.execute(f"""
        SELECT h3::VARCHAR AS h3, round(lat, 3) AS lat, round(lon, 3) AS lon,
               round(({terms}) / {len(SHARED)}, 3) AS score,
               {', '.join(f'round(c.{f}::DOUBLE, 1) AS {f}' for f in SHARED)}
        FROM cells c WHERE body = 'earth'
        ORDER BY score DESC LIMIT {limit}""").df()
    return t, hits


if __name__ == "__main__":
    body, lat, lon = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
    con = duckdb.connect(str(DB), read_only=True)
    t, hits = mirror(con, body, lat, lon)
    print(f"{body} at {lat}, {lon}: " + ", ".join(f"{f} {t[f]:.1f} K" for f in SHARED))
    print(f"\nclosest Earth cells\n{hits.to_string(index=False)}")
