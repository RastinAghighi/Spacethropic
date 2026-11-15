"""Single-granule terrain analysis: AOI selection, derivatives, masking and statistics.

``analyze_granule`` is the unit of work for scaling up: it returns a
JSON-serialisable summary and the per-sample layers for one granule/AOI.
Derivatives are computed in row strips (with a one-row halo), so memory stays
at a few hundred MB even for a full 3601 x 3601 tile. Later multi-granule or
H3 aggregation can reuse the same layers, row weights and half-open ownership rule.
"""

from __future__ import annotations

import datetime as _dt
import importlib.util
import platform
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import __version__, terrain
from .nasadem import BBox, GeoGrid, NasademGranule, rasterio_crosscheck
from .stats import DEFAULT_PERCENTILES, summarize

SCHEMA = "spacethropic.terrain_summary/v1"
STRIP_ROWS = 512


@dataclass(frozen=True)
class AnalysisConfig:
    bbox: BBox | None = None  # None -> the tile's own half-open 1 x 1 degree extent
    name: str | None = None
    exclude_water: bool = True
    percentiles: tuple[float, ...] = DEFAULT_PERCENTILES
    rasterio_crosscheck: bool | None = None  # None = run only if rasterio is installed
    hillshade_z_factor: float = 3.0  # visualisation only; not used for any measurement


@dataclass
class TerrainLayers:
    """Per-sample float32 arrays for the AOI (rows north -> south), for plotting/aggregation."""

    grid: GeoGrid
    elevation_m: np.ndarray
    slope_deg: np.ndarray
    tri_m: np.ndarray
    roughness_m: np.ndarray
    hillshade: np.ndarray
    water: np.ndarray
    analysis_mask: np.ndarray  # True = sample contributes to the statistics
    cell_area_m2: np.ndarray  # one value per row


MEASUREMENT_DEFINITIONS = {
    "elevation": {
        "units": "m",
        "definition": "NASADEM_HGT height above the EGM96 geoid",
    },
    "slope": {
        "units": "degrees",
        "definition": (
            "arctan(|grad z|); Horn (1981) 3x3 gradient using WGS 84 ground distances "
            "(per-row east-west spacing N*cos(lat)*dlon, north-south spacing M*dlat)"
        ),
    },
    "roughness_tri": {
        "units": "m",
        "definition": (
            "Terrain Ruggedness Index (Riley et al., 1999): sqrt(sum of squared elevation "
            "differences between a sample and its 8 neighbours); sensitive to slope and grid spacing"
        ),
    },
    "roughness_detrended": {
        "units": "m",
        "definition": (
            "RMS residual of the 3x3 window about its least-squares plane; zero on uniform "
            "slopes, so it isolates small-scale relief"
        ),
    },
}


def _software_versions() -> dict:
    return {
        "spacethropic": __version__,
        "python": platform.python_version(),
        "numpy": np.__version__,
        "reader": "native numpy reader of NASADEM .hgt/.num/.swb streamed from the ZIP",
    }


def _expand(sl: slice, n: int) -> slice:
    return slice(max(sl.start - 1, 0), min(sl.stop + 1, n))


def derive_layers(granule: NasademGranule, rows: slice, cols: slice, z_factor: float, strip_rows: int = STRIP_ROWS):
    """Elevation, slope, TRI, detrended roughness and hillshade (float32) for an AOI window.

    A one-sample buffer is read around the AOI so 3x3 derivatives are defined up
    to the AOI edge; they are NaN only where the AOI touches the granule's outer edge.
    """
    brows, bcols = _expand(rows, granule.grid.nrows), _expand(cols, granule.grid.ncols)
    zb = granule.read_elevation(brows, bcols, dtype=np.float32)
    gb = granule.grid.subgrid(brows, bcols)
    dx, dy = gb.dx_m(), gb.dy_m()
    r_off = rows.start - brows.start
    c_in = slice(cols.start - bcols.start, cols.stop - bcols.start)
    nr, nc = rows.stop - rows.start, cols.stop - cols.start
    out = {k: np.full((nr, nc), np.nan, dtype=np.float32) for k in ("slope", "tri", "rough", "shade")}
    for a in range(0, nr, strip_rows):
        b = min(a + strip_rows, nr)
        s0, s1 = max(r_off + a - 1, 0), min(r_off + b + 1, zb.shape[0])  # strip plus halo
        strip = zb[s0:s1].astype(np.float64)
        if min(strip.shape) < 3:
            continue  # no complete 3x3 window exists
        inner = (slice(r_off + a - s0, r_off + b - s0), c_in)
        dzdx, dzdy = terrain.horn_gradient(strip, dx[s0:s1], dy[s0:s1])
        out["slope"][a:b] = terrain.slope_from_gradient(dzdx, dzdy)[inner]
        out["shade"][a:b] = terrain.hillshade(dzdx, dzdy, z_factor=z_factor)[inner]
        del dzdx, dzdy
        out["tri"][a:b] = terrain.terrain_ruggedness_index(strip)[inner]
        out["rough"][a:b] = terrain.detrended_roughness(strip)[inner]
    z = zb[r_off : r_off + nr, c_in].copy()
    return z, out


def analyze_granule(zip_path: str | Path, config: AnalysisConfig = AnalysisConfig()) -> tuple[dict, TerrainLayers]:
    """Validate a NASADEM_HGT granule and measure terrain inside an area of interest."""
    zip_path = Path(zip_path)
    with NasademGranule(zip_path) as granule:
        metadata = granule.inspect()
        run_xcheck = (
            importlib.util.find_spec("rasterio") is not None
            if config.rasterio_crosscheck is None
            else config.rasterio_crosscheck
        )
        xcheck = rasterio_crosscheck(granule) if run_xcheck else {"status": "skipped"}

        tile_box = granule.tile.owned_bbox()
        bbox = config.bbox or tile_box
        if not tile_box.contains(bbox):
            raise ValueError(
                f"AOI {bbox.as_dict()} extends beyond granule {granule.tile.name} "
                f"{tile_box.as_dict()}; multi-granule AOIs are not supported yet"
            )
        window = granule.grid.window(bbox)
        if window is None:
            raise ValueError(f"AOI {bbox.as_dict()} contains no sample centres")
        rows, cols = window
        z, d = derive_layers(granule, rows, cols, config.hillshade_z_factor)
        water, water_source = granule.water_mask(rows, cols)
        grid = granule.grid.subgrid(rows, cols)
        num_present = granule.members.num is not None

    valid = np.isfinite(z)
    mask = valid & ~water if config.exclude_water else valid
    area = grid.cell_area_m2()  # per row

    measurements = {}
    for key, layer in (("elevation", z), ("slope", d["slope"]), ("roughness_tri", d["tri"]),
                       ("roughness_detrended", d["rough"])):
        stats = summarize(layer, row_weights=area, mask=mask, percentiles=config.percentiles)
        stats["valid_area_km2"] = stats.pop("weight_sum") / 1e6
        measurements[key] = {**MEASUREMENT_DEFINITIONS[key], **stats}

    dx, dy = grid.dx_m(), grid.dy_m()
    n_water = int(np.count_nonzero(water))
    summary = {
        "schema": SCHEMA,
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
        "source_file": zip_path.name,
        "software": _software_versions(),
        "granule": metadata,
        "rasterio_crosscheck": xcheck,
        "aoi": {
            "name": config.name or ("tile" if config.bbox is None else "aoi"),
            "requested_bbox_deg": bbox.as_dict(),
            "selection_rule": "samples with south <= lat < north and west <= lon < east (half-open)",
            "sample_centre_extent_deg": grid.sample_centre_bounds().as_dict(),
            "row_range": [rows.start, rows.stop],
            "col_range": [cols.start, cols.stop],
            "shape": list(z.shape),
            "area_km2": float(area.sum() * grid.ncols / 1e6),
            "dx_m_range": [float(dx.min()), float(dx.max())],
            "dy_m_range": [float(dy.min()), float(dy.max())],
        },
        "parameters": {
            "horizontal_crs": metadata["horizontal_crs"],
            "vertical_datum": metadata["vertical_datum"],
            "ellipsoid_for_distances": "WGS 84 (a = 6378137 m, 1/f = 298.257223563)",
            "nodata_rule": "elevation == -32768 -> missing; 3x3 derivatives missing if any window sample is missing",
            "exclude_water": config.exclude_water,
            "water_mask_source": water_source,
            "statistic_weighting": "cell ground area (WGS 84), so statistics describe surface area rather than sample count",
            "percentile_method": "weighted inverted CDF",
            "percentiles": list(config.percentiles),
            "derivative_window": "3 x 3 samples",
            "visualisation_hillshade_z_factor": config.hillshade_z_factor,
        },
        "sample_counts": {
            "aoi_samples": int(z.size),
            "void_samples": int(np.count_nonzero(~valid)),
            "water_samples": n_water,
            "water_fraction": n_water / z.size,
            "num_layer_present": num_present,
            "analysis_samples": int(np.count_nonzero(mask)),
            "derivative_undefined_in_analysis": int(np.count_nonzero(mask & ~np.isfinite(d["slope"]))),
            "derivative_undefined_reason": "AOI touches the granule edge, or a 3x3 window holds a void sample",
        },
        "measurements": measurements,
    }
    layers = TerrainLayers(
        grid=grid,
        elevation_m=z,
        slope_deg=d["slope"],
        tri_m=d["tri"],
        roughness_m=d["rough"],
        hillshade=d["shade"],
        water=water,
        analysis_mask=mask,
        cell_area_m2=area,
    )
    return summary, layers
