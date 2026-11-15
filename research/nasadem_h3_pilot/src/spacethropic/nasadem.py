"""NASADEM_HGT V001 granule access: ZIP member discovery, grid geometry, validation, reading.

Format facts used here (NASADEM User Guide, JPL; V1 Jan 2020 and V1.3 Jan 2025,
Section 3 and Tables 1-2):

* ``.hgt`` - flat binary, **big-endian int16**, 3601 x 3601, metres relative to
  the **EGM96 geoid**; void-filled (no fill/no-data value; valid range -32767..32767).
* ``.num`` - uint8 class codes giving the source of each ``.hgt`` sample (Table 2).
* ``.swb`` - uint8 water-body mask: 0 = land, 255 = water.
* The tile name gives the **south-west** corner (``n51w113`` -> 51-52 N, 113-112 W).
  The V1 guide text says "northwest"; V1.3 corrected it to "southwest corner".
* Samples sit on integer arc-second positions (pixel-is-point), so adjacent
  1 x 1 degree quads share their edge row/column ("overlap at quad edges").

HGT files are headerless: CRS, bounds and resolution are not embedded but are
defined by the format plus the file name. The horizontal reference is WGS 84
geographic coordinates (EPSG:4326), the same CRS GDAL's SRTMHGT driver assigns.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import numpy as np

from . import geodesy

HGT_DTYPE = np.dtype(">i2")
MASK_DTYPE = np.dtype("u1")
NASADEM_SAMPLES = 3601  # rows == cols for every NASADEM_HGT quad
SRTM_VOID = -32768  # SRTM void marker; outside NASADEM's valid range, so never a real height
# Earth's land surface spans about -430 m (Dead Sea shore) to 8849 m (Everest).
PLAUSIBLE_ELEVATION_M = (-500.0, 9000.0)
SWB_LAND, SWB_WATER = 0, 255
_COORD_TOL_DEG = 1e-9  # ~0.1 mm; absorbs float error when matching bbox edges to sample centres

HORIZONTAL_CRS = "EPSG:4326 (WGS 84 geographic; latitude/longitude in degrees)"
VERTICAL_DATUM = "EGM96 geoid (EPSG:5773); heights in metres"

# NASADEM User Guide Table 2 (identical in V1 and V1.3): (first, last, category, description).
NUM_CODE_TABLE: tuple[tuple[int, int, str, str], ...] = (
    (0, 0, "water", "Water in corrected SRTM water body data"),
    (1, 23, "srtm", "SRTM 1-23 (number of SRTM scenes; max known is 23)"),
    (41, 94, "void_fill", "PRISM AW3D30 (scene count)"),
    (110, 160, "void_fill", "ASTER GDEM3 (scene count, saturated at 50)"),
    (170, 220, "void_fill", "ASTER GDEM2 (scene count, saturated at 50)"),
    (231, 231, "void_fill", "SRTMv3 from GDEM3"),
    (232, 232, "void_fill", "SRTMv2 from GDEM3"),
    (233, 233, "void_fill", "SRTMv2 from GDEM2"),
    (234, 234, "void_fill", "SRTM-with-NGA-fill from GDEM2"),
    (241, 241, "void_fill", "NED from GDEM2 (USA)"),
    (242, 242, "void_fill", "NED from GDEM3 (USA)"),
    (243, 243, "void_fill", "CDED from GDEM2 (Canada)"),
    (244, 244, "void_fill", "CDED from GDEM3 (Canada)"),
    (245, 245, "void_fill", "Alaska from GDEM2"),
    (246, 246, "void_fill", "Alaska from GDEM3"),
    (250, 250, "void_fill", "Interpolation"),
    (251, 251, "void_fill", "Quad edge averaged where two neighbouring quads disagreed"),
    (255, 255, "error", "ERROR (NUM missing)"),
)


def describe_num_code(code: int) -> tuple[str, str]:
    """Return (category, description) for a NUM value; undocumented values are flagged."""
    for lo, hi, category, description in NUM_CODE_TABLE:
        if lo <= code <= hi:
            return category, description
    return "undocumented", "Not listed in NASADEM User Guide Table 2"


# --------------------------------------------------------------------------- geometry


@dataclass(frozen=True)
class BBox:
    """Geographic bounding box in degrees (WGS 84)."""

    west: float
    south: float
    east: float
    north: float

    def __post_init__(self) -> None:
        if not (-180.0 <= self.west < self.east <= 180.0):
            raise ValueError(f"invalid longitudes: west={self.west}, east={self.east}")
        if not (-90.0 <= self.south < self.north <= 90.0):
            raise ValueError(f"invalid latitudes: south={self.south}, north={self.north}")

    def contains(self, other: "BBox", tol: float = _COORD_TOL_DEG) -> bool:
        return (
            other.west >= self.west - tol
            and other.east <= self.east + tol
            and other.south >= self.south - tol
            and other.north <= self.north + tol
        )

    def as_dict(self) -> dict:
        return {"west": self.west, "south": self.south, "east": self.east, "north": self.north}


@dataclass(frozen=True)
class TileId:
    """1 x 1 degree tile identified by its south-west corner (integer degrees)."""

    south: int
    west: int

    _PATTERN = re.compile(r"([ns])(\d{2})([ew])(\d{3})", re.IGNORECASE)

    @classmethod
    def from_name(cls, text: str) -> "TileId":
        match = cls._PATTERN.search(PurePosixPath(text.replace("\\", "/")).name)
        if match is None:
            raise ValueError(f"no tile id like 'n51w113' found in {text!r}")
        ns, lat, ew, lon = match.groups()
        south = int(lat) * (1 if ns.lower() == "n" else -1)
        west = int(lon) * (1 if ew.lower() == "e" else -1)
        return cls(south, west)

    @property
    def name(self) -> str:
        return (
            f"{'n' if self.south >= 0 else 's'}{abs(self.south):02d}"
            f"{'e' if self.west >= 0 else 'w'}{abs(self.west):03d}"
        )

    def owned_bbox(self) -> BBox:
        """Half-open extent [S, S+1) x [W, W+1) this tile owns when tiles are combined."""
        return BBox(self.west, self.south, self.west + 1, self.south + 1)


@dataclass(frozen=True)
class GeoGrid:
    """Regular latitude/longitude grid of point samples (pixel-is-point).

    Row 0 is the northernmost row and column 0 the westernmost column.
    """

    north: float  # latitude of row-0 sample centres (deg)
    west: float  # longitude of column-0 sample centres (deg)
    lat_step: float  # degrees between rows (positive; latitude decreases with row index)
    lon_step: float  # degrees between columns
    nrows: int
    ncols: int

    @property
    def south(self) -> float:
        return self.north - (self.nrows - 1) * self.lat_step

    @property
    def east(self) -> float:
        return self.west + (self.ncols - 1) * self.lon_step

    def lats(self) -> np.ndarray:
        return self.north - np.arange(self.nrows) * self.lat_step

    def lons(self) -> np.ndarray:
        return self.west + np.arange(self.ncols) * self.lon_step

    def sample_centre_bounds(self) -> BBox:
        return BBox(self.west, self.south, self.east, self.north)

    def pixel_edge_bounds(self) -> BBox:
        """Bounds of the cells around the samples (half a step outside the sample centres)."""
        return BBox(
            self.west - self.lon_step / 2,
            self.south - self.lat_step / 2,
            self.east + self.lon_step / 2,
            self.north + self.lat_step / 2,
        )

    def geotransform(self) -> tuple[float, float, float, float, float, float]:
        """GDAL-style geotransform (pixel-edge registration), as GDAL reports for SRTM HGT."""
        return (
            self.west - self.lon_step / 2,
            self.lon_step,
            0.0,
            self.north + self.lat_step / 2,
            0.0,
            -self.lat_step,
        )

    def window(self, bbox: BBox) -> tuple[slice, slice] | None:
        """Rows/cols of samples whose centres satisfy south <= lat < north, west <= lon < east.

        Half-open selection means adjacent boxes (or tiles) never share a sample.
        Returns None if no sample centre falls inside ``bbox``.
        """
        rows = _half_open_index_range(self.lats(), bbox.south, bbox.north)
        cols = _half_open_index_range(self.lons(), bbox.west, bbox.east)
        if rows is None or cols is None:
            return None
        return rows, cols

    def subgrid(self, rows: slice, cols: slice) -> "GeoGrid":
        r0, r1, _ = rows.indices(self.nrows)
        c0, c1, _ = cols.indices(self.ncols)
        if r1 <= r0 or c1 <= c0:
            raise ValueError("empty subgrid")
        return GeoGrid(
            north=self.north - r0 * self.lat_step,
            west=self.west + c0 * self.lon_step,
            lat_step=self.lat_step,
            lon_step=self.lon_step,
            nrows=r1 - r0,
            ncols=c1 - c0,
        )

    def dx_m(self) -> np.ndarray:
        """East-west ground spacing between adjacent samples, per row (m)."""
        return geodesy.metres_per_degree_lon(self.lats()) * self.lon_step

    def dy_m(self) -> np.ndarray:
        """North-south ground spacing between adjacent samples, per row (m)."""
        return geodesy.metres_per_degree_lat(self.lats()) * self.lat_step

    def cell_area_m2(self) -> np.ndarray:
        """Ground area represented by each sample, per row (m^2)."""
        return geodesy.cell_area_m2(self.lats(), self.lat_step, self.lon_step)


def _half_open_index_range(coords: np.ndarray, lo: float, hi: float) -> slice | None:
    idx = np.flatnonzero((coords >= lo - _COORD_TOL_DEG) & (coords < hi - _COORD_TOL_DEG))
    if idx.size == 0:
        return None
    return slice(int(idx[0]), int(idx[-1]) + 1)


# --------------------------------------------------------------------------- ZIP access


@dataclass(frozen=True)
class NasademMembers:
    hgt: str
    num: str | None
    swb: str | None
    other: tuple[str, ...] = field(default_factory=tuple)


def find_members(names: list[str]) -> NasademMembers:
    """Identify the elevation raster and its NUM/SWB companions among ZIP member names."""
    by_ext: dict[str, list[str]] = {}
    other = []
    for name in names:
        if name.endswith("/"):
            continue
        ext = PurePosixPath(name).suffix.lower()
        if ext in (".hgt", ".num", ".swb"):
            by_ext.setdefault(ext, []).append(name)
        else:
            other.append(name)
    hgts = by_ext.get(".hgt", [])
    if len(hgts) != 1:
        raise ValueError(f"expected exactly one .hgt member, found {hgts}")
    for ext in (".num", ".swb"):
        if len(by_ext.get(ext, [])) > 1:
            raise ValueError(f"multiple {ext} members: {by_ext[ext]}")
    return NasademMembers(
        hgt=hgts[0],
        num=(by_ext.get(".num") or [None])[0],
        swb=(by_ext.get(".swb") or [None])[0],
        other=tuple(other),
    )


def _square_side(nbytes: int, itemsize: int) -> int:
    count, rem = divmod(nbytes, itemsize)
    side = int(round(count**0.5))
    if rem or side * side != count:
        raise ValueError(f"{nbytes} bytes is not a square grid of {itemsize}-byte samples")
    return side


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


class NasademGranule:
    """Read-only access to one NASADEM_HGT ZIP, read in place without extracting it.

    Rows are streamed out of the compressed members, so reading a small area of
    interest decodes only the rows up to that area.
    """

    def __init__(self, zip_path: str | Path):
        self.zip_path = Path(zip_path)
        self._zf = zipfile.ZipFile(self.zip_path)
        try:
            self.members = find_members(self._zf.namelist())
            self.tile = TileId.from_name(self.members.hgt)
            n = _square_side(self._zf.getinfo(self.members.hgt).file_size, HGT_DTYPE.itemsize)
        except Exception:
            self._zf.close()
            raise
        step = 1.0 / (n - 1)  # n samples span exactly 1 degree, edge to edge
        self.grid = GeoGrid(
            north=self.tile.south + 1.0,
            west=float(self.tile.west),
            lat_step=step,
            lon_step=step,
            nrows=n,
            ncols=n,
        )

    # context manager -----------------------------------------------------------------
    def close(self) -> None:
        self._zf.close()

    def __enter__(self) -> "NasademGranule":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # raw access ----------------------------------------------------------------------
    def _read_rows(self, member: str, dtype: np.dtype, rows: slice) -> np.ndarray:
        r0, r1, step = rows.indices(self.grid.nrows)
        if step != 1 or r1 <= r0:
            raise ValueError(f"unsupported row slice {rows}")
        expected = self.grid.nrows * self.grid.ncols * dtype.itemsize
        actual = self._zf.getinfo(member).file_size
        if actual != expected:
            raise ValueError(f"{member}: {actual} bytes, expected {expected} for the .hgt grid")
        row_bytes = self.grid.ncols * dtype.itemsize
        with self._zf.open(member) as f:
            f.seek(r0 * row_bytes)
            buf = f.read((r1 - r0) * row_bytes)
        if len(buf) != (r1 - r0) * row_bytes:
            raise IOError(f"short read from {member}")
        return np.frombuffer(buf, dtype=dtype).reshape(r1 - r0, self.grid.ncols)

    def read_elevation(self, rows: slice = slice(None), cols: slice = slice(None), dtype=np.float64) -> np.ndarray:
        """Elevation (m, EGM96) as floats; SRTM void samples (-32768) become NaN.

        float32 holds every int16 height exactly and halves memory.
        """
        raw = self._read_rows(self.members.hgt, HGT_DTYPE, rows)[:, cols]
        z = raw.astype(dtype)
        z[raw == SRTM_VOID] = np.nan
        return z

    def read_num(self, rows: slice = slice(None), cols: slice = slice(None)) -> np.ndarray | None:
        if self.members.num is None:
            return None
        return self._read_rows(self.members.num, MASK_DTYPE, rows)[:, cols].copy()

    def read_swb(self, rows: slice = slice(None), cols: slice = slice(None)) -> np.ndarray | None:
        if self.members.swb is None:
            return None
        return self._read_rows(self.members.swb, MASK_DTYPE, rows)[:, cols].copy()

    def water_mask(self, rows: slice = slice(None), cols: slice = slice(None)) -> tuple[np.ndarray, str]:
        """Boolean water mask and a note on its source (SWB preferred, NUM == 0 as fallback)."""
        swb = self.read_swb(rows, cols)
        if swb is not None:
            return swb == SWB_WATER, "swb == 255"
        num = self.read_num(rows, cols)
        if num is not None:
            return num == 0, "num == 0 (no .swb member)"
        shape = (len(range(*rows.indices(self.grid.nrows))), len(range(*cols.indices(self.grid.ncols))))
        return np.zeros(shape, dtype=bool), "none available (all samples treated as land)"

    # validation ----------------------------------------------------------------------
    def inspect(self) -> dict:
        """Full-granule metadata and validation checks (decodes all 3601 x 3601 samples)."""
        checks: list[dict] = []

        def check(name: str, passed: bool, detail: str) -> None:
            checks.append({"check": name, "passed": bool(passed), "detail": detail})

        zf = self._zf
        bad_member = zf.testzip()
        check("zip_crc_ok", bad_member is None, f"first corrupt member: {bad_member}" if bad_member else "all CRCs match")

        zip_tile = None
        try:
            zip_tile = TileId.from_name(self.zip_path.name)
        except ValueError:
            pass
        check(
            "zip_name_matches_hgt_tile",
            zip_tile == self.tile,
            f"zip: {zip_tile.name if zip_tile else 'none'}, hgt member: {self.tile.name}",
        )
        g = self.grid
        check(
            "hgt_is_3601x3601_1arcsec",
            g.nrows == NASADEM_SAMPLES and g.ncols == NASADEM_SAMPLES,
            f"{g.nrows} x {g.ncols} samples, {g.lat_step * 3600:.6f} arcsec spacing",
        )
        for role in ("num", "swb"):
            member = getattr(self.members, role)
            size_ok = member is not None and zf.getinfo(member).file_size == g.nrows * g.ncols
            check(f"{role}_present_and_matches_grid", size_ok, member or "missing")

        raw = self._read_rows(self.members.hgt, HGT_DTYPE, slice(None))
        void = raw == SRTM_VOID
        valid = raw[~void]
        lo, hi = PLAUSIBLE_ELEVATION_M
        implausible = int(np.count_nonzero((valid < lo) | (valid > hi)))
        check("no_void_samples", not void.any(), f"{int(void.sum())} samples == {SRTM_VOID} (NASADEM_HGT is void-filled)")
        check("elevations_plausible", implausible == 0, f"{implausible} samples outside {lo:g}..{hi:g} m")

        elevation = {
            "dtype": "int16, big-endian (>i2)",
            "units": "m",
            "vertical_datum": VERTICAL_DATUM,
            "documented_fill_value": None,
            "void_value_treated_as_nodata": SRTM_VOID,
            "void_count": int(void.sum()),
            "valid_count": int(valid.size),
            "min_m": int(valid.min()) if valid.size else None,
            "max_m": int(valid.max()) if valid.size else None,
            "mean_m_unweighted_all_samples": float(valid.mean()) if valid.size else None,
            "plausible_range_m": [lo, hi],
            "implausible_count": implausible,
        }

        num_info = None
        num = self.read_num()
        if num is not None:
            counts = np.bincount(num.ravel(), minlength=256)
            per_code, per_category = {}, {}
            for code in np.flatnonzero(counts).tolist():
                count = int(counts[code])
                category, description = describe_num_code(code)
                per_code[str(code)] = {"count": count, "category": category, "description": description}
                per_category[category] = per_category.get(category, 0) + count
            check(
                "num_codes_documented",
                "undocumented" not in per_category and "error" not in per_category,
                f"categories present: {sorted(per_category)}",
            )
            num_info = {
                "code_counts": per_code,
                "category_counts": per_category,
                "code_table_source": "NASADEM User Guide Table 2",
            }

        swb_info = None
        swb = self.read_swb()
        if swb is not None:
            n_land = int(np.count_nonzero(swb == SWB_LAND))
            n_water = int(np.count_nonzero(swb == SWB_WATER))
            n_other = int(swb.size - n_land - n_water)
            check("swb_values_are_0_or_255", n_other == 0, f"{n_other} samples with other values")
            swb_info = {
                "land_count": n_land,
                "water_count": n_water,
                "other_count": n_other,
                "water_fraction": n_water / swb.size,
            }
            if num is not None:
                agree = np.array_equal(num == 0, swb == SWB_WATER)
                check("num_water_matches_swb_water", agree, "NUM == 0 <=> SWB == 255")

        dx, dy = g.dx_m(), g.dy_m()
        info = {
            "product": "NASADEM_HGT V001 (NASADEM Merged DEM Global 1 arc second)",
            "zip_file": self.zip_path.name,
            "zip_bytes": self.zip_path.stat().st_size,
            "zip_sha256": sha256_file(self.zip_path),
            "members": [
                {
                    "name": i.filename,
                    "role": {".hgt": "elevation", ".num": "source/scene-count codes", ".swb": "water-body mask"}.get(
                        PurePosixPath(i.filename).suffix.lower(), "other"
                    ),
                    "bytes_uncompressed": i.file_size,
                    "bytes_compressed": i.compress_size,
                    "modified": "%04d-%02d-%02dT%02d:%02d:%02d" % i.date_time,
                }
                for i in zf.infolist()
            ],
            "tile_id": self.tile.name,
            "tile_naming": "south-west corner of the 1 x 1 degree tile (NASADEM User Guide V1.3, Section 3.1)",
            "horizontal_crs": HORIZONTAL_CRS,
            "vertical_datum": VERTICAL_DATUM,
            "crs_source": (
                "defined by the NASADEM/SRTM HGT format and tile name; .hgt files are headerless "
                "raw rasters with no embedded CRS or geotransform"
            ),
            "grid": {
                "rows": g.nrows,
                "cols": g.ncols,
                "lat_step_deg": g.lat_step,
                "lon_step_deg": g.lon_step,
                "resolution_arcsec": g.lat_step * 3600.0,
                "registration": (
                    "pixel-is-point: sample centres on integer arc-seconds; edge rows/columns "
                    "are shared with neighbouring tiles"
                ),
                "sample_centre_bounds_deg": g.sample_centre_bounds().as_dict(),
                "pixel_edge_bounds_deg": g.pixel_edge_bounds().as_dict(),
                "gdal_geotransform": list(g.geotransform()),
                "row_order": "north to south",
                "dx_m_range": [float(dx.min()), float(dx.max())],
                "dy_m_range": [float(dy.min()), float(dy.max())],
            },
            "elevation": elevation,
            "num": num_info,
            "swb": swb_info,
            "checks": checks,
            "all_checks_passed": all(c["passed"] for c in checks),
        }
        return info


def rasterio_crosscheck(granule: NasademGranule) -> dict:
    """Compare the native reader with GDAL (via rasterio) when rasterio can be loaded.

    Never raises: returns a status dict so a missing or blocked GDAL install does
    not stop the pipeline.
    """
    try:
        import rasterio
    except Exception as exc:  # ImportError, or OSError/ImportError from a blocked DLL
        return {"status": "unavailable", "reason": f"{type(exc).__name__}: {exc}"}
    try:
        path = f"/vsizip/{granule.zip_path.resolve().as_posix()}/{granule.members.hgt}"
        with rasterio.open(path) as src:
            data = src.read(1)
            t = src.transform
            gdal_gt = (t.c, t.a, t.b, t.f, t.d, t.e)
            native = granule._read_rows(granule.members.hgt, HGT_DTYPE, slice(None))
            return {
                "status": "ok",
                "rasterio_version": rasterio.__version__,
                "gdal_version": rasterio.__gdal_version__,
                "driver": src.driver,
                "crs": src.crs.to_string() if src.crs else None,
                "width": src.width,
                "height": src.height,
                "dtype": src.dtypes[0],
                "nodata": src.nodata,
                "geotransform": list(gdal_gt),
                "geotransform_matches_native": bool(
                    np.allclose(gdal_gt, granule.grid.geotransform(), rtol=0.0, atol=1e-12)
                ),
                "pixel_values_identical": bool(np.array_equal(data, native)),
            }
    except Exception as exc:
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}
