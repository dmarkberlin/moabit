import json
import os
from shapely.geometry import shape, LineString, MultiLineString
from layers.overpass import overpass_post
from layers.utils import load_boundary
CACHE_PATH      = "data/routes.json"
FULL_CACHE_PATH = "data/routes_full.json"
BBOX            = "(52.5165,13.3110,52.5420,13.3720)"

QUERY = f"""
[out:json][timeout:60];
(
  relation["route"="bus"]{BBOX};
  relation["route"="tram"]{BBOX};
  relation["route"="subway"]{BBOX};
  relation["route"="light_rail"]{BBOX};
);
out geom;
"""


ROUTE_STYLE = {
    "bus":        {"colour": "#A020F0", "weight": 2, "opacity": 0.7},
    "tram":       {"colour": "#CC0000", "weight": 3, "opacity": 0.8},
    "subway":     {"colour": "#0A4B9A", "weight": 3, "opacity": 0.8},
    "light_rail": {"colour": "#006E35", "weight": 3, "opacity": 0.8},
}

LEGEND = {
    "Bus":    "#A020F0",
    "Tram":   "#CC0000",
    "U-Bahn": "#0A4B9A",
    "S-Bahn": "#006E35",
}

def _relation_to_features(el):
    """
    Extract route line segments from a relation's member ways.
    Returns a list of GeoJSON LineString features.
    """
    tags = el.get("tags", {})
    route_type = tags.get("route", "bus")
    ref = tags.get("ref", "")
    name = tags.get("name", "")
    style = ROUTE_STYLE.get(route_type, ROUTE_STYLE["bus"])
    features = []
    for member in el.get("members", []):
        # Only use way members with route role (empty string or "route")
        if member["type"] != "way":
            continue
        if member.get("role") in ("stop", "platform", "stop_exit_only", "stop_entry_only"):
            continue
        geometry = member.get("geometry", [])
        if len(geometry) < 2:
            continue
        coords = [[g["lon"], g["lat"]] for g in geometry]
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {
                "route":   route_type,
                "ref":     ref,
                "name":    name,
                "colour":  style["colour"],
                "weight":  style["weight"],
                "opacity": style["opacity"],
            }
        })
    return features

def _deduplicated_elements(elements):
    """Yield one element per (route, ref) pair — drops duplicate directions."""
    seen = set()
    for el in elements:
        tags = el.get("tags", {})
        key = (tags.get("route", ""), tags.get("ref", ""))
        if key in seen:
            continue
        seen.add(key)
        yield el


def fetch_routes():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)

    response = overpass_post(QUERY, timeout=60)
    response.raise_for_status()
    elements = response.json()["elements"]

    boundary = load_boundary()
    features = []
    for el in _deduplicated_elements(elements):
        for feature in _relation_to_features(el):
            try:
                line = shape(feature["geometry"])
                clipped = boundary.intersection(line)
                if clipped.is_empty:
                    continue
                if isinstance(clipped, LineString):
                    geoms = [clipped]
                elif isinstance(clipped, MultiLineString):
                    geoms = list(clipped.geoms)
                else:
                    continue
                for geom in geoms:
                    coords = list(geom.coords)
                    if len(coords) < 2:
                        continue
                    f = dict(feature)
                    f["geometry"] = {"type": "LineString", "coordinates": [[c[0], c[1]] for c in coords]}
                    features.append(f)
            except Exception:
                continue

    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(features, f)
    return features


def fetch_routes_full():
    if os.path.exists(FULL_CACHE_PATH):
        with open(FULL_CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)

    # Reuse the same bbox query — out geom already returns full member geometry,
    # not just the bbox-intersecting portion. We just skip the shapely clip.
    response = overpass_post(QUERY, timeout=60)
    response.raise_for_status()
    elements = response.json()["elements"]

    features = []
    for el in _deduplicated_elements(elements):
        features.extend(_relation_to_features(el))

    with open(FULL_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(features, f)
    return features
