import os
import json
import math
import urllib.request
import urllib.parse
from datetime import datetime

# Path references
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")
CITY_BOUNDARIES_PATH = os.path.join(DATA_DIR, "city_boundaries.json")
ENVIRONMENT_DATA_PATH = os.path.join(DATA_DIR, "city_environment.json")
DEMOGRAPHICS_DATA_PATH = os.path.join(DATA_DIR, "city_demographics.json")

# Complete Municipal Population Baseline Estimates for all 58 King & Snohomish Cities
CITY_POPULATION_ESTIMATES = {
    "algona": 3300, "auburn": 87000, "beaux-arts-village": 300, "bellevue": 151000,
    "black-diamond": 5800, "bothell": 48000, "burien": 51000, "carnation": 2200,
    "clyde-hill": 3100, "covington": 21000, "des-moines": 32000, "duvall": 8200,
    "enumclaw": 12500, "federal-way": 101000, "hunts-point": 400, "issaquah": 40000,
    "kenmore": 23500, "kent": 136000, "kirkland": 93000, "lake-forest-park": 13500,
    "maple-valley": 28000, "medina": 3000, "mercer-island": 25500, "milton": 8500,
    "newcastle": 13000, "normandy-park": 6700, "north-bend": 8000, "pacific": 7200,
    "redmond": 76000, "renton": 106000, "sammamish": 67000, "seatac": 31000,
    "seattle": 750000, "shoreline": 58000, "skykomish": 200, "snoqualmie": 14000,
    "tukwila": 21500, "woodinville": 13500, "yarrow-point": 1000, "arlington": 20000,
    "brier": 6800, "darrington": 1400, "edmonds": 42000, "everett": 112000,
    "gold-bar": 2400, "granite-falls": 4400, "index": 200, "lake-stevens": 39000,
    "lynnwood": 40000, "marysville": 71000, "mill-creek": 21000, "monroe": 20000,
    "mountlake-terrace": 21500, "mukilteo": 21500, "snohomish": 10500, "stanwood": 8000,
    "sultan": 5200, "woodway": 1300
}

def slugify(text):
    """Generate a clean URL slug from any city name string."""
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
    """Normalize municipal names for cross-dataset matching."""
    if not name or not isinstance(name, str):
        return ""
    return name.lower().replace("city of ", "").replace("town of ", "").strip()

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

# ==============================================================================
# SPATIAL POINT-IN-POLYGON & BOUNDING BOX ENGINE
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
    """Load and index city boundary polygons and bounding boxes."""
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

def load_city_data():
    """Load city_data.json and normalize city entries."""
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

        normalized.append({
            "slug": slug,
            "name": str(raw_name).strip(),
            "latitude": lat_float,
            "longitude": lon_float
        })

    print(f"Pre-processed {len(normalized)} city records from city_data.json.")
    return normalized

# ==============================================================================
# MODULE 1: MULTI-AGENCY TRAFFIC CAMERA HARVESTER
# ==============================================================================
def harvest_traffic_cams(cities, city_boundaries):
    print("🎥 Harvesting WSDOT & Seattle DOT Traffic Camera Feeds...")
    wsdot_code = os.environ.get("WSDOT_ACCESS_CODE", "").strip().strip("'").strip('"')
    
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
                title = cam.get("Title") or cam.get("CameraOwner") or "WSDOT Camera"
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
    else:
        print("WSDOT_ACCESS_CODE not found. Skipping WSDOT camera ingestion.")

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
                title = cam.get("Description") or "Seattle DOT Camera"
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

    # Format final JSON output payload
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
# MODULE 2: TRANSIT RADAR & ACTIVE SEAT SCORE ENGINE
# ==============================================================================
def harvest_transit_radar(cities, city_boundaries):
    print("🚆 Harvesting OneBusAway GTFS-Realtime Transit Positions...")
    oba_key = os.environ.get("ONEBUSAWAY_API_KEY", "").strip().strip("'").strip('"') or "TEST"
    
    agencies = {"1": "King County Metro", "29": "Sound Transit", "23": "Community Transit"}
    city_map = {c["slug"]: {"name": c["name"], "vehicles": [], "total_seats": 0} for c in cities}
    total_vehicles = 0

    for agency_id, agency_name in agencies.items():
        oba_url = f"https://api.pugetsound.onebusaway.org/api/where/vehicles-for-agency/{agency_id}.json?key={oba_key}"
        res = http_get_json(oba_url, timeout=20)
        
        if not res or not isinstance(res, dict) or res.get("code") != 200:
            print(f"OBA Warning: Unable to fetch vehicles for {agency_name} (Agency ID: {agency_id}).")
            continue
            
        data = res.get("data", {})
        v_list = data.get("list", []) if isinstance(data, dict) else []
        print(f"Retrieved {len(v_list)} active vehicles for {agency_name}.")

        for v in v_list:
            loc = v.get("location") or {}
            vlat = loc.get("lat")
            vlon = loc.get("lon")
            if vlat is None or vlon is None:
                continue
                
            try:
                vlat = float(vlat)
                vlon = float(vlon)
            except (ValueError, TypeError):
                continue
                
            if agency_id == "29":
                seat_capacity = 148  # Sound Transit / Light Rail / Sounder / ST Express
            elif agency_id == "23":
                seat_capacity = 60   # Community Transit / Swift BRT
            else:
                seat_capacity = 40   # King County Metro Standard Bus

            matched_slug = match_city_for_point(vlat, vlon, city_boundaries)
            if matched_slug and matched_slug in city_map:
                city_map[matched_slug]["vehicles"].append({
                    "vehicle_id": v.get("vehicleId"),
                    "agency": agency_name,
                    "trip_id": v.get("tripId"),
                    "latitude": vlat,
                    "longitude": vlon,
                    "seats": seat_capacity
                })
                city_map[matched_slug]["total_seats"] += seat_capacity
                total_vehicles += 1

    # Calculate Active Transit Score per 1,000 residents
    output = {}
    for slug, details in city_map.items():
        pop = CITY_POPULATION_ESTIMATES.get(slug, 25000)
        pop_units = max(1.0, pop / 1000.0)
        total_seats = details["total_seats"]
        active_score = round(total_seats / pop_units, 2)
        
        output[slug] = {
            "name": details["name"],
            "active_vehicles": len(details["vehicles"]),
            "active_in_bounds_seats": total_seats,
            "population_est": pop,
            "active_transit_score": active_score,
            "last_updated": datetime.utcnow().isoformat() + "Z"
        }

    print(f"Successfully tracked {total_vehicles} in-bounds active transit vehicles.")
    save_json("transit_radar_live.json", output)

# ==============================================================================
# MODULE 3: EPA AIRNOW AIR QUALITY INDEX (AQI) ENGINE
# ==============================================================================
def harvest_air_quality(cities):
    print("🍃 Harvesting EPA AirNow Live Air Quality Observations...")
    airnow_key = os.environ.get("AIRNOW_API_KEY", "").strip().strip("'").strip('"')
    
    if not airnow_key:
        print("AIRNOW_API_KEY missing. Skipping AirNow AQI ingestion.")
        return

    regional_stations = [
        {"name": "Seattle", "lat": 47.6062, "lon": -122.3321},
        {"name": "Bellevue / Eastside", "lat": 47.6101, "lon": -122.2015},
        {"name": "Everett / North Sound", "lat": 47.9790, "lon": -122.2021},
        {"name": "Tacoma / South Sound", "lat": 47.2529, "lon": -122.4443}
    ]

    aqi_observations = []
    for st in regional_stations:
        url = f"https://www.airnowapi.org/aq/observation/latLong/current/?format=application/json&latitude={st['lat']}&longitude={st['lon']}&distance=25&API_KEY={airnow_key}"
        obs = http_get_json(url, timeout=15)
        if obs and isinstance(obs, list) and len(obs) > 0:
            primary_param = obs[0]
            aqi_observations.append({
                "reporting_area": primary_param.get("ReportingArea", st["name"]),
                "aqi": primary_param.get("AQI"),
                "category": primary_param.get("Category", {}).get("Name", "Good"),
                "parameter": primary_param.get("ParameterName", "PM2.5"),
                "observed_time": f"{primary_param.get('DateObserved', '')} {primary_param.get('HourObserved', '')}:00"
            })

    env_data = {}
    if os.path.exists(ENVIRONMENT_DATA_PATH):
        try:
            with open(ENVIRONMENT_DATA_PATH, "r", encoding="utf-8") as f:
                env_data = json.load(f)
        except Exception:
            env_data = {}

    env_data["city_air_quality"] = aqi_observations
    env_data["last_updated"] = datetime.utcnow().isoformat() + "Z"

    print(f"Successfully appended {len(aqi_observations)} live AQI observations to city_environment.json.")
    save_json("city_environment.json", env_data)

# ==============================================================================
# MAIN SANDBOX EXECUTION ROUTINE
# ==============================================================================
if __name__ == "__main__":
    print("Starting Phase 2 Sandbox Test Harvest Pipeline...")
    cities = load_city_data()
    city_boundaries = load_city_boundaries()
    
    harvest_traffic_cams(cities, city_boundaries)
    harvest_transit_radar(cities, city_boundaries)
    harvest_air_quality(cities)
    
    print("Phase 2 Sandbox Test Harvest Pipeline Complete.")