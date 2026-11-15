import warnings

import numpy as np
import pytest

from spacethropic.stats import summarize


def test_unweighted_summary_ignores_nan():
    s = summarize(np.array([1.0, 2.0, 3.0, 4.0, np.nan]), percentiles=(0, 50, 100))
    assert (s["count_total"], s["count_valid"], s["count_excluded"]) == (5, 4, 1)
    assert (s["min"], s["max"], s["mean"]) == (1.0, 4.0, 2.5)
    assert s["std"] == pytest.approx(np.sqrt(1.25))
    assert (s["p0"], s["p50"], s["p100"]) == (1.0, 2.0, 4.0)  # inverted CDF


def test_weighted_summary():
    s = summarize(np.array([[0.0], [4.0]]), row_weights=[1.0, 3.0], percentiles=(50,))
    assert s["mean"] == pytest.approx(3.0)
    assert s["std"] == pytest.approx(np.sqrt((1 * 9 + 3 * 1) / 4))
    assert s["p50"] == 4.0
    assert s["weight_sum"] == 4.0


def test_row_weights_act_like_cell_areas():
    values = np.array([[10.0, 10.0, 10.0], [40.0, 40.0, np.nan]])
    s = summarize(values, row_weights=[2.0, 1.0], percentiles=())
    assert s["mean"] == pytest.approx((3 * 2 * 10 + 2 * 1 * 40) / (3 * 2 + 2 * 1))
    assert s["count_valid"] == 5


def test_mask_and_zero_weight_rows_are_excluded():
    s = summarize(np.array([[1.0, 100.0]]), mask=np.array([[True, False]]), percentiles=())
    assert (s["count_valid"], s["max"]) == (1, 1.0)
    s = summarize(np.array([[1.0], [100.0]]), row_weights=[1.0, 0.0], percentiles=())
    assert (s["count_valid"], s["max"]) == (1, 1.0)


def test_matches_numpy_reference_on_random_data():
    rng = np.random.default_rng(42)
    values = rng.gamma(2.0, 3.0, size=(60, 45)).astype(np.float32)
    values[rng.random(values.shape) < 0.1] = np.nan
    mask = rng.random(values.shape) < 0.9
    w_row = rng.uniform(0.5, 1.5, size=60)
    qs = (5, 25, 50, 75, 95)
    s = summarize(values, row_weights=w_row, mask=mask, percentiles=qs)

    keep = np.isfinite(values) & mask
    vv = values[keep].astype(np.float64)
    ww = np.broadcast_to(w_row[:, None], values.shape)[keep]
    mean = np.average(vv, weights=ww)
    assert s["count_valid"] == keep.sum()
    assert s["mean"] == pytest.approx(mean, rel=1e-12)
    assert s["std"] == pytest.approx(np.sqrt(np.average((vv - mean) ** 2, weights=ww)), rel=1e-12)
    expected = np.percentile(vv, qs, weights=ww, method="inverted_cdf")
    assert [s[f"p{q}"] for q in qs] == pytest.approx(expected.tolist(), rel=1e-12)


def test_all_missing_returns_none_without_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        s = summarize(np.full((2, 2), np.nan), percentiles=(5, 95))
    assert s["count_valid"] == 0
    assert all(s[k] is None for k in ("min", "max", "mean", "std", "p5", "p95"))
