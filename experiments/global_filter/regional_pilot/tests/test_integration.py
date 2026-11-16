"""Integration tests on real H3 resolution-8 geometry.

All rasters here are SYNTHETIC test fixtures written to pytest's tmp_path. None of
their values are satellite observations, and their source ids say so.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import h3
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import rasterio
import shapely
from pyproj import Transformer
from rasterio.transform import from_origin

import pilot

# Drumheller badlands, Alberta (inside the NASADEM pilot's AOI). Location only.
LAT, LON = 51.4714, -112.72
UTM12N = "EPSG:32612"
SYNTHETIC_ID = "SYNTHETIC-TEST-FIXTURE-NOT-OBSERVED"
DW = {v: k for k, v in pilot.CLASS_MAPS["dynamic_world"].items()}  # name -> code
TO_UTM = Transformer.from_crs("EPSG:4326", UTM12N, always_xy=True)


def write_tif(path, array, transform, crs=UTM12N, nodata=None):
    with rasterio.open(path, "w", driver="GTiff", width=array.shape[1], height=array.shape[0],
                       count=1, dtype=array.dtype, crs=crs, transform=transform,
                       nodata=nodata) as dst:
        dst.write(array, 1)
    return path


def utm_grid(half_m=2500, px=10.0):
    """A 10 m UTM grid centred on the H3 r8 cell holding (LAT, LON)."""
    clat, clon = h3.cell_to_latlng(h3.latlng_to_cell(LAT, LON, 8))
    cx, cy = TO_UTM.transform(clon, clat)
    x0, y0 = round(cx) - half_m, round(cy) + half_m
    n = int(2 * half_m / px)
    xs = x0 + (np.arange(n) + 0.5) * px  # pixel-centre eastings
    return from_origin(x0, y0, px, px), n, cx, xs


def args_for(raster, output, **kw):
    argv = ["--raster", str(raster), "--lat", str(LAT), "--lon", str(LON),
            "--resolution", str(kw.pop("resolution", 8)),
            "--ring", str(kw.pop("ring", 1)), "--scheme", kw.pop("scheme", "dynamic_world"),
            "--mission", kw.pop("mission", "mars_dry"),
            "--source-asset-id", SYNTHETIC_ID, "--source-version", "test",
            "--observation-start", kw.pop("start", "2025-07-01"),
            "--observation-end", kw.pop("end", "2025-07-01"),
            "--output", str(output)]
    if "nodata" in kw:
        argv += ["--nodata", str(kw.pop("nodata"))]
    assert not kw
    return pilot.parse(argv)


# ----------------------------------------------------------------- H3 r8 generation


@pytest.mark.parametrize("resolution", [7, 8])
def test_ring_cells_are_valid_cells(resolution):
    centre = h3.latlng_to_cell(LAT, LON, resolution)
    one, seven = pilot.ring_cells(LAT, LON, 0, resolution), pilot.ring_cells(LAT, LON, 1, resolution)
    assert one == [centre]
    assert len(seven) == 7 and centre in seven and set(one) < set(seven)
    assert all(h3.is_valid_cell(c) and h3.get_resolution(c) == resolution for c in seven)
    assert len(pilot.ring_cells(LAT, LON, 5)) == 91
    with pytest.raises(ValueError):
        pilot.ring_cells(LAT, LON, 6)
    with pytest.raises(ValueError):
        pilot.ring_cells(LON, LAT, 0)  # swapped arguments: latitude out of range


def test_r7_default_run_metadata(tmp_path):
    transform, n, _, _ = utm_grid(half_m=4000, px=100)
    tif = write_tif(tmp_path / "r7.tif", np.full((n,n), DW["bare"], np.uint8), transform, nodata=255)
    args = args_for(tif, tmp_path / "r7", resolution=7, ring=0)
    manifest = pilot.run(args)
    assert manifest["h3_resolution"] == 7
    row = pilot.read_cells(tmp_path / "r7").to_pylist()[0]
    assert row["resolution"] == 7 and h3.get_resolution(row["h3_cell"]) == 7
    assert row["cell_area_km2"] > 4
    assert pilot.ring_cells(LAT,LON,0) == [h3.latlng_to_cell(LAT,LON,7)]


def test_cell_polygon_matches_h3_geometry_and_area():
    for cell in pilot.ring_cells(LAT, LON, 1, resolution=8):
        poly = pilot.cell_polygon(cell)
        ref = shapely.geometry.shape(h3.cells_to_geo([cell]))
        assert poly.normalize().equals_exact(ref.normalize(), 1e-12)
        lat, lon = h3.cell_to_latlng(cell)
        laea = pilot._laea_transformer("EPSG:4326", lat, lon)
        area_km2 = pilot._reproject(poly, laea).area / 1e6
        # Ellipsoidal vs H3's spherical area differ by well under 1 % at 51 N.
        assert area_km2 == pytest.approx(h3.cell_area(cell, unit="km^2"), rel=0.01)
        assert 0.6 < area_km2 < 0.9  # r8 cells average 0.737 km^2


def test_cell_polygon_rejects_antimeridian_cells():
    cell = h3.latlng_to_cell(0.0, 179.9999, 8)
    crossing = [c for c in h3.grid_disk(cell, 2)
                if np.ptp([lon for _, lon in h3.cell_to_boundary(c)]) > 180]
    assert crossing, "fixture should contain a cell spanning the antimeridian"
    with pytest.raises(ValueError):
        pilot.cell_polygon(crossing[0])


# ----------------------------------------------------------- area-weighted classes


def test_area_weighting_matches_independent_h3_point_sampling(tmp_path):
    """West of the cell centre is bare, east is trees. The exact overlay must agree with
    an independent estimate: dense points assigned by H3's own latlng_to_cell."""
    transform, n, cx, xs = utm_grid()
    arr = np.where(xs[None, :] < cx, DW["bare"], DW["trees"]).astype(np.uint8).repeat(n, 0)
    tif = write_tif(tmp_path / "split.tif", arr, transform)
    cell = h3.latlng_to_cell(LAT, LON, 8)
    clat, clon = h3.cell_to_latlng(cell)
    with rasterio.open(tif) as src:
        p = pilot.aggregate_polygon(src, pilot.cell_polygon(cell), clat, clon, "dynamic_world")
    assert sum(p.values()) == pytest.approx(100, abs=1e-6)
    assert p["unknown"] == pytest.approx(0, abs=1e-6)

    # Independent estimate: 4 m point lattice in UTM (an equal-area-enough plane at
    # this scale), each point assigned to a cell by H3 itself.
    gx, gy = np.meshgrid(np.arange(cx - 700, cx + 700, 4.0), np.arange(-700, 700, 4.0))
    _, cy = TO_UTM.transform(clon, clat)
    gy = gy + cy
    lon, lat = Transformer.from_crs(UTM12N, "EPSG:4326", always_xy=True).transform(gx.ravel(), gy.ravel())
    inside = np.fromiter((h3.latlng_to_cell(a, b, 8) == cell for a, b in zip(lat, lon)), bool)
    west = (gx.ravel()[inside] < cx).mean() * 100
    assert p["bare"] == pytest.approx(west, abs=0.5)
    assert p["trees"] == pytest.approx(100 - west, abs=0.5)


def test_uniform_raster_conserves_area_over_seven_cells(tmp_path):
    transform, n, _, _ = utm_grid()
    tif = write_tif(tmp_path / "bare.tif", np.full((n, n), DW["bare"], np.uint8), transform)
    with rasterio.open(tif) as src:
        for cell in pilot.ring_cells(LAT, LON, 1, resolution=8):
            lat, lon = h3.cell_to_latlng(cell)
            p = pilot.aggregate_polygon(src, pilot.cell_polygon(cell), lat, lon, "dynamic_world")
            assert p["bare"] == pytest.approx(100, abs=1e-5)
            assert p["unknown"] == pytest.approx(0, abs=1e-5)


# ------------------------------------------------- nodata / unknown is conservative


def test_untagged_dynamic_world_raster_is_refused(tmp_path):
    """Earth Engine writes masked pixels as 0 (= DW water) unless noData is set."""
    transform, n, _, _ = utm_grid()
    arr = np.full((n, n), DW["bare"], np.uint8)
    arr[:, : n // 2] = 0
    tif = write_tif(tmp_path / "untagged.tif", arr, transform, nodata=None)
    with rasterio.open(tif) as src:
        with pytest.raises(ValueError, match="no-data"):
            pilot.check_categorical_raster(src, "dynamic_world")
        pilot.check_categorical_raster(src, "esri_io")  # Esri code 0 is already No Data
        pilot.check_categorical_raster(src, "dynamic_world", nodata_override=255)
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="no-data"):
        pilot.run(args_for(tif, out))
    assert not out.exists()  # no empty directory left behind to block a rerun


def test_tagged_nodata_counts_as_unknown_and_forces_review(tmp_path):
    transform, n, _, _ = utm_grid()
    arr = np.full((n, n), DW["trees"], np.uint8)
    arr[: n // 2, :] = 255  # northern half masked (e.g. cloud)
    tif = write_tif(tmp_path / "masked.tif", arr, transform, nodata=255)
    cell = h3.latlng_to_cell(LAT, LON, 8)
    lat, lon = h3.cell_to_latlng(cell)
    with rasterio.open(tif) as src:
        pilot.check_categorical_raster(src, "dynamic_world")
        p = pilot.aggregate_polygon(src, pilot.cell_polygon(cell), lat, lon, "dynamic_world")
    assert 30 < p["unknown"] < 70 and p["water_unspecified"] == 0
    assert pilot.decision(p, "mars_dry")[0] == "review"


def test_non_integer_or_rgb_like_rasters_are_refused(tmp_path):
    transform, n, _, _ = utm_grid(half_m=100)
    tif = write_tif(tmp_path / "float.tif", np.zeros((n, n), np.float32), transform, nodata=-1)
    with rasterio.open(tif) as src:
        with pytest.raises(ValueError, match="integer"):
            pilot.check_categorical_raster(src, "dynamic_world")


def test_coastal_cell_beyond_raster_footprint_is_review_not_excluded(tmp_path):
    """Water on the covered half, no raster beyond the shoreline: the missing half is
    unknown, so the cell cannot be called excluded (or ocean) from this source."""
    transform, n, cx, xs = utm_grid()
    keep = xs < cx  # raster stops at the cell centre's easting
    arr = np.full((n, int(keep.sum())), DW["water_unspecified"], np.uint8)
    tif = write_tif(tmp_path / "coast.tif", arr, transform, nodata=255)
    cell = h3.latlng_to_cell(LAT, LON, 8)
    lat, lon = h3.cell_to_latlng(cell)
    with rasterio.open(tif) as src:
        p = pilot.aggregate_polygon(src, pilot.cell_polygon(cell), lat, lon, "dynamic_world")
    assert p["water_unspecified"] == pytest.approx(100 - p["unknown"], abs=1e-5)
    assert 30 < p["unknown"] < 70
    assert pilot.decision(p, "mars_dry") == ("review", "insufficient_observed_area")


def test_mixed_cell_near_threshold():
    fully_observed = {"trees": 79.9, "bare": 20.1, "unknown": 0}
    assert pilot.decision(fully_observed, "mars_dry")[0] == "retained"
    slightly_unknown = {"trees": 75, "bare": 20, "unknown": 5}
    assert pilot.decision(slightly_unknown, "mars_dry") == (
        "review", "uncertainty_could_change_exclusion")


def test_snow_ice_is_never_auto_excluded():
    p = {"snow_ice_unspecified": 100.0, "unknown": 0.0}
    for mission in pilot.MISSIONS:
        assert "snow_ice_unspecified" not in pilot.MISSIONS[mission]
        assert pilot.decision(p, mission)[0] == "retained"


# ------------------------------------------------------- end-to-end Parquet + manifest


def test_run_writes_partitioned_parquet_and_manifest(tmp_path):
    transform, n, cx, xs = utm_grid()
    # Trees west of a north-south line just east of the westernmost cell, bare east of
    # it: that cell is wholly trees (excluded), the eastern cells wholly bare (retained).
    east_edge = min(max(TO_UTM.transform(lon, lat)[0] for lat, lon in h3.cell_to_boundary(c))
                    for c in pilot.ring_cells(LAT, LON, 1, resolution=8))
    arr = np.where(xs[None, :] < east_edge + 20, DW["trees"], DW["bare"]).astype(np.uint8).repeat(n, 0)
    tif = write_tif(tmp_path / "scene.tif", arr, transform, nodata=255)
    out = tmp_path / "run"
    manifest = pilot.run(args_for(tif, out))

    assert (out / "manifest.json").is_file()
    assert json.loads((out / "manifest.json").read_text(encoding="utf-8")) == manifest
    assert manifest["h3_resolution"] == 8 and manifest["cells_count"] == 7
    assert sum(manifest["decision_counts"].values()) == 7
    assert manifest["source_asset_id"] == SYNTHETIC_ID
    assert len(manifest["raster"]["sha256"]) == 64 and manifest["raster"]["nodata"] == 255
    assert manifest["mission_exclusion_classes"] == list(pilot.MISSIONS["mars_dry"])
    assert {"h3", "rasterio", "gdal", "pyarrow"} <= manifest["software"].keys()

    parts = sorted(p.relative_to(out).as_posix() for p in out.rglob("*.parquet"))
    assert all(p.startswith("cells/mission=mars_dry/decision=") for p in parts)
    assert parts == sorted(f["path"] for f in manifest["parquet_files"])
    assert sum(f["rows"] for f in manifest["parquet_files"]) == 7
    table = pilot.read_cells(out)
    assert table.num_rows == 7
    assert sorted(table["h3_cell"].to_pylist()) == manifest["cells"]
    assert set(table["mission"].to_pylist()) == {"mars_dry"}
    rows = table.to_pylist()
    pct_cols = [f"pct_{c}" for c in pilot.ALL_CLASSES]
    for r in rows:  # every class percentage kept, also for excluded cells
        assert sum(r[c] for c in pct_cols) == pytest.approx(100, abs=1e-3)
        assert r["ocean_pct"] is None and r["permanent_ice_pct"] is None
        assert r["decision"] == pilot.decision(
            {c: r[f"pct_{c}"] for c in pilot.ALL_CLASSES}, "mars_dry")[0]
    assert any(r["decision"] == "excluded" for r in rows)
    assert any(r["decision"] == "retained" for r in rows)

    for f in manifest["parquet_files"]:
        schema = pq.read_schema(out / f["path"])
        assert "mission" not in schema.names and "decision" not in schema.names  # hive
        for col in ("ocean_pct", "inland_water_pct", "permanent_ice_pct", "seasonal_snow_pct"):
            assert schema.field(col).type == pa.float64()  # not an inferred null type
        assert schema.field("observation_start").type == pa.date32()

    with pytest.raises(FileExistsError):
        pilot.run(args_for(tif, out))


def test_layout_is_readable_by_a_standard_hive_reader(tmp_path):
    try:
        import pyarrow._dataset_parquet  # noqa: F401
        import pyarrow.dataset as ds
    except ImportError as exc:  # e.g. blocked by Windows Application Control
        pytest.skip(f"pyarrow.dataset Parquet support unavailable here: {exc}")
    transform, n, _, _ = utm_grid()
    tif = write_tif(tmp_path / "bare.tif", np.full((n, n), DW["bare"], np.uint8), transform, nodata=255)
    out = tmp_path / "run"
    pilot.run(args_for(tif, out, ring=0))
    table = ds.dataset(out / "cells", format="parquet", partitioning="hive").to_table()
    assert table.num_rows == 1
    assert table["decision"].to_pylist() == ["retained"]


@pytest.mark.parametrize("start,end", [("2025-07-02", "2025-07-01"), ("2025-7-1", "2025-07-01"),
                                       ("July 2025", "2025-07-31")])
def test_run_rejects_bad_observation_dates(tmp_path, start, end):
    out = tmp_path / "out"
    with pytest.raises(ValueError):
        pilot.run(args_for(tmp_path / "missing.tif", out, start=start, end=end))
    assert not out.exists()


def test_missing_raster_leaves_no_output(tmp_path):
    out = tmp_path / "out"
    with pytest.raises(rasterio.errors.RasterioIOError):
        pilot.run(args_for(tmp_path / "missing.tif", out))
    assert not out.exists()
