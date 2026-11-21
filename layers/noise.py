"""Strategic noise maps 2022 (EU Environmental Noise Directive), Umweltatlas Berlin.

Source: Senatsverwaltung für Mobilität, Verkehr, Klimaschutz und Umwelt,
Strategische Lärmkarten 2022 — WMS/WFS `ua_stratlaerm_2022` on gdi.berlin.de.

The Umwelt tab statistics come from the façade measurement points
(`aa_fp_gesamt2022`): one point per building façade, each carrying L_DEN and
L_N per source. They are precomputed into data/noise_2022.json (committed), so
the deployed app never queries the WFS. Regenerate with:

    python -m layers.noise
"""
import json
import math
import os
import statistics
from collections import defaultdict

import requests
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

from layers.utils import load_boundary

CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "noise_2022.json")

WMS_URL = "https://gdi.berlin.de/services/wms/ua_stratlaerm_2022"
_WFS_NOISE = "https://gdi.berlin.de/services/wfs/ua_stratlaerm_2022"
_WFS_STREETS = "https://gdi.berlin.de/services/wfs/detailnetz"
_BBOX = "13.3110,52.5165,13.3720,52.5420,CRS:84"

# WMS layer per (source, period) for the map overlay.
WMS_LAYERS = {
    ("Gesamt",          "24 h"):  "bf_gesamtlaerm_den2022",
    ("Gesamt",          "Nacht"): "cf_gesamtlaerm_n2022",
    ("Straße",          "24 h"):  "bb_strasse_gesamt_den2022",
    ("Straße",          "Nacht"): "cb_strasse_gesamt_n2022",
    ("Tram & U-Bahn",   "24 h"):  "bc_tram_ubahn_den2022",
    ("Tram & U-Bahn",   "Nacht"): "cc_tram_ubahn_n2022",
}

# Official legend colours of the 2022 maps (sampled from the service's
# GetLegendGraphic), so the sidebar legend matches the overlay exactly.
# These are the map's own semantic scale, not the dashboard palette.
LEGEND = {
    "24 h": [
        ("< 55",  "#FFFFFF"), ("55–59", "#E2F2BF"), ("60–64", "#F3C683"),
        ("65–69", "#CD463E"), ("70–74", "#75085C"), ("≥ 75",  "#430A4A"),
    ],
    "Nacht": [
        ("< 45",  "#FFFFFF"), ("45–49", "#A0BABF"), ("50–54", "#B8D6D1"),
        ("55–59", "#E2F2BF"), ("60–64", "#F3C683"), ("65–69", "#CD463E"),
        ("≥ 70",  "#75085C"),
    ],
}

_DEN_EDGES = [55, 60, 65, 70, 75]
_N_EDGES = [45, 50, 55, 60, 65, 70]


def sld_body(layer):
    """Per-request style that reproduces the official classes exactly but leaves
    the quietest class transparent.

    The service's only style paints "< 55" (L_DEN) / "< 45" (L_N) near-opaque
    white, which on this app's dark basemap would veil roughly half the map.
    The official classes are drawn on rounded values, hence the -0.5 offsets;
    with them, every coloured pixel matches the official tile exactly.
    """
    period = "24 h" if "_den" in layer else "Nacht"
    edges = _DEN_EDGES if period == "24 h" else _N_EDGES
    colours = [c for _, c in LEGEND[period]]
    quantities = [e - 0.5 for e in edges] + [200]
    entries = [(colours[0], quantities[0], 0)] + [
        (c, q, 1) for c, q in zip(colours[1:], quantities[1:])
    ]
    colour_map = "".join(
        f'<ColorMapEntry color="{c}" quantity="{q}" opacity="{o}"/>' for c, q, o in entries
    )
    return (
        '<StyledLayerDescriptor version="1.0.0" xmlns="http://www.opengis.net/sld">'
        f"<NamedLayer><Name>ua_stratlaerm_2022:{layer}</Name><UserStyle>"
        "<FeatureTypeStyle><Rule><RasterSymbolizer>"
        f'<ColorMap type="intervals">{colour_map}</ColorMap>'
        "</RasterSymbolizer></Rule></FeatureTypeStyle></UserStyle></NamedLayer>"
        "</StyledLayerDescriptor>"
    )


# Lärmaktionsplan Berlin 2024–2029: trigger values (Auslösewerte) and the
# level above which health risk is assumed and action is prioritised.
THRESHOLDS = {
    "trigger": {"den": 65, "n": 55},
    "health":  {"den": 70, "n": 60},
}

DB_BANDS = ["< 45", "45–49", "50–54", "55–59", "60–64", "65–69", "70–74", "≥ 75"]

# A façade point is attributed to a street only if it lies this close to it;
# beyond that it is most likely a rear or courtyard façade.
_STREET_MAX_DIST_M = 20
_STREET_MIN_POINTS = 15
_TOP_N = 10


def _band(db):
    if db < 45:
        return "< 45"
    if db >= 75:
        return "≥ 75"
    lo = int(db // 5 * 5)
    return f"{lo}–{lo + 4}"


def _wfs_all(url, typename, page=10000):
    """Fetch every feature of a WFS layer inside the Moabit bbox, paged."""
    features, start = [], 0
    while True:
        r = requests.get(url, params={
            "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
            "TYPENAMES": typename, "OUTPUTFORMAT": "application/json",
            "SRSNAME": "EPSG:4326", "BBOX": _BBOX,
            "COUNT": page, "STARTINDEX": start,
        }, timeout=120)
        r.raise_for_status()
        batch = r.json().get("features", [])
        features.extend(batch)
        if len(batch) < page:
            return features
        start += page


def _to_metres(lon, lat, lat0=52.53):
    """Local equirectangular projection — accurate to well under 1 % across
    Moabit, and avoids a pyproj dependency for a nearest-street join."""
    k = 111_320
    return lon * k * math.cos(math.radians(lat0)), lat * 110_574


def _compute():
    boundary = load_boundary()

    points = []
    for f in _wfs_all(_WFS_NOISE, "ua_stratlaerm_2022:aa_fp_gesamt2022"):
        lon, lat = f["geometry"]["coordinates"][:2]
        p = f["properties"]
        if p.get("ges_den") is None or p.get("ges_n") is None:
            continue
        if not boundary.contains(Point(lon, lat)):
            continue
        points.append((lon, lat, p))

    if not points:
        raise RuntimeError("No façade points returned for Moabit")

    den = [p["ges_den"] for _, _, p in points]
    n   = [p["ges_n"]   for _, _, p in points]
    t, h = THRESHOLDS["trigger"], THRESHOLDS["health"]

    def pct(vals, limit):
        return round(sum(v >= limit for v in vals) / len(vals) * 100, 1)

    metrics = {
        "n_points":         len(points),
        "median_den":       round(statistics.median(den), 1),
        "median_n":         round(statistics.median(n), 1),
        "trigger_den_pct":  pct(den, t["den"]),
        "trigger_n_pct":    pct(n,   t["n"]),
        "health_den_pct":   pct(den, h["den"]),
        "health_n_pct":     pct(n,   h["n"]),
    }

    dist = {"den": {b: 0 for b in DB_BANDS}, "n": {b: 0 for b in DB_BANDS}}
    for v in den:
        dist["den"][_band(v)] += 1
    for v in n:
        dist["n"][_band(v)] += 1

    # Loudest streets: road noise (str_den) of street-facing façades, joined
    # to the nearest named segment of the Berlin street network.
    segments, names = [], []
    for f in _wfs_all(_WFS_STREETS, "detailnetz:c_strassenabschnitte"):
        name = f["properties"].get("strassenname")
        geom = f.get("geometry") or {}
        if not name or geom.get("type") != "LineString":
            continue
        line = LineString(geom["coordinates"])
        if not boundary.intersects(line):
            continue
        segments.append(LineString([_to_metres(x, y) for x, y in geom["coordinates"]]))
        names.append(name)

    tree = STRtree(segments)
    by_street = defaultdict(list)
    for lon, lat, p in points:
        if p.get("str_den") is None:
            continue
        pt = Point(_to_metres(lon, lat))
        idx = tree.nearest(pt)
        if segments[idx].distance(pt) <= _STREET_MAX_DIST_M:
            by_street[names[idx]].append(p["str_den"])

    top = sorted(
        ((s, round(statistics.median(v), 1), len(v))
         for s, v in by_street.items() if len(v) >= _STREET_MIN_POINTS),
        key=lambda r: r[1], reverse=True,
    )[:_TOP_N]

    return {
        "metrics": metrics,
        "dist": dist,
        "top": [{"street": s, "den": d, "points": c} for s, d, c in top],
    }


def fetch_noise_data():
    """Precomputed 2022 façade-level summary for Moabit (see precompute())."""
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return _compute()


def precompute():
    data = _compute()
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Wrote {CACHE_PATH}: {data['metrics']['n_points']} façade points, "
          f"{len(data['top'])} streets")


if __name__ == "__main__":
    precompute()
