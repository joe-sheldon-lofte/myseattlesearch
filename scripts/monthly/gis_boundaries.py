import os
import json
import math
import urllib.request
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")

def slugify(text):
    if not text: return ""
    text = str(text).lower().strip()
    out = [ch if ch.isalnum() else '-' for ch in text]
    res = "".join(out)
    while '--' in res: res = res.replace('--', '-')
    return res.strip('-')

def clean_city_name(name):
    if not name or not isinstance(name, str): return ""
    return name.lower().replace("city of ", "").replace("town of ", "").strip()

def perpendicular_distance(point, line_start, line_end):
    if line_start == line_end:
        return math.hypot(point[0] - line_start[0], point[1] - line_start[1])
    dx = line_end[0] - line_start[0]
    dy = line_end[1] - line_start[1]
    mag = math.hypot(dx, dy)
    if mag == 0.0: return 0.0
    u = ((point[0] - line_start[0]) * dx + (point[1] - line_start[1]) * dy) / (mag * mag)
    if u < 0.0 or u > 1.0:
        ix = line_start[0] if u < 0.0 else line_end[0]
        iy = line_start[1] if u < 0.0 else line_end[1]
    else:
        ix = line_start[0] + u * dx
        iy = line_start[1] + u * dy
    return math.hypot(point[0] - ix, point[1] - iy)

def rdp_simplify(points, epsilon=0.0008):
    if len(points) < 4: return points
    dmax, index, end = 0.0, 0, len(points) - 1
    for i in range(1, end):
        d = perpendicular_distance(points[i], points[0], points[end])
        if d > dmax: index, dmax = i, d
    if dmax > epsilon:
        rec1 = rdp_simplify(points[:index+1], epsilon)
        rec2 = rdp_simplify(points[index:], epsilon)
        return rec1[:-1] + rec2
    else:
        return [points[0], points[end]]

def simplify_geometry(geometry, epsilon=0.0008):
    g_type, coords = geometry.get("type"), geometry.get("coordinates", [])
    if g_type == "Polygon":
        return {"type": "Polygon", "coordinates": [rdp_simplify(ring, epsilon) for ring in coords]}
    elif g_type == "MultiPolygon":
        return {"type": "MultiPolygon", "coordinates": [[rdp_simplify(ring, epsilon) for ring in poly] for poly in coords]}
    return geometry

def main():
    print("🗺️ Ingesting & Simplifying WSDOT City Boundaries GIS...")
    if not os.path.exists(CITY_DATA_PATH):
        print("ℹ️ city_data.json missing. Skipping GIS boundaries.")
        return

    with open(CITY_DATA_PATH, "r", encoding="utf-8") as f:
        raw_cities = json.load(f)

    items = raw_cities if isinstance(raw_cities, list) else list(raw_cities.values())
    target_slugs = {clean_city_name(item.get("City") or item.get("name") or ""): slugify(item.get("City") or item.get("name") or "") for item in items}

    wsdot_url = "https://data.wsdot.wa.gov/arcgis/rest/services/Shared/PoliAdminBndryData/MapServer/1/query?where=1%3D1&outFields=CityName&outSR=4326&f=geojson"
    try:
        req = urllib.request.Request(wsdot_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status == 200:
                geojson = json.loads(resp.read().decode("utf-8"))
                simplified_features = []
                for feat in geojson.get("features", []):
                    raw_city_name = feat.get("properties", {}).get("CityName", "")
                    c_name = clean_city_name(raw_city_name)
                    if c_name in target_slugs:
                        feat["properties"]["slug"] = target_slugs[c_name]
                        feat["properties"]["name"] = raw_city_name
                        feat["geometry"] = simplify_geometry(feat["geometry"])
                        simplified_features.append(feat)

                output = {
                    "type": "FeatureCollection",
                    "features": simplified_features,
                    "last_updated": datetime.utcnow().isoformat() + "Z"
                }
                os.makedirs(DATA_DIR, exist_ok=True)
                with open(os.path.join(DATA_DIR, "city_boundaries.json"), "w", encoding="utf-8") as f:
                    json.dump(output, f, indent=2, ensure_ascii=False)
                print("💾 Saved simplified city_boundaries.json.")
    except Exception as e:
        print(f"⚠️ Boundaries notice: {e}")

if __name__ == "__main__":
    main()