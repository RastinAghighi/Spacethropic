"""
Earth soil and surface material: WRB 2006 reference soil groups on a 0.02° grid.

    .venv/Scripts/python soil.py D:/wrb2006_points_0.02deg.csv   # ~1 min -> out/wrb_0.02deg.npz

The CSV holds one row per land cell centre (lat, lon, wrb_code, wrb_class, share). It is
packed into a global uint8 raster (0 = no data) so a lookup is one array index.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parent
OUT = ROOT / "out" / "wrb_0.02deg.npz"
STEP = 0.02
NROW, NCOL = round(180 / STEP), round(360 / STEP)


def build(csv: str) -> None:
    import pandas as pd

    grid = np.zeros((NROW, NCOL), np.uint8)
    names: dict[int, str] = {}
    for ch in pd.read_csv(csv, chunksize=4_000_000, dtype={"lat": "f8", "lon": "f8", "wrb_code": "i2", "wrb_class": "str", "share": "f4"}):
        i = np.clip(np.floor((90 - ch["lat"].to_numpy()) / STEP).astype(np.int64), 0, NROW - 1)
        j = np.clip(np.floor((ch["lon"].to_numpy() + 180) / STEP).astype(np.int64), 0, NCOL - 1)
        code = ch["wrb_code"].to_numpy()
        grid[i, j] = code + 1  # 0 stays "no data"
        for c, n in ch[["wrb_code", "wrb_class"]].drop_duplicates().itertuples(index=False):
            names[int(c)] = n
        print(f"{len(ch):,} rows", flush=True)
    OUT.parent.mkdir(exist_ok=True)
    codes = np.array(sorted(names))
    np.savez_compressed(OUT, grid=grid, codes=codes, names=np.array([names[c] for c in codes]))
    print(f"-> {OUT} ({OUT.stat().st_size / 1e6:.1f} MB), {len(names)} classes")


class Soil:
    def __init__(self, path: Path = OUT):
        d = np.load(path)
        self.grid = d["grid"]
        self.name = {int(c) + 1: str(n) for c, n in zip(d["codes"], d["names"])}

    def dominant(self, lat: float, lon: float, radius_km: float = 1.3) -> tuple[str | None, float]:
        """Most common soil group within the cell's disk, and its share of the land there."""
        r = max(1, round(radius_km / (111.32 * STEP)))
        i = int((90 - lat) / STEP)
        j = int((lon + 180) / STEP)
        w = self.grid[max(i - r, 0):i + r + 1, max(j - r, 0):j + r + 1].ravel()
        w = w[w > 0]
        if not len(w):
            return None, 0.0
        v, n = np.unique(w, return_counts=True)
        k = int(n.argmax())
        return self.name.get(int(v[k])), float(n[k] / len(w))

    def dominant_many(self, lat: np.ndarray, lon: np.ndarray, radius_km: float = 1.3, chunk: int = 1 << 20):
        """dominant() for every point at once, as grid values: (most common value, its count, land count).

        0 is no land; ties go to the smaller value, as np.unique + argmax does."""
        r = max(1, round(radius_km / (111.32 * STEP)))
        d = np.arange(-r, r + 1)
        val, cnt, land = (np.zeros(len(lat), np.uint16) for _ in range(3))
        for s in range(0, len(lat), chunk):
            i = ((90 - lat[s:s + chunk]) / STEP).astype(np.int64)[:, None, None] + d[None, :, None]
            j = ((lon[s:s + chunk] + 180) / STEP).astype(np.int64)[:, None, None] + d[None, None, :]
            ok = (i >= 0) & (i < NROW) & (j >= 0) & (j < NCOL)  # the window, cut at the grid's edges
            w = np.where(ok, self.grid[i.clip(0, NROW - 1), j.clip(0, NCOL - 1)], 0).reshape(len(ok), -1).astype(np.int64)
            c = (w[:, :, None] == w[:, None, :]).sum(2) * (w > 0)
            k = (c * 256 + 255 - w).argmax(1)
            n = np.arange(len(w))
            val[s:s + chunk], cnt[s:s + chunk], land[s:s + chunk] = w[n, k] * (c[n, k] > 0), c[n, k], (w > 0).sum(1)
        return val, cnt, land


if __name__ == "__main__":
    build(sys.argv[1])
