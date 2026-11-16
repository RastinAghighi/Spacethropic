"""Synthetic fixtures verify mechanics; observed regression is separately labelled."""

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core
import h3
import numpy as np
import pyarrow.parquet as pq
import pytest
from run import execute, parent_ids
from validate import AUDIT, AuditObservations


class Synthetic:
    source_id = "SYNTHETIC-TEST-ONLY"

    def __init__(self, flag=0):
        self.flag = flag

    def sample(self, lat, lon):
        n = len(lat)
        frac = np.zeros((17, n))
        frac[16] = 1
        return dict(
            flags=np.full(n, self.flag, np.uint16),
            land=np.ones(n, bool),
            density=np.zeros(n),
            fractions=frac,
            class_known=np.ones(n, bool),
            groups=np.vstack([np.zeros((3, n)), np.ones(n)]),
        )


@pytest.mark.parametrize("res", [0, 7, 8])
def test_geometry_at_poles_dateline_and_pentagons(res):
    cells = [
        h3.latlng_to_cell(90, 0, res),
        h3.latlng_to_cell(-90, 0, res),
        h3.latlng_to_cell(0, 180, res),
        *h3.get_pentagons(res),
    ]
    for cell in cells:
        lat, lon, ar = core.cell_samples(cell)
        assert np.all(ar > 0)
        assert abs(ar.sum() / h3.cell_area(cell, unit="km^2") - 1) < 1e-7
        # Every sample must actually be in its intended spherical H3 polygon.
        assert all(h3.latlng_to_cell(a, b, res) == cell for a, b in zip(lat, lon))


def test_pixel_area_and_dateline():
    assert np.isclose(core.pixel_areas().sum() * core.W, 4 * math.pi * core.R_KM**2)
    r, c = core.pixel_indices([90, -90, 0, 0], [-180, 180, -180, 180])
    assert list(r) == [0, 3599, 1800, 1800]
    assert list(c) == [0, 0, 0, 0]


def test_baseline_thresholds_and_missing():
    n = 7
    flags = core.policy_flags(
        np.ones(n, bool),
        np.array([0.5, 0, 0, 0, 0.2, 0, 0], np.float32),
        np.array([0, 0.25, 0, 0, 0.1, 0, 0], np.float32),
        np.array([0, 0, 0.5, 0, 0.2, 0, 0], np.float32),
        np.array([0, 0, 0, 50, 0, np.nan, 0]),
        np.array([1, 1, 1, 1, 1, 1, 0], bool),
        np.array([1, 1, 1, 1, 1, 0, 1], bool),
    )
    assert flags.tolist() == [2, 4, 16, 8, 32, 128, 64]
    cell = h3.latlng_to_cell(40, -110, 7)
    assert core.evaluate(cell, Synthetic(0))["decision"] == "eligible"
    assert core.evaluate(cell, Synthetic(64))["decision"] == "uncertain"
    assert core.evaluate(cell, Synthetic(128))["decision"] == "uncertain"
    assert core.evaluate(cell, Synthetic(16 | 128))["decision"] == "excluded"
    assert core.evaluate(cell, Synthetic(16 | 256))["decision"] == "uncertain"


def test_complete_globe_partition_enumeration_and_resume(tmp_path):
    # All real r0 cells, synthetic observations; exact complete global enumeration.
    sampler = Synthetic()
    first = execute(
        sampler,
        tmp_path,
        resolution=0,
        parent_resolution=0,
        subdivisions=2,
        limit=3,
        min_free_gb=0,
    )
    assert first["status"] == "partial" and first["evaluated_cells"] == 3
    checkpoints = sorted((tmp_path / "checkpoints").glob("*.json"))
    mtimes = {p: p.stat().st_mtime_ns for p in checkpoints}
    result = execute(
        sampler,
        tmp_path,
        resolution=0,
        parent_resolution=0,
        subdivisions=2,
        min_free_gb=0,
    )
    assert result["status"] == "complete" and result["evaluated_cells"] == 122
    assert result["candidate_cells"] == 122
    assert np.isclose(result["area_km2"]["whole_cells"], 4 * math.pi * core.R_KM**2)
    assert all(p.stat().st_mtime_ns == m for p, m in mtimes.items())
    ids = []
    for p in (tmp_path / "cells").rglob("*.parquet"):
        ids += pq.ParquetFile(p).read(columns=["h3_cell"]).column(0).to_pylist()
    assert len(set(ids)) == len(ids) == 122
    with pytest.raises(ValueError, match="changed"):
        execute(
            sampler,
            tmp_path,
            resolution=0,
            parent_resolution=0,
            subdivisions=3,
            min_free_gb=0,
        )
    cp = json.loads(checkpoints[0].read_text())
    (tmp_path / cp["parquet"]["path"]).write_bytes(b"damaged")
    with pytest.raises(ValueError, match="corrupt"):
        execute(
            sampler,
            tmp_path,
            resolution=0,
            parent_resolution=0,
            subdivisions=2,
            min_free_gb=0,
        )


def test_deterministic_partitions_and_empty_output(tmp_path):
    parents = [h3.latlng_to_cell(40, -110, 6)]
    for name in ("a", "b"):
        execute(
            Synthetic(),
            tmp_path / name,
            resolution=7,
            parent_resolution=6,
            parents=parents,
            subdivisions=2,
            min_free_gb=0,
        )
    paths = [
        next((tmp_path / name / "cells").rglob("*.parquet")) for name in ("a", "b")
    ]
    assert core.digest(paths[0]) == core.digest(paths[1])
    m = execute(
        Synthetic(16),
        tmp_path / "empty",
        resolution=7,
        parent_resolution=6,
        parents=parents,
        subdivisions=2,
        min_free_gb=0,
    )
    assert m["candidate_cells"] == 0 and m["counts"]["excluded"] == 7
    p = next((tmp_path / "empty" / "cells").rglob("*.parquet"))
    assert pq.ParquetFile(p).metadata.num_rows == 0


def test_real_audit_snapshot_centers_and_unknown():
    s = AuditObservations(AUDIT / "site_validation_detail.json")
    for name, expected in [
        ("drumheller", "excluded"),
        ("atacama_yungay", "eligible"),
        ("hanksville_mdrs", "eligible"),
        ("mcmurdo_beacon", "eligible"),
    ]:
        site = s.data[name]["site"]
        row = core.evaluate(h3.latlng_to_cell(site["lat"], site["lon"], 7), s)
        assert row["decision"] == expected
        assert all(row[f"lc_{k:02d}_fraction"] is None for k in range(17))
    row = core.evaluate(h3.latlng_to_cell(10, 10, 7), s)
    assert row["decision"] == "uncertain"
    assert row["eligible_fraction"] == 0


def test_parent_enumeration_pentagons_unique():
    parents = parent_ids(1)
    assert len(parents) == len(set(parents)) == h3.get_num_cells(1)
    descendants = [c for p in parents for c in h3.cell_to_children(p, 2)]
    assert len(descendants) == len(set(descendants)) == h3.get_num_cells(2)


def test_mask_preparation_roundtrip_and_area_accounting(tmp_path, monkeypatch):
    # A tiny global-grid SYNTHETIC fixture exercises actual mask/GeoTIFF/memmap
    # preparation and the production loader, without allocating global test data.
    import prepare

    for module in (core, prepare):
        monkeypatch.setattr(module, "H", 4)
        monkeypatch.setattr(module, "W", 8)
        monkeypatch.setattr(module, "DEG", 45.0)
    base = tmp_path / "base"
    base.mkdir()
    land = np.ones((4, 8), dtype=np.uint8)
    land[0, 0] = 0
    density = np.zeros((4, 8))
    density[1, 0] = 50
    density[1, 1] = np.nan
    np.save(base / "land.npy", land)
    np.save(base / "density.npy", density)
    core.atomic_json(
        base / "manifest.json",
        dict(
            status="complete",
            files={
                name: prepare.file_info(base / name)
                for name in ("land.npy", "density.npy")
            },
        ),
    )
    counts = np.zeros((17, 4, 8), dtype=np.uint8)
    counts[16] = 100
    counts[16, 0, 1] = 0
    counts[0, 0, 1] = 100
    counts[:, 0, 2] = 0
    cp = tmp_path / "counts.npy"
    np.save(cp, counts)
    out = tmp_path / "mask"
    prepare.build_mask(base, cp, None, out)
    mask = core.Mask(out)
    assert mask.flags[0, 0] == core.BITS["ocean"]
    assert mask.flags[0, 1] == core.BITS["water"]
    assert mask.flags[0, 2] == core.BITS["missing_landcover"]
    assert mask.flags[1, 0] == core.BITS["population"]
    assert mask.flags[1, 1] == core.BITS["missing_population"]
    stats = mask.manifest["area_km2"]
    assert stats["eligible_land"] + stats["uncertain_land"] + stats[
        "excluded_land"
    ] == pytest.approx(stats["land"])
    # Site lies wholly in the synthetic water pixel; verifies loader indexing.
    row = core.evaluate(h3.latlng_to_cell(60, -110, 7), mask)
    assert row["decision"] == "excluded"
    assert row["lc_00_fraction"] == pytest.approx(1)
    stamp = (out / "flags.npy").stat().st_mtime_ns
    prepare.build_mask(base, cp, None, out)
    assert (out / "flags.npy").stat().st_mtime_ns == stamp
