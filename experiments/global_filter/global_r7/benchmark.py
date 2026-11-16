"""Benchmark complete r3 partitions in representative landscapes using actual global inputs."""

import argparse
from pathlib import Path

import h3
from core import Mask, atomic_json
from run import execute

# Deserts, mixed badlands, rainforest, cropland, urban, ice, coast, date line, poles.
POINTS = [
    (51.4714, -112.72),
    (-24.0638, -69.8805),
    (38.4065, -110.7919),
    (-77.85, 160.6),
    (-3, -60),
    (42, -93),
    (30.04, 31.24),
    (70, -40),
    (0, 180),
    (90, 0),
    (-90, 0),
    (0, 0),
]


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mask", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    parents = sorted(set(h3.latlng_to_cell(lat, lon, 3) for lat, lon in POINTS))
    result = execute(Mask(a.mask), a.output, parents=parents)
    n, t = result["evaluated_cells"], result["processing_seconds"]
    estimate = dict(
        evaluated_cells=n,
        seconds=t,
        cells_per_second=n / t,
        naive_full_globe_hours=h3.get_num_cells(7) / n * t / 3600,
        naive_output_bytes=h3.get_num_cells(7) / n * result["storage_bytes"],
        measured_peak_rss_bytes=result["peak_rss_bytes"],
        caveat="Purposeful representative sample, not area-random; extrapolations are planning estimates only",
    )
    atomic_json(a.output / "benchmark.json", estimate)
    print(estimate)
