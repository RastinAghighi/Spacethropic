"""What ends up in the merged table, and how gaps in each layer are filled."""
from dataclasses import dataclass

DIMENSIONS = {
    1: "Geology, mineralogy, and surface materials",
    2: "Terrain, elevation, slope, roughness, craters",
    3: "Temperature, illumination, environmental extremes",
    4: "Water, ice, permafrost, resources",
    5: "Dust, wind, erosion, atmospheric/surface processes",
    6: "Biology, extremophiles, habitability, biosignatures",
    7: "Caves, lava tubes, subsurface",
    8: "Landing, mobility, navigation, robotic/human ops, construction",
}

STATS = ("mean", "std", "p10", "p50", "p90")


@dataclass(frozen=True)
class Layer:
    name: str
    dimension: int
    group: str  # source group in sources.REGISTRY
    # "cell": stats over the pixels inside the H3 cell.
    # "fixed": stats over a fixed ~6 km² disk at the cell centre, identical on every body.
    window: str
    stats: tuple[str, ...] = STATS  # subset of STATS kept in the output
    # True: cells no fill rule can reach stay empty and are reported in coverage.csv instead
    # of failing the merge. Default True by user decision: "it's ok to have some features
    # missing from certain locations". Set False for a layer that must always be complete.
    allow_gaps: bool = True

    def columns(self) -> list[str]:
        return [f"{self.name}__{s}" for s in self.stats]


LAYERS = [
    # Total iron as FeO wt%. Orbital gamma-ray bins are 60–300 km, so a site has ~1 value:
    # keep the mean only. No Earth source exists yet, and the Mars map masks the poles.
    Layer("feo_wt_pct", 1, "geochem", "cell", stats=("mean",)),
    # Fraction of light reflected (0–1). Definitions differ slightly by body; see sources/albedo.py.
    Layer("albedo", 1, "albedo", "cell"),
    # Only the spread is kept: absolute heights use a different reference on each body
    # (EGM2008 geoid, 1737.4 km sphere, MOLA areoid), so mean/percentiles aren't comparable.
    Layer("elevation_m", 2, "terrain", "cell", stats=("std",)),
    Layer("slope_deg", 2, "terrain", "fixed"),
    Layer("tri_m", 2, "terrain", "fixed"),  # terrain ruggedness index: mean |Δh| to 8 neighbours
    # Surface (skin) temperature over a year; day = local solar time 6–18 h. Sources are
    # 15–300 km grids, so only the cell mean is kept. See sources/climate.py.
    Layer("temp_day_max_k", 3, "temperature", "cell", stats=("mean",)),
    Layer("temp_night_max_k", 3, "temperature", "cell", stats=("mean",)),
    Layer("temp_night_min_k", 3, "temperature", "cell", stats=("mean",)),
    Layer("temp_mean_k", 3, "temperature", "cell", stats=("mean",)),
    # Annual-mean top-of-atmosphere sunlight from latitude + orbit; no terrain shadowing.
    Layer("insolation_wm2", 3, "insolation", "cell", stats=("mean",)),
    # Weather: annual mean surface pressure, mean and max near-surface wind. Earth wind is at
    # 10 m, Mars wind is the GCM layer nearest the ground. See sources/climate.py.
    Layer("pressure_mean_pa", 5, "weather", "cell", stats=("mean",)),
    Layer("wind_mean_ms", 5, "weather", "cell", stats=("mean",)),
    Layer("wind_max_ms", 5, "weather", "cell", stats=("mean",)),
]

# Known-absent quantities: (layer, body) -> physical value, used when no source exists for
# that body (e.g. ("wind_ms", "moon"): 0.0). Filled with std/percentile spread of 0.
KNOWN_ABSENT: dict[tuple[str, str], float] = {
    # The Moon has no atmosphere (surface pressure ~3e-10 Pa, treated as 0) and so no wind.
    ("pressure_mean_pa", "moon"): 0.0,
    ("wind_mean_ms", "moon"): 0.0,
    ("wind_max_ms", "moon"): 0.0,
}

# Quantities nothing measures on a body: (layer, body) -> another layer whose stats stand in,
# labelled as a proxy (e.g. ("biosignature", "mars"): "hydrated_minerals").
PROXIES: dict[tuple[str, str], str] = {}
