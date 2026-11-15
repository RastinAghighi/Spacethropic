"""Download the three global inputs for the Earth exclusion mask (see global_mask.py).

- VIIRS VNP13C2 v002 monthly NDVI, 0.05 deg CMG, all 12 months of 2023 (needs EARTHDATA_TOKEN in .env)
- GHSL GHS-POP R2023A, epoch 2020, 30 arcsec WGS84 (JRC, open)
- Natural Earth 1:10m land polygons, GeoJSON (public domain)

Usage: uv run python analysis/global_mask_download.py
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "global"

CMR = "https://cmr.earthdata.nasa.gov/search/granules.json"
GHSL = ("https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_POP_GLOBE_R2023A/"
        "GHS_POP_E2020_GLOBE_R2023A_4326_30ss/V1-0/GHS_POP_E2020_GLOBE_R2023A_4326_30ss_V1_0.zip")
NE_LAND = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_land.geojson"


def token() -> str:
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("EARTHDATA_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("EARTHDATA_TOKEN missing from pipeline/.env")


def fetch(url: str, dest: Path, headers: dict | None = None) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"have {dest.name}")
        return
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, headers=headers, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    tmp.replace(dest)
    print(f"got  {dest.name} ({dest.stat().st_size / 1e6:.0f} MB)")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    fetch(NE_LAND, OUT / "ne_10m_land.geojson")

    zpath = OUT / Path(GHSL).name
    fetch(GHSL, zpath)
    with zipfile.ZipFile(zpath) as z:
        for name in z.namelist():
            if name.endswith(".tif") and not (OUT / name).exists():
                z.extract(name, OUT)

    granules = requests.get(CMR, params={
        "short_name": "VNP13C2", "version": "002", "page_size": 50,
        "temporal": "2023-01-01T00:00:00Z,2023-12-31T23:59:59Z",
    }, timeout=60).json()["feed"]["entry"]
    auth = {"Authorization": f"Bearer {token()}"}
    ndvi_dir = OUT / "vnp13c2"
    ndvi_dir.mkdir(exist_ok=True)
    for g in granules:
        href = next(l["href"] for l in g["links"] if l["href"].endswith(".h5"))
        fetch(href, ndvi_dir / Path(href).name, auth)


if __name__ == "__main__":
    main()
