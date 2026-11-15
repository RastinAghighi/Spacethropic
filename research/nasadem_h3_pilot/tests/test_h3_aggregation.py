"""H3 aggregation tests (DRUMHELLER-PILOT-03).

Expected values come from hand calculation, from numpy's own weighted percentiles
(``np.percentile(..., weights=, method="inverted_cdf")``), or from H3 calls made
through a different API path (the default string API, ``cells_to_geo``), never
from the code under test. The real-granule tests are skipped if the ZIP is absent.
"""

import csv
import json
import math
import zipfile
from pathlib import Path

import h3
import numpy as np
import pytest

from spacethropic import geodesy, h3grid
from spacethropic.aggregation import aggregate_samples
from spacethropic.cli import main as terrain_main
from spacethropic.h3_cli import main as h3_main
from spacethropic.h3_outputs import cells_feature_collection, write_cells_csv
from spacethropic.h3_pipeline import aggregate_terrain, reconcile, stat_column
from spacethropic.nasadem import BBox, GeoGrid
from spacethropic.pipeline import AnalysisConfig, TerrainLayers, analyze_granule

ROOT = Path(__file__).resolve().parents[1]
REAL_ZIP = ROOT / "NASADEM_HGT_001-20261114_161823" / "NASADEM_HGT_n51w113.zip"
STORED_SUMMARY = ROOT / "outputs" / "n51w113_drumheller_badlands" / "terrain_summary.json"
DRUMHELLER = BBox(-112.80, 51.40, -112.60, 51.52)
ARCSEC = 1.0 / 3600.0
LAT, LON = 51.4636, -112.7106  # Drumheller town; lat != lon in magnitude and sign


def numpy_weighted(values, weights, q=None):
    """Independent reference: numpy weighted mean or inverted-CDF percentile."""
    v = np.asarray(values, dtype=np.float64)
    w = np.asarray(weights, dtype=np.float64)
    if q is None:
        return float(np.average(v, weights=w))
    return float(np.percentile(v, q, weights=w, method="inverted_cdf"))


def point_in_ring(lon, lat, ring) -> bool:
    """Ray casting in longitude/latitude, independent of h3grid."""
    inside = False
    n = len(ring)
    for i in range(n):
        (x1, y1), (x2, y2) = ring[i], ring[(i + 1) % n]
        if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def distance_to_ring_m(lon, lat, ring) -> float:
    """Approximate ground distance (m) from a point to a ring's straight edges (local plane)."""
    kx = float(geodesy.metres_per_degree_lon(lat))
    ky = float(geodesy.metres_per_degree_lat(lat))
    best = math.inf
    for i in range(len(ring)):
        (x1, y1), (x2, y2) = ring[i], ring[(i + 1) % len(ring)]
        ax, ay = (x1 - lon) * kx, (y1 - lat) * ky
        bx, by = (x2 - lon) * kx, (y2 - lat) * ky
        dx, dy = bx - ax, by - ay
        t = min(1.0, max(0.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy)))
        best = min(best, math.hypot(ax + t * dx, ay + t * dy))
    return best


EDGE_BULGE_M = 1.0  # H3 edges are great-circle arcs: up to ~0.3 m off a straight lon/lat edge at res 6


def geo_ring(cell_int) -> list:
    """Cell boundary via h3.cells_to_geo (already GeoJSON longitude/latitude order)."""
    return [tuple(p) for p in h3.cells_to_geo([h3.int_to_str(int(cell_int))])["coordinates"][0][:-1]]


def small_grid(nrows=60, ncols=90, step_arcsec=3.0, north=51.48, west=-112.76) -> GeoGrid:
    step = step_arcsec * ARCSEC
    return GeoGrid(north=north, west=west, lat_step=step, lon_step=step, nrows=nrows, ncols=ncols)


def synthetic_layers(grid: GeoGrid, seed=7, water=None, voids=(), missing_derivatives=()) -> TerrainLayers:
    """Terrain-like layers with optional water block, void samples and undefined derivatives."""
    rng = np.random.default_rng(seed)
    shape = (grid.nrows, grid.ncols)
    z = np.round(700 + 40 * rng.random(shape)).astype(np.float32)
    slope = (30 * rng.random(shape)).astype(np.float32)
    tri = (20 * rng.random(shape)).astype(np.float32)
    rough = (2 * rng.random(shape)).astype(np.float32)
    w = np.zeros(shape, dtype=bool)
    if water is not None:
        w[water] = True
        z[water] = 5000.0  # sentinel: must never reach a statistic
        slope[water] = 89.0
    for r, c in voids:
        z[r, c] = np.nan
        for layer in (slope, tri, rough):  # a void invalidates every 3x3 window holding it
            layer[max(r - 1, 0) : r + 2, max(c - 1, 0) : c + 2] = np.nan
    for r, c in missing_derivatives:
        slope[r, c] = tri[r, c] = rough[r, c] = np.nan
    mask = np.isfinite(z) & ~w
    return TerrainLayers(grid=grid, elevation_m=z, slope_deg=slope, tri_m=tri, roughness_m=rough,
                         hillshade=np.zeros(shape, np.float32), water=w, analysis_mask=mask,
                         cell_area_m2=grid.cell_area_m2())


# ============================================================================ pixel-to-H3 assignment


def test_assign_grid_matches_pointwise_string_api():
    grid = small_grid()
    cells = h3grid.assign_grid(grid, 8)
    assert cells.shape == (grid.nrows, grid.ncols) and cells.dtype == np.uint64
    lats, lons = grid.lats(), grid.lons()
    assert lats[0] > lats[-1]  # row 0 is the northern row
    for r in range(0, grid.nrows, 7):
        for c in range(0, grid.ncols, 5):
            expected = h3.str_to_int(h3.latlng_to_cell(float(lats[r]), float(lons[c]), 8))
            assert int(cells[r, c]) == expected, (r, c)
    assert len(np.unique(cells)) > 5  # the grid really spans several cells


def test_pixel_centres_lie_inside_their_cell_polygon_and_no_other():
    grid = small_grid()
    cells = h3grid.assign_grid(grid, 8)
    rings = {int(c): geo_ring(c) for c in np.unique(cells)}
    lats, lons = grid.lats(), grid.lons()
    for r in range(grid.nrows):
        for c in range(grid.ncols):
            hits = [k for k, ring in rings.items() if point_in_ring(lons[c], lats[r], ring)]
            if hits != [int(cells[r, c])]:  # only allowed within the great-circle bulge of an edge
                assert distance_to_ring_m(lons[c], lats[r], rings[int(cells[r, c])]) < EDGE_BULGE_M, (r, c)


def test_coordinate_order_h3_latitude_first_geojson_longitude_first():
    cell = int(h3grid.assign_points([LAT], [LON], 8)[0])
    clat, clon = h3.cell_to_latlng(h3.int_to_str(cell))
    assert abs(clat - LAT) < 0.01 and abs(clon - LON) < 0.01
    # H3 does not reject swapped arguments: it returns a valid cell thousands of km away.
    swapped = h3.latlng_to_cell(LON, LAT, 8)
    assert h3.great_circle_distance(h3.cell_to_latlng(swapped), (LAT, LON), unit="km") > 1000

    ring = h3grid.cell_boundary_lonlat(cell)
    assert np.all((ring[:, 0] > -113) & (ring[:, 0] < -112))  # column 0 = longitude
    assert np.all((ring[:, 1] > 51) & (ring[:, 1] < 52))  # column 1 = latitude
    geo = np.array(geo_ring(cell))  # h3's own GeoJSON-ordered boundary: same vertices
    assert len(geo) == len(ring)
    assert all(np.min(np.abs(geo - v).max(axis=1)) < 1e-9 for v in ring)
    x, y = ring[:, 0], ring[:, 1]
    assert np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y) > 0  # counter-clockwise (RFC 7946)
    assert point_in_ring(LON, LAT, ring)


def test_assignment_rejects_bad_inputs():
    with pytest.raises(ValueError):
        h3grid.assign_points([95.0], [LON], 6)  # latitude out of range (e.g. lon passed as lat)
    with pytest.raises(ValueError):
        h3grid.assign_points([LAT, LAT], [LON], 6)
    for bad in (16, -1, 6.5, True):
        with pytest.raises(ValueError):
            h3grid.validate_resolution(bad)


def test_each_resolution_is_assigned_directly_not_via_parents():
    # H3 cells are not exactly nested: a res-8 cell's res-6 parent need not contain all its samples.
    grid = small_grid(nrows=150, ncols=200, step_arcsec=4.0)
    fine, coarse = h3grid.assign_grid(grid, 8), h3grid.assign_grid(grid, 6)
    parent = np.vectorize(lambda c: h3.str_to_int(h3.cell_to_parent(h3.int_to_str(int(c)), 6)), otypes=[np.uint64])(fine)
    assert (parent != coarse).any()  # so deriving res 6 from res 8 would misassign samples
    lats, lons = grid.lats(), grid.lons()
    rr, cc = np.nonzero(parent != coarse)
    for r, c in zip(rr[:20], cc[:20]):
        assert int(coarse[r, c]) == h3.str_to_int(h3.latlng_to_cell(float(lats[r]), float(lons[c]), 6))


# ============================================================================ aggregation statistics


def test_area_weighted_mean_min_max_and_counts_by_hand():
    ids = np.array([5, 5, 5, 2, 2, 5])
    area = np.array([1.0, 3.0, 2.0, 1.0, 1.0, 4.0])
    vals = np.array([10.0, 20.0, 40.0, 7.0, 9.0, np.nan])
    agg = aggregate_samples(ids, area, {"x": vals}, np.ones(6, bool), {"x": ("mean", "min", "max")})
    assert agg.cell_ids.tolist() == [2, 5]  # ascending key order
    x = agg.measurements["x"]
    assert x["mean"][0] == pytest.approx(8.0)
    assert x["mean"][1] == pytest.approx((1 * 10 + 3 * 20 + 2 * 40) / 6)  # NaN sample ignored
    assert (x["min"][1], x["max"][1]) == (10.0, 40.0)
    assert agg.n_samples.tolist() == [2, 4] and x["count_valid"].tolist() == [2, 3]
    assert x["valid_area_m2"].tolist() == [2.0, 6.0] and agg.sample_area_m2.tolist() == [2.0, 10.0]


def test_cell_percentiles_pool_samples_and_are_not_averages_of_parts():
    # One cell made of two sub-areas (e.g. two tiles): a flat one and a steep one, unequal areas.
    flat = np.array([1.0, 1.5, 2.0, 2.5])
    steep = np.array([20.0, 25.0, 30.0, 35.0, 40.0, 45.0])
    vals = np.concatenate([flat, steep])
    area = np.concatenate([np.full(4, 3.0), np.full(6, 1.0)])
    agg = aggregate_samples(np.zeros(10, np.int64), area, {"s": vals}, np.ones(10, bool),
                            {"s": ("mean", "p50", "p95")})
    s = agg.measurements["s"]
    # Total weight 18: the cumulative weight first reaches 9 at value 2.0 (3 + 3 + 3).
    assert s["p50"][0] == numpy_weighted(vals, area, 50) == 2.0
    assert s["p95"][0] == numpy_weighted(vals, area, 95) == 45.0
    assert s["mean"][0] == pytest.approx(numpy_weighted(vals, area))
    part_p50 = [numpy_weighted(flat, np.full(4, 3.0), 50), numpy_weighted(steep, np.ones(6), 50)]
    assert np.average(part_p50, weights=[12.0, 6.0]) != pytest.approx(s["p50"][0], abs=1.0)


def test_random_cells_match_numpy_reference_and_conserve_counts_and_area():
    rng = np.random.default_rng(2026)
    n = 5000
    ids = rng.integers(0, 9, n) * 1000 + 17
    area = rng.uniform(500, 700, n)
    vals = rng.gamma(2.0, 3.0, n).astype(np.float32)
    vals[rng.random(n) < 0.05] = np.nan
    include = rng.random(n) < 0.9
    agg = aggregate_samples(ids, area, {"v": vals}, include, {"v": ("mean", "min", "max", "p50", "p95")},
                            {"excluded": ~include})
    v = agg.measurements["v"]
    for j, key in enumerate(agg.cell_ids):
        sel = (ids == key) & include & np.isfinite(vals)
        vv, ww = vals[sel].astype(np.float64), area[sel]
        assert v["count_valid"][j] == sel.sum()
        assert v["mean"][j] == pytest.approx(numpy_weighted(vv, ww), rel=1e-12)
        assert (v["min"][j], v["max"][j]) == (vv.min(), vv.max())
        assert v["p50"][j] == numpy_weighted(vv, ww, 50)
        assert v["p95"][j] == numpy_weighted(vv, ww, 95)
        assert v["valid_area_m2"][j] == pytest.approx(ww.sum(), rel=1e-12)
    assert agg.n_samples.sum() == n
    assert agg.sample_area_m2.sum() == pytest.approx(area.sum(), rel=1e-12)
    assert agg.n_included.sum() + agg.counts["excluded"].sum() == n
    assert v["count_valid"].sum() == (include & np.isfinite(vals)).sum()
    assert np.array_equal(np.sort(agg.sample_order), np.arange(n))  # a partition: each sample once


def test_output_order_is_deterministic_and_independent_of_input_order():
    rng = np.random.default_rng(3)
    n = 3000
    ids = rng.choice(np.array([2**59 + 5, 17, 2**40, 999], dtype=np.uint64), n)
    area = rng.uniform(1, 2, n)
    vals = rng.normal(size=n)
    stats = {"v": ("mean", "p50", "p95")}
    a = aggregate_samples(ids, area, {"v": vals}, np.ones(n, bool), stats)
    perm = rng.permutation(n)
    b = aggregate_samples(ids[perm], area[perm], {"v": vals[perm]}, np.ones(n, bool), stats)
    assert a.cell_ids.tolist() == sorted(int(i) for i in set(ids.tolist())) == b.cell_ids.tolist()
    assert np.array_equal(a.n_samples, b.n_samples)
    np.testing.assert_allclose(a.measurements["v"]["mean"], b.measurements["v"]["mean"], rtol=1e-12)
    for p in ("p50", "p95"):  # continuous values: percentile picks the same sample either way
        assert np.array_equal(a.measurements["v"][p], b.measurements["v"][p])


def test_aggregation_rejects_bad_inputs():
    one = np.ones(3)
    with pytest.raises(ValueError, match="positive"):
        aggregate_samples([1, 1, 2], [1.0, 0.0, 1.0], {"v": one}, one > 0, {"v": ("mean",)})
    with pytest.raises(ValueError, match="samples"):
        aggregate_samples([1, 1, 2], one, {"v": np.ones(4)}, one > 0, {"v": ("mean",)})
    with pytest.raises(ValueError, match="unknown statistic"):
        aggregate_samples([1, 1, 2], one, {"v": one}, one > 0, {"v": ("median",)})
    with pytest.raises(TypeError):
        aggregate_samples(np.array(["a", "b", "c"]), one, {"v": one}, one > 0, {"v": ("mean",)})


# ============================================================================ terrain layers -> cells


def test_water_void_and_missing_derivatives_are_excluded_and_counted():
    grid = small_grid(nrows=80, ncols=120, step_arcsec=2.0)
    water = (slice(10, 30), slice(20, 60))
    voids = [(50, 70), (51, 100)]
    edge = [(r, 0) for r in range(80)]  # e.g. a granule-edge column without derivatives
    layers = synthetic_layers(grid, water=water, voids=voids, missing_derivatives=edge)
    res = aggregate_terrain(layers, 8, ["synthetic.zip"])
    assert res.all_checks_passed, [c for c in res.checks if not c["passed"]]
    recs = res.records
    assert sum(r["n_excluded_water"] for r in recs) == 20 * 40
    assert sum(r["n_excluded_void"] for r in recs) == 2
    valid_land = np.isfinite(layers.elevation_m) & ~layers.water
    expected_missing = int((valid_land & ~np.isfinite(layers.slope_deg)).sum())
    assert sum(r["n_derivative_missing"] for r in recs) == expected_missing > 80
    for r in recs:
        assert r["n_samples"] == r["n_analysis"] + r["n_excluded_water"] + r["n_excluded_void"]
        assert r["n_valid_slope"] == r["n_analysis"] - r["n_derivative_missing"]
        assert r["elevation_max_m"] is None or r["elevation_max_m"] < 5000  # water sentinel excluded
        assert r["slope_p95_deg"] is None or r["slope_p95_deg"] < 89
    flagged = {f for r in recs for f in r["quality_flags"].split(";") if f}
    assert {"water_excluded", "void_samples", "missing_derivatives"} <= flagged
    # Per-cell stats equal an independent numpy computation over that cell's land samples.
    cells = h3grid.assign_grid(grid, 8)
    area = np.broadcast_to(grid.cell_area_m2()[:, None], cells.shape)
    checked_empty = False
    for r in recs[:5]:
        key = h3.str_to_int(r["h3_cell"])
        sel = (cells == key) & valid_land & np.isfinite(layers.slope_deg)
        if not sel.any():  # e.g. a cell whose only samples sit in the no-derivative edge column
            assert r["slope_mean_deg"] is None and "no_valid_derivatives" in r["quality_flags"]
            checked_empty = True
            continue
        assert r["slope_mean_deg"] == pytest.approx(numpy_weighted(layers.slope_deg[sel], area[sel]), rel=1e-12)
        assert r["slope_p95_deg"] == numpy_weighted(layers.slope_deg[sel], area[sel], 95)
    assert checked_empty  # this layout has such a cell at the grid's west edge


def test_partial_and_complete_cells_and_exact_area_budget():
    # Footprint smaller than the cells around its edges: interior cells complete, edge cells partial.
    grid = small_grid(nrows=360, ncols=540, step_arcsec=1.0)
    res = aggregate_terrain(synthetic_layers(grid), 8, ["synthetic.zip"])
    assert res.all_checks_passed, [c for c in res.checks if not c["passed"]]
    by_status = {s: [r for r in res.records if r["coverage_status"] == s] for s in ("complete", "partial")}
    assert by_status["complete"] and by_status["partial"]
    for r in by_status["complete"]:
        assert r["coverage_fraction_exact_overlap"] == pytest.approx(1.0, abs=1e-9)
        assert abs(r["coverage_fraction_pixel_centre"] - 1.0) < 0.01  # boundary pixels assigned whole
        assert "partial_coverage" not in r["quality_flags"]
    for r in by_status["partial"]:
        assert 0 < r["coverage_fraction_exact_overlap"] < 1
        # sampled area is what was observed, not scaled up to the hexagon (the pixel-centre
        # excess can push a nearly complete cell slightly above 1)
        assert r["coverage_fraction_pixel_centre"] == pytest.approx(r["coverage_fraction_exact_overlap"], abs=0.01)
        # pixel-centre area differs from the exact overlap by at most about one pixel along the cut
        assert abs(r["sampled_area_km2"] - r["overlap_area_km2"]) < 0.01 * r["cell_area_km2"]
        assert "partial_coverage" in r["quality_flags"]
    footprint = grid.pixel_edge_bounds()
    total = sum(r["overlap_area_km2"] for r in res.records) + res.totals["sliver_overlap_area_km2"]
    assert total == pytest.approx(h3grid.bbox_area_m2(footprint) / 1e6, rel=1e-9)
    assert sum(r["sampled_area_km2"] for r in res.records) == pytest.approx(grid.cell_area_m2().sum() * grid.ncols / 1e6, rel=1e-12)


# ============================================================================ geometry


def test_rectangle_area_and_clipping_are_exact():
    grid = small_grid(nrows=120, ncols=200, step_arcsec=1.0)
    fp = grid.pixel_edge_bounds()
    pixel_sum = grid.cell_area_m2().sum() * grid.ncols
    assert h3grid.bbox_area_m2(fp) == pytest.approx(pixel_sum, rel=1e-10)
    rect = np.array([[fp.west, fp.south], [fp.east, fp.south], [fp.east, fp.north], [fp.west, fp.north]])
    assert h3grid.ring_area_m2(rect) == pytest.approx(h3grid.bbox_area_m2(fp), rel=1e-12)
    # Clip that rectangle by a box overlapping its north-east quarter: result is the intersection box.
    clip = BBox(0.5 * (fp.west + fp.east), 0.5 * (fp.south + fp.north), fp.east + 1, fp.north + 1)
    piece = h3grid.clip_ring_to_bbox(rect, clip)
    expected = h3grid.bbox_area_m2(BBox(clip.west, clip.south, fp.east, fp.north))
    assert h3grid.ring_area_m2(piece) == pytest.approx(expected, rel=1e-10)
    assert h3grid.clip_ring_to_bbox(rect, BBox(10.0, 10.0, 11.0, 11.0)).size == 0
    np.testing.assert_allclose(h3grid.clip_ring_to_bbox(rect, BBox(-180, -90, 180, 90)), rect, atol=1e-10)


@pytest.mark.parametrize("lat", [0.5, LAT, 70.0])
def test_cell_area_on_ellipsoid_vs_h3_sphere(lat):
    # H3 uses geodetic lat/lon as spherical coordinates on the authalic sphere, so the ratio of
    # ellipsoidal to spherical area is M*N / R^2 at the cell's latitude.
    cell = h3.latlng_to_cell(lat, LON, 7)
    geom = h3grid.cell_geometry(cell, BBox(-180, -90, 180, 90))
    r_auth = 6371007.180918475
    clat = geom.centre_lat
    expected = geodesy.meridional_radius_m(clat) * geodesy.prime_vertical_radius_m(clat) / r_auth**2
    assert geom.area_m2 / geom.h3_area_m2 == pytest.approx(expected, rel=1e-4)
    assert geom.is_complete and geom.overlap_fraction == 1.0


def test_straight_edge_model_matches_great_circle_edges():
    # Densify each H3 edge along its great-circle arc; the area changes by < 1e-7 at res 6.
    def unit(lon, lat):
        lo, la = math.radians(lon), math.radians(lat)
        return np.array([math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)])

    ring = h3grid.cell_boundary_lonlat(h3.latlng_to_cell(LAT, LON, 6))
    dense = []
    for i in range(len(ring)):
        p, q = unit(*ring[i]), unit(*ring[(i + 1) % len(ring)])
        om = math.acos(min(1.0, float(p @ q)))
        for t in np.linspace(0, 1, 100, endpoint=False):
            v = (math.sin((1 - t) * om) * p + math.sin(t * om) * q) / math.sin(om)
            dense.append([math.degrees(math.atan2(v[1], v[0])), math.degrees(math.asin(v[2]))])
    a, d = h3grid.ring_area_m2(ring), h3grid.ring_area_m2(np.array(dense))
    assert abs(d - a) / a < 1e-7


# ============================================================================ serialisation and CLI


def test_csv_and_geojson_records_order_and_coordinates(tmp_path):
    grid = small_grid()
    res = aggregate_terrain(synthetic_layers(grid), 8, ["synthetic.zip"])
    path = write_cells_csv(res.records, tmp_path / "cells.csv")
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    ids = [r["h3_cell"] for r in rows]
    assert ids == sorted(ids) == [r["h3_cell"] for r in res.records]
    assert [h3.str_to_int(i) for i in ids] == sorted(h3.str_to_int(i) for i in ids)  # hex order == int order
    assert int(rows[0]["n_samples"]) == res.records[0]["n_samples"]
    fc = json.loads(json.dumps(cells_feature_collection(res, {"note": "test"})))
    assert [f["id"] for f in fc["features"]] == ids
    for feat in fc["features"]:
        ring = feat["geometry"]["coordinates"][0]
        assert ring[0] == ring[-1] and len(ring) >= 6
        lon, lat = feat["properties"]["centre_lon_deg"], feat["properties"]["centre_lat_deg"]
        assert all(-113 < x < -112 and 51 < y < 52 for x, y in ring)  # [longitude, latitude]
        assert point_in_ring(lon, lat, ring[:-1])
    assert fc["metadata"]["coordinate_order"] == "[longitude, latitude]"
    # Writing the same result twice gives byte-identical CSV (deterministic output).
    again = write_cells_csv(res.records, tmp_path / "again.csv")
    assert again.read_bytes() == path.read_bytes()


N = 3601


@pytest.fixture(scope="module")
def synthetic_corner_zip(tmp_path_factory):
    """Synthetic n51w113 tile; the test AOI touches its south-west corner and holds voids and water."""
    path = tmp_path_factory.mktemp("nasadem_h3") / "NASADEM_HGT_n51w113.zip"
    rows = np.arange(N, dtype=np.float32)[:, None]  # broadcast: keeps memory to one 3601^2 float32 array
    cols = np.arange(N, dtype=np.float32)[None, :]
    hgt = np.round(700 + 0.3 * cols + 25 * np.sin(rows / 37.0) + 10 * np.cos(cols / 23.0)).astype(">i2")
    hgt[3550, 30] = hgt[3520, 70] = -32768
    swb = np.zeros((N, N), dtype="u1")
    swb[3560:3580, 40:90] = 255
    num = np.where(swb == 255, 0, 3).astype("u1")
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        zf.writestr("n51w113.hgt", hgt.tobytes())
        zf.writestr("n51w113.num", num.tobytes())
        zf.writestr("n51w113.swb", swb.tobytes())
    return path


def test_cli_end_to_end_reconciles_with_terrain_summary(synthetic_corner_zip, tmp_path):
    bbox = ["-113.0", "51.0", "-112.96", "51.03"]
    assert terrain_main([str(synthetic_corner_zip), "--bbox", *bbox, "--name", "corner", "--out-dir",
                         str(tmp_path), "--no-plot", "--rasterio-crosscheck", "no"]) == 0
    ref = tmp_path / "n51w113_corner" / "terrain_summary.json"
    assert h3_main([str(synthetic_corner_zip), "--bbox", *bbox, "--name", "corner", "--resolutions", "9", "7",
                    "--out-dir", str(tmp_path), "--reference-summary", str(ref)]) == 0
    out = tmp_path / "n51w113_corner_h3"
    stored = json.loads(ref.read_text(encoding="utf-8"))
    sc = stored["sample_counts"]
    assert sc["water_samples"] > 0 and sc["void_samples"] == 2 and sc["derivative_undefined_in_analysis"] > 0
    for res in (7, 9):
        run = json.loads((out / f"h3_res{res}_run_summary.json").read_text(encoding="utf-8"))
        assert run["all_checks_passed"] and run["h3"]["resolution"] == res
        assert [r["reference"] for r in run["reconciliation"]] == ["fresh_aoi_summary", "stored_aoi_summary"]
        t = run["results"]
        assert t["n_samples"] == sc["aoi_samples"] and t["n_excluded_water"] == sc["water_samples"]
        assert t["n_derivative_missing"] == sc["derivative_undefined_in_analysis"]
        with open(out / f"h3_res{res}_cells.csv", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == t["n_cells"] and all(r["h3_resolution"] == str(res) for r in rows)
        assert (out / f"h3_res{res}_mean_slope.png").stat().st_size > 10_000
        geo = json.loads((out / f"h3_res{res}_cells.geojson").read_text(encoding="utf-8"))
        assert len(geo["features"]) == len(rows)


# ============================================================================ real granule


@pytest.fixture(scope="module")
def drumheller():
    if not REAL_ZIP.exists():
        pytest.skip("real NASADEM granule n51w113 not present")
    cfg = AnalysisConfig(bbox=DRUMHELLER, name="drumheller_badlands", rasterio_crosscheck=False)
    summary, layers = analyze_granule(REAL_ZIP, cfg)
    return summary, layers, {res: aggregate_terrain(layers, res, [REAL_ZIP.name]) for res in (6, 8)}


@pytest.mark.parametrize("res, n_cells", [(6, 12), (8, 296)])
def test_real_drumheller_reconciles_with_original_summary(drumheller, res, n_cells):
    summary, layers, results = drumheller
    result = results[res]
    assert result.all_checks_passed, [c for c in result.checks if not c["passed"]]
    assert len(result.records) == n_cells
    fresh = reconcile(result, summary, "fresh")
    assert fresh["all_passed"], [c for c in fresh["checks"] if not c["passed"]]
    if STORED_SUMMARY.exists():
        stored = reconcile(result, json.loads(STORED_SUMMARY.read_text(encoding="utf-8")), "stored")
        assert stored["all_passed"], [c for c in stored["checks"] if not c["passed"]]
    # Means recompose exactly; averaged cell percentiles do not reproduce the AOI percentile.
    recs = result.records
    w = np.array([r["valid_derivative_area_km2"] for r in recs])
    mean = np.dot(w, [r[stat_column("slope", "mean")] for r in recs]) / w.sum()
    assert mean == pytest.approx(summary["measurements"]["slope"]["mean"], rel=1e-9)
    naive_p50 = np.dot(w, [r["slope_p50_deg"] for r in recs]) / w.sum()
    assert abs(naive_p50 - summary["measurements"]["slope"]["p50"]) > 0.1


def test_real_drumheller_assignment_spot_check(drumheller):
    _, layers, results = drumheller
    g = layers.grid
    rng = np.random.default_rng(20261114)
    idx = rng.choice(g.nrows * g.ncols, 400, replace=False)
    for res, result in results.items():
        cells = h3grid.assign_grid(g, res).reshape(-1)
        rings = {}
        for i in idx:
            lat, lon = float(g.lats()[i // g.ncols]), float(g.lons()[i % g.ncols])
            cell = int(cells[i])
            assert cell == h3.str_to_int(h3.latlng_to_cell(lat, lon, res))
            ring = rings.setdefault(cell, geo_ring(cell))
            assert point_in_ring(lon, lat, ring) or distance_to_ring_m(lon, lat, ring) < EDGE_BULGE_M
        assert {int(c) for c in np.unique(cells)} == {h3.str_to_int(r["h3_cell"]) for r in result.records}
