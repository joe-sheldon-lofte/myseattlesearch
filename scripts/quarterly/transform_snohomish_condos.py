import os
import json
import time
import requests
import re

# Navigate up to the repo root
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))
DATA_DIR = os.path.join(BASE_DIR, "data")

RAW_PATH = os.path.join(DATA_DIR, "snohomish_county_raw.json")
OUT_PATH = os.path.join(DATA_DIR, "snohomish_condos.json")

def clean_subdivision_name(raw_name):
    """Cleans raw SUB_NAME text into a polished building name."""
    if not raw_name: return None
    name = str(raw_name).strip()
    if not name or name.upper() in ["NONE", "UNKNOWN", "NULL"]:
        return None
        
    name_upper = name.upper()
    name_clean = re.sub(r'\b(HOA|LLC|INC|ASSOC|ASSOCIATION)\b.*$', '', name_upper)
    name_clean = re.sub(r'[^A-Z0-9\s-]', '', name_clean)
    name_clean = re.sub(r'\s+', ' ', name_clean).strip()
    
    if len(name_clean) < 3 or name_clean.isdigit():
        return None
        
    if "CONDO" not in name_clean:
        name_clean += " CONDOMINIUMS"
        
    return name_clean.title()

def clean_address(unit):
    """Safely builds the street address, ignoring apartment/unit fields."""
    house = str(unit.get("SITUSHOUSE", "") or "").strip()
    street = str(unit.get("SITUSSTRT", "") or "").strip().title()
    st_type = str(unit.get("SITUSSTTYP", "") or "").strip().title()
    
    address = f"{house} {street} {st_type}".strip()
    
    if not address or "Unknown" in address:
        raw_line = str(unit.get("SITUSLINE1", "")).title()
        address = re.sub(r'\b(Unit|Apt|Bldg|Ste|#)\b.*$', '', raw_line, flags=re.IGNORECASE).strip()
        
    # Fixes duplicate house numbers at start (e.g. "610 610 Front St" -> "610 Front St")
    address = re.sub(r'^(\d+)\s+\1\b', r'\1', address)
    
    return address

def get_polygon_center(geometry):
    """Calculates the center Lat/Lon from an ArcGIS map polygon."""
    if not geometry: return None, None
    rings = geometry.get("rings", [])
    if not rings or not rings[0]: return None, None
    
    points = rings[0]
    lons = [pt[0] for pt in points if len(pt) >= 2]
    lats = [pt[1] for pt in points if len(pt) >= 2]
    
    if not lons or not lats: return None, None
    
    return (min(lats) + max(lats)) / 2.0, (min(lons) + max(lons)) / 2.0

def point_in_polygon(lat, lon, rings):
    """Pure Python ray-casting algorithm for spatial point-in-polygon check."""
    inside = False
    for ring in rings:
        n = len(ring)
        if n < 3: continue
        p1x, p1y = ring[0][0], ring[0][1] # lon, lat
        for i in range(1, n + 1):
            p2x, p2y = ring[i % n][0], ring[i % n][1]
            if lat > min(p1y, p2y):
                if lat <= max(p1y, p2y):
                    if lon <= max(p1x, p2x):
                        if p1y != p2y:
                            xinters = (lat - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                        if p1x == p2x or lon <= xinters:
                            inside = not inside
            p1x, p1y = p2x, p2y
    return inside

def fetch_all_subdivisions():
    """Bulk fetches subdivision polygons in 1-2 API calls for fast local spatial matching."""
    print("📡 Pre-loading Snohomish Subdivisions map layer into memory...")
    sub_url = "https://services6.arcgis.com/z6WYi9VRHfgwgtyW/arcgis/rest/services/Subdivisions/FeatureServer/0/query"
    
    subdivisions = []
    offset = 0
    limit = 2000
    
    while True:
        params = {
            "where": "SUB_NAME IS NOT NULL",
            "outFields": "SUB_NAME",
            "outSR": "4326",
            "f": "json",
            "returnGeometry": "true",
            "resultOffset": offset,
            "resultRecordCount": limit
        }
        
        try:
            res = requests.get(sub_url, params=params, timeout=15)
            res.raise_for_status()
            data = res.json()
            features = data.get("features", [])
            
            if not features:
                break
                
            for feat in features:
                raw_name = feat.get("attributes", {}).get("SUB_NAME")
                clean_name = clean_subdivision_name(raw_name)
                geom = feat.get("geometry", {})
                rings = geom.get("rings", [])
                
                if clean_name and rings:
                    all_lons = [pt[0] for ring in rings for pt in ring if len(pt) >= 2]
                    all_lats = [pt[1] for ring in rings for pt in ring if len(pt) >= 2]
                    if all_lons and all_lats:
                        subdivisions.append({
                            "name": clean_name,
                            "rings": rings,
                            "bbox": (min(all_lats), max(all_lats), min(all_lons), max(all_lons))
                        })
                        
            if not data.get("exceededTransferLimit", False):
                break
                
            offset += limit
        except Exception as e:
            print(f"⚠️ Warning: Failed to pre-fetch subdivisions batch: {e}")
            break
            
    print(f"✅ Loaded {len(subdivisions)} subdivision polygons for spatial matching.\n")
    return subdivisions

def transform_snohomish_condos():
    print("🚀 Starting Snohomish County Transformer...")
    
    if not os.path.exists(RAW_PATH):
        print(f"❌ Raw file not found: {RAW_PATH}")
        return
        
    with open(RAW_PATH, 'r') as f:
        raw_data = json.load(f)
        
    print(f"Loaded {len(raw_data)} raw condo units.")
    
    # 1. Group the units by their 6-digit base (merges phases/buildings)
    complexes = {}
    for row in raw_data:
        parcel = str(row.get("PARCEL_ID", "")).strip().zfill(14)
        if len(parcel) != 14:
            continue
            
        major = parcel[:6]
        
        if major not in complexes:
            complexes[major] = {
                "major": major,
                "sample_pin": parcel,
                "units": []
            }
        complexes[major]["units"].append(row)
            
    # 2. Filter for > 8 units
    filtered_complexes = {k: v for k, v in complexes.items() if len(v["units"]) > 8}
    print(f"Found {len(filtered_complexes)} merged complexes with >8 units.")
    
    # 3. Pre-fetch subdivisions polygon layer into memory
    subdivision_polygons = fetch_all_subdivisions()
    
    # 4. Batch query the Parcel GIS API for precise building coordinates
    parcels_url = "https://services6.arcgis.com/z6WYi9VRHfgwgtyW/arcgis/rest/services/Parcels/FeatureServer/0/query"
    final_condos = []
    
    pins_to_query = [c["sample_pin"] for c in filtered_complexes.values()]
    batch_size = 50 
    
    print(f"Fetching map coordinates in batch...")
    coords_map = {}
    
    for i in range(0, len(pins_to_query), batch_size):
        batch_pins = pins_to_query[i:i+batch_size]
        pin_string = ",".join([f"'{p}'" for p in batch_pins])
        
        params = {
            "where": f"PARCEL_ID IN ({pin_string})",
            "outFields": "PARCEL_ID", 
            "outSR": "4326",
            "f": "json",
            "returnGeometry": "true"
        }
        
        try:
            res = requests.get(parcels_url, params=params, timeout=10)
            res.raise_for_status()
            data = res.json()
            
            for feature in data.get("features", []):
                pid = feature.get("attributes", {}).get("PARCEL_ID", "")
                geom = feature.get("geometry", {})
                lat, lon = get_polygon_center(geom)
                coords_map[pid] = (lat, lon)
        except Exception as e:
            print(f"⚠️ Parcel batch query failed: {e}")
            
        time.sleep(0.1)

    # 5. Fast In-Memory Spatial Matching
    print("Performing fast in-memory spatial matching for building names...")
    for pin in pins_to_query:
        major = pin[:6]
        if major in filtered_complexes:
            c_data = filtered_complexes[major]
            sample_unit = c_data["units"][0]
            lat, lon = coords_map.get(pin, (None, None))
            
            building_name = None
            if lat and lon:
                for sub in subdivision_polygons:
                    min_lat, max_lat, min_lon, max_lon = sub["bbox"]
                    if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
                        if point_in_polygon(lat, lon, sub["rings"]):
                            building_name = sub["name"]
                            break
            
            if not building_name:
                addr_str = clean_address(sample_unit)
                building_name = f"{addr_str} Condominiums" if addr_str else "Unknown Condominiums"
                
            final_condos.append({
                "building_id": f"sno_condo_{major}",
                "name": building_name,
                "address": clean_address(sample_unit),
                "city": str(sample_unit.get("SITUSCITY", "Unknown")).title(),
                "state": "WA",
                "latitude": lat,
                "longitude": lon,
                "total_units": len(c_data["units"]),
                "stories": None,
                "has_elevator": None
            })

    print(f"\nSuccessfully enriched and finalized {len(final_condos)} Snohomish complexes.")
    
    with open(OUT_PATH, 'w') as f:
        json.dump(final_condos, f, indent=2)
        
    print(f"💾 Saved processed data to {OUT_PATH}\n")

if __name__ == "__main__":
    transform_snohomish_condos()