import numpy as np
import pytest

from spacethropic import geodesy, terrain

ALL_METRICS = (
    lambda z: terrain.slope_degrees(z, 30.0, 30.0),
    terrain.terrain_ruggedness_index,
    terrain.detrended_roughness,
)


def interior(a):
    return a[1:-1, 1:-1]


def edge_mask(shape):
    m = np.zeros(shape, dtype=bool)
    m[0, :] = m[-1, :] = m[:, 0] = m[:, -1] = True
    return m


@pytest.mark.parametrize("metric", ALL_METRICS)
def test_flat_surface_is_zero_inside_and_nan_on_edges(metric):
    z = np.full((6, 7), 812.0)
    out = metric(z)
    assert np.array_equal(np.isnan(out), edge_mask(z.shape))
    np.testing.assert_allclose(interior(out), 0.0, atol=1e-12)


def test_plane_on_projected_grid_gives_exact_gradient_and_slope():
    dx, dy = 30.0, 20.0
    nr, nc = 9, 11
    east = np.arange(nc) * dx
    north = (nr - 1 - np.arange(nr)) * dy  # row 0 is the northern edge
    a, b = 0.10, -0.05
    z = 100.0 + a * east[None, :] + b * north[:, None]
    dzdx, dzdy = terrain.horn_gradient(z, dx, dy)
    np.testing.assert_allclose(interior(dzdx), a)
    np.testing.assert_allclose(interior(dzdy), b)
    expected = np.degrees(np.arctan(np.hypot(a, b)))
    np.testing.assert_allclose(interior(terrain.slope_degrees(z, dx, dy)), expected)


def test_unit_rise_over_unit_run_is_45_degrees():
    z = np.tile(np.arange(5) * 25.0, (5, 1))
    np.testing.assert_allclose(interior(terrain.slope_degrees(z, 25.0, 25.0)), 45.0)


def test_geographic_grid_slope_uses_ground_metres():
    """1 m rise per arc-second at 45 N; expected spacings from the WGS 84 degree-length series.

    At 45 N one degree is 78 846.80 m of longitude and 111 131.78 m of latitude.
    """
    step = 1.0 / 3600.0
    lats = 45.0 + (2 - np.arange(5)) * step  # 5 rows centred on 45 N
    dx = geodesy.metres_per_degree_lon(lats) * step
    dy = geodesy.metres_per_degree_lat(lats) * step

    east_ramp = np.tile(np.arange(7, dtype=float), (5, 1))  # +1 m per arc-second of longitude
    slope_e = terrain.slope_degrees(east_ramp, dx, dy)
    assert slope_e[2, 3] == pytest.approx(np.degrees(np.arctan(3600 / 78_846.80)), abs=1e-5)

    north_ramp = np.tile((4.0 - np.arange(5))[:, None], (1, 7))  # +1 m per arc-second northward
    slope_n = terrain.slope_degrees(north_ramp, dx, dy)
    assert slope_n[2, 3] == pytest.approx(np.degrees(np.arctan(3600 / 111_131.78)), abs=1e-5)

    # Pixels are not square: the same 1 m step is steeper east-west (21.9 m) than north-south (30.9 m).
    assert slope_e[2, 3] > slope_n[2, 3]
    # Treating degrees as metres would give an absurd ~90 degree slope.
    assert slope_e[2, 3] < 3.0


def test_tri_of_uniform_ramp():
    z = np.tile(np.arange(6, dtype=float) * 2.0, (5, 1))  # 2 m per column
    # neighbours differ by +-2 m in 6 of 8 positions: sqrt(6 * 2^2)
    np.testing.assert_allclose(interior(terrain.terrain_ruggedness_index(z)), 2.0 * np.sqrt(6.0))


def test_detrended_roughness_ignores_planes_and_detects_spikes():
    i, j = np.mgrid[0:7, 0:8].astype(float)
    plane = 500.0 + 3.0 * i - 7.0 * j
    np.testing.assert_allclose(interior(terrain.detrended_roughness(plane)), 0.0, atol=1e-9)

    h = 9.0
    spiked = plane.copy()
    spiked[3, 4] += h
    # Residual RMS about the best plane of a centred spike: h * sqrt(8/81).
    assert terrain.detrended_roughness(spiked)[3, 4] == pytest.approx(h * np.sqrt(8.0 / 81.0))
    spike_only = np.zeros((3, 3))
    spike_only[1, 1] = h
    assert terrain.terrain_ruggedness_index(spike_only)[1, 1] == pytest.approx(np.sqrt(8 * h * h))


@pytest.mark.parametrize("metric", ALL_METRICS)
def test_missing_value_only_affects_its_3x3_neighbourhood(metric):
    i, j = np.mgrid[0:9, 0:9].astype(float)
    z = 700.0 + 2.0 * i + 1.0 * j
    z[4, 4] = np.nan
    expected_nan = edge_mask(z.shape)
    expected_nan[3:6, 3:6] = True
    out = metric(z)
    assert np.array_equal(np.isnan(out), expected_nan)


def test_hillshade_flat_and_orientation():
    flat = terrain.hillshade(np.zeros((1, 1)), np.zeros((1, 1)), azimuth_deg=315, altitude_deg=45)
    assert flat[0, 0] == pytest.approx(np.sin(np.radians(45)))
    # Rising to the south-east = facing the north-west sun: brighter than the opposite slope.
    facing_sun = terrain.hillshade(np.array([[0.5]]), np.array([[-0.5]]))
    facing_away = terrain.hillshade(np.array([[-0.5]]), np.array([[0.5]]))
    assert facing_sun[0, 0] > flat[0, 0] > facing_away[0, 0]


def test_invalid_inputs_rejected():
    with pytest.raises(ValueError):
        terrain.horn_gradient(np.zeros((4, 4)), np.ones(3), 1.0)  # wrong dx length
    with pytest.raises(ValueError):
        terrain.horn_gradient(np.zeros((4, 4)), 0.0, 1.0)  # non-positive spacing
    with pytest.raises(ValueError):
        terrain.slope_degrees(np.zeros((2, 5)), 1.0, 1.0)  # smaller than 3 x 3
