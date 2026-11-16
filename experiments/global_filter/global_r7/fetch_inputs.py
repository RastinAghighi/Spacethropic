"""Download matching public inputs; inventory protected MODIS inputs without credentials."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import zipfile
from pathlib import Path

import requests

NE = "https://naturalearth.s3.amazonaws.com/5.1.1/10m_physical/ne_10m_land.zip"
GHSL = (
    "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_POP_GLOBE_R2023A/"
    "GHS_POP_E2020_GLOBE_R2023A_4326_30ss/V1-0/"
    "GHS_POP_E2020_GLOBE_R2023A_4326_30ss_V1_0.zip"
)
CMR = "https://cmr.earthdata.nasa.gov/search/granules.json"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(8 << 20), b""):
            h.update(b)
    return h.hexdigest()


def fetch(url, dest):
    dest = Path(dest)
    receipt = dest.with_suffix(dest.suffix + ".json")
    if dest.exists():
        if not receipt.exists() or json.loads(receipt.read_text())["sha256"] != sha256(
            dest
        ):
            raise ValueError(f"Unverified existing download: {dest}")
        return json.loads(receipt.read_text())
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    offset = tmp.stat().st_size if tmp.exists() else 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    with requests.get(url, stream=True, timeout=(30, 120), headers=headers) as r:
        r.raise_for_status()
        append = offset > 0 and r.status_code == 206
        if append and not r.headers.get("Content-Range", "").startswith(
            f"bytes {offset}-"
        ):
            raise ValueError("Unexpected range response")
        with open(tmp, "ab" if append else "wb") as f:
            for b in r.iter_content(4 << 20):
                f.write(b)
        if zipfile.is_zipfile(tmp):
            with zipfile.ZipFile(tmp) as z:
                if z.testzip() is not None:
                    raise ValueError("ZIP CRC failed")
        else:
            raise ValueError(f"Not a ZIP: {url}")
        meta = dict(
            url=url,
            resolved_url=r.url,
            bytes=tmp.stat().st_size,
            sha256=sha256(tmp),
            etag=r.headers.get("ETag"),
            last_modified=r.headers.get("Last-Modified"),
        )
    os.replace(tmp, dest)
    receipt.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta), flush=True)
    return meta


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument(
        "--only", choices=["natural-earth", "ghsl", "modis", "all"], default="all"
    )
    a = p.parse_args()
    a.root.mkdir(parents=True, exist_ok=True)
    if a.only in ("all", "natural-earth"):
        fetch(NE, a.root / "natural-earth" / "ne_10m_land.zip")
    if a.only in ("all", "ghsl"):
        dest = a.root / "ghsl" / GHSL.rsplit("/", 1)[1]
        fetch(GHSL, dest)
        with zipfile.ZipFile(dest) as z:
            for name in z.namelist():
                if name.endswith(".tif"):
                    out = dest.parent / Path(name).name
                    if not out.exists():
                        tmp = out.with_suffix(".tif.part")
                        with z.open(name) as src, open(tmp, "wb") as dst:
                            import shutil

                            shutil.copyfileobj(src, dst, 8 << 20)
                        os.replace(tmp, out)
                    print(
                        f"GHSL raster: {out} ({out.stat().st_size} bytes)", flush=True
                    )
    if a.only in ("all", "modis"):
        result = {}
        for product in ("MCD12C1", "MCD12Q1"):
            r = requests.get(
                CMR,
                params=dict(
                    short_name=product,
                    version="061",
                    page_size=1000,
                    temporal="2023-01-01T00:00:00Z,2023-12-31T23:59:59Z",
                ),
                timeout=60,
            )
            r.raise_for_status()
            entries = r.json()["feed"]["entry"]
            result[product] = [
                dict(
                    title=e["title"],
                    urls=[
                        l["href"]
                        for l in e["links"]
                        if l["href"].startswith("https:") and l["href"].endswith(".hdf")
                    ],
                )
                for e in entries
            ]
        (a.root / "modis_2023_inventory.json").write_text(json.dumps(result, indent=2))
        print({k: len(v) for k, v in result.items()}, flush=True)
        print(
            "MODIS requires Earthdata authentication or teammate transfer; no credentials read."
        )


if __name__ == "__main__":
    main()
