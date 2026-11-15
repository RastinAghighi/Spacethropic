"""Spacethropic small-region H3 r8 land-cover aggregation prototype.

Purposefully independent from the legacy global mask. No network or Git operations.
This exact pixel-polygon intersection algorithm is for small regions, NOT a global run.
"""
from __future__ import annotations

import argparse
from collections import defaultdict, Counter
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform

import numpy as np
import rasterio
from rasterio.enums import MaskFlags
from rasterio.windows import from_bounds, Window
import shapely
from shapely.geometry import Polygon
from pyproj import CRS, Transformer

# Source-specific *labels*. Ocean/inland water and permanent/seasonal ice
# cannot be inferred from either source's single-date categorical bands.
CLASS_MAPS = {
    "dynamic_world": {
        0: "water_unspecified", 1: "trees", 2: "grass",
        3: "flooded_vegetation", 4: "cropland", 5: "shrub_scrub",
        6: "built", 7: "bare", 8: "snow_ice_unspecified",
    },
    "esri_io": {
        1: "water_unspecified", 2: "trees", 4: "flooded_vegetation",
        5: "cropland", 7: "built", 8: "bare",
        9: "snow_ice_unspecified", 10: "unknown", 11: "rangeland",
    },
}
ALL_CLASSES = (
    "water_unspecified", "trees", "grass", "shrub_scrub", "rangeland",
    "flooded_vegetation", "cropland", "built", "bare",
    "snow_ice_unspecified", "unknown",
)
# These are conservative PRE-FILTER examples, not calibrated scientific claims.
MISSIONS = {
    "mars_dry": ("water_unspecified", "trees", "cropland", "built"),
    "moon_dry": ("water_unspecified", "trees", "cropland", "built"),
    "polar_analog": ("trees", "cropland", "built"),
    "volcanic_analog": ("water_unspecified", "built"),
    "impact_crater": ("built",),
}


def _laea_transformer(source_crs, latitude: float, longitude: float):
    """Local equal-area projection for reliable small-cell area fractions."""
    laea = CRS.from_proj4(
        f"+proj=laea +lat_0={latitude:.12f} +lon_0={longitude:.12f} "
        "+datum=WGS84 +units=m +no_defs"
    )
    return Transformer.from_crs(source_crs, laea, always_xy=True).transform


def _reproject(geom, fn):
    """Vertex-wise reprojection with a pyproj ``transform(x, y)`` function."""
    return shapely.transform(geom, lambda xy: np.column_stack(fn(xy[:, 0], xy[:, 1])))


def ring_cells(latitude: float, longitude: float, ring: int, resolution: int = 8) -> list[str]:
    """The H3 cell holding (lat, lon) plus ``ring`` rings of neighbours, sorted.

    ring 0 -> 1 cell, ring 1 -> 7 cells (away from pentagons). Latitude comes first:
    H3 silently wraps swapped arguments into a valid but wrong cell.
    """
    import h3
    if not 0 <= ring <= 5:
        raise ValueError("Prototype requires ring between 0 and 5")
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("Latitude must be within +-90 and longitude within +-180")
    return sorted(h3.grid_disk(h3.latlng_to_cell(latitude, longitude, resolution), ring))


def check_categorical_raster(src, scheme: str, band: int = 1,
                             nodata_override: float | None = None) -> None:
    """Refuse rasters that would silently turn missing data into observed classes.

    Earth Engine GeoTIFF exports write masked pixels as 0 unless a no-data value is
    set. For Dynamic World, 0 is ``water``, so an untagged export would report
    cloud-masked or out-of-swath pixels as observed water. Such a raster must
    declare a no-data value / mask, or the caller must pass one explicitly.
    """
    if scheme not in CLASS_MAPS:
        raise ValueError(f"Unknown raster class scheme: {scheme}")
    if not 1 <= band <= src.count:
        raise ValueError(f"Raster has {src.count} band(s); band {band} requested")
    if not np.issubdtype(np.dtype(src.dtypes[band - 1]), np.integer):
        raise ValueError(f"Categorical labels must be an integer band, got {src.dtypes[band - 1]} "
                         "(RGB renders and probability bands are not class codes)")
    declares_mask = MaskFlags.all_valid not in src.mask_flag_enums[band - 1]
    zero_is_class = CLASS_MAPS[scheme].get(0, "unknown") != "unknown"
    if zero_is_class and not declares_mask and nodata_override is None:
        raise ValueError(
            f"Raster declares no no-data value or mask, but code 0 is a real {scheme} class "
            f"({CLASS_MAPS[scheme][0]}). Re-export with a no-data value (e.g. 255) or pass "
            "--nodata explicitly; otherwise masked pixels would be counted as observed.")


def cell_polygon(cell: str) -> Polygon:
    # Import here so core raster/decision functions can be tested separately.
    import h3
    coords = h3.cell_to_boundary(cell)  # (lat, lon) pairs in h3-py v4
    longitudes = [lon for _, lon in coords]
    if max(longitudes) - min(longitudes) > 180:
        raise ValueError("Cell crosses antimeridian: use split-tile production path")
    return Polygon([(lon, lat) for lat, lon in coords])


def aggregate_polygon(src, geo_polygon: Polygon, latitude: float,
                      longitude: float, scheme: str,
                      nodata: float | None = None) -> dict[str, float]:
    """Exact overlay of a small polygon with categorical raster pixel footprints.

    Per-pixel intersections are measured in a local equal-area CRS. Missing
    raster coverage / nodata / unmapped labels count toward the WHOLE-cell
    unknown percentage, never silently disappear from the denominator.
    ``nodata`` is an extra code treated as missing, on top of the raster's own
    no-data value and mask.
    """
    if src.crs is None:
        raise ValueError("Raster CRS required")
    if scheme not in CLASS_MAPS:
        raise ValueError(f"Unknown raster class scheme: {scheme}")
    if geo_polygon.is_empty or not geo_polygon.is_valid:
        raise ValueError("Valid nonempty cell polygon required")
    longitudes = [p[0] for p in geo_polygon.exterior.coords]
    if max(longitudes) - min(longitudes) > 180:
        raise ValueError("Antimeridian-spanning polygon requires tile splitting")
    to_src = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True).transform
    to_area = _laea_transformer(src.crs, latitude, longitude)
    polygon_in_src = _reproject(geo_polygon, to_src)
    poly_area = _reproject(polygon_in_src, to_area).area
    if poly_area <= 0:
        raise ValueError("Invalid zero-area polygon")
    areas = defaultdict(float)
    try:
        win = from_bounds(*polygon_in_src.bounds, transform=src.transform)
    except Exception as exc:
        raise ValueError("Unsupported raster transform/window") from exc
    c0 = max(0, math.floor(win.col_off))
    c1 = min(src.width, math.ceil(win.col_off + win.width))
    r0 = max(0, math.floor(win.row_off))
    r1 = min(src.height, math.ceil(win.row_off + win.height))
    if c1 > c0 and r1 > r0:
        data = src.read(1, window=Window(c0, r0, c1-c0, r1-r0), masked=True)
        labels = CLASS_MAPS[scheme]
        for row in range(r0, r1):
            for col in range(c0, c1):
                value = data[row-r0, col-c0]
                corners = [src.transform @ (col, row),
                           src.transform @ (col+1, row),
                           src.transform @ (col+1, row+1),
                           src.transform @ (col, row+1)]
                pixel = Polygon(corners)
                if not pixel.intersects(polygon_in_src):
                    continue
                overlap = pixel.intersection(polygon_in_src)
                if overlap.is_empty or overlap.area == 0:
                    continue
                fraction_area = _reproject(overlap, to_area).area
                if fraction_area <= 0:
                    continue
                missing = (getattr(value, "mask", False)
                           or (nodata is not None and value == nodata))
                label = "unknown" if missing else labels.get(int(value), "unknown")
                areas[label] += fraction_area
    # Raster outside footprint is also unknown; tiny numerical discrepancies
    # are absorbed by unknown rather than renormalizing observed classes.
    measured = sum(areas.values())
    if measured > poly_area * (1 + 1e-7):
        raise ValueError("Overcounted overlapping raster areas")
    areas["unknown"] += max(0.0, poly_area - measured)
    result = {name: 100.0 * areas.get(name, 0.0) / poly_area
              for name in ALL_CLASSES}
    return result


def decision(percentages: dict[str, float], mission: str,
             threshold: float = 80.0,
             min_observed: float = 80.0) -> tuple[str, str]:
    """Ternary decision with conservative bounds on missing area."""
    if mission not in MISSIONS:
        raise ValueError(f"Unknown mission {mission}")
    if not 0 < threshold <= 100 or not 0 <= min_observed <= 100:
        raise ValueError("Thresholds must be percentages")
    unknown = percentages.get("unknown", 0.0)
    observed = 100.0 - unknown
    excluded = sum(percentages.get(c, 0.0) for c in MISSIONS[mission])
    if observed + 1e-7 < min_observed:
        return "review", "insufficient_observed_area"
    if excluded + 1e-7 >= threshold:
        return "excluded", "mission_exclusion_fraction_at_threshold"
    if excluded + unknown + 1e-7 >= threshold:
        return "review", "uncertainty_could_change_exclusion"
    return "retained", "below_mission_exclusion_threshold"


PARQUET_SCHEMA_VERSION = "0.2.0"


def _iso_date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Observation dates must be ISO YYYY-MM-DD, got {text!r}") from exc


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cell_schema():
    """Explicit Arrow schema, so all-null breakdown columns stay float64 across runs."""
    import pyarrow as pa
    return pa.schema(
        [("h3_cell", pa.string()), ("resolution", pa.int8()),
         ("mission", pa.string()), ("decision", pa.string()), ("reason", pa.string()),
         ("cell_area_km2", pa.float64()), ("source_scheme", pa.string()),
         ("source_asset_id", pa.string()), ("source_version", pa.string()),
         ("observation_start", pa.date32()), ("observation_end", pa.date32()),
         ("threshold_pct", pa.float64()), ("min_observed_pct", pa.float64()),
         ("ocean_pct", pa.float64()), ("inland_water_pct", pa.float64()),
         ("permanent_ice_pct", pa.float64()), ("seasonal_snow_pct", pa.float64())]
        + [(f"pct_{c}", pa.float64()) for c in ALL_CLASSES])


PARTITION_COLUMNS = ("mission", "decision")


def write_partitioned(records: list[dict], output: Path) -> list[dict]:
    """Write hive-partitioned Parquet, cells/mission=<m>/decision=<d>/part-0.parquet.

    Same layout as ``pyarrow.dataset.write_dataset(..., flavor="hive")`` (partition
    columns live in the directory names, not in the files), but written file by
    file with ``pyarrow.parquet``: some Windows Application Control policies block
    pyarrow's ``_dataset_parquet`` DLL, which the dataset writer needs.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq
    file_schema = pa.schema([f for f in cell_schema() if f.name not in PARTITION_COLUMNS])
    groups = defaultdict(list)
    for r in records:
        groups[(r["mission"], r["decision"])].append(
            {k: v for k, v in r.items() if k not in PARTITION_COLUMNS})
    files = []
    for (mission, status), rows in sorted(groups.items()):
        rel = f"cells/mission={mission}/decision={status}/part-0.parquet"
        path = output / rel
        path.parent.mkdir(parents=True, exist_ok=False)
        pq.write_table(pa.Table.from_pylist(rows, schema=file_schema), path)
        files.append(dict(path=rel, mission=mission, decision=status,
                          rows=len(rows), sha256=_sha256(path)))
    return files


def read_cells(output: Path):
    """All cell rows of a run as one Arrow table, partition columns restored.

    Reads the files listed in the manifest one by one, so it works where
    ``pyarrow.dataset`` is unavailable. Elsewhere, any hive-aware reader
    (pyarrow.dataset, DuckDB, pandas) can read ``cells/`` directly.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq
    output = Path(output)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    tables = []
    for f in manifest["parquet_files"]:
        t = pq.read_table(output / f["path"])
        for col in PARTITION_COLUMNS:
            t = t.append_column(col, pa.array([f[col]] * t.num_rows, pa.string()))
        tables.append(t)
    return pa.concat_tables(tables)


def _software() -> dict:
    import h3
    import pyarrow as pa
    import pyproj
    return dict(python=platform.python_version(), h3=h3.__version__,
                rasterio=rasterio.__version__, gdal=rasterio.__gdal_version__,
                shapely=shapely.__version__, pyproj=pyproj.__version__,
                pyarrow=pa.__version__, numpy=np.__version__)


def run(args) -> dict:
    import h3
    import pyarrow as pa
    # Validate everything before touching the output path, so a bad argument or
    # unusable raster never leaves an empty directory that blocks a rerun.
    if not args.source_asset_id or not args.source_version:
        raise ValueError("Source asset ID and version required")
    obs_start, obs_end = _iso_date(args.observation_start), _iso_date(args.observation_end)
    if obs_start > obs_end:
        raise ValueError("Observation dates out of order")
    decision({"unknown": 0.0}, args.mission, args.threshold, args.min_observed)  # validates
    cell_ids = ring_cells(args.lat, args.lon, args.ring)
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite: {output}")
    raster_path = Path(args.raster).resolve()

    records = []
    with rasterio.open(raster_path) as src:
        check_categorical_raster(src, args.scheme, 1, args.nodata)
        for cid in cell_ids:
            lat, lon = h3.cell_to_latlng(cid)
            geometry = cell_polygon(cid)
            pcts = aggregate_polygon(src, geometry, lat, lon, args.scheme, args.nodata)
            status, reason = decision(pcts, args.mission, args.threshold,
                                      args.min_observed)
            row = dict(h3_cell=cid, resolution=8, mission=args.mission,
                       decision=status, reason=reason,
                       # H3's spherical area (authalic sphere), for reference;
                       # percentages use the WGS 84 equal-area polygon area.
                       cell_area_km2=h3.cell_area(cid, unit="km^2"),
                       source_scheme=args.scheme,
                       source_asset_id=args.source_asset_id,
                       source_version=args.source_version,
                       observation_start=obs_start, observation_end=obs_end,
                       threshold_pct=args.threshold, min_observed_pct=args.min_observed,
                       # Explicitly unresolved; never pretend water=oceans or
                       # snow=permanent ice from a single-class raster.
                       ocean_pct=None, inland_water_pct=None,
                       permanent_ice_pct=None, seasonal_snow_pct=None,
                       **{f"pct_{c}": round(pcts[c], 6) for c in ALL_CLASSES})
            records.append(row)
        raster_metadata = dict(path=str(raster_path), sha256=_sha256(raster_path),
                               size_bytes=raster_path.stat().st_size,
                               band=1, dtype=src.dtypes[0],
                               crs=str(src.crs), resolution=list(src.res),
                               width=src.width, height=src.height,
                               bounds=list(src.bounds),
                               nodata=src.nodata, nodata_override=args.nodata)

    pa.Table.from_pylist(records, schema=cell_schema())  # schema check before any write
    output.mkdir(parents=True, exist_ok=False)
    parquet_files = write_partitioned(records, output)
    counts = dict(Counter(r["decision"] for r in records))
    manifest = dict(
        program="spacethropic_r8_regional_pilot", schema_version=PARQUET_SCHEMA_VERSION,
        created_utc=datetime.now(timezone.utc).isoformat(),
        h3_resolution=8, center_lat=args.lat, center_lon=args.lon, ring=args.ring,
        cells_count=len(records), cells=cell_ids, decision_counts=counts,
        parquet_layout="hive: cells/mission=<m>/decision=<d>/part-0.parquet",
        parquet_files=parquet_files,
        mission=args.mission, mission_exclusion_classes=list(MISSIONS[args.mission]),
        threshold_pct=args.threshold, min_observed_pct=args.min_observed,
        threshold_note="configurable screening values; not calibrated",
        raster=raster_metadata, source_scheme=args.scheme,
        class_map={str(k): v for k, v in CLASS_MAPS[args.scheme].items()},
        source_asset_id=args.source_asset_id,
        source_version=args.source_version,
        observation_start=obs_start.isoformat(),
        observation_end=obs_end.isoformat(),
        software=_software(),
        area_model="exact pixel/cell polygon overlay; areas in a cell-centred "
                   "WGS 84 Lambert azimuthal equal-area projection",
        limits=["small-regional overlay only",
                "water cannot be split into ocean/inland from this input",
                "snow and permanent ice cannot be distinguished from this input",
                "categorical labels lack pixel confidence/time-series",
                "dateline-crossing polygons unsupported in prototype",
                "global-scale batching and coast refinement not implemented"],
    )
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(dict(output=str(output), counts=counts), indent=2))
    return manifest


def parse(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--raster", required=True, help="Existing categorical GeoTIFF (band 1 = class codes)")
    p.add_argument("--lat", required=True, type=float)
    p.add_argument("--lon", required=True, type=float)
    p.add_argument("--ring", type=int, default=1, help="0 = one cell, 1 = seven cells")
    p.add_argument("--scheme", required=True, choices=sorted(CLASS_MAPS))
    p.add_argument("--mission", default="mars_dry", choices=sorted(MISSIONS))
    p.add_argument("--threshold", type=float, default=80.0)
    p.add_argument("--min-observed", type=float, default=80.0)
    p.add_argument("--nodata", type=float, default=None,
                   help="Extra code to treat as missing. Required for an untagged raster "
                        "whose scheme uses 0 as a class (Dynamic World 0 = water)")
    p.add_argument("--source-asset-id", required=True)
    p.add_argument("--source-version", required=True)
    p.add_argument("--observation-start", required=True, help="ISO date")
    p.add_argument("--observation-end", required=True, help="ISO date")
    p.add_argument("--output", required=True, help="New, nonexistent directory")
    return p.parse_args(argv)


if __name__ == "__main__":
    run(parse())
