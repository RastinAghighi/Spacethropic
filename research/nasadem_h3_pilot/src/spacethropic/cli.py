"""Command line: validate one NASADEM_HGT granule and summarise terrain in an AOI.

Example:
    spacethropic-terrain path/to/NASADEM_HGT_n51w113.zip --bbox -112.8 51.4 -112.6 51.52 --name drumheller
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from .nasadem import BBox
from .outputs import write_csv, write_json
from .pipeline import AnalysisConfig, analyze_granule


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="spacethropic-terrain", description=__doc__.split("\n\n")[0])
    p.add_argument("zip_path", type=Path, help="NASADEM_HGT granule ZIP (read in place, never extracted)")
    p.add_argument("--bbox", nargs=4, type=float, metavar=("WEST", "SOUTH", "EAST", "NORTH"),
                   help="AOI in degrees (WGS 84); default: the whole tile")
    p.add_argument("--name", help="AOI label used in outputs (default: 'tile', or 'aoi' with --bbox)")
    p.add_argument("--out-dir", type=Path, default=Path("outputs"), help="output root directory (default: outputs)")
    p.add_argument("--include-water", action="store_true", help="include SWB water samples in the statistics")
    p.add_argument("--no-plot", action="store_true", help="skip the PNG overview")
    p.add_argument("--rasterio-crosscheck", choices=("auto", "yes", "no"), default="auto",
                   help="compare against GDAL/rasterio (auto = only if rasterio is installed)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    bbox = BBox(*args.bbox) if args.bbox else None
    name = args.name or ("tile" if bbox is None else "aoi")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        raise SystemExit(f"--name may only contain letters, digits, '_', '-', '.': {name!r}")
    config = AnalysisConfig(
        bbox=bbox,
        name=name,
        exclude_water=not args.include_water,
        rasterio_crosscheck={"auto": None, "yes": True, "no": False}[args.rasterio_crosscheck],
    )
    summary, layers = analyze_granule(args.zip_path, config)

    out_dir = args.out_dir / f"{summary['granule']['tile_id']}_{name}"
    out_dir.mkdir(parents=True, exist_ok=True)
    written = [write_json(summary, out_dir / "terrain_summary.json"), write_csv(summary, out_dir / "terrain_summary.csv")]
    if not args.no_plot:
        from .viz import plot_overview

        written.append(plot_overview(layers, summary, out_dir / "terrain_overview.png"))

    g = summary["granule"]
    failed = [c["check"] for c in g["checks"] if not c["passed"]]
    print(f"granule {g['tile_id']} ({summary['source_file']}): "
          f"{'all checks passed' if not failed else 'FAILED checks: ' + ', '.join(failed)}")
    print(f"AOI '{name}': {summary['aoi']['shape'][0]} x {summary['aoi']['shape'][1]} samples, "
          f"{summary['aoi']['area_km2']:.1f} km2, analysed {summary['sample_counts']['analysis_samples']}")
    for key, m in summary["measurements"].items():
        if m["count_valid"]:
            print(f"  {key:<20} min {m['min']:9.2f}  mean {m['mean']:9.2f}  max {m['max']:9.2f}  [{m['units']}]")
        else:
            print(f"  {key:<20} no valid samples")
    for path in written:
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
