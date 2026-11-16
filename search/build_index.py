"""
Search index for the API: the patches file turned into flat arrays it can memory-map.

    .venv/Scripts/python build_index.py                         # out/nevada_patches.npz -> out/index/
    .venv/Scripts/python build_index.py other_patches.npz out/index
    .venv/bin/python build_index.py /srv/build/shards out/global --mask /srv/build   # every shard so far; re-run for more

The patches are read and the arrays written a block of rows at a time, so the build
never holds them all (10M cells are ~9 GB of patches). Written to out/index/, one .npy per array, row i
is the same cell everywhere:

    E.npy      N x NPIX float32  zero-mean disk vectors (what Index searches)
    pix.npy    N x NPIX float32  the raw disk heights (the match drawn in a response)
    n2, std    float64           squared norm and relief std of each E row
    h3         uint64            cell id (h3.str_to_int)
    lat, lon   float64
    slope, roughness, elevation, slopeMax, flatGround, heightRange, concavity   float64
    wrb, env_*  (with --mask only) WRB class code per cell (255 = ice), climate from the 10-degree grid
"""

from __future__ import annotations

import shutil
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
ENV = ["tair_mean", "tsurf_min", "tsurf_max", "rh", "wind", "sw", "tair_range", "dust_conc", "ps", "cloud", "dust_aod"]
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


class _Out:
    """An .npy written a block of rows at a time (appended: a writable memmap grows the
    process's committed memory on Windows)."""

    def __init__(self, path: Path, dtype, shape: tuple):
        self.f = open(path, "wb")
        np.lib.format.write_array_header_2_0(self.f, {"descr": np.lib.format.dtype_to_descr(np.dtype(dtype)), "fortran_order": False, "shape": shape})
        self.dtype = dtype

    def write(self, a) -> None:
        self.f.write(np.ascontiguousarray(a, self.dtype).tobytes())


def build(srcs: list[Path], out: Path = OUT, mask: Path | None = None) -> None:
    """srcs: patches files (h3 as strings or uint64), concatenated in order. mask: the global
    mask folder (h3.npy, wrb.npy) - then the WRB class per cell (255 = ice) and climate from
    the Earth 10-degree grid are written too, as analogs.duckdb holds climate for Nevada only."""
    t0 = time.time()
    tmp = out.with_name(out.name + ".tmp")  # built aside, then swapped in: a running API keeps its open files
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    zs = [zipfile.ZipFile(f) for f in srcs]
    n = sum(_Rows(z, "patches").shape[0] for z in zs)
    lat = np.concatenate([np.lib.format.read_array(z.open("lat.npy")).astype(np.float64) for z in zs])
    lon = np.concatenate([np.lib.format.read_array(z.open("lon.npy")).astype(np.float64) for z in zs])
    np.save(tmp / "lat.npy", lat), np.save(tmp / "lon.npy", lon)
    w = {k: _Out(tmp / f"{k}.npy", np.float32, (n, NPIX)) for k in ("E", "pix")}
    w |= {k: _Out(tmp / f"{k}.npy", np.float64, (n,)) for k in ("n2", "std", *TERRAIN)}
    w["h3"] = _Out(tmp / "h3.npy", np.uint64, (n,))
    done = 0
    for z in zs:
        patches, cells = _Rows(z, "patches"), _Rows(z, "h3")
        for _ in range(0, patches.shape[0], CHUNK):
            P = patches.read(CHUNK).astype(np.float64)
            x = px(P, MASK)
            E = (x - x.mean(1, keepdims=True)).astype(np.float32)  # shape.vec, row by row
            n2 = (E.astype(np.float64) ** 2).sum(1)
            w["E"].write(E), w["pix"].write(x), w["n2"].write(n2), w["std"].write(np.sqrt(n2 / NPIX))
            for k, v in terrain(P).items():
                w[k].write(v)
            c = cells.read(len(P))
            w["h3"].write([h3.str_to_int(str(i)) for i in c] if c.dtype.kind == "U" else c.astype(np.uint64))
            done += len(P)
            print(f"\r{done:,} / {n:,} cells  {time.time() - t0:.0f}s", end="", flush=True)
        z.close()
    for o in w.values():
        o.f.close()
    if mask is not None:
        ids = np.load(tmp / "h3.npy")
        m_ids, m_wrb = np.load(mask / "h3.npy"), np.load(mask / "wrb.npy")
        o = np.argsort(m_ids)
        at = o[np.searchsorted(m_ids, ids, sorter=o).clip(0, len(o) - 1)]
        np.save(tmp / "wrb.npy", np.where(m_ids[at] == ids, m_wrb[at], 254).astype(np.uint8))  # 255 = ice, 254 = not in the mask
        del ids, m_ids, m_wrb, o, at
        sys.path.insert(0, str(ROOT.parent / "db"))
        from lookup import grid
        g = grid("earth")
        # A grid point with no value takes the nearest one that has it (else ice-sheet cells get NaN, which JSON can't carry)
        la, lo = np.meshgrid(np.radians(g.lat), np.radians(g.lon), indexing="ij")
        for k in ENV:
            z, ok = g.z[k], np.isfinite(g.z[k])
            for i, j in zip(*np.nonzero(~ok)):
                d = np.sin(la[ok]) * np.sin(la[i, j]) + np.cos(la[ok]) * np.cos(la[i, j]) * np.cos(lo[ok] - lo[i, j])
                z[i, j] = z[ok][d.argmax()]
        env, B = {k: np.empty(n) for k in ENV}, 1 << 20
        for s in range(0, n, B):
            v = g(lat[s:s + B], lon[s:s + B])
            for k in ENV:
                env[k][s:s + B] = v[k]
        for k in ENV:
            np.save(tmp / f"env_{k}.npy", env[k])
    shutil.rmtree(out, ignore_errors=True)
    tmp.rename(out)
    size = sum(f.stat().st_size for f in out.glob("*.npy"))
    print(f"\n{out}: {n:,} cells, {size / 1e9:.2f} GB, {time.time() - t0:.0f}s")


if __name__ == "__main__":
    a = sys.argv[1:]
    mask = Path(a.pop(a.index("--mask") + 1)) if "--mask" in a else None
    a = [x for x in a if x != "--mask"]
    src = Path(a[0]) if a else SRC
    build(sorted(src.glob("*.npz")) if src.is_dir() else [src], Path(a[1]) if len(a) > 1 else OUT, mask)
