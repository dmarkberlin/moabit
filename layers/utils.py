import json
from shapely.geometry import shape


def load_boundary(path="data/moabit_boundary.geojson"):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return shape(data["geometry"] if data.get("type") == "Feature" else data)
