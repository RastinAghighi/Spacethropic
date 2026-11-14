"""Per-pixel features derived from a source raster. Inputs are already on the shared baseline
pixel size, so slope and roughness mean the same thing on every body."""
import numpy as np


def terrain(dem: np.ndarray, pixel_m: float) -> dict[str, np.ndarray]:
    gy, gx = np.gradient(dem, pixel_m)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))

    padded = np.pad(dem, 1, constant_values=np.nan)
    h, w = dem.shape
    diffs = [
        np.abs(padded[1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w] - dem)
        for dy in (-1, 0, 1)
        for dx in (-1, 0, 1)
        if (dy, dx) != (0, 0)
    ]
    with np.errstate(invalid="ignore"):
        tri = np.nanmean(np.stack(diffs), axis=0) if np.isfinite(dem).any() else np.full_like(dem, np.nan)
    tri[~np.isfinite(dem)] = np.nan

    return {"elevation_m": dem, "slope_deg": slope.astype(np.float32), "tri_m": tri.astype(np.float32)}


EXTRACTORS = {"terrain": terrain}
