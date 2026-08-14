import os
import json
import requests
import re
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUT_PATH = os.path.join(DATA_DIR, "snohomish_subdivisions.json")

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
    os.makedirs(DATA_DIR, exist_ok=True)
    
    sub_url = "https://services6.arcgis.com/z6WYi9VRHfgwgtyW/arcgis/rest/services/Subdivisions/FeatureServer/0/query"
    
    params = {
        "where": "SUB_NAME IS NOT NULL",
        "outFields": "OBJECTID,SUB_NAME,SUB_REF,RECORDDATE,CREATEDATE,GIS_SQ_FT",
        "outSR": "4326",  # Native Lat/Lon degrees
        "f": "json",
        "returnGeometry": "true",
        "resultRecordCount": 2000
    }
    
    subdivisions = []
    seen_names = set()
    offset = 0
    limit = 2000
    
    while True:
        params["resultOffset"] = offset
        try:
            res = requests.get(sub_url, params=params, timeout=15)
            res.raise_for_status()
            data = res.json()
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
                
                record_ts = attrs.get("RECORDDATE")
                rec_year = None
                if record_ts:
                    try:
                        rec_year = datetime.fromtimestamp(record_ts / 1000.0).year
                    except Exception:
                        pass
                        
                subdivisions.append({
                    "plat_id": f"plat_sno_{attrs.get('OBJECTID')}",
                    "name": plat_name,
                    "slug": slugify(plat_name),
                    "subdivision_ref": attrs.get("SUB_REF", ""),
                    "city": "Snohomish County",
                    "county": "Snohomish",
                    "recording_year": rec_year,
                    "sq_ft": attrs.get("GIS_SQ_FT"),
                    "latitude": lat,
                    "longitude": lon,
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
        
    print(f"💾 Saved {len(subdivisions)} active Snohomish subdivisions to {OUT_PATH}\n")

if __name__ == "__main__":
    harvest_snohomish_subdivisions()