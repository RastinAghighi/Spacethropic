"""Site/body configuration, paths, and the site-local projection every raster is warped into."""
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml
from rasterio.crs import CRS

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RAW = DATA / "raw"
INTERIM = DATA / "interim"
OUT = DATA / "out"


@dataclass(frozen=True)
class Body:
    name: str
    radius_m: float
    h3_res: int


@dataclass(frozen=True)
class Site:
    id: str
    name: str
    body: Body
    lat: float
    lon: float
    radius_km: float


@cache
def _config() -> dict:
    return yaml.safe_load((ROOT / "sites.yaml").read_text(encoding="utf-8"))


def settings() -> dict:
    return _config()["defaults"]


@cache
def sites() -> dict[str, Site]:
    cfg = _config()
    bodies = {k: Body(k, float(v["radius_m"]), int(v["h3_res"])) for k, v in cfg["bodies"].items()}
    radius = cfg["defaults"]["radius_km"]
    return {
        s["id"]: Site(s["id"], s["name"], bodies[s["body"]], float(s["lat"]), float(s["lon"]), float(s.get("radius_km", radius)))
        for s in cfg["sites"]
    }


def select(name: str) -> list[Site]:
    """`all` or a single site id."""
    if name == "all":
        return list(sites().values())
    if name not in sites():
        raise SystemExit(f"unknown site {name!r}; choose from: all, {', '.join(sites())}")
    return [sites()[name]]


def geographic_crs(body: Body) -> CRS:
    if body.name == "earth":
        return CRS.from_epsg(4326)
    return CRS.from_proj4(f"+proj=longlat +R={body.radius_m} +no_defs")


def local_crs(site: Site) -> CRS:
    """Azimuthal equidistant projection centred on the site: distances from the centre are true,
    and there's no pole singularity, so the same code handles Shackleton and the Atacama."""
    shape = "+ellps=WGS84" if site.body.name == "earth" else f"+R={site.body.radius_m}"
    return CRS.from_proj4(f"+proj=aeqd +lat_0={site.lat} +lon_0={site.lon} {shape} +units=m +no_defs")


def window_radius_m() -> float:
    """Radius of the fixed-area disk used for scale-sensitive features."""
    from math import pi, sqrt

    return sqrt(settings()["window_km2"] * 1e6 / pi)


def raster_half_extent_m(site: Site) -> float:
    """Half-width of the square raster pulled around a site: the site disk plus room for a
    full feature window and a cell's circumradius at the edge, plus a 1 km margin."""
    return site.radius_km * 1000 + window_radius_m() + 3000 + 1000
