"""Global Moon/Mars inputs for the FeO and albedo hexagon columns (non-Earth features, user).

FeO: the site pipeline's bin tables (sources/geochem.py), burned once into 0.1 deg lookup grids
     (same values; avoids testing every bin for every hexagon).
       Moon: Lunar Prospector GRS, 2 deg equal-area bins, FeO wt%
       Mars: Odyssey GRS Fe 5x5 deg, x1.2865 -> FeO-equivalent wt%, polar regions masked (NaN)
Albedo: the site pipeline's products, downloaded whole (small):
       Moon: LOLA LDAM_10 global 10 px/deg; LDAM_50S_1000M polar (used south of 55S)
       Mars: TES Lambert albedo global mosaic, ~7.4 km

Outputs: data/interim/global/planet_feo_grids.npz and the albedo files in data/raw/global/planet/.
Usage: uv run python analysis/planet_feature_grids.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sources.albedo import LDAM_GLOBAL, LDAM_SOUTH, TES_ALBEDO  # noqa: E402
from sources.geochem import FE_TO_FEO, LP_GRS, ODY_GRS_FE, _cached  # noqa: E402

PLANET = ROOT / "data" / "raw" / "global" / "planet"
OUT = ROOT / "data" / "interim" / "global" / "planet_feo_grids.npz"
RES = 0.1


def burn(bins: np.ndarray, lon0: float) -> np.ndarray:
    """bins rows (lat0, lat1, lon0, lon1, value) -> grid (1800, 3600) on [-90,90] x [lon0, lon0+360)."""
    g = np.full((int(180 / RES), int(360 / RES)), np.nan, np.float32)
    lat_c = -90 + (np.arange(g.shape[0]) + 0.5) * RES
    lon_c = lon0 + (np.arange(g.shape[1]) + 0.5) * RES
    for la0, la1, lo0, lo1, v in bins:
        r = (lat_c >= la0) & (lat_c < la1)
        c = (lon_c >= lo0) & (lon_c < lo1)
        g[np.ix_(r, c)] = v
    return g


def fetch(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        print("have", dest.name, flush=True)
        return
    with requests.get(url, stream=True, timeout=1800) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 22):
                f.write(chunk)
        tmp.replace(dest)
    print("got", dest.name, f"{dest.stat().st_size / 1e6:.0f} MB", flush=True)


def main() -> None:
    lp = np.loadtxt(_cached(LP_GRS), usecols=(1, 2, 3, 4, 12))
    lp[:, 4] *= 100
    ody = np.loadtxt(_cached(ODY_GRS_FE), usecols=(0, 1, 2))
    ody = ody[ody[:, 2] < 9999]
    ody_bins = np.column_stack([ody[:, 0] - 2.5, ody[:, 0] + 2.5, ody[:, 1] - 2.5, ody[:, 1] + 2.5, ody[:, 2] * FE_TO_FEO])
    moon = burn(lp, -180.0 if lp[:, 2].min() < 0 else 0.0)
    moon_lon0 = -180.0 if lp[:, 2].min() < 0 else 0.0
    mars = burn(ody_bins, 0.0)  # Odyssey table longitudes are 0..360 east
    OUT.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT, moon_feo=moon, moon_lon0=moon_lon0, mars_feo=mars, mars_lon0=0.0, res=RES)
    print("feo grids", {"moon_filled": float(np.isfinite(moon).mean()), "mars_filled": float(np.isfinite(mars).mean()),
                        "moon_range": [float(np.nanmin(moon)), float(np.nanmax(moon))],
                        "mars_range": [float(np.nanmin(mars)), float(np.nanmax(mars))]}, flush=True)

    PLANET.mkdir(parents=True, exist_ok=True)
    for url, name in ((LDAM_GLOBAL + ".LBL", "moon_ldam10.lbl"), (LDAM_GLOBAL + ".IMG", "moon_ldam10.img"),
                      (LDAM_SOUTH + ".LBL", "moon_ldam50s.lbl"), (LDAM_SOUTH + ".IMG", "moon_ldam50s.img"),
                      (TES_ALBEDO, "mars_tes_albedo.tif")):
        fetch(url, PLANET / name)
    # The labels point at the original upper-case .IMG names; point them at the local copies.
    for lbl, img in (("moon_ldam10.lbl", "moon_ldam10.img"), ("moon_ldam50s.lbl", "moon_ldam50s.img")):
        p = PLANET / lbl
        t = p.read_text(errors="ignore")
        import re
        t2 = re.sub(r'(\^IMAGE\s*=\s*)"?[A-Za-z0-9_]+\.IMG"?', rf'\1"{img}"', t, flags=re.I)
        p.write_text(t2)
    print("albedo files ready", flush=True)


if __name__ == "__main__":
    main()
