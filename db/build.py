"""
Build the analog search database: H3 cells on Earth with environment features,
plus the Moon and Mars grids they are matched against.

    db/.venv/Scripts/python db/build.py            # -> db/out/analogs.duckdb

Scope (hackathon): Nevada only, H3 resolution 7, environment features only
(no elevation match). Earth features come from the 10 degree ERA5/CAMS grid
produced by planets.py, so they vary smoothly across a region; finer source
grids drop in by replacing db/sources/earth_features.csv.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path

import duckdb
import h3
import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
SRC = ROOT / "sources"
OUT = ROOT / "out" / "analogs.duckdb"
RES = 7
GRID_DEG = 10.0

# Nevada: survey lines on the north, east and west, the Colorado River in the
# south-east. Accurate to a few km, which is below the 10 degree source grid.
NEVADA = [
    (42.000, -120.000), (42.000, -114.040), (36.120, -114.040), (36.050, -114.300),
    (36.016, -114.737), (35.500, -114.670), (35.002, -114.633), (39.000, -120.000),
]

# name, label, unit, bodies with data, source note
FEATURES = [
    ("tsurf_mean", "Mean surface temperature", "K", "earth,mars,moon", "Earth: ERA5 skin temperature; Mars: MCD; Moon: LRO Diviner"),
    ("tsurf_min", "Daily low (surface)", "K", "earth,mars,moon", "Mean of daily minima"),
    ("tsurf_max", "Daily high (surface)", "K", "earth,mars,moon", "Mean of daily maxima"),
    ("tsurf_range", "Day-night range (surface)", "K", "earth,mars,moon", "tsurf_max - tsurf_min"),
    ("tair_mean", "Mean air temperature", "K", "earth,mars", "Earth 2 m, Mars 10 m"),
    ("tair_range", "Air day-night range", "K", "earth,mars", ""),
    ("ps", "Surface pressure", "Pa", "earth,mars", ""),
    ("wind", "Wind speed", "m/s", "earth,mars", "Earth 10 m, Mars 10 m"),
    ("rh", "Relative humidity (2 m)", "%", "earth", "ERA5"),
    ("sw", "Sunlight at surface", "W/m2", "earth", "All-sky shortwave, 24 h mean"),
    ("cloud", "Cloud cover", "%", "earth", "ERA5"),
    ("dust_aod", "Aerosol optical depth (550 nm)", "", "earth", "CAMS; all aerosols"),
    ("dust_conc", "Dust near the surface", "ug/m3", "earth", "CAMS"),
    ("tau", "Dust optical depth", "", "mars", "MCD visible column"),
    ("mtot", "Water vapour column", "kg/m2", "mars", "MCD (stored as written by planets.py)"),
    ("icetot", "Water ice clouds (column)", "kg/m2", "mars", "MCD (stored as written by planets.py)"),
]
NAMES = [f[0] for f in FEATURES]
EARTH = [f[0] for f in FEATURES if "earth" in f[3]]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def load_grid(body: str) -> pd.DataFrame:
    df = pd.read_csv(SRC / f"{body}_features.csv")
    df.insert(0, "body", body)
    for n in NAMES:
        if n not in df:
            df[n] = np.nan
    return df[["body", "lat", "lon", *NAMES]]


def earth_lookup(earth: pd.DataFrame):
    """Bilinear interpolation on the land points of the regular Earth grid.

    Ocean neighbours (elevation 0 in the source) are dropped and the remaining
    weights renormalised, so coastal cells don't inherit sea-surface values."""
    elev = pd.read_csv(SRC / "earth_grid_elevation.csv")
    g = earth.merge(elev, on=["lat", "lon"], how="left")
    land = g[g.elevation_m.fillna(0) != 0].set_index(["lat", "lon"])

    def at(lat: float, lon: float) -> dict:
        la0 = np.floor((lat - 5) / GRID_DEG) * GRID_DEG + 5
        lo0 = np.floor((lon - 5) / GRID_DEG) * GRID_DEG + 5
        ty, tx = (lat - la0) / GRID_DEG, (lon - lo0) / GRID_DEG
        corners = [(la0, lo0, (1 - ty) * (1 - tx)), (la0, lo0 + GRID_DEG, (1 - ty) * tx),
                   (la0 + GRID_DEG, lo0, ty * (1 - tx)), (la0 + GRID_DEG, lo0 + GRID_DEG, ty * tx)]
        used = [(land.loc[(a, ((b + 180) % 360) - 180)], w) for a, b, w in corners
                if (a, ((b + 180) % 360) - 180) in land.index and w > 0]
        total = sum(w for _, w in used)
        out = {n: (sum(r[n] * w for r, w in used) / total if total else np.nan) for n in EARTH}
        out["src_points"] = len(used)
        return out

    return at


def nevada_cells(at) -> pd.DataFrame:
    poly = h3.LatLngPoly(NEVADA)
    ids = sorted(h3.polygon_to_cells(poly, RES))
    rows = []
    for c in ids:
        lat, lon = h3.cell_to_latlng(c)
        rows.append({"h3": h3.str_to_int(c), "h3_res": RES, "region": "nevada",
                     "lat": lat, "lon": lon, "area_km2": h3.cell_area(c, "km^2"), **at(lat, lon)})
    df = pd.DataFrame(rows)
    df["tsurf_range"] = df["tsurf_max"] - df["tsurf_min"]
    return df


def main() -> None:
    grids = pd.concat([load_grid(b) for b in ("earth", "mars", "moon")], ignore_index=True)
    cells = nevada_cells(earth_lookup(grids[grids.body == "earth"]))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.unlink(missing_ok=True)
    con = duckdb.connect(str(OUT))
    feat_cols = ",\n  ".join(f"{n} DOUBLE" for n in EARTH)
    con.execute(f"""
CREATE TABLE cells (
  h3 UBIGINT PRIMARY KEY,
  h3_res TINYINT NOT NULL,
  region VARCHAR NOT NULL,
  lat DOUBLE NOT NULL,
  lon DOUBLE NOT NULL,
  area_km2 DOUBLE NOT NULL,
  {feat_cols},
  src_points TINYINT NOT NULL  -- land grid points blended into this cell
)""")
    all_cols = ",\n  ".join(f"{n} DOUBLE" for n in NAMES)
    con.execute(f"""
CREATE TABLE grid_points (
  body VARCHAR NOT NULL,       -- earth | mars | moon
  lat DOUBLE NOT NULL,
  lon DOUBLE NOT NULL,
  {all_cols},
  PRIMARY KEY (body, lat, lon)
)""")
    con.execute("CREATE TABLE features (name VARCHAR PRIMARY KEY, label VARCHAR, unit VARCHAR, bodies VARCHAR, note VARCHAR)")
    con.execute("CREATE TABLE meta (key VARCHAR PRIMARY KEY, value VARCHAR)")

    con.register("cells_df", cells)
    con.execute(f"INSERT INTO cells SELECT h3, h3_res, region, lat, lon, area_km2, {', '.join(EARTH)}, src_points FROM cells_df")
    con.register("grid_df", grids)
    con.execute("INSERT INTO grid_points SELECT * FROM grid_df")
    con.executemany("INSERT INTO features VALUES (?, ?, ?, ?, ?)", FEATURES)
    meta = {
        "built_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "h3_res": str(RES),
        "regions": "nevada",
        "earth_source": f"ERA5 + CAMS via Open-Meteo, {GRID_DEG:g} deg grid, 4 sample weeks (planets.py)",
        "earth_interp": "bilinear on land grid points; ocean neighbours dropped",
        "mars_source": "Mars Climate Database v6, 4 seasons x 6 local times (planets.py)",
        "moon_source": "LRO Diviner Global Cumulative Product, 2 deg pixels (planets.py)",
        "units": "SI: K, Pa, m/s; see features table",
        **{f"sha256:{p.name}": sha(p) for p in sorted(SRC.glob("*.csv"))},
    }
    con.executemany("INSERT INTO meta VALUES (?, ?)", list(meta.items()))
    con.execute("CREATE INDEX cells_region ON cells(region)")

    n = con.execute("SELECT count(*), round(sum(area_km2)) FROM cells").fetchone()
    g = con.execute("SELECT body, count(*) FROM grid_points GROUP BY body ORDER BY body").fetchall()
    con.close()
    print(f"{OUT}: {n[0]:,} cells covering {n[1]:,.0f} km2; grid points {dict(g)}")


if __name__ == "__main__":
    main()
