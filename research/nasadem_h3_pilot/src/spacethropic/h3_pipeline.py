"""H3 aggregation of validated per-sample terrain layers.

Order of operations, which is the point of the design:

1. ``pipeline.analyze_granule`` reads the granule and computes slope, TRI and
   detrended roughness on the native 1-arc-second grid with a one-sample halo,
   i.e. with the full neighbouring-pixel context. Nothing is recomputed per cell.
2. ``h3grid.assign_grid`` assigns every sample centre to an H3 cell.
3. ``aggregation.aggregate_samples`` groups the samples by cell and computes
   area-weighted statistics with the existing ``stats.summarize`` definitions.
4. ``h3grid.cell_geometry`` measures each cell polygon and its exact overlap with
   the analysed footprint, so partial cells are labelled as partial.

The functions take any AOI and any H3 resolution; nothing here is specific to
Drumheller. Checks that tie the cell results back to the AOI summary run on every call.
"""

from __future__ import annotations

import datetime as _dt
import math
from dataclasses import dataclass, field

import h3
import numpy as np

from . import h3grid
from .aggregation import CellAggregates, aggregate_samples
from .nasadem import BBox
from .pipeline import MEASUREMENT_DEFINITIONS, TerrainLayers, _software_versions
from .stats import summarize

SCHEMA = "spacethropic.h3_terrain_cells/v1"
SOURCE_COLLECTION = "NASADEM_HGT.001"  # LP DAAC short name and version

# Measurement key -> statistics reported per cell (existing measurement keys and definitions).
TERRAIN_STATISTICS: dict[str, tuple[str, ...]] = {
    "elevation": ("mean", "min", "max"),
    "slope": ("mean", "p50", "p95"),
    "roughness_tri": ("mean",),
    "roughness_detrended": ("mean",),
}
UNIT_SUFFIX = {"elevation": "m", "slope": "deg", "roughness_tri": "m", "roughness_detrended": "m"}
DERIVATIVES = ("slope", "roughness_tri", "roughness_detrended")
# Advisory floors from scientific_validation.md section 5.1 (1 m height quantisation).
QUANTISATION_FLOORS = {"slope_p50_deg": 0.5, "roughness_detrended_mean_m": 0.30}

REL_TOL_AREA = 1e-9  # area sums: float64 summation of ~1e5 terms, plus the 1e-11 pixel-area model
REL_TOL_MEAN = 1e-9  # re-composed means; the stored summary keeps 12 significant digits


def stat_column(measurement: str, stat: str) -> str:
    return f"{measurement}_{stat}_{UNIT_SUFFIX[measurement]}"


@dataclass
class H3TerrainResult:
    resolution: int
    records: list[dict]  # one per cell with at least one sample centre, ascending H3 index
    geometries: list[h3grid.CellGeometry]
    slivers: list[h3grid.CellGeometry]  # overlap the footprint but hold no sample centre
    aggregates: CellAggregates
    footprint: BBox
    samples: dict = field(default_factory=dict, repr=False)  # flattened per-sample inputs (views where possible)
    checks: list[dict] = field(default_factory=list)
    totals: dict = field(default_factory=dict)

    @property
    def all_checks_passed(self) -> bool:
        return all(c["passed"] for c in self.checks)


def _check(checks: list, name: str, passed: bool, detail: str) -> None:
    checks.append({"check": name, "passed": bool(passed), "detail": detail})


def _rel_close(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol * max(abs(a), abs(b), 1e-300)


def terrain_samples(layers: TerrainLayers) -> dict:
    """Flatten the AOI layers (C order, rows north -> south) into per-sample arrays."""
    g = layers.grid
    z = layers.elevation_m.reshape(-1)
    valid = np.isfinite(z)
    water = layers.water.reshape(-1)
    mask = layers.analysis_mask.reshape(-1)
    slope = layers.slope_deg.reshape(-1)
    return {
        "area_m2": np.repeat(np.asarray(layers.cell_area_m2, dtype=np.float64), g.ncols),
        "include": mask,
        "values": {
            "elevation": z,
            "slope": slope,
            "roughness_tri": layers.tri_m.reshape(-1),
            "roughness_detrended": layers.roughness_m.reshape(-1),
        },
        "count_masks": {
            "water": water,
            "void": ~valid,
            "excluded_water": valid & water & ~mask,
            "excluded_other": valid & ~water & ~mask,  # must be zero with the current masks
            "derivative_missing": mask & ~np.isfinite(slope),
        },
    }


def aggregate_terrain(layers: TerrainLayers, resolution: int, source_granules: list[str]) -> H3TerrainResult:
    """Assign the AOI samples to H3 cells at ``resolution`` and compute per-cell terrain statistics."""
    res = h3grid.validate_resolution(resolution)
    samples = terrain_samples(layers)
    cells = h3grid.assign_grid(layers.grid, res)
    agg = aggregate_samples(
        cells, samples["area_m2"], samples["values"], samples["include"], TERRAIN_STATISTICS, samples["count_masks"]
    )
    footprint = layers.grid.pixel_edge_bounds()  # union of the analysed pixels' footprints
    geoms = [h3grid.cell_geometry(int(c), footprint) for c in agg.cell_ids]
    slivers = h3grid.uncovered_overlapping_cells(agg.cell_ids.tolist(), footprint)
    records = [_record(agg, j, geoms[j], res, source_granules) for j in range(len(agg))]
    result = H3TerrainResult(res, records, geoms, slivers, agg, footprint, samples)
    _conservation_checks(result, samples)
    return result


def _flags(rec: dict) -> list[str]:
    flags = []
    if rec["coverage_status"] == "partial":
        flags.append("partial_coverage")
    if rec["n_excluded_water"]:
        flags.append("water_excluded")
    if rec["n_excluded_void"]:
        flags.append("void_samples")
    if rec["n_derivative_missing"]:
        flags.append("missing_derivatives")
    if rec["n_valid_slope"] == 0:
        flags.append("no_valid_derivatives")
    for col, floor in QUANTISATION_FLOORS.items():
        v = rec[col]
        if v is not None and v < floor:
            flags.append(f"{col}_below_quantisation_floor")
    return flags


def _num(x) -> float | None:
    x = float(x)
    return x if math.isfinite(x) else None


def _record(agg: CellAggregates, j: int, geom: h3grid.CellGeometry, res: int, granules: list[str]) -> dict:
    m = agg.measurements
    valid_deriv_area = float(m["slope"]["valid_area_m2"][j])
    rec = {
        "h3_cell": geom.h3_id,
        "h3_resolution": res,
        "centre_lat_deg": geom.centre_lat,
        "centre_lon_deg": geom.centre_lon,
        "is_pentagon": geom.is_pentagon,
        "coverage_status": "complete" if geom.is_complete else "partial",
        "coverage_fraction_exact_overlap": geom.overlap_area_m2 / geom.area_m2,
        "coverage_fraction_pixel_centre": float(agg.sample_area_m2[j]) / geom.area_m2,
        "valid_coverage_fraction": valid_deriv_area / geom.area_m2,
        "cell_area_km2": geom.area_m2 / 1e6,
        "h3_spherical_cell_area_km2": geom.h3_area_m2 / 1e6,
        "overlap_area_km2": geom.overlap_area_m2 / 1e6,
        "sampled_area_km2": float(agg.sample_area_m2[j]) / 1e6,
        "analysis_area_km2": float(agg.included_area_m2[j]) / 1e6,
        "valid_derivative_area_km2": valid_deriv_area / 1e6,
        "n_samples": int(agg.n_samples[j]),
        "n_analysis": int(agg.n_included[j]),
        "n_excluded_water": int(agg.counts["excluded_water"][j]),
        "n_excluded_void": int(agg.counts["void"][j]),
        "n_derivative_missing": int(agg.counts["derivative_missing"][j]),
        "n_valid_elevation": int(m["elevation"]["count_valid"][j]),
        "n_valid_slope": int(m["slope"]["count_valid"][j]),
        "n_valid_roughness_tri": int(m["roughness_tri"]["count_valid"][j]),
        "n_valid_roughness_detrended": int(m["roughness_detrended"]["count_valid"][j]),
    }
    for meas, stats in TERRAIN_STATISTICS.items():
        for stat in stats:
            rec[stat_column(meas, stat)] = _num(m[meas][stat][j])
    rec["quality_flags"] = ";".join(_flags(rec))
    rec["source_collection"] = SOURCE_COLLECTION
    rec["source_granules"] = ";".join(granules)
    return rec


def _conservation_checks(result: H3TerrainResult, samples: dict) -> None:
    agg, checks = result.aggregates, result.checks
    n = samples["include"].size
    total_area = float(samples["area_m2"].sum())
    footprint_area = h3grid.bbox_area_m2(result.footprint)
    cell_overlap = sum(g.overlap_area_m2 for g in result.geometries)
    sliver_overlap = sum(g.overlap_area_m2 for g in result.slivers)

    _check(checks, "every_sample_assigned_once",
           np.array_equal(np.sort(agg.sample_order), np.arange(n)) and int(agg.n_samples.sum()) == n,
           f"{int(agg.n_samples.sum())} of {n} samples in {len(agg)} cells")
    _check(checks, "sampled_area_conserved", _rel_close(float(agg.sample_area_m2.sum()), total_area, REL_TOL_AREA),
           f"sum over cells {agg.sample_area_m2.sum() / 1e6:.9f} km2 vs AOI {total_area / 1e6:.9f} km2")
    partition = agg.n_included + agg.counts["excluded_water"] + agg.counts["void"] + agg.counts["excluded_other"]
    _check(checks, "sample_partition_per_cell",
           np.array_equal(partition, agg.n_samples) and not agg.counts["excluded_other"].any(),
           "n_samples = n_analysis + n_excluded_water + n_excluded_void in every cell")
    same = all(np.array_equal(agg.measurements[d]["count_valid"], agg.measurements["slope"]["count_valid"])
               for d in DERIVATIVES)
    _check(checks, "derivative_counts_consistent", same, "slope, TRI and detrended roughness share one 3x3 validity rule")
    _check(checks, "footprint_area_matches_pixel_areas", _rel_close(footprint_area, total_area, REL_TOL_AREA),
           f"exact footprint {footprint_area / 1e6:.9f} km2 vs sum of pixel areas {total_area / 1e6:.9f} km2")
    _check(checks, "exact_overlap_conserved",
           _rel_close(cell_overlap + sliver_overlap, footprint_area, REL_TOL_AREA),
           f"cells {cell_overlap / 1e6:.9f} + slivers {sliver_overlap / 1e6:.9f} km2 vs footprint "
           f"{footprint_area / 1e6:.9f} km2")
    _check(checks, "assigned_cells_overlap_footprint", all(g.overlap_area_m2 > 0 for g in result.geometries),
           "every cell holding a sample centre overlaps the analysed footprint")
    complete = [r for r in result.records if r["coverage_status"] == "complete"]
    result.totals = {
        "n_cells": len(result.records),
        "n_cells_complete": len(complete),
        "n_cells_partial": len(result.records) - len(complete),
        "n_cells_without_valid_derivatives": sum(1 for r in result.records if r["n_valid_slope"] == 0),
        "n_sliver_cells_without_samples": len(result.slivers),
        "sliver_overlap_area_km2": sliver_overlap / 1e6,
        "sliver_cells": [g.h3_id for g in result.slivers],
        "n_samples": int(agg.n_samples.sum()),
        "n_analysis": int(agg.n_included.sum()),
        "n_excluded_water": int(agg.counts["excluded_water"].sum()),
        "n_excluded_void": int(agg.counts["void"].sum()),
        "n_derivative_missing": int(agg.counts["derivative_missing"].sum()),
        "sampled_area_km2": float(agg.sample_area_m2.sum()) / 1e6,
        "analysis_area_km2": float(agg.included_area_m2.sum()) / 1e6,
        "valid_derivative_area_km2": float(agg.measurements["slope"]["valid_area_m2"].sum()) / 1e6,
        "footprint_area_km2_exact": footprint_area / 1e6,
        "cell_overlap_area_km2_exact": cell_overlap / 1e6,
        "pixel_centre_vs_exact_overlap_complete_cells": _fraction_range(complete, "coverage_fraction_pixel_centre"),
        "pixel_centre_minus_exact_overlap_all_cells_km2": _diff_range(result.records),
    }


def _fraction_range(records: list[dict], key: str) -> dict | None:
    if not records:
        return None
    v = np.array([r[key] for r in records])
    return {"n": int(v.size), "min": float(v.min()), "max": float(v.max()), "mean": float(v.mean()),
            "note": "complete cells have exact coverage 1; the spread is the pixel-centre discretisation"}


def _diff_range(records: list[dict]) -> dict:
    d = np.array([r["sampled_area_km2"] - r["overlap_area_km2"] for r in records])
    rel = d / np.array([r["overlap_area_km2"] for r in records])
    return {"min_km2": float(d.min()), "max_km2": float(d.max()),
            "max_abs_relative_to_overlap": float(np.abs(rel).max())}


# --------------------------------------------------------------------------- reconciliation


def reconcile(result: H3TerrainResult, aoi_summary: dict, label: str) -> dict:
    """Tie the cell results back to an AOI terrain summary (``analyze_granule`` output or its JSON).

    Mathematically applicable: counts and areas add up; area-weighted means of cell
    means recompose the AOI mean; extremes of cell extremes are the AOI extremes;
    pooling all cells' samples reproduces the AOI percentiles. Averaging cell
    percentiles does **not** give AOI percentiles; the size of that error is
    reported as an illustration only.
    """
    agg = result.aggregates
    checks: list[dict] = []
    sc = aoi_summary["sample_counts"]
    totals = result.totals
    for name, ours, theirs in (
        ("aoi_samples", totals["n_samples"], sc["aoi_samples"]),
        ("void_samples", totals["n_excluded_void"], sc["void_samples"]),
        ("water_samples", int(agg.counts["water"].sum()), sc["water_samples"]),
        ("analysis_samples", totals["n_analysis"], sc["analysis_samples"]),
        ("derivative_undefined_in_analysis", totals["n_derivative_missing"], sc["derivative_undefined_in_analysis"]),
    ):
        _check(checks, f"{label}:{name}", ours == theirs, f"cells {ours} vs AOI {theirs}")
    aoi_area = aoi_summary["aoi"]["area_km2"]
    _check(checks, f"{label}:aoi_area_km2", _rel_close(totals["sampled_area_km2"], aoi_area, REL_TOL_AREA),
           f"cells {totals['sampled_area_km2']:.9f} vs AOI {aoi_area:.9f} km2")

    measurements = {}
    for meas, stats in TERRAIN_STATISTICS.items():
        ref = aoi_summary["measurements"][meas]
        r = agg.measurements[meas]
        area = r["valid_area_m2"]
        ok = r["count_valid"] > 0
        mean = float(np.dot(area[ok], r["mean"][ok]) / area[ok].sum()) if ok.any() else None
        row = {
            "count_valid": [int(r["count_valid"].sum()), ref["count_valid"]],
            "valid_area_km2": [float(area.sum()) / 1e6, ref["valid_area_km2"]],
            "mean_from_area_weighted_cell_means": [mean, ref["mean"]],
        }
        _check(checks, f"{label}:{meas}:count_valid", row["count_valid"][0] == row["count_valid"][1],
               f"{row['count_valid'][0]} vs {row['count_valid'][1]}")
        _check(checks, f"{label}:{meas}:valid_area",
               _rel_close(row["valid_area_km2"][0], row["valid_area_km2"][1], REL_TOL_AREA),
               f"{row['valid_area_km2'][0]:.9f} vs {row['valid_area_km2'][1]:.9f} km2")
        if mean is not None:
            _check(checks, f"{label}:{meas}:mean", _rel_close(mean, ref["mean"], REL_TOL_MEAN),
                   f"{mean:.10g} vs {ref['mean']:.10g} (diff {mean - ref['mean']:.3g})")
        for stat, fn in (("min", np.nanmin), ("max", np.nanmax)):
            if stat in stats and ok.any():
                v = float(fn(r[stat][ok]))
                row[f"{stat}_of_cell_{stat}s"] = [v, ref[stat]]
                _check(checks, f"{label}:{meas}:{stat}", v == ref[stat], f"{v} vs {ref[stat]}")
        pcts = [s for s in stats if s.startswith("p")]
        if pcts:
            row.update(_percentile_reconciliation(result, meas, pcts, ref, checks, label))
        measurements[meas] = row
    return {"reference": label, "all_passed": all(c["passed"] for c in checks), "checks": checks,
            "measurements": measurements}


def _percentile_reconciliation(result, meas, pcts, ref, checks, label) -> dict:
    """Pool every cell's samples (in grouping order) and recompute the AOI percentiles."""
    agg = result.aggregates
    samples = agg.sample_order  # all samples, grouped by cell
    values = result.samples["values"][meas][samples]
    area = result.samples["area_m2"][samples]
    include = result.samples["include"][samples]
    qs = tuple(float(p[1:]) for p in pcts)
    pooled = summarize(values[:, None], row_weights=area, mask=include[:, None], percentiles=qs)
    r = agg.measurements[meas]
    ok = r["count_valid"] > 0
    out = {}
    for p, q in zip(pcts, qs):
        key = f"p{q:g}"
        _check(checks, f"{label}:{meas}:{p}_pooled", _rel_close(pooled[key], ref[key], 1e-6),
               f"pooled cell samples {pooled[key]:.9g} vs AOI {ref[key]:.9g}")
        naive = float(np.dot(r["valid_area_m2"][ok], r[p][ok]) / r["valid_area_m2"][ok].sum())
        out[f"{p}_from_pooled_cell_samples"] = [pooled[key], ref[key]]
        out[f"{p}_naive_area_weighted_mean_of_cell_{p}_NOT_VALID"] = naive
    return out


# --------------------------------------------------------------------------- run summary


def build_run_summary(result: H3TerrainResult, aoi_summary: dict, reconciliations: list[dict], outputs: dict) -> dict:
    g = aoi_summary["granule"]
    grid = g["grid"]
    res = result.resolution
    aoi = aoi_summary["aoi"]
    return {
        "schema": SCHEMA,
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
        "software": {**_software_versions(), **h3grid.h3_versions()},
        "source": {
            "collection": SOURCE_COLLECTION,
            "product": g["product"],
            "granules": [{"zip_file": g["zip_file"], "zip_sha256": g["zip_sha256"], "tile_id": g["tile_id"],
                          "all_granule_checks_passed": g["all_checks_passed"]}],
            "horizontal_crs": g["horizontal_crs"],
            "vertical_datum": g["vertical_datum"],
            "native_sampling": {
                "resolution_arcsec": grid["resolution_arcsec"],
                "registration": grid["registration"],
                "aoi_dx_m_range": aoi["dx_m_range"],
                "aoi_dy_m_range": aoi["dy_m_range"],
            },
        },
        "aoi": {
            "name": aoi["name"],
            "requested_bbox_deg": aoi["requested_bbox_deg"],
            "selection_rule": aoi["selection_rule"],
            "sample_centre_extent_deg": aoi["sample_centre_extent_deg"],
            "analysed_pixel_footprint_deg": result.footprint.as_dict(),
            "footprint_note": (
                "union of the analysed pixels (sample centre +- half a sample); the half-open selection "
                "puts it half a sample south and west of the requested bbox"
            ),
            "shape": aoi["shape"],
            "area_km2": aoi["area_km2"],
        },
        "h3": {
            "resolution": res,
            "library": "h3-py v4 (Uber H3)",
            "api_calls": "latlng_to_cell(lat, lng, res), cell_to_boundary, cell_to_latlng, cell_area, grid_disk",
            "cell_id_format": "15-character lower-case hexadecimal H3 index string",
            "global_cell_count_at_resolution": h3.get_num_cells(res),
            "average_hexagon_area_km2": h3.average_hexagon_area(res, unit="km^2"),
            "average_hexagon_edge_length_km": h3.average_hexagon_edge_length(res, unit="km"),
            "planned_global_baseline": {
                "resolution": 6,
                "global_cells_including_ocean": h3.get_num_cells(6),
                "land_cells": "about 4.09 million: a planning estimate, not computed or verified here",
            },
        },
        "methodology": {
            "order_of_operations": (
                "3x3 derivatives are computed on the native grid with a one-sample halo (full neighbouring "
                "context) before assignment; cells never recompute derivatives from cropped samples"
            ),
            "assignment": (
                "pixel-centre: each sample goes wholly to the H3 cell containing its centre "
                "(latlng_to_cell takes latitude first; GeoJSON outputs are longitude first). Boundary pixels "
                "are not split, so each cell's sampled area differs from its exact overlap by up to about "
                "one pixel row along the cell edge"
            ),
            "hierarchy": "each resolution is assigned directly from the samples (H3 cells are not exactly nested)",
            "derivative_window": aoi_summary["parameters"]["derivative_window"],
            "terrain_baseline": (
                f"native {grid['resolution_arcsec']:g}-arc-second samples; 3x3 window spans about "
                f"{2 * aoi['dx_m_range'][0]:.1f} m east-west x {2 * aoi['dy_m_range'][0]:.1f} m north-south here"
            ),
            "statistics_per_cell": {m: list(s) for m, s in TERRAIN_STATISTICS.items()},
            "measurement_definitions": MEASUREMENT_DEFINITIONS,
            "weighting": aoi_summary["parameters"]["statistic_weighting"],
            "percentile_method": (
                "weighted inverted CDF over each cell's own samples (stats.summarize); cell percentiles are "
                "never derived from tile/AOI percentiles"
            ),
            "exclusions": {
                "exclude_water": aoi_summary["parameters"]["exclude_water"],
                "water_mask_source": aoi_summary["parameters"]["water_mask_source"],
                "nodata_rule": aoi_summary["parameters"]["nodata_rule"],
            },
            "coverage": {
                "cell_area_km2": "WGS 84 ellipsoidal area of the full H3 cell polygon",
                "h3_spherical_cell_area_km2": h3grid.H3_SPHERE_NOTE,
                "overlap_area_km2": "exact area of (cell polygon intersect analysed pixel footprint)",
                "sampled_area_km2": "sum of the areas of the pixels whose centres fall in the cell (pixel-centre)",
                "coverage_fraction_exact_overlap": "overlap_area / cell_area",
                "coverage_fraction_pixel_centre": "sampled_area / cell_area (pixel-centre approximation)",
                "valid_coverage_fraction": "area of samples with valid derivatives / cell_area",
                "coverage_status": "complete if the footprint covers the whole polygon, else partial",
                "partial_cells": (
                    "statistics describe only the observed part of the cell and are not extrapolated "
                    "to the whole hexagon"
                ),
                "geometry_model": (
                    "cell_to_boundary vertices, edges straight in the WGS 84 cylindrical equal-area plane; "
                    "H3's own edges are great-circle arcs, which differ by well under a metre at these sizes"
                ),
            },
            "quality_flags": {
                "partial_coverage": "cell only partly inside the analysed footprint",
                "water_excluded": "SWB water samples were excluded",
                "void_samples": "cell holds samples with missing elevation",
                "missing_derivatives": "analysis samples whose 3x3 window crosses the granule edge or a void",
                "no_valid_derivatives": "no slope/roughness statistics available",
                **{f"{k}_below_quantisation_floor": f"{k} < {v:g} (1 m height-rounding floor; "
                   "scientific_validation.md section 5.1)" for k, v in QUANTISATION_FLOORS.items()},
            },
            "output_order": "cells sorted by ascending 64-bit H3 index (the same as sorting the hex strings)",
        },
        "results": result.totals,
        "conservation_checks": result.checks,
        "reconciliation": reconciliations,
        "all_checks_passed": result.all_checks_passed and all(r["all_passed"] for r in reconciliations),
        "quality_limitations": QUALITY_LIMITATIONS,
        "outputs": outputs,
    }


QUALITY_LIMITATIONS = [
    "Pixel-centre assignment: boundary pixels are assigned whole; see coverage_fraction_pixel_centre vs "
    "coverage_fraction_exact_overlap for the per-cell effect.",
    "Partial cells (coverage_status = partial) describe only the observed part of the hexagon; their "
    "statistics are not representative of the whole cell and should not be ranked against complete cells "
    "without accounting for coverage.",
    "1 m elevation quantisation: slopes below about 0.5 deg and detrended roughness below about 0.3 m are "
    "dominated by rounding (scientific_validation.md section 5.1).",
    "TRI and detrended roughness depend on the 1-arc-second sample spacing, pixel aspect (about 19.3 m x "
    "30.9 m here) and latitude; they are not comparable across latitudes or with lunar/Martian DEMs without "
    "a common metric baseline (scientific_validation.md section 5.2).",
    "Single granule: derivatives on a granule's south and west edge rows are undefined without the "
    "neighbouring granule, and cells crossing granule edges would be incomplete.",
    "Water mask: SWB flags no water in some river channels (for example the Red Deer River), which are "
    "then analysed as land.",
    "Absolute accuracy of NASADEM heights is not validated here (no ground truth).",
]
