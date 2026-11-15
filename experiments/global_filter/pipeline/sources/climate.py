"""Temperature extremes and sunlight (dimension 3).

Temperature features use one definition on every body. From a year of surface (skin)
temperature samples at many local solar times (LT):
    day   = samples with 6 <= LT < 18,  night = the rest
    temp_day_max_k   = max of day samples       temp_night_max_k = max of night samples
    temp_night_min_k = min of night samples     temp_mean_k      = mean of all samples
Sources: Earth NASA POWER hourly skin temperature (MERRA-2 reanalysis), Mars NASA Ames Legacy
GCM (model), Moon LRO Diviner (measured).

Sunlight: annual-mean top-of-atmosphere insolation computed from latitude and each body's
orbit, identical method everywhere. Terrain shadowing is ignored.
"""
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from scipy.interpolate import RegularGridInterpolator
from scipy.io import netcdf_file

from config import RAW, Site, raster_half_extent_m
from sources.base import Source
from sources.raster import http_provenance, write_site_raster

PIXEL_M = 500.0
BANDS = ("temp_day_max_k", "temp_night_max_k", "temp_night_min_k", "temp_mean_k")
# Weather (dimension 5). Earth wind is at 10 m (POWER WS10M); Mars wind is the GCM layer
# nearest the ground (a few metres up). The Moon has no atmosphere: known-absent 0.
WEATHER_BANDS = ("pressure_mean_pa", "wind_mean_ms", "wind_max_ms")


def _stats(temps: np.ndarray, local_time: np.ndarray) -> np.ndarray:
    """temps, local_time: same shape (samples, ...). Returns (4, ...) in BANDS order."""
    day = (local_time >= 6) & (local_time < 18)
    with np.errstate(all="ignore"):
        out = np.stack(
            [
                np.where(day, temps, -np.inf).max(axis=0),
                np.where(~day, temps, -np.inf).max(axis=0),
                np.where(~day, temps, np.inf).min(axis=0),
                temps.mean(axis=0),
            ]
        )
    return np.where(np.isfinite(out), out, np.nan)  # no day (or night) samples -> NaN


# ---------------------------------------------------------------- Earth: NASA POWER hourly
POWER = "https://power.larc.nasa.gov/api/temporal/hourly/point"
POWER_YEAR = 2023
POWER_DLAT, POWER_DLON = 0.5, 0.625  # MERRA-2 grid behind POWER's meteorology


def _power_hourly_cells(site: Site, parameters: str, reduce) -> tuple[dict, list]:
    """Query every POWER grid cell the site raster touches for a year of hourly data.
    `reduce(series_by_param, local_hours)` -> 1-D array of band values for one cell."""
    reach = raster_half_extent_m(site) / 1000 / 111.0
    reach_lon = reach / max(math.cos(math.radians(site.lat)), 0.05)
    lats = np.arange(math.floor((site.lat - reach) / POWER_DLAT), math.floor((site.lat + reach) / POWER_DLAT) + 1) * POWER_DLAT
    lons = np.arange(math.floor((site.lon - reach_lon) / POWER_DLON), math.floor((site.lon + reach_lon) / POWER_DLON) + 1) * POWER_DLON
    cells, inputs = {}, []
    for la in lats + POWER_DLAT / 2:
        for lo in lons + POWER_DLON / 2:
            params = {
                "parameters": parameters,
                "community": "RE",
                "latitude": round(float(la), 4),
                "longitude": round(float(lo), 4),
                "start": f"{POWER_YEAR}0101",
                "end": f"{POWER_YEAR}1231",
                "format": "JSON",
                "time-standard": "LST",
            }
            r = requests.get(POWER, params=params, timeout=300)
            r.raise_for_status()
            data = r.json()["properties"]["parameter"]
            keys = sorted(set.intersection(*[{k for k, v in data[p].items() if v is not None and v > -900} for p in parameters.split(",")]))
            series = {p: np.array([data[p][k] for k in keys], float) for p in parameters.split(",")}
            hours = np.array([int(k[-2:]) + 0.5 for k in keys], float)  # LST hour bin centre
            cells[(la, lo)] = reduce(series, hours)
            inputs.append({"url": r.url, "samples": len(keys)})
    return cells, inputs


def _nearest_cell_raster(cells: dict):
    grid = np.array(list(cells))
    stack = np.stack([cells[tuple(g)] for g in grid])  # (cells, bands)

    def value_at(lat, lon):
        d = (lat[..., None] - grid[:, 0]) ** 2 + ((lon[..., None] - grid[:, 1]) * np.cos(np.radians(lat[..., None]))) ** 2
        return np.moveaxis(stack[d.argmin(axis=-1)], -1, 0)

    return value_at


class PowerWeather(Source):
    id = "power_weather_hourly"
    group = "weather"
    bodies = {"earth"}
    product = f"NASA POWER hourly surface pressure PS and 10 m wind speed WS10M (MERRA-2 reanalysis), {POWER_YEAR}"
    native_res = "0.5° × 0.625° (~55 km), hourly"

    def fetch(self, site: Site, out: Path) -> dict:
        def reduce(series, hours):
            ps, ws = series["PS"] * 1000.0, series["WS10M"]  # kPa -> Pa
            return np.array([ps.mean(), ws.mean(), ws.max()])

        cells, inputs = _power_hourly_cells(site, "PS,WS10M", reduce)
        meta = write_site_raster(site, out, PIXEL_M, _nearest_cell_raster(cells), bands=WEATHER_BANDS)
        return {**meta, "year": POWER_YEAR, "inputs": inputs}


class PowerSkinTemperature(Source):
    id = "power_ts_hourly"
    group = "temperature"
    bodies = {"earth"}
    product = f"NASA POWER hourly earth skin temperature TS (MERRA-2 reanalysis), {POWER_YEAR}, local solar time"
    native_res = "0.5° × 0.625° (~55 km)"

    def fetch(self, site: Site, out: Path) -> dict:
        # Query every POWER grid cell the site raster touches, then nearest-cell rasterise.
        reach = raster_half_extent_m(site) / 1000 / 111.0
        reach_lon = reach / max(math.cos(math.radians(site.lat)), 0.05)
        lats = np.arange(math.floor((site.lat - reach) / POWER_DLAT), math.floor((site.lat + reach) / POWER_DLAT) + 1) * POWER_DLAT
        lons = np.arange(math.floor((site.lon - reach_lon) / POWER_DLON), math.floor((site.lon + reach_lon) / POWER_DLON) + 1) * POWER_DLON
        cells, inputs = {}, []
        for la in lats + POWER_DLAT / 2:
            for lo in lons + POWER_DLON / 2:
                params = {
                    "parameters": "TS",
                    "community": "RE",
                    "latitude": round(float(la), 4),
                    "longitude": round(float(lo), 4),
                    "start": f"{POWER_YEAR}0101",
                    "end": f"{POWER_YEAR}1231",
                    "format": "JSON",
                    "time-standard": "LST",
                }
                r = requests.get(POWER, params=params, timeout=300)
                r.raise_for_status()
                series = r.json()["properties"]["parameter"]["TS"]  # {"YYYYMMDDHH": °C}
                keys = sorted(k for k, v in series.items() if v is not None and v > -900)
                t = np.array([series[k] for k in keys], float) + 273.15
                lt = np.array([int(k[-2:]) + 0.5 for k in keys], float)  # hour bin centre
                cells[(la, lo)] = _stats(t, lt)
                inputs.append({"url": r.url, "samples": len(keys)})

        grid = np.array(list(cells))

        def value_at(lat, lon):
            d = (lat[..., None] - grid[:, 0]) ** 2 + ((lon[..., None] - grid[:, 1]) * np.cos(np.radians(lat[..., None]))) ** 2
            nearest = d.argmin(axis=-1)
            stack = np.stack([cells[tuple(g)] for g in grid])  # (cells, 4)
            return np.moveaxis(stack[nearest], -1, 0)

        meta = write_site_raster(site, out, PIXEL_M, value_at, bands=BANDS)
        return {**meta, "year": POWER_YEAR, "inputs": inputs}


# ---------------------------------------------------------------- Moon: Diviner GCP
DIVINER_GCP = "https://pds-geosciences.wustl.edu/lro/urn-nasa-pds-lro_diviner_derived1/data_derived_gcp/"
DIVINER_MIN_BINS = 12  # of 48 day / 48 night quarter-hour bins, to trust a max/min


def _diviner_band_file(lat: float) -> str:
    """10° latitude band file, e.g. -8.97 -> 10s00s, 5 -> 00n10n, -89.67 -> 90s80s."""
    lo = math.floor(lat / 10) * 10
    band = f"{-lo:02d}s{-(lo + 10):02d}s" if lo < 0 else f"{lo:02d}n{lo + 10:02d}n"
    return f"global_cumul_avg_cyl_{band}_002.tab"


class DivinerTemperature(Source):
    id = "diviner_gcp"
    group = "temperature"
    bodies = {"moon"}
    product = "LRO Diviner Global Cumulative Product (Williams et al. 2017): bolometric temperature binned 0.5° × 0.25 h local time, 2009–2015"
    native_res = "0.5° (~15 km), 15-min local-time bins"

    def fetch(self, site: Site, out: Path) -> dict:
        name = _diviner_band_file(site.lat)
        local = RAW / "_shared" / "diviner" / name
        if not local.exists():
            local.parent.mkdir(parents=True, exist_ok=True)
            with requests.get(DIVINER_GCP + name, stream=True, timeout=1800) as r:
                r.raise_for_status()
                tmp = local.with_suffix(".part")
                with open(tmp, "wb") as fh:
                    for chunk in r.iter_content(1 << 22):
                        fh.write(chunk)
                tmp.replace(local)
        t = pd.read_csv(local, skipinitialspace=True, usecols=["clon", "clat", "ltim", "tbol"])
        t = t[t["tbol"] > 0]
        # Rows are 720 lon × 20 lat bins × 96 local-time bins; index bins on a 0.5° grid.
        t["i"] = np.floor((t["clat"] + 90) / 0.5).astype(int)
        t["j"] = np.floor((t["clon"] + 180) / 0.5).astype(int)
        t["day"] = (t["ltim"] >= 6) & (t["ltim"] < 18)
        g = t.groupby(["i", "j"])
        day, night = t[t["day"]].groupby(["i", "j"])["tbol"], t[~t["day"]].groupby(["i", "j"])["tbol"]
        table = pd.DataFrame(
            {
                "day_max": day.max().where(day.count() >= DIVINER_MIN_BINS),
                "night_max": night.max().where(night.count() >= DIVINER_MIN_BINS),
                "night_min": night.min().where(night.count() >= DIVINER_MIN_BINS),
                # Mean over local time: average each quarter-hour bin equally.
                "mean": g["tbol"].mean().where(g["tbol"].count() >= 2 * DIVINER_MIN_BINS),
            }
        )
        grid = np.full((4, 360, 720), np.nan)
        idx = table.index.to_frame().to_numpy()
        for b, col in enumerate(["day_max", "night_max", "night_min", "mean"]):
            grid[b, idx[:, 0], idx[:, 1]] = table[col].to_numpy()

        def value_at(lat, lon):
            i = np.clip(np.floor((lat + 90) / 0.5).astype(int), 0, 359)
            j = np.clip(np.floor((lon + 180) / 0.5).astype(int), 0, 719)
            return grid[:, i, j]

        meta = write_site_raster(site, out, PIXEL_M, value_at, bands=BANDS)
        return {**meta, "inputs": [http_provenance(DIVINER_GCP + name)]}


# ---------------------------------------------------------------- Mars: Ames Legacy GCM
MGCM = "https://data.nas.nasa.gov/legacygcm/legacygcm/ACTIVECLDS_NCDF/"
MGCM_CACHE = RAW / "_shared" / "mgcm"


def _mgcm_files() -> list[str]:
    html = requests.get(MGCM, timeout=120).text
    return sorted(set(re.findall(r"LegacyGCM_Ls\d{3}_Ls\d{3}\.nc", html)))


# Fields accumulated from the GCM in one pass, so the ~20 GB is streamed only once.
# "lowest" = the model layer nearest the ground (last nlay index, sigma ~0.9995).
MGCM_FIELDS = (
    "tsurf_day_max", "tsurf_night_max", "tsurf_night_min", "tsurf_mean",  # K
    "psurf_mean_pa", "psurf_min_pa", "psurf_max_pa",                       # psurf is mbar in the files
    "wind_mean_ms", "wind_max_ms",                                         # lowest-layer |u,v|
    "dust_mass_mean", "dust_mass_max",                                     # lowest-layer dst_mass, kg/kg
    "h2o_vap_mass_mean",                                                   # lowest-layer vapour, kg/kg
)


def _download(url: str, local: Path, attempts: int = 6) -> None:
    """Whole-file download with retries; the NAS portal returns intermittent 502s."""
    import time

    for attempt in range(1, attempts + 1):
        try:
            with requests.get(url, stream=True, timeout=1800) as r:
                r.raise_for_status()
                tmp = local.with_suffix(".part")
                with open(tmp, "wb") as fh:
                    for chunk in r.iter_content(1 << 22):
                        fh.write(chunk)
                tmp.replace(local)
                return
        except (requests.RequestException, OSError) as e:
            if attempt == attempts:
                raise
            wait = 30 * attempt
            print(f"  retry {attempt}/{attempts - 1} in {wait}s after: {e}", flush=True)
            time.sleep(wait)


def _mgcm_reduce(local: Path) -> dict[str, np.ndarray]:
    """Per-file reductions: extremes, and sums + sample count for the means."""
    with netcdf_file(local, mmap=False) as f:
        v = f.variables
        ts = v["tsurf"][:].astype(np.float64)  # (sol, tod, lat, lon)
        ps = v["psurf"][:].astype(np.float64) * 100.0  # mbar -> Pa
        wind = np.hypot(v["ucomp"][:, :, -1].astype(np.float64), v["vcomp"][:, :, -1].astype(np.float64))
        dust = v["dst_mass"][:, :, -1].astype(np.float64)
        vap = v["h2o_vap_mass"][:, :, -1].astype(np.float64)
        lat = v["latitude"][:].astype(float)
        lon = v["longitude"][:].astype(float)
    n_tod = ts.shape[1]
    # Output step i is at 1.5*i h at the prime meridian (verified: daily peaks fall at
    # LT ~12–13.5 at every longitude); local time adds lon/15.
    lt = (1.5 * np.arange(n_tod)[:, None] + lon[None, :] / 15) % 24  # (tod, lon)
    lt = np.broadcast_to(lt[None, :, None, :], ts.shape)
    flat = lambda a: a.reshape(-1, *a.shape[2:])  # noqa: E731
    s = _stats(flat(ts), flat(lt))
    return {
        "lat": lat, "lon": lon, "count": np.array(ts.shape[0] * ts.shape[1]),
        "tsurf_day_max": s[0], "tsurf_night_max": s[1], "tsurf_night_min": s[2],
        "psurf_min_pa": ps.min(axis=(0, 1)), "psurf_max_pa": ps.max(axis=(0, 1)),
        "wind_max_ms": wind.max(axis=(0, 1)), "dust_mass_max": dust.max(axis=(0, 1)),
        "sum_tsurf_mean": ts.sum(axis=(0, 1)), "sum_psurf_mean_pa": ps.sum(axis=(0, 1)),
        "sum_wind_mean_ms": wind.sum(axis=(0, 1)), "sum_dust_mass_mean": dust.sum(axis=(0, 1)),
        "sum_h2o_vap_mass_mean": vap.sum(axis=(0, 1)),
    }


# Sample every Nth 10-sol file, evenly spread through the Mars year (user decision, to cut
# the ~20 GB / ~80 min full download to ~3.5 GB / ~15 min). Means barely change; extremes
# (day max, night min) come out slightly too mild, since the hottest/coldest sols may fall
# in a skipped file. Set to 1 for the full year.
MGCM_FILE_STEP = 6


def mgcm_climatology() -> dict:
    """Year-long statistics on the GCM grid (MGCM_FIELDS) from every MGCM_FILE_STEP-th
    10-sol file. Resumable: each file's reductions are saved to partials/ and the file
    deleted, so a rerun skips finished files. The result is cached as a small .npz."""
    cache = MGCM_CACHE / f"mgcm_climatology_step{MGCM_FILE_STEP}.npz"
    if cache.exists():
        z = np.load(cache, allow_pickle=True)
        return {k: z[k] for k in z.files}
    partials = MGCM_CACHE / "partials"
    partials.mkdir(parents=True, exist_ok=True)
    files = _mgcm_files()
    if len(files) != 67:
        raise RuntimeError(f"expected 67 Legacy GCM files, found {len(files)}")
    files = files[::MGCM_FILE_STEP]
    used = []
    for k, name in enumerate(files, 1):
        part = partials / (name + ".npz")
        if not part.exists():
            local = MGCM_CACHE / name
            if not local.exists():
                _download(MGCM + name, local)
            size = local.stat().st_size
            np.savez(part, **_mgcm_reduce(local), bytes=np.array(size))
            local.unlink()  # keep disk small
        used.append({"file": MGCM + name, "bytes": int(np.load(part)["bytes"])})
        print(f"mgcm {k}/{len(files)} {name}", flush=True)

    acc: dict[str, np.ndarray] = {}
    count = 0
    for name in files:
        z = np.load(partials / (name + ".npz"))
        count += int(z["count"])
        for key, how in (("tsurf_day_max", np.fmax), ("tsurf_night_max", np.fmax), ("tsurf_night_min", np.fmin),
                         ("psurf_min_pa", np.minimum), ("psurf_max_pa", np.maximum), ("wind_max_ms", np.maximum),
                         ("dust_mass_max", np.maximum)):
            acc[key] = z[key] if key not in acc else how(acc[key], z[key])
        for key in ("tsurf_mean", "psurf_mean_pa", "wind_mean_ms", "dust_mass_mean", "h2o_vap_mass_mean"):
            acc[key] = z["sum_" + key] if key not in acc else acc[key] + z["sum_" + key]
        lat, lon = z["lat"], z["lon"]
    for key in ("tsurf_mean", "psurf_mean_pa", "wind_mean_ms", "dust_mass_mean", "h2o_vap_mass_mean"):
        acc[key] = acc[key] / count
    clim = {
        "lat": lat,
        "lon": lon,
        **{f: acc[f] for f in MGCM_FIELDS},
        "samples": np.array(count),
        "file_step": np.array(MGCM_FILE_STEP),
        "files": np.array(json.dumps(used)),
        "built_at": np.array(datetime.now(timezone.utc).isoformat(timespec="seconds")),
    }
    np.savez(cache, **clim)
    return clim


def mgcm_interpolators(fields: tuple[str, ...]):
    """Bilinear (lat, lon) interpolators over the GCM grid, wrapping longitude across ±180."""
    clim = mgcm_climatology()
    lat, lon = clim["lat"], clim["lon"]
    lon_w = np.concatenate([lon - 360, lon, lon + 360])
    interps = [RegularGridInterpolator((lat, lon_w), np.concatenate([clim[f]] * 3, axis=-1), bounds_error=False, fill_value=None) for f in fields]

    def value_at(la, lo):
        pts = np.stack([np.clip(la, lat.min(), lat.max()), lo], axis=-1)
        return np.stack([f(pts) for f in interps])

    return value_at, clim


class MarsGcmTemperature(Source):
    id = "mgcm_tsurf"
    group = "temperature"
    bodies = {"mars"}
    product = "NASA Ames Legacy Mars GCM, ACTIVECLDS reference simulation (Haberle et al. 2019), 1 Mars year, surface temperature (model output)"
    native_res = "5° lat × 6° lon, 1.5 h steps; every 6th 10-sol file (12 of 67, evenly through the year)"

    def fetch(self, site: Site, out: Path) -> dict:
        value_at, clim = mgcm_interpolators(("tsurf_day_max", "tsurf_night_max", "tsurf_night_min", "tsurf_mean"))
        meta = write_site_raster(site, out, PIXEL_M, value_at, bands=BANDS)
        return {**meta, "inputs": json.loads(str(clim["files"])), "file_step": int(clim["file_step"]), "climatology_built_at": str(clim["built_at"])}


class MarsGcmWeather(Source):
    id = "mgcm_weather"
    group = "weather"
    bodies = {"mars"}
    product = "NASA Ames Legacy Mars GCM (ACTIVECLDS): surface pressure and lowest-layer wind speed (model output)"
    native_res = "5° lat × 6° lon, 1.5 h steps; every 6th 10-sol file"

    def fetch(self, site: Site, out: Path) -> dict:
        value_at, clim = mgcm_interpolators(("psurf_mean_pa", "wind_mean_ms", "wind_max_ms"))
        meta = write_site_raster(site, out, PIXEL_M, value_at, bands=WEATHER_BANDS)
        return {**meta, "inputs": json.loads(str(clim["files"])), "file_step": int(clim["file_step"]), "climatology_built_at": str(clim["built_at"])}


# ---------------------------------------------------------------- Sunlight (all bodies)
SOLAR_CONSTANT_1AU = 1361.0  # W/m², Kopp & Lean 2011
ORBITS = {
    # semi-major axis (AU), eccentricity, obliquity (deg), longitude of perihelion measured
    # from the northern spring equinox (deg, i.e. Ls of perihelion)
    "earth": (1.0000, 0.0167, 23.44, 283.0),
    "moon": (1.0000, 0.0167, 1.54, 283.0),  # Earth's orbit; obliquity to the ecliptic
    "mars": (1.5237, 0.0934, 25.19, 251.0),
}


def annual_mean_insolation(lat_deg: np.ndarray, body: str, steps: int = 720) -> np.ndarray:
    """Time-averaged daily-mean top-of-atmosphere insolation over one orbit (W/m²)."""
    a, e, obl, peri = ORBITS[body]
    obl, peri = math.radians(obl), math.radians(peri)
    phi = np.radians(np.asarray(lat_deg, float))
    total = np.zeros_like(phi)
    for M in np.linspace(0, 2 * math.pi, steps, endpoint=False):  # uniform in time
        E = M
        for _ in range(8):
            E = E - (E - e * math.sin(E) - M) / (1 - e * math.cos(E))
        nu = 2 * math.atan2(math.sqrt(1 + e) * math.sin(E / 2), math.sqrt(1 - e) * math.cos(E / 2))
        r = a * (1 - e * math.cos(E))
        ls = nu + peri
        dec = math.asin(math.sin(obl) * math.sin(ls))
        x = np.clip(-np.tan(phi) * math.tan(dec), -1, 1)
        h0 = np.arccos(x)
        q = SOLAR_CONSTANT_1AU / r**2 / math.pi * (h0 * np.sin(phi) * math.sin(dec) + np.cos(phi) * math.cos(dec) * np.sin(h0))
        total += q
    return total / steps


class OrbitalInsolation(Source):
    id = "orbital_insolation"
    group = "insolation"
    bodies = {"earth", "moon", "mars"}
    product = "Annual-mean top-of-atmosphere insolation computed from latitude and orbital elements (no terrain shadowing, no atmosphere)"
    native_res = "analytic"

    def fetch(self, site: Site, out: Path) -> dict:
        meta = write_site_raster(site, out, PIXEL_M, lambda lat, lon: annual_mean_insolation(lat, site.body.name))
        return {**meta, "orbit": dict(zip(("a_au", "e", "obliquity_deg", "ls_perihelion_deg"), ORBITS[site.body.name])), "solar_constant_1au": SOLAR_CONSTANT_1AU}
