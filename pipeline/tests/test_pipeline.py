import math

import h3
import numpy as np
import pandas as pd
import pytest
import rasterio
from pyproj import Transformer
from rasterio.features import geometry_mask
from rasterio.transform import from_origin

import grid
from aggregate import aggregate
from config import INTERIM, RAW, geographic_crs, local_crs, raster_half_extent_m, settings, sites
from features import terrain
from merge import _interpolate
from sources import sources_for

SITES = list(sites().values())


@pytest.mark.parametrize("site", SITES, ids=lambda s: s.id)
def test_cell_areas_cover_the_site_disk(site):
    cells = grid.site_cells(site)
    disk = math.pi * site.radius_km**2
    assert abs(cells["area_km2"].sum() - disk) / disk < 0.03
    assert cells["dist_km"].max() <= site.radius_km


def test_each_body_resolution_is_nearest_to_6_km2():
    for site in (sites()["sudbury"], sites()["apollo16"], sites()["viking1"]):
        R = site.body.radius_m
        area = lambda res: h3.average_hexagon_area(res, unit="km^2") * (R / 6371007.180918475) ** 2
        chosen = abs(math.log(area(site.body.h3_res) / 6))
        assert all(chosen <= abs(math.log(area(r) / 6)) for r in range(4, 10))


def test_slope_of_a_tilted_plane():
    px, angle = 200.0, 10.0
    y = np.arange(100)[:, None] * px
    dem = np.repeat(y * math.tan(math.radians(angle)), 100, axis=1).astype(np.float32)
    f = terrain(dem, px)
    assert np.nanmean(f["slope_deg"]) == pytest.approx(angle, abs=1e-3)


def _synthetic_plane(site, angle):
    half, px = raster_half_extent_m(site), settings()["terrain_baseline_m"]
    n = math.ceil(2 * half / px)
    y = (np.arange(n)[:, None] * px).repeat(n, axis=1)
    return terrain((y * math.tan(math.radians(angle))).astype(np.float32), px), from_origin(-half, half, px, px)


def test_fixed_window_slope_is_identical_on_every_body():
    """Scale normalisation: same terrain, same features, whatever the body's cell size."""
    means = {}
    for sid in ("sudbury", "apollo16", "viking1"):
        site = sites()[sid]
        feats, transform = _synthetic_plane(site, 5.0)
        table = aggregate(site, grid.site_cells(site), feats, transform)
        means[sid] = table["slope_deg__mean"].mean()
        assert table["slope_deg__std"].max() < 1e-3
    assert max(means.values()) - min(means.values()) < 1e-3


def test_interpolation_fills_from_neighbours():
    site = sites()["sudbury"]
    cells = grid.site_cells(site).set_index("cell")
    cols = ["x__mean"]
    table = pd.DataFrame({"x__mean": 1.0}, index=cells.index)
    hole = cells.index[0]
    table.loc[hole, "x__mean"] = np.nan
    source = pd.Series("measured:test", index=cells.index, dtype="string")
    _interpolate(table, cols, source)
    assert table.loc[hole, "x__mean"] == 1.0 and source[hole] == "interpolated"


@pytest.mark.parametrize("site", SITES, ids=lambda s: s.id)
def test_cell_means_match_independent_polygon_zonal_stats(site):
    """Spot-check: recompute a few cells' elevation spread by rasterising the H3 polygon."""
    src_id = sources_for(site, "terrain")[0].id
    parquet = INTERIM / site.id / f"{src_id}.parquet"
    if not parquet.exists():
        pytest.skip("run the pipeline first")
    table = pd.read_parquet(parquet).set_index("cell")
    to_xy = Transformer.from_crs(geographic_crs(site.body), local_crs(site), always_xy=True)
    with rasterio.open(RAW / site.id / f"{src_id}.tif") as r:
        dem = r.read(1)
        for cell in table.index[:: max(len(table) // 5, 1)]:
            ring = [to_xy.transform(lon, lat) for lat, lon in h3.cell_to_boundary(cell)]
            inside = ~geometry_mask([{"type": "Polygon", "coordinates": [ring + ring[:1]]}], dem.shape, r.transform)
            expected = np.nanstd(dem[inside])
            assert table.loc[cell, "elevation_m__std"] == pytest.approx(expected, rel=0.1, abs=1.0)
