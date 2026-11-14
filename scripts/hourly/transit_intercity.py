# File: scripts/hourly/transit_intercity.py
"""
MYSEATTLESEARCH - HOURLY GROUND TRANSIT, COMMUTE RADAR & WSDOT FERRY INGESTION
File: scripts/hourly/transit_intercity.py

Purpose:
  1. Ingests live ground transit vehicles from OneBusAway (King & Snohomish agencies)
     with request pacing and retry logic to avoid HTTP 429 throttling.
  2. Queries Mapbox Directions API (mapbox/driving-traffic) for real-time traffic
     duration vs. typical duration across city diagonal coordinates, and calculates
     Active Commute Score (0-100).
  3. Outputs consolidated ground telemetry to data/transit_radar_live.json.
  4. Harvests 48-hour WSDOT Ferry schedules, assigned vessel names, disruptions/alerts,
     and terminal coordinates across all active WSF routes into data/ferry_schedules.json.
"""

import os
import json
import re
import time
import requests
import urllib3
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

# Suppress unverified HTTPS request warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
OUTPUT_FERRY_PATH = os.path.join(DATA_DIR, "ferry_schedules.json")

# Ground transit agencies serving King & Snohomish Counties
ONEBUSAWAY_AGENCIES = ["1", "29", "23", "13", "10", "3", "40"]

# WSDOT Ferries REST API endpoints
WSF_SCHEDULE_BASE = "https://www.wsdot.wa.gov/Ferries/API/Schedule/rest"
WSF_TERMINALS_BASE = "https://www.wsdot.wa.gov/Ferries/API/Terminals/rest"
PACIFIC_TZ = ZoneInfo("America/Los_Angeles")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)",
    "Accept": "application/json"
}

def slugify(text):
    if not text:
        return ""
    text = str(text).lower().strip()
    out = [ch if ch.isalnum() else '-' for ch in text]
    res = "".join(out)
    while '--' in res:
        res = res.replace('--', '-')
    return res.strip('-')

def parse_wsf_date(raw_val):
    """Parses WCF /Date(ms-offset)/ strings or ISO strings into timezone-aware ISO-8601 strings."""
    if not raw_val:
        return None
    s = str(raw_val).strip()
    m = re.search(r"/Date\((-?\d+)([+-]\d{4})?\)/", s)
    if m:
        ms = int(m.group(1))
        tz_str = m.group(2)
        dt_utc = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
        if tz_str:
            sign = 1 if tz_str[0] == "+" else -1
            hours = int(tz_str[1:3])
            mins = int(tz_str[3:5])
            offset = timezone(timedelta(hours=sign * hours, minutes=sign * mins))
            return dt_utc.astimezone(offset).isoformat()
        return dt_utc.astimezone(PACIFIC_TZ).isoformat()
    return s

def strip_html_tags(raw_html):
    if not raw_html:
        return ""
    text = re.sub(r"<[^>]+>", " ", str(raw_html))
    return re.sub(r"\s+", " ", text).strip()

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

def fetch_oba_agency_vehicles(session, agency_id, oba_key):
    url = f"https://api.pugetsound.onebusaway.org/api/where/vehicles-for-agency/{agency_id}.json?key={oba_key}"
    for attempt in range(2):
        try:
            res = session.get(url, timeout=8)
            if res.status_code == 200:
                data = res.json()
                if "data" in data and "list" in data["data"]:
                    return data["data"]["list"]
                return []
            elif res.status_code == 429:
                time.sleep(1.0)
                continue
        except Exception as e:
            if attempt == 1:
                print(f"   ⚠️ OneBusAway Agency {agency_id} notice: {e}")
        time.sleep(0.3)
    return []

def fetch_mapbox_drive_times(session, nw_lat, nw_lng, se_lat, se_lng, token):
    if not token:
        return None, None
        
    url = f"https://api.mapbox.com/directions/v5/mapbox/driving-traffic/{nw_lng},{nw_lat};{se_lng},{se_lat}?overview=false&access_token={token}"
    try:
        res = session.get(url, timeout=6)
        if res.status_code == 200:
            data = res.json()
            if "routes" in data and data["routes"]:
                route = data["routes"][0]
                live_sec = route.get("duration", 0)
                typical_sec = route.get("duration_typical", live_sec)
                
                live_mins = round(live_sec / 60.0, 1) if live_sec else None
                typical_mins = round(typical_sec / 60.0, 1) if typical_sec else None
                return live_mins, typical_mins
    except Exception as e:
        print(f"   ⚠️ Mapbox Directions notice: {e}")
        
    return None, None

def calculate_active_commute_score(live_mins, base_mins):
    if not live_mins or not base_mins or base_mins <= 0:
        return 88
    
    ratio = live_mins / base_mins
    if ratio <= 1.0:
        return 100
    
    penalty = (ratio - 1.0) * 100.0 * 1.5
    return max(0, min(100, int(round(100.0 - penalty))))

def fetch_wsf_json(session, url):
    for attempt in range(3):
        try:
            res = session.get(url, timeout=12)
            if res.status_code == 200:
                return res.json()
            elif res.status_code in (429, 503):
                time.sleep(1.5 * (attempt + 1))
                continue
        except Exception as e:
            if attempt == 2:
                print(f"   ⚠️ WSDOT Ferries API notice ({url.split('?')[0]}): {e}")
        time.sleep(0.4)
    return None

def harvest_wsdot_ferry_schedules(session, wsdot_key):
    """
    Fetches terminal coordinates, 48-hour sailing timetables (Today + Tomorrow),
    assigned vessel names, and active route alerts for all WSDOT Ferry routes.
    """
    if not wsdot_key:
        print("⚠️ WSDOT_ACCESS_CODE missing; skipping ferry schedule harvest.")
        return

    print("⛴️  Ingesting WSDOT Ferry Schedules (48-hour window), Vessels & Terminal Coordinates...")

    # 1. Fetch Terminal Locations (Lat/Lng coordinates & metadata)
    term_locs_raw = fetch_wsf_json(session, f"{WSF_TERMINALS_BASE}/terminallocations?apiaccesscode={wsdot_key}")
    terminal_map = {}
    if isinstance(term_locs_raw, list):
        for t in term_locs_raw:
            tid = t.get("TerminalID")
            if tid is not None:
                terminal_map[tid] = {
                    "terminal_id": tid,
                    "name": (t.get("TerminalName") or "").strip(),
                    "abbrev": (t.get("TerminalAbbrev") or "").strip(),
                    "latitude": t.get("Latitude"),
                    "longitude": t.get("Longitude"),
                    "city": (t.get("City") or "").strip() or None,
                    "address": (t.get("AddressLineOne") or "").strip() or None,
                }

    # 2. Fetch Active Ferry Bulletins / Alerts
    alerts_raw = fetch_wsf_json(session, f"{WSF_SCHEDULE_BASE}/alerts?apiaccesscode={wsdot_key}")
    global_alerts = []
    if isinstance(alerts_raw, list):
        for al in alerts_raw:
            global_alerts.append({
                "bulletin_id": al.get("BulletinID"),
                "title": (al.get("BulletinTitle") or "").strip(),
                "text": strip_html_tags(al.get("BulletinText") or al.get("DisruptionDescription") or ""),
                "last_updated": parse_wsf_date(al.get("BulletinLastUpdated")),
            })

    # 3. Query Today + Tomorrow (48-hour horizon) in Pacific Time
    now_pt = datetime.now(PACIFIC_TZ)
    trip_dates = [
        now_pt.strftime("%Y-%m-%d"),
        (now_pt + timedelta(days=1)).strftime("%Y-%m-%d"),
    ]

    routes_by_id = {}
    for idx, trip_date in enumerate(trip_dates):
        day_label = "today" if idx == 0 else "tomorrow"
        routes_raw = fetch_wsf_json(session, f"{WSF_SCHEDULE_BASE}/routes/{trip_date}?apiaccesscode={wsdot_key}")
        if not isinstance(routes_raw, list):
            print(f"   ⚠️ WSDOT Ferries /routes/{trip_date} returned no list.")
            continue

        for r_obj in routes_raw:
            rid = r_obj.get("RouteID")
            if rid is None:
                continue
            r_abbrev = (r_obj.get("RouteAbbrev") or "").strip()
            r_desc = (r_obj.get("Description") or "").strip()
            r_slug = slugify(r_abbrev or r_desc or f"route-{rid}")

            if rid not in routes_by_id:
                routes_by_id[rid] = {
                    "route_id": rid,
                    "route_abbrev": r_abbrev,
                    "route_slug": r_slug,
                    "description": r_desc,
                    "region_id": r_obj.get("RegionID"),
                    "service_disruptions": [],
                    "terminals": {},
                    "assigned_vessels": set(),
                    "sailings_by_date": {},
                }

            entry = routes_by_id[rid]

            # Capture route-level service disruptions
            for dis in r_obj.get("ServiceDisruptions") or []:
                d_text = strip_html_tags(dis.get("DisruptionDescription") or dis.get("PublishStatus") or "")
                if d_text and d_text not in entry["service_disruptions"]:
                    entry["service_disruptions"].append(d_text)

            # Fetch full daily schedule & assigned vessels for this route + trip_date
            sched_raw = fetch_wsf_json(
                session,
                f"{WSF_SCHEDULE_BASE}/schedule/{trip_date}/{rid}?apiaccesscode={wsdot_key}"
            )
            time.sleep(0.15)

            day_sailings = []
            combos = sched_raw.get("TerminalCombos") if isinstance(sched_raw, dict) else []
            for combo in combos or []:
                dep_id = combo.get("DepartingTerminalID")
                arr_id = combo.get("ArrivingTerminalID")
                dep_name = (combo.get("DepartingTerminalName") or "").strip()
                arr_name = (combo.get("ArrivingTerminalName") or "").strip()

                for tid, fallback_name in ((dep_id, dep_name), (arr_id, arr_name)):
                    if tid is not None and tid not in entry["terminals"]:
                        t_info = terminal_map.get(tid) or {
                            "terminal_id": tid,
                            "name": fallback_name,
                            "abbrev": None,
                            "latitude": None,
                            "longitude": None,
                            "city": None,
                            "address": None,
                        }
                        if not t_info.get("name") and fallback_name:
                            t_info = dict(t_info, name=fallback_name)
                        entry["terminals"][tid] = t_info

                for t_slot in combo.get("Times") or []:
                    dep_iso = parse_wsf_date(t_slot.get("DepartingTime"))
                    arr_iso = parse_wsf_date(t_slot.get("ArrivingTime"))
                    v_name = (t_slot.get("VesselName") or "").strip() or None
                    v_id = t_slot.get("VesselID")
                    if v_name:
                        entry["assigned_vessels"].add(v_name)

                    day_sailings.append({
                        "departing_terminal_id": dep_id,
                        "departing_terminal_name": dep_name,
                        "arriving_terminal_id": arr_id,
                        "arriving_terminal_name": arr_name,
                        "departing_time": dep_iso,
                        "arriving_time": arr_iso,
                        "vessel_id": v_id,
                        "vessel_name": v_name,
                        "vessel_position_num": t_slot.get("VesselPositionNum"),
                        "loading_rule": t_slot.get("LoadingRule"),
                        "annotations": [
                            strip_html_tags(a) for a in (t_slot.get("AnnotationIndexes") or []) if strip_html_tags(a)
                        ],
                    })

            day_sailings.sort(key=lambda s: s.get("departing_time") or "")
            entry["sailings_by_date"][trip_date] = {
                "day_label": day_label,
                "trip_date": trip_date,
                "sailing_count": len(day_sailings),
                "sailings": day_sailings,
            }

    if not routes_by_id:
        print("⚠️ No WSDOT Ferry routes returned; preserving existing data/ferry_schedules.json.")
        return

    # Format final route-keyed payload
    routes_output = {}
    total_sailings = 0
    for rid, rdata in sorted(routes_by_id.items(), key=lambda kv: kv[1]["route_slug"]):
        slug = rdata["route_slug"]
        terminals_list = sorted(rdata["terminals"].values(), key=lambda t: t.get("name") or "")
        sailing_sum = sum(d["sailing_count"] for d in rdata["sailings_by_date"].values())
        total_sailings += sailing_sum

        routes_output[slug] = {
            "route_id": rdata["route_id"],
            "route_abbrev": rdata["route_abbrev"],
            "route_slug": slug,
            "description": rdata["description"],
            "region_id": rdata["region_id"],
            "assigned_vessels": sorted(rdata["assigned_vessels"]),
            "terminals": terminals_list,
            "service_disruptions": rdata["service_disruptions"],
            "total_48h_sailings": sailing_sum,
            "schedules": rdata["sailings_by_date"],
        }

    ferry_payload = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "horizon_hours": 48,
        "trip_dates": trip_dates,
        "route_count": len(routes_output),
        "total_sailings": total_sailings,
        "global_alerts": global_alerts,
        "routes": routes_output,
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_FERRY_PATH, "w", encoding="utf-8") as f:
        json.dump(ferry_payload, f, indent=2, ensure_ascii=False)

    print(f"💾 Saved 48-hour WSDOT Ferry schedules ({len(routes_output)} routes, {total_sailings} sailings) ➔ {OUTPUT_FERRY_PATH}")

def main():
    print("🚌 Ingesting Live Ground Transit Vehicles, Commute Radar & WSDOT Ferry Schedules...")
    session = requests.Session()
    session.headers.update(HEADERS)

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
    wsdot_key = (os.environ.get("WSDOT_ACCESS_CODE") or "").strip().strip("'").strip('"')
    
    # 1. Harvest Active Puget Sound Public Transit Vehicles with Query Pacing
    active_vehicles = []
    for agency_id in ONEBUSAWAY_AGENCIES:
        v_list = fetch_oba_agency_vehicles(session, agency_id, oba_key)
        active_vehicles.extend(v_list)
        time.sleep(0.35)

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
            live_mins, typical_mins = fetch_mapbox_drive_times(session, nw_lat, nw_lng, se_lat, se_lng, mapbox_token)

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

    # 3. Harvest 48-Hour WSDOT Ferry Schedules, Vessels & Terminal Coordinates
    harvest_wsdot_ferry_schedules(session, wsdot_key)

if __name__ == "__main__":
    main()