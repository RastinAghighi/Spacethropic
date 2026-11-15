"""Per-pixel features derived from a source raster. Inputs are already on the shared baseline
pixel size, so slope and roughness mean the same thing on every body."""
import warnings

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
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN neighbourhoods -> NaN, expected
        tri = np.nanmean(np.stack(diffs), axis=0)
    tri[~np.isfinite(dem)] = np.nan

    return {"elevation_m": dem, "slope_deg": slope.astype(np.float32), "tri_m": tri.astype(np.float32)}


def geochem(values: np.ndarray, pixel_m: float) -> dict[str, np.ndarray]:
    return {"feo_wt_pct": values}


def albedo(values: np.ndarray, pixel_m: float) -> dict[str, np.ndarray]:
    return {"albedo": values}


def temperature(bands: np.ndarray, pixel_m: float) -> dict[str, np.ndarray]:
    from sources.climate import BANDS

    return dict(zip(BANDS, bands))


# Each extractor gets all bands of a source raster, shape (bands, h, w).
EXTRACTORS = {
    "terrain": lambda b, px: terrain(b[0], px),
    "geochem": lambda b, px: geochem(b[0], px),
    "albedo": lambda b, px: albedo(b[0], px),
    "temperature": temperature,
    "insolation": lambda b, px: {"insolation_wm2": b[0]},
    "weather": lambda b, px: dict(zip(("pressure_mean_pa", "wind_mean_ms", "wind_max_ms"), b)),
}
