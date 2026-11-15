import math

import numpy as np
import pytest

from spacethropic import geodesy

def _reference_degree_lengths_m(lat_deg):
    """Published WGS 84 series for the length of one degree (independent of the closed form).

    lat: 111132.954 - 559.822 cos(2 phi) + 1.175 cos(4 phi)
    lon: 111412.84 cos(phi) - 93.5 cos(3 phi) + 0.118 cos(5 phi)
    Truncation and coefficient rounding keep these within ~0.1 m.
    """
    p = math.radians(lat_deg)
    m_lat = 111_132.954 - 559.822 * math.cos(2 * p) + 1.175 * math.cos(4 * p)
    m_lon = 111_412.84 * math.cos(p) - 93.5 * math.cos(3 * p) + 0.118 * math.cos(5 * p)
    return m_lat, m_lon


@pytest.mark.parametrize("lat", [0, 15, 30, 45, 51.5, 60, 75, 89])
def test_degree_lengths_match_wgs84_series(lat):
    m_lat, m_lon = _reference_degree_lengths_m(lat)
    assert geodesy.metres_per_degree_lat(lat) == pytest.approx(m_lat, abs=0.1)
    assert geodesy.metres_per_degree_lon(lat) == pytest.approx(m_lon, abs=0.1)


def test_degree_lengths_at_equator():
    # Equator: one degree of longitude is a * pi / 180; of latitude a * (1 - e^2) * pi / 180.
    assert geodesy.metres_per_degree_lon(0.0) == pytest.approx(geodesy.WGS84_A * math.pi / 180, rel=1e-15)
    assert geodesy.metres_per_degree_lat(0.0) == pytest.approx(110_574.27, abs=0.01)


def test_longitude_degree_vanishes_at_pole():
    assert geodesy.metres_per_degree_lon(90.0) == pytest.approx(0.0, abs=1e-6)


def _exact_quadrangle_area_m2(lat1, lat2, dlon_deg):
    """Closed-form area of an ellipsoidal quadrangle (authalic-latitude formula)."""
    e2 = geodesy.WGS84_E2
    e = math.sqrt(e2)
    b2 = geodesy.WGS84_A**2 * (1.0 - e2)

    def q(lat):
        s = math.sin(math.radians(lat))
        return s / (1.0 - e2 * s * s) + math.log((1.0 + e * s) / (1.0 - e * s)) / (2.0 * e)

    return 0.5 * b2 * math.radians(dlon_deg) * (q(lat2) - q(lat1))


def test_arcsecond_cell_areas_sum_to_exact_tile_area():
    step = 1.0 / 3600.0
    centres = 51.0 + (np.arange(3600) + 0.5) * step  # 1" rows spanning 51..52 N
    total = geodesy.cell_area_m2(centres, step, 1.0).sum()
    exact = _exact_quadrangle_area_m2(51.0, 52.0, 1.0)
    assert total == pytest.approx(exact, rel=1e-9)
    # Sanity: ~111.25 km (N-S) x ~69.4 km (E-W) at 51.5 N.
    assert 7_600 < exact / 1e6 < 7_850
