import json
import os
import requests
from shapely.geometry import Point
from layers.utils import load_boundary

WFS_URL = "https://gdi.berlin.de/services/wfs/wohnlagenadr2024"

PARAMS = {
    "SERVICE":      "WFS",
    "VERSION":      "2.0.0",
    "REQUEST":      "GetFeature",
    "TYPENAMES":    "wohnlagenadr2024:wohnlagenadr2024",
    "SRSNAME":      "EPSG:4326",
    "outputFormat": "application/json",
    "COUNT":        "5000",
    "CQL_FILTER":   "bezname='Mitte' AND BBOX(geom,13.3110,52.5165,13.3720,52.5420,'EPSG:4326')",
}

CACHE_PATH = "data/wohnlagen.geojson"

WOL_STYLE = {
    "einfach": {"colour": "#E24B4A", "label": "Einfach"},
    "mittel":  {"colour": "#EF9F27", "label": "Mittel"},
    "gut":     {"colour": "#1D9E75", "label": "Gut"},
}

def fetch_wohnlagen():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    response = requests.get(WFS_URL, params=PARAMS, timeout=30)
    response.raise_for_status()
    features = response.json()["features"]

    # Filter to points strictly within the Moabit boundary polygon
    boundary = load_boundary()
    features = [
        f for f in features
        if boundary.contains(Point(f["geometry"]["coordinates"][:2]))
    ]

    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(features, f)
    return features
