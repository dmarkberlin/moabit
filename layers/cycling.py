import json
import os
from layers.overpass import overpass_post
CACHE_PATH = "data/cycle_lanes.json"
BBOX = "(52.5165,13.3110,52.5420,13.3720)"

QUERY = f"""
[out:json][timeout:25];
(
  way["highway"="cycleway"]{BBOX};
  way["cycleway"~"lane|track|opposite_lane"]{BBOX};
  way["bicycle"="designated"]{BBOX};
);
out geom;
"""

LEGEND = {
    "Fahrradweg":       "#4FC3F7",
    "Radfahrstreifen":  "#FFF176",
    "Sonstige":         "#CE93D8",
}

def lane_style(tags):
    highway = tags.get("highway", "")
    cycleway = tags.get("cycleway", "")
    if highway == "cycleway":
        return "#4FC3F7"   # light blue — dedicated path
    if "lane" in cycleway:
        return "#FFF176"   # yellow — painted lane
    return "#CE93D8"       # purple — other

def fetch_cycle_lanes():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    response = overpass_post(QUERY, timeout=30)
    response.raise_for_status()
    elements = response.json()["elements"]
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(elements, f)
    return elements
