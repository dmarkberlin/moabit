"""Berlin tree register (Baumbestand), street and park trees in Moabit.

Source: Senatsverwaltung für Mobilität, Verkehr, Klimaschutz und Umwelt —
Baumbestand Berlin (GRIS tree register), WFS `baumbestand` on gdi.berlin.de,
Datenlizenz Deutschland – Zero – 2.0.

Precomputed into data/trees.json (committed), so the deployed app never
queries the WFS. Regenerate with:

    python -m layers.trees
"""
import json
import os

import requests
from shapely.geometry import Point

from layers.utils import load_boundary

CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "trees.json")

_WFS = "https://gdi.berlin.de/services/wfs/baumbestand"
_BBOX = "13.3110,52.5165,13.3720,52.5420,CRS:84"

# Two shades of the dashboard's green so street and park trees are
# distinguishable on the dark basemap by lightness.
TREE_TYPES = {
    "strasse": {"layer": "baumbestand:strassenbaeume", "label": "Straßenbaum", "colour": "#43A047"},
    "anlage":  {"layer": "baumbestand:anlagenbaeume",  "label": "Anlagenbaum", "colour": "#B6E880"},
}

# Row layout in the cache — compact arrays rather than dicts, since the whole
# list is embedded in the map page.
FIELDS = ["lat", "lon", "type", "species", "botanical", "year", "height",
          "trunk", "crown", "street", "number"]

# British English common names for the register's German species names, used by
# the English version of the app. Covers the species common in Moabit (the
# top ~45 by count, plus the oldest trees); anything else falls back to the
# German name, and the botanical name is always shown alongside.
SPECIES_EN = {
    "Spitz-Ahorn": "Norway maple",
    "Winter-Linde": "Small-leaved lime",
    "Ahornblättrige Platane": "London plane",
    "Gemeine Rosskastanie": "Horse chestnut",
    "Berg-Ahorn, Weiss-Ahorn": "Sycamore",
    "Feld-Ahorn": "Field maple",
    "Holländische Linde": "Common lime",
    "Baum-Hasel": "Turkish hazel",
    "Pyramiden-Hainbuche": "Fastigiate hornbeam",
    "Robinie": "Black locust",
    "Sommer-Eiche, Stiel-Eiche": "English oak",
    "Sommer-Linde": "Large-leaved lime",
    "Sand-Birke": "Silver birch",
    "Sumpf-Eiche": "Pin oak",
    "Amerikanische Rot-Eiche": "Northern red oak",
    "Hainbuche": "Hornbeam",
    "Resista Ulme 'Regal'": "Resista elm 'Regal'",
    "Italienische Pyramiden-Pappel": "Lombardy poplar",
    "Silber-Ahorn": "Silver maple",
    "Silber-Linde": "Silver lime",
    "Japanischer Schnurbaum": "Japanese pagoda tree",
    "Dreidorniger Lederhülsenbaum": "Honey locust",
    "Pyramiden-Eiche": "Cypress oak",
    "Birken-Pappel": "Simon's poplar",
    "Feldahorn 'Elsrijk'": "Field maple 'Elsrijk'",
    "Unbekannt": "Unknown",
    "Einblattakazie": "Black locust 'Unifoliola'",
    "Säulenförmiger Spitz-Ahorn": "Columnar Norway maple",
    "Zier-Feld-Ahorn 'Red Shine'": "Field maple 'Red Shine'",
    "Gewöhnliche Esche": "European ash",
    "Götterbaum": "Tree of heaven",
    "Echter Rotdorn": "Midland hawthorn 'Paul's Scarlet'",
    "Gold-Gleditschie": "Honey locust 'Sunburst'",
    "Süss-Kirsche,Vogel-Kirsche": "Wild cherry",
    "Fächerblattbaum": "Ginkgo",
    "Resista Ulme 'Fiorente'": "Resista elm 'Fiorente'",
    "Rotblühende Rosskastanie": "Red horse chestnut",
    "Amberbaum": "Sweetgum",
    "Säulen-Blumenesche": "Manna ash 'Obelisk'",
    "Rot-Buche": "Common beech",
    "Resista Ulme 'Rebona'": "Resista elm 'Rebona'",
    "Hybrid-Pappel": "Hybrid black poplar",
    "Purpur-Erle": "Späth's alder",
    "Trauben-Eiche": "Sessile oak",
    "Eisenholzbaum, Parrotie": "Persian ironwood",
    "Blutbuche": "Copper beech",
    "Berg-Ulme": "Wych elm",
    "Gemeine Eibe": "Common yew",
    "Stechpalme, Gemeine Hülse": "Holly",
}


def _num(v):
    """0 and empty mean 'not recorded' in this dataset."""
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return None
    return n or None


def _fetch(layer, page=10000):
    features, start = [], 0
    while True:
        r = requests.get(_WFS, params={
            "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
            "TYPENAMES": layer, "OUTPUTFORMAT": "application/json",
            "SRSNAME": "EPSG:4326", "BBOX": _BBOX,
            "COUNT": page, "STARTINDEX": start,
        }, timeout=120)
        r.raise_for_status()
        batch = r.json().get("features", [])
        features.extend(batch)
        if len(batch) < page:
            return features
        start += page


def _compute():
    boundary = load_boundary()
    rows = []
    for key, spec in TREE_TYPES.items():
        for f in _fetch(spec["layer"]):
            lon, lat = f["geometry"]["coordinates"][:2]
            if not boundary.contains(Point(lon, lat)):
                continue
            p = f["properties"]
            rows.append([
                round(lat, 6), round(lon, 6), key,
                p.get("art_dtsch") or p.get("gattung_deutsch") or "Baum",
                p.get("art_bot") or "",
                _num(p.get("pflanzjahr")),
                _num(p.get("baumhoehe")),
                _num(p.get("stammumfg")),
                _num(p.get("kronedurch")),
                p.get("strname") or "",
                p.get("hausnr") or "",
            ])
    if not rows:
        raise RuntimeError("No trees returned for Moabit")
    return rows


def fetch_trees():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)["rows"]
    return _compute()


def precompute():
    rows = _compute()
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump({"fields": FIELDS, "rows": rows}, f, ensure_ascii=False, separators=(",", ":"))
    by_type = {k: sum(r[2] == k for r in rows) for k in TREE_TYPES}
    print(f"Wrote {CACHE_PATH}: {len(rows)} trees {by_type}, "
          f"{os.path.getsize(CACHE_PATH) / 1e6:.2f} MB")


if __name__ == "__main__":
    precompute()
