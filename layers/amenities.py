import json
import os
from shapely.geometry import Point
from layers.overpass import overpass_post
from layers.utils import load_boundary

CACHE_PATH = "data/amenities.json"
BBOX = "(52.5165,13.3110,52.5420,13.3720)"

QUERY = f"""
[out:json][timeout:25];
(
  node["amenity"="school"]{BBOX};
  way["amenity"="school"]{BBOX};
  relation["amenity"="school"]{BBOX};
  node["amenity"="kindergarten"]{BBOX};
  way["amenity"="kindergarten"]{BBOX};
  relation["amenity"="kindergarten"]{BBOX};
  node["amenity"="pharmacy"]{BBOX};
  node["amenity"="doctors"]{BBOX};
  node["amenity"="clinic"]{BBOX};
  node["shop"="supermarket"]{BBOX};
  node["shop"="convenience"]{BBOX};
);
out center;
"""

AMENITY_STYLE = {
    "school":       {"colour": "#E24B4A", "label": "Schule"},
    "kindergarten": {"colour": "#EF9F27", "label": "Kita"},
    "pharmacy":     {"colour": "#1D9E75", "label": "Apotheke"},
    "doctors":      {"colour": "#4FC3F7", "label": "Arzt"},
    "clinic":       {"colour": "#0097A7", "label": "Klinik"},
    "supermarket":  {"colour": "#9B59B6", "label": "Supermarkt"},
    "convenience":  {"colour": "#B07FD4", "label": "Kiosk"},
}

LEGEND = {v["label"]: v["colour"] for v in AMENITY_STYLE.values()}

def _get_coords(el):
    """Return (lat, lon) for both nodes and ways (using center)."""
    if el["type"] == "node":
        return el["lat"], el["lon"]
    if "center" in el:
        return el["center"]["lat"], el["center"]["lon"]
    return None

def fetch_amenities():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)

    response = overpass_post(QUERY, timeout=30)
    response.raise_for_status()
    elements = response.json()["elements"]

    boundary = load_boundary()
    features = []
    seen = set()
    for el in elements:
        coords = _get_coords(el)
        if not coords:
            continue
        lat, lon = coords
        if not boundary.contains(Point(lon, lat)):
            continue
        tags = el.get("tags", {})
        amenity = tags.get("amenity") or tags.get("shop")
        if not amenity:
            continue
        # Deduplicate by name + type (ways and nodes can overlap)
        key = (amenity, tags.get("name", ""), round(lat, 4), round(lon, 4))
        if key in seen:
            continue
        seen.add(key)
        features.append({
            "lat":     lat,
            "lon":     lon,
            "amenity": amenity,
            "name":    tags.get("name", ""),
            "address": f"{tags.get('addr:street', '')} {tags.get('addr:housenumber', '')}".strip(),
        })

    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(features, f)
    return features
