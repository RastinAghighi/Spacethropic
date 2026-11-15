"""Command line: aggregate validated NASADEM terrain layers of one AOI into H3 cells.

Example:
    python -m spacethropic.h3_cli path/to/NASADEM_HGT_n51w113.zip --bbox -112.8 51.4 -112.6 51.52 \
        --name drumheller_badlands --resolutions 6 8 \
        --reference-summary outputs/n51w113_drumheller_badlands/terrain_summary.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import h3_pipeline, h3grid
from .h3_outputs import write_cells_csv, write_cells_geojson, write_run_summary
from .nasadem import BBox
from .pipeline import AnalysisConfig, analyze_granule


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="spacethropic-h3", description=__doc__.split("\n\n")[0])
    p.add_argument("zip_path", type=Path, help="NASADEM_HGT granule ZIP (read in place, never extracted)")
    p.add_argument("--bbox", nargs=4, type=float, metavar=("WEST", "SOUTH", "EAST", "NORTH"),
                   help="AOI in degrees (WGS 84); default: the whole tile")
    p.add_argument("--name", help="AOI label used in outputs (default: 'tile', or 'aoi' with --bbox)")
    p.add_argument("--resolutions", nargs="+", type=int, default=[6], help="H3 resolutions (default: 6)")
    p.add_argument("--out-dir", type=Path, default=Path("outputs"), help="output root directory (default: outputs)")
    p.add_argument("--include-water", action="store_true", help="include SWB water samples in the statistics")
    p.add_argument("--reference-summary", type=Path,
                   help="existing terrain_summary.json of the same AOI to reconcile against")
    p.add_argument("--no-plot", action="store_true", help="skip the PNG maps")
    return p


def _reference(path: Path | None, summary: dict) -> tuple[dict | None, str]:
    """Load a stored AOI summary, and confirm it describes the same granule, AOI and masks."""
    if path is None:
        return None, "no reference summary given"
    ref = json.loads(path.read_text(encoding="utf-8"))
    same = (
        ref["granule"]["zip_sha256"] == summary["granule"]["zip_sha256"]
        and ref["aoi"]["row_range"] == summary["aoi"]["row_range"]
        and ref["aoi"]["col_range"] == summary["aoi"]["col_range"]
        and ref["parameters"]["exclude_water"] == summary["parameters"]["exclude_water"]
    )
    if not same:
        return None, f"{path} describes a different granule, AOI or water setting; not reconciled"
    return ref, f"reconciled against {path.as_posix()}"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    bbox = BBox(*args.bbox) if args.bbox else None
    name = args.name or ("tile" if bbox is None else "aoi")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        raise SystemExit(f"--name may only contain letters, digits, '_', '-', '.': {name!r}")
    resolutions = sorted(set(args.resolutions))
    for res in resolutions:
        h3grid.validate_resolution(res)

    config = AnalysisConfig(bbox=bbox, name=name, exclude_water=not args.include_water, rasterio_crosscheck=False)
    summary, layers = analyze_granule(args.zip_path, config)
    ref, ref_note = _reference(args.reference_summary, summary)

    out_dir = args.out_dir / f"{summary['granule']['tile_id']}_{name}_h3"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"granule {summary['granule']['tile_id']}: "
          f"{'all checks passed' if summary['granule']['all_checks_passed'] else 'FAILED granule checks'}; "
          f"AOI '{name}' {summary['aoi']['shape'][0]} x {summary['aoi']['shape'][1]} samples, "
          f"{summary['aoi']['area_km2']:.3f} km2; {ref_note}")
    failures = 0
    for res in resolutions:
        result = h3_pipeline.aggregate_terrain(layers, res, [summary["source_file"]])
        recon = [h3_pipeline.reconcile(result, summary, "fresh_aoi_summary")]
        if ref is not None:
            recon.append(h3_pipeline.reconcile(result, ref, "stored_aoi_summary"))
        stem = f"h3_res{res}"
        files = {"csv": f"{stem}_cells.csv", "geojson": f"{stem}_cells.geojson",
                 "run_summary": f"{stem}_run_summary.json"}
        if not args.no_plot:
            files["map_png"] = f"{stem}_mean_slope.png"
        run = h3_pipeline.build_run_summary(result, summary, recon, files)
        run["reference_summary_note"] = ref_note
        geo_meta = {
            "schema": h3_pipeline.SCHEMA,
            "h3_resolution": res,
            "source_collection": h3_pipeline.SOURCE_COLLECTION,
            "source_granules": [summary["source_file"]],
            "aoi_name": name,
            "requested_bbox_deg": summary["aoi"]["requested_bbox_deg"],
            "analysed_pixel_footprint_deg": result.footprint.as_dict(),
            "geometry": "full H3 cell polygons; partial cells' statistics describe only the observed part",
            "run_summary": files["run_summary"],
            "generated_utc": run["generated_utc"],
        }
        written = [
            write_cells_csv(result.records, out_dir / files["csv"]),
            write_cells_geojson(result, geo_meta, out_dir / files["geojson"]),
            write_run_summary(run, out_dir / files["run_summary"]),
        ]
        if not args.no_plot:
            from .h3_viz import plot_mean_slope

            written.append(plot_mean_slope(result, run, out_dir / files["map_png"]))
        t = result.totals
        ok = run["all_checks_passed"]
        failures += not ok
        print(f"res {res}: {t['n_cells']} cells ({t['n_cells_complete']} complete, {t['n_cells_partial']} partial, "
              f"{t['n_sliver_cells_without_samples']} zero-sample slivers); {t['n_samples']} samples, "
              f"{t['sampled_area_km2']:.6f} km2; checks {'all passed' if ok else 'FAILED'}")
        for path in written:
            print(f"  wrote {path}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
