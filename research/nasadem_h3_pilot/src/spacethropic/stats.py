"""NaN-aware, area-weighted summary statistics for gridded layers.

On a latitude/longitude grid each sample stands for a ground area proportional
to cos(latitude), so means, standard deviations and percentiles are weighted by
cell area. They describe the *surface*, not the sample count. Cell area depends
only on the row (latitude), so weights are passed per row: this avoids
full-size weight arrays and keeps a 3601 x 3601 tile within a few hundred MB.
NaNs, masked-out samples and rows with zero/non-finite weight are excluded and counted.
"""

from __future__ import annotations

import numpy as np

DEFAULT_PERCENTILES: tuple[float, ...] = (5.0, 25.0, 50.0, 75.0, 95.0)
STAT_KEYS = ("min", "max", "mean", "std")


def _pct_key(q: float) -> str:
    return f"p{q:g}"


def summarize(values, row_weights=None, mask=None, percentiles=DEFAULT_PERCENTILES, block_rows: int = 256) -> dict:
    """Summary statistics of a 1-D or 2-D array, ignoring NaNs.

    ``row_weights`` gives one weight per row (e.g. cell area in m^2); a 1-D input is
    a single row. ``mask`` (same shape, True = include) restricts the samples.
    ``std`` is the weighted population standard deviation. Percentiles use the
    weighted inverted-CDF rule: the smallest value whose cumulative weight reaches
    q% of the total. With no valid samples every statistic is None.
    """
    v = np.asarray(values)
    if v.ndim == 1:
        v = v[None, :]
    if v.ndim != 2:
        raise ValueError(f"values must be 1-D or 2-D, got shape {v.shape}")
    nr = v.shape[0]
    w = np.ones(nr) if row_weights is None else np.asarray(row_weights, dtype=np.float64).reshape(-1)
    if w.shape != (nr,):
        raise ValueError(f"row_weights must have one value per row ({nr}), got {w.shape}")

    ok = np.isfinite(v)
    if mask is not None:
        m = np.asarray(mask, dtype=bool)
        ok &= m[None, :] if m.ndim == 1 else m
    good_row = np.isfinite(w) & (w > 0)
    ok &= good_row[:, None]
    w = np.where(good_row, w, 0.0)

    n_row = np.count_nonzero(ok, axis=1)
    n_valid = int(n_row.sum())
    out: dict = {"count_total": int(v.size), "count_valid": n_valid, "count_excluded": int(v.size) - n_valid}
    keys = list(STAT_KEYS) + [_pct_key(q) for q in percentiles]
    if n_valid == 0:
        out.update({k: None for k in keys})
        out["weight_sum"] = 0.0
        return out

    wsum = float(np.dot(w, n_row))
    mean = float(np.dot(w, np.sum(v, axis=1, where=ok, dtype=np.float64)) / wsum)
    ss_row = np.zeros(nr)
    for r0 in range(0, nr, block_rows):  # second pass, in blocks, for a stable variance
        blk = slice(r0, r0 + block_rows)
        d = v[blk].astype(np.float64) - mean
        np.multiply(d, d, out=d)
        ss_row[blk] = np.sum(d, axis=1, where=ok[blk])
    std = float(np.sqrt(np.dot(w, ss_row) / wsum))
    out.update(
        {
            "min": float(np.min(v, where=ok, initial=np.inf)),
            "max": float(np.max(v, where=ok, initial=-np.inf)),
            "mean": mean,
            "std": std,
        }
    )
    if percentiles:
        vv = v[ok]
        row_id = np.repeat(np.arange(nr, dtype=np.min_scalar_type(nr)), n_row)  # row of each vv entry
        order = np.argsort(vv, kind="stable")
        cum_w = w[row_id[order]]
        del row_id
        np.cumsum(cum_w, out=cum_w)
        targets = np.asarray(percentiles, dtype=np.float64) / 100.0 * cum_w[-1]
        pos = np.minimum(np.searchsorted(cum_w, targets, side="left"), vv.size - 1)
        out.update({_pct_key(q): float(vv[order[p]]) for q, p in zip(percentiles, pos)})
    out["weight_sum"] = wsum
    return out
