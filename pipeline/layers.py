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

    def columns(self) -> list[str]:
        return [f"{self.name}__{s}" for s in STATS]


LAYERS = [
    Layer("elevation_m", 2, "terrain", "cell"),
    Layer("slope_deg", 2, "terrain", "fixed"),
    Layer("tri_m", 2, "terrain", "fixed"),  # terrain ruggedness index: mean |Δh| to 8 neighbours
]

# Known-absent quantities: (layer, body) -> physical value, used when no source exists for
# that body (e.g. ("wind_ms", "moon"): 0.0). Filled with std/percentile spread of 0.
KNOWN_ABSENT: dict[tuple[str, str], float] = {}

# Quantities nothing measures on a body: (layer, body) -> another layer whose stats stand in,
# labelled as a proxy (e.g. ("biosignature", "mars"): "hydrated_minerals").
PROXIES: dict[tuple[str, str], str] = {}
