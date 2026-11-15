"""Source registry: for each feature group and body, sources in fill order.

The first source that covers a site is its primary ("measured"); later ones are fallbacks used
only for cells the primary leaves empty.
"""
from config import Site
from sources.albedo import LolaAlbedoGlobal, LolaAlbedoSouthPole, Sentinel2Albedo, TesAlbedo
from sources.base import Source
from sources.climate import DivinerTemperature, MarsGcmTemperature, MarsGcmWeather, OrbitalInsolation, PowerSkinTemperature, PowerWeather
from sources.geochem import LunarProspectorGRS, OdysseyGRS
from sources.terrain import CopernicusDEM, HrscMolaBlend, LolaGlobal, LolaPolar, Mola

REGISTRY: dict[str, dict[str, list[Source]]] = {
    "temperature": {
        "earth": [PowerSkinTemperature()],
        "moon": [DivinerTemperature()],
        "mars": [MarsGcmTemperature()],
    },
    "weather": {
        "earth": [PowerWeather()],
        "moon": [],  # no atmosphere: layers.KNOWN_ABSENT
        "mars": [MarsGcmWeather()],
    },
    "insolation": {b: [OrbitalInsolation()] for b in ("earth", "moon", "mars")},
    "albedo": {
        "earth": [Sentinel2Albedo()],
        "moon": [LolaAlbedoSouthPole(), LolaAlbedoGlobal()],
        "mars": [TesAlbedo()],
    },
    "geochem": {
        "earth": [],  # no orbital FeO for Earth; ground-sample values not sourced yet
        "moon": [LunarProspectorGRS()],
        "mars": [OdysseyGRS()],
    },
    "terrain": {
        "earth": [CopernicusDEM()],
        "moon": [LolaPolar(), LolaGlobal()],
        "mars": [HrscMolaBlend(), Mola()],
    },
}


def sources_for(site: Site, group: str) -> list[Source]:
    return [s for s in REGISTRY[group].get(site.body.name, []) if s.covers(site)]
