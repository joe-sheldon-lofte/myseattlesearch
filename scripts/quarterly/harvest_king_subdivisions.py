import os
import json
import math
import re
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")
CITY_BOUNDARIES_PATH = os.path.join(DATA_DIR, "city_boundaries.json")
KING_SUBDIVISIONS_PATH = os.path.join(DATA_DIR, "king_subdivisions.json")

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

def extract_builder_name(props):
    """Extracts verified corporate builder/developer entities dynamically.
    Requires explicit corporate indicators and excludes individual human names."""
    if not isinstance(props, dict):
        props = {}

    candidates = [
        props.get("DEVELOPER") or props.get("developer"),
        props.get("BUILDER") or props.get("builder") or props.get("builder_name"),
        props.get("GRANTOR") or props.get("grantor") or props.get("grantor_name"),
        props.get("TAXPAYER_NAME") or props.get("taxpayer_name") or props.get("taxprname") or props.get("TAXPRNAME"),
        props.get("OWNERNAME") or props.get("ownername") or props.get("owner_name") or props.get("owner"),
        props.get("attn_line") or props.get("tax_payer_name")
    ]

    corp_markers = [
        r'\bLLC\b', r'\bINC\b', r'\bCORP\b', r'\bCORPORATION\b', r'\bLTD\b', r'\bCO\b', 
        r'\bCOMPANY\b', r'\bLP\b', r'\bLLP\b', r'\bHOMES\b', r'\bBUILDERS?\b', 
        r'\bPROPERTIES\b', r'\bCONST(RUCTION)?\b', r'\bDEVELOPMENT\b', r'\bHOLDINGS\b', 
        r'\bGROUP\b', r'\bVENTURES\b', r'\bHOUSING\b', r'\bPARTNERS\b', r'\bENTERPRISES\b', 
        r'\bREALTY\b', r'\bINVESTMENTS?\b', r'\bDESIGN\b', r'\bBUILDING\b', r'\bCRAFT\b'
    ]

    for raw in candidates:
        if not raw or not str(raw).strip():
            continue
        val = str(raw).strip()
        is_corporate = any(re.search(m, val, flags=re.IGNORECASE) for m in corp_markers)
        
        if is_corporate:
            cleaned = re.sub(
                r'\b(LLC|INC|CORP|CORPORATION|LTD|CO|COMPANY|LP|LLP|TRUST|TRUSTEE|ET\s+AL)\b.*$', 
                '', 
                val, 
                flags=re.IGNORECASE
            ).strip(' ,.')
            
            if len(cleaned) >= 3 and not cleaned.isdigit() and not re.search(r'\b(COUNTY|CITY|STATE|DEPT|DEPARTMENT|PORT|DISTRICT|CHURCH|SCHOOL|TRIBE)\b', cleaned, flags=re.IGNORECASE):
                return cleaned.title()

    return "Unable to Verify"

def fetch_kc_assessor_taxpayer(major_pin, cache):
    """Queries King County Socrata Assessor dataset by Major PIN to extract corporate builder/taxpayer LLCs."""
    if not major_pin:
        return "Unable to Verify"
    if major_pin in cache:
        return cache[major_pin]

    params = {
        "$where": f"major='{major_pin}'",
        "$limit": "5"
    }
    url = f"https://data.kingcounty.gov/resource/pv2w-3b3h.json?{urllib.parse.urlencode(params)}"
    res = http_get_json_simple(url, timeout=10)

    if res and isinstance(res, list):
        for item in res:
            extracted = extract_builder_name(item)
            if extracted != "Unable to Verify":
                cache[major_pin] = extracted
                return extracted

    cache[major_pin] = "Unable to Verify"
    return "Unable to Verify"

def clean_plat_name(raw_name):
    """Slices survey artifacts strictly at directional transition tokens."""
    if not raw_name:
        return ""
    name = str(raw_name).strip()
    if name.isdigit() or re.match(r'^\d{6,}', name):
        return ""

    cutoff_pattern = r'\b(TH|THENCE|TGW|TOGETHER\s+WITH|LESS|POR|PORTION|EXC|EXCEPT|SEC|SECTION|TWP|RNG|VOL|PG|AFN|PER\s+REC)\b.*$'
    name = re.sub(cutoff_pattern, '', name, flags=re.IGNORECASE).strip()

    name = re.sub(r'^(SEC\s+\d+.*?PLAT\s+OF\s+)?', '', name, flags=re.IGNORECASE)
    name = re.sub(r'^(PLAT\s+OF|SUBDIVISION\s+OF|PLAT\s+)', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\b(DIVISION|DIV|PHASE|PH|LOT|BLK|BLOCK|NO|UNREC|ADDITION|ADD|TRACTS|TR|TRS)\b.*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[^a-zA-Z0-9\s-]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()

    if len(name) < 3 or name.isdigit():
        return ""

    return name.title()

def state_plane_to_wgs84(x_ft, y_ft):
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
                "bbox": bbox
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

def harvest_king_subdivisions():
    print("🏗️ Ingesting King County New Construction Plats & Subdivisions...")
    os.makedirs(DATA_DIR, exist_ok=True)
    
    city_boundaries = load_city_boundaries()
    city_centers = load_city_centers()
    cities_map = {}
    assessor_cache = {}

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

    # Stream King County Recorded Plats via Socrata
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
            builder = extract_builder_name(item)
            
            if major_pin:
                if major_pin not in kc_plat_map:
                    kc_plat_map[major_pin] = {
                        "name": plat_name,
                        "builder": builder,
                        "lots": 1
                    }
                else:
                    kc_plat_map[major_pin]["lots"] += 1
                    if not kc_plat_map[major_pin]["name"] and plat_name:
                        kc_plat_map[major_pin]["name"] = plat_name
                    if builder != "Unable to Verify":
                        kc_plat_map[major_pin]["builder"] = builder

        if len(kc_plat_res) < limit:
            break
        offset += limit

    print(f"   [DIAGNOSTIC] Found {len(kc_plat_map)} King County major PIN blocks.")

    # Batch Query King County GIS MapServer
    major_keys = list(kc_plat_map.keys())
    batch_size = 25
    total_batches = math.ceil(len(major_keys) / batch_size) if major_keys else 0
    print(f"   📡 Querying King County GIS coordinates across {total_batches} batches...")

    for i in range(0, len(major_keys), batch_size):
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
                
                raw_builder = kc_plat_map[major_pin].get("builder", "Unable to Verify")
                if raw_builder == "Unable to Verify":
                    raw_builder = extract_builder_name(props)
                if raw_builder == "Unable to Verify":
                    raw_builder = fetch_kc_assessor_taxpayer(major_pin, assessor_cache)

                subdiv_entry = {
                    "plat_id": f"plat_kc_{major_pin}",
                    "name": plat_name,
                    "slug": slugify(plat_name),
                    "city": city_display,
                    "city_slug": matched_slug,
                    "builder_name": raw_builder,
                    "builder_details": None,
                    "lot_count": max(lot_count, 6),
                    "recording_year": datetime.now().year,
                    "latitude": lat,
                    "longitude": lon
                }

                if not any(existing["slug"] == subdiv_entry["slug"] for existing in cities_map[matched_slug]["subdivisions"]):
                    cities_map[matched_slug]["subdivisions"].append(subdiv_entry)

        time.sleep(0.05)

    out_payload = {
        "cities": {k: {"name": v["name"], "subdivisions": v["subdivisions"]} for k, v in cities_map.items() if v["subdivisions"]},
        "last_updated": datetime.utcnow().isoformat() + "Z"
    }

    with open(KING_SUBDIVISIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(out_payload, f, indent=2, ensure_ascii=False)

    total_subdivisions = sum(len(v["subdivisions"]) for v in cities_map.values())
    print(f"💾 Saved {total_subdivisions} King County subdivisions to {KING_SUBDIVISIONS_PATH}")

def main():
    harvest_king_subdivisions()

if __name__ == "__main__":
    main()