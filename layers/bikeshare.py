import requests
from shapely.geometry import Point
from layers.utils import load_boundary

GBFS_INFO   = "https://gbfs.nextbike.net/maps/gbfs/v2/nextbike_bn/en/station_information.json"
GBFS_STATUS = "https://gbfs.nextbike.net/maps/gbfs/v2/nextbike_bn/en/station_status.json"


def _availability_colour(num_bikes):
    if num_bikes == 0:
        return "red"
    if num_bikes <= 2:
        return "orange"
    return "green"


def fetch_bikeshare_stations():
    info_r   = requests.get(GBFS_INFO,   timeout=15)
    status_r = requests.get(GBFS_STATUS, timeout=15)
    info_r.raise_for_status()
    status_r.raise_for_status()

    stations = {
        s["station_id"]: s
        for s in info_r.json()["data"]["stations"]
        if not s.get("is_virtual_station", False)
    }
    status = {
        s["station_id"]: s
        for s in status_r.json()["data"]["stations"]
    }

    boundary = load_boundary()
    result = []
    for sid, info in stations.items():
        lat, lon = info["lat"], info["lon"]
        if not boundary.contains(Point(lon, lat)):
            continue
        st = status.get(sid, {})
        if not st.get("is_installed", True) or not st.get("is_renting", True):
            continue
        bikes = st.get("num_bikes_available", 0)
        docks = st.get("num_docks_available", 0)
        result.append({
            "id":       sid,
            "name":     info["name"],
            "lat":      lat,
            "lon":      lon,
            "capacity": info.get("capacity", 0),
            "bikes":    bikes,
            "docks":    docks,
            "colour":   _availability_colour(bikes),
        })
    return result
