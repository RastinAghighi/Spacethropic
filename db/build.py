"""
Build the analog search database: Earth H3 cells with environment features,
plus the Earth, Moon and Mars source grids.

    db/.venv/Scripts/python db/build.py            # -> db/out/analogs.duckdb

Scope (hackathon): Earth is the search space, so its cells are materialised
(Nevada, H3 resolution 7). The Moon and Mars are only ever the target, a
single point, so they are not tiled: lookup.py interpolates their grids at
the requested point on demand. Earth values are bilinear interpolations of the
10 degree planets.py grid; finer grids drop in by replacing db/sources/.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import time
from pathlib import Path

import duckdb
import h3
import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
SRC = ROOT / "sources"
OUT = ROOT / "out" / "analogs.duckdb"
RES = 7
R_EARTH = 6371.007180918475  # H3's authalic radius, km
RADIUS = {"earth": R_EARTH, "moon": 1737.4, "mars": 3389.5}

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
OF = {b: [f[0] for f in FEATURES if b in f[3]] for b in RADIUS}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def load_grid(body: str) -> pd.DataFrame:
    df = pd.read_csv(SRC / f"{body}_features.csv")
    df.insert(0, "body", body)
    for n in NAMES:
        if n not in df:
            df[n] = np.nan
    return df[["body", "lat", "lon", *NAMES]]


class Grid:
    """Bilinear interpolation on a lat/lon grid, wrapping in longitude.

    Missing source values (NaN) are skipped and the remaining corner weights
    renormalised, so a cell only takes values from points that have data."""

    def __init__(self, df: pd.DataFrame, cols: list[str]):
        df = df.assign(lon=((df.lon + 180) % 360) - 180).drop_duplicates(["lat", "lon"])  # 180 == -180
        self.lat = np.sort(df.lat.unique())
        self.lon = np.sort(df.lon.unique())
        self.cols = cols
        full = pd.MultiIndex.from_product([self.lat, self.lon], names=["lat", "lon"])
        g = df.set_index(["lat", "lon"]).reindex(full)
        self.z = {c: g[c].to_numpy(float).reshape(len(self.lat), len(self.lon)) for c in cols}

    def __call__(self, lat: np.ndarray, lon: np.ndarray) -> dict[str, np.ndarray]:
        i = np.clip(np.searchsorted(self.lat, lat) - 1, 0, len(self.lat) - 2)
        ty = np.clip((lat - self.lat[i]) / (self.lat[i + 1] - self.lat[i]), 0, 1)
        ext = np.append(self.lon, self.lon[0] + 360)  # wrap the last column to the first
        j = np.searchsorted(ext, lon) - 1
        lon = np.where(j < 0, lon + 360, lon)
        j = np.where(j < 0, len(self.lon) - 1, j)
        tx = (lon - ext[j]) / (ext[j + 1] - ext[j])
        j1 = (j + 1) % len(self.lon)
        corners = [(i, j, (1 - ty) * (1 - tx)), (i, j1, (1 - ty) * tx), (i + 1, j, ty * (1 - tx)), (i + 1, j1, ty * tx)]
        out, used = {}, None
        for c in self.cols:
            num = np.zeros_like(lat)
            den = np.zeros_like(lat)
            cnt = np.zeros(lat.shape, np.int8)
            for a, b, w in corners:
                v = self.z[c][a, b]
                ok = np.isfinite(v) & (w > 0)
                num += np.where(ok, v * w, 0)
                den += np.where(ok, w, 0)
                cnt += ok
            out[c] = np.where(den > 0, num / np.where(den > 0, den, 1), np.nan)
            used = cnt if used is None else np.maximum(used, cnt)
        out["src_points"] = used
        return out


def earth_grid(grids: pd.DataFrame) -> Grid:
    """Earth's land points only: ocean neighbours (elevation 0 in the source)
    would otherwise give coastal cells sea-surface values."""
    elev = pd.read_csv(SRC / "earth_grid_elevation.csv")
    g = grids[grids.body == "earth"].merge(elev, on=["lat", "lon"], how="left")
    g.loc[g.elevation_m.fillna(0) == 0, OF["earth"]] = np.nan
    return Grid(g, OF["earth"])


def frame(body: str, region: str, h3s, lat, lon, area_earth_km2, vals: dict) -> pd.DataFrame:
    df = pd.DataFrame({"body": body, "h3": np.asarray(h3s, np.uint64), "region": region,
                       "lat": lat, "lon": lon, "area_km2": np.asarray(area_earth_km2) * (RADIUS[body] / R_EARTH) ** 2})
    for n in NAMES:
        df[n] = vals.get(n, np.nan)
    df["tsurf_range"] = df["tsurf_max"] - df["tsurf_min"]
    df["src_points"] = vals["src_points"]
    return df


SCHEMA = f"""
CREATE TABLE cells (
  body VARCHAR NOT NULL,       -- earth (other bodies are looked up on demand)
  h3 UBIGINT NOT NULL,         -- unique per body; rows are stored in h3 order
  region VARCHAR NOT NULL,     -- nevada
  lat DOUBLE NOT NULL,         -- cell centre, degrees
  lon DOUBLE NOT NULL,
  area_km2 FLOAT NOT NULL,     -- scaled to the body's radius
  {", ".join(f"{n} FLOAT" for n in NAMES)},
  src_points TINYINT NOT NULL  -- source grid points blended into this cell (0 = no data)
);
CREATE TABLE grid_points (body VARCHAR, lat DOUBLE, lon DOUBLE, {", ".join(f"{n} DOUBLE" for n in NAMES)});
CREATE TABLE features (name VARCHAR, label VARCHAR, unit VARCHAR, bodies VARCHAR, note VARCHAR);
CREATE TABLE meta (key VARCHAR, value VARCHAR);
"""


def main() -> None:
    t0 = time.time()
    grids = pd.concat([load_grid(b) for b in ("earth", "mars", "moon")], ignore_index=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.unlink(missing_ok=True)
    con = duckdb.connect(str(OUT))
    con.execute(SCHEMA)
    cols = ", ".join(["body", "h3", "region", "lat", "lon", "area_km2", *NAMES, "src_points"])

    def insert(df: pd.DataFrame) -> None:
        con.register("batch", df)
        con.execute(f"INSERT INTO cells SELECT {cols} FROM batch")
        con.unregister("batch")

    # Earth: Nevada
    ids = sorted(h3.str_to_int(c) for c in h3.polygon_to_cells(h3.LatLngPoly(NEVADA), RES))
    ll = np.array([h3.cell_to_latlng(h3.int_to_str(c)) for c in ids])
    area = np.array([h3.cell_area(h3.int_to_str(c), "km^2") for c in ids])
    insert(frame("earth", "nevada", ids, ll[:, 0], ll[:, 1], area, earth_grid(grids)(ll[:, 0], ll[:, 1])))
    print(f"earth: {len(ids):,} Nevada cells ({time.time() - t0:.0f}s)")

    con.register("grid_df", grids)
    con.execute("INSERT INTO grid_points SELECT * FROM grid_df")
    con.executemany("INSERT INTO features VALUES (?, ?, ?, ?, ?)", FEATURES)
    meta = {
        "built_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "h3_res": str(RES),
        "coverage": "earth cells: nevada; moon, mars: grid_points, interpolated on demand (lookup.py)",
        "radii_km": ", ".join(f"{b} {r:g}" for b, r in RADIUS.items()),
        "earth_source": "ERA5 + CAMS via Open-Meteo, 10 deg grid, 4 sample weeks (planets.py)",
        "mars_source": "Mars Climate Database v6, 4 seasons x 6 local times (planets.py)",
        "moon_source": "LRO Diviner Global Cumulative Product, 2 deg pixels (planets.py)",
        "interp": "bilinear, longitude wraps, missing corners dropped and weights renormalised; Earth uses land points only",
        "units": "SI: K, Pa, m/s; see features table",
        **{f"sha256:{p.name}": sha(p) for p in sorted(SRC.glob("*.csv"))},
    }
    con.executemany("INSERT INTO meta VALUES (?, ?)", list(meta.items()))
    con.execute("CHECKPOINT")
    print(con.execute("SELECT body, count(*), round(sum(area_km2)) FROM cells GROUP BY body ORDER BY body").fetchall())
    con.close()
    print(f"{OUT} ({OUT.stat().st_size / 1e6:.0f} MB, {time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
