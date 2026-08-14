import os
import json
import re
import requests
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
    
    # Filter out metes & bounds descriptions unless 'PLAT OF' is explicitly present
    if re.search(r'\b(BEG|BEGINNING|STR|STR\d|N\s+\d+|S\s+\d+|E\s+\d+|W\s+\d+|PCL|PARCEL|BAAP|LYING|TRACT|QUARTER|QTR|SEC|SECTION|TWP|RNG|FT|FEET)\b', name, re.I):
        if "PLAT OF" in name.upper():
            match = re.search(r'PLAT\s+OF\s+([A-Za-z0-9\s-]+)', name, re.I)
            if match:
                name = match.group(1)
            else:
                return ""
        else:
            return ""
            
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
    print("🚀 Starting King County Subdivision Harvester...")
    os.makedirs(DATA_DIR, exist_ok=True)
    
    socrata_url = "https://data.kingcounty.gov/resource/4854-i48r.json"
    kc_plat_map = {}
    offset = 0
    limit = 5000
    
    print("📡 Streaming King County Recorded Plats from Socrata...")
    while True:
        params = {
            "$where": "upper(legal_description) like '%PLAT OF%'",
            "$limit": str(limit),
            "$offset": str(offset)
        }
        try:
            res = requests.get(socrata_url, params=params, timeout=25)
            res.raise_for_status()
            data = res.json()
            
            if not data:
                break
                
            for item in data:
                parcel = str(item.get("parcel_number", "")).strip().zfill(10)
                if len(parcel) != 10:
                    continue
                major = parcel[:6]
                
                legal_desc = item.get("legal_description", "")
                plat_name = clean_plat_name(legal_desc)
                
                if plat_name and major != "000000":
                    if major not in kc_plat_map:
                        kc_plat_map[major] = {
                            "name": plat_name,
                            "lots": 1
                        }
                    else:
                        kc_plat_map[major]["lots"] += 1
                        
            if len(data) < limit:
                break
            offset += limit
        except Exception as e:
            print(f"⚠️ Socrata query failed: {e}")
            break

    print(f"Found {len(kc_plat_map)} King County subdivision major blocks.")
    
    gis_url = "https://gismaps.kingcounty.gov/arcgis/rest/services/Property/KingCo_Parcels/MapServer/0/query"
    final_subdivisions = []
    major_keys = list(kc_plat_map.keys())
    batch_size = 50
    
    print(f"Fetching precise map coordinates in {len(major_keys)//batch_size + 1} batches...")
    
    for i in range(0, len(major_keys), batch_size):
        chunk = major_keys[i:i+batch_size]
        quoted_chunk = [f"'{k}'" for k in chunk]
        where_clause = f"MAJOR IN ({','.join(quoted_chunk)})"
        
        gis_params = {
            "where": where_clause,
            "outFields": "MAJOR,PIN",
            "outSR": "4326",  # Standard WGS84 GPS degrees
            "f": "json",
            "returnGeometry": "true"
        }
        
        try:
            res = requests.get(gis_url, params=gis_params, timeout=15)
            res.raise_for_status()
            gis_data = res.json()
            
            coords_map = {}
            for feat in gis_data.get("features", []):
                attrs = feat.get("attributes", {})
                geom = feat.get("geometry", {})
                major = str(attrs.get("MAJOR", "")).zfill(6)
                if major and major not in coords_map:
                    lat, lon = get_polygon_center(geom)
                    if lat and lon:
                        coords_map[major] = (lat, lon)
                        
            for major in chunk:
                if major in coords_map:
                    plat_data = kc_plat_map[major]
                    lat, lon = coords_map[major]
                    
                    subdivisions_entry = {
                        "plat_id": f"plat_kc_{major}",
                        "name": plat_data["name"],
                        "slug": slugify(plat_data["name"]),
                        "city": "King County",
                        "county": "King",
                        "lot_count": max(plat_data["lots"], 6),
                        "latitude": lat,
                        "longitude": lon,
                        "last_updated": datetime.now().strftime("%Y-%m-%d")
                    }
                    
                    if not any(s["plat_id"] == subdivisions_entry["plat_id"] for s in final_subdivisions):
                        final_subdivisions.append(subdivisions_entry)
        except Exception as e:
            print(f"⚠️ GIS batch query failed: {e}")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(final_subdivisions, f, indent=2, ensure_ascii=False)

    print(f"💾 Saved {len(final_subdivisions)} King County subdivisions to {OUT_PATH}\n")

if __name__ == "__main__":
    harvest_king_subdivisions()