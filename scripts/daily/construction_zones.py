import os
import json
import math
import urllib.request
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")
CITY_BOUNDARIES_PATH = os.path.join(DATA_DIR, "city_boundaries.json")
OUT_PATH = os.path.join(DATA_DIR, "city_construction.json")

def slugify(text):
    if not text: return ""
    text = str(text).lower().strip()
    out = [ch if ch.isalnum() else '-' for ch in text]
    res = "".join(out)
    while '--' in res: res = res.replace('--', '-')
    return res.strip('-')

def http_get_json_simple(url, timeout=25):
    headers = {"User-Agent": "Mozilla/5.0"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"HTTP GET Error [{url[:60]}...]: {e}")
    return None

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 3958.8
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def get_geometry_bbox(geometry):
    g_type, coords = geometry.get("type"), geometry.get("coordinates", [])
    all_pts = []
    if g_type == "Polygon":
        for ring in coords: all_pts.extend(ring)
    elif g_type == "MultiPolygon":
        for poly in coords:
            for ring in poly: all_pts.extend(ring)
    if not all_pts: return None
    return (min(pt[1] for pt in all_pts), min(pt[0] for pt in all_pts), max(pt[1] for pt in all_pts), max(pt[0] for pt in all_pts))

def point_in_ring(lat, lon, ring):
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        intersect = ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-12) + xi)
        if intersect: inside = not inside
        j = i
    return inside

def point_in_geometry(lat, lon, geometry):
    g_type, coords = geometry.get("type"), geometry.get("coordinates", [])
    if g_type == "Polygon":
        if coords and point_in_ring(lat, lon, coords[0]):
            return not any(point_in_ring(lat, lon, hole) for hole in coords[1:])
    elif g_type == "MultiPolygon":
        for poly in coords:
            if poly and point_in_ring(lat, lon, poly[0]):
                if not any(point_in_ring(lat, lon, hole) for hole in poly[1:]):
                    return True
    return False

def load_city_boundaries():
    if not os.path.exists(CITY_BOUNDARIES_PATH): return []
    with open(CITY_BOUNDARIES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    indexed = []
    for feat in data.get("features", []):
        props = feat.get("properties", {})
        slug = props.get("slug") or slugify(props.get("name") or "")
        bbox = get_geometry_bbox(feat.get("geometry", {}))
        if slug and bbox:
            indexed.append({"slug": slug, "bbox": bbox, "geometry": feat.get("geometry", {})})
    return indexed

def match_city_for_alert(lat, lon, city_boundaries, cities):
    for city in city_boundaries:
        bbox = city["bbox"]
        if bbox[0] <= lat <= bbox[2] and bbox[1] <= lon <= bbox[3]:
            if point_in_geometry(lat, lon, city["geometry"]):
                return city["slug"]

    closest_city, min_dist = None, 3.0
    for c in cities:
        if c.get("latitude") is not None and c.get("longitude") is not None:
            dist = haversine_distance(lat, lon, c["latitude"], c["longitude"])
            if dist < min_dist:
                min_dist, closest_city = dist, c["slug"]
    return closest_city

def main():
    print("🚧 Harvesting Active WSDOT Construction & Work Zones...")
    if not os.path.exists(CITY_DATA_PATH):
        print("ℹ️ city_data.json missing. Skipping construction alerts.")
        return

    with open(CITY_DATA_PATH, "r", encoding="utf-8") as f:
        raw_cities = json.load(f)

    items = raw_cities if isinstance(raw_cities, list) else list(raw_cities.values())
    cities = []
    for it in items:
        name = it.get("City") or it.get("name")
        if name:
            lat = float(it["Latitude"]) if it.get("Latitude") else None
            lon = float(it["Longitude"]) if it.get("Longitude") else None
            cities.append({"slug": slugify(name), "name": str(name).strip(), "latitude": lat, "longitude": lon})

    city_boundaries = load_city_boundaries()
    wsdot_code = os.environ.get("WSDOT_ACCESS_CODE", "").strip().strip("'").strip('"')
    if not wsdot_code:
        print("ℹ️ WSDOT_ACCESS_CODE missing. Skipping construction harvest.")
        return

    wsdot_alerts_url = f"https://wsdot.wa.gov/Traffic/api/HighwayAlerts/HighwayAlertsREST.svc/GetAlertsAsJson?AccessCode={wsdot_code}"
    alerts = http_get_json_simple(wsdot_alerts_url)
    city_map = {c["slug"]: {"name": c["name"], "alert_count": 0, "alerts": []} for c in cities}
    total_alerts = 0

    if alerts and isinstance(alerts, list):
        for a in alerts:
            combined_text = f"{a.get('EventCategory')} {a.get('HeadlineDescription')} {a.get('ExtendedDescription')}".lower()
            if not any(k in combined_text for k in ["construction", "maintenance", "work", "closure", "paving", "repair", "delay", "lane"]):
                continue

            loc_obj = a.get("StartRoadWayLocation") or a.get("StartRoadwayLocation") or {}
            alat = loc_obj.get("Latitude") if isinstance(loc_obj, dict) else a.get("Latitude")
            alon = loc_obj.get("Longitude") if isinstance(loc_obj, dict) else a.get("Longitude")
            
            if alat is None or alon is None: continue
            try: alat, alon = float(alat), float(alon)
            except (ValueError, TypeError): continue

            alert_obj = {
                "alert_id": f"wsdot-{a.get('AlertID')}",
                "headline": a.get("HeadlineDescription", "Roadwork Alert"),
                "priority": a.get("Priority", "Low"),
                "event_category": a.get("EventCategory", "Construction"),
                "start_time": a.get("StartTime"), "end_time": a.get("EndTime"),
                "description": a.get("ExtendedDescription", "")
            }

            matched_slug = match_city_for_alert(alat, alon, city_boundaries, cities)
            if matched_slug and matched_slug in city_map:
                city_map[matched_slug]["alerts"].append(alert_obj)
                city_map[matched_slug]["alert_count"] += 1
                total_alerts += 1

    output = {
        slug: {"name": details["name"], "alert_count": details["alert_count"], "alerts": details["alerts"], "last_updated": datetime.now(timezone.utc).isoformat()}
        for slug, details in city_map.items()
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"💾 Saved {total_alerts} active construction alerts to {OUT_PATH}")

if __name__ == "__main__":
    main()