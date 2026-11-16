"""
Terrain shape search on Earth-sized H3 resolution 7 cells.

A cell's shape is its elevation inside a disk of the res-7 cell area (5.16 km2,
radius 1.28 km) centred on the cell, sampled at 200 m and with its mean height
removed (tilt and relief are kept: they are real properties of the ground).
The same physical disk is used on every body, so a Moon or Mars patch is
compared with an Earth patch of the same size in metres.

Distance is the RMSE in metres between two patches, minimised over rotations
of the target (every 15 degrees), so the match doesn't depend on which way the
terrain faces. It is computed for every candidate as one matrix product.

Speed-up without losing matches: for zero-mean patches, RMSE(a, b) >= |std(a) - std(b)|
(triangle inequality), and rotation doesn't change std. Candidates are visited
in order of that lower bound and the search stops once the bound exceeds the
current k-th best exact distance, so the result is identical to brute force.
"""

from __future__ import annotations

import numpy as np

PX_M = 200.0  # pixel size, metres (matches the teammate's site grids)
CELL_AREA_KM2 = 5.161293  # H3 res-7 average cell area
RADIUS_PX = np.sqrt(CELL_AREA_KM2 * 1e6 / np.pi) / PX_M  # ~6.41 px
HALF = int(np.ceil(RADIUS_PX))  # patch is (2*HALF+1)^2
SIZE = 2 * HALF + 1
_ii, _jj = np.mgrid[-HALF:HALF + 1, -HALF:HALF + 1]
MASK = (_ii ** 2 + _jj ** 2) <= RADIUS_PX ** 2  # disk inside the square patch
NPIX = int(MASK.sum())
ANGLES = np.arange(0, 360, 15)


def offsets(angle_deg: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """Patch pixel offsets in metres (east, north), rotated by angle_deg."""
    a = np.radians(angle_deg)
    east, north = _jj * PX_M, -_ii * PX_M  # row 0 is north
    return east * np.cos(a) - north * np.sin(a), east * np.sin(a) + north * np.cos(a)


def bilinear(z: np.ndarray, r: np.ndarray, c: np.ndarray) -> np.ndarray:
    r0 = np.clip(np.floor(r).astype(int), 0, z.shape[0] - 2)
    c0 = np.clip(np.floor(c).astype(int), 0, z.shape[1] - 2)
    fr, fc = r - r0, c - c0
    return (z[r0, c0] * (1 - fr) * (1 - fc) + z[r0, c0 + 1] * (1 - fr) * fc
            + z[r0 + 1, c0] * fr * (1 - fc) + z[r0 + 1, c0 + 1] * fr * fc)


def vec(patch: np.ndarray) -> np.ndarray:
    """Disk pixels with the mean removed."""
    v = patch[MASK].astype(np.float64)
    return v - v.mean()


def target_variants(raster: np.ndarray, row: float, col: float, px_m: float = PX_M) -> tuple[np.ndarray, np.ndarray]:
    """The target patch at (row, col) of a local metric raster, at every rotation.

    Returns (V x NPIX zero-mean vectors, V x SIZE x SIZE patches for display)."""
    vs, ps = [], []
    for a in ANGLES:
        e, n = offsets(a)
        p = bilinear(raster, row - n / px_m, col + e / px_m)
        ps.append(p)
        vs.append(vec(p))
    return np.array(vs), np.array(ps)


class Index:
    """All candidate patches, as zero-mean disk vectors, ready to search."""

    def __init__(self, patches: np.ndarray):
        self.E = np.array([vec(p) for p in patches], dtype=np.float32)  # N x NPIX
        self.n2 = (self.E.astype(np.float64) ** 2).sum(1)
        self.std = np.sqrt(self.n2 / NPIX)

    def exact(self, T: np.ndarray, idx: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
        """RMSE (m) and best rotation index for candidates idx (all if None)."""
        E = self.E if idx is None else self.E[idx]
        n2 = self.n2 if idx is None else self.n2[idx]
        # float64: patches are stored as float32, but small RMSEs come from differences of large sums
        d2 = n2[:, None] + (T ** 2).sum(1)[None, :] - 2.0 * (E.astype(np.float64) @ T.T)
        best = d2.argmin(1)
        return np.sqrt(np.maximum(d2[np.arange(len(best)), best], 0) / NPIX), best

    def search(self, T: np.ndarray, k: int = 50, allowed: np.ndarray | None = None, prune: bool = True, chunk: int = 4096):
        """Top-k (indices, rmse, rotation index); `allowed` is a boolean pre-filter.

        Returns also how many candidates got an exact comparison."""
        cand = np.arange(len(self.E)) if allowed is None else np.flatnonzero(allowed)
        if not prune:
            rmse, rot = self.exact(T, cand)
            o = np.argsort(rmse)[:k]
            return cand[o], rmse[o], rot[o], len(cand)
        ts = np.sqrt((T ** 2).sum(1) / NPIX)  # target std per rotation
        lo, hi = ts.min(), ts.max()
        lb = np.maximum(0, np.maximum(lo - self.std[cand], self.std[cand] - hi))  # distance to [lo, hi]
        order = cand[np.argsort(lb)]
        lb_sorted = np.sort(lb)
        best_i = np.empty(0, int)
        best_r = np.empty(0)
        best_rot = np.empty(0, int)
        done = 0
        for s in range(0, len(order), chunk):
            if len(best_r) >= k and lb_sorted[s] > best_r[k - 1]:
                break  # nothing left can beat the k-th best
            idx = order[s:s + chunk]
            r, rot = self.exact(T, idx)
            done += len(idx)
            best_i = np.concatenate([best_i, idx])
            best_r = np.concatenate([best_r, r])
            best_rot = np.concatenate([best_rot, rot])
            o = np.argsort(best_r, kind="stable")[:k]
            best_i, best_r, best_rot = best_i[o], best_r[o], best_rot[o]
        return best_i, best_r, best_rot, done
