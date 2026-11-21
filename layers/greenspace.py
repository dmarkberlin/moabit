import json
import os
from shapely.geometry import shape, Point
from layers.overpass import overpass_post
from layers.utils import load_boundary

CACHE_PATH = "data/greenspaces.json"
BBOX = "(52.5165,13.3110,52.5420,13.3720)"

QUERY = f"""
[out:json][timeout:25];
(
  way["leisure"="park"]{BBOX};
  way["leisure"="garden"]{BBOX};
  way["landuse"="grass"]{BBOX};
  way["landuse"="recreation_ground"]{BBOX};
  way["leisure"="playground"]{BBOX};
  way["leisure"="sports_centre"]{BBOX};
);
out geom;
"""

# Dashboard Material palette. The three vegetated types stay in the green family
# (park → garden → grass, darkest to lightest); the built types take contrasting
# hues so they read as different in kind, not merely a different shade of green.
_GREEN_COLOURS = {
    "park":               "#43A047",
    "garden":             "#7CB342",
    "grass":              "#B6E880",
    "recreation_ground":  "#FB8C00",
    "playground":         "#FFB300",
    "sports_centre":      "#039BE5",
}

_FILL_OPACITY = {
    "park": 0.4, "garden": 0.4, "grass": 0.3,
    "recreation_ground": 0.3, "playground": 0.4, "sports_centre": 0.3,
}
_WEIGHT = {"grass": 0.5}

FEATURE_STYLE = {
    key: {
        "color":       colour,
        "fillColor":   colour,
        "fillOpacity": _FILL_OPACITY[key],
        "weight":      _WEIGHT.get(key, 1),
    }
    for key, colour in _GREEN_COLOURS.items()
}

# German display label per OSM feature type, for the legend and the map tooltip
# (the cached features carry the raw OSM value, e.g. "recreation_ground").
TYPE_LABELS = {
    "park":               "Park",
    "garden":             "Garten",
    "grass":              "Rasenfläche",
    "recreation_ground":  "Freizeitgelände",
    "playground":         "Spielplatz",
    "sports_centre":      "Sportstätte",
}

LEGEND = {TYPE_LABELS[key]: colour for key, colour in _GREEN_COLOURS.items()}

def _way_to_geojson(el):
    """Convert an Overpass way with geometry to a GeoJSON feature."""
    coords = [[n["lon"], n["lat"]] for n in el.get("geometry", [])]
    if len(coords) < 3:
        return None
    tags = el.get("tags", {})
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [coords]},
        "properties": {
            "name":     tags.get("name", ""),
            "type":     tags.get("leisure") or tags.get("landuse", ""),
        }
    }

def fetch_greenspaces():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)

    response = overpass_post(QUERY, timeout=30)
    response.raise_for_status()
    elements = response.json()["elements"]

    boundary = load_boundary()
    features = []
    for el in elements:
        feature = _way_to_geojson(el)
        if not feature:
            continue
        # Keep if centroid is within Moabit boundary
        try:
            centroid = shape(feature["geometry"]).centroid
            if boundary.contains(centroid):
                features.append(feature)
        except Exception:
            continue

    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(features, f)
    return features
