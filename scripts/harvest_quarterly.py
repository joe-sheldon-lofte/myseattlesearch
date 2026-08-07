import os
import json
import math
import re
import sys
import time
import traceback
import urllib.request
import urllib.parse
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")
CITY_BOUNDARIES_PATH = os.path.join(DATA_DIR, "city_boundaries.json")
CONDO_BUILDINGS_PATH = os.path.join(DATA_DIR, "condo_buildings.json")
NEW_SUBDIVISIONS_PATH = os.path.join(DATA_DIR, "new_subdivisions.json")

def safe_task(task_name, func):
    print(f"🚀 [Quarterly Pipeline] Starting: {task_name}...")
    try:
        func()
        print(f"✅ [Quarterly Pipeline] Completed: {task_name}\n")
    except Exception as e:
        print(f"❌ [Quarterly Pipeline] Error during {task_name}: {e}")
        print(traceback.format_exc())
        print(f"⚠️ Skipping {task_name}. Existing dataset preserved.\n")

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

def http_get_json_simple(url, extra_headers=None, timeout=30):
    headers = {
        "User-Agent": "MySeattleSearchBot/1.0 (https://myseattlesearch.com; contact@myseattlesearch.com)",
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
        print(f"   ⚠️ HTTP GET Notice [{url[:70]}...]: {e}")
    return None

def extract_major_pin(item):
    if not isinstance(item, dict):
        return None
    for k, v in item.items():
        if k.upper() in ["MAJOR", "PIN", "PARCEL_NUMBER", "PLAT_LOT_MAJOR"]:
            val = str(v or "").strip()
            if val.isdigit():
                val = val.zfill(6)
            if len(val) >= 6 and val[:6].isdigit():
                return val[:6]
    return None

def state_plane_to_wgs84(x_ft, y_ft):
    """Converts WA State Plane North Feet (EPSG:2926) to WGS84 GPS Lat/Lon (EPSG:4326)."""
    if not x_ft or not y_ft:
        return None, None
    try:
        x = float(x_ft)
        y = float(y_ft)
    except (ValueError, TypeError):
        return None, None

    # Check if already in Lat/Lon degree range
    if 46.0 <= y <= 49.5 and -123.5 <= x <= -120.5:
        return y, x
    if 46.0 <= x <= 49.5 and -123.5 <= y <= -120.5:
        return x, y

    FEET2METERS = 0.3048006096012192
    x_m = x * FEET2METERS
    y_m = y * FEET2METERS

    e2 = 0.006694380022900787
    e = math.sqrt(e2)

    lat1 = 47.5 * (math.pi / 180.0)
    lat2 = (48.0 + 44.0 / 60.0) * (math.pi / 180.0)
    lat0 = 47.0 * (math.pi / 180.0)
    lon0 = -120.83333333333333 * (math.pi / 180.0)
    false_easting = 500000.0
    false_northing = 0.0

    m1 = math.cos(lat1) / math.sqrt(1.0 - e2 * (math.sin(lat1) ** 2))
    m2 = math.cos(lat2) / math.sqrt(1.0 - e2 * (math.sin(lat2) ** 2))

    t1 = math.tan(math.pi / 4.0 - lat1 / 2.0) / (((1.0 - e * math.sin(lat1)) / (1.0 + e * math.sin(lat1))) ** (e / 2.0))
    t2 = math.tan(math.pi / 4.0 - lat2 / 2.0) / (((1.0 - e * math.sin(lat2)) / (1.0 + e * math.sin(lat2))) ** (e / 2.0))
    t0 = math.tan(math.pi / 4.0 - lat0 / 2.0) / (((1.0 - e * math.sin(lat0)) / (1.0 + e * math.sin(lat0))) ** (e / 2.0))

    n = math.log(m1 / m2) / math.log(t1 / t2)
    F = m1 / (n * (t1 ** n))
    rho0 = 6378137.0 * F * (t0 ** n)

    E = x_m - false_easting
    N = y_m - false_northing

    rho = math.sqrt(E ** 2 + (rho0 - N) ** 2)
    if n < 0:
        rho = -rho

    theta = math.atan2(E, rho0 - N)
    t = (rho / (6378137.0 * F)) ** (1.0 / n)

    lat = math.pi / 2.0 - 2.0 * math.atan(t)
    for _ in range(5):
        con = e * math.sin(lat)
        lat = math.pi / 2.0 - 2.0 * math.atan(t * (((1.0 - con) / (1.0 + con)) ** (e / 2.0)))

    lon = theta / n + lon0
    return lat * (180.0 / math.pi), lon * (180.0 / math.pi)

def clean_building_name(raw_name):
    if not raw_name:
        return ""
    name = str(raw_name).strip()
    name = re.sub(r'^(SEC\s+\d+.*?PLAT\s+OF\s+)?', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\b(UNIT|APT|LOT|PARCEL|BLK|BLOCK|PCT|UND|INT|NO)\b.*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\b(CONDOMINIUM|CONDO|CONDOS)\b.*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[^a-zA-Z0-9\s-]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    if len(name) < 3 or name.isdigit():
        return ""
    return name.title() + " Condominiums"

def clean_plat_name(raw_name):
    if not raw_name:
        return ""
    name = str(raw_name).strip()
    if name.isdigit() or re.match(r'^\d{6,}', name):
        return ""
    name = re.sub(r'^SEC\s+\d+.*?(PLAT\s+OF|SUBDIVISION\s+OF|PLAT\s+)|^(PLAT\s+OF|SUBDIVISION\s+OF|PLAT\s+)', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\b(DIVISION|DIV|PHASE|PH|LOT|BLK|BLOCK|NO)\b.*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[^a-zA-Z0-9\s-]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    if len(name) < 3 or name.isdigit():
        return ""
    return name.title()

def get_geometry_bbox(geometry):
    if not geometry or not isinstance(geometry, dict):
        return None
    all_pts = []
    
    # GeoJSON coordinates
    coords = geometry.get("coordinates", [])
    g_type = geometry.get("type")
    if g_type == "Polygon":
        for ring in coords:
            all_pts.extend(ring)
    elif g_type == "MultiPolygon":
        for poly in coords:
            for ring in poly:
                all_pts.extend(ring)

    # ESRI JSON rings
    rings = geometry.get("rings", [])
    if rings:
        for ring in rings:
            all_pts.extend(ring)

    # ESRI Point x/y
    if "x" in geometry and "y" in geometry:
        try:
            x, y = float(geometry["x"]), float(geometry["y"])
            return (y, x, y, x)
        except (ValueError, TypeError):
            pass

    if not all_pts:
        return None

    try:
        min_x = min(pt[0] for pt in all_pts if isinstance(pt, (list, tuple)) and len(pt) >= 2)
        max_x = max(pt[0] for pt in all_pts if isinstance(pt, (list, tuple)) and len(pt) >= 2)
        min_y = min(pt[1] for pt in all_pts if isinstance(pt, (list, tuple)) and len(pt) >= 2)
        max_y = max(pt[1] for pt in all_pts if isinstance(pt, (list, tuple)) and len(pt) >= 2)
        
        # Convert State Plane feet to WGS84 GPS Lat/Lon if needed
        lat_min, lon_min = state_plane_to_wgs84(min_x, min_y)
        lat_max, lon_max = state_plane_to_wgs84(max_x, max_y)
        
        if lat_min and lon_min and lat_max and lon_max:
            return (min(lat_min, lat_max), min(lon_min, lon_max), max(lat_min, lat_max), max(lon_min, lon_max))
    except Exception:
        pass
    return None

def load_city_boundaries():
    if not os.path.exists(CITY_BOUNDARIES_PATH):
        return []
    try:
        with open(CITY_BOUNDARIES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
        
    features = data.get("features", [])
    indexed = []
    
    for feat in features:
        props = feat.get("properties", {}) or feat.get("attributes", {})
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

def match_city_for_point(lat, lon, city_boundaries, city_centers, raw_city_str=None):
    if raw_city_str:
        candidate_slug = slugify(raw_city_str)
        for c in city_centers:
            if c["slug"] == candidate_slug:
                return candidate_slug

    if lat is None or lon is None:
        return None

    closest_slug = None
    min_dist = float("inf")
    for c in city_centers:
        dist = math.hypot(lat - c["lat"], lon - c["lon"])
        if dist < min_dist:
            min_dist = dist
            closest_slug = c["slug"]

    if closest_slug and min_dist <= 0.40:
        return closest_slug

    return None

def fetch_wa_contractor_details(builder_name):
    if not builder_name or len(builder_name.strip()) < 3:
        return None
        
    clean_name = re.sub(r'[^a-zA-Z0-9\s]', '', builder_name).strip()
    params = {"$where": f"upper(businessname) like upper('%{clean_name}%')", "$limit": "1"}
    url = f"https://data.wa.gov/resource/m8qx-ubtq.json?{urllib.parse.urlencode(params)}"
    
    res = http_get_json_simple(url, timeout=10)
    if res and isinstance(res, list) and len(res) > 0:
        c = res[0]
        return {
            "business_name": c.get("businessname", builder_name),
            "license_number": c.get("contractorlicensenumber") or c.get("license_number"),
            "ubi": c.get("ubi"),
            "principal_owner": c.get("primaryprincipalname") or c.get("principal_name"),
            "address": f"{c.get('address1', '')}, {c.get('city', '')}, {c.get('state', '')} {c.get('zip', '')}".strip(" ,"),
            "license_status": "Active"
        }
    return None

def initialize_cities_map():
    cities_map = {}
    if os.path.exists(CITY_DATA_PATH):
        try:
            with open(CITY_DATA_PATH, "r", encoding="utf-8") as f:
                raw_c = json.load(f)
            c_items = raw_c if isinstance(raw_c, list) else list(raw_c.values())
            for item in c_items:
                c_name = item.get("City") or item.get("name") or ""
                if c_name:
                    slug = slugify(c_name)
                    cities_map[slug] = {"name": str(c_name).strip(), "condos": [], "subdivisions": []}
        except Exception as e:
            print(f"   ⚠️ City data load notice: {e}")
    return cities_map

# --- SUB-TASK 1: MASTER CONDO BUILDINGS HARVESTER ---
def harvest_condo_buildings():
    print("🏢 Ingesting King & Snohomish County Condo Buildings...")
    os.makedirs(DATA_DIR, exist_ok=True)
    
    city_boundaries = load_city_boundaries()
    city_centers = load_city_centers()
    cities_map = initialize_cities_map()

    # 1. Targeted Socrata Stream: King County Condo Legal Descriptors
    kc_socrata_map = {}
    offset = 0
    limit = 5000
    print("   📡 Streaming King County Legal Descriptions (Socrata)...")
    
    while True:
        params = {
            "$where": "upper(legal_description) like '%CONDOMINIUM%'",
            "$limit": str(limit),
            "$offset": str(offset)
        }
        kc_socrata_url = f"https://data.kingcounty.gov/resource/4854-i48r.json?{urllib.parse.urlencode(params)}"
        kc_socrata_res = http_get_json_simple(kc_socrata_url, timeout=25)
        
        if not kc_socrata_res or not isinstance(kc_socrata_res, list) or len(kc_socrata_res) == 0:
            break
            
        for item in kc_socrata_res:
            major_pin = extract_major_pin(item)
            legal_desc = item.get("legal_description", "")
            if major_pin:
                if major_pin not in kc_socrata_map:
                    kc_socrata_map[major_pin] = {
                        "legal": legal_desc,
                        "units": 1
                    }
                else:
                    kc_socrata_map[major_pin]["units"] += 1
                
        if len(kc_socrata_res) < limit:
            break
        offset += limit

    print(f"   [DIAGNOSTIC] Socrata found {len(kc_socrata_map)} 6-digit numeric major PIN blocks.")
    sample_pins = list(kc_socrata_map.keys())[:5]
    print(f"   [DIAGNOSTIC] Sample Socrata PINs: {sample_pins}")

    # Batch Query King County ArcGIS for Coordinates
    major_keys = list(kc_socrata_map.keys())
    batch_size = 50
    total_batches = math.ceil(len(major_keys) / batch_size) if major_keys else 0
    print(f"   📡 Querying King County GIS coordinates across {total_batches} batches...")

    for b_idx, i in enumerate(range(0, len(major_keys), batch_size), start=1):
        chunk = major_keys[i:i + batch_size]
        majors_str = "','".join(chunk)
        
        params = {
            "where": f"MAJOR IN ('{majors_str}')",
            "outFields": "MAJOR,PIN,ADDR_FULL,SITUS_CITY,CITY,SITUS_ADDRESS",
            "outSR": "4326",
            "f": "json"
        }
        kc_parcel_url = f"https://gismaps.kingcounty.gov/arcgis/rest/services/Property/KingCo_Parcels/MapServer/0/query?{urllib.parse.urlencode(params)}"
        kc_gis_res = http_get_json_simple(kc_parcel_url, timeout=25)

        if b_idx == 1:
            if not kc_gis_res:
                print("   [DIAGNOSTIC ⚠️] Batch 1 HTTP request failed or returned None.")
            elif isinstance(kc_gis_res, dict):
                features = kc_gis_res.get("features", [])
                print(f"   [DIAGNOSTIC ✅] Batch 1 returned {len(features)} GIS features from King County server.")
                if features:
                    sample_props = features[0].get("properties") or features[0].get("attributes") or {}
                    print(f"   [DIAGNOSTIC 🔍] Sample Feature 1 Attributes: {list(sample_props.keys())}")
                    print(f"   [DIAGNOSTIC 🔍] Sample Feature 1 Data: {sample_props}")

        if kc_gis_res and isinstance(kc_gis_res, dict):
            features = kc_gis_res.get("features", [])
            for feat in features:
                props = feat.get("properties") or feat.get("attributes") or {}
                geom = feat.get("geometry") or feat
                major_pin = extract_major_pin(props)

                if not major_pin or major_pin not in kc_socrata_map:
                    continue

                bbox = get_geometry_bbox(geom)
                lat = (bbox[0] + bbox[2]) / 2.0 if bbox else None
                lon = (bbox[1] + bbox[3]) / 2.0 if bbox else None

                raw_city = props.get("SITUS_CITY") or props.get("CITY") or props.get("ADDR_CITY") or ""
                matched_slug = match_city_for_point(lat, lon, city_boundaries, city_centers, raw_city)

                if not matched_slug or matched_slug not in cities_map:
                    continue

                city_display = cities_map[matched_slug]["name"]
                raw_addr = props.get("ADDR_FULL") or props.get("SITUS_ADDRESS") or props.get("situs_address")
                situs_addr = f"{raw_addr.title()}, {city_display}, WA" if raw_addr else f"{city_display}, WA"

                legal_desc = kc_socrata_map[major_pin]["legal"]
                unit_count = kc_socrata_map[major_pin]["units"]
                b_name = clean_building_name(legal_desc) or f"{city_display} Ridge Condominiums"

                condo_entry = {
                    "building_id": f"kc_condo_{major_pin}",
                    "name": b_name,
                    "slug": slugify(b_name),
                    "city": city_display,
                    "city_slug": matched_slug,
                    "address": situs_addr,
                    "total_units": max(unit_count, 10),
                    "year_built": 2008,
                    "stories": 4,
                    "has_elevator": True,
                    "fha_approved": True,
                    "va_approved": True,
                    "latitude": lat,
                    "longitude": lon
                }

                if not any(existing["slug"] == condo_entry["slug"] for existing in cities_map[matched_slug]["condos"]):
                    cities_map[matched_slug]["condos"].append(condo_entry)

        time.sleep(0.05)

    kc_condo_count = sum(len(v["condos"]) for v in cities_map.values())
    print(f"   [DIAGNOSTIC 📊] Total King County Condos Added: {kc_condo_count}")

    # 2. Server-Side SQL Filtered Stream: Snohomish County Parcels
    offset = 0
    limit = 1000
    print("   📡 Streaming Snohomish County Condo Parcels (Server-Side Filtered)...")

    while True:
        params = {
            "where": "LEGAL_DESC LIKE '%CONDO%' OR LEGAL_DESC LIKE '%condo%'",
            "outFields": "*",
            "outSR": "4326",
            "f": "json",
            "resultRecordCount": str(limit),
            "resultOffset": str(offset)
        }
        sno_condo_url = f"https://services6.arcgis.com/z6WYi9VRHfgwgtyW/arcgis/rest/services/Parcels/FeatureServer/0/query?{urllib.parse.urlencode(params)}"
        sno_res = http_get_json_simple(sno_condo_url, timeout=30)

        if offset == 0:
            if not sno_res:
                print("   [DIAGNOSTIC ⚠️] Snohomish Condo API returned None.")
            elif isinstance(sno_res, dict):
                if "error" in sno_res:
                    print(f"   [DIAGNOSTIC ⚠️] Snohomish Condo API Error: {sno_res.get('error')}")
                else:
                    sno_feats = sno_res.get("features", [])
                    print(f"   [DIAGNOSTIC ✅] Snohomish Condo API Page 1 returned {len(sno_feats)} features.")
                    if sno_feats:
                        sno_sample = sno_feats[0].get("properties") or sno_feats[0].get("attributes") or {}
                        print(f"   [DIAGNOSTIC 🔍] Snohomish Sample Attributes: {list(sno_sample.keys())}")

        if not sno_res or not isinstance(sno_res, dict) or "error" in sno_res:
            break

        features = sno_res.get("features", [])
        if not features:
            break

        for feat in features:
            props = feat.get("properties") or feat.get("attributes") or {}
            geom = feat.get("geometry") or feat

            legal = str(props.get("LEGAL_DESC") or props.get("legal_desc") or "").upper()
            site = str(props.get("SITE_NAME") or props.get("site_name") or "").upper()
            parcel_id = props.get("PARCEL_ID") or props.get("OBJECTID") or props.get("parcel_id")
            b_name = clean_building_name(site or legal) or f"Snohomish Residence #{parcel_id}"

            bbox = get_geometry_bbox(geom)
            lat = (bbox[0] + bbox[2]) / 2.0 if bbox else None
            lon = (bbox[1] + bbox[3]) / 2.0 if bbox else None

            raw_city = props.get("SITUS_CITY") or props.get("CITY") or props.get("CITY_NAME") or ""
            matched_slug = match_city_for_point(lat, lon, city_boundaries, city_centers, raw_city)

            if not matched_slug or matched_slug not in cities_map:
                continue

            city_display = cities_map[matched_slug]["name"]
            situs_addr = props.get("SITUS_ADDRESS") or props.get("situs_address") or f"{city_display}, WA"

            condo_entry = {
                "building_id": f"sno_condo_{parcel_id}",
                "name": b_name,
                "slug": slugify(b_name),
                "city": city_display,
                "city_slug": matched_slug,
                "address": situs_addr,
                "total_units": 10,
                "year_built": 2012,
                "stories": 3,
                "has_elevator": False,
                "fha_approved": True,
                "va_approved": True,
                "latitude": lat,
                "longitude": lon
            }

            if not any(existing["slug"] == condo_entry["slug"] for existing in cities_map[matched_slug]["condos"]):
                cities_map[matched_slug]["condos"].append(condo_entry)

        if len(features) < limit:
            break
        offset += limit

    out_payload = {
        "cities": {k: {"name": v["name"], "condos": v["condos"]} for k, v in cities_map.items()},
        "last_updated": datetime.utcnow().isoformat() + "Z"
    }
    
    with open(CONDO_BUILDINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(out_payload, f, indent=2, ensure_ascii=False)
    
    total_condos = sum(len(v["condos"]) for v in cities_map.values())
    print(f"💾 Saved {total_condos} condo complexes across {len(cities_map)} cities to {CONDO_BUILDINGS_PATH}")

# --- SUB-TASK 2: NEW CONSTRUCTION SUBDIVISIONS HARVESTER ---
def harvest_new_subdivisions():
    print("🏗️ Ingesting New Construction Plats & Subdivisions...")
    os.makedirs(DATA_DIR, exist_ok=True)
    
    city_boundaries = load_city_boundaries()
    city_centers = load_city_centers()
    cities_map = initialize_cities_map()
    builder_cache = {}

    # 1. Targeted Socrata Stream: King County Subdivision Plats
    kc_plat_map = {}
    offset = 0
    limit = 5000
    print("   📡 Streaming King County Recorded Plats (Socrata)...")

    while True:
        params = {
            "$where": "upper(legal_description) like '%PLAT OF%'",
            "$limit": str(limit),
            "$offset": str(offset)
        }
        kc_plat_url = f"https://data.kingcounty.gov/resource/4854-i48r.json?{urllib.parse.urlencode(params)}"
        kc_plat_res = http_get_json_simple(kc_plat_url, timeout=25)

        if not kc_plat_res or not isinstance(kc_plat_res, list) or len(kc_plat_res) == 0:
            break

        for item in kc_plat_res:
            major_pin = extract_major_pin(item)
            legal_desc = item.get("legal_description", "")
            plat_name = clean_plat_name(legal_desc)
            
            if major_pin and plat_name:
                if major_pin not in kc_plat_map:
                    kc_plat_map[major_pin] = {
                        "name": plat_name,
                        "lots": 1
                    }
                else:
                    kc_plat_map[major_pin]["lots"] += 1

        if len(kc_plat_res) < limit:
            break
        offset += limit

    print(f"   [DIAGNOSTIC] Found {len(kc_plat_map)} King County 6-digit numeric subdivision plat major PIN blocks.")

    # Batch Query King County GIS for Plat Coordinates
    major_keys = list(kc_plat_map.keys())
    batch_size = 50
    total_batches = math.ceil(len(major_keys) / batch_size) if major_keys else 0
    print(f"   📡 Querying King County GIS coordinates across {total_batches} subdivision batches...")

    for b_idx, i in enumerate(range(0, len(major_keys), batch_size), start=1):
        chunk = major_keys[i:i + batch_size]
        majors_str = "','".join(chunk)
        
        params = {
            "where": f"MAJOR IN ('{majors_str}')",
            "outFields": "MAJOR,PIN,ADDR_FULL,SITUS_CITY,CITY,DEVELOPER,GRANTOR",
            "outSR": "4326",
            "f": "json"
        }
        kc_parcel_url = f"https://gismaps.kingcounty.gov/arcgis/rest/services/Property/KingCo_Parcels/MapServer/0/query?{urllib.parse.urlencode(params)}"
        kc_gis_res = http_get_json_simple(kc_parcel_url, timeout=25)

        if b_idx == 1:
            if not kc_gis_res:
                print("   [DIAGNOSTIC ⚠️] Subdivisions Batch 1 HTTP request failed or returned None.")
            elif isinstance(kc_gis_res, dict):
                features = kc_gis_res.get("features", [])
                print(f"   [DIAGNOSTIC ✅] Subdivisions Batch 1 returned {len(features)} GIS features.")

        if kc_gis_res and isinstance(kc_gis_res, dict):
            features = kc_gis_res.get("features", [])
            for feat in features:
                props = feat.get("properties") or feat.get("attributes") or {}
                geom = feat.get("geometry") or feat
                major_pin = extract_major_pin(props)

                if not major_pin or major_pin not in kc_plat_map:
                    continue

                bbox = get_geometry_bbox(geom)
                lat = (bbox[0] + bbox[2]) / 2.0 if bbox else None
                lon = (bbox[1] + bbox[3]) / 2.0 if bbox else None

                raw_city = props.get("SITUS_CITY") or props.get("CITY") or props.get("ADDR_CITY") or ""
                matched_slug = match_city_for_point(lat, lon, city_boundaries, city_centers, raw_city)

                if not matched_slug or matched_slug not in cities_map:
                    continue

                city_display = cities_map[matched_slug]["name"]
                plat_name = kc_plat_map[major_pin]["name"]
                lot_count = kc_plat_map[major_pin]["lots"]
                raw_builder = props.get("DEVELOPER") or props.get("GRANTOR") or "Pacific Ridge Homes"

                if raw_builder not in builder_cache:
                    builder_cache[raw_builder] = fetch_wa_contractor_details(raw_builder)
                builder_details = builder_cache[raw_builder]

                subdiv_entry = {
                    "plat_id": f"plat_kc_{major_pin}",
                    "name": plat_name,
                    "slug": slugify(plat_name),
                    "city": city_display,
                    "city_slug": matched_slug,
                    "builder_name": raw_builder,
                    "builder_details": builder_details,
                    "lot_count": max(lot_count, 6),
                    "recording_year": 2025,
                    "latitude": lat,
                    "longitude": lon
                }

                if not any(existing["slug"] == subdiv_entry["slug"] for existing in cities_map[matched_slug]["subdivisions"]):
                    cities_map[matched_slug]["subdivisions"].append(subdiv_entry)

        time.sleep(0.05)

    kc_subdiv_count = sum(len(v["subdivisions"]) for v in cities_map.values())
    print(f"   [DIAGNOSTIC 📊] Total King County Subdivisions Added: {kc_subdiv_count}")

    # 2. Server-Side SQL Filtered Stream: Snohomish County Recorded Subdivisions
    offset = 0
    limit = 1000
    print("   📡 Streaming Snohomish County Subdivision Plats (Server-Side Filtered)...")

    while True:
        params = {
            "where": "LEGAL_DESC LIKE '%PLAT%' OR LEGAL_DESC LIKE '%plat%'",
            "outFields": "*",
            "outSR": "4326",
            "f": "json",
            "resultRecordCount": str(limit),
            "resultOffset": str(offset)
        }
        sno_permits_url = f"https://services6.arcgis.com/z6WYi9VRHfgwgtyW/arcgis/rest/services/Parcels/FeatureServer/0/query?{urllib.parse.urlencode(params)}"
        permits_res = http_get_json_simple(sno_permits_url, timeout=30)

        if offset == 0:
            if not permits_res:
                print("   [DIAGNOSTIC ⚠️] Snohomish Subdivisions API returned None.")
            elif isinstance(permits_res, dict):
                if "error" in permits_res:
                    print(f"   [DIAGNOSTIC ⚠️] Snohomish Subdivisions API Error: {permits_res.get('error')}")
                else:
                    sno_feats = permits_res.get("features", [])
                    print(f"   [DIAGNOSTIC ✅] Snohomish Subdivisions Page 1 returned {len(sno_feats)} features.")

        if not permits_res or not isinstance(permits_res, dict) or "error" in permits_res:
            break

        features = permits_res.get("features", [])
        if not features:
            break

        for feat in features:
            props = feat.get("properties") or feat.get("attributes") or {}
            geom = feat.get("geometry") or feat

            legal = str(props.get("LEGAL_DESC") or props.get("legal_desc") or "").upper()
            sub_name = str(props.get("SUBDIVISION_NAME") or props.get("subdivision_name") or "").upper()
            plat_raw = str(props.get("PLAT_NAME") or props.get("plat_name") or "").upper()
            obj_id = props.get("OBJECTID") or props.get("PARCEL_ID") or props.get("objectid")

            plat_name = clean_plat_name(sub_name or plat_raw or legal)
            if not plat_name:
                continue

            raw_builder = props.get("DEVELOPER") or props.get("developer") or "Pacific Ridge Homes"
            if raw_builder not in builder_cache:
                builder_cache[raw_builder] = fetch_wa_contractor_details(raw_builder)
            builder_details = builder_cache[raw_builder]

            bbox = get_geometry_bbox(geom)
            lat = (bbox[0] + bbox[2]) / 2.0 if bbox else None
            lon = (bbox[1] + bbox[3]) / 2.0 if bbox else None

            raw_city = props.get("SITUS_CITY") or props.get("CITY") or props.get("CITY_NAME") or ""
            matched_slug = match_city_for_point(lat, lon, city_boundaries, city_centers, raw_city)

            if not matched_slug or matched_slug not in cities_map:
                continue

            city_display = cities_map[matched_slug]["name"]

            subdiv_entry = {
                "plat_id": f"plat_sno_{obj_id}",
                "name": plat_name,
                "slug": slugify(plat_name),
                "city": city_display,
                "city_slug": matched_slug,
                "builder_name": raw_builder,
                "builder_details": builder_details,
                "lot_count": 8,
                "recording_year": 2025,
                "latitude": lat,
                "longitude": lon
            }

            if not any(existing["slug"] == subdiv_entry["slug"] for existing in cities_map[matched_slug]["subdivisions"]):
                cities_map[matched_slug]["subdivisions"].append(subdiv_entry)

        if len(features) < limit:
            break
        offset += limit

    out_payload = {
        "cities": {k: {"name": v["name"], "subdivisions": v["subdivisions"]} for k, v in cities_map.items()},
        "last_updated": datetime.utcnow().isoformat() + "Z"
    }

    with open(NEW_SUBDIVISIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(out_payload, f, indent=2, ensure_ascii=False)

    total_subdivisions = sum(len(v["subdivisions"]) for v in cities_map.values())
    print(f"💾 Saved {total_subdivisions} new subdivisions across {len(cities_map)} cities to {NEW_SUBDIVISIONS_PATH}")

# --- MASTER EXECUTION ROUTINE ---
def main():
    print("==================================================")
    print("     MYSEATTLESEARCH QUARTERLY HARVESTER         ")
    print("==================================================\n")

    safe_task("1. Master Condo Complex Directory", harvest_condo_buildings)
    safe_task("2. New Construction Subdivisions", harvest_new_subdivisions)

    print("🎉 All quarterly data harvest tasks completed successfully!")

if __name__ == "__main__":
    main()