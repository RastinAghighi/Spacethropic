"""Targeted analytic checks added in DRUMHELLER-PILOT-02 (scientific validation).

``test_terrain.py`` covers planes, ramps, spikes and missing data. These tests add:

* non-planar surfaces with closed-form answers (quadratic and cubic surfaces, curvature);
* the dependence of TRI and detrended roughness on the non-square 1" pixels;
* the statistical noise floor that 1 m height rounding puts on slope and roughness;
* the AOI/halo property that geographic aggregation relies on (an AOI's layers equal the
  same pixels of whole-granule layers).

The expected values here are derived by hand, not computed with the pipeline's own
helpers. The last test runs only when the real NASADEM granule is present. It compares
the pipeline with the independent standard-library reader and reference implementation
in ``validation/independent_check.py``.
"""

import importlib.util
import math
import zipfile
from pathlib import Path

import numpy as np
import pytest

from spacethropic import terrain
from spacethropic.nasadem import BBox, NasademGranule
from spacethropic.pipeline import derive_layers
from spacethropic.stats import summarize

ROOT = Path(__file__).resolve().parents[1]
REAL_ZIP = ROOT / "NASADEM_HGT_001-20261114_161823" / "NASADEM_HGT_n51w113.zip"
DX, DY = 19.3, 30.9  # ~1" ground spacing at 51.5 N (m); deliberately non-square


def interior(a):
    return a[1:-1, 1:-1]


def metric_grid(nr, nc, dx=DX, dy=DY):
    """East and north coordinates (m) of a north-up grid; row 0 is the northern edge."""
    east = np.arange(nc) * dx
    north = (nr - 1 - np.arange(nr)) * dy
    return np.meshgrid(east, north)


# ----------------------------------------------------------------------------- slope on curved surfaces


def test_horn_gradient_is_exact_for_quadratic_surfaces():
    # Central differences are exact for quadratics; the 1-2-1 cross weights then average a
    # gradient that is linear across the window, so Horn's operator is exact at every node.
    x, y = metric_grid(9, 11)
    a, b, c, d, e = 0.03, -0.02, 4e-4, -3e-4, 2.5e-4
    z = 500 + a * x + b * y + c * x**2 + d * x * y + e * y**2
    dzdx, dzdy = terrain.horn_gradient(z, DX, DY)
    np.testing.assert_allclose(interior(dzdx), interior(a + 2 * c * x + d * y), rtol=0, atol=1e-11)
    np.testing.assert_allclose(interior(dzdy), interior(b + d * x + 2 * e * y), rtol=0, atol=1e-11)


def test_horn_truncation_error_on_a_cubic_is_k_dx_squared():
    # ((x+h)^3 - (x-h)^3) / 2h = 3x^2 + h^2: Horn's slope error grows with the square of the spacing.
    x, _ = metric_grid(5, 9)
    k = 1e-5
    dzdx, _ = terrain.horn_gradient(k * x**3, DX, DY)
    np.testing.assert_allclose(interior(dzdx) - interior(3 * k * x**2), k * DX**2, rtol=1e-9)


# ----------------------------------------------------------------------------- roughness and pixel shape


def test_detrended_roughness_of_quadratic_surface():
    # z = A u^2 + B u v + C v^2 in window offsets (u east, v north). After removing the best
    # plane, the residuals are A(u^2 - 2/3), B u v and C(v^2 - 2/3). These are mutually
    # orthogonal with sums of squares 2, 4 and 2, so RMS = sqrt((2A^2 + 4B^2 + 2C^2) / 9).
    x, y = metric_grid(7, 8)
    kxx, kxy, kyy = 2e-3, -1.5e-3, 1e-3  # second derivatives (1/m)
    z = 900 + 0.05 * x - 0.02 * y + 0.5 * kxx * x**2 + kxy * x * y + 0.5 * kyy * y**2
    A, B, C = 0.5 * kxx * DX**2, kxy * DX * DY, 0.5 * kyy * DY**2
    expected = math.sqrt((2 * A**2 + 4 * B**2 + 2 * C**2) / 9)
    np.testing.assert_allclose(interior(terrain.detrended_roughness(z)), expected, rtol=1e-9)


def test_same_curvature_reads_rougher_north_south_on_non_square_pixels():
    # Roughness from curvature k across the window scales with spacing^2 in that direction,
    # so an east-west trough and a north-south trough of equal curvature differ by (dy/dx)^2.
    x, y = metric_grid(5, 5)
    k = 1e-3
    ew = terrain.detrended_roughness(0.5 * k * x**2)[2, 2]  # curved along x
    ns = terrain.detrended_roughness(0.5 * k * y**2)[2, 2]  # curved along y
    assert ew == pytest.approx(k * DX**2 * math.sqrt(2) / 6, rel=1e-9)
    assert ns / ew == pytest.approx((DY / DX) ** 2, rel=1e-9)  # ~2.56 at 51.5 N


@pytest.mark.parametrize("aspect_deg", [0.0, 37.0, 90.0])
def test_tri_of_plane_depends_on_aspect_on_non_square_pixels(aspect_deg):
    # Neighbour differences of a plane are gx*u*dx + gy*v*dy, so with sum(u^2) = sum(v^2) = 6
    # and sum(u v) = 0: TRI = sqrt(6) * sqrt((gx dx)^2 + (gy dy)^2).
    g = math.tan(math.radians(10.0))
    gx, gy = g * math.cos(math.radians(aspect_deg)), g * math.sin(math.radians(aspect_deg))
    x, y = metric_grid(5, 6)
    tri = terrain.terrain_ruggedness_index(100 + gx * x + gy * y)
    expected = math.sqrt(6.0) * math.hypot(gx * DX, gy * DY)
    np.testing.assert_allclose(interior(tri), expected, rtol=1e-12)


# ----------------------------------------------------------------------------- 1 m rounding floor


def _independent_rounded_planes(n, rng):
    """n independent 3x3 planes side by side (one per 3 columns), rounded to whole metres."""
    gx = rng.uniform(-1.5, 1.5, n)  # m/m: tens of metres per pixel, so rounding errors are ~iid
    gy = rng.uniform(-1.5, 1.5, n)
    off = rng.uniform(0.0, 1.0, n)
    u = np.tile(np.arange(3) - 1.0, n)  # column offset within each block
    blk = np.repeat(np.arange(n), 3)
    v = np.array([1.0, 0.0, -1.0])[:, None]  # row offsets (north positive)
    z = off[blk] + gx[blk] * u * DX + gy[blk] * v * DY
    return np.round(z), gx, gy


def test_rounding_to_whole_metres_sets_roughness_and_slope_noise_floor():
    # Rounding errors e ~ U(-1/2, 1/2) have variance 1/12. The plane fit removes 3 of 9 degrees
    # of freedom, so E[roughness^2] = (6/9) / 12 = 1/18 (RMS 0.236 m). Horn's x-gradient sums
    # 6 errors with weights +-1, +-2, +-1 over 8 dx, so sd = sqrt(12/12) / (8 dx) = 1 / (8 dx).
    rng = np.random.default_rng(2026)
    n = 100_000
    z, gx, gy = _independent_rounded_planes(n, rng)
    centres = np.arange(n) * 3 + 1
    rough = terrain.detrended_roughness(z)[1, centres]
    assert np.mean(rough**2) == pytest.approx(1 / 18, rel=0.02)
    dzdx, dzdy = terrain.horn_gradient(z, DX, DY)
    assert np.std(dzdx[1, centres] - gx) == pytest.approx(1 / (8 * DX), rel=0.02)
    assert np.std(dzdy[1, centres] - gy) == pytest.approx(1 / (8 * DY), rel=0.02)


# ----------------------------------------------------------------------------- AOI / halo consistency


@pytest.fixture(scope="module")
def rough_granule(tmp_path_factory):
    n = 1201  # small grid keeps the test fast; the reader infers the size from the member
    rng = np.random.default_rng(7)
    hgt = 1000 + np.cumsum(rng.normal(0, 2, (n, n)), axis=1) + np.cumsum(rng.normal(0, 2, (n, n)), axis=0)
    path = tmp_path_factory.mktemp("halo") / "NASADEM_HGT_n51w113.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        zf.writestr("n51w113.hgt", np.round(hgt).astype(">i2").tobytes())
    return path


@pytest.mark.parametrize(
    "bbox",
    [
        BBox(-112.7, 51.3, -112.4, 51.65),  # interior, spans several strips
        BBox(-113.0, 51.9, -112.9, 52.0),  # north-west corner: north row uses the shared row 0 as halo
        None,  # the tile's own half-open extent
    ],
)
def test_aoi_layers_equal_whole_granule_layers(rough_granule, bbox):
    with NasademGranule(rough_granule) as g:
        z_all = g.read_elevation()
        dx, dy = g.grid.dx_m(), g.grid.dy_m()
        whole = {
            "slope": terrain.slope_degrees(z_all, dx, dy),
            "tri": terrain.terrain_ruggedness_index(z_all),
            "rough": terrain.detrended_roughness(z_all),
        }
        rows, cols = g.grid.window(bbox or g.tile.owned_bbox())
        z, layers = derive_layers(g, rows, cols, 1.0, strip_rows=50)
    np.testing.assert_array_equal(z, z_all[rows, cols])
    for key, full in whole.items():
        # float32 storage; NaN positions must coincide (granule edge only).
        np.testing.assert_allclose(layers[key], full[rows, cols], rtol=1e-6, atol=1e-6, err_msg=key)


# ----------------------------------------------------------------------------- real granule (optional)


@pytest.fixture(scope="module")
def reference_module():
    spec = importlib.util.spec_from_file_location("independent_check", ROOT / "validation" / "independent_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(not REAL_ZIP.exists(), reason="real NASADEM granule n51w113 not present")
def test_real_drumheller_window_matches_independent_reference(reference_module):
    ic = reference_module
    members = ic.read_zip_members(REAL_ZIP)  # struct + zlib reader, CRC-checked
    hgt = members["n51w113.hgt"]
    z16 = np.frombuffer(ic.decode_hgt(hgt), dtype=np.int16).reshape(ic.N, ic.N)
    rows, cols = ic.aoi_window(ic.DRUMHELLER_BBOX, 51, -113)
    with NasademGranule(REAL_ZIP) as g:
        assert g.grid.window(BBox(*ic.DRUMHELLER_BBOX)) == (rows, cols)
        np.testing.assert_array_equal(g._read_rows(g.members.hgt, np.dtype(">i2"), slice(None)), z16)
        z, layers = derive_layers(g, rows, cols, 1.0)
        area = g.grid.subgrid(rows, cols).cell_area_m2()
    np.testing.assert_array_equal(z, z16[rows, cols])
    assert z[0, 0] == ic.hgt_value(hgt, rows.start, cols.start)

    halo = z16[rows.start - 1 : rows.stop + 1, cols.start - 1 : cols.stop + 1]
    lats = 52.0 - np.arange(rows.start - 1, rows.stop + 1) / 3600.0
    ref, _ = ic.reference_terrain(halo, lats, metric_roughness=False)
    inner = (slice(1, -1), slice(1, -1))
    for key, ref_key in (("slope", "slope"), ("tri", "tri"), ("rough", "rough_index")):
        np.testing.assert_allclose(layers[key], ref[ref_key][inner], rtol=0, atol=1e-5, err_msg=key)

    exact_area = ic.row_cell_area_m2(lats[1:-1])
    np.testing.assert_allclose(area, exact_area, rtol=1e-9)
    mask = np.ones(z.shape, dtype=bool)  # no water or voids in this AOI
    pipe = summarize(layers["slope"], row_weights=area, mask=mask)
    refs = ic.reference_stats(ref["slope"][inner], exact_area, mask)
    for k in ("mean", "std"):
        assert pipe[k] == pytest.approx(refs[k], rel=1e-6)
    for k in ("min", "max", "p5", "p25", "p50", "p75", "p95"):
        assert pipe[k] == pytest.approx(refs[k], abs=1e-5)
