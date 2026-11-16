"""
Nevada candidate patches: every H3 res-7 cell in Nevada, its terrain disk
sampled at 200 m from Copernicus DEM GLO-90.

    .venv/Scripts/python prepare.py      # -> out/nevada_patches.npz
"""

from pathlib import Path

import h3
import numpy as np
import rasterio

from shape import PX_M, bilinear, offsets

ROOT = Path(__file__).parent
DEM = ROOT / "dem"
OUT = ROOT / "out" / "nevada_patches.npz"
R_EARTH = 6371007.18
# Same outline as db/build.py in the nasa26 repo
NEVADA = [
    (42.000, -120.000), (42.000, -114.040), (36.120, -114.040), (36.050, -114.300),
    (36.016, -114.737), (35.500, -114.670), (35.002, -114.633), (39.000, -120.000),
]


class Mosaic:
    """GLO-90 tiles stitched into one lat/lon grid, lightly smoothed to the 200 m footprint."""

    def __init__(self, folder: Path):
        tiles = sorted(folder.glob("*.tif"))
        with rasterio.open(tiles[0]) as t:
            self.d = t.transform.a  # degrees per pixel
            n = t.height
        tops, lefts = [], []
        for p in tiles:
            with rasterio.open(p) as t:
                tops.append(t.transform.f)
                lefts.append(t.transform.c)
        self.top, self.left = max(tops), min(lefts)
        rows = int(round((self.top - min(tops) + 1) / self.d))
        cols = int(round((max(lefts) + 1 - self.left) / self.d))
        z = np.full((rows, cols), np.nan, np.float32)
        for p in tiles:
            with rasterio.open(p) as t:
                a = t.read(1).astype(np.float32)
                r0 = int(round((self.top - t.transform.f) / self.d))
                c0 = int(round((t.transform.c - self.left) / self.d))
                z[r0:r0 + n, c0:c0 + a.shape[1]] = a
        # 3x3 box (about 270 m at this latitude) so 200 m samples aren't aliased
        k = np.pad(z, 1, mode="edge")
        self.z = sum(k[i:i + rows, j:j + cols] for i in range(3) for j in range(3)) / 9.0

    def sample(self, lat, lon):
        return bilinear(self.z, (self.top - lat) / self.d - 0.5, (lon - self.left) / self.d - 0.5)

    def patch(self, lat0: float, lon0: float, angle: float = 0.0) -> np.ndarray:
        e, n = offsets(angle)
        lat = lat0 + np.degrees(n / R_EARTH)
        lon = lon0 + np.degrees(e / (R_EARTH * np.cos(np.radians(lat0))))
        return self.sample(lat, lon)

    def raster(self, lat0: float, lon0: float, half: int, angle: float = 0.0) -> np.ndarray:
        """A local metric raster (200 m pixels, north up, rotated by angle) around a point."""
        ii, jj = np.mgrid[-half:half + 1, -half:half + 1]
        a = np.radians(angle)
        e0, n0 = jj * PX_M, -ii * PX_M
        e, n = e0 * np.cos(a) - n0 * np.sin(a), e0 * np.sin(a) + n0 * np.cos(a)
        lat = lat0 + np.degrees(n / R_EARTH)
        lon = lon0 + np.degrees(e / (R_EARTH * np.cos(np.radians(lat0))))
        return self.sample(lat, lon)


def main():
    m = Mosaic(DEM)
    print(f"mosaic {m.z.shape}, {np.isnan(m.z).mean():.4%} empty")
    cells = sorted(h3.polygon_to_cells(h3.LatLngPoly(NEVADA), 7))
    ll = np.array([h3.cell_to_latlng(c) for c in cells])
    patches = np.array([m.patch(la, lo) for la, lo in ll], dtype=np.float32)
    keep = ~np.isnan(patches).any(axis=(1, 2))
    OUT.parent.mkdir(exist_ok=True)
    np.savez_compressed(OUT, h3=np.array(cells)[keep], lat=ll[keep, 0], lon=ll[keep, 1], patches=patches[keep])
    print(f"{OUT}: {keep.sum():,} cells ({(~keep).sum()} dropped for missing DEM)")


if __name__ == "__main__":
    main()
