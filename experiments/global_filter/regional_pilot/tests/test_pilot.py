import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pytest
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from shapely.geometry import box
from pilot import aggregate_polygon, decision, CLASS_MAPS


def make_raster(array):
    mem = MemoryFile()
    ds = mem.open(driver="GTiff", width=array.shape[1], height=array.shape[0],
                  count=1, dtype="uint8", crs="EPSG:3857",
                  transform=from_origin(0, 100, 10, 10))
    ds.write(array, 1)
    return mem, ds


def to_geo(polygon):
    from pyproj import Transformer
    from pilot import _reproject
    tx = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True).transform
    return _reproject(polygon, tx)


def test_exact_split_area():
    a = np.full((10, 10), 7, dtype=np.uint8)  # Dynamic World: bare
    a[:, 5:] = 1  # trees
    mem, ds = make_raster(a)
    try:
        p = aggregate_polygon(ds, to_geo(box(0, 0, 100, 100)), 0, 0, "dynamic_world")
        assert p["bare"] == pytest.approx(50, abs=0.02)
        assert p["trees"] == pytest.approx(50, abs=0.02)
        assert sum(p.values()) == pytest.approx(100, abs=0.02)
    finally:
        ds.close(); mem.close()


def test_partial_pixel_intersection_not_pixel_center_only():
    a = np.full((10, 10), 7, dtype=np.uint8)
    a[:, 5:] = 1
    mem, ds = make_raster(a)
    try:
        p = aggregate_polygon(ds, to_geo(box(0, 0, 55, 100)), 0, 0, "dynamic_world")
        assert p["bare"] == pytest.approx(100 * 50/55, abs=0.02)
        assert p["trees"] == pytest.approx(100 * 5/55, abs=0.02)
    finally:
        ds.close(); mem.close()


def test_missing_raster_area_is_unknown():
    a = np.full((10, 10), 7, dtype=np.uint8)
    mem, ds = make_raster(a)
    try:
        p = aggregate_polygon(ds, to_geo(box(0, 0, 200, 100)), 0, 0, "dynamic_world")
        assert p["unknown"] == pytest.approx(50, abs=0.02)
        assert p["bare"] == pytest.approx(50, abs=0.02)
    finally:
        ds.close(); mem.close()


def test_exclusion_at_exact_threshold():
    p = {"trees":80, "bare":20, "unknown":0}
    assert decision(p, "mars_dry")[0] == "excluded"


def test_uncertain_mixed_cell_review():
    p = {"trees":70, "bare":10, "unknown":20}
    assert decision(p, "mars_dry")[0] == "review"


def test_certain_acceptable_cell_retained():
    p = {"trees":20, "bare":70, "unknown":10}
    assert decision(p, "mars_dry")[0] == "retained"


def test_ice_preserved_and_water_unresolved():
    p = {"snow_ice_unspecified":95, "trees":0, "unknown":5}
    assert decision(p, "polar_analog")[0] == "retained"
    assert CLASS_MAPS["dynamic_world"][0] == "water_unspecified"


def test_inadequate_coverage_review():
    assert decision({"trees":35, "unknown":60}, "mars_dry")[0] == "review"


def test_esri_cloud_is_unknown_not_ice():
    assert CLASS_MAPS["esri_io"][10] == "unknown"
    assert CLASS_MAPS["esri_io"][9] == "snow_ice_unspecified"
