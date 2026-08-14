import os
import json
import math
import re
import requests
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))
DATA_DIR = os.path.join(BASE_DIR, "data")
STAGING_DIR = os.path.join(DATA_DIR, "staging")
CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")
OUT_PATH = os.path.join(STAGING_DIR, "snohomish_subdivisions.json")

def slugify(text):
    if not text: return ""
    text = str(text).lower().strip()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    return text.strip('-')

def clean_plat_name(raw_name):
    if not raw_name or str(raw_name).upper() in ["NONE", "UNKNOWN", "NULL"]:
        return ""
    name = str(raw_name).strip()
    name = re.sub(r'^(PLAT\s+OF|SUBDIVISION\s+OF|PLAT\s+)', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[^a-zA-Z0-9\s-]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    if len(name) < 3 or name.isdigit():
        return ""
    return name.title()

def parse_recording_year(record_ts):
    if not record_ts:
        return None
    
    try:
        val = float(record_ts)
        if val > 1e11:
            val = val / 1000.0
        dt = datetime.utcfromtimestamp(val)
        if 1900 <= dt.year <= 2100:
            return dt.year
    except (ValueError, TypeError, OverflowError):
        pass

    val_str = str(record_ts).strip()
    match = re.search(r'\b(20\d\d|19\d\d)\b', val_str)
    if match:
        return int(match.group(1))

    return None

def load_city_centers():
    centers = []
    if os.path.exists(CITY_DATA_PATH):
        try:
            with open(CITY_DATA_PATH, "r", encoding="utf-8") as f:
                raw_c = json.load(f)
            c_items = raw_c if isinstance(raw_c, list) else list(raw_c.values())
            for item in c_items:
                c_name = item.get("City") or item.get("name") or ""
                lat = item.get("Latitude") or item.get("lat") or item.get("latitude")
                lon = item.get("Longitude") or item.get("lon") or item.get("lng") or item.get("longitude")
                if c_name and lat and lon:
                    try:
                        centers.append({
                            "slug": slugify(c_name),
                            "name": str(c_name).strip(),
                            "lat": float(lat),
                            "lon": float(lon)
                        })
                    except (ValueError, TypeError):
                        pass
        except Exception:
            pass
    return centers

def match_city_for_point(lat, lon, city_centers):
    if lat is not None and lon is not None and city_centers:
        closest_city = None
        min_dist = float("inf")
        for c in city_centers:
            dist = math.hypot(lat - c["lat"], lon - c["lon"])
            if dist < min_dist:
                min_dist = dist
                closest_city = c["name"]

        if closest_city and min_dist <= 0.35:
            return closest_city

    return "Snohomish County"

def get_polygon_center(geometry):
    if not geometry: return None, None
    rings = geometry.get("rings", [])
    if not rings or not rings[0]: return None, None
    
    points = rings[0]
    lons = [pt[0] for pt in points if len(pt) >= 2]
    lats = [pt[1] for pt in points if len(pt) >= 2]
    
    if not lons or not lats: return None, None
    return (min(lats) + max(lats)) / 2.0, (min(lons) + max(lons)) / 2.0

def harvest_snohomish_subdivisions():
    print("🚀 Starting Snohomish County Subdivision Harvester...")
    os.makedirs(STAGING_DIR, exist_ok=True)
    
    city_centers = load_city_centers()
    sub_url = "https://services6.arcgis.com/z6WYi9VRHfgwgtyW/arcgis/rest/services/Subdivisions/FeatureServer/0/query"
    
    two_years_ago = datetime.now() - timedelta(days=730)
    date_str = two_years_ago.strftime("%Y-%m-%d")
    
    params = {
        "where": f"SUB_NAME IS NOT NULL AND (RECORDDATE >= DATE '{date_str}' OR CREATEDATE >= DATE '{date_str}')",
        "outFields": "OBJECTID,SUB_NAME,SUB_REF,RECORDDATE,CREATEDATE,GIS_SQ_FT",
        "outSR": "4326",
        "f": "json",
        "returnGeometry": "true",
        "resultRecordCount": 2000
    }
    
    subdivisions = []
    seen_names = set()
    offset = 0
    limit = 2000
    
    print(f"📡 Querying Snohomish County Subdivisions recorded/created since {date_str}...")
    
    while True:
        params["resultOffset"] = offset
        try:
            res = requests.get(sub_url, params=params, timeout=15)
            res.raise_for_status()
            data = res.json()
            
            if "error" in data:
                print(f"⚠️ ArcGIS Error: {data['error']}")
                break
                
            features = data.get("features", [])
            if not features:
                break
                
            for feat in features:
                attrs = feat.get("attributes", {})
                geom = feat.get("geometry", {})
                
                raw_name = attrs.get("SUB_NAME")
                plat_name = clean_plat_name(raw_name)
                if not plat_name or plat_name in seen_names:
                    continue
                    
                seen_names.add(plat_name)
                lat, lon = get_polygon_center(geom)
                matched_city = match_city_for_point(lat, lon, city_centers)
                
                record_ts = attrs.get("RECORDDATE") or attrs.get("CREATEDATE")
                rec_year = parse_recording_year(record_ts)
                
                sub_ref = str(attrs.get("SUB_REF", "") or "").strip()
                
                assessor_url = "https://www.snohomishcountywa.gov/3169/Property-Summary-Information"
                gis_viewer_url = "https://snohomishcountywa.gov/5414/Interactive-Map-SCOPI"
                
                subdivisions.append({
                    "plat_id": f"plat_sno_{attrs.get('OBJECTID')}",
                    "name": plat_name,
                    "slug": slugify(plat_name),
                    "subdivision_ref": sub_ref,
                    "city": matched_city,
                    "county": "Snohomish",
                    "builder_name": "Unable to Verify",
                    "recording_year": rec_year,
                    "sq_ft": attrs.get("GIS_SQ_FT"),
                    "latitude": lat,
                    "longitude": lon,
                    "assessor_url": assessor_url,
                    "gis_viewer_url": gis_viewer_url,
                    "last_updated": datetime.now().strftime("%Y-%m-%d")
                })
                
            if not data.get("exceededTransferLimit", False):
                break
                
            offset += limit
        except Exception as e:
            print(f"❌ Error harvesting Snohomish subdivisions: {e}")
            break
            
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(subdivisions, f, indent=2, ensure_ascii=False)
        
    print(f"💾 Staged {len(subdivisions)} Snohomish subdivisions to {OUT_PATH}\n")

if __name__ == "__main__":
    harvest_snohomish_subdivisions()