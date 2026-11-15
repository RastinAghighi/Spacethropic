"""Remaining feature columns per hexagon (dimensions 4 water/ice and 5 dust), one pass per body.

User (2026-11-15): "just as much information as possible", "all in one go for each planet".
So every product that covers a whole body (or a large region of it) becomes its own column in
its native units, with NaN where the product has no coverage; nothing is harmonised across
bodies. Each source value is taken from the cell or pixel that contains the hexagon centre.

  body   columns                                             source
  earth  soil_moisture_m3m3__mean/__max, _valid_days         ESA CCI SM v09.2 COMBINED, daily 2023, 0.25 deg
         permafrost_pct, active_layer_m                      ESA CCI Permafrost v5 2023, 0.01 deg, 25-85 N
         dust_aod_mean/_max, dust_surface_kgm3,              MERRA-2 M2TMNXAER monthly 2023 (DUEXTTAU,
         dust_column_kgm2, aerosol_aod_mean                  DUSMASS, DUCMASS, TOTEXTTAU), 0.5 x 0.625 deg
  moon   hydrogen_ppm                                        Lunar Prospector NS, 0.5 deg
         psr_flag, sun_visibility                            LOLA LPSR / AVGVISIB 85S, 60 m (south cap only)
  mars   h2o_wt_pct, h2o_sigma_wt_pct                        Odyssey GRS smoothed 5 deg, +-57.5 deg
         neutron_{epithermal,thermal,fast}_cps               Odyssey NS 2002 maps, 0.5 deg
         hend_epithermal_norm                                Odyssey HEND 2002, 4 deg (normalised; x0.26 = c/s)
         dust_cover_index                                    TES DCI 16 ppd (0.85 fill -> NaN), +-60 deg
         dust_tau_mean/_max                                  Montabone CDOD 9.3 um, MY32/33/35 sols, 3 deg
         dust_mass_mean/_max, h2o_vapour_mass_mean,          Ames Mars GCM climatology (already built),
         pressure_min_pa, pressure_max_pa                    bilinear like the other GCM columns

Step 1 builds north-up lookup grids as .npy files (memory-mapped by the workers) in
data/interim/global/extras/. Step 2 rewrites each table atomically with the body's columns.
Usage: uv run python analysis/hex_extras.py build
       uv run python analysis/hex_extras.py run --bodies earth [--workers 12]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from functools import cache
from pathlib import Path

for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hex_features as hf  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PRE = ROOT / "data" / "raw" / "_shared" / "prefetch"
GRIDS = ROOT / "data" / "interim" / "global" / "extras"
DATASETS = {"earth": hf.DATASETS["earth"][:1], "moon": hf.DATASETS["moon"], "mars": hf.DATASETS["mars"]}  # follows HEX_RES
MERRA_AER = ("https://opendap.earthdata.nasa.gov/collections/C1276812866-GES_DISC/granules/"
             "M2TMNXAER.5.12.4%3AMERRA2_400.tavgM_2d_aer_Nx.2023{mm}.nc4.dap.nc4"
             "?dap4.ce=/DUEXTTAU;/DUSMASS;/DUCMASS;/TOTEXTTAU;/lat;/lon;/time")
GCM = {"dust_mass_mean": "dust_mass_mean", "dust_mass_max": "dust_mass_max",
       "h2o_vapour_mass_mean": "h2o_vap_mass_mean", "pressure_min_pa": "psurf_min_pa", "pressure_max_pa": "psurf_max_pa"}
COLUMNS = {
    "earth": ["soil_moisture_m3m3__mean", "soil_moisture_m3m3__max", "soil_moisture_valid_days",
              "permafrost_pct", "active_layer_m",
              "dust_aod_mean", "dust_aod_max", "dust_surface_kgm3", "dust_column_kgm2", "aerosol_aod_mean"],
    "moon": ["hydrogen_ppm", "psr_flag", "sun_visibility"],
    "mars": ["h2o_wt_pct", "h2o_sigma_wt_pct", "neutron_epithermal_cps", "neutron_thermal_cps", "neutron_fast_cps",
             "hend_epithermal_norm", "dust_cover_index", "dust_tau_mean", "dust_tau_max", *GCM],
}
PROVENANCE = {
    "earth": "ESA CCI SM v09.2 COMBINED daily 2023 (0.25 deg; mean/max over valid days); ESA CCI Permafrost v5 2023 "
             "PFR/ALT (0.01 deg, 25-85 N; 255/65535 fill = NaN); MERRA-2 M2TMNXAER monthly 2023 DUEXTTAU/DUSMASS/"
             "DUCMASS/TOTEXTTAU (mean of 12 months, max monthly DUEXTTAU); containing cell",
    "moon": "Lunar Prospector NS hydrogenhd 0.5 deg H ppm; LOLA LPSR_85S_060M and AVGVISIB_85S_060M (2016), "
            "south of ~85 S only; containing bin/pixel",
    "mars": "Odyssey GRS H2O smoothed 5x5 (+-57.5 deg); Odyssey NS 2002 epithermal/thermal/fast c/s 0.5 deg; HEND "
            "epithermal 4 deg normalised; TES DCI 16 ppd (0.85 = NaN); Montabone CDOD 9.3 um cdodtot MY32/33/35 "
            "(mean/max over sols); containing bin/pixel. Ames GCM dust/H2O vapour/pressure min-max, bilinear",
}


# ---------------------------------------------------------------- step 1: lookup grids

def save(name: str, a: np.ndarray, top: float, left: float, dlat: float, dlon: float) -> None:
    """a is north-up: row 0 starts at latitude `top`, column 0 at longitude `left`."""
    GRIDS.mkdir(parents=True, exist_ok=True)
    np.save(GRIDS / f"{name}.npy", a)
    meta = json.loads((GRIDS / "grids.json").read_text()) if (GRIDS / "grids.json").exists() else {}
    meta[name] = {"top": top, "left": left, "dlat": dlat, "dlon": dlon, "shape": list(a.shape), "dtype": str(a.dtype)}
    (GRIDS / "grids.json").write_text(json.dumps(meta, indent=1))
    print(f"  {name}: {a.shape} {a.dtype}, finite {np.isfinite(a.astype(np.float32)).mean():.1%}", flush=True)


def nc(path: str, var: str):
    import rasterio
    with rasterio.open(f'NETCDF:"{path}":{var}') as s:
        return s.read(), s.transform


def bin_table(rows: np.ndarray, top: float, left: float, d: float, h: int, w: int) -> np.ndarray:
    """rows: (n, 3) of (lat_centre, lon_centre, value) -> north-up grid."""
    g = np.full((h, w), np.nan, np.float32)
    i = np.floor((top - rows[:, 0]) / d).astype(int)
    j = np.floor(((rows[:, 1] - left) % 360) / d).astype(int) % w
    ok = (i >= 0) & (i < h)
    g[i[ok], j[ok]] = rows[ok, 2]
    return g


def build_earth() -> None:
    files = sorted(glob.glob(str(PRE / "esacci_sm_v09.2" / "*.nc")))
    s = n = mx = None
    for f in files:
        a, T = nc(f, "sm")
        a = a[0].astype(np.float32)
        a[a < 0] = np.nan
        if s is None:
            s, n, mx = np.zeros_like(a, np.float64), np.zeros(a.shape, np.int16), np.full_like(a, -np.inf)
        ok = np.isfinite(a)
        s[ok] += a[ok]
        n += ok
        mx = np.fmax(mx, a)
    with np.errstate(invalid="ignore", divide="ignore"):
        save("soil_moisture_m3m3__mean", np.where(n > 0, s / n, np.nan).astype(np.float32), T.f, T.c, -T.e, T.a)
    save("soil_moisture_m3m3__max", np.where(n > 0, mx, np.nan).astype(np.float32), T.f, T.c, -T.e, T.a)
    save("soil_moisture_valid_days", np.where(n > 0, n, np.nan).astype(np.float32), T.f, T.c, -T.e, T.a)
    print(f"  soil moisture from {len(files)} daily files", flush=True)

    # GDAL reports top = 90 N for these files; the data actually start at 85 N (pitfall in PREFETCH.md)
    pf = PRE / "esacci_permafrost_v5"
    a, T = nc(str(next(pf.glob("*PFR*"))), "PFR")
    save("permafrost_pct", a[0], 85.0, T.c, 0.01, 0.01)  # uint8, 255 = fill (handled at lookup)
    a, T = nc(str(next(pf.glob("*ALT*"))), "ALT")
    save("active_layer_m", a[0], 85.0, T.c, 0.01, 0.01)  # uint16 x 0.01, 65535 = fill

    import requests
    auth = {"Authorization": f"Bearer {hf_token()}"}
    months = {}
    for mm in range(1, 13):
        url = MERRA_AER.format(mm=f"{mm:02d}")
        for attempt in range(5):
            try:
                r = requests.get(url, headers=auth, timeout=600)
                r.raise_for_status()
                break
            except Exception:  # noqa: BLE001
                if attempt == 4:
                    raise
                time.sleep(10 * (attempt + 1))
        fd, path = tempfile.mkstemp(suffix=".nc4")
        with os.fdopen(fd, "wb") as f:
            f.write(r.content)
        try:
            for v in ("DUEXTTAU", "DUSMASS", "DUCMASS", "TOTEXTTAU"):
                a, T = nc(path, v)
                a = a[0].astype(np.float64)
                a[a > 1e14] = np.nan
                months.setdefault(v, []).append(a)
        finally:
            os.remove(path)
    st = {v: np.stack(m) for v, m in months.items()}
    g = dict(top=T.f, left=T.c, dlat=-T.e, dlon=T.a)
    save("dust_aod_mean", np.nanmean(st["DUEXTTAU"], 0).astype(np.float32), **g)
    save("dust_aod_max", np.nanmax(st["DUEXTTAU"], 0).astype(np.float32), **g)
    save("dust_surface_kgm3", np.nanmean(st["DUSMASS"], 0).astype(np.float32), **g)
    save("dust_column_kgm2", np.nanmean(st["DUCMASS"], 0).astype(np.float32), **g)
    save("aerosol_aod_mean", np.nanmean(st["TOTEXTTAU"], 0).astype(np.float32), **g)


def hf_token() -> str:
    import earth_merra2_climate
    return earth_merra2_climate.token()


def build_moon() -> None:
    rows = []
    for line in (PRE / "lp_ns_hydrogen" / "hydrogenhd.txt").read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        p = [x.strip() for x in line.split(",")]
        try:
            v = float(p[4])
        except ValueError:  # one '**********' overflow bin
            v = np.nan
        rows.append(((float(p[0]) + float(p[1])) / 2, (float(p[2]) + float(p[3])) / 2, v))
    save("hydrogen_ppm", bin_table(np.array(rows), 90.0, -180.0, 0.5, 360, 720), 90.0, -180.0, 0.5, 0.5)


def read_table(path: Path, cols: int) -> np.ndarray:
    out = []
    for line in path.read_text().splitlines():
        p = line.replace(",", " ").split()
        if len(p) >= cols:
            try:
                out.append([float(x) for x in p[:cols]])
            except ValueError:
                continue
    return np.array(out)


def build_mars() -> None:
    t = read_table(PRE / "ody_grs_h2o" / "h2o_sr_5x5.tab", 5)  # LAT, LON, CONC, SIGMA, SIGMA_CFS
    t[t >= 9999] = np.nan
    save("h2o_wt_pct", bin_table(t[:, [0, 1, 2]], 90.0, 0.0, 5.0, 36, 72), 90.0, 0.0, 5.0, 5.0)
    save("h2o_sigma_wt_pct", bin_table(t[:, [0, 1, 3]], 90.0, 0.0, 5.0, 36, 72), 90.0, 0.0, 5.0, 5.0)

    for kind in ("epithermal", "thermal", "fast"):
        t = read_table(PRE / "ody_neutron_2002" / f"ns_{kind}_020917.tab", 3)  # LON, LAT, value
        v = t[:, 2].copy()
        v[(v <= -99) | ((kind == "epithermal") & (v == 0))] = np.nan  # fills
        save(f"neutron_{kind}_cps", bin_table(np.c_[t[:, 1], t[:, 0], v], 90.0, 0.0, 0.5, 360, 720), 90.0, 0.0, 0.5, 0.5)
    t = read_table(PRE / "ody_neutron_2002" / "hend_epithermal_020917.tab", 3)
    save("hend_epithermal_norm", bin_table(np.c_[t[:, 1], t[:, 0], t[:, 2]], 90.0, -180.0, 4.0, 45, 90), 90.0, -180.0, 4.0, 4.0)

    # ISIS2 qube: 2 label records of 512 bytes, then float32 LE (5760 samples x 2880 lines)
    a = np.fromfile(PRE / "tes_dci" / "dci_lo_ice_dust_16ppd_shifted.pds", "<f4", count=5760 * 2880, offset=1024)
    a = a.reshape(2880, 5760).copy()
    a[np.isclose(a, 0.85) | (a <= 0)] = np.nan
    save("dust_cover_index", a, 90.0, -180.0, 1 / 16, 1 / 16)

    sols = []
    for f in sorted((PRE / "mars_cdod_montabone").glob("*.nc")):
        a, T = nc(str(f), "cdodtot")
        a = a.astype(np.float32)
        a[a > 1e30] = np.nan
        sols.append(a)
    sols = np.concatenate(sols)
    save("dust_tau_mean", np.nanmean(sols, 0), T.f, T.c, -T.e, T.a)
    save("dust_tau_max", np.nanmax(sols, 0), T.f, T.c, -T.e, T.a)


# ---------------------------------------------------------------- step 2: per-hexagon columns

@cache
def grid(name: str):
    m = json.loads((GRIDS / "grids.json").read_text())[name]
    return np.load(GRIDS / f"{name}.npy", mmap_mode="r"), m


def lookup(name: str, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    a, m = grid(name)
    h, w = a.shape
    i = np.floor((m["top"] - lat) / m["dlat"]).astype(np.int64)
    j = np.floor(((lon - m["left"]) % 360) / m["dlon"]).astype(np.int64) % w
    ok = (i >= 0) & (i < h)
    out = np.full(lat.shape, np.nan, np.float32)
    if ok.any():
        v = a[i[ok], j[ok]].astype(np.float32)
        if name == "permafrost_pct":
            v[v == 255] = np.nan
        elif name == "active_layer_m":
            v[v == 65535] = np.nan
            v *= 0.01
        out[ok] = v
    return out


def values(body: str, lat: np.ndarray, lon: np.ndarray) -> dict[str, np.ndarray]:
    if body == "moon":
        out = {"hydrogen_ppm": lookup("hydrogen_ppm", lat, lon)}
        for col, name in (("psr_flag", "LPSR_85S_060M_201608.LBL"), ("sun_visibility", "AVGVISIB_85S_060M_201608.LBL")):
            v = np.full(lat.shape, np.nan, np.float32)
            south = lat < -84
            if south.any():  # the polar map only covers ~85 S to the pole; don't load it otherwise
                v[south] = sample_lola(name, lat[south], lon[south])
            out[col] = v
        return out
    out = {c: lookup(c, lat, lon) for c in COLUMNS[body] if c not in GCM}
    if body == "mars":
        value_at, _ = hf.mgcm_interpolators(tuple(GCM.values()))
        out.update(zip(GCM, value_at(lat, lon)))
    return out


def sample_lola(name: str, lat, lon):
    """Containing pixel of a LOLA polar-stereographic map (same method as the albedo sampler)."""
    a, T, tr = _lola(name)
    x, y = tr.transform(lon, lat)
    c = np.floor((np.asarray(x) - T.c) / T.a).astype(int)
    r = np.floor((np.asarray(y) - T.f) / T.e).astype(int)
    ok = (r >= 0) & (r < a.shape[0]) & (c >= 0) & (c < a.shape[1])
    out = np.full(np.shape(lat), np.nan, np.float32)
    out[ok] = a[r[ok], c[ok]]
    return out


@cache
def _lola(name: str):
    import rasterio
    from pyproj import Transformer
    with rasterio.open(PRE / "lola_psr" / name) as s:
        a = s.read(1).astype(np.float32) * np.float32(s.scales[0]) + np.float32(s.offsets[0])
        tr = Transformer.from_crs("+proj=longlat +R=1737400 +no_defs", s.crs, always_xy=True)
        return a, s.transform, tr


def update_tile(path: str, body: str) -> int:
    t = pq.read_table(path)
    lat, lon = t.column("lat").to_numpy(), t.column("lon").to_numpy()
    new = values(body, lat, lon) if t.num_rows else {c: np.zeros(0) for c in COLUMNS[body]}
    for c in COLUMNS[body]:
        arr = pa.array(np.asarray(new[c], np.float32), pa.float32())
        t = t.set_column(t.schema.get_field_index(c), c, arr) if c in t.column_names else t.append_column(c, arr)
    tmp = path + ".tmp"
    pq.write_table(t, tmp, compression="zstd")
    os.replace(tmp, path)
    return t.num_rows


def run(bodies: list[str], workers: int) -> None:
    for body in bodies:  # user order: one body at a time
        jobs = [(str(ds / "tiles" / f"{tile}.hexes.parquet"), ds) for ds in DATASETS[body] if (ds / "done.txt").exists()
                for tile in (ds / "done.txt").read_text().split()]
        print(f"extras {body}: {len(jobs)} tile tables, columns {COLUMNS[body]}", flush=True)
        t0, rows, done = time.time(), 0, 0
        with ProcessPoolExecutor(workers) as ex:
            futs = [ex.submit(update_tile, p, body) for p, _ in jobs]
            for f in as_completed(futs):
                rows += f.result()
                done += 1
                if done % 2000 == 0 or done == len(jobs):
                    print(f"extras {body}: {done}/{len(jobs)} tables, {rows:,} hexagons, {time.time() - t0:.0f} s", flush=True)
        for ds in DATASETS[body]:
            mp = ds / "manifest.json"
            if mp.exists():
                m = json.loads(mp.read_text())
                m.setdefault("features", {})["extras"] = {"columns": COLUMNS[body], "source": PROVENANCE[body]}
                tmp = mp.with_suffix(".tmp")
                tmp.write_text(json.dumps(m, indent=2))
                os.replace(tmp, mp)
        print(f"extras {body}: done", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=("build", "run"))
    ap.add_argument("--bodies", default="earth,moon,mars")
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()
    bodies = a.bodies.split(",")
    if a.step == "build":
        for b in bodies:
            print(f"build {b}", flush=True)
            {"earth": build_earth, "moon": build_moon, "mars": build_mars}[b]()
    else:
        run(bodies, a.workers)


if __name__ == "__main__":
    main()
