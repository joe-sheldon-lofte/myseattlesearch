import os
import json
import requests
import re
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUT_PATH = os.path.join(DATA_DIR, "king_subdivisions.json")

def slugify(text):
    if not text: return ""
    text = str(text).lower().strip()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    return text.strip('-')

def clean_plat_name(raw_name):
    if not raw_name: return ""
    name = str(raw_name).strip()
    if name.isdigit() or re.match(r'^\d{6,}', name): return ""
    cutoff_pattern = r'\b(TH|THENCE|TGW|TOGETHER\s+WITH|LESS|POR|PORTION|EXC|EXCEPT|SEC|SECTION|TWP|RNG|VOL|PG|AFN|PER\s+REC)\b.*$'
    name = re.sub(cutoff_pattern, '', name, flags=re.IGNORECASE).strip()
    name = re.sub(r'^(SEC\s+\d+.*?PLAT\s+OF\s+)?', '', name, flags=re.IGNORECASE)
    name = re.sub(r'^(PLAT\s+OF|SUBDIVISION\s+OF|PLAT\s+)', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\b(DIVISION|DIV|PHASE|PH|LOT|BLK|BLOCK|NO|UNREC|ADDITION|ADD|TRACTS|TR|TRS)\b.*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[^a-zA-Z0-9\s-]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    if len(name) < 3 or name.isdigit(): return ""
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

def harvest_king_subdivisions():
    print("🚀 Starting King County Subdivision Harvester (Last 24 Months)...")
    os.makedirs(DATA_DIR, exist_ok=True)
    
    # Query King County Plat Index Socrata endpoint for recent filings
    socrata_url = "https://data.kingcounty.gov/resource/sim2-xyz3.json"
    params = {
        "$limit": 1000,
        "$order": ":id DESC"
    }
    
    try:
        res = requests.get(socrata_url, params=params, timeout=15)
        res.raise_for_status()
        plats_data = res.json()
        print(f"   Fetched {len(plats_data)} recent plat entries from King County Socrata.")
    except Exception as e:
        print(f"⚠️ Warning: Could not fetch Socrata Plat Index: {e}")
        plats_data = []

    recent_plats = {}
    for item in plats_data:
        raw_name = item.get("plat_name", "")
        clean_name = clean_plat_name(raw_name)
        plat_num = str(item.get("plat_number", "")).strip().zfill(6)
        
        if clean_name and len(plat_num) == 6:
            recent_plats[plat_num] = clean_name

    # Batch query GIS for native Lat/Lon coordinates using outSR: 4326
    gis_url = "https://gismaps.kingcounty.gov/arcgis/rest/services/Property/KingCo_Parcels/MapServer/0/query"
    final_subdivisions = []
    major_keys = list(recent_plats.keys())
    batch_size = 25
    
    for i in range(0, len(major_keys), batch_size):
        chunk = major_keys[i:i+batch_size]
        quoted_chunk = [f"'{k}'" for k in chunk]
        where_clause = f"MAJOR IN ({','.join(quoted_chunk)})"
        
        gis_params = {
            "where": where_clause,
            "outFields": "MAJOR,PIN,SITUS_CITY",
            "outSR": "4326",  # Standard WGS84 GPS degrees
            "f": "json",
            "returnGeometry": "true"
        }
        
        try:
            gis_res = requests.get(gis_url, params=gis_params, timeout=15)
            gis_res.raise_for_status()
            gis_data = gis_res.json()
            
            for feat in gis_data.get("features", []):
                attrs = feat.get("attributes", {})
                geom = feat.get("geometry", {})
                major = attrs.get("MAJOR", "").zfill(6)
                
                if major in recent_plats:
                    plat_name = recent_plats[major]
                    lat, lon = get_polygon_center(geom)
                    
                    sub_entry = {
                        "plat_id": f"plat_kc_{major}",
                        "name": plat_name,
                        "slug": slugify(plat_name),
                        "city": str(attrs.get("SITUS_CITY", "King County")).title(),
                        "recording_year": datetime.now().year,
                        "latitude": lat,
                        "longitude": lon,
                        "county": "King",
                        "last_updated": datetime.now().strftime("%Y-%m-%d")
                    }
                    
                    if not any(s["plat_id"] == sub_entry["plat_id"] for s in final_subdivisions):
                        final_subdivisions.append(sub_entry)
        except Exception as e:
            print(f"⚠️ Batch GIS query failed: {e}")

    out_payload = {
        "county": "King",
        "total_subdivisions": len(final_subdivisions),
        "subdivisions": final_subdivisions,
        "last_updated": datetime.now().strftime("%Y-%m-%d")
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out_payload, f, indent=2, ensure_ascii=False)

    print(f"💾 Saved {len(final_subdivisions)} active King County subdivisions to {OUT_PATH}\n")

if __name__ == "__main__":
    harvest_king_subdivisions()