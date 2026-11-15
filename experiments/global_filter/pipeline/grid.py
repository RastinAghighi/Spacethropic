"""H3 cells covering each site disk, with areas and distances on the site's own body.

H3 indexes a unit sphere. Its km-based helpers assume Earth's radius, so every physical
quantity here is computed in radians and scaled by the body radius instead.
"""
import math

import h3
import pandas as pd

from config import Site

H3_EARTH_RADIUS_KM = 6371.007180918475


def site_cells(site: Site) -> pd.DataFrame:
    res = site.body.h3_res
    R = site.body.radius_m
    r_rad = site.radius_km * 1000 / R
    edge_rad = h3.average_hexagon_edge_length(res, unit="km") / H3_EARTH_RADIUS_KM
    k = math.ceil(r_rad / (math.sqrt(3) * edge_rad)) + 2

    centre = h3.latlng_to_cell(site.lat, site.lon, res)
    rows = []
    for cell in h3.grid_disk(centre, k):
        lat, lon = h3.cell_to_latlng(cell)
        d_rad = h3.great_circle_distance((lat, lon), (site.lat, site.lon), unit="rads")
        if d_rad <= r_rad:
            rows.append(
                {
                    "cell": cell,
                    "lat": lat,
                    "lon": lon,
                    "area_km2": h3.cell_area(cell, unit="rads^2") * R * R / 1e6,
                    "dist_km": d_rad * R / 1000,
                }
            )
    return pd.DataFrame(rows).sort_values("dist_km", ignore_index=True)
