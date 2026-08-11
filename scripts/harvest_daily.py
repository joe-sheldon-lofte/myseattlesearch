import os
import json
import math
import sys
import traceback
import urllib.request
import urllib.parse
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")
CITY_BOUNDARIES_PATH = os.path.join(DATA_DIR, "city_boundaries.json")
TRAFFIC_CAMS_PATH = os.path.join(DATA_DIR, "traffic_cams.json")
TRANSIT_DATA_PATH = os.path.join(DATA_DIR, "transit_data.json")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly"
]

def get_gspread_client():
    creds_json = (
        os.environ.get("GA_GOOGLE_CREDENTIALS") or 
        os.environ.get("GOOGLE_CREDENTIALS") or 
        os.environ.get("GA_CREDENTIALS")
    )
    if creds_json and creds_json.strip():
        try:
            creds_dict = json.loads(creds_json)
            creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
            return gspread.authorize(creds), creds
        except Exception as e:
            print(f"⚠️ Could not parse JSON from environment variable: {e}")

    if os.path.exists("credentials.json"):
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
        return gspread.authorize(creds), creds

    raise FileNotFoundError("Google service account credentials not found. Ensure GA_GOOGLE_CREDENTIALS secret is configured.")

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

def http_get_json_simple(url, timeout=25):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) RealEstateDataBot/1.0"}
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

def match_city_for_alert(lat, lon, city_boundaries, cities):
    matched = match_city_for_point(lat, lon, city_boundaries)
    if matched:
        return matched

    closest_city = None
    min_dist = 3.0
    for c in cities:
        clat, clon = c.get("latitude"), c.get("longitude")
        if clat is None or clon is None:
            continue
        dist = haversine_distance(lat, lon, clat, clon)
        if dist < min_dist:
            min_dist = dist
            closest_city = c["slug"]

    return closest_city

def load_city_data_normalized():
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

        normalized.append({
            "slug": slug,
            "name": str(raw_name).strip(),
            "latitude": lat_float,
            "longitude": lon_float
        })

    return normalized

def safe_run(task_name, func):
    print(f"🚀 Starting daily task: {task_name}...")
    try:
        func()
        print(f"✅ Completed daily task: {task_name}\n")
    except Exception as e:
        print(f"❌ Error during {task_name}: {e}")
        print(traceback.format_exc())
        print(f"⚠️ Skipping {task_name}. Existing dataset preserved.\n")

# --- HARVEST TASK 1: CITY DATA MASTER WORKBOOK ---
def harvest_city_data():
    client, _ = get_gspread_client()
    sheet_id = os.environ.get("CITY_DATA_SHEET_ID")
    if not sheet_id:
        print("ℹ️ CITY_DATA_SHEET_ID environment variable not set. Skipping.")
        return

    doc = client.open_by_key(sheet_id)
    try:
        worksheet = doc.worksheet("CityData")
    except gspread.exceptions.WorksheetNotFound:
        worksheet = doc.worksheet("City Data")
        
    records = worksheet.get_all_records()

    os.makedirs(DATA_DIR, exist_ok=True)
    out_path = os.path.join(DATA_DIR, "city_data.json")
    
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    
    print(f"💾 Saved {len(records)} city master records to {out_path}")

# --- HARVEST TASK 2: WEBSITE STATS TAB ---
def harvest_website_stats():
    client, _ = get_gspread_client()
    sheet_id = os.environ.get("WEBSITE_DATA_SHEET_ID")
    if not sheet_id:
        print("ℹ️ WEBSITE_DATA_SHEET_ID environment variable not set. Skipping stats sync.")
        return

    doc = client.open_by_key(sheet_id)
    try:
        worksheet = doc.worksheet("Stats")
        records = worksheet.get_all_records()
        
        os.makedirs(DATA_DIR, exist_ok=True)
        out_path = os.path.join(DATA_DIR, "stats.json")
        
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
        
        print(f"💾 Saved stats records to {out_path}")
    except gspread.exceptions.WorksheetNotFound:
        print("ℹ️ 'Stats' worksheet not found in Website Data workbook. Skipping.")

# --- HARVEST TASK 3: SHEETS ADMIN CONFIG BACKUP ---
def harvest_sheets_admin_config():
    _, creds = get_gspread_client()
    sheet_id = os.environ.get("CITY_DATA_SHEET_ID")
    if not sheet_id:
        print("ℹ️ CITY_DATA_SHEET_ID not set. Skipping Admin Config backup.")
        return

    try:
        service = build('sheets', 'v4', credentials=creds)
        sheet_meta = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
        sheet_titles = [s.get('properties', {}).get('title', '') for s in sheet_meta.get('sheets', [])]
        
        traffic_cams_title = next((t for t in sheet_titles if "trafficcam" in t.lower().replace(" ", "").replace("_", "")), None)
        transit_data_title = next((t for t in sheet_titles if "transitdata" in t.lower().replace(" ", "").replace("_", "")), None)

        ranges_to_fetch = []
        if traffic_cams_title:
            ranges_to_fetch.append(f"'{traffic_cams_title}'!A1:Z5000")
        if transit_data_title:
            ranges_to_fetch.append(f"'{transit_data_title}'!A1:Z200")

        if ranges_to_fetch:
            batch = service.spreadsheets().values().batchGet(
                spreadsheetId=sheet_id, ranges=ranges_to_fetch
            ).execute().get('valueRanges', [])

            if traffic_cams_title and len(batch) > 0:
                feed_rows = batch[0].get('values', [])
                if feed_rows and len(feed_rows) > 1:
                    headers = [str(h).strip() for h in feed_rows[0]]
                    raw_feeds_export = []
                    for r in feed_rows[1:]:
                        padded = list(r) + [""] * (len(headers) - len(r))
                        raw_feeds_export.append(dict(zip(headers, padded)))
                    with open(TRAFFIC_CAMS_PATH, "w", encoding="utf-8") as f:
                        json.dump(raw_feeds_export, f, indent=2, ensure_ascii=False)
                    print(f"💾 Exported {len(raw_feeds_export)} traffic cam overrides to {TRAFFIC_CAMS_PATH}")

            transit_batch_idx = 1 if (traffic_cams_title and len(batch) > 1) else 0
            if transit_data_title and len(batch) > transit_batch_idx:
                transit_rows = batch[transit_batch_idx].get('values', [])
                if transit_rows and len(transit_rows) > 1:
                    headers = [str(h).strip() for h in transit_rows[0]]
                    raw_transit_export = []
                    for r in transit_rows[1:]:
                        padded = list(r) + [""] * (len(headers) - len(r))
                        raw_transit_export.append(dict(zip(headers, padded)))
                    with open(TRANSIT_DATA_PATH, "w", encoding="utf-8") as f:
                        json.dump(raw_transit_export, f, indent=2, ensure_ascii=False)
                    print(f"💾 Exported {len(raw_transit_export)} transit rules to {TRANSIT_DATA_PATH}")

    except Exception as e:
        print(f"⚠️ Sheets Admin Config Backup Notice: {e}")

# --- HARVEST TASK 4: MULTI-AGENCY TRAFFIC CAMERAS INDEX ---
def harvest_traffic_cams():
    cities = load_city_data_normalized()
    city_boundaries = load_city_boundaries()
    
    feed_overrides = {}
    if os.path.exists(TRAFFIC_CAMS_PATH):
        try:
            with open(TRAFFIC_CAMS_PATH, "r", encoding="utf-8") as f:
                feeds_list = json.load(f)
                for row_dict in feeds_list:
                    feed_id = row_dict.get("Feed ID", "").strip()
                    if feed_id:
                        feed_overrides[feed_id] = {
                            "name": row_dict.get("Feed Name", "").strip(),
                            "active": str(row_dict.get("Active", "Yes")).strip().lower() == "yes"
                        }
        except Exception as e:
            print(f"Traffic Cams Config Read Notice: {e}")

    wsdot_code = os.environ.get("WSDOT_ACCESS_CODE", "").strip().strip("'").strip('"')
    city_map = {c["slug"]: {"name": c["name"], "cameras": []} for c in cities}
    total_found = 0

    if wsdot_code:
        wsdot_url = f"https://wsdot.wa.gov/Traffic/api/HighwayCameras/HighwayCamerasREST.svc/GetCamerasAsJson?AccessCode={wsdot_code}"
        cams = http_get_json_simple(wsdot_url, timeout=25)
        if cams and isinstance(cams, list):
            for cam in cams:
                try:
                    clat = float(cam.get("CameraLocation", {}).get("Latitude"))
                    clon = float(cam.get("CameraLocation", {}).get("Longitude"))
                except (ValueError, TypeError):
                    continue
                    
                cam_id = f"wsdot-{cam.get('CameraID')}"
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

    sdot_url = "https://web6.seattle.gov/Travelers/api/Map/GetMapData"
    sdot_res = http_get_json_simple(sdot_url, timeout=25)
    if sdot_res and isinstance(sdot_res, dict) and "Features" in sdot_res:
        features = sdot_res.get("Features", [])
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

    out_path = os.path.join(DATA_DIR, "city_traffic_cams.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"💾 Saved {total_found} active traffic cameras across cities to {out_path}")

# --- HARVEST TASK 5: WSDOT ACTIVE CONSTRUCTION & WORK ZONES ---
def harvest_construction():
    cities = load_city_data_normalized()
    city_boundaries = load_city_boundaries()
    
    wsdot_code = os.environ.get("WSDOT_ACCESS_CODE", "").strip().strip("'").strip('"')
    if not wsdot_code:
        print("ℹ️ WSDOT_ACCESS_CODE missing. Skipping Construction harvest.")
        return

    wsdot_alerts_url = f"https://wsdot.wa.gov/Traffic/api/HighwayAlerts/HighwayAlertsREST.svc/GetAlertsAsJson?AccessCode={wsdot_code}"
    alerts = http_get_json_simple(wsdot_alerts_url, timeout=25)
    
    city_map = {c["slug"]: {"name": c["name"], "alert_count": 0, "alerts": []} for c in cities}
    total_alerts = 0

    if alerts and isinstance(alerts, list):
        for a in alerts:
            event_type = str(a.get("EventCategory") or "").lower()
            headline = str(a.get("HeadlineDescription") or "").lower()
            ext_desc = str(a.get("ExtendedDescription") or "").lower()
            
            combined_text = f"{event_type} {headline} {ext_desc}"
            if not any(k in combined_text for k in ["construction", "maintenance", "work", "closure", "paving", "repair", "delay", "lane"]):
                continue

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

    out_path = os.path.join(DATA_DIR, "city_construction.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"💾 Saved {total_alerts} active construction alerts to {out_path}")

# --- HARVEST TASK 6: DAILY QUIZZES PROCESSOR ---
def harvest_quizzes_daily():
    print("🎯 Executing Daily Quizzes Processor...")
    script_path = os.path.join(BASE_DIR, "scripts", "daily", "quizzes_processor.py")
    if os.path.exists(script_path):
        exit_code = os.system(f"{sys.executable} {script_path}")
        if exit_code != 0:
            print(f"⚠️ quizzes_processor.py exited with status code {exit_code}")
    else:
        print(f"⚠️ Daily quizzes script not found at {script_path}")

def main():
    print("==================================================")
    print("       MYSEATTLESEARCH DAILY DATA HARVESTER       ")
    print("==================================================\n")
    
    safe_run("City Data Master Sheet Sync (data/city_data.json)", harvest_city_data)
    safe_run("Website Data Stats Sync (data/stats.json)", harvest_website_stats)
    safe_run("Sheets Admin Config Backup (data/traffic_cams.json & transit_data.json)", harvest_sheets_admin_config)
    safe_run("Traffic Cameras Mapping (data/city_traffic_cams.json)", harvest_traffic_cams)
    safe_run("WSDOT Construction & Work Zones (data/city_construction.json)", harvest_construction)
    safe_run("Daily Quizzes Processing (data/quizzes.json)", harvest_quizzes_daily)
    
    print("🎉 Daily data harvesting sequence completed.")

if __name__ == "__main__":
    main()