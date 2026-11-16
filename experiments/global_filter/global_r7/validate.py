"""Regression on real, committed audit observations; NOT a fresh raw-MODIS run."""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

import h3
import numpy as np
import psutil
import pyarrow as pa
import pyarrow.parquet as pq
from core import (
    BITS,
    Mask,
    W,
    atomic_json,
    cell_samples,
    digest,
    evaluate,
    pixel_indices,
    policy_flags,
)
from run import schema

AUDIT = Path(__file__).resolve().parents[2] / "landcover_audit_2023" / "results"
SITES = (
    "drumheller",
    "atacama_yungay",
    "hanksville_mdrs",
    "mcmurdo_beacon",
    "mcmurdo_don_juan",
)


class AuditObservations:
    """Sparse genuine observations. Unreported pixels are unknown, never filled in.

    Group fractions are rounded in the original report. Individual IGBP fractions
    are deliberately null: the report's text percentages are not original counts.
    Land outside the recorded footprint is unobserved (land_fraction lower bound).
    """

    source_kind = "rounded_audit_snapshot_not_global_inputs"

    def __init__(self, path):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text())
        self.source_id = digest(self.path)
        pixels = {}
        for site in self.data.values():
            for px in site["pixels"]:
                key = px["rc"][0] * W + px["rc"][1]
                if key in pixels and pixels[key] != px:
                    raise ValueError("Conflicting audit observations")
                pixels[key] = px
        self.keys = np.array(sorted(pixels), dtype=np.int64)
        rows = [pixels[int(k)] for k in self.keys]
        self.groups = np.array(
            [
                [r["shares"][k] for r in rows]
                for k in ("water", "built", "veg", "other")
            ],
            np.float32,
        )
        self.density = np.array([r["pop_per_km2"] for r in rows], float)
        # The audit's Pacific control has no class counts and is excluded by NE.
        observed = self.groups.sum(axis=0) > 0
        self.land = np.array(
            [not (r["decision"] == "water" and r["classes"] == "no data") for r in rows]
        )
        self.flags = policy_flags(
            self.land,
            *self.groups[:3],
            self.density,
            observed,
            np.ones(len(rows), bool),
        )
        for row, flag in zip(rows, self.flags):
            if bool(flag == 0) != (row["decision"] == "kept"):
                raise ValueError(
                    f"Rounded audit observation changes baseline decision: {row}"
                )

    def sample(self, lat, lon):
        r, c = pixel_indices(lat, lon)
        keys = r * W + c
        i = np.searchsorted(self.keys, keys)
        pos = np.minimum(i, len(self.keys) - 1)
        found = (i < len(self.keys)) & (self.keys[pos] == keys)
        n = len(keys)
        return dict(
            flags=np.where(
                found,
                self.flags[pos],
                BITS["missing_landcover"] | BITS["missing_population"],
            ),
            land=found & self.land[pos],
            density=np.where(found, self.density[pos], np.nan),
            fractions=np.zeros((17, n)),
            class_known=np.zeros(n, bool),
            groups=np.where(found[None, :], self.groups[:, pos], 0),
        )


def polygon_feature(row, site):
    coords = [(lo, la) for la, lo in h3.cell_to_boundary(row["h3_cell"])]
    return dict(
        type="Feature",
        geometry=dict(type="Polygon", coordinates=[coords + coords[:1]]),
        properties={
            **row,
            "site": site,
            "data_scope": "committed audit observations only",
        },
    )


def validate(output, benchmark_repeats=10, public=None, mask=None):
    output.mkdir(parents=True, exist_ok=True)
    snapshot = AuditObservations(AUDIT / "site_validation_detail.json")
    sampler = Mask(mask) if mask else snapshot
    expected = {
        r["id"]: r for r in csv.DictReader((AUDIT / "r7_hex_filter_sites.csv").open())
    }
    results, features, rows, timed_cells = [], [], [], []
    for site_id in SITES:
        site = snapshot.data[site_id]["site"]
        center = h3.latlng_to_cell(site["lat"], site["lon"], 7)
        cells = sorted(h3.grid_disk(center, 2))
        records = [evaluate(c, sampler) for c in cells]
        refined = [evaluate(c, sampler, subdivisions=16) for c in cells]
        center_row = next(r for r in records if r["h3_cell"] == center)
        results.append(
            dict(
                site=site_id,
                site_h3=center,
                site_decision=center_row["decision"],
                expected_site_kept=expected[site_id]["site_r7_kept"] == "True",
                site_matches_audit=center_row["baseline_kept"]
                == (expected[site_id]["site_r7_kept"] == "True"),
                cells=len(records),
                eligible=sum(r["decision"] == "eligible" for r in records),
                uncertain=sum(r["decision"] == "uncertain" for r in records),
                excluded=sum(r["decision"] == "excluded" for r in records),
                complete_observation_cells=sum(
                    r["uncertain_fraction"] < 1e-10 for r in records
                ),
                expected_original_kept_of_19=int(expected[site_id]["r7_kept"]),
                max_fraction_change_8_to_16=max(
                    abs(a["excluded_fraction"] - b["excluded_fraction"])
                    for a, b in zip(records, refined)
                ),
                decision_changes_8_to_16=sum(
                    a["decision"] != b["decision"] for a, b in zip(records, refined)
                ),
            )
        )
        rows.extend(records)
        features.extend(polygon_feature(row, site_id) for row in records)
        timed_cells.extend(cells)
    # Original report has only 8 Drumheller pixels, not its whole ring window.
    # Compare centers; expose any ring area not present in the committed snapshot.
    if not all(r["site_matches_audit"] for r in results):
        raise AssertionError("Site regression failed")
    if any(r["eligible"] == 0 for r in results):
        raise AssertionError("An analog region has no eligible cell")
    sample_name = "mask_sample" if mask else "audit_sample"
    if mask:
        for feature in features:
            feature["properties"]["data_scope"] = "prepared global input mask"
    pq.write_table(
        pa.Table.from_pylist(rows, schema=schema()),
        output / f"{sample_name}.parquet",
        compression="zstd",
    )
    atomic_json(
        output / f"{sample_name}.geojson",
        dict(type="FeatureCollection", features=features),
    )
    # Kernel benchmark uses real observations repeatedly, with no invented global inputs.
    start = time.perf_counter()
    for _ in range(benchmark_repeats):
        for cell in timed_cells:
            evaluate(cell, sampler)
    seconds = time.perf_counter() - start
    n = len(timed_cells) * benchmark_repeats
    benchmark = dict(
        measured_evaluations=n,
        seconds=seconds,
        cells_per_second=n / seconds,
        naive_all_earth_hours=h3.get_num_cells(7) / (n / seconds) / 3600,
        peak_rss_bytes=psutil.Process().memory_info().rss,
        scope="Repeated real audit windows, single process; excludes global mmap I/O and output overhead",
        global_feasibility="Not established without global MODIS; extrapolation is not a global benchmark",
    )
    geometry = []
    probes = [
        h3.latlng_to_cell(90, 0, 7),
        h3.latlng_to_cell(-90, 0, 7),
        h3.latlng_to_cell(0, 180, 7),
        *h3.get_pentagons(7),
    ]
    for cell in probes:
        _, _, ar = cell_samples(cell)
        geometry.append(
            dict(
                cell=cell,
                relative_area_error=abs(ar.sum() / h3.cell_area(cell, unit="km^2") - 1),
            )
        )
    comparisons = []
    if public:
        density = np.load(public / "density.npy", mmap_mode="r")
        land = np.load(public / "land.npy", mmap_mode="r")
        for site_id in SITES:
            px = snapshot.data[site_id]["pixels"]
            errors = [
                abs(float(density[p["rc"][0], p["rc"][1]]) - p["pop_per_km2"])
                for p in px
            ]
            comparisons.append(
                dict(
                    site=site_id,
                    max_density_difference_from_rounded_audit=max(errors),
                    all_observed_pixels_on_ne_land=all(
                        land[p["rc"][0], p["rc"][1]] for p in px
                    ),
                )
            )
    report = dict(
        status="passed_mask_regression" if mask else "passed_snapshot_regression",
        provenance_id=sampler.source_id,
        source=str(mask) if mask else str(snapshot.path),
        source_type="prepared global MODIS mask"
        if mask
        else "real committed rounded audit observations, not newly read MODIS",
        sites=results,
        geometry=geometry,
        benchmark=benchmark,
        public_data_comparisons=comparisons,
        sample_rows=len(rows),
        sample_candidates=sum(r["decision"] != "excluded" for r in rows),
        sample_parquet_bytes=(output / f"{sample_name}.parquet").stat().st_size,
        limitations=(
            ["Coarse 0.05 degree mask, sampled H3 fractions", "MODIS-only, Esri absent"]
            if mask
            else [
                "Sparse observation footprint; unknown outside it",
                "Detailed IGBP fractions null, only reported groups known",
                "Original QC not present; snow/ice remains permissive",
                "Full global execution and fresh MODIS validation blocked by missing input",
            ]
        ),
    )
    atomic_json(output / "validation.json", report)
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--public", type=Path)
    p.add_argument(
        "--mask",
        type=Path,
        help="Validate newly prepared global data instead of the audit snapshot",
    )
    p.add_argument("--benchmark-repeats", type=int, default=10)
    p.add_argument(
        "--partitioned",
        action="store_true",
        help="Also exercise resumable Parquet output on these 95 cells",
    )
    a = p.parse_args()
    validate(a.output, a.benchmark_repeats, a.public, a.mask)
    if a.partitioned:
        from run import execute

        snapshot = AuditObservations(AUDIT / "site_validation_detail.json")
        cells = sorted(
            {
                c
                for k in SITES
                for c in h3.grid_disk(
                    h3.latlng_to_cell(
                        snapshot.data[k]["site"]["lat"],
                        snapshot.data[k]["site"]["lon"],
                        7,
                    ),
                    2,
                )
            }
        )
        execute(
            Mask(a.mask) if a.mask else snapshot,
            a.output / "partitioned",
            parent_resolution=7,
            parents=cells,
        )
