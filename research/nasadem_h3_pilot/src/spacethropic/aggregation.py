"""Group per-sample measurements by cell key and compute area-weighted cell statistics.

This module is independent of H3 and of NASADEM. A "cell" is any integer key (an
H3 index here), and a "sample" is one raster pixel with a ground area. Statistics
come from the validated ``stats.summarize`` applied to each cell's own samples, so
the definitions are identical to the tile/AOI summaries:

* means are weighted by sample ground area;
* percentiles use the weighted inverted-CDF rule on the cell's pooled samples, and
  are never formed by averaging percentiles of sub-areas (they are not mergeable);
* min/max are plain extremes of the valid samples;
* a sample counts for a measurement only if it passes the analysis mask and its
  value is finite.

Grouping uses one stable sort, so each cell's samples keep their input order. The
output is ordered by ascending cell key, which makes it deterministic and
independent of input order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np

from .stats import summarize

_PCT = re.compile(r"p(\d+(?:\.\d+)?)")
_PLAIN = ("mean", "min", "max", "std")


def _parse_statistics(names: Sequence[str]) -> tuple[dict[str, str], tuple[float, ...]]:
    """Map each requested statistic to its ``summarize`` key, and collect the percentiles."""
    keys, pcts = {}, []
    for name in names:
        if name in _PLAIN:
            keys[name] = name
            continue
        m = _PCT.fullmatch(name)
        if m is None or not 0.0 <= float(m.group(1)) <= 100.0:
            raise ValueError(f"unknown statistic {name!r}; use mean/min/max/std or pNN (0-100)")
        q = float(m.group(1))
        pcts.append(q)
        keys[name] = f"p{q:g}"  # the key summarize() uses
    return keys, tuple(dict.fromkeys(pcts))


def _flat(a, n: int, name: str, dtype=None) -> np.ndarray:
    arr = np.asarray(a, dtype=dtype).reshape(-1)
    if arr.size != n:
        raise ValueError(f"{name} has {arr.size} samples, expected {n}")
    return arr


@dataclass
class CellAggregates:
    """Per-cell results, one entry per cell in ascending key order."""

    cell_ids: np.ndarray  # (K,) unique keys, ascending
    n_samples: np.ndarray  # (K,) all samples assigned to the cell
    sample_area_m2: np.ndarray  # (K,) ground area of those samples
    n_included: np.ndarray  # (K,) samples passing the analysis mask
    included_area_m2: np.ndarray
    counts: dict[str, np.ndarray] = field(default_factory=dict)  # named per-cell sample counts
    measurements: dict[str, dict[str, np.ndarray]] = field(default_factory=dict)
    # Grouping index: samples of cell k are sample_order[group_bounds[k]:group_bounds[k + 1]].
    sample_order: np.ndarray | None = None
    group_bounds: np.ndarray | None = None

    def __len__(self) -> int:
        return int(self.cell_ids.size)

    def samples_of(self, k: int) -> np.ndarray:
        return self.sample_order[self.group_bounds[k] : self.group_bounds[k + 1]]


def aggregate_samples(
    cell_ids,
    sample_area_m2,
    values: Mapping[str, np.ndarray],
    include,
    statistics: Mapping[str, Sequence[str]],
    count_masks: Mapping[str, np.ndarray] | None = None,
) -> CellAggregates:
    """Aggregate per-sample values into per-cell statistics.

    Parameters
    ----------
    cell_ids : (N,) integer keys, one per sample (any shape; flattened in C order).
    sample_area_m2 : (N,) positive ground area of each sample (the weights).
    values : measurement name -> (N,) per-sample values; NaN marks an invalid sample.
    include : (N,) bool analysis mask (e.g. valid land samples).
    statistics : measurement name -> statistics to report, e.g. ("mean", "p50", "p95").
        ``count_valid`` and ``valid_area_m2`` are always reported.
    count_masks : name -> (N,) bool; the number of True samples per cell is reported.
    """
    ids = np.asarray(cell_ids).reshape(-1)
    n = ids.size
    if n == 0:
        raise ValueError("no samples to aggregate")
    if not np.issubdtype(ids.dtype, np.integer):
        raise TypeError(f"cell_ids must be integers, got {ids.dtype}")
    w = _flat(sample_area_m2, n, "sample_area_m2", np.float64)
    if not np.all(np.isfinite(w) & (w > 0)):
        raise ValueError("sample areas must be finite and positive")
    inc = _flat(include, n, "include", bool)

    keys, inverse = np.unique(ids, return_inverse=True)
    k = keys.size
    order = np.argsort(inverse, kind="stable")
    counts = np.bincount(inverse, minlength=k)
    bounds = np.concatenate([[0], np.cumsum(counts)])

    out = CellAggregates(
        cell_ids=keys,
        n_samples=counts.astype(np.int64),
        sample_area_m2=np.bincount(inverse, weights=w, minlength=k),
        n_included=np.bincount(inverse[inc], minlength=k).astype(np.int64),
        included_area_m2=np.bincount(inverse[inc], weights=w[inc], minlength=k),
        sample_order=order,
        group_bounds=bounds,
    )
    for name, m in (count_masks or {}).items():
        mm = _flat(m, n, f"count mask {name!r}", bool)
        out.counts[name] = np.bincount(inverse[mm], minlength=k).astype(np.int64)

    for name, wanted in statistics.items():
        if name not in values:
            raise KeyError(f"no values supplied for measurement {name!r}")
        v = _flat(values[name], n, f"values[{name!r}]")
        stat_keys, pcts = _parse_statistics(wanted)
        res = {"count_valid": np.zeros(k, dtype=np.int64), "valid_area_m2": np.zeros(k)}
        res.update({stat: np.full(k, np.nan) for stat in stat_keys})
        for j in range(k):
            idx = order[bounds[j] : bounds[j + 1]]
            s = summarize(v[idx][:, None], row_weights=w[idx], mask=inc[idx][:, None], percentiles=pcts)
            res["count_valid"][j] = s["count_valid"]
            res["valid_area_m2"][j] = s["weight_sum"]
            for stat, key in stat_keys.items():
                if s[key] is not None:
                    res[stat][j] = s[key]
        out.measurements[name] = res
    return out

