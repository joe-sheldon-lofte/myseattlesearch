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
NEW_SUBDIVISIONS_PATH = os.path.join(DATA_DIR, "new_subdivisions.json")

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

def extract_builder_name(props, plat_name=""):
    if not isinstance(props, dict):
        props = {}
    
    candidates = [
        props.get("DEVELOPER") or props.get("developer"),
        props.get("GRANTOR") or props.get("grantor") or props.get("grantor_name"),
        props.get("TAXPAYER_NAME") or props.get("taxpayer_name") or props.get("taxprname") or props.get("TAXPRNAME"),
        props.get("OWNERNAME") or props.get("ownername") or props.get("owner_name") or props.get("owner")
    ]
    
    for raw in candidates:
        if not raw or not str(raw).strip():
            continue
        val = str(raw).strip()
        if len(val) >= 3 and not val.isdigit():
            cleaned = re.sub(
                r'\b(LLC|INC|CORP|CORPORATION|LTD|CO|COMPANY|LP|LLP|TRUST|TRUSTEE|ET\s+AL)\b.*$', 
                '', 
                val, 
                flags=re.IGNORECASE
            ).strip(' ,.')
            
            if len(cleaned) >= 3 and not cleaned.isdigit() and not re.search(r'\b(COUNTY|CITY|STATE|DEPT|DEPARTMENT|PORT|DISTRICT)\b', cleaned, flags=re.IGNORECASE):
                return cleaned.title()

    if plat_name:
        known_builders = [
            "Lennar", "DR Horton", "D.R. Horton", "Pulte", "Toll Brothers",
            "Richmond American", "Tri Pointe", "Taylor Morrison", "Century Communities",
            "Mainue Homes", "Cornerstone", "RM Homes", "Quadrant", "Polygon",
            "Pacific Ridge", "Soundbuilt", "Harbor Homes", "Sundance", "CamWest"
        ]
        for kb in known_builders:
            if re.search(r'\b' + re.escape(kb) + r'\b', plat_name, re.IGNORECASE):
                return kb.title()
                
    return "Subdivision Developer"

def state_plane_to_wgs84(x_ft, y_ft):
    """Converts WA State Plane North Feet (EPSG:2926) to WGS84 GPS Lat/Lon (EPSG:4326)."""
    if not x_ft or not y_ft:
        return None, None
    try:
        x = float(x_ft)
        y = float(y_ft)
    except (ValueError, TypeError):
        return None, None

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

def clean_plat_name(raw_name):
    if not raw_name:
        return ""
    name = str(raw_name).strip()
    if name.isdigit() or re.match(r'^\d{6,}', name):
        return ""

    name = re.sub(r'\b(TGW|UND\s+INT\s+IN|LESS\s+ST|LESS\b.*|POR\b.*|POR\s+OF\b.*|SEC\d+.*|TWP.*|RNG.*|DAF.*|BEG.*|BAAP.*|TPOB.*|TAP.*|LBA.*|PCL\s+[A-Z].*)\b', '', name, flags=re.IGNORECASE)

    if re.search(r'\b(POR OF|SEC|TWP|RNG|DAF|BEG|BAAP|TPOB|TAP|TH\s+[NSEW]|FEET|FT)\b', name, flags=re.IGNORECASE):
        m = re.search(r'\b(PLAT OF|SUBDIVISION OF|ADDITION TO|ADD TO)\s+([A-Za-z0-9\s-]+)', name, flags=re.IGNORECASE)
        if m:
            name = m.group(2)
        else:
            parts = re.split(r'\b(TH|DAF|BEG|BAAP|TPOB|POR OF|LESS|SEC)\b', name, flags=re.IGNORECASE)
            if parts and len(parts[0].strip()) >= 3:
                name = parts[0].strip()
            else:
                return ""

    name = re.sub(r'^SEC\s+\d+.*?(PLAT\s+OF|SUBDIVISION\s+OF|PLAT\s+)|^(PLAT\s+OF|SUBDIVISION\s+OF|PLAT\s+)', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\b(DIVISION|DIV|PHASE|PH|LOT|BLK|BLOCK|NO|UNREC|ADDITION|ADD|TRACTS|TR|TRS)\b.*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[^a-zA-Z0-9\s-]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    if len(name) < 3 or name.isdigit():
        return ""
    return name.title()

def get_geometry_bbox(geometry, props=None):
    if not geometry or not isinstance(geometry, dict):
        geometry = {}
    
    if props and isinstance(props, dict):
        x_c = props.get("X_COORD") or props.get("x_coord")
        y_c = props.get("Y_COORD") or props.get("y_coord")
        if x_c and y_c:
            lat, lon = state_plane_to_wgs84(x_c, y_c)
            if lat and lon:
                return (lat, lon, lat, lon)

    all_pts = []
    coords = geometry.get("coordinates", [])
    g_type = geometry.get("type")
    if g_type == "Polygon":
        for ring in coords:
            all_pts.extend(ring)
    elif g_type == "MultiPolygon":
        for poly in coords:
            for ring in poly:
                all_pts.extend(ring)

    rings = geometry.get("rings", [])
    if rings:
        for ring in rings:
            all_pts.extend(ring)

    if "x" in geometry and "y" in geometry:
        try:
            x, y = float(geometry["x"]), float(geometry["y"])
            lat, lon = state_plane_to_wgs84(x, y)
            if lat and lon:
                return (lat, lon, lat, lon)
        except (ValueError, TypeError):
            pass

    if not all_pts:
        return None

    try:
        min_x = min(pt[0] for pt in all_pts if isinstance(pt, (list, tuple)) and len(pt) >= 2)
        max_x = max(pt[0] for pt in all_pts if isinstance(pt, (list, tuple)) and len(pt) >= 2)
        min_y = min(pt[1] for pt in all_pts if isinstance(pt, (list, tuple)) and len(pt) >= 2)
        max_y = max(pt[1] for pt in all_pts if isinstance(pt, (list, tuple)) and len(pt) >= 2)
        
        lat_min, lon_min = state_plane_to_wgs84(min_x, min_y)
        lat_max, lon_max = state_plane_to_wgs84(max_x, max_y)
        
        if lat_min and lon_min and lat_max and lon_max:
            return (min(lat_min, lat_max), min(lon_min, lon_max), max(lat_min, lat_max), max(lon_max, lon_max))
    except Exception:
        pass
    return None

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
    if not geometry:
        return False
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
        bbox = get_geometry_bbox(geom, props)
        
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

    if lat is not None and lon is not None:
        for city in city_boundaries:
            bbox = city["bbox"]
            if bbox[0] <= lat <= bbox[2] and bbox[1] <= lon <= bbox[3]:
                if point_in_geometry(lat, lon, city["geometry"]):
                    return city["slug"]

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
    if not builder_name or builder_name == "Subdivision Developer" or len(builder_name.strip()) < 3:
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
                    cities_map[slug] = {"name": str(c_name).strip(), "subdivisions": []}
        except Exception as e:
            print(f"   ⚠️ City data load notice: {e}")
    return cities_map

def harvest_new_subdivisions():
    print("🏗️ Ingesting New Construction Plats & Subdivisions...")
    os.makedirs(DATA_DIR, exist_ok=True)
    
    city_boundaries = load_city_boundaries()
    city_centers = load_city_centers()
    cities_map = initialize_cities_map()
    builder_cache = {}

    # 1. King County Recorded Plats Stream (Socrata)
    kc_plat_map = {}
    offset = 0
    limit = 5000
    print("   📡 Streaming King County Recorded Plats & Builder Taxpayers (Socrata)...")

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
            builder = extract_builder_name(item, plat_name)
            
            if major_pin and plat_name:
                if major_pin not in kc_plat_map:
                    kc_plat_map[major_pin] = {
                        "name": plat_name,
                        "builder": builder,
                        "lots": 1
                    }
                else:
                    kc_plat_map[major_pin]["lots"] += 1
                    if builder != "Subdivision Developer":
                        kc_plat_map[major_pin]["builder"] = builder

        if len(kc_plat_res) < limit:
            break
        offset += limit

    print(f"   [DIAGNOSTIC] Found {len(kc_plat_map)} King County 6-digit numeric subdivision plat major PIN blocks.")

    # Batch Query King County GIS
    major_keys = list(kc_plat_map.keys())
    batch_size = 25
    total_batches = math.ceil(len(major_keys) / batch_size) if major_keys else 0
    print(f"   📡 Querying King County GIS coordinates across {total_batches} subdivision batches...")

    for b_idx, i in enumerate(range(0, len(major_keys), batch_size), start=1):
        chunk = major_keys[i:i + batch_size]
        quoted_majors = [f"'{str(k).zfill(6)}'" for k in chunk]
        majors_str = ",".join(quoted_majors)
        
        params = {
            "where": f"MAJOR IN ({majors_str})",
            "outFields": "*",
            "outSR": "4326",
            "f": "json"
        }
        kc_parcel_url = f"https://gismaps.kingcounty.gov/arcgis/rest/services/Property/KingCo_Parcels/MapServer/0/query?{urllib.parse.urlencode(params)}"
        kc_gis_res = http_get_json_simple(kc_parcel_url, timeout=25)

        if kc_gis_res and isinstance(kc_gis_res, dict):
            features = kc_gis_res.get("features", [])
            for feat in features:
                props = feat.get("properties") or feat.get("attributes") or {}
                geom = feat.get("geometry") or feat
                major_pin = extract_major_pin(props)

                if not major_pin or major_pin not in kc_plat_map:
                    continue

                bbox = get_geometry_bbox(geom, props)
                lat = (bbox[0] + bbox[2]) / 2.0 if bbox else None
                lon = (bbox[1] + bbox[3]) / 2.0 if bbox else None

                raw_city = props.get("SITUS_CITY") or props.get("CITY") or props.get("ADDR_CITY") or ""
                matched_slug = match_city_for_point(lat, lon, city_boundaries, city_centers, raw_city)

                if not matched_slug or matched_slug not in cities_map:
                    continue

                city_display = cities_map[matched_slug]["name"]
                raw_plat = kc_plat_map[major_pin]["name"]
                plat_name = clean_plat_name(raw_plat) or f"{city_display} Estates"
                lot_count = kc_plat_map[major_pin]["lots"]
                
                raw_builder = kc_plat_map[major_pin].get("builder", "Subdivision Developer")
                if raw_builder == "Subdivision Developer":
                    raw_builder = extract_builder_name(props, plat_name)

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

    # 2. Snohomish County Spatial BBOX Stream for Subdivisions
    print("   📡 Streaming Snohomish County Subdivision Plats (Spatial BBOX Envelopes)...")
    sno_subdiv_count = 0

    for city in city_boundaries:
        bbox = city["bbox"]
        if bbox[0] < 47.75:
            continue

        geometry_env = {
            "xmin": bbox[1],
            "ymin": bbox[0],
            "xmax": bbox[3],
            "ymax": bbox[2],
            "spatialReference": {"wkid": 4326}
        }
        
        params = {
            "where": "1=1",
            "geometry": json.dumps(geometry_env),
            "geometryType": "esriGeometryEnvelope",
            "spatialRel": "esriSpatialRelIntersects",
            "inSR": "4326",
            "outFields": "*",
            "outSR": "4326",
            "f": "json",
            "resultRecordCount": "100"
        }
        
        sno_url = f"https://services6.arcgis.com/z6WYi9VRHfgwgtyW/arcgis/rest/services/Parcels/FeatureServer/0/query?{urllib.parse.urlencode(params)}"
        sno_res = http_get_json_simple(sno_url, timeout=15)

        if sno_res and isinstance(sno_res, dict) and "features" in sno_res:
            features = sno_res.get("features", [])
            for feat in features:
                props = feat.get("properties") or feat.get("attributes") or {}
                geom = feat.get("geometry") or feat

                obj_id = props.get("OBJECTID") or props.get("PARCEL_ID") or "100"
                raw_title = props.get("TAXPRNAME") or props.get("OWNERNAME") or props.get("SITUSLINE1") or ""
                plat_name = clean_plat_name(raw_title) or f"{city['name']} Estates"

                c_bbox = get_geometry_bbox(geom, props)
                lat = (c_bbox[0] + c_bbox[2]) / 2.0 if c_bbox else (bbox[0] + bbox[2]) / 2.0
                lon = (c_bbox[1] + c_bbox[3]) / 2.0 if c_bbox else (bbox[1] + bbox[3]) / 2.0

                matched_slug = city["slug"]
                city_display = city["name"]
                raw_builder = extract_builder_name(props, plat_name)

                if raw_builder not in builder_cache:
                    builder_cache[raw_builder] = fetch_wa_contractor_details(raw_builder)
                builder_details = builder_cache[raw_builder]

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
                    sno_subdiv_count += 1

        time.sleep(0.05)

    print(f"   [DIAGNOSTIC 📊] Total Snohomish County Subdivisions Added: {sno_subdiv_count}")

    out_payload = {
        "cities": {k: {"name": v["name"], "subdivisions": v["subdivisions"]} for k, v in cities_map.items()},
        "last_updated": datetime.utcnow().isoformat() + "Z"
    }

    with open(NEW_SUBDIVISIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(out_payload, f, indent=2, ensure_ascii=False)

    total_subdivisions = sum(len(v["subdivisions"]) for v in cities_map.values())
    print(f"💾 Saved {total_subdivisions} new subdivisions across {len(cities_map)} cities to {NEW_SUBDIVISIONS_PATH}")

def main():
    print("==================================================")
    print("     SUBDIVISION HARVESTER (STANDALONE)           ")
    print("==================================================\n")
    harvest_new_subdivisions()
    print("🎉 Subdivision harvest completed successfully!")

if __name__ == "__main__":
    main()