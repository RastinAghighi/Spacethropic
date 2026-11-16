"""
Search index for the API: the patches file turned into flat arrays it can memory-map.

    .venv/Scripts/python build_index.py                         # out/nevada_patches.npz -> out/index/
    .venv/Scripts/python build_index.py other_patches.npz out/index

The patches are read a block of rows at a time, so the build never holds them all
(10M cells are ~9 GB of patches). Written to out/index/, one .npy per array, row i
is the same cell everywhere:

    E.npy      N x NPIX float32  zero-mean disk vectors (what Index searches)
    pix.npy    N x NPIX float32  the raw disk heights (the match drawn in a response)
    n2, std    float64           squared norm and relief std of each E row
    h3         uint64            cell id (h3.str_to_int)
    lat, lon   float64
    slope, roughness, elevation, slopeMax, flatGround, heightRange, concavity   float64
"""

from __future__ import annotations

import sys
import time
import zipfile
from pathlib import Path

import h3
import numpy as np

from shape import MASK, NPIX, PX_M

ROOT = Path(__file__).parent
SRC = ROOT / "out" / "nevada_patches.npz"
OUT = ROOT / "out" / "index"
CHUNK = 1 << 14  # rows per block: ~0.4 GB of working arrays
TERRAIN = ["slope", "roughness", "elevation", "slopeMax", "flatGround", "heightRange", "concavity"]

_ii, _jj = np.mgrid[-(MASK.shape[0] // 2):MASK.shape[0] // 2 + 1, -(MASK.shape[1] // 2):MASK.shape[1] // 2 + 1]
_R = np.hypot(_ii, _jj)
CORE, RIM = _R <= 2.0, MASK & (_R >= 5.0)
_DY, _DX = MASK[1:] & MASK[:-1], MASK[:, 1:] & MASK[:, :-1]


def px(P: np.ndarray, m: np.ndarray) -> np.ndarray:
    """P[:, m], row-major: boolean indexing returns it column-major, and a row mean over that
    sums in another order than the per-patch mean (last-bit differences)."""
    return np.ascontiguousarray(P[:, m])


def terrain(P: np.ndarray) -> dict[str, np.ndarray]:
    """Per-cell values the refine drawers limit on, for a stack of float64 patches (n x SIZE x SIZE)."""
    gy, gx = np.gradient(P, PX_M, axis=(1, 2))
    s = px(np.degrees(np.arctan(np.hypot(gx, gy))), MASK)
    z = px(P, MASK)
    return {
        "slope": s.mean(1),
        "roughness": np.concatenate([px(np.abs(np.diff(P, axis=1)), _DY), px(np.abs(np.diff(P, axis=2)), _DX)], axis=1).mean(1),
        "elevation": z.mean(1),
        "slopeMax": np.percentile(s, 90, axis=1),
        "flatGround": 100 * (s < 5.0).mean(1),  # share of the cell (%) gentle enough to land or drive on
        "heightRange": z.max(1) - z.min(1),
        "concavity": px(P, CORE).mean(1) - px(P, RIM).mean(1),  # centre minus rim: negative is a bowl, positive a dome
    }


class _Rows:
    """One array of an .npz, read a block of rows at a time (np.load would inflate it whole)."""

    def __init__(self, z: zipfile.ZipFile, name: str):
        self.f = z.open(name + ".npy")
        v = np.lib.format.read_magic(self.f)
        read = np.lib.format.read_array_header_1_0 if v == (1, 0) else np.lib.format.read_array_header_2_0
        self.shape, fortran, self.dtype = read(self.f)
        assert not fortran, name
        self.row = int(np.prod(self.shape[1:], dtype=np.int64)) * self.dtype.itemsize

    def read(self, n: int) -> np.ndarray:
        return np.frombuffer(self.f.read(n * self.row), self.dtype).reshape(-1, *self.shape[1:])


def build(src: Path = SRC, out: Path = OUT) -> None:
    t0 = time.time()
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(src) as z:
        patches, cells = _Rows(z, "patches"), _Rows(z, "h3")
        n = patches.shape[0]
        with z.open("lat.npy") as f:
            np.save(out / "lat.npy", np.lib.format.read_array(f).astype(np.float64))
        with z.open("lon.npy") as f:
            np.save(out / "lon.npy", np.lib.format.read_array(f).astype(np.float64))
        mm = lambda name, dtype, shape=(n,): np.lib.format.open_memmap(out / f"{name}.npy", "w+", dtype, shape)
        E, pix = mm("E", np.float32, (n, NPIX)), mm("pix", np.float32, (n, NPIX))
        n2, ids = mm("n2", np.float64), mm("h3", np.uint64)
        fields = {k: mm(k, np.float64) for k in TERRAIN}
        for s in range(0, n, CHUNK):
            P = patches.read(CHUNK).astype(np.float64)
            e = s + len(P)
            x = px(P, MASK)
            E[s:e] = x - x.mean(1, keepdims=True)  # shape.vec, row by row
            n2[s:e] = (E[s:e].astype(np.float64) ** 2).sum(1)
            pix[s:e] = x
            for k, v in terrain(P).items():
                fields[k][s:e] = v
            ids[s:e] = [h3.str_to_int(str(c)) for c in cells.read(len(P))]
            print(f"\r{e:,} / {n:,} cells  {time.time() - t0:.0f}s", end="", flush=True)
        np.save(out / "std.npy", np.sqrt(n2 / NPIX))
        for a in (E, pix, n2, ids, *fields.values()):
            a.flush()
    size = sum(f.stat().st_size for f in out.glob("*.npy"))
    print(f"\n{out}: {n:,} cells, {size / 1e9:.2f} GB, {time.time() - t0:.0f}s")


if __name__ == "__main__":
    build(*(Path(a) for a in sys.argv[1:3]))
