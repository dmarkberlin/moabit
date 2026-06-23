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

# Style by feature type
FEATURE_STYLE = {
    "park":               {"color": "#1D9E75", "fillColor": "#1D9E75", "fillOpacity": 0.4, "weight": 1},
    "garden":             {"color": "#2ECC71", "fillColor": "#2ECC71", "fillOpacity": 0.4, "weight": 1},
    "grass":              {"color": "#72CEB0", "fillColor": "#72CEB0", "fillOpacity": 0.3, "weight": 0.5},
    "recreation_ground":  {"color": "#EF9F27", "fillColor": "#EF9F27", "fillOpacity": 0.3, "weight": 1},
    "playground":         {"color": "#F7D070", "fillColor": "#F7D070", "fillOpacity": 0.4, "weight": 1},
    "sports_centre":      {"color": "#4FC3F7", "fillColor": "#4FC3F7", "fillOpacity": 0.3, "weight": 1},
}

LEGEND = {
    "Park":           "#1D9E75",
    "Garten":         "#2ECC71",
    "Rasenfläche":    "#72CEB0",
    "Freizeitgelände":"#EF9F27",
    "Spielplatz":     "#F7D070",
    "Sportstätte":    "#4FC3F7",
}

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
