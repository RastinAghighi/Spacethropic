"""Global Moon temperature grid from the LRO Diviner Global Cumulative Product.

Downloads all 18 ten-degree latitude-band files (data/raw/_shared/diviner/, ~156 MB each) and
reduces each with exactly the rules of sources/climate.py DivinerTemperature: bins of 0.5 deg x
0.25 h local time; day = 6 <= LT < 18; a max/min needs >= 12 bins, a mean >= 24.

Output: data/interim/global/diviner_temperature_grid.npz with the 4 temperature bands on a
360 x 720 grid (row 0 = 90S..89.5S, col 0 = 180W..179.5W).
Usage: uv run python analysis/moon_diviner_grid.py
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sources.climate import BANDS, DIVINER_GCP, DIVINER_MIN_BINS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "raw" / "_shared" / "diviner"
OUT = ROOT / "data" / "interim" / "global" / "diviner_temperature_grid.npz"


def band_names() -> list[str]:
    names = []
    for lo in range(-90, 90, 10):
        band = f"{-lo:02d}s{-(lo + 10):02d}s" if lo < 0 else f"{lo:02d}n{lo + 10:02d}n"
        names.append(f"global_cumul_avg_cyl_{band}_002.tab")
    return names


def fetch(name: str) -> Path:
    local = CACHE / name
    if not local.exists():
        with requests.get(DIVINER_GCP + name, stream=True, timeout=1800) as r:
            r.raise_for_status()
            tmp = local.with_suffix(".part")
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(1 << 22):
                    fh.write(chunk)
            tmp.replace(local)
    print("have", name, flush=True)
    return local


def reduce(path: Path, grid: np.ndarray) -> None:
    t = pd.read_csv(path, skipinitialspace=True, usecols=["clon", "clat", "ltim", "tbol"])
    t = t[t["tbol"] > 0]
    t["i"] = np.floor((t["clat"] + 90) / 0.5).astype(int)
    t["j"] = np.floor((t["clon"] + 180) / 0.5).astype(int)
    t["day"] = (t["ltim"] >= 6) & (t["ltim"] < 18)
    g = t.groupby(["i", "j"])
    day, night = t[t["day"]].groupby(["i", "j"])["tbol"], t[~t["day"]].groupby(["i", "j"])["tbol"]
    table = pd.DataFrame({
        "day_max": day.max().where(day.count() >= DIVINER_MIN_BINS),
        "night_max": night.max().where(night.count() >= DIVINER_MIN_BINS),
        "night_min": night.min().where(night.count() >= DIVINER_MIN_BINS),
        "mean": g["tbol"].mean().where(g["tbol"].count() >= 2 * DIVINER_MIN_BINS),
    })
    idx = table.index.to_frame().to_numpy()
    for b, col in enumerate(["day_max", "night_max", "night_min", "mean"]):
        grid[b, idx[:, 0], idx[:, 1]] = table[col].to_numpy()


def main() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(4) as ex:
        paths = list(ex.map(fetch, band_names()))
    grid = np.full((4, 360, 720), np.nan)
    for p in paths:
        reduce(p, grid)
        print("reduced", p.name, flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT, **{b: grid[k].astype(np.float32) for k, b in enumerate(BANDS)})
    print("saved", OUT, "filled cells per band", [int(np.isfinite(grid[k]).sum()) for k in range(4)], "of", 360 * 720, flush=True)


if __name__ == "__main__":
    main()
