import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import h3
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import rasterio
from contours import execute
from rasterio.transform import from_origin


def test_ramp_contours_missing_coverage_and_restart(tmp_path):
    # Synthetic known east-west ramp: every 20 m contour must be vertical.
    dem = tmp_path / "ramp.tif"
    transform = from_origin(-112.8, 51.52, 0.001, 0.001)
    z = np.broadcast_to(np.arange(160, dtype=np.float32) * 2, (100, 160)).copy()
    with rasterio.open(
        dem,
        "w",
        driver="GTiff",
        width=160,
        height=100,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        nodata=-9999,
    ) as dst:
        dst.write(z, 1)
    here = h3.latlng_to_cell(51.4714, -112.72, 7)
    away = h3.latlng_to_cell(-24, -69, 7)
    cells = tmp_path / "cells.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [dict(h3_cell=c, decision="eligible") for c in (here, away)]
        ),
        cells,
    )
    result = execute(cells, dem, tmp_path / "out")
    assert result["coverage"] == {"covered": 1, "no_dem_coverage": 1}
    lines = pq.ParquetFile(tmp_path / "out" / "lines.parquet").read().to_pylist()
    assert len(lines) > 0
    for line in lines:
        assert np.ptp(line["x"]) < 1e-10
        assert line["level_m"] % 20 == 0
        assert line["h3_cell"] == here
    assert execute(cells, dem, tmp_path / "out")["files"] == result["files"]
