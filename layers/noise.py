import math
import requests
import pandas as pd
from collections import defaultdict

_WFS = "https://gdi.berlin.de/services/wfs/ua_laerm_2004"

# Moabit bounding box in EPSG:3857
def _to_3857(lon, lat):
    x = lon * 20037508.34 / 180
    y = math.log(math.tan((90 + lat) * math.pi / 360)) / (math.pi / 180) * 20037508.34 / 180
    return x, y

_X1, _Y1 = _to_3857(13.31, 52.51)
_X2, _Y2 = _to_3857(13.38, 52.55)
_BBOX = f"{_X1:.0f},{_Y1:.0f},{_X2:.0f},{_Y2:.0f},EPSG:3857"

# EU Environmental Noise Directive thresholds (dB)
THRESHOLDS = {"Tag": 55, "Nacht": 50}

DB_BANDS = ["< 55", "55–64", "65–74", "≥ 75"]

def _band(db):
    if db < 55:  return "< 55"
    if db < 65:  return "55–64"
    if db < 75:  return "65–74"
    return "≥ 75"


def _fetch_layer(typename, field):
    r = requests.get(_WFS, params={
        "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
        "TYPENAMES": f"ua_laerm_2004:{typename}",
        "BBOX": _BBOX,
        "OUTPUTFORMAT": "application/json",
    }, timeout=20)
    r.raise_for_status()
    features = r.json().get("features", [])
    return [
        (f["properties"].get("strassenname", ""), f["properties"][field])
        for f in features
        if f["properties"].get(field) is not None
    ]


def fetch_noise_data():
    """Return dict with distribution and top-streets DataFrames for road noise."""
    road_day   = _fetch_layer("a_strlaerm_tag",   "gesamtmittelpegel_tag2004")
    road_night = _fetch_layer("b_strlaerm_nacht",  "gesamtmittelpegel_nacht2004")

    day_vals   = [v for _, v in road_day]
    night_vals = [v for _, v in road_night]

    # dB band distribution
    day_bands   = {b: 0 for b in DB_BANDS}
    night_bands = {b: 0 for b in DB_BANDS}
    for v in day_vals:   day_bands[_band(v)]   += 1
    for v in night_vals: night_bands[_band(v)] += 1

    dist_df = pd.DataFrame({
        "Band":  DB_BANDS,
        "Tag":   [day_bands[b]   for b in DB_BANDS],
        "Nacht": [night_bands[b] for b in DB_BANDS],
    })

    # Top streets by average daytime dB
    street_vals = defaultdict(list)
    for name, val in road_day:
        if name:
            street_vals[name].append(val)
    top_streets = sorted(
        {k: sum(v) / len(v) for k, v in street_vals.items()}.items(),
        key=lambda x: x[1], reverse=True
    )[:10]
    top_df = pd.DataFrame(top_streets, columns=["Straße", "dB (Tag)"])

    # Summary metrics
    n = len(day_vals)
    if n == 0:
        return None
    above_day   = sum(1 for v in day_vals   if v > THRESHOLDS["Tag"])
    above_night = sum(1 for v in night_vals if v > THRESHOLDS["Nacht"])

    metrics = {
        "n_segments":        n,
        "median_day":        round(sorted(day_vals)[n // 2], 1),
        "median_night":      round(sorted(night_vals)[n // 2], 1),
        "above_day_pct":     round(above_day   / n * 100, 1),
        "above_night_pct":   round(above_night / n * 100, 1),
    }

    return {"dist": dist_df, "top": top_df, "metrics": metrics}
