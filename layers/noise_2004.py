"""Road traffic noise 2004 (Umweltatlas Berlin), kept for comparison with 2022.

Source: Senatsverwaltung für Stadtentwicklung, Umweltatlas Berlin 2004 —
WMS/WFS `ua_laerm_2004` on gdi.berlin.de.

2004 rates each street *section* by its average level at the building line,
for day (6–22 h) and night (22–6 h). 2022 rates every building *façade* by
L_DEN / L_N. The two are therefore only roughly comparable; see the captions
in the app.

Clipped to the Moabit boundary (like the 2022 data) and precomputed into
data/noise_2004.json (committed). Regenerate with:

    python -m layers.noise_2004
"""
import json
import os
import re
import statistics
from collections import defaultdict

import requests
from shapely.geometry import shape

from layers.noise import DB_BANDS, _band
from layers.utils import load_boundary

CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "noise_2004.json")

WMS_URL = "https://gdi.berlin.de/services/wms/ua_laerm_2004"
_WFS = "https://gdi.berlin.de/services/wfs/ua_laerm_2004"
_BBOX = "13.3110,52.5165,13.3720,52.5420,CRS:84"

# WMS layer per (source, period). Rail is drawn on both sides of the track.
WMS_LAYERS = {
    ("Straße",  "Tag"):   "a_strlaerm_tag",
    ("Straße",  "Nacht"): "b_strlaerm_nacht",
    ("Schiene", "Tag"):   "ca_laerm_schiene_tag_links,cb_laerm_schiene_tag_rechts",
    ("Schiene", "Nacht"): "da_schienlaerm_nachts_links,db_schienlaerm_nachts_rechts",
}

# Colours of the official 2004 legend (sampled from images/noise_legend_*.png).
LEGEND = [
    ("≤ 55",  "#009933"), ("55–60", "#66CC33"), ("60–65", "#CCFF99"),
    ("65–70", "#FF9900"), ("70–75", "#CC6600"), ("75–80", "#CC0033"),
]
LEGEND_UNRATED_COLOUR = "#999999"

# A street needs this many rated sections to be ranked.
_MIN_SECTIONS = 5


def normalise_street(name):
    """'Turmstr.' -> 'Turmstraße', 'Perleberger Str.' -> 'Perleberger Straße'
    (2004 abbreviates; the 2022 street network spells names out)."""
    name = (name or "").strip()
    name = re.sub(r"(?<=\w)str\.$", "straße", name)
    name = re.sub(r"\bStr\.$", "Straße", name)
    return name


def _fetch(typename, field):
    r = requests.get(_WFS, params={
        "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
        "TYPENAMES": f"ua_laerm_2004:{typename}", "OUTPUTFORMAT": "application/json",
        "SRSNAME": "EPSG:4326", "BBOX": _BBOX,
    }, timeout=60)
    r.raise_for_status()
    boundary = load_boundary()
    out = []
    for f in r.json().get("features", []):
        value = f["properties"].get(field)
        if value is None or not f.get("geometry"):
            continue
        if not boundary.intersects(shape(f["geometry"])):
            continue
        out.append((normalise_street(f["properties"].get("strassenname")), value))
    return out


def _compute():
    day = _fetch("a_strlaerm_tag", "gesamtmittelpegel_tag2004")
    night = _fetch("b_strlaerm_nacht", "gesamtmittelpegel_nacht2004")
    if not day or not night:
        raise RuntimeError("No 2004 noise sections returned for Moabit")

    day_vals = [v for _, v in day]
    night_vals = [v for _, v in night]

    def pct(vals, limit):
        return round(sum(v >= limit for v in vals) / len(vals) * 100, 1)

    metrics = {
        "n_sections":     len(day_vals),
        "median_day":     round(statistics.median(day_vals), 1),
        "median_night":   round(statistics.median(night_vals), 1),
        # Same thresholds as the 2022 section, applied to the 2004 day/night
        # levels for orientation only (2004 has no L_DEN).
        "over65_day_pct":   pct(day_vals, 65),
        "over55_night_pct": pct(night_vals, 55),
    }

    dist = {"day": {b: 0 for b in DB_BANDS}, "night": {b: 0 for b in DB_BANDS}}
    for v in day_vals:
        dist["day"][_band(v)] += 1
    for v in night_vals:
        dist["night"][_band(v)] += 1

    by_street = defaultdict(list)
    for name, value in day:
        if name:
            by_street[name].append(value)
    streets = sorted(
        ({"street": s, "day": round(statistics.median(v), 1), "sections": len(v)}
         for s, v in by_street.items() if len(v) >= _MIN_SECTIONS),
        key=lambda r: r["day"], reverse=True,
    )
    return {"metrics": metrics, "dist": dist, "streets": streets}


def fetch_noise_2004():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return _compute()


def precompute():
    data = _compute()
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Wrote {CACHE_PATH}: {data['metrics']['n_sections']} sections, "
          f"{len(data['streets'])} ranked streets")


if __name__ == "__main__":
    precompute()
