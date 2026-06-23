import csv
import io
import json
import os
import re
import zipfile
import requests
from shapely.geometry import Point
from layers.utils import load_boundary

CACHE_PATH = "data/transport_stops.json"
GTFS_PATH  = "data/GTFS.zip"
GTFS_URL   = "https://www.vbb.de/fileadmin/user_upload/VBB/Dokumente/API-Datensaetze/gtfs-mastscharf/GTFS.zip"
BBOX       = (52.5165, 52.5420, 13.3110, 13.3720)


def _vbb_id(gtfs_id):
    """'de:11000:900002201' or 'de:11000:900003102::1' → '900002201'"""
    m = re.search(r':(\d+)(?:::|$)', gtfs_id)
    return m.group(1) if m else gtfs_id


def _stop_type(name):
    if name.startswith(("S+U ", "U+S ", "U ")):
        return "subway"
    if name.startswith("S "):
        return "suburban"
    if "Tram" in name:
        return "tram"
    return "bus"


def stop_style(stop):
    t = stop.get("type", "bus")
    if t in ("subway", "suburban"):
        return {"color": "red", "icon": "train"}
    if t == "tram":
        return {"color": "orange", "icon": "train"}
    return {"color": "green", "icon": "bus"}


def _download_gtfs():
    tmp = GTFS_PATH + ".tmp"
    r = requests.get(
        GTFS_URL,
        headers={"User-Agent": "Mozilla/5.0"},
        stream=True,
        timeout=120,
    )
    r.raise_for_status()
    with open(tmp, "wb") as f:
        for chunk in r.iter_content(65536):
            f.write(chunk)
    os.replace(tmp, GTFS_PATH)


def _parse_stops():
    with zipfile.ZipFile(GTFS_PATH) as z:
        with z.open("stops.txt") as f:
            rows = list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8")))

    boundary = load_boundary()
    seen_ids = {}  # vbb_id → stop dict; type=1 wins over type=0

    for r in rows:
        if not r.get("stop_lat") or not r.get("stop_lon"):
            continue
        lat = float(r["stop_lat"])
        lon = float(r["stop_lon"])
        if not (BBOX[0] <= lat <= BBOX[1] and BBOX[2] <= lon <= BBOX[3]):
            continue
        loc_type = r.get("location_type", "0")
        is_station    = loc_type == "1"
        is_standalone = loc_type == "0" and not r.get("parent_station")
        if not is_station and not is_standalone:
            continue
        if not boundary.contains(Point(lon, lat)):
            continue

        vid = _vbb_id(r["stop_id"])
        stop = {
            "id":   vid,
            "name": r["stop_name"],
            "lat":  lat,
            "lon":  lon,
            "type": _stop_type(r["stop_name"]),
        }
        # Prefer type=1 entries when the same base ID appears as both
        if vid not in seen_ids or is_station:
            seen_ids[vid] = stop

    return list(seen_ids.values())


def fetch_stops():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)

    if not os.path.exists(GTFS_PATH):
        _download_gtfs()

    stops = _parse_stops()
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(stops, f)
    return stops
