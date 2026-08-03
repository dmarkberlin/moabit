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

# Dashboard Material palette. "other" is deliberately NOT purple: bus routes are
# BVG purple (#A5027D) and the two layers are commonly shown together. Pink is
# adjacent in hue but 37 points lighter, so the two stay easy to tell apart on
# the dark basemap.
_LANE_COLOURS = {
    "dedicated": "#039BE5",  # blue   — dedicated cycle path
    "lane":      "#FECB52",  # yellow — painted lane
    "other":     "#FF6692",  # pink   — everything else
}

LEGEND = {
    "Fahrradweg":      _LANE_COLOURS["dedicated"],
    "Radfahrstreifen": _LANE_COLOURS["lane"],
    "Sonstige":        _LANE_COLOURS["other"],
}

def lane_style(tags):
    if tags.get("highway", "") == "cycleway":
        return _LANE_COLOURS["dedicated"]
    if "lane" in tags.get("cycleway", ""):
        return _LANE_COLOURS["lane"]
    return _LANE_COLOURS["other"]

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
