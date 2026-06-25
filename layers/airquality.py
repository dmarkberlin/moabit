import requests
import pandas as pd
from datetime import date, timedelta

_BASE = "https://www.umweltbundesamt.de/api/air_data/v3/measures/json"

# Berlin Wedding (DEBE010) — nearest active station to Moabit with full component coverage
STATION_ID   = "121"
STATION_NAME = "Berlin Wedding"
STATION_LAT  = 52.543
STATION_LON  = 13.3493

# Moabit stations — location only, no live data in UBA API
MOABIT_STATIONS = [
    {"name": "Berlin Stromstraße",  "lat": 52.5272, "lon": 13.3431},
    {"name": "Berlin Birkenstraße", "lat": 52.5315, "lon": 13.3443},
]

COMPONENTS = {
    "5": ("NO₂",   "µg/m³", "#E53935"),
    "1": ("PM₁₀",  "µg/m³", "#FB8C00"),
    "9": ("PM₂,₅", "µg/m³", "#8E24AA"),
    "3": ("O₃",    "µg/m³", "#1E88E5"),
}

# EU/WHO limit values (µg/m³, annual / hourly where applicable)
LIMITS = {
    "NO₂":   40,
    "PM₁₀":  50,   # daily limit
    "PM₂,₅": 25,   # annual
    "O₃":    120,  # 8-hour max
}

# UBA index → German label and colour
INDEX_LABELS = {
    "0": ("sehr gut",         "#43A047"),
    "1": ("sehr gut",         "#43A047"),
    "2": ("gut",              "#7CB342"),
    "3": ("mäßig",            "#FDD835"),
    "4": ("schlecht",         "#FB8C00"),
    "5": ("sehr schlecht",    "#E53935"),
    "6": ("äußerst schlecht", "#B71C1C"),
}


def _fetch(component_id, scope, days=1):
    today    = date.today()
    date_from = (today - timedelta(days=days)).isoformat()
    r = requests.get(_BASE, params={
        "date_from": date_from,
        "time_from": 1,
        "date_to":   today.isoformat(),
        "time_to":   24,
        "station":   STATION_ID,
        "component": component_id,
        "scope":     scope,
    }, timeout=15)
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
        result[label] = {
            "value":  vals[2],
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
            rows = [{"date": dt[:10], label: vals[2]} for dt, vals in entries.items()]
        else:
            entries = _fetch(comp_id, scope=2, days=days)
            if not entries:
                continue
            rows = [{"date": dt[:10], label: vals[2]} for dt, vals in entries.items()]
            df_hourly = pd.DataFrame(rows)
            df_hourly[label] = pd.to_numeric(df_hourly[label], errors="coerce")
            df_hourly = df_hourly.groupby("date")[label].mean().round(1).reset_index()
            rows = df_hourly.to_dict("records")
        df = pd.DataFrame(rows).drop_duplicates("date").sort_values("date")
        frames.append(df.set_index("date"))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, axis=1).reset_index()
