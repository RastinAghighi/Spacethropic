"""Reader, geometry and end-to-end tests on a synthetic NASADEM_HGT granule.

The synthetic tile n51w113 has the real 3601 x 3601 big-endian layout with
elevation = 500 + column index (1 m rise per arc-second eastward), two void
samples, and a 10 x 20 water block flagged in both SWB (255) and NUM (0).
"""

import json
import zipfile

import numpy as np
import pytest

from spacethropic import geodesy
from spacethropic.cli import main
from spacethropic.nasadem import BBox, NasademGranule, TileId, find_members, rasterio_crosscheck
from spacethropic.pipeline import AnalysisConfig, analyze_granule, derive_layers

N = 3601
STEP = 1.0 / 3600.0
VOIDS = [(2600, 1900), (2700, 2000)]
WATER = (slice(2800, 2810), slice(2100, 2120))
# Lon [-112.5, -112.4) -> cols 1800..2159; lat [51.2, 51.3) -> rows 2521..2880 (half-open in latitude).
AOI = BBox(-112.5, 51.2, -112.4, 51.3)


@pytest.fixture(scope="module")
def synthetic_zip(tmp_path_factory):
    path = tmp_path_factory.mktemp("nasadem") / "NASADEM_HGT_n51w113.zip"
    hgt = np.broadcast_to((500 + np.arange(N)).astype(">i2"), (N, N)).copy()
    for r, c in VOIDS:
        hgt[r, c] = -32768
    swb = np.zeros((N, N), dtype="u1")
    swb[WATER] = 255
    num = np.full((N, N), 3, dtype="u1")
    num[WATER] = 0
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        zf.writestr("n51w113.hgt", hgt.tobytes())
        zf.writestr("n51w113.num", num.tobytes())
        zf.writestr("n51w113.swb", swb.tobytes())
    return path


def run(zip_path, **kwargs):
    return analyze_granule(zip_path, AnalysisConfig(rasterio_crosscheck=False, **kwargs))


# ----------------------------------------------------------------------------- naming


@pytest.mark.parametrize(
    "text, south, west, name",
    [
        ("NASADEM_HGT_n51w113.zip", 51, -113, "n51w113"),
        ("dir/s01e000.hgt", -1, 0, "s01e000"),
        ("S56W070.HGT", -56, -70, "s56w070"),
    ],
)
def test_tile_id_is_south_west_corner(text, south, west, name):
    tile = TileId.from_name(text)
    assert (tile.south, tile.west, tile.name) == (south, west, name)


def test_tile_id_rejects_names_without_tile():
    with pytest.raises(ValueError):
        TileId.from_name("NASADEM_HGT.zip")


def test_find_members():
    m = find_members(["sub/", "sub/N51W113.HGT", "sub/n51w113.num", "n51w113.swb", "readme.txt"])
    assert (m.hgt, m.num, m.swb, m.other) == ("sub/N51W113.HGT", "sub/n51w113.num", "n51w113.swb", ("readme.txt",))
    with pytest.raises(ValueError):
        find_members(["n51w113.num"])
    with pytest.raises(ValueError):
        find_members(["a/n51w113.hgt", "b/n51w113.hgt"])


# ----------------------------------------------------------------------------- geometry and reading


def test_grid_geometry(synthetic_zip):
    with NasademGranule(synthetic_zip) as g:
        grid = g.grid
        assert (grid.nrows, grid.ncols) == (N, N)
        assert grid.lat_step == pytest.approx(STEP) and grid.lon_step == pytest.approx(STEP)
        c = grid.sample_centre_bounds()
        assert (c.west, c.south, c.east, c.north) == pytest.approx((-113.0, 51.0, -112.0, 52.0))
        e = grid.pixel_edge_bounds()
        h = STEP / 2
        assert (e.west, e.south, e.east, e.north) == pytest.approx((-113 - h, 51 - h, -112 + h, 52 + h))
        assert grid.geotransform() == pytest.approx((-113 - h, STEP, 0.0, 52 + h, 0.0, -STEP))


def test_tile_ownership_is_half_open(synthetic_zip):
    with NasademGranule(synthetic_zip) as g:
        rows, cols = g.grid.window(g.tile.owned_bbox())
    # Northern row (lat 52) and eastern column (lon -112) belong to the neighbouring tiles.
    assert (rows.start, rows.stop, cols.start, cols.stop) == (1, N, 0, N - 1)


def test_read_elevation_maps_voids_to_nan(synthetic_zip):
    with NasademGranule(synthetic_zip) as g:
        z = g.read_elevation(slice(2600, 2601), slice(1899, 1902))
    assert z[0, 0] == 500 + 1899
    assert np.isnan(z[0, 1])
    assert z[0, 2] == 500 + 1901


def test_inspect_reports_voids_masks_and_checks(synthetic_zip):
    with NasademGranule(synthetic_zip) as g:
        info = g.inspect()
    assert info["tile_id"] == "n51w113"
    assert info["elevation"]["void_count"] == 2
    assert (info["elevation"]["min_m"], info["elevation"]["max_m"]) == (500, 500 + N - 1)
    assert info["swb"]["water_count"] == 200
    assert info["num"]["category_counts"] == {"srtm": N * N - 200, "water": 200}
    passed = {c["check"]: c["passed"] for c in info["checks"]}
    assert passed.pop("no_void_samples") is False
    assert all(passed.values()), passed
    assert info["all_checks_passed"] is False


# ----------------------------------------------------------------------------- AOI statistics


def test_clean_aoi_has_exact_statistics(synthetic_zip):
    # lon [-112.45, -112.42) -> cols 1980..2087; lat [51.10, 51.15) -> rows 3061..3240: no voids or water.
    summary, layers = run(synthetic_zip, bbox=BBox(-112.45, 51.10, -112.42, 51.15))
    assert summary["aoi"]["col_range"] == [1980, 2088]
    assert summary["aoi"]["row_range"] == [3061, 3241]
    elev = summary["measurements"]["elevation"]
    assert (elev["min"], elev["max"]) == (2480.0, 2587.0)
    # Elevation depends only on column, so area weighting cancels: mean = mid-range.
    assert elev["mean"] == pytest.approx((2480 + 2587) / 2)
    assert elev["units"] == "m"
    # Slope of a 1 m per arc-second eastward ramp is atan(1 / dx(lat)).
    lats = 52.0 - np.arange(3061, 3241) * STEP
    expected = np.degrees(np.arctan(1.0 / (geodesy.metres_per_degree_lon(lats) * STEP)))
    slope = summary["measurements"]["slope"]  # layers are stored as float32 (~1e-7 relative)
    assert slope["min"] == pytest.approx(expected.min(), abs=1e-5)
    assert slope["max"] == pytest.approx(expected.max(), abs=1e-5)
    assert slope["max"] - slope["min"] == pytest.approx(expected.max() - expected.min(), abs=2e-5)
    assert slope["units"] == "degrees"
    assert summary["measurements"]["roughness_tri"]["max"] == pytest.approx(np.sqrt(6.0))
    assert summary["measurements"]["roughness_detrended"]["max"] == pytest.approx(0.0, abs=1e-9)
    assert summary["sample_counts"]["derivative_undefined_in_analysis"] == 0


def test_voids_and_water_are_excluded(synthetic_zip):
    summary, layers = run(synthetic_zip, bbox=AOI)
    counts = summary["sample_counts"]
    assert summary["aoi"]["shape"] == [360, 360]
    assert (counts["void_samples"], counts["water_samples"]) == (2, 200)
    assert counts["analysis_samples"] == 360 * 360 - 2 - 200
    # Each void blanks its own 3x3 window: 8 neighbours per void are valid land but have no slope.
    assert counts["derivative_undefined_in_analysis"] == 16

    # Independent brute-force area-weighted mean over the same samples.
    rows, cols = np.arange(2521, 2881), np.arange(1800, 2160)
    w = np.broadcast_to(geodesy.cell_area_m2(52.0 - rows * STEP, STEP, STEP)[:, None], (360, 360))
    z = np.broadcast_to((500.0 + cols)[None, :], (360, 360))
    keep = np.ones((360, 360), dtype=bool)
    for r, c in VOIDS:
        keep[r - 2521, c - 1800] = False
    keep[2800 - 2521 : 2810 - 2521, 2100 - 1800 : 2120 - 1800] = False
    expected = np.average(z[keep], weights=w[keep])
    assert summary["measurements"]["elevation"]["mean"] == pytest.approx(expected, rel=1e-12)
    assert summary["measurements"]["elevation"]["count_valid"] == keep.sum()


def test_include_water(synthetic_zip):
    summary, _ = run(synthetic_zip, bbox=AOI, exclude_water=False)
    assert summary["sample_counts"]["analysis_samples"] == 360 * 360 - 2


def test_aoi_touching_tile_edge_has_undefined_edge_derivatives(synthetic_zip):
    summary, layers = run(synthetic_zip, bbox=BBox(-113.0, 51.0, -112.99, 51.01))
    assert summary["aoi"]["shape"] == [36, 36]
    # South row (lat 51.0) and west column (lon -113.0) are the granule's own edge.
    assert summary["sample_counts"]["derivative_undefined_in_analysis"] == 36 + 36 - 1
    assert np.isnan(layers.slope_deg[-1, :]).all() and np.isnan(layers.slope_deg[:, 0]).all()


def test_strip_processing_matches_single_pass_and_handles_missing_masks(tmp_path):
    n = 1201  # small 3-arc-second-sized grid keeps this test fast
    rng = np.random.default_rng(0)
    hgt = (1000 + np.cumsum(rng.normal(0, 3, (n, n)), axis=0)).astype(">i2")  # rough random surface
    hgt[600, 600] = -32768
    path = tmp_path / "NASADEM_HGT_n10e020.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("n10e020.hgt", hgt.tobytes())  # no .num / .swb members
    with NasademGranule(path) as g:
        for box in (BBox(20.1, 10.2, 20.9, 10.8), g.tile.owned_bbox()):
            rows, cols = g.grid.window(box)
            z1, d1 = derive_layers(g, rows, cols, 1.0, strip_rows=37)
            z2, d2 = derive_layers(g, rows, cols, 1.0, strip_rows=10_000)
            np.testing.assert_array_equal(z1, z2)
            for key in d1:
                np.testing.assert_array_equal(d1[key], d2[key])
    summary, _ = run(path)
    assert summary["parameters"]["water_mask_source"].startswith("none available")
    passed = {c["check"]: c["passed"] for c in summary["granule"]["checks"]}
    assert passed["hgt_is_3601x3601_1arcsec"] is False and passed["num_present_and_matches_grid"] is False


def test_invalid_aois_raise(synthetic_zip):
    with pytest.raises(ValueError, match="beyond granule"):
        run(synthetic_zip, bbox=BBox(-113.5, 51.2, -112.4, 51.3))
    with pytest.raises(ValueError, match="no sample centres"):
        run(synthetic_zip, bbox=BBox(-112.5 + 0.1 * STEP, 51.2, -112.5 + 0.9 * STEP, 51.3))


def test_cli_writes_json_csv_and_png(synthetic_zip, tmp_path):
    code = main([str(synthetic_zip), "--bbox", "-112.5", "51.2", "-112.4", "51.3", "--name", "test_aoi",
                 "--out-dir", str(tmp_path), "--rasterio-crosscheck", "no"])
    assert code == 0
    out = tmp_path / "n51w113_test_aoi"
    summary = json.loads((out / "terrain_summary.json").read_text(encoding="utf-8"))
    assert summary["source_file"] == "NASADEM_HGT_n51w113.zip"
    assert summary["measurements"]["slope"]["units"] == "degrees"
    csv_text = (out / "terrain_summary.csv").read_text(encoding="utf-8")
    assert "elevation,mean," in csv_text and ",m\n" in csv_text.replace("\r\n", "\n")
    assert (out / "terrain_overview.png").stat().st_size > 10_000


def test_rasterio_crosscheck_matches_native_reader(synthetic_zip):
    pytest.importorskip("rasterio")
    with NasademGranule(synthetic_zip) as g:
        result = rasterio_crosscheck(g)
    assert result["status"] == "ok", result
    assert result["pixel_values_identical"] and result["geotransform_matches_native"]
