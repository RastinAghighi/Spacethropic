"""Global Earth temperature and weather climatology from MERRA-2 hourly fields, 2023.

The same reanalysis NASA POWER serves (the site pipeline used POWER's point API, which is
rate-limited to ~30 requests/min: too slow for the whole planet). Reads each day's
M2T1NXSLV file through the Earthdata Cloud OPeNDAP service, subset to TS, PS, U10M, V10M
(~37 MB/day), folds it into running per-cell statistics and deletes it.

Definitions match sources/climate.py exactly:
  local solar time LT = UTC hour (bin centre) + lon / 15; day = 6 <= LT < 18, night = the rest
  temp_day_max_k, temp_night_max_k, temp_night_min_k (skin temperature TS), temp_mean_k
  pressure_mean_pa (PS), wind_mean_ms, wind_max_ms (10 m wind speed from U10M, V10M)

Output: data/interim/global/merra2_2023_climate.npz (7 bands on the 361 x 576 MERRA-2 grid,
0.5 deg x 0.625 deg, plus lat/lon axes). Needs EARTHDATA_TOKEN with the GES DISC EULA accepted.
Usage: uv run python analysis/earth_merra2_climate.py [--workers 6]
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import rasterio
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "interim" / "global" / "merra2_2023_climate.npz"
YEAR = 2023
OPENDAP = ("https://opendap.earthdata.nasa.gov/collections/C1276812863-GES_DISC/granules/"
           "M2T1NXSLV.5.12.4%3AMERRA2_{stream}.tavg1_2d_slv_Nx.{ymd}.nc4.dap.nc4"
           "?dap4.ce=/TS;/PS;/U10M;/V10M;/lat;/lon;/time")
BANDS = ("temp_day_max_k", "temp_night_max_k", "temp_night_min_k", "temp_mean_k",
         "pressure_mean_pa", "wind_mean_ms", "wind_max_ms")


def token() -> str:
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("EARTHDATA_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("EARTHDATA_TOKEN missing from pipeline/.env")


def read(path: str, var: str):
    with rasterio.open(f'NETCDF:"{path}":{var}') as s:
        a = s.read().astype(np.float64)
        a[a > 1e14] = np.nan  # MERRA-2 fill value 1e15
        return a, s.transform


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    auth = {"Authorization": f"Bearer {token()}"}
    days = [dt.date(YEAR, 1, 1) + dt.timedelta(d) for d in range((dt.date(YEAR + 1, 1, 1) - dt.date(YEAR, 1, 1)).days)]

    lock = threading.Lock()
    acc: dict[str, np.ndarray] = {}
    grid = {}

    def one(day: dt.date):
        url = OPENDAP.format(stream=400, ymd=day.strftime("%Y%m%d"))
        for attempt in range(6):
            try:
                r = requests.get(url, headers=auth, timeout=600)
                r.raise_for_status()
                break
            except Exception:  # noqa: BLE001
                if attempt == 5:
                    raise
                time.sleep(10 * (attempt + 1))
        fd, path = tempfile.mkstemp(suffix=".nc4")
        with os.fdopen(fd, "wb") as f:
            f.write(r.content)
        try:
            ts, T = read(path, "TS")
            ps, _ = read(path, "PS")
            u, _ = read(path, "U10M")
            v, _ = read(path, "V10M")
        finally:
            os.remove(path)
        h, w = ts.shape[1:]
        lon = T.c + (np.arange(w) + 0.5) * T.a
        lat = T.f + (np.arange(h) + 0.5) * T.e
        lt = ((np.arange(24)[:, None] + 0.5 + lon[None, :] / 15.0) % 24.0)[:, None, :]  # (24, 1, w)
        day_m = (lt >= 6) & (lt < 18)
        ws = np.hypot(u, v)
        with np.errstate(invalid="ignore"):
            part = {
                "day_max": np.nanmax(np.where(day_m, ts, -np.inf), axis=0),
                "night_max": np.nanmax(np.where(~day_m, ts, -np.inf), axis=0),
                "night_min": np.nanmin(np.where(~day_m, ts, np.inf), axis=0),
                "ts_sum": np.nansum(ts, axis=0), "ts_n": np.isfinite(ts).sum(axis=0),
                "ps_sum": np.nansum(ps, axis=0), "ps_n": np.isfinite(ps).sum(axis=0),
                "ws_sum": np.nansum(ws, axis=0), "ws_n": np.isfinite(ws).sum(axis=0),
                "ws_max": np.nanmax(ws, axis=0),
            }
        with lock:
            grid.setdefault("lat", lat)
            grid.setdefault("lon", lon)
            for k, val in part.items():
                if k not in acc:
                    acc[k] = val.astype(np.float64)
                elif k.endswith("max"):
                    np.maximum(acc[k], val, out=acc[k])
                elif k.endswith("min"):
                    np.minimum(acc[k], val, out=acc[k])
                else:
                    acc[k] += val
        return len(r.content)

    t0, mb = time.time(), 0.0
    with ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(one, d): d for d in days}
        for n, f in enumerate(as_completed(futs), 1):
            mb += f.result() / 1e6
            if n % 15 == 0 or n == len(days):
                print(f"merra2 {n}/{len(days)} days, {mb / 1e3:.1f} GB, {mb / (time.time() - t0):.1f} MB/s", flush=True)

    with np.errstate(invalid="ignore", divide="ignore"):
        bands = {
            "temp_day_max_k": acc["day_max"], "temp_night_max_k": acc["night_max"],
            "temp_night_min_k": acc["night_min"], "temp_mean_k": acc["ts_sum"] / acc["ts_n"],
            "pressure_mean_pa": acc["ps_sum"] / acc["ps_n"],
            "wind_mean_ms": acc["ws_sum"] / acc["ws_n"], "wind_max_ms": acc["ws_max"],
        }
    bands = {k: np.where(np.isfinite(v), v, np.nan).astype(np.float32) for k, v in bands.items()}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT, lat=grid["lat"], lon=grid["lon"], year=YEAR, **bands)
    print("saved", OUT, {k: round(float(np.nanmean(v)), 2) for k, v in bands.items()}, flush=True)


if __name__ == "__main__":
    main()
