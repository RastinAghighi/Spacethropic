"""Source registry: for each feature group and body, sources in fill order.

The first source that covers a site is its primary ("measured"); later ones are fallbacks used
only for cells the primary leaves empty.
"""
from config import Site
from sources.base import Source
from sources.terrain import CopernicusDEM, HrscMolaBlend, LolaGlobal, LolaPolar, Mola

REGISTRY: dict[str, dict[str, list[Source]]] = {
    "terrain": {
        "earth": [CopernicusDEM()],
        "moon": [LolaPolar(), LolaGlobal()],
        "mars": [HrscMolaBlend(), Mola()],
    },
}


def sources_for(site: Site, group: str) -> list[Source]:
    return [s for s in REGISTRY[group].get(site.body.name, []) if s.covers(site)]
