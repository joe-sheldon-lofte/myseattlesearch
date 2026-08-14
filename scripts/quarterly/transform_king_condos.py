import os
import json
import time
import requests
import re

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))
DATA_DIR = os.path.join(BASE_DIR, "data")

RAW_PATH = os.path.join(DATA_DIR, "king_county_raw.json")
OUT_PATH = os.path.join(DATA_DIR, "king_condos.json")

def clean_building_name(raw_name):
    """Extracts the real condo name from the messy legal description"""
    if not raw_name: return "Unknown Condominium"
    name = str(raw_name).upper()
    
    name = re.sub(r'\b(CONDOMINIUM|CONDO)\b.*$', '', name)
    name = re.sub(r'\b(PCT|UND|INT|UNIT|LOT|BLK|PHASE|DIV)\b.*$', '', name)
    name = re.sub(r'[^A-Z0-9\s-]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    
    if not name or len(name) < 3:
        return "Unknown Condominium"
    return name.title() + " Condominiums"

def get_polygon_center(geometry):
    """Calculates the center Lat/Lon from an ArcGIS map polygon"""
    if not geometry: return None, None
    rings = geometry.get("rings", [])
    if not rings or not rings[0]: return None, None
    
    points = rings[0]
    lons = [pt[0] for pt in points if len(pt) >= 2]
    lats = [pt[1] for pt in points if len(pt) >= 2]
    
    if not lons or not lats: return None, None
    
    center_lon = (min(lons) + max(lons)) / 2.0
    center_lat = (min(lats) + max(lats)) / 2.0
    
    return center_lat, center_lon

def transform_king_condos():
    print("🚀 Starting King County Transformer...")
    
    if not os.path.exists(RAW_PATH):
        print(f"❌ Raw file not found: {RAW_PATH}")
        return
        
    with open(RAW_PATH, 'r') as f:
        raw_data = json.load(f)
        
    # 1. Group the units by MAJOR (first 6 digits)
    complexes = {}
    for row in raw_data:
        pin = str(row.get("parcel_number", "")).zfill(10)
        if len(pin) != 10:
            continue
            
        major = pin[:6]
        
        if major not in complexes:
            complexes[major] = {
                "major": major,
                "unit_count": 0,
                "legal_description": row.get("legal_description", "")
            }
        complexes[major]["unit_count"] += 1
        
    # 2. Filter for buildings with > 8 units
    filtered_complexes = {k: v for k, v in complexes.items() if v["unit_count"] > 8}
    print(f"Found {len(filtered_complexes)} complexes with >8 units.")
    
    # 3. Batch query the GIS API
    api_urls = [
        "https://gismaps.kingcounty.gov/arcgis/rest/services/Property/KingCo_PropertyInfo/MapServer/2/query",
        "https://gismaps.kingcounty.gov/arcgis/rest/services/Property/KingCo_Parcels/MapServer/0/query"
    ]
    
    final_condos = []
    
    # Query using the 6-digit MAJOR code representing the building footprint
    majors_to_query = list(filtered_complexes.keys())
    batch_size = 50 
    
    print(f"Fetching map data in {len(majors_to_query)//batch_size + 1} batches...")
    
    for i in range(0, len(majors_to_query), batch_size):
        batch_majors = majors_to_query[i:i+batch_size]
        major_string = ",".join([f"'{m}'" for m in batch_majors])
        
        params = {
            "where": f"MAJOR IN ({major_string})",
            "outFields": "*", 
            "outSR": "4326",
            "f": "json",
            "returnGeometry": "true"
        }
        
        features_found = []
        
        for url in api_urls:
            try:
                res = requests.get(url, params=params)
                res.raise_for_status()
                data = res.json()
                if data.get("features"):
                    features_found = data["features"]
                    break 
            except Exception:
                continue
                
        for feature in features_found:
            attr = feature.get("attributes", {})
            major = attr.get("MAJOR") or attr.get("major") or ""
            
            if not major: continue
            
            major = str(major).zfill(6)
            
            if major in filtered_complexes:
                c_data = filtered_complexes[major]
                
                geom = feature.get("geometry", {})
                lat, lon = get_polygon_center(geom)
                
                raw_address = attr.get("SITUS_ADDRESS") or attr.get("ADDR_FULL") or attr.get("ADDRESS") or attr.get("Address") or "Unknown Address"
                raw_city = attr.get("SITUS_CITY") or attr.get("CTYNAME") or attr.get("CITY") or attr.get("City") or "King County"
                
                final_condos.append({
                    "building_id": f"kc_condo_{major}",
                    "name": clean_building_name(c_data["legal_description"]),
                    "address": str(raw_address).title(),
                    "city": str(raw_city).title(),
                    "state": "WA",
                    "latitude": lat,
                    "longitude": lon,
                    "total_units": c_data["unit_count"],
                    "stories": None,
                    "has_elevator": None
                })
                
        time.sleep(0.2)
        
    print(f"Successfully enriched and finalized {len(final_condos)} complexes.")
    
    with open(OUT_PATH, 'w') as f:
        json.dump(final_condos, f, indent=2)
        
    print(f"💾 Saved processed data to {OUT_PATH}\n")

if __name__ == "__main__":
    transform_king_condos()