import os
import io
import json
import math
import re
import sys
import time
import datetime
from datetime import timedelta
import warnings
import ssl
import urllib.request
import urllib.parse
import requests
import feedparser
import boto3
import pandas as pd
from PIL import Image
from dateutil import parser
from dateutil.parser import UnknownTimezoneWarning
from zoneinfo import ZoneInfo
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# Import standalone weather harvester module
try:
    from harvest_weather_hourly import harvest_weather_data
except ImportError:
    from scripts.harvest_weather_hourly import harvest_weather_data

# Suppress dateutil PST/PDT unknown timezone warnings
warnings.filterwarnings("ignore", category=UnknownTimezoneWarning)

# Enable native Apple HEIC/HEIF decoding via Pillow-HEIF
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")
CITY_BOUNDARIES_PATH = os.path.join(DATA_DIR, "city_boundaries.json")
CRIME_STATS_PATH = os.path.join(DATA_DIR, "crime_stats.json")
CITY_FEEDS_PATH = os.path.join(DATA_DIR, "city_feeds.json")
TRANSIT_DATA_PATH = os.path.join(DATA_DIR, "transit_data.json")
TRANSIT_LIVE_PATH = os.path.join(DATA_DIR, "transit_radar_live.json")
TRANSIT_HISTORY_PATH = os.path.join(DATA_DIR, "transit_radar_history.json")
INTERCITY_SUMMARY_PATH = os.path.join(DATA_DIR, "intercity_summary.json")
COMMUTE_TOLLS_PATH = os.path.join(DATA_DIR, "city_commute_tolls.json")

def slugify(text):
    if not text:
        return ""
    text = str(text).lower().strip()
    out = []
    for ch in text:
        if ch.isalnum():
            out.append(ch)
        elif ch in [' ', '-', '_']:
            out.append('-')
    res = "".join(out)
    while '--' in res:
        res = res.replace('--', '-')
    return res.strip('-')

def clean_city_name(name):
    if not name or not isinstance(name, str):
        return ""
    return name.lower().replace("city of ", "").replace("town of ", "").strip()

def http_get_json_simple(url, extra_headers=None, timeout=25):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) RealEstateDataBot/1.0",
        "Accept": "application/json, text/plain, */*"
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                raw_bytes = resp.read()
                return json.loads(raw_bytes.decode("utf-8"))
    except Exception as e:
        print(f"HTTP GET Error [{url[:80]}...]: {e}")
    return None

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 3958.8
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def get_geometry_bbox(geometry):
    g_type = geometry.get("type")
    coords = geometry.get("coordinates", [])
    all_pts = []
    
    if g_type == "Polygon":
        for ring in coords:
            all_pts.extend(ring)
    elif g_type == "MultiPolygon":
        for poly in coords:
            for ring in poly:
                all_pts.extend(ring)
                
    if not all_pts:
        return None
        
    min_lon = min(pt[0] for pt in all_pts)
    max_lon = max(pt[0] for pt in all_pts)
    min_lat = min(pt[1] for pt in all_pts)
    max_lat = max(pt[1] for pt in all_pts)
    return (min_lat, min_lon, max_lat, max_lon)

def point_in_ring(lat, lon, ring):
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        intersect = ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-12) + xi)
        if intersect:
            inside = not inside
        j = i
    return inside

def point_in_geometry(lat, lon, geometry):
    g_type = geometry.get("type")
    coords = geometry.get("coordinates", [])
    
    if g_type == "Polygon":
        if not coords:
            return False
        if point_in_ring(lat, lon, coords[0]):
            for hole in coords[1:]:
                if point_in_ring(lat, lon, hole):
                    return False
            return True
    elif g_type == "MultiPolygon":
        for poly in coords:
            if not poly:
                continue
            if point_in_ring(lat, lon, poly[0]):
                in_hole = False
                for hole in poly[1:]:
                    if point_in_ring(lat, lon, hole):
                        in_hole = True
                        break
                if not in_hole:
                    return True
    return False

def load_city_boundaries():
    if not os.path.exists(CITY_BOUNDARIES_PATH):
        return []
        
    with open(CITY_BOUNDARIES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    features = data.get("features", [])
    indexed = []
    
    for feat in features:
        props = feat.get("properties", {})
        slug = props.get("slug") or slugify(props.get("CityName") or props.get("name") or "")
        name = props.get("name") or props.get("CityName") or ""
        geom = feat.get("geometry", {})
        bbox = get_geometry_bbox(geom)
        
        if slug and bbox:
            indexed.append({
                "slug": slug,
                "name": name,
                "bbox": bbox,
                "geometry": geom
            })
            
    return indexed

def match_city_for_point(lat, lon, city_boundaries):
    for city in city_boundaries:
        bbox = city["bbox"]
        if bbox[0] <= lat <= bbox[2] and bbox[1] <= lon <= bbox[3]:
            if point_in_geometry(lat, lon, city["geometry"]):
                return city["slug"]
    return None

def load_official_population_map():
    pop_map = {}

    if os.path.exists(CRIME_STATS_PATH):
        try:
            with open(CRIME_STATS_PATH, "r", encoding="utf-8") as f:
                crime_data = json.load(f)
                for city_name, details in crime_data.items():
                    if isinstance(details, dict) and "reported_population" in details:
                        slug = slugify(city_name)
                        pop_map[slug] = int(details["reported_population"])
        except Exception:
            pass

    return pop_map

def load_city_data():
    pop_map = load_official_population_map()

    if not os.path.exists(CITY_DATA_PATH):
        return []
        
    with open(CITY_DATA_PATH, "r", encoding="utf-8") as f:
        raw_data = json.load(f)
        
    raw_list = []
    if isinstance(raw_data, dict):
        for key, details in raw_data.items():
            if isinstance(details, dict):
                item = dict(details)
                item["_raw_key"] = key
                raw_list.append(item)
    elif isinstance(raw_data, list):
        raw_list = raw_data

    normalized = []
    for item in raw_list:
        raw_name = item.get("City") or item.get("name") or item.get("cityName") or item.get("_raw_key") or ""
        if not raw_name:
            continue
            
        slug = slugify(raw_name)
        lat = item.get("Latitude") or item.get("latitude") or item.get("lat")
        lon = item.get("Longitude") or item.get("longitude") or item.get("lng") or item.get("lon")
        try:
            lat_float = float(lat)
            lon_float = float(lon)
        except (ValueError, TypeError):
            lat_float, lon_float = None, None

        # Population Hierarchy: 1. crime_stats.json -> 2. city_data.json FallbackPopulation -> 3. Error Flag 1
        population = pop_map.get(slug)
        if not population:
            for k in ["FallbackPopulation", "fallback_population", "fallbackpopulation"]:
                if item.get(k):
                    try:
                        population = int(str(item.get(k)).replace(",", "").strip())
                        break
                    except (ValueError, TypeError):
                        pass
        if not population or population <= 0:
            population = 1  # Distinguishable error flag if population fails to resolve

        normalized.append({
            "slug": slug,
            "name": str(raw_name).strip(),
            "latitude": lat_float,
            "longitude": lon_float,
            "population": population
        })

    return normalized

def clean_wsdot_facility_name(raw_name, travel_dir):
    if not raw_name:
        return "Express Toll Lane"
    
    clean_id = str(raw_name).strip().lower()
    
    wsdot_known_map = {
        "520tp00422": "SR 520 Floating Bridge (Eastbound)",
        "520tp00421": "SR 520 Floating Bridge (Westbound)",
        "099tp03060": "SR 99 Tunnel (Southbound)",
        "099tp03268": "SR 99 Tunnel (Northbound)",
        "509tp02050": "SR 509 Expressway (Southbound)",
        "509tp02051": "SR 509 Expressway (Southbound)",
        "509tp02092": "SR 509 Expressway (Southbound)",
        "509tp02093": "SR 509 Expressway (Southbound)",
    }
    
    if clean_id in wsdot_known_map:
        return wsdot_known_map[clean_id]
        
    if "405" in clean_id or clean_id.startswith("405tp"):
        dir_str = f" ({travel_dir})" if travel_dir else ""
        return f"I-405 Express Toll Lane{dir_str}"
    elif "167" in clean_id or clean_id.startswith("167tp"):
        dir_str = f" ({travel_dir})" if travel_dir else ""
        return f"SR 167 HOT Lane{dir_str}"
    elif "520" in clean_id:
        dir_str = f" ({travel_dir})" if travel_dir else ""
        return f"SR 520 Floating Bridge{dir_str}"
    elif "99" in clean_id:
        dir_str = f" ({travel_dir})" if travel_dir else ""
        return f"SR 99 Tunnel{dir_str}"
        
    return str(raw_name).strip()

def harvest_commute_and_tolls(toll_schedules_from_sheet=None):
    print("🚗 Ingesting WSDOT Live Tolls & Travel Times...")
    wsdot_code = os.environ.get("WSDOT_ACCESS_CODE", "").strip().strip("'").strip('"')
    
    tolls_data = []
    travel_times_data = []

    if wsdot_code:
        # Ingest active trip rates from WSDOT GetTollTripRatesAsJson
        tolls_url = f"https://wsdot.wa.gov/Traffic/api/TollRates/TollRatesREST.svc/GetTollTripRatesAsJson?AccessCode={wsdot_code}"
        res_tolls = http_get_json_simple(tolls_url)
        
        raw_trips = []
        if isinstance(res_tolls, list):
            raw_trips = res_tolls
        elif isinstance(res_tolls, dict):
            raw_trips = res_tolls.get("Trips") or res_tolls.get("TripTollRates") or []
        
        facility_rate_map = {}
        for t in raw_trips:
            if not isinstance(t, dict):
                continue
            
            raw_facility = t.get("TripName") or t.get("LocationName") or t.get("FacilityName") or ""
            travel_dir = t.get("TravelDirection") or t.get("Direction") or ""
            facility_name = clean_wsdot_facility_name(raw_facility, travel_dir)
            
            cents = 0
            if "Toll" in t and t["Toll"] is not None:
                try:
                    cents = int(round(float(t["Toll"]) * 100))
                except (ValueError, TypeError):
                    cents = 0
            elif "CurrentTollCents" in t and t["CurrentTollCents"] is not None:
                cents = int(t["CurrentTollCents"])
            elif "TripTollCents" in t and t["TripTollCents"] is not None:
                cents = int(t["TripTollCents"])

            dollars = round(cents / 100.0, 2)
            sign_msg = t.get("TollSignMessage") or t.get("Message") or f"${dollars:.2f}"

            if cents > 0:
                key = f"{facility_name}_{travel_dir}"
                if key not in facility_rate_map or cents > facility_rate_map[key]["current_toll_cents"]:
                    facility_rate_map[key] = {
                        "facility": facility_name,
                        "travel_direction": travel_dir,
                        "current_toll_cents": cents,
                        "current_toll_dollars": dollars,
                        "sign_message": sign_msg
                    }

        tolls_data = list(facility_rate_map.values())

        # Ingest WSDOT Corridor Travel Times
        tt_url = f"https://wsdot.wa.gov/Traffic/api/TravelTimes/TravelTimesREST.svc/GetTravelTimesAsJson?AccessCode={wsdot_code}"
        raw_tt = http_get_json_simple(tt_url)
        if raw_tt and isinstance(raw_tt, list):
            for route in raw_tt:
                name = route.get("Description") or route.get("Title") or f"Route #{route.get('TravelTimeID')}"
                avg_min = route.get("AverageTime", 0)
                curr_min = route.get("CurrentTime", 0)
                
                friction_score = 0
                if avg_min > 0 and curr_min > 0:
                    delay_ratio = curr_min / float(avg_min)
                    friction_score = min(100, max(0, round((delay_ratio - 1.0) * 100)))

                travel_times_data.append({
                    "route_id": route.get("TravelTimeID"),
                    "route_name": name,
                    "distance_miles": route.get("Distance"),
                    "average_time_mins": avg_min,
                    "current_time_mins": curr_min,
                    "commute_friction_score": friction_score,
                    "status": "Free Flowing" if friction_score <= 15 else ("Moderate Delay" if friction_score <= 40 else "Heavy Congestion")
                })

    # Preserve or set static rate schedules from Google Sheet TollData tab
    static_schedules = toll_schedules_from_sheet if toll_schedules_from_sheet else []
    if not static_schedules and os.path.exists(COMMUTE_TOLLS_PATH):
        try:
            with open(COMMUTE_TOLLS_PATH, "r", encoding="utf-8") as f:
                prev_data = json.load(f)
                static_schedules = prev_data.get("static_rate_schedules", [])
        except Exception:
            pass

    output = {
        "live_express_tolls": tolls_data,
        "static_rate_schedules": static_schedules,
        "commute_corridors": travel_times_data,
        "last_updated": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
    
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(COMMUTE_TOLLS_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"   ✅ Commute corridors ({len(travel_times_data)}) & Live Tolls ({len(tolls_data)}) fresh.")

def load_sheets_admin_config_local():
    """Reads local data/city_feeds.json and data/transit_data.json backups."""
    config = {"feeds": {}, "transit_rules": {}}

    if os.path.exists(CITY_FEEDS_PATH):
        try:
            with open(CITY_FEEDS_PATH, "r", encoding="utf-8") as f:
                feeds_list = json.load(f)
                for row_dict in feeds_list:
                    feed_id = row_dict.get("Feed ID", "").strip()
                    if feed_id:
                        config["feeds"][feed_id] = {
                            "name": row_dict.get("Feed Name", "").strip(),
                            "active": str(row_dict.get("Active", "Yes")).strip().lower() == "yes",
                            "city": row_dict.get("City", "").strip()
                        }
        except Exception as e:
            print(f"Local City Feeds Read Notice: {e}")

    if os.path.exists(TRANSIT_DATA_PATH):
        try:
            with open(TRANSIT_DATA_PATH, "r", encoding="utf-8") as f:
                transit_list = json.load(f)
                for row_dict in transit_list:
                    route_id = row_dict.get("Route ID", "").strip() or row_dict.get("Feed ID", "").strip()
                    try:
                        seats = int(str(row_dict.get("Default Seats", "40")).strip() or 40)
                    except ValueError:
                        seats = 40
                    if route_id:
                        config["transit_rules"][route_id] = {
                            "agency": row_dict.get("Agency", "").strip(),
                            "mode": row_dict.get("Transit Mode", "").strip(),
                            "name": row_dict.get("Route Name", "").strip(),
                            "seats": seats,
                            "include_in_score": str(row_dict.get("Active Transit Score", "Yes")).strip().lower() == "yes",
                            "active": str(row_dict.get("Active", "Yes")).strip().lower() == "yes",
                            "api_endpoint_url": row_dict.get("API Endpoint URL", "").strip(),
                            "target_scope": row_dict.get("Target Scope", "").strip(),
                            "target": row_dict.get("Target", "").strip()
                        }
        except Exception as e:
            print(f"Local Transit Data Read Notice: {e}")

    return config

def harvest_transit_radar(cities, city_boundaries, sheets_config):
    print("🚆 Harvesting OneBusAway GTFS-RT Transit Positions & Schedule Deviation...")
    oba_key = os.environ.get("ONEBUSAWAY_API_KEY", "").strip().strip("'").strip('"') or "TEST"
    
    all_agencies = {
        "1": "King County Metro", "29": "Sound Transit", "23": "Community Transit",
        "13": "Everett Transit", "10": "Seattle Center Monorail",
        "96": "King County Water Taxi", "95": "Kitsap Fast Ferries"
    }
    
    transit_rules = sheets_config.get("transit_rules", {})
    city_map = {
        c["slug"]: {
            "name": c["name"],
            "population": c["population"],
            "ground_vehicles": [],
            "ground_seats": 0,
            "on_time_ground_vehicles": 0,
            "delayed_ground_vehicles": 0,
            "early_ground_vehicles": 0,
            "maritime_vessels": [],
            "maritime_seats": 0
        } for c in cities
    }
    total_vehicles = 0

    for agency_id, agency_name in all_agencies.items():
        oba_url = f"https://api.pugetsound.onebusaway.org/api/where/vehicles-for-agency/{agency_id}.json?key={oba_key}"
        res = http_get_json_simple(oba_url, timeout=20)
        
        if not res or not isinstance(res, dict) or res.get("code") != 200:
            continue
            
        data = res.get("data", {})
        v_list = data.get("list", []) if isinstance(data, dict) else []

        for v in v_list:
            loc = v.get("location") or {}
            vlat, vlon = loc.get("lat"), loc.get("lon")
            if vlat is None or vlon is None:
                continue
                
            try:
                vlat, vlon = float(vlat), float(vlon)
            except (ValueError, TypeError):
                continue
                
            trip_status = v.get("tripStatus") or {}
            route_id = str(trip_status.get("activeTrip", {}).get("routeId") or "").strip()
            
            dev_sec = trip_status.get("scheduleDeviation")
            if dev_sec is not None:
                try:
                    dev_sec = int(dev_sec)
                except (ValueError, TypeError):
                    dev_sec = 0
            else:
                dev_sec = 0
            
            include_in_score = True
            if "40_100479" in route_id:
                rule = transit_rules.get("40_100479") or transit_rules.get("link-1line") or {}
                seat_capacity = rule.get("seats", 592)
                include_in_score = rule.get("include_in_score", True)
            elif "40_100511" in route_id:
                rule = transit_rules.get("40_100511") or transit_rules.get("link-2line") or {}
                seat_capacity = rule.get("seats", 296)
                include_in_score = rule.get("include_in_score", True)
            elif "40_100224" in route_id or "40_100225" in route_id:
                rule = transit_rules.get("40_100224") or transit_rules.get("sounder-north") or {}
                seat_capacity = rule.get("seats", 560)
                include_in_score = rule.get("include_in_score", True)
            elif agency_id == "10":
                rule = transit_rules.get("10_MONORAIL") or transit_rules.get("monorail") or {}
                seat_capacity = rule.get("seats", 250)
                include_in_score = rule.get("include_in_score", True)
            elif agency_id == "23":
                rule = transit_rules.get("23_SWIFT") or transit_rules.get("swift-brt") or {}
                seat_capacity = rule.get("seats", 60)
                include_in_score = rule.get("include_in_score", True)
            elif agency_id == "29":
                rule = transit_rules.get("40_ST_BUS") or transit_rules.get("st-express") or {}
                seat_capacity = rule.get("seats", 55)
                include_in_score = rule.get("include_in_score", True)
            elif agency_id == "96":
                rule = transit_rules.get("96_WATERTAXI") or transit_rules.get("kc-watertaxi") or {}
                seat_capacity = rule.get("seats", 278)
                include_in_score = rule.get("include_in_score", False)
            elif agency_id == "95":
                rule = transit_rules.get("95_FASTFERRY") or transit_rules.get("kitsap-fastferry") or {}
                seat_capacity = rule.get("seats", 250)
                include_in_score = rule.get("include_in_score", False)
            else:
                seat_capacity = 40
                include_in_score = True

            matched_slug = match_city_for_point(vlat, vlon, city_boundaries)
            if matched_slug and matched_slug in city_map:
                v_obj = {
                    "vehicle_id": v.get("vehicleId"),
                    "agency": agency_name,
                    "route_id": route_id,
                    "latitude": vlat,
                    "longitude": vlon,
                    "seats": seat_capacity,
                    "schedule_deviation_sec": dev_sec
                }
                
                if include_in_score:
                    city_map[matched_slug]["ground_vehicles"].append(v_obj)
                    city_map[matched_slug]["ground_seats"] += seat_capacity
                    
                    if -60 <= dev_sec <= 300:
                        city_map[matched_slug]["on_time_ground_vehicles"] += 1
                    elif dev_sec > 300:
                        city_map[matched_slug]["delayed_ground_vehicles"] += 1
                    else:
                        city_map[matched_slug]["early_ground_vehicles"] += 1
                else:
                    city_map[matched_slug]["maritime_vessels"].append(v_obj)
                    city_map[matched_slug]["maritime_seats"] += seat_capacity
                    
                total_vehicles += 1

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    live_output = {}
    
    for slug, details in city_map.items():
        pop = details["population"]
        pop_units = max(1.0, pop / 1000.0)
        ground_seats = details["ground_seats"]
        ground_vehicle_count = len(details["ground_vehicles"])
        on_time_count = details["on_time_ground_vehicles"]
        
        raw_seats_per_1k = round(ground_seats / pop_units, 2)
        normalized_transit_score = min(100, round((raw_seats_per_1k / 50.0) * 100))
        active_on_time_score = round((on_time_count / ground_vehicle_count) * 100) if ground_vehicle_count > 0 else 100
        
        live_output[slug] = {
            "name": details["name"],
            "active_vehicles": ground_vehicle_count,
            "active_in_bounds_seats": ground_seats,
            "population_official": pop,
            "raw_seats_per_1k": raw_seats_per_1k,
            "active_transit_score": normalized_transit_score,
            "on_time_performance": {
                "active_on_time_score": active_on_time_score,
                "tracked_vehicles": ground_vehicle_count,
                "on_time_vehicles": on_time_count,
                "delayed_vehicles": details["delayed_ground_vehicles"],
                "early_vehicles": details["early_ground_vehicles"]
            },
            "maritime_capacity": {
                "active_vessels": len(details["maritime_vessels"]),
                "active_seats": details["maritime_seats"]
            },
            "last_updated": now_utc.isoformat()
        }

    target_live = os.path.join(DATA_DIR, "transit_radar_live.json")
    with open(target_live, "w", encoding="utf-8") as f:
        json.dump(live_output, f, indent=2, ensure_ascii=False)
    print(f"   ✅ Tracked {total_vehicles} active vehicles. transit_radar_live.json fresh.")

    # 168-Hour Rolling Historical Archive Engine
    print("📈 Processing 168-Hour Rolling Historical Archive (transit_radar_history.json)...")
    slot_dt = now_utc.replace(minute=0, second=0, microsecond=0)
    slot_iso = slot_dt.isoformat()
    day_of_week = slot_dt.strftime("%A")
    hour_of_day = slot_dt.hour

    history_data = {}
    if os.path.exists(TRANSIT_HISTORY_PATH):
        try:
            with open(TRANSIT_HISTORY_PATH, "r", encoding="utf-8") as f:
                history_data = json.load(f)
        except Exception as e:
            print(f"History Load Notice: {e}. Re-initializing history data.")
            history_data = {}

    for slug, live_entry in live_output.items():
        if slug not in history_data or not isinstance(history_data[slug], list):
            history_data[slug] = []

        city_hist = history_data[slug]

        if len(city_hist) > 0:
            last_entry = city_hist[-1]
            last_ts_str = last_entry.get("timestamp", "")
            if last_ts_str:
                try:
                    last_dt = datetime.datetime.fromisoformat(last_ts_str.replace("Z", "+00:00"))
                    curr_gap_dt = last_dt + timedelta(hours=1)
                    
                    while curr_gap_dt < slot_dt:
                        gap_iso = curr_gap_dt.isoformat()
                        city_hist.append({
                            "timestamp": gap_iso,
                            "day_of_week": curr_gap_dt.strftime("%A"),
                            "hour_of_day": curr_gap_dt.hour,
                            "active_transit_score": None,
                            "active_on_time_score": None,
                            "active_vehicles": 0,
                            "active_seats": 0,
                            "data_available": False
                        })
                        curr_gap_dt += timedelta(hours=1)
                except Exception as e:
                    print(f"Gap calculation notice for {slug}: {e}")

        current_record = {
            "timestamp": slot_iso,
            "day_of_week": day_of_week,
            "hour_of_day": hour_of_day,
            "active_transit_score": live_entry["active_transit_score"],
            "active_on_time_score": live_entry["on_time_performance"]["active_on_time_score"],
            "active_vehicles": live_entry["active_vehicles"],
            "active_seats": live_entry["active_in_bounds_seats"],
            "data_available": True
        }

        if len(city_hist) > 0 and city_hist[-1].get("timestamp") == slot_iso:
            city_hist[-1] = current_record
        else:
            city_hist.append(current_record)

        history_data[slug] = city_hist[-168:]

    with open(TRANSIT_HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history_data, f, indent=2, ensure_ascii=False)
    print("   ✅ 168-Hour Rolling Archive synchronized.")

def harvest_intercity_summary():
    print("✈️ Ingesting FAA NAS Status API & Intercity Regional Summary...")
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    
    intercity = {
        "airports": {
            "seatac_sea": {
                "name": "Seattle-Tacoma International Airport (SEA)",
                "faa_code": "SEA",
                "status": "Normal Operations",
                "delay_type": "None",
                "avg_delay_minutes": 0,
                "weather": "VFR Fair",
                "flightaware_url": "https://www.flightaware.com/live/airport/KSEA"
            },
            "paine_field_pae": {
                "name": "Paine Field Passenger Terminal (PAE)",
                "faa_code": "PAE",
                "status": "Normal Operations",
                "delay_type": "None",
                "avg_delay_minutes": 0,
                "weather": "VFR Fair",
                "flightaware_url": "https://www.flightaware.com/live/airport/KPAE"
            }
        },
        "amtrak": {
            "agency": "Amtrak Cascades",
            "corridor": "Vancouver BC - Seattle - Portland - Eugene",
            "status": "Normal Operations",
            "amtrak_map_url": "https://www.amtrak.com/track-your-train.html"
        },
        "last_updated": now_utc.isoformat()
    }

    faa_url = "https://nasstatus.faa.gov/api/airport-status"
    faa_data = http_get_json_simple(faa_url, timeout=15)
    
    if faa_data and isinstance(faa_data, list):
        for apt in faa_data:
            code = str(apt.get("arpt", "")).upper()
            if code in ["SEA", "PAE"]:
                key = "seatac_sea" if code == "SEA" else "paine_field_pae"
                
                status_str = "Normal Operations"
                delay_type = "None"
                
                if apt.get("delay") == "true" or apt.get("delay") is True:
                    status_str = "Minor Delays"
                    if "GROUND_DELAY" in str(apt).upper():
                        status_str = "Ground Delay Program"
                        delay_type = "FAA Ground Delay"
                    elif "STOP" in str(apt).upper():
                        status_str = "Ground Stop"
                        delay_type = "Ground Stop"

                weather_str = apt.get("weather", {}).get("weather", {}).get("temp", "VFR Fair") if isinstance(apt.get("weather"), dict) else "VFR Fair"

                intercity["airports"][key]["status"] = status_str
                intercity["airports"][key]["delay_type"] = delay_type
                intercity["airports"][key]["weather"] = str(weather_str)

    with open(INTERCITY_SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump(intercity, f, indent=2, ensure_ascii=False)
    print("   ✅ Intercity Regional Summary (intercity_summary.json) fresh.")

def get_col_letter(col_idx):
    result = ""
    col_idx += 1
    while col_idx > 0:
        remainder = (col_idx - 1) % 26
        result = chr(65 + remainder) + result
        col_idx = (col_idx - 1) // 26
    return result

def clean_nan_tokens(node):
    if isinstance(node, dict):
        return {k: clean_nan_tokens(v) for k, v in node.items()}
    elif isinstance(node, list):
        return [clean_nan_tokens(element) for element in node]
    elif isinstance(node, float) and (math.isnan(node) or math.isinf(node)):
        return None
    return node

def generate_url_slug(text_input):
    processed = str(text_input).lower().strip()
    processed = re.sub(r'[^a-z0-9\s-]', '', processed)
    return re.sub(r'[\s-]+', '-', processed)

def extract_google_id(url_string):
    if not isinstance(url_string, str):
        return None
    match = re.search(r'/d/([a-zA-Z0-9_-]+)', url_string)
    if match:
        return match.group(1)
    match = re.search(r'id=([a-zA-Z0-9_-]+)', url_string)
    if match:
        return match.group(1)
    return None

def extract_youtube_id(url_string):
    if not isinstance(url_string, str) or not url_string.strip():
        return None
    pattern = r'(?:v=|\/embed\/|\/v\/|\/vi\/|youtu\.be\/|\/shorts\/)([a-zA-Z0-9_-]{11})'
    match = re.search(pattern, url_string.strip())
    return match.group(1) if match else None

def is_google_drive_link(url_string):
    if not isinstance(url_string, str) or not url_string.strip():
        return False
    u = url_string.lower().strip()
    if "assets.myseattlesearch.com" in u:
        return False
    return "drive.google.com" in u or "docs.google.com" in u or "drive.usercontent.google.com" in u or extract_google_id(url_string) is not None

def apply_markdown_style(content, style_type, url=None):
    if not content or content.isspace():
        return content
    match = re.match(r'^(\s*)(.*?)(\s*)$', content, re.DOTALL)
    if match:
        lead, core, trail = match.groups()
        if style_type == 'bold':
            core = f"**{core}**"
        elif style_type == 'italic':
            core = f"*{core}*"
        elif style_type == 'link' and url:
            core = core.replace('[', '').replace(']', '')
            core = f"[{core}]({url})"
        return f"{lead}{core}{trail}"
    return content

def get_google_doc_as_markdown(docs_service, doc_url):
    doc_id = extract_google_id(doc_url)
    if not doc_id:
        return ""
    try:
        doc = docs_service.documents().get(documentId=doc_id).execute()
        elements = doc.get('body', {}).get('content', [])
        markdown_text = []
        for element in elements:
            if 'paragraph' in element:
                paragraph = element['paragraph']
                named_style = paragraph.get('paragraphStyle', {}).get('namedStyleType', 'NORMAL_TEXT')
                p_text = ""
                for p_element in paragraph.get('elements', []):
                    if 'textRun' in p_element:
                        text_run = p_element['textRun']
                        content = text_run.get('content', '')
                        style = text_run.get('textStyle', {})
                        if style.get('bold'):
                            content = apply_markdown_style(content, 'bold')
                        if style.get('italic'):
                            content = apply_markdown_style(content, 'italic')
                        if 'link' in style and 'url' in style['link']:
                            content = apply_markdown_style(content, 'link', style['link']['url'])
                        p_text += content
                if named_style == 'HEADING_1':
                    markdown_text.append(f"# {p_text.strip()}\n\n")
                elif named_style == 'HEADING_2':
                    markdown_text.append(f"## {p_text.strip()}\n\n")
                elif named_style == 'HEADING_3':
                    markdown_text.append(f"### {p_text.strip()}\n\n")
                else:
                    markdown_text.append(p_text)
        return "".join(markdown_text)
    except Exception as e:
        print(f"   ⚠️ Warning: Doc parsing fault on ID {doc_id}: {e}")
        return ""

def process_and_upload_image(drive_service, s3_client, r2_bucket, image_url, folder_name, filename_slug, index=1):
    file_id = extract_google_id(image_url)
    if not file_id:
        return image_url
        
    custom_domain = "https://assets.myseattlesearch.com"
    object_key = f"{folder_name.lower()}/{filename_slug}-img-{index}.webp"
    permanent_url = f"{custom_domain}/{object_key}"
    
    try:
        request = drive_service.files().get_media(fileId=file_id)
        raw_bytes = request.execute()
        
        if isinstance(raw_bytes, str) or raw_bytes.startswith(b"<!DOCTYPE") or raw_bytes.startswith(b"<html") or raw_bytes.startswith(b"{"):
            print(f"   ⚠️ Non-image byte stream returned from Drive for ID {file_id}. Preserving original URL.")
            return image_url

        file_stream = io.BytesIO(raw_bytes)
        img = Image.open(file_stream)
        img = img.convert("RGBA") if img.mode in ("RGBA", "P") else img.convert("RGB")
        
        webp_buffer = io.BytesIO()
        img.save(webp_buffer, format="WEBP", quality=80)
        webp_buffer.seek(0)
        
        s3_client.put_object(
            Bucket=r2_bucket,
            Key=object_key,
            Body=webp_buffer,
            ContentType="image/webp"
        )
        print(f"   🚀 WebP uploaded safely to R2 bucket path: {permanent_url}")

        try:
            drive_service.files().delete(fileId=file_id).execute()
            print(f"   🗑️ Successfully purged source Drive image file (ID: {file_id})")
        except Exception as del_err:
            print(f"   ⚠️ Drive deletion notice for file ID {file_id}: {del_err}")

        return permanent_url
    except Exception as e:
        print(f"   ❌ Image optimization fallback triggered on ID {file_id}: {e}")
        return image_url

def process_and_upload_pdf(drive_service, s3_client, r2_bucket, pdf_url, mls_number, index=1):
    file_id = extract_google_id(pdf_url)
    if not file_id:
        filename = pdf_url.split('/')[-1].split('?')[0]
        title = filename.replace('.pdf', '').replace('.PDF', '').replace('_', ' ').replace('-', ' ').title()
        return pdf_url, title or f"Document {index}"

    custom_domain = "https://assets.myseattlesearch.com"
    
    try:
        file_meta = drive_service.files().get(fileId=file_id, fields="name").execute()
        original_name = file_meta.get("name", f"Document_{index}.pdf")
        clean_name = re.sub(r'[^a-zA-Z0-9._-]', '_', original_name)
        if not clean_name.lower().endswith('.pdf'):
            clean_name += '.pdf'

        object_key = f"downloads/{str(mls_number).strip()}/{clean_name}"
        permanent_url = f"{custom_domain}/{object_key}"

        request = drive_service.files().get_media(fileId=file_id)
        raw_bytes = request.execute()

        s3_client.put_object(
            Bucket=r2_bucket,
            Key=object_key,
            Body=raw_bytes,
            ContentType="application/pdf"
        )
        print(f"   📄 PDF uploaded safely to R2 bucket path: {permanent_url}")

        try:
            drive_service.files().delete(fileId=file_id).execute()
            print(f"   🗑️ Successfully purged source Drive PDF file (ID: {file_id})")
        except Exception as del_err:
            print(f"   ⚠️ Drive deletion notice for PDF ID {file_id}: {del_err}")

        display_title = original_name.replace('.pdf', '').replace('.PDF', '').replace('_', ' ').replace('-', ' ').title()
        return permanent_url, display_title
    except Exception as e:
        print(f"   ❌ PDF optimization fallback triggered on ID {file_id}: {e}")
        return pdf_url, f"Document {index}"

def parse_sheet_values(rows):
    if not rows:
        return []
    headers = [str(h).strip() for h in rows[0]]
    records = []
    for row in rows[1:]:
        padded = list(row) + [""] * (len(headers) - len(row))
        sanitized = [str(item).strip() if item is not None else "" for item in padded]
        records.append(dict(zip(headers, sanitized)))
    return records

def publish_to_facebook(page_id, access_token, text, link=None, image_url=None):
    if not page_id or not access_token:
        print("   ⚠️ Facebook credentials missing. Skipping FB publish.")
        return None

    page_id = page_id.strip()
    access_token = access_token.strip()

    if image_url and not image_url.startswith("https://assets.myseattlesearch.com"):
        image_url = None

    try:
        if image_url:
            url = f"https://graph.facebook.com/v19.0/{page_id}/photos"
            payload = {"url": image_url, "caption": text, "access_token": access_token}
        else:
            url = f"https://graph.facebook.com/v19.0/{page_id}/feed"
            payload = {"message": text, "access_token": access_token}
            if link:
                payload["link"] = link

        res = requests.post(url, data=payload, timeout=15)
        res_data = res.json()

        if res.status_code == 200 and "id" in res_data:
            print(f"   ✅ Facebook post published successfully! Post ID: {res_data['id']}")
            return res_data["id"]
        else:
            print(f"   ❌ Facebook API Error: {res_data}")
            return None
    except Exception as e:
        print(f"   ❌ Exception during Facebook publish: {e}")
        return None

def publish_to_threads(user_id, access_token, text, image_url=None):
    if not user_id or not access_token:
        print("   ⚠️ Threads credentials missing. Skipping Threads publish.")
        return None

    user_id = user_id.strip()
    access_token = access_token.strip()

    if image_url and not image_url.startswith("https://assets.myseattlesearch.com"):
        image_url = None

    try:
        container_url = f"https://graph.threads.net/v1.0/{user_id}/threads"
        if image_url:
            c_payload = {"media_type": "IMAGE", "image_url": image_url, "text": text, "access_token": access_token}
        else:
            c_payload = {"media_type": "TEXT", "text": text, "access_token": access_token}

        c_res = requests.post(container_url, data=c_payload, timeout=15)
        c_data = c_res.json()
        container_id = c_data.get("id")

        if not container_id:
            print(f"   ❌ Threads Container Creation Error: {c_data}")
            return None

        time.sleep(3)

        pub_url = f"https://graph.threads.net/v1.0/{user_id}/threads_publish"
        p_payload = {"creation_id": container_id, "access_token": access_token}
        p_res = requests.post(pub_url, data=p_payload, timeout=15)
        p_data = p_res.json()
        post_id = p_data.get("id")

        if p_res.status_code == 200 and post_id:
            print(f"   ✅ Threads post published successfully! Thread ID: {post_id}")
            return post_id
        else:
            print(f"   ❌ Threads Publish Error: {p_data}")
            return None
    except Exception as e:
        print(f"   ❌ Exception during Threads publish: {e}")
        return None

def publish_to_linkedin(author_urn, access_token, text, link=None, title=None):
    if not author_urn or not access_token:
        print("   ⚠️ LinkedIn credentials missing. Skipping LinkedIn publish.")
        return None

    author_urn = author_urn.strip()
    access_token = access_token.strip()

    if author_urn.startswith("urn:li:person:"):
        author_urn = author_urn.replace("urn:li:person:", "urn:li:member:")
    elif not author_urn.startswith("urn:li:"):
        author_urn = f"urn:li:member:{author_urn}"

    try:
        url = "https://api.linkedin.com/v2/posts"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }

        payload = {
            "author": author_urn,
            "commentary": text,
            "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED",
        }

        if link:
            payload["content"] = {"article": {"source": link, "title": title or "MySeattleSearch Update"}}

        res = requests.post(url, headers=headers, json=payload, timeout=15)
        if res.status_code in (200, 201):
            post_id = res.headers.get("x-restli-id") or res.json().get("id") or "published"
            print(f"   ✅ LinkedIn post published successfully! Post URN: {post_id}")
            return post_id
        else:
            print(f"   ❌ LinkedIn API Error ({res.status_code}): {res.text}")
            return None
    except Exception as e:
        print(f"   ❌ Exception during LinkedIn publish: {e}")
        return None

def main():
    print("🧠 Starting the MySeattleSearch Master Omnibus Data Engine...")
    data_dir = "data"
    posts_dir = "posts"
    editorials_dir = os.path.join(data_dir, "editorials")
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(posts_dir, exist_ok=True)
    os.makedirs(editorials_dir, exist_ok=True)

    # --------------------------------------------------------------------
    # MODULE 0A: STANDALONE WEATHER, TIDES, AQI & RIVER GAUGES HARVESTER
    # --------------------------------------------------------------------
    try:
        harvest_weather_data()
    except Exception as e:
        print(f"   ❌ Standalone Weather/Environment Harvester Error: {e}")

    # --------------------------------------------------------------------
    # MODULE 0B: TRANSIT RADAR, 168H HISTORY & INTERCITY SUMMARY
    # --------------------------------------------------------------------
    cities = load_city_data()
    city_boundaries = load_city_boundaries()
    sheets_config = load_sheets_admin_config_local()

    if cities and city_boundaries:
        try:
            harvest_transit_radar(cities, city_boundaries, sheets_config)
        except Exception as e:
            print(f"   ❌ Transit Radar harvest error: {e}")

    try:
        harvest_intercity_summary()
    except Exception as e:
        print(f"   ❌ Intercity summary harvest error: {e}")

    creds_path = "credentials.json"
    if not os.path.exists(creds_path):
        print("❌ Core Error: credentials.json identity file is missing from root path.")
        return

    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/documents.readonly',
        'https://www.googleapis.com/auth/drive'
    ]

    try:
        creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
        sheets_service = build('sheets', 'v4', credentials=creds)
        docs_service = build('docs', 'v1', credentials=creds)
        drive_service = build('drive', 'v3', credentials=creds)
    except Exception as auth_err:
        print(f"❌ Core Error: Cloud authorization handshake failed: {auth_err}")
        return

    r2_access_key = os.environ.get("R2_ACCESS_KEY_ID")
    r2_secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
    r2_endpoint = os.environ.get("R2_ENDPOINT_URL")
    r2_bucket = os.environ.get("R2_BUCKET_NAME")
    s3_client = None
    if all([r2_access_key, r2_secret_key, r2_endpoint, r2_bucket]):
        s3_client = boto3.client(
            "s3", endpoint_url=r2_endpoint,
            aws_access_key_id=r2_access_key, aws_secret_access_key=r2_secret_key,
            region_name="auto"
        )

    batch_sheet_writebacks = {}
    cms_image_map = {}

    # ====================================================================
    # MODULE 1: COMMAND CENTER INGESTION
    # ====================================================================
    cc_sheet_id = os.environ.get("COMMAND_CENTER_SHEET_ID")
    if cc_sheet_id:
        print("📡 Pulling market data, interest rates, and historical logs from Command Center Workbook...")
        try:
            cc_ranges = ["Market_Dashboard!A:Z", "Rates!A:Z", "Historical_Log!A:Z"]
            cc_batch = sheets_service.spreadsheets().values().batchGet(
                spreadsheetId=cc_sheet_id, ranges=cc_ranges
            ).execute().get('valueRanges', [])

            market_rows = cc_batch[0].get('values', []) if len(cc_batch) > 0 else []
            rates_rows = cc_batch[1].get('values', []) if len(cc_batch) > 1 else []
            hist_rows = cc_batch[2].get('values', []) if len(cc_batch) > 2 else []

            if market_rows:
                market_data = parse_sheet_values(market_rows)
                with open(os.path.join(data_dir, "hourly_market.json"), "w", encoding="utf-8") as f:
                    json.dump(market_data, f, indent=2, ensure_ascii=False)
            if rates_rows:
                rates_data = parse_sheet_values(rates_rows)
                with open(os.path.join(data_dir, "hourly_rates.json"), "w", encoding="utf-8") as f:
                    json.dump(rates_data, f, indent=2, ensure_ascii=False)
            if hist_rows:
                hist_data = parse_sheet_values(hist_rows)
                with open(os.path.join(data_dir, "hourly_market_historical.json"), "w", encoding="utf-8") as f:
                    json.dump(hist_data, f, indent=2, ensure_ascii=False)
            print("   ✅ Command Center indices successfully synchronized.")
        except Exception as e:
            print(f"   ⚠️ Warning: Command Center download pass skipped: {e}")

    # ====================================================================
    # MODULE 1B: CITY DATA WORKBOOK & GOOGLE DOCS EDITORIAL INGESTION
    # ====================================================================
    city_sheet_id = os.environ.get("CITY_DATA_SHEET_ID")
    if city_sheet_id:
        print("📡 Ingesting CityData workbook and checking for pending Google Doc editorials...")
        try:
            if city_sheet_id not in batch_sheet_writebacks:
                batch_sheet_writebacks[city_sheet_id] = []

            rows = sheets_service.spreadsheets().values().get(
                spreadsheetId=city_sheet_id, range="CityData!A:AZ"
            ).execute().get('values', [])

            if rows and len(rows) >= 2:
                headers = [str(h).strip() for h in rows[0]]
                parsed_city_data = parse_sheet_values(rows)

                # Synchronize local city_data.json
                with open(CITY_DATA_PATH, "w", encoding="utf-8") as f:
                    json.dump(clean_nan_tokens(parsed_city_data), f, indent=2, ensure_ascii=False)
                print(f"   ✅ Synchronized {len(parsed_city_data)} cities into data/city_data.json.")

                # Locate EditorialStatus column index dynamically for writebacks
                col_status_idx = -1
                for candidate in ["EditorialStatus", "Editorial Status", "Editorial_Status"]:
                    if candidate in headers:
                        col_status_idx = headers.index(candidate)
                        break

                for idx, r in enumerate(rows[1:]):
                    padded = list(r) + [""] * (len(headers) - len(r))
                    record = dict(zip(headers, padded))
                    row_num = idx + 2

                    city_name = record.get("City", "").strip()
                    if not city_name:
                        continue

                    slug = slugify(city_name)
                    doc_url = record.get("Editorial", "").strip()
                    status = (record.get("EditorialStatus", "") or record.get("Editorial Status", "") or record.get("Editorial_Status", "")).strip()

                    # Ingest pending editorial Google Doc
                    if doc_url and is_google_drive_link(doc_url) and status.lower() == "pending":
                        print(f"   ✍️ Downloading pending editorial Google Doc for {city_name} ({slug})...")
                        md_content = get_google_doc_as_markdown(docs_service, doc_url)

                        if md_content and md_content.strip():
                            out_md_path = os.path.join(editorials_dir, f"{slug}.md")
                            with open(out_md_path, "w", encoding="utf-8") as f_md:
                                f_md.write(md_content)
                            print(f"   ✅ Saved editorial Markdown for {city_name} -> data/editorials/{slug}.md")

                            # Queue writeback to Google Sheet setting EditorialStatus to "Complete"
                            if col_status_idx != -1:
                                cell_range = f"CityData!{get_col_letter(col_status_idx)}{row_num}"
                                batch_sheet_writebacks[city_sheet_id].append({
                                    'range': cell_range,
                                    'values': [["Complete"]]
                                })

        except Exception as e:
            print(f"   ❌ CityData ingestion and Google Doc harvester fault: {e}")

    # ====================================================================
    # MODULE 2: WEBSITE DATA SHEET MULTI-TAB INGESTION
    # ====================================================================
    web_sheet_id = os.environ.get("WEBSITE_DATA_SHEET_ID")
    team_lookup = {}
    if web_sheet_id:
        print("📡 Ingesting multi-tab dataset from the Website Data Workbook...")
        target_tabs = ["Stats", "Team", "Disclaimers", "Events", "Celebrations", "DPA", "Professionals", "Reviews", "ThirdPartyPrograms", "News", "Sales", "Live_Archive", "Uploads", "Sports", "TollData"]
        try:
            web_ranges = [f"{tab}!A:AZ" for tab in target_tabs]
            web_batch = sheets_service.spreadsheets().values().batchGet(
                spreadsheetId=web_sheet_id, ranges=web_ranges
            ).execute().get('valueRanges', [])

            tabs_data = dict(zip(target_tabs, web_batch))
            if web_sheet_id not in batch_sheet_writebacks:
                batch_sheet_writebacks[web_sheet_id] = []

            # Ingest static toll rate schedules directly from TollData tab
            toll_rows = tabs_data.get("TollData", {}).get('values', [])
            parsed_toll_schedules = parse_sheet_values(toll_rows) if toll_rows else []
            
            # Execute commute corridors and live tolls harvester with dynamic TollData schedule
            try:
                harvest_commute_and_tolls(parsed_toll_schedules)
            except Exception as e:
                print(f"   ❌ Commute & Tolls Harvester Error: {e}")

            # A. Process Team roster profiles
            team_rows = tabs_data.get("Team", {}).get('values', [])
            if team_rows:
                headers = [h.strip() for h in team_rows[0]]
                photo_col_idx = headers.index("Photo") if "Photo" in headers else -1
                compiled_team = []
                for idx, r in enumerate(team_rows[1:]):
                    padded = list(r) + [""] * (len(headers) - len(r))
                    row_dict = dict(zip(headers, padded))
                    row_num = idx + 2
                    member_name = row_dict.get("Name", "").strip()
                    if not member_name: continue
                    slug = generate_url_slug(member_name)
                    photo_url = row_dict.get("Photo", "").strip()
                    if photo_url and is_google_drive_link(photo_url) and s3_client:
                        r2_url = process_and_upload_image(drive_service, s3_client, r2_bucket, photo_url, "Team", slug)
                        if "assets.myseattlesearch.com" in r2_url:
                            row_dict["Photo"] = r2_url
                            batch_sheet_writebacks[web_sheet_id].append({
                                'range': f"Team!{get_col_letter(photo_col_idx)}{row_num}", 'values': [[r2_url]]
                            })
                    member_obj = {
                        "id": row_dict.get("Team ID", "").strip().replace(".0", ""),
                        "teamPage": row_dict.get("Team Page", "No").strip().lower() == "yes",
                        "position": row_dict.get("Position", "").strip(), "name": member_name, "slug": slug,
                        "phone": row_dict.get("Phone", "").strip(), "email": row_dict.get("Email", "").strip(),
                        "website": row_dict.get("Website", "").strip(), "description": row_dict.get("Description", "").strip(),
                        "photo": row_dict.get("Photo", "").strip()
                    }
                    team_lookup[member_obj["id"]] = member_obj
                    compiled_team.append(member_obj)
                with open(os.path.join(data_dir, "team.json"), "w", encoding="utf-8") as f:
                    json.dump(clean_nan_tokens(compiled_team), f, indent=2, ensure_ascii=False)

            # B. Process Personal Stats Row
            stats_rows = tabs_data.get("Stats", {}).get('values', [])
            if stats_rows:
                records = parse_sheet_values(stats_rows)
                with open(os.path.join(data_dir, "stats.json"), "w", encoding="utf-8") as f:
                    json.dump(clean_nan_tokens(records[0] if records else {}), f, indent=2, ensure_ascii=False)

            # C. Process Page Disclaimers
            disc_rows = tabs_data.get("Disclaimers", {}).get('values', [])
            if disc_rows:
                disc_map = {r[0].strip(): r[1].strip() for r in disc_rows[1:] if len(r) >= 2 and r[0].strip()}
                with open(os.path.join(data_dir, "disclaimers.json"), "w", encoding="utf-8") as f:
                    json.dump(clean_nan_tokens(disc_map), f, indent=2, ensure_ascii=False)

            # D. Process Events tab
            event_rows = tabs_data.get("Events", {}).get('values', [])
            if event_rows:
                headers = [h.strip() for h in event_rows[0]]
                img_cols = [headers.index(f"Image {i} Link") for i in range(1, 4) if f"Image {i} Link" in headers]
                compiled_events = []
                for idx, r in enumerate(event_rows[1:]):
                    padded = list(r) + [""] * (len(headers) - len(r))
                    row_dict = dict(zip(headers, padded))
                    row_num = idx + 2
                    if row_dict.get("Status", "").strip().lower() != "active": continue
                    evt_id = row_dict.get("Event ID", "").strip().lower()
                    if not evt_id or evt_id == "nan": continue

                    event_images = []
                    for c_idx in img_cols:
                        img_url = padded[c_idx].strip()
                        if img_url and is_google_drive_link(img_url) and s3_client:
                            r2_url = process_and_upload_image(drive_service, s3_client, r2_bucket, img_url, "Events", f"{evt_id}-{c_idx}")
                            if "assets.myseattlesearch.com" in r2_url:
                                event_images.append(r2_url)
                                batch_sheet_writebacks[web_sheet_id].append({
                                    'range': f"Events!{get_col_letter(c_idx)}{row_num}", 'values': [[r2_url]]
                                })
                        elif img_url:
                            event_images.append(img_url)

                    hosts = [team_lookup[hid.strip()] for hid in row_dict.get("Host IDs", "").split(",") if hid.strip() in team_lookup]
                    city_val = row_dict.get("City", "").strip()

                    cities_array = [city_val.lower()] if city_val and city_val.lower() != "nan" else []
                    if "edmonds" in cities_array or "lynnwood" in cities_array or "mountlake-terrace" in cities_array:
                        if "snohomish-county" not in cities_array:
                            cities_array.append("snohomish-county")

                    compiled_events.append({
                        "id": evt_id, "type": row_dict.get("Type", "Home Buying Class"), "status": "Active",
                        "title": row_dict.get("Title", ""), "subtitle": row_dict.get("Subtitle", None),
                        "date": row_dict.get("Date", ""), "startTime": row_dict.get("Start Time", ""), "endTime": row_dict.get("End Time", ""),
                        "locationName": row_dict.get("Location Name", ""), "streetAddress": row_dict.get("Street Address", ""), "city": city_val,
                        "cities": cities_array, "display": row_dict.get("Display", "Yes").lower() == "yes",
                        "registration": row_dict.get("Registration", "Yes").lower() == "yes", "legacyLink": row_dict.get("Link", ""),
                        "description": row_dict.get("Full Description", ""), "mapsLink": row_dict.get("Google Maps Link", ""),
                        "images": event_images, "hosts": hosts
                    })
                with open(os.path.join(data_dir, "events.json"), "w", encoding="utf-8") as f:
                    json.dump(clean_nan_tokens(compiled_events), f, indent=2, ensure_ascii=False)

            # E. Process Celebrations
            cel_rows = tabs_data.get("Celebrations", {}).get('values', [])
            if cel_rows:
                records = parse_sheet_values(cel_rows)
                with open(os.path.join(data_dir, "celebrations.json"), "w", encoding="utf-8") as f:
                    json.dump(clean_nan_tokens(records), f, indent=2, ensure_ascii=False)

            # F. Process DPA Programs
            dpa_rows = tabs_data.get("DPA", {}).get('values', [])
            if dpa_rows:
                records = parse_sheet_values(dpa_rows)
                with open(os.path.join(data_dir, "dpa_programs.json"), "w", encoding="utf-8") as f:
                    json.dump(clean_nan_tokens(records), f, indent=2, ensure_ascii=False)

            # G. Process Professionals
            prof_rows = tabs_data.get("Professionals", {}).get('values', [])
            if prof_rows:
                records = parse_sheet_values(prof_rows)
                with open(os.path.join(data_dir, "professionals.json"), "w", encoding="utf-8") as f:
                    json.dump(clean_nan_tokens(records), f, indent=2, ensure_ascii=False)

            # H. Process Reviews
            rev_rows = tabs_data.get("Reviews", {}).get('values', [])
            if rev_rows:
                records = parse_sheet_values(rev_rows)
                with open(os.path.join(data_dir, "reviews.json"), "w", encoding="utf-8") as f:
                    json.dump(clean_nan_tokens(records), f, indent=2, ensure_ascii=False)

            # I. Process ThirdPartyPrograms
            tpp_rows = tabs_data.get("ThirdPartyPrograms", {}).get('values', [])
            if tpp_rows:
                records = parse_sheet_values(tpp_rows)
                with open(os.path.join(data_dir, "thirdpartyprograms.json"), "w", encoding="utf-8") as f:
                    json.dump(clean_nan_tokens(records), f, indent=2, ensure_ascii=False)

            # J. Process News
            news_rows = tabs_data.get("News", {}).get('values', [])
            if news_rows:
                records = parse_sheet_values(news_rows)
                with open(os.path.join(data_dir, "news.json"), "w", encoding="utf-8") as f:
                    json.dump(clean_nan_tokens(records), f, indent=2, ensure_ascii=False)

            # K. Process Sales Tab
            sales_rows = tabs_data.get("Sales", {}).get('values', [])
            if sales_rows:
                headers = [h.strip() for h in sales_rows[0]]
                compiled_sales = []

                img_cols = []
                for i in range(1, 6):
                    col_name = f"Image URL {i}"
                    if col_name in headers:
                        img_cols.append((i, headers.index(col_name)))

                pdf_cols = []
                for i in range(1, 6):
                    col_name = f"PDF URL {i}"
                    if col_name in headers:
                        pdf_cols.append((i, headers.index(col_name)))

                for idx, r in enumerate(sales_rows[1:]):
                    padded = list(r) + [""] * (len(headers) - len(r))
                    row_dict = dict(zip(headers, padded))
                    row_num = idx + 2

                    mls_id = row_dict.get("MLS Number", "").strip() or generate_url_slug(row_dict.get("Address", "listing"))

                    for i_num, c_idx in img_cols:
                        img_url = padded[c_idx].strip()
                        if img_url and is_google_drive_link(img_url) and s3_client:
                            r2_url = process_and_upload_image(drive_service, s3_client, r2_bucket, img_url, "Sales", f"{mls_id}", i_num)
                            if "assets.myseattlesearch.com" in r2_url:
                                row_dict[headers[c_idx]] = r2_url
                                batch_sheet_writebacks[web_sheet_id].append({
                                    'range': f"Sales!{get_col_letter(c_idx)}{row_num}", 'values': [[r2_url]]
                                })

                    dl_active = str(row_dict.get("Downloads", "No")).strip().lower() == "yes"
                    pdf_downloads = []
                    if dl_active and mls_id:
                        for p_num, c_idx in pdf_cols:
                            pdf_url = padded[c_idx].strip()
                            if not pdf_url:
                                continue

                            if is_google_drive_link(pdf_url) and s3_client:
                                r2_url, doc_title = process_and_upload_pdf(drive_service, s3_client, r2_bucket, pdf_url, mls_id, p_num)
                                if "assets.myseattlesearch.com" in r2_url:
                                    row_dict[headers[c_idx]] = r2_url
                                    batch_sheet_writebacks[web_sheet_id].append({
                                        'range': f"Sales!{get_col_letter(c_idx)}{row_num}", 'values': [[r2_url]]
                                    })
                                    pdf_downloads.append({"title": doc_title, "url": r2_url})
                                else:
                                    pdf_downloads.append({"title": doc_title, "url": pdf_url})
                            elif pdf_url:
                                filename = pdf_url.split('/')[-1].split('?')[0]
                                doc_title = filename.replace('.pdf', '').replace('.PDF', '').replace('_', ' ').replace('-', ' ').title()
                                pdf_downloads.append({"title": doc_title or f"Document {p_num}", "url": pdf_url})

                    row_dict["pdfDownloads"] = pdf_downloads
                    compiled_sales.append(row_dict)

                with open(os.path.join(data_dir, "sales.json"), "w", encoding="utf-8") as f:
                    json.dump(clean_nan_tokens(compiled_sales), f, indent=4, ensure_ascii=False)

            # L. Process Live_Archive Tab
            archive_rows = tabs_data.get("Live_Archive", {}).get('values', [])
            if archive_rows:
                headers = [h.strip() for h in archive_rows[0]]
                compiled_archive = []
                thumb_col_idx = headers.index("Thumbnail_URL") if "Thumbnail_URL" in headers else -1

                for idx, r in enumerate(archive_rows[1:]):
                    padded = list(r) + [""] * (len(headers) - len(r))
                    row_dict = dict(zip(headers, padded))
                    row_num = idx + 2

                    title = row_dict.get("Title", "").strip()
                    if not title:
                        continue

                    slug = generate_url_slug(title)
                    video_url = row_dict.get("Video_URL", "").strip()
                    youtube_id = extract_youtube_id(video_url)

                    thumb_url = row_dict.get("Thumbnail_URL", "").strip()
                    if thumb_url and is_google_drive_link(thumb_url) and s3_client:
                        r2_url = process_and_upload_image(drive_service, s3_client, r2_bucket, thumb_url, "Live", slug)
                        if "assets.myseattlesearch.com" in r2_url:
                            row_dict["Thumbnail_URL"] = r2_url
                            if thumb_col_idx != -1:
                                batch_sheet_writebacks[web_sheet_id].append({
                                    'range': f"Live_Archive!{get_col_letter(thumb_col_idx)}{row_num}",
                                    'values': [[r2_url]]
                                })
                            thumb_url = r2_url

                    compiled_archive.append({
                        "Title": title,
                        "Date": row_dict.get("Date", "").strip(),
                        "Description": row_dict.get("Description", "").strip(),
                        "Video_URL": video_url,
                        "youtube_id": youtube_id,
                        "Thumbnail_URL": thumb_url
                    })

                with open(os.path.join(data_dir, "live_archive.json"), "w", encoding="utf-8") as f:
                    json.dump(clean_nan_tokens(compiled_archive), f, indent=2, ensure_ascii=False)

            # M. Process Uploads Tab
            uploads_rows = tabs_data.get("Uploads", {}).get('values', [])
            if uploads_rows and s3_client:
                headers = [h.strip() for h in uploads_rows[0]]
                link_col_idx = headers.index("Link") if "Link" in headers else -1
                done_col_idx = headers.index("Done") if "Done" in headers else -1

                if link_col_idx != -1 and done_col_idx != -1:
                    for idx, r in enumerate(uploads_rows[1:]):
                        padded = list(r) + [""] * (len(headers) - len(r))
                        row_dict = dict(zip(headers, padded))
                        row_num = idx + 2

                        done_status = row_dict.get("Done", "").strip().lower()
                        source_link = row_dict.get("Link", "").strip()

                        if done_status == "yes" or not source_link:
                            continue

                        upload_id = row_dict.get("Upload ID", "").strip()
                        name = row_dict.get("Name", "").strip()
                        specified_type = row_dict.get("Type", "").strip().lower()
                        custom_dir = row_dict.get("Directory", "").strip()

                        clean_dir = re.sub(r'[^a-zA-Z0-9/_-]', '', custom_dir).strip('/') if custom_dir else "uploads"
                        if not clean_dir:
                            clean_dir = "uploads"

                        file_slug = generate_url_slug(name) if name else (generate_url_slug(upload_id) if upload_id else f"asset-{row_num}")

                        raw_bytes = None
                        file_id = extract_google_id(source_link)
                        if file_id and drive_service:
                            try:
                                request = drive_service.files().get_media(fileId=file_id)
                                raw_bytes = request.execute()
                            except Exception as ge:
                                print(f"   ⚠️ Could not fetch Drive file ID {file_id}: {ge}")
                        elif source_link.startswith("http://") or source_link.startswith("https://"):
                            try:
                                res = requests.get(source_link, timeout=15)
                                if res.status_code == 200:
                                    raw_bytes = res.content
                            except Exception as re_err:
                                print(f"   ⚠️ Could not fetch URL {source_link}: {re_err}")

                        if not raw_bytes or isinstance(raw_bytes, str):
                            continue

                        is_img = False
                        img_obj = None
                        if specified_type not in ["pdf", "doc", "docx"]:
                            try:
                                stream = io.BytesIO(raw_bytes)
                                img_obj = Image.open(stream)
                                img_obj.verify()
                                stream.seek(0)
                                img_obj = Image.open(stream)
                                is_img = True
                            except Exception:
                                is_img = False

                        if specified_type == "image":
                            is_img = True

                        custom_domain = "https://assets.myseattlesearch.com"

                        if is_img and img_obj:
                            try:
                                img_obj = img_obj.convert("RGBA") if img_obj.mode in ("RGBA", "P") else img_obj.convert("RGB")
                                webp_buffer = io.BytesIO()
                                img_obj.save(webp_buffer, format="WEBP", quality=80)
                                webp_buffer.seek(0)

                                object_key = f"{clean_dir}/{file_slug}.webp"
                                permanent_url = f"{custom_domain}/{object_key}"

                                s3_client.put_object(
                                    Bucket=r2_bucket,
                                    Key=object_key,
                                    Body=webp_buffer,
                                    ContentType="image/webp"
                                )
                                print(f"   🚀 Asset image uploaded safely to R2: {permanent_url}")

                                batch_sheet_writebacks[web_sheet_id].append({
                                    'range': f"Uploads!{get_col_letter(link_col_idx)}{row_num}",
                                    'values': [[permanent_url]]
                                })
                                batch_sheet_writebacks[web_sheet_id].append({
                                    'range': f"Uploads!{get_col_letter(done_col_idx)}{row_num}",
                                    'values': [["Yes"]]
                                })

                                if file_id and drive_service:
                                    try:
                                        drive_service.files().delete(fileId=file_id).execute()
                                        print(f"   🗑️ Purged Drive source file ID {file_id}")
                                    except Exception: pass
                            except Exception as ie:
                                print(f"   ❌ Image asset ingestion failed for row {row_num}: {ie}")
                        else:
                            try:
                                ext = specified_type if specified_type else "pdf"
                                if "pdf" in source_link.lower() or specified_type == "pdf":
                                    ext = "pdf"
                                    content_type = "application/pdf"
                                else:
                                    content_type = "application/octet-stream"

                                object_key = f"{clean_dir}/{file_slug}.{ext}"
                                permanent_url = f"{custom_domain}/{object_key}"

                                s3_client.put_object(
                                    Bucket=r2_bucket,
                                    Key=object_key,
                                    Body=raw_bytes,
                                    ContentType=content_type
                                )
                                print(f"   📄 Asset document uploaded safely to R2: {permanent_url}")

                                batch_sheet_writebacks[web_sheet_id].append({
                                    'range': f"Uploads!{get_col_letter(link_col_idx)}{row_num}",
                                    'values': [[permanent_url]]
                                })
                                batch_sheet_writebacks[web_sheet_id].append({
                                    'range': f"Uploads!{get_col_letter(done_col_idx)}{row_num}",
                                    'values': [["Yes"]]
                                })

                                if file_id and drive_service:
                                    try:
                                        drive_service.files().delete(fileId=file_id).execute()
                                        print(f"   🗑️ Purged Drive source file ID {file_id}")
                                    except Exception: pass
                            except Exception as fe:
                                print(f"   ❌ Document asset ingestion failed for row {row_num}: {fe}")

            # N. Process Sports Tab
            sports_rows = tabs_data.get("Sports", {}).get('values', [])
            if sports_rows:
                records = parse_sheet_values(sports_rows)
                with open(os.path.join(data_dir, "sports_teams.json"), "w", encoding="utf-8") as f:
                    json.dump(clean_nan_tokens(records), f, indent=2, ensure_ascii=False)
                print(f"   ✅ Sports roster synchronized ({len(records)} teams) to data/sports_teams.json.")

        except Exception as e:
            print(f"   ❌ Critical error compiling Website Data workbook: {e}")

    # ====================================================================
    # MODULE 3: CMS HEADLESS GENERATOR
    # ====================================================================
    cms_sheet_id = os.environ.get("CMS_SHEET_ID")
    if cms_sheet_id:
        print("📡 Accessing Headless CMS Content Workbook parameters...")
        try:
            if cms_sheet_id not in batch_sheet_writebacks:
                batch_sheet_writebacks[cms_sheet_id] = []

            rows = sheets_service.spreadsheets().values().get(spreadsheetId=cms_sheet_id, range="Posts!A:X").execute().get('values', [])
            if rows:
                headers = rows[0]
                col_map = {i: headers.index(f"Image {i} URL") for i in range(1, 6) if f"Image {i} URL" in headers}
                for idx, r in enumerate(rows[1:]):
                    padded = list(r) + [""] * (len(headers) - len(r))
                    record = dict(zip(headers, padded))
                    row_num = idx + 2
                    slug = record.get("Content ID", "").strip()
                    if not slug: continue

                    target_md = os.path.join(posts_dir, f"{slug}.md")

                    if record.get("Active", "").strip().lower() != "yes":
                        if os.path.exists(target_md):
                            os.remove(target_md)
                        continue

                    optimized_images = []
                    for i in range(1, 6):
                        img_url = record.get(f"Image {i} URL", "").strip()
                        if img_url and is_google_drive_link(img_url) and s3_client:
                            r2_url = process_and_upload_image(drive_service, s3_client, r2_bucket, img_url, "CMS", slug, i)
                            optimized_images.append(r2_url)
                            if "assets.myseattlesearch.com" in r2_url:
                                batch_sheet_writebacks[cms_sheet_id].append({
                                    'range': f"Posts!{get_col_letter(col_map[i])}{row_num}", 'values': [[r2_url]]
                                })
                        else:
                            optimized_images.append(img_url)

                    if optimized_images and optimized_images[0]:
                        cms_image_map[slug] = optimized_images[0]

                    post_type = record.get("Type", "").strip()
                    content_field = record.get("Content", "").strip()

                    raw_tags = record.get("Tags", "")
                    tags_list = ", ".join([f'"{t.strip()}"' for t in raw_tags.split(",") if t.strip()])

                    clean_title = record.get('Title', '').replace('"', '\\"')
                    clean_headline = record.get('Headline', '').replace('"', '\\"')
                    clean_subhead = record.get('Subhead', '').replace('"', '\\"')

                    front_matter = (
f"""---
layout: post.njk
title: "{clean_title}"
headline: "{clean_headline}"
subhead: "{clean_subhead}"
date: {record.get('Publish Date', datetime.date.today().strftime('%Y-%m-%d'))}
author: "{record.get('Author', 'Joe Sheldon')}"
tags: [{tags_list}]
type: "{post_type}"
url_1_label: "{record.get('URL 1 Label', '')}"
url_1: "{record.get('URL 1', '')}"
url_2_label: "{record.get('URL 2 Label', '')}"
url_2: "{record.get('URL 2', '')}"
image_1: "{optimized_images[0] if len(optimized_images) > 0 else ''}"
image_2: "{optimized_images[1] if len(optimized_images) > 1 else ''}"
image_3: "{optimized_images[2] if len(optimized_images) > 2 else ''}"
image_4: "{optimized_images[3] if len(optimized_images) > 3 else ''}"
image_5: "{optimized_images[4] if len(optimized_images) > 4 else ''}"
---
"""
                    )

                    file_exists = os.path.exists(target_md)
                    existing_content = ""
                    if file_exists:
                        try:
                            with open(target_md, "r", encoding="utf-8") as ef:
                                existing_content = ef.read()
                        except Exception:
                            existing_content = ""

                    body_text = ""

                    if "docs.google.com" in content_field:
                        body_text = get_google_doc_as_markdown(docs_service, content_field)
                        published_post_url = f"https://myseattlesearch.com/posts/{slug}/"
                        col_content_idx = headers.index("Content") if "Content" in headers else -1
                        if col_content_idx != -1:
                            batch_sheet_writebacks[cms_sheet_id].append({
                                'range': f"Posts!{get_col_letter(col_content_idx)}{row_num}",
                                'values': [[published_post_url]]
                            })
                    elif "myseattlesearch.com" in content_field or file_exists:
                        if file_exists and existing_content and ("---\n" in existing_content):
                            parts = existing_content.split("---\n", 2)
                            body_text = parts[2] if len(parts) >= 3 else content_field
                        else:
                            body_text = content_field
                    else:
                        body_text = content_field

                    full_md_payload = f"{front_matter}{body_text}"

                    if existing_content != full_md_payload:
                        with open(target_md, "w", encoding="utf-8") as f:
                            f.write(full_md_payload)

        except Exception as e:
            print(f"   ❌ Headless CMS module execution failure: {e}")

    # ====================================================================
    # MODULE 4: POLYMORPHIC QUIZZES PROCESSING LAYER
    # ====================================================================
    quiz_sheet_id = os.environ.get("QUIZZES_SHEET_ID")
    if quiz_sheet_id:
        print("📡 Accessing Polymorphic interactive lead assessments...")
        try:
            if quiz_sheet_id not in batch_sheet_writebacks:
                batch_sheet_writebacks[quiz_sheet_id] = []

            rows = sheets_service.spreadsheets().values().get(spreadsheetId=quiz_sheet_id, range="Quizzes!A:DB").execute().get('values', [])
            if rows:
                headers = rows[0]
                img_col_idx = headers.index("Quiz Image") if "Quiz Image" in headers else -1
                quizzes_db = {}

                for idx, r in enumerate(rows[1:]):
                    padded = list(r) + [""] * (len(headers) - len(r))
                    row_dict = dict(zip(headers, padded))
                    row_num = idx + 2
                    quiz_id = row_dict.get("Quiz ID", "").strip()
                    if not quiz_id: continue

                    quiz_slug = generate_url_slug(row_dict.get("Quiz Name", "quiz"))
                    cover_img = row_dict.get("Quiz Image", "").strip()
                    if cover_img and is_google_drive_link(cover_img) and s3_client:
                        r2_url = process_and_upload_image(drive_service, s3_client, r2_bucket, cover_img, "Quizzes", quiz_slug, "cover")
                        if "assets.myseattlesearch.com" in r2_url:
                            row_dict["Quiz Image"] = r2_url
                            batch_sheet_writebacks[quiz_sheet_id].append({
                                'range': f"Quizzes!{get_col_letter(img_col_idx)}{row_num}", 'values': [[r2_url]]
                            })

                    questions = []
                    for i in range(1, 21):
                        q_text = row_dict.get(f"Q{i} Text", "").strip()
                        if q_text: questions.append({"text": q_text, "bucket": row_dict.get(f"Q{i} Bucket", "").strip()})

                    routing = []
                    for j in range(1, 11):
                        r_url = row_dict.get(f"R{j} URL", "").strip()
                        r_key = row_dict.get(f"R{j} Key", "").strip()
                        if r_url and is_google_drive_link(r_url) and s3_client:
                            r2_url = process_and_upload_image(drive_service, s3_client, r2_bucket, r_url, "Quizzes", f"{quiz_slug}-res-{j}")
                            if "assets.myseattlesearch.com" in r2_url:
                                r_url = r2_url
                                url_col_idx = headers.index(f"R{j} URL")
                                batch_sheet_writebacks[quiz_sheet_id].append({
                                    'range': f"Quizzes!{get_col_letter(url_col_idx)}{row_num}", 'values': [[r2_url]]
                                })
                        if r_key or r_url:
                            routing.append({
                                "key": r_key, "url": r_url, "heading": row_dict.get(f"R{j} Heading", "").strip(),
                                "subheading": row_dict.get(f"R{j} Subheading", "").strip(), "details": row_dict.get(f"R{j} Details", "").strip(),
                                "additionalDetails": row_dict.get(f"R{j} Additional Details", "").strip()
                            })
                    quizzes_db[quiz_id] = {
                        "id": int(quiz_id), "name": row_dict.get("Quiz Name", "").strip(), "webTitle": row_dict.get("Quiz Web Title", "").strip(),
                        "introText": row_dict.get("Intro Text", "").strip(), "scoringType": row_dict.get("Scoring Type", "").strip(),
                        "requiredFields": row_dict.get("Required Fields", "").strip(), "rank": int(row_dict.get("Rank", "0").strip() or 0),
                        "quizImage": row_dict.get("Quiz Image", ""), "showInCatalog": row_dict.get("Show In Catalog", ""),
                        "webhookUrl": row_dict.get("Webhook URL", ""), "emailSubject": row_dict.get("Email Subject", ""), "userTags": row_dict.get("User Tags", ""),
                        "questions": questions, "routing": routing
                    }
                with open(os.path.join(data_dir, "quizzes.json"), "w", encoding="utf-8") as f:
                    json.dump(quizzes_db, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"   ❌ Assessment processing fault: {e}")

    # ====================================================================
    # MODULE 5: LOCAL RSS REAL ESTATE WIRE
    # ====================================================================
    news_config = os.path.join(data_dir, "news.json")
    if os.path.exists(news_config):
        print("📡 Starting isolated neighborhood news aggregator parsing pass...")
        try:
            with open(news_config, "r", encoding="utf-8") as f:
                sources = json.load(f)
            compiled_articles = []
            for src in sources:
                feed_name = src.get("Name", "Local Wire")
                rss_url = src.get("RSS Feed URL")
                if not rss_url: continue

                paywall_val = str(src.get("Paywall", "No")).strip()
                is_paywall = paywall_val.lower() == "yes"

                city_raw = src.get("City", "").strip()
                cities_array = [city_raw.lower()] if city_raw and city_raw.lower() != "nan" else []

                categories_array = [c.strip().lower().replace(" ", "-") for c in src.get("Categories", "").split(",") if c.strip()]

                if "north-sound" in categories_array and "snohomish-county" not in categories_array:
                    categories_array.append("snohomish-county")

                try:
                    res = requests.get(rss_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
                    if res.status_code == 200:
                        feed = feedparser.parse(res.content)
                        for entry in feed.entries:
                            title = entry.get("title", "").strip()
                            link = entry.get("link", "").strip()
                            if not title or not link: continue

                            excerpt = re.sub(r'<[^>]+>', '', entry.get("summary") or entry.get("description") or "")
                            excerpt = " ".join(excerpt.split())
                            if len(excerpt) > 220: excerpt = excerpt[:220] + "..."

                            raw_date = entry.get("published") or entry.get("updated")
                            try:
                                p_dt = parser.parse(str(raw_date))
                                if p_dt.tzinfo is None: p_dt = p_dt.replace(tzinfo=ZoneInfo("UTC"))
                                p_local = p_dt.astimezone(ZoneInfo("America/Los_Angeles"))
                                pub_str = p_local.strftime("%a, %b %d, %Y at %I:%M %p")
                                sort_str = p_local.isoformat()
                            except:
                                now_pac = datetime.datetime.now(ZoneInfo("America/Los_Angeles"))
                                pub_str = now_pac.strftime("%a, %b %d, %Y at %I:%M %p")
                                sort_str = now_pac.isoformat()

                            compiled_articles.append({
                                "source": feed_name, "title": title, "link": link,
                                "excerpt": excerpt if excerpt else "Click view details to read full update.",
                                "published": pub_str,
                                "paywall": is_paywall,
                                "cities": cities_array, "categories": categories_array, "_iso": sort_str
                            })
                except Exception as e:
                    print(f"   ⚠️ Feed skip warning on '{feed_name}': {e}")

            compiled_articles.sort(key=lambda x: x.get("_iso", ""), reverse=True)
            for a in compiled_articles: a.pop("_iso", None)
            with open(os.path.join(data_dir, "market_news.json"), "w", encoding="utf-8") as f:
                json.dump(compiled_articles[:200], f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"   ❌ News compilation halted: {e}")

    # ====================================================================
    # MODULE 6: CALIBRATE ACTIVE DAYS ON MARKET (DOM) INDICES
    # ====================================================================
    sales_file = os.path.join(data_dir, "sales.json")
    if os.path.exists(sales_file):
        print("📡 Calibrating active inventory Days on Market values...")
        try:
            with open(sales_file, "r", encoding="utf-8") as f:
                sales_data = json.load(f)
            if isinstance(sales_data, list):
                today_date = datetime.datetime.now().date()
                for item in sales_data:
                    if item.get("Status", "").strip() == "Sold": continue
                    s_date = item.get("Selling Date")
                    if s_date and str(s_date).strip():
                        try:
                            dt_obj = datetime.datetime.strptime(str(s_date).strip(), "%m/%d/%Y").date()
                            item["DOM"] = max(0, (today_date - dt_obj).days)
                        except: item["DOM"] = "-"
                    else: item["DOM"] = "-"
                with open(sales_file, "w", encoding="utf-8") as f:
                    json.dump(sales_data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"   ⚠️ Portfolio DOM sync pass bypassed: {e}")

    # ====================================================================
    # MODULE 7: SOCIAL MEDIA AUTO-PUBLISHER
    # ====================================================================
    if cms_sheet_id:
        fb_page_id = os.environ.get("FB_PAGE_ID")
        fb_token = os.environ.get("FB_PAGE_ACCESS_TOKEN")
        threads_user_id = os.environ.get("THREADS_USER_ID")
        threads_token = os.environ.get("THREADS_ACCESS_TOKEN")
        li_author = os.environ.get("LINKEDIN_AUTHOR_URN")
        li_token = os.environ.get("LINKEDIN_ACCESS_TOKEN")

        if any([fb_token, threads_token, li_token]):
            print("📢 Scanning for pending social media posts...")
            try:
                res = sheets_service.spreadsheets().values().get(
                    spreadsheetId=cms_sheet_id, range="Posts!A:AD"
                ).execute()
                p_rows = res.get("values", [])

                if p_rows and len(p_rows) >= 2:
                    p_headers = [str(h).strip() for h in p_rows[0]]
                    col_map_soc = {
                        "active": p_headers.index("Active") if "Active" in p_headers else -1,
                        "content_id": p_headers.index("Content ID") if "Content ID" in p_headers else -1,
                        "title": p_headers.index("Title") if "Title" in p_headers else -1,
                        "headline": p_headers.index("Headline") if "Headline" in p_headers else -1,
                        "subhead": p_headers.index("Subhead") if "Subhead" in p_headers else -1,
                        "content": p_headers.index("Content") if "Content" in p_headers else -1,
                        "url_1": p_headers.index("URL 1") if "URL 1" in p_headers else -1,
                        "img_1": p_headers.index("Image 1 URL") if "Image 1 URL" in p_headers else -1,
                        "fb_switch": p_headers.index("FB") if "FB" in p_headers else -1,
                        "fb_id": p_headers.index("FB ID") if "FB ID" in p_headers else -1,
                        "threads_switch": p_headers.index("Threads") if "Threads" in p_headers else -1,
                        "threads_id": p_headers.index("Threads ID") if "Threads ID" in p_headers else -1,
                        "li_switch": p_headers.index("LI") if "LI" in p_headers else -1,
                        "li_id": p_headers.index("LI ID") if "LI ID" in p_headers else -1,
                    }

                    if cms_sheet_id not in batch_sheet_writebacks:
                        batch_sheet_writebacks[cms_sheet_id] = []

                    for idx, row in enumerate(p_rows[1:]):
                        row_num = idx + 2
                        padded = list(row) + [""] * (len(p_headers) - len(row))

                        def get_v(c_idx):
                            return padded[c_idx].strip() if c_idx != -1 else ""

                        if get_v(col_map_soc["active"]).lower() != "yes":
                            continue

                        slug = get_v(col_map_soc["content_id"])
                        title = get_v(col_map_soc["title"])
                        headline = get_v(col_map_soc["headline"])
                        subhead = get_v(col_map_soc["subhead"])
                        content_body = get_v(col_map_soc["content"])
                        url_1 = get_v(col_map_soc["url_1"])

                        image_1 = cms_image_map.get(slug, get_v(col_map_soc["img_1"]))

                        primary_text = headline or title
                        if not primary_text and not content_body:
                            continue

                        post_components = []
                        if primary_text:
                            post_components.append(primary_text)

                        if content_body and "docs.google.com" not in content_body:
                            if content_body != primary_text:
                                post_components.append(content_body)
                        elif subhead and subhead != primary_text:
                            post_components.append(subhead)

                        if url_1 and "docs.google.com" not in url_1 and url_1 not in primary_text and url_1 not in content_body:
                            post_components.append(url_1)

                        post_text = "\n\n".join(post_components)

                        if get_v(col_map_soc["fb_switch"]).lower() == "yes" and not get_v(col_map_soc["fb_id"]):
                            print(f"   📢 [Row {row_num}] Publishing to Facebook: '{primary_text[:40]}...'")
                            pub_id = publish_to_facebook(
                                fb_page_id, fb_token, post_text, link=url_1, image_url=image_1
                            )
                            if pub_id and col_map_soc["fb_id"] != -1:
                                batch_sheet_writebacks[cms_sheet_id].append({
                                    'range': f"Posts!{get_col_letter(col_map_soc['fb_id'])}{row_num}",
                                    'values': [[pub_id]]
                                })

                        if get_v(col_map_soc["threads_switch"]).lower() == "yes" and not get_v(col_map_soc["threads_id"]):
                            print(f"   📢 [Row {row_num}] Publishing to Threads: '{primary_text[:40]}...'")
                            pub_id = publish_to_threads(
                                threads_user_id, threads_token, post_text, image_url=image_1
                            )
                            if pub_id and col_map_soc["threads_id"] != -1:
                                batch_sheet_writebacks[cms_sheet_id].append({
                                    'range': f"Posts!{get_col_letter(col_map_soc['threads_id'])}{row_num}",
                                    'values': [[pub_id]]
                                })

                        if get_v(col_map_soc["li_switch"]).lower() == "yes" and not get_v(col_map_soc["li_id"]):
                            print(f"   📢 [Row {row_num}] Publishing to LinkedIn: '{primary_text[:40]}...'")
                            pub_id = publish_to_linkedin(
                                li_author, li_token, post_text, link=url_1, title=primary_text
                            )
                            if pub_id and col_map_soc["li_id"] != -1:
                                batch_sheet_writebacks[cms_sheet_id].append({
                                    'range': f"Posts!{get_col_letter(col_map_soc['li_id'])}{row_num}",
                                    'values': [[pub_id]]
                                })

            except Exception as e:
                print(f"   ❌ Social publisher module execution failure: {e}")

    # ====================================================================
    # MODULE 8: FLUSH BULK CELL WRITEBACKS
    # ====================================================================
    for s_id, updates in batch_sheet_writebacks.items():
        if updates:
            print(f"📝 Executing unified cell data writeback pass ({len(updates)} cell updates) to Workbook ID: {s_id}...")
            try:
                sheets_service.spreadsheets().values().batchUpdate(
                    spreadsheetId=s_id, body={'valueInputOption': 'USER_ENTERED', 'data': updates}
                ).execute()
                print(f"   ✅ Workbook `{s_id}` writebacks synchronized in single batch pass.")
            except Exception as write_err:
                print(f"   ⚠️ Sheet cells writeback bypass warning: {write_err}")

    # ====================================================================
    # MODULE 9: CLOUDFLARE R2 ACCOUNTING METRICS GENERATOR
    # ====================================================================
    out_dir = "_data"
    os.makedirs(out_dir, exist_ok=True)
    out_f = os.path.join(out_dir, "r2_storage.json")
    r2_payload = {"usedGB": "0.00", "usedBytes": 0, "lastChecked": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    if s3_client and r2_bucket:
        try:
            total_bytes = 0
            paginator = s3_client.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=r2_bucket):
                if 'Contents' in page:
                    for obj in page['Contents']: total_bytes += obj.get('Size', 0)
            r2_payload["usedGB"] = f"{(total_bytes / (1024 ** 3)):.2f}"
            r2_payload["usedBytes"] = total_bytes
        except: pass
    with open(out_f, "w", encoding="utf-8") as f: json.dump(r2_payload, f, indent=2)

    print("🏁 Real-Time Master Locomotive Processing Sequence Complete. Site data fresh.")

if __name__ == "__main__":
    main()