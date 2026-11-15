from pathlib import Path

from config import Site


class Source:
    """One dataset product. `fetch` writes a single-band raster on the site-local grid and
    returns provenance for the manifest."""

    id: str
    group: str  # which feature extractor consumes it, e.g. "terrain"
    bodies: set[str]
    product: str
    native_res: str

    def covers(self, site: Site) -> bool:
        return True

    def fetch(self, site: Site, out: Path) -> dict:
        raise NotImplementedError
