# File: scripts/hourly/transit_intercity.py
"""
MYSEATTLESEARCH - HOURLY GROUND TRANSIT & COMMUTE RADAR INGESTION
File: scripts/hourly/transit_intercity.py

Purpose:
  1. Ingests live ground transit vehicles from OneBusAway (King & Snohomish agencies)
     and calculates normalized Active Transit Score (0-100) per city boundary.
  2. Queries Mapbox Directions API (mapbox/driving-traffic) for real-time traffic
     duration vs. typical duration across city diagonal coordinates, and calculates
     Active Commute Score (0-100).
  3. Outputs consolidated telemetry to data/transit_radar_live.json.
"""

import os
import json
import re
import math
import urllib.request
import urllib.parse
from datetime import datetime, timezone

# Robust Repository Root Path Resolution
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(CURRENT_DIR) == "hourly":
    REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
elif os.path.basename(CURRENT_DIR) == "scripts":
    REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
else:
    REPO_ROOT = os.path.abspath(CURRENT_DIR)

DATA_DIR = os.path.join(REPO_ROOT, "data")

CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")
CITY_BOUNDARIES_PATH = os.path.join(DATA_DIR, "city_boundaries.json")
COMMUTE_BASELINE_PATH = os.path.join(DATA_DIR, "city_commute_baseline.json")
TRANSIT_DATA_PATH = os.path.join(DATA_DIR, "transit_data.json")
OUTPUT_RADAR_PATH = os.path.join(DATA_DIR, "transit_radar_live.json")

# Ground transit agencies serving King & Snohomish Counties
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

def http_get_json(url, timeout=10):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)",
        "Accept": "application/json"
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"   ⚠️ API notice for {url[:70]}...: {e}")
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
    """Parses transit_data.json capacity rules."""
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
        os.path.join(REPO_ROOT, "data", "transit_data.json"),
        os.path.join(REPO_ROOT, "transit_data.json")
    ]
    
    target_path = next((cand for cand in candidates if os.path.exists(cand)), None)

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
        except Exception as e:
            print(f"⚠️ transit_data.json parse notice: {e}")

    return route_seat_map, mode_seat_map

def classify_vehicle_mode(vehicle, route_seat_map, mode_seat_map):
    """Determines vehicle mode and seat capacity directly from GTFS-RT payload."""
    vehicle_id = str(vehicle.get("vehicleId") or "").lower()
    trip_status = vehicle.get("tripStatus") or {}
    route_id = str(trip_status.get("activeTrip", {}).get("routeId") or trip_status.get("routeId") or "").lower()
    
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

def fetch_mapbox_drive_times(nw_lat, nw_lng, se_lat, se_lng, token):
    """Queries Mapbox Directions (driving-traffic) for live duration and typical baseline."""
    if not token:
        return None, None
        
    url = f"https://api.mapbox.com/directions/v5/mapbox/driving-traffic/{nw_lng},{nw_lat};{se_lng},{se_lat}?overview=false&access_token={token}"
    res = http_get_json(url, timeout=6)
    
    if res and isinstance(res, dict) and "routes" in res and res["routes"]:
        route = res["routes"][0]
        live_sec = route.get("duration", 0)
        typical_sec = route.get("duration_typical", live_sec)
        
        live_mins = round(live_sec / 60.0, 1) if live_sec else None
        typical_mins = round(typical_sec / 60.0, 1) if typical_sec else None
        return live_mins, typical_mins
        
    return None, None

def calculate_active_commute_score(live_mins, base_mins):
    """Calculates Active Commute Score (0-100) based on live vs baseline ratio."""
    if not live_mins or not base_mins or base_mins <= 0:
        return 88  # Neutral fallback when telemetry is temporarily unavailable
    
    ratio = live_mins / base_mins
    if ratio <= 1.0:
        return 100
    
    # Proportional congestion penalty (20% delay -> 30 pt reduction -> 70 score)
    penalty = (ratio - 1.0) * 100.0 * 1.5
    return max(0, min(100, int(round(100.0 - penalty))))

def main():
    print("🚌 Ingesting Live Ground Transit Vehicles & Real-Time Commute Radar...")
    
    c_path = next((p for p in [CITY_DATA_PATH, os.path.join(REPO_ROOT, "data", "city_data.json")] if os.path.exists(p)), None)
    b_path = next((p for p in [CITY_BOUNDARIES_PATH, os.path.join(REPO_ROOT, "data", "city_boundaries.json")] if os.path.exists(p)), None)
    base_path = next((p for p in [COMMUTE_BASELINE_PATH, os.path.join(REPO_ROOT, "data", "city_commute_baseline.json")] if os.path.exists(p)), None)

    if not c_path or not b_path:
        print("❌ Required city_data.json or city_boundaries.json missing. Aborting.")
        return

    with open(c_path, "r", encoding="utf-8") as f:
        raw_cities = json.load(f)
    city_items = raw_cities if isinstance(raw_cities, list) else list(raw_cities.values())

    with open(b_path, "r", encoding="utf-8") as f:
        boundaries_geo = json.load(f)

    commute_baselines = {}
    if base_path and os.path.exists(base_path):
        with open(base_path, "r", encoding="utf-8") as f:
            commute_baselines = json.load(f)

    route_seat_map, mode_seat_map = load_transit_rules()

    # Pre-index city boundaries
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

    oba_key = os.environ.get("ONEBUSAWAY_API_KEY") or os.environ.get("OBA_API_KEY") or "TEST"
    mapbox_token = os.environ.get("MAPBOX_ACCESS_TOKEN", "").strip().strip("'").strip('"')
    
    # 1. Harvest Active Puget Sound Public Transit Vehicles
    active_vehicles = []
    for agency_id in ONEBUSAWAY_AGENCIES:
        url = f"http://api.pugetsound.onebusaway.org/api/where/vehicles-for-agency/{agency_id}.json?key={oba_key}"
        res = http_get_json(url)
        if res and isinstance(res, dict) and "data" in res and "list" in res["data"]:
            active_vehicles.extend(res["data"]["list"])

    city_counts = {
        c["slug"]: {
            "name": c["name"],
            "total_active_seats": 0,
            "counts": {"bus": 0, "light_rail": 0, "commuter_rail": 0, "monorail": 0}
        }
        for c in city_polygons
    }

    for v in active_vehicles:
        loc = v.get("location") or v.get("lastKnownLocation") or {}
        lat, lon = loc.get("lat") or loc.get("latitude"), loc.get("lon") or loc.get("lng") or loc.get("longitude")
        if lat is None or lon is None: continue
        try: v_lat, v_lon = float(lat), float(lon)
        except (ValueError, TypeError): continue

        mode, seats = classify_vehicle_mode(v, route_seat_map, mode_seat_map)

        for c in city_polygons:
            min_lng, min_lat, max_lng, max_lat = c["bbox"]
            if min_lng <= v_lon <= max_lng and min_lat <= v_lat <= max_lat:
                if is_point_in_geojson_geometry(v_lon, v_lat, c["geometry"]):
                    slug = c["slug"]
                    city_counts[slug]["total_active_seats"] += seats
                    city_counts[slug]["counts"][mode] = city_counts[slug]["counts"].get(mode, 0) + 1
                    break

    # 2. Assemble Live Telemetry & Scores Across Municipalities
    output_radar = {}
    for c_obj in city_items:
        raw_name = c_obj.get("City") or c_obj.get("name") or ""
        if not raw_name: continue

        city_name = str(raw_name).strip()
        slug = slugify(city_name)
        
        try: pop_val = int(c_obj.get("FallbackPopulation") or c_obj.get("population") or 0)
        except (ValueError, TypeError): pop_val = 0

        c_data = city_counts.get(slug, {"name": city_name, "total_active_seats": 0, "counts": {}})
        total_seats = c_data["total_active_seats"]

        seats_per_1k = total_seats / (pop_val / 1000.0) if pop_val > 0 else 0.0
        active_transit_score = min(100, max(0, int(round((seats_per_1k / 50.0) * 100.0))))

        # Live Mapbox Congestion Drive Time vs Typical Duration
        b_info = commute_baselines.get(slug, {})
        nw_lat, nw_lng = b_info.get("nw_lat"), b_info.get("nw_lng")
        se_lat, se_lng = b_info.get("se_lat"), b_info.get("se_lng")
        manual_base_mins = b_info.get("baseline_drive_minutes")

        live_mins, typical_mins = None, None
        if nw_lat and nw_lng and se_lat and se_lng and mapbox_token:
            live_mins, typical_mins = fetch_mapbox_drive_times(nw_lat, nw_lng, se_lat, se_lng, mapbox_token)

        base_mins = typical_mins or manual_base_mins or live_mins or 10.0
        active_commute_score = calculate_active_commute_score(live_mins, base_mins)

        counts = c_data.get("counts", {})

        output_radar[slug] = {
            "name": city_name,
            "population": pop_val,
            "active_transit_score": active_transit_score,
            "active_commute_score": active_commute_score,
            "live_commute_minutes": live_mins or base_mins,
            "baseline_commute_minutes": base_mins,
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

    print(f"💾 Saved live ground transit & Mapbox commute score for {len(output_radar)} cities ➔ {OUTPUT_RADAR_PATH}")

if __name__ == "__main__":
    main()