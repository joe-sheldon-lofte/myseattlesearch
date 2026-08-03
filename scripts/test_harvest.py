import os
import json
import math
import urllib.request
import urllib.parse
import traceback
from datetime import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# Path references
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")
CITY_BOUNDARIES_PATH = os.path.join(DATA_DIR, "city_boundaries.json")
ENVIRONMENT_DATA_PATH = os.path.join(DATA_DIR, "city_environment.json")
CRIME_STATS_PATH = os.path.join(DATA_DIR, "crime_stats.json")
DEMOGRAPHICS_PATH = os.path.join(DATA_DIR, "city_demographics.json")

# Fallback Municipal Population Baseline (Used ONLY if dynamic local JSON files are missing)
FALLBACK_POPULATION = {
    "algona": 3335, "auburn": 88950, "beaux-arts-village": 315, "bellevue": 155000,
    "black-diamond": 7195, "bothell": 50670, "burien": 53000, "carnation": 2250,
    "clyde-hill": 3100, "covington": 22000, "des-moines": 33400, "duvall": 8780,
    "enumclaw": 13350, "federal-way": 102500, "hunts-point": 3100, "issaquah": 41500,
    "kenmore": 24350, "kent": 140400, "kirkland": 96710, "lake-forest-park": 13680,
    "maple-valley": 29320, "medina": 3380, "mercer-island": 25830, "milton": 8755,
    "newcastle": 13750, "normandy-park": 6855, "north-bend": 8260, "pacific": 7270,
    "redmond": 80040, "renton": 108800, "sammamish": 68410, "seatac": 32710,
    "seattle": 797700, "shoreline": 61910, "skykomish": 165, "snoqualmie": 14520,
    "tukwila": 22930, "woodinville": 13900, "yarrow-point": 1135, "arlington": 22980,
    "brier": 6600, "darrington": 1515, "edmonds": 43420, "everett": 114800,
    "gold-bar": 2310, "granite-falls": 4775, "index": 160, "lake-stevens": 41540,
    "lynnwood": 41500, "marysville": 74390, "mill-creek": 21630, "monroe": 20830,
    "mountlake-terrace": 24260, "mukilteo": 21590, "snohomish": 10350, "stanwood": 8865,
    "sultan": 7160, "woodway": 1345
}

def slugify(text):
    """Generate a clean URL slug from any string."""
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

def http_get_raw(url, extra_headers=None, timeout=30):
    """Robust HTTP GET text helper returning raw string output and HTTP status code."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) RealEstateDataBot/1.0",
        "Accept": "application/json, text/plain, */*"
    }
    if extra_headers:
        headers.update(extra_headers)
        
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_bytes = resp.read()
            return resp.status, raw_bytes.decode("utf-8")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else ""
        return e.code, body
    except Exception as e:
        return 0, ""

def http_get_json(url, extra_headers=None, timeout=30):
    """Utility helper for HTTP GET requests returning decoded JSON objects."""
    status, raw_text = http_get_raw(url, extra_headers=extra_headers, timeout=timeout)
    if status == 200 and raw_text and not raw_text.strip().startswith("<"):
        try:
            return json.loads(raw_text)
        except Exception:
            pass
    return None

def save_json(filename, data):
    """Save formatted JSON output to data directory."""
    os.makedirs(DATA_DIR, exist_ok=True)
    target_path = os.path.join(DATA_DIR, filename)
    with open(target_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Successfully generated: {target_path}")

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate Great Circle distance in miles between two lat/lon points."""
    R = 3958.8
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# ==============================================================================
# SPATIAL POINT-IN-POLYGON ENGINE
# ==============================================================================
def get_geometry_bbox(geometry):
    """Calculate Bounding Box (min_lat, min_lon, max_lat, max_lon) for GeoJSON geometry."""
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
    """Ray-casting algorithm to test if (lat, lon) is inside a GeoJSON coordinate ring."""
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
    """Test if a latitude/longitude point falls inside a Polygon or MultiPolygon."""
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
    """Load and index municipal spatial boundary shapes for PIP matching."""
    if not os.path.exists(CITY_BOUNDARIES_PATH):
        print(f"Warning: {CITY_BOUNDARIES_PATH} not found.")
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
            
    print(f"Loaded {len(indexed)} municipal spatial boundary shapes for PIP matching.")
    return indexed

def match_city_for_point(lat, lon, city_boundaries):
    """Fast Bounding Box pre-filter + Point-in-Polygon match for a lat/lon point."""
    for city in city_boundaries:
        bbox = city["bbox"]
        if bbox[0] <= lat <= bbox[2] and bbox[1] <= lon <= bbox[3]:
            if point_in_geometry(lat, lon, city["geometry"]):
                return city["slug"]
    return None

def match_city_for_alert(lat, lon, city_boundaries, cities):
    """Match point to city polygon or fallback to nearest city centroid within 3 miles for highway alerts."""
    matched = match_city_for_point(lat, lon, city_boundaries)
    if matched:
        return matched

    # Proximity check for freeway work zones situated along municipal border edges
    closest_city = None
    min_dist = 3.0  # Max 3 mile proximity buffer
    for c in cities:
        clat, clon = c.get("latitude"), c.get("longitude")
        if clat is None or clon is None:
            continue
        dist = haversine_distance(lat, lon, clat, clon)
        if dist < min_dist:
            min_dist = dist
            closest_city = c["slug"]

    return closest_city

def load_official_population_map():
    """Load live reported population figures from crime_stats.json, city_demographics.json, or fallback."""
    pop_map = dict(FALLBACK_POPULATION)

    # 1. Try reading official reported population from crime_stats.json
    if os.path.exists(CRIME_STATS_PATH):
        try:
            with open(CRIME_STATS_PATH, "r", encoding="utf-8") as f:
                crime_data = json.load(f)
                for city_name, details in crime_data.items():
                    if isinstance(details, dict) and "reported_population" in details:
                        slug = slugify(city_name)
                        pop_map[slug] = int(details["reported_population"])
            print(f"Loaded official WA OFM population baseline for {len(crime_data)} cities from crime_stats.json.")
            return pop_map
        except Exception as e:
            print(f"Crime Stats Population Read Warning: {e}")

    # 2. Try reading Census ACS population from city_demographics.json
    if os.path.exists(DEMOGRAPHICS_PATH):
        try:
            with open(DEMOGRAPHICS_PATH, "r", encoding="utf-8") as f:
                demo_data = json.load(f)
                for slug, details in demo_data.items():
                    if isinstance(details, dict) and "population" in details:
                        pop_map[slug] = int(details["population"])
            print(f"Loaded official Census ACS population baseline from city_demographics.json.")
            return pop_map
        except Exception as e:
            print(f"Demographics Population Read Warning: {e}")

    return pop_map

def load_city_data():
    """Load city_data.json and normalize city records with official population figures."""
    pop_map = load_official_population_map()

    if not os.path.exists(CITY_DATA_PATH):
        print(f"Error: {CITY_DATA_PATH} not found.")
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

        population = pop_map.get(slug, 25000)

        normalized.append({
            "slug": slug,
            "name": str(raw_name).strip(),
            "latitude": lat_float,
            "longitude": lon_float,
            "population": population
        })

    print(f"Pre-processed {len(normalized)} city records with official population data.")
    return normalized

# ==============================================================================
# GOOGLE SHEETS ADMIN CONFIGURATION INGESTION
# ==============================================================================
def load_sheets_admin_config():
    """Load CityFeeds and TransitData configurations from Google Sheets using dynamic tab discovery."""
    web_sheet_id = os.environ.get("WEBSITE_DATA_SHEET_ID")
    creds_path = os.path.join(BASE_DIR, "credentials.json")
    
    config = {"feeds": {}, "transit_rules": {}}
    
    if not web_sheet_id or not os.path.exists(creds_path):
        print("Sheets Auth Notice: credentials.json or WEBSITE_DATA_SHEET_ID not found. Using local API defaults.")
        return config

    try:
        creds = Credentials.from_service_account_file(creds_path, scopes=['https://www.googleapis.com/auth/spreadsheets.readonly'])
        service = build('sheets', 'v4', credentials=creds)
        
        # 1. Dynamically inspect available tab titles to resolve exact title strings and handle trailing whitespace or casing
        sheet_meta = service.spreadsheets().get(spreadsheetId=web_sheet_id).execute()
        sheet_titles = [s.get('properties', {}).get('title', '') for s in sheet_meta.get('sheets', [])]
        
        city_feeds_title = next((t for t in sheet_titles if t.strip().lower() == "cityfeeds"), None)
        transit_data_title = next((t for t in sheet_titles if t.strip().lower() == "transitdata"), None)

        ranges_to_fetch = []
        if city_feeds_title:
            ranges_to_fetch.append(f"'{city_feeds_title}'!A1:Z5000")
        if transit_data_title:
            ranges_to_fetch.append(f"'{transit_data_title}'!A1:Z200")

        if not ranges_to_fetch:
            print("Sheets Config Notice: Target tabs (CityFeeds, TransitData) not found in workbook metadata.")
            return config

        batch = service.spreadsheets().values().batchGet(
            spreadsheetId=web_sheet_id, ranges=ranges_to_fetch
        ).execute().get('valueRanges', [])

        # 2. Parse CityFeeds camera overrides
        if city_feeds_title and len(batch) > 0:
            feed_rows = batch[0].get('values', [])
            if feed_rows and len(feed_rows) > 1:
                headers = [str(h).strip() for h in feed_rows[0]]
                for r in feed_rows[1:]:
                    padded = list(r) + [""] * (len(headers) - len(r))
                    row_dict = dict(zip(headers, padded))
                    feed_id = row_dict.get("Feed ID", "").strip()
                    if feed_id:
                        config["feeds"][feed_id] = {
                            "name": row_dict.get("Feed Name", "").strip(),
                            "active": row_dict.get("Active", "Yes").strip().lower() == "yes",
                            "city": row_dict.get("City", "").strip()
                        }

        # 3. Parse TransitData route/terminal rules
        transit_batch_idx = 1 if (city_feeds_title and len(batch) > 1) else 0
        if transit_data_title and len(batch) > transit_batch_idx:
            transit_rows = batch[transit_batch_idx].get('values', [])
            if transit_rows and len(transit_rows) > 1:
                headers = [str(h).strip() for h in transit_rows[0]]
                for r in transit_rows[1:]:
                    padded = list(r) + [""] * (len(headers) - len(r))
                    row_dict = dict(zip(headers, padded))
                    route_id = row_dict.get("Route ID", "").strip() or row_dict.get("Feed ID", "").strip()
                    try:
                        seats = int(row_dict.get("Default Seats", "40").strip() or 40)
                    except ValueError:
                        seats = 40
                    if route_id:
                        config["transit_rules"][route_id] = {
                            "agency": row_dict.get("Agency", "").strip(),
                            "mode": row_dict.get("Transit Mode", "").strip(),
                            "name": row_dict.get("Route Name", "").strip(),
                            "seats": seats,
                            "include_in_score": row_dict.get("Active Transit Score", "Yes").strip().lower() == "yes",
                            "active": row_dict.get("Active", "Yes").strip().lower() == "yes"
                        }

        print(f"Successfully loaded Google Sheets Admin Config: {len(config['feeds'])} Camera Feeds, {len(config['transit_rules'])} Transit Routes.")
    except Exception as e:
        print(f"Sheets Config Load Notice: {e}. Falling back to default API configurations.")
        
    return config

# ==============================================================================
# MODULE 1: MULTI-AGENCY TRAFFIC CAMERA HARVESTER
# ==============================================================================
def harvest_traffic_cams(cities, city_boundaries, sheets_config):
    print("🎥 Harvesting WSDOT & Seattle DOT Traffic Camera Feeds...")
    wsdot_code = os.environ.get("WSDOT_ACCESS_CODE", "").strip().strip("'").strip('"')
    
    feed_overrides = sheets_config.get("feeds", {})
    city_map = {c["slug"]: {"name": c["name"], "cameras": []} for c in cities}
    total_found = 0

    # 1. Ingest WSDOT Highway Cameras
    if wsdot_code:
        wsdot_url = f"https://wsdot.wa.gov/Traffic/api/HighwayCameras/HighwayCamerasREST.svc/GetCamerasAsJson?AccessCode={wsdot_code}"
        cams = http_get_json(wsdot_url, timeout=25)
        if cams and isinstance(cams, list):
            print(f"Retrieved {len(cams)} WSDOT highway camera feeds.")
            for cam in cams:
                try:
                    clat = float(cam.get("CameraLocation", {}).get("Latitude"))
                    clon = float(cam.get("CameraLocation", {}).get("Longitude"))
                except (ValueError, TypeError):
                    continue
                    
                cam_id = f"wsdot-{cam.get('CameraID')}"
                
                # Check Sheet Admin Override
                override = feed_overrides.get(cam_id, {})
                if override.get("active") is False:
                    continue
                    
                title = override.get("name") or cam.get("Title") or cam.get("CameraOwner") or "WSDOT Camera"
                img_url = cam.get("ImageURL", "")
                direction = cam.get("Direction", "")
                
                matched_slug = match_city_for_point(clat, clon, city_boundaries)
                if matched_slug and matched_slug in city_map:
                    city_map[matched_slug]["cameras"].append({
                        "id": cam_id,
                        "title": title,
                        "agency": "WSDOT",
                        "direction": direction,
                        "latitude": clat,
                        "longitude": clon,
                        "image_url": img_url
                    })
                    total_found += 1

    # 2. Ingest Seattle DOT (SDOT) City Arterial Cameras
    sdot_url = "https://web6.seattle.gov/Travelers/api/Map/GetMapData"
    sdot_res = http_get_json(sdot_url, timeout=25)
    if sdot_res and isinstance(sdot_res, dict) and "Features" in sdot_res:
        features = sdot_res.get("Features", [])
        print(f"Retrieved {len(features)} SDOT camera locations.")
        for feat in features:
            coords = feat.get("PointCoordinate") or []
            if len(coords) < 2:
                continue
            clat, clon = float(coords[0]), float(coords[1])
            
            cams = feat.get("Cameras") or []
            for c_idx, cam in enumerate(cams):
                cam_id = f"sdot-{cam.get('Id') or c_idx}"
                
                override = feed_overrides.get(cam_id, {})
                if override.get("active") is False:
                    continue
                    
                title = override.get("name") or cam.get("Description") or "Seattle DOT Camera"
                img_url = cam.get("ImageUrl", "")
                if not img_url.startswith("http"):
                    img_url = f"https://www.seattle.gov/trafficers/images/{img_url}" if img_url else ""
                    
                matched_slug = match_city_for_point(clat, clon, city_boundaries)
                if matched_slug and matched_slug in city_map:
                    city_map[matched_slug]["cameras"].append({
                        "id": cam_id,
                        "title": title,
                        "agency": "SDOT",
                        "direction": "",
                        "latitude": clat,
                        "longitude": clon,
                        "image_url": img_url
                    })
                    total_found += 1

    output = {}
    for slug, details in city_map.items():
        c_list = details["cameras"]
        output[slug] = {
            "name": details["name"],
            "camera_count": len(c_list),
            "cameras": c_list,
            "last_updated": datetime.utcnow().isoformat() + "Z"
        }

    print(f"Successfully mapped {total_found} active traffic cameras across cities.")
    save_json("city_traffic_cams.json", output)

# ==============================================================================
# MODULE 2: MULTI-MODAL TRANSIT RADAR & ACTIVE SEAT SCORE ENGINE
# ==============================================================================
def harvest_transit_radar(cities, city_boundaries, sheets_config):
    print("🚆 Harvesting OneBusAway GTFS-RT Transit Positions...")
    oba_key = os.environ.get("ONEBUSAWAY_API_KEY", "").strip().strip("'").strip('"') or "TEST"
    
    # Regional Agency Map
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
            "maritime_vessels": [],
            "maritime_seats": 0
        } for c in cities
    }
    total_vehicles = 0

    for agency_id, agency_name in all_agencies.items():
        oba_url = f"https://api.pugetsound.onebusaway.org/api/where/vehicles-for-agency/{agency_id}.json?key={oba_key}"
        res = http_get_json(oba_url, timeout=20)
        
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
                
            route_id = str(v.get("tripStatus", {}).get("activeTrip", {}).get("routeId") or "").strip()
            
            # Lookup Rule Config or Fallbacks
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
                seat_capacity = 40  # Standard Bus Default
                include_in_score = True

            matched_slug = match_city_for_point(vlat, vlon, city_boundaries)
            if matched_slug and matched_slug in city_map:
                v_obj = {
                    "vehicle_id": v.get("vehicleId"),
                    "agency": agency_name,
                    "route_id": route_id,
                    "latitude": vlat,
                    "longitude": vlon,
                    "seats": seat_capacity
                }
                
                if include_in_score:
                    city_map[matched_slug]["ground_vehicles"].append(v_obj)
                    city_map[matched_slug]["ground_seats"] += seat_capacity
                else:
                    city_map[matched_slug]["maritime_vessels"].append(v_obj)
                    city_map[matched_slug]["maritime_seats"] += seat_capacity
                    
                total_vehicles += 1

    output = {}
    for slug, details in city_map.items():
        pop = details["population"]
        pop_units = max(1.0, pop / 1000.0)
        ground_seats = details["ground_seats"]
        
        # Raw density metric (Seats per 1,000 residents)
        raw_seats_per_1k = round(ground_seats / pop_units, 2)
        
        # Standardized 0-100 Score Normalization (Benchmarked at 50 seats/1k residents)
        normalized_score = min(100, round((raw_seats_per_1k / 50.0) * 100))
        
        output[slug] = {
            "name": details["name"],
            "active_vehicles": len(details["ground_vehicles"]),
            "active_in_bounds_seats": ground_seats,
            "population_official": pop,
            "raw_seats_per_1k": raw_seats_per_1k,
            "active_transit_score": normalized_score,
            "maritime_capacity": {
                "active_vessels": len(details["maritime_vessels"]),
                "active_seats": details["maritime_seats"]
            },
            "last_updated": datetime.utcnow().isoformat() + "Z"
        }

    print(f"Successfully tracked {total_vehicles} in-bounds active transit vehicles across cities.")
    save_json("transit_radar_live.json", output)

# ==============================================================================
# MODULE 3: EPA AIRNOW 58-CITY NEAREST-NEIGHBOR AQI ENGINE
# ==============================================================================
def harvest_air_quality(cities):
    print("🍃 Harvesting EPA AirNow Live Air Quality Observations...")
    airnow_key = os.environ.get("AIRNOW_API_KEY", "").strip().strip("'").strip('"')
    
    if not airnow_key:
        print("AIRNOW_API_KEY missing. Skipping AirNow AQI ingestion.")
        return

    regional_stations = [
        {"name": "Seattle Hub", "lat": 47.6062, "lon": -122.3321},
        {"name": "Bellevue / Eastside Hub", "lat": 47.6101, "lon": -122.2015},
        {"name": "Everett / North Sound Hub", "lat": 47.9790, "lon": -122.2021},
        {"name": "Tacoma / South Sound Hub", "lat": 47.2529, "lon": -122.4443}
    ]

    station_data = []
    for st in regional_stations:
        url = f"https://www.airnowapi.org/aq/observation/latLong/current/?format=application/json&latitude={st['lat']}&longitude={st['lon']}&distance=25&API_KEY={airnow_key}"
        obs = http_get_json(url, timeout=15)
        if obs and isinstance(obs, list) and len(obs) > 0:
            primary_param = obs[0]
            station_data.append({
                "reporting_area": primary_param.get("ReportingArea", st["name"]),
                "aqi": primary_param.get("AQI", 30),
                "category": primary_param.get("Category", {}).get("Name", "Good"),
                "parameter": primary_param.get("ParameterName", "PM2.5"),
                "observed_time": f"{primary_param.get('DateObserved', '')} {primary_param.get('HourObserved', '')}:00",
                "lat": st["lat"],
                "lon": st["lon"]
            })

    if not station_data:
        print("AirNow Notice: Station feeds unreachable. Preserving baseline environment data.")
        return

    # Map nearest PSCAA station to all 58 cities via Spatial Haversine Distance
    city_aqi_map = {}
    for c in cities:
        clat, clon = c.get("latitude"), c.get("longitude")
        if clat is None or clon is None:
            continue
            
        nearest = min(station_data, key=lambda st: haversine_distance(clat, clon, st["lat"], st["lon"]))
        city_aqi_map[c["slug"]] = {
            "name": c["name"],
            "aqi": nearest["aqi"],
            "category": nearest["category"],
            "parameter": nearest["parameter"],
            "reporting_area": nearest["reporting_area"],
            "observed_time": nearest["observed_time"]
        }

    env_data = {}
    if os.path.exists(ENVIRONMENT_DATA_PATH):
        try:
            with open(ENVIRONMENT_DATA_PATH, "r", encoding="utf-8") as f:
                env_data = json.load(f)
        except Exception:
            env_data = {}

    env_data["city_air_quality"] = city_aqi_map
    env_data["last_updated"] = datetime.utcnow().isoformat() + "Z"

    print(f"Successfully mapped localized AQI readings across all {len(city_aqi_map)} cities in city_environment.json.")
    save_json("city_environment.json", env_data)

# ==============================================================================
# MODULE 4: WSDOT ACTIVE HIGHWAY CONSTRUCTION & WORK ZONES
# ==============================================================================
def harvest_construction(cities, city_boundaries):
    print("🚧 Harvesting WSDOT Active Construction & Work Zone Feeds...")
    wsdot_code = os.environ.get("WSDOT_ACCESS_CODE", "").strip().strip("'").strip('"')
    
    if not wsdot_code:
        print("WSDOT_ACCESS_CODE missing. Skipping Construction harvest.")
        return

    wsdot_alerts_url = f"https://wsdot.wa.gov/Traffic/api/HighwayAlerts/HighwayAlertsREST.svc/GetHighwayAlertsAsJson?AccessCode={wsdot_code}"
    alerts = http_get_json(wsdot_alerts_url, timeout=25)
    
    city_map = {c["slug"]: {"name": c["name"], "alert_count": 0, "alerts": []} for c in cities}
    total_alerts = 0

    if alerts and isinstance(alerts, list):
        print(f"Retrieved {len(alerts)} active state highway alerts from WSDOT.")
        for a in alerts:
            event_type = str(a.get("EventCategory") or "").lower()
            headline = str(a.get("HeadlineDescription") or "").lower()
            
            # WSDOT includes construction, maintenance, and work zone alerts under various terms
            if not any(k in event_type or k in headline for k in ["construction", "maintenance", "work", "closure", "paving", "repair"]):
                continue

            # Case-insensitive WSDOT location payload keys
            loc_obj = a.get("StartRoadWayLocation") or a.get("StartRoadwayLocation") or a.get("EndRoadWayLocation") or a.get("EndRoadwayLocation") or {}
            alat = loc_obj.get("Latitude") if isinstance(loc_obj, dict) else a.get("Latitude")
            alon = loc_obj.get("Longitude") if isinstance(loc_obj, dict) else a.get("Longitude")
            
            if alat is None or alon is None:
                continue

            try:
                alat, alon = float(alat), float(alon)
            except (ValueError, TypeError):
                continue

            alert_obj = {
                "alert_id": f"wsdot-{a.get('AlertID')}",
                "headline": a.get("HeadlineDescription", "Roadwork Alert"),
                "priority": a.get("Priority", "Low"),
                "event_category": a.get("EventCategory", "Construction"),
                "start_time": a.get("StartTime"),
                "end_time": a.get("EndTime"),
                "description": a.get("ExtendedDescription", "")
            }

            matched_slug = match_city_for_alert(alat, alon, city_boundaries, cities)
            if matched_slug and matched_slug in city_map:
                city_map[matched_slug]["alerts"].append(alert_obj)
                city_map[matched_slug]["alert_count"] += 1
                total_alerts += 1

    output = {}
    for slug, details in city_map.items():
        output[slug] = {
            "name": details["name"],
            "alert_count": details["alert_count"],
            "alerts": details["alerts"],
            "last_updated": datetime.utcnow().isoformat() + "Z"
        }

    print(f"Successfully mapped {total_alerts} active construction alerts across municipal boundaries.")
    save_json("city_construction.json", output)

# ==============================================================================
# MASTER SANDBOX EXECUTION ROUTINE
# ==============================================================================
if __name__ == "__main__":
    print("==================================================")
    print("     MYSEATTLESEARCH PHASE 2 SANDBOX ENGINE       ")
    print("==================================================\n")

    cities = load_city_data()
    city_boundaries = load_city_boundaries()
    sheets_config = load_sheets_admin_config()
    
    harvest_traffic_cams(cities, city_boundaries, sheets_config)
    harvest_transit_radar(cities, city_boundaries, sheets_config)
    harvest_air_quality(cities)
    harvest_construction(cities, city_boundaries)
    
    print("\n🎉 Phase 2 Sandbox Pipeline execution complete! All artifacts fresh.")