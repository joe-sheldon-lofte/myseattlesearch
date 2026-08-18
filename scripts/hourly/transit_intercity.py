import os
import json
import re
import math
import urllib.request
import urllib.parse
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")

CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")
CITY_BOUNDARIES_PATH = os.path.join(DATA_DIR, "city_boundaries.json")
TRANSIT_DATA_PATH = os.path.join(DATA_DIR, "transit_data.json")
OUTPUT_RADAR_PATH = os.path.join(DATA_DIR, "transit_radar_live.json")

# Ground transit agencies serving King & Snohomish Counties
# 1: King County Metro
# 29 / 3 / 40: Sound Transit
# 23: Community Transit
# 13: Everett Transit
# 10: Seattle Center Monorail
ONEBUSAWAY_AGENCIES = ["1", "29", "23", "13", "10", "3", "40"]

def slugify(text):
    if not text:
        return ""
    text = str(text).lower().strip()
    out = [ch if ch.isalnum() else '-' for ch in text]
    res = "".join(out)
    while '--' in res:
        res = res.replace('--', '-')
    return res.strip('-')

def http_get_json(url, timeout=12):
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"   ⚠️ Transit API notice for {url}: {e}")
    return None

def point_in_poly(x, y, poly):
    """Ray casting point-in-polygon algorithm (x=lng, y=lat)."""
    n = len(poly)
    inside = False
    p1x, p1y = poly[0][0], poly[0][1]
    for i in range(1, n + 1):
        p2x, p2y = poly[i % n][0], poly[i % n][1]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside

def is_point_in_geojson_geometry(lng, lat, geometry):
    """Checks if a point (lng, lat) lies inside a GeoJSON Polygon or MultiPolygon."""
    gtype = geometry.get('type')
    coords = geometry.get('coordinates', [])
    
    if gtype == 'Polygon':
        if not coords:
            return False
        if point_in_poly(lng, lat, coords[0]):
            for hole in coords[1:]:
                if point_in_poly(lng, lat, hole):
                    return False
            return True
        return False
        
    elif gtype == 'MultiPolygon':
        for poly in coords:
            if not poly:
                continue
            if point_in_poly(lng, lat, poly[0]):
                in_hole = False
                for hole in poly[1:]:
                    if point_in_poly(lng, lat, hole):
                        in_hole = True
                        break
                if not in_hole:
                    return True
        return False
        
    return False

def compute_bbox(geometry):
    """Computes bounding box (min_lng, min_lat, max_lng, max_lat) for fast spatial pre-filtering."""
    gtype = geometry.get('type')
    coords = geometry.get('coordinates', [])
    all_lngs, all_lats = [], []
    
    if gtype == 'Polygon':
        for ring in coords:
            for pt in ring:
                all_lngs.append(pt[0])
                all_lats.append(pt[1])
    elif gtype == 'MultiPolygon':
        for poly in coords:
            for ring in poly:
                for pt in ring:
                    all_lngs.append(pt[0])
                    all_lats.append(pt[1])
                    
    if not all_lngs or not all_lats:
        return (0, 0, 0, 0)
    return (min(all_lngs), min(all_lats), max(all_lngs), max(all_lats))

def load_transit_rules():
    """Parses transit_data.json list or dictionary structure cleanly."""
    route_seat_map = {}
    mode_seat_map = {
        "light rail": 296,
        "commuter rail": 560,
        "express bus": 55,
        "bus": 40,
        "bus rapid transit": 60,
        "monorail": 250
    }
    
    candidates = [
        TRANSIT_DATA_PATH,
        os.path.join(os.getcwd(), "data", "transit_data.json"),
        os.path.join(os.getcwd(), "transit_data.json"),
        os.path.join(BASE_DIR, "transit_data.json")
    ]
    
    target_path = None
    for cand in candidates:
        if os.path.exists(cand):
            target_path = cand
            break

    if target_path:
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            items = data if isinstance(data, list) else data.get("rules", []) if isinstance(data, dict) else []
            for rule in items:
                if isinstance(rule, dict) and rule.get("Active Transit Score") == "Yes":
                    route_id = str(rule.get("Route ID", "")).strip().lower()
                    mode = str(rule.get("Transit Mode", "")).strip().lower()
                    try:
                        seats = int(rule.get("Default Seats", 0))
                    except (ValueError, TypeError):
                        seats = 0
                        
                    if route_id and seats > 0:
                        route_seat_map[route_id] = seats
                    if mode and seats > 0:
                        mode_seat_map[mode] = seats
            print(f"✅ Loaded {len(route_seat_map)} route capacity rules from {target_path}")
        except Exception as e:
            print(f"⚠️ transit_data.json parse notice: {e}")
    else:
        print("⚠️ Warning: transit_data.json not found on disk. Falling back to GTFS mode capacities.")

    return route_seat_map, mode_seat_map

def classify_vehicle_mode(vehicle, route_seat_map, mode_seat_map):
    """Determines vehicle mode and seat capacity directly from GTFS-RT payload and transit_data.json."""
    vehicle_id = str(vehicle.get("vehicleId") or "").lower()
    trip_status = vehicle.get("tripStatus") or {}
    route_id = str(trip_status.get("activeTrip", {}).get("routeId") or trip_status.get("routeId") or "").lower()
    
    # 1. Exact route ID match in transit_data.json
    if route_id in route_seat_map:
        seats = route_seat_map[route_id]
        if "100479" in route_id or "100511" in route_id:
            mode = "light_rail"
        elif "100224" in route_id or "100225" in route_id:
            mode = "commuter_rail"
        elif "monorail" in route_id:
            mode = "monorail"
        else:
            mode = "bus"
        return mode, seats

    # 2. Mode pattern fallbacks
    if "monorail" in vehicle_id or "monorail" in route_id:
        return "monorail", mode_seat_map.get("monorail", 250)
    if "link" in route_id or "light_rail" in route_id or "link" in vehicle_id:
        return "light_rail", mode_seat_map.get("light rail", 296)
    if "sounder" in route_id or "commuter" in route_id or "sounder" in vehicle_id:
        return "commuter_rail", mode_seat_map.get("commuter rail", 560)
    if "swift" in route_id or "brt" in route_id:
        return "bus", mode_seat_map.get("bus rapid transit", 60)
    if "st_bus" in route_id or "express" in route_id:
        return "bus", mode_seat_map.get("express bus", 55)

    return "bus", mode_seat_map.get("bus", 40)

def main():
    print("🚌 Ingesting Live Ground Transit Vehicles (King & Snohomish Agencies)...")
    
    candidates_city = [CITY_DATA_PATH, os.path.join(os.getcwd(), "data", "city_data.json"), os.path.join(os.getcwd(), "city_data.json")]
    candidates_bound = [CITY_BOUNDARIES_PATH, os.path.join(os.getcwd(), "data", "city_boundaries.json"), os.path.join(os.getcwd(), "city_boundaries.json")]
    
    c_path = next((p for p in candidates_city if os.path.exists(p)), None)
    b_path = next((p for p in candidates_bound if os.path.exists(p)), None)

    if not c_path or not b_path:
        print(f"❌ Required city_data.json ({c_path}) or city_boundaries.json ({b_path}) missing. Aborting.")
        return

    with open(c_path, "r", encoding="utf-8") as f:
        raw_cities = json.load(f)
    city_items = raw_cities if isinstance(raw_cities, list) else list(raw_cities.values())

    with open(b_path, "r", encoding="utf-8") as f:
        boundaries_geo = json.load(f)

    route_seat_map, mode_seat_map = load_transit_rules()

    # Pre-index city boundaries with bounding boxes
    city_polygons = []
    for feat in boundaries_geo.get('features', []):
        props = feat.get('properties', {})
        c_slug = props.get('slug') or slugify(props.get('CityName') or props.get('name') or "")
        c_name = props.get('CityName') or props.get('name') or ""
        geom = feat.get('geometry', {})
        bbox = compute_bbox(geom)
        city_polygons.append({
            "slug": c_slug,
            "name": c_name,
            "geometry": geom,
            "bbox": bbox
        })

    # Read OneBusAway API Key Secret
    oba_key = os.environ.get("ONEBUSAWAY_API_KEY") or os.environ.get("OBA_API_KEY") or "TEST"
    
    # Fetch live active vehicles from target ground agencies
    active_vehicles = []
    for agency_id in ONEBUSAWAY_AGENCIES:
        url = f"http://api.pugetsound.onebusaway.org/api/where/vehicles-for-agency/{agency_id}.json?key={oba_key}"
        res = http_get_json(url)
        if res and isinstance(res, dict) and "data" in res and "list" in res["data"]:
            active_vehicles.extend(res["data"]["list"])

    print(f"📡 Fetched {len(active_vehicles)} live active transit vehicles across King & Snohomish agencies.")

    # Spatial counters per city
    city_counts = {
        c["slug"]: {
            "name": c["name"],
            "total_active_seats": 0,
            "counts": {"bus": 0, "light_rail": 0, "commuter_rail": 0, "monorail": 0, "streetcar": 0}
        }
        for c in city_polygons
    }

    # Match live vehicle coordinates to city boundaries
    matched_vehicles = 0
    for v in active_vehicles:
        loc = v.get("location") or v.get("lastKnownLocation") or {}
        lat = loc.get("lat") or loc.get("latitude")
        lon = loc.get("lon") or loc.get("lng") or loc.get("longitude")
        
        if lat is None or lon is None:
            continue

        try:
            v_lat, v_lon = float(lat), float(lon)
        except (ValueError, TypeError):
            continue

        mode, seats = classify_vehicle_mode(v, route_seat_map, mode_seat_map)

        for c in city_polygons:
            min_lng, min_lat, max_lng, max_lat = c["bbox"]
            if min_lng <= v_lon <= max_lng and min_lat <= v_lat <= max_lat:
                if is_point_in_geojson_geometry(v_lon, v_lat, c["geometry"]):
                    slug = c["slug"]
                    city_counts[slug]["total_active_seats"] += seats
                    if mode in city_counts[slug]["counts"]:
                        city_counts[slug]["counts"][mode] += 1
                    else:
                        city_counts[slug]["counts"][mode] = 1
                    matched_vehicles += 1
                    break

    print(f"🎯 Matched {matched_vehicles} live vehicles into target city boundaries.")

    # Calculate Normalized Active Transit Score per City
    output_radar = {}
    for c_obj in city_items:
        raw_name = c_obj.get("City") or c_obj.get("name") or ""
        if not raw_name:
            continue

        city_name = str(raw_name).strip()
        slug = slugify(city_name)
        
        try:
            pop_val = int(c_obj.get("FallbackPopulation") or c_obj.get("population") or 0)
        except (ValueError, TypeError):
            pop_val = 0

        c_data = city_counts.get(slug, {
            "name": city_name,
            "total_active_seats": 0,
            "counts": {"bus": 0, "light_rail": 0, "commuter_rail": 0, "monorail": 0}
        })

        total_seats = c_data["total_active_seats"]

        seats_per_1k = total_seats / (pop_val / 1000.0) if pop_val > 0 else 0.0
        raw_score = (seats_per_1k / 50.0) * 100.0
        active_transit_score = min(100, max(0, int(round(raw_score))))

        counts = c_data.get("counts", {})

        output_radar[slug] = {
            "name": city_name,
            "population": pop_val,
            "active_transit_score": active_transit_score,
            "total_active_seats": total_seats,
            "seats_per_1000": round(seats_per_1k, 1),
            "vehicle_counts": {
                "buses": counts.get("bus", 0),
                "light_rail": counts.get("light_rail", 0),
                "commuter_rail": counts.get("commuter_rail", 0),
                "monorail": counts.get("monorail", 0)
            },
            "last_updated": datetime.now(timezone.utc).isoformat()
        }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_RADAR_PATH, "w", encoding="utf-8") as f:
        json.dump(output_radar, f, indent=2, ensure_ascii=False)

    print(f"💾 Saved strictly live spatial active transit radar for {len(output_radar)} cities.")

if __name__ == "__main__":
    main()