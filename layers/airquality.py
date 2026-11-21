import time

import requests
import pandas as pd
from datetime import date, timedelta

# The UBA moved its air-data API to this host (the old
# www.umweltbundesamt.de/api/air_data/... address now only redirects here).
_BASE = "https://luftdaten.umweltbundesamt.de/api/air-data/v3/measures/json"

# The new host intermittently answers 410 Gone (and the odd 5xx) for requests
# that succeed moments later, so transient failures are retried briefly.
_RETRY_STATUS = {410, 429, 500, 502, 503, 504}
_RETRIES = 2
_RETRY_DELAY_S = 1.5

# Berlin Wedding (DEBE010) — nearest active station to Moabit with full component coverage
STATION_ID   = "121"
STATION_NAME = "Berlin Wedding"
STATION_LAT  = 52.543
STATION_LON  = 13.3493

# Nearby stations — location only, no data available via public API
MOABIT_STATIONS = [
    {"name": "Berlin Alt-Moabit",   "lat": 52.5239, "lon": 13.3288, "active": False, "years": "2007–"},
    {"name": "Berlin Stromstraße",  "lat": 52.5272, "lon": 13.3431, "active": False, "years": "2019–2022"},
    {"name": "Berlin Birkenstraße", "lat": 52.5315, "lon": 13.3443, "active": False, "years": "2019–2020"},
]

COMPONENTS = {
    "5": ("NO₂",   "µg/m³", "#C0504D"),
    "1": ("PM₁₀",  "µg/m³", "#FB8C00"),
    "9": ("PM₂,₅", "µg/m³", "#8E24AA"),
    "3": ("O₃",    "µg/m³", "#1E88E5"),
}

# Single source of truth for pollutant colours, consumed by the Umwelt charts in
# app.py so a pollutant is never two different colours.
COMPONENT_COLOURS = {label: colour for label, _unit, colour in COMPONENTS.values()}

# EU/WHO limit values (µg/m³, annual / hourly where applicable)
LIMITS = {
    "NO₂":   40,
    "PM₁₀":  50,   # daily limit
    "PM₂,₅": 25,   # annual
    "O₃":    120,  # 8-hour max
}

# UBA index → German label and colour.
# Ordered severity ramp drawn from the dashboard's Material palette. The final
# step (#7B2E2C) is a deliberately darkened shade of the standard red #C0504D —
# the palette has no "worse than red" step of its own.
INDEX_LABELS = {
    "0": ("sehr gut",         "#43A047"),
    "1": ("sehr gut",         "#43A047"),
    "2": ("gut",              "#7CB342"),
    "3": ("mäßig",            "#FFB300"),
    "4": ("schlecht",         "#FB8C00"),
    "5": ("sehr schlecht",    "#C0504D"),
    "6": ("äußerst schlecht", "#7B2E2C"),
}


def _to_num(v):
    """Coerce an API value to int/float, or None if it is not numeric.

    The UBA endpoint is inconsistent about returning numbers vs numeric strings;
    callers do arithmetic against the EU limits, so coerce once at the source.
    """
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return int(n) if n == int(n) else n


def _fetch(component_id, scope, days=1):
    today    = date.today()
    date_from = (today - timedelta(days=days)).isoformat()
    params = {
        "date_from": date_from,
        "time_from": 1,
        "date_to":   today.isoformat(),
        "time_to":   24,
        "station":   STATION_ID,
        "component": component_id,
        "scope":     scope,
    }
    for attempt in range(_RETRIES + 1):
        try:
            r = requests.get(_BASE, params=params, timeout=15)
        except (requests.ConnectionError, requests.Timeout):
            if attempt == _RETRIES:
                raise
        else:
            if r.status_code not in _RETRY_STATUS or attempt == _RETRIES:
                break
        time.sleep(_RETRY_DELAY_S)
    r.raise_for_status()
    return r.json().get("data", {}).get(STATION_ID, {})


def fetch_current():
    """Return the latest hourly reading for each component."""
    result = {}
    for comp_id, (label, unit, colour) in COMPONENTS.items():
        entries = _fetch(comp_id, scope=2, days=2)
        if not entries:
            continue
        _, vals = sorted(entries.items())[-1]
        value = _to_num(vals[2])
        if value is None:
            continue
        result[label] = {
            "value":  value,
            "unit":   unit,
            "colour": colour,
            "index":  vals[4],
        }
    return result


def fetch_history(days=365):
    """Return a DataFrame of daily average values per component."""
    frames = []
    for comp_id, (label, unit, colour) in COMPONENTS.items():
        # Try pre-computed daily averages first; fall back to aggregating hourly
        entries = _fetch(comp_id, scope=1, days=days)
        if entries:
            rows = [{"date": dt[:10], label: _to_num(vals[2])} for dt, vals in entries.items()]
        else:
            entries = _fetch(comp_id, scope=2, days=days)
            if not entries:
                continue
            rows = [{"date": dt[:10], label: _to_num(vals[2])} for dt, vals in entries.items()]
            df_hourly = pd.DataFrame(rows)
            df_hourly[label] = pd.to_numeric(df_hourly[label], errors="coerce")
            df_hourly = df_hourly.groupby("date")[label].mean().round(1).reset_index()
            rows = df_hourly.to_dict("records")
        df = pd.DataFrame(rows).drop_duplicates("date").sort_values("date")
        frames.append(df.set_index("date"))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, axis=1).reset_index()
