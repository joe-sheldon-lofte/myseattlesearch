# File: scripts/monthly/osm_amenities.py
import os
import json
import time
import subprocess
import requests
import urllib3
from datetime import datetime, timezone

# Suppress unverified HTTPS request warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Robust Repository Root Path Resolution
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(CURRENT_DIR) == "monthly":
    REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
elif os.path.basename(CURRENT_DIR) == "scripts":
    REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
else:
    REPO_ROOT = os.path.abspath(CURRENT_DIR)

DATA_DIR = os.path.join(REPO_ROOT, "data")
CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")
CITY_BOUNDARIES_PATH = os.path.join(DATA_DIR, "city_boundaries.json")
DEMOGRAPHICS_PATH = os.path.join(DATA_DIR, "city_demographics.json")
CRIME_STATS_PATH = os.path.join(DATA_DIR, "crime_stats.json")
TRANSIT_RADAR_PATH = os.path.join(DATA_DIR, "transit_radar_live.json")
OUT_PATH = os.path.join(DATA_DIR, "city_amenities.json")

# Verified OpenStreetMap Overpass Public Interpreters
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter"
]

USER_AGENT = "MySeattleSearch-MunicipalAmenities/3.0 (https://myseattlesearch.com; contact@myseattlesearch.com)"

HEADERS_OVERPASS = {
    "User-Agent": USER_AGENT,
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Accept": "application/json, */*"
}

# Empirical Benchmarks for 0-100 Normalization (Per 1,000 residents)
BENCHMARKS = {
    "bark": {"count": 25.0, "per_capita": 1.5},
    "park": {"count": 60.0, "per_capita": 3.0},
    "shore": {"count": 8.0, "per_capita": 0.5},
    "caffeine": {"count": 50.0, "per_capita": 2.5},
    "golf": {"count": 2.0, "per_capita": 0.15},
    "brew": {"count": 8.0, "per_capita": 0.5},
    "wine": {"count": 6.0, "per_capita": 0.3}
}

def slugify(text):
    if not text:
        return ""
    text = str(text).lower().strip()
    out = [ch if ch.isalnum() else '-' for ch in text]
    res = "".join(out)
    while '--' in res:
        res = res.replace('--', '-')
    return res.strip('-')

def point_in_poly(x, y, poly):
    """Ray casting point-in-polygon algorithm (x=lng, y=lat)."""
    n = len(poly)
    if n < 3:
        return False
    inside = False
    p1x, p1y = poly[0][0], poly[0][1]
    for i in range(1, n + 1):
        p2x, p2y = poly[i % n][0], poly[i % n][1]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside

def is_point_in_geojson_geometry(lng, lat, geometry):
    """Checks if a point (lng, lat) lies inside a GeoJSON Polygon or MultiPolygon."""
    gtype = geometry.get("type")
    coords = geometry.get("coordinates", [])

    if gtype == "Polygon":
        if not coords:
            return False
        if point_in_poly(lng, lat, coords[0]):
            for hole in coords[1:]:
                if point_in_poly(lng, lat, hole):
                    return False
            return True
        return False

    elif gtype == "MultiPolygon":
        for poly in coords:
            if not poly:
                continue
            if point_in_poly(lng, lat, poly[0]):
                in_hole = False
                for hole in poly[1:]:
                    if point_in_poly(lng, lat, hole):
                        in_hole = True
                        break
                if not in_hole:
                    return True
        return False

    return False

def compute_bbox(geometry):
    """Computes bounding box (min_lng, min_lat, max_lng, max_lat) for fast spatial pre-filtering."""
    gtype = geometry.get("type")
    coords = geometry.get("coordinates", [])
    all_lngs, all_lats = [], []

    if gtype == "Polygon":
        for ring in coords:
            for pt in ring:
                all_lngs.append(pt[0])
                all_lats.append(pt[1])
    elif gtype == "MultiPolygon":
        for poly in coords:
            for ring in poly:
                for pt in ring:
                    all_lngs.append(pt[0])
                    all_lats.append(pt[1])

    if not all_lngs or not all_lats:
        return (0, 0, 0, 0)
    return (min(all_lngs), min(all_lats), max(all_lngs), max(all_lats))

def calculate_index(pts, pop, count_target, per_cap_target):
    """Calculates a dual-vector index (0-100) balancing municipal count and per-capita availability."""
    if not pts or pts <= 0 or not pop or pop <= 0:
        return 0

    eff_pop_k = float(pop) / 1000.0
    per_cap = float(pts) / eff_pop_k

    score_count = min(100.0, (float(pts) / count_target) * 100.0)
    score_per_cap = min(100.0, (per_cap / per_cap_target) * 100.0)

    # 50% physical municipal inventory + 50% population intensity
    blended = 0.50 * score_count + 0.50 * score_per_cap
    return int(min(100, max(0, round(blended))))

def fetch_via_native_curl(endpoint, query):
    """Fallback using macOS native curl (Apple SecureTransport) when LibreSSL Python 3.9 rejects TLS 1.3."""
    try:
        proc = subprocess.run(
            [
                "curl", "-sS", "-m", "95",
                "-A", USER_AGENT,
                "-H", "Accept: application/json, */*",
                "--data-urlencode", f"data={query}",
                endpoint
            ],
            capture_output=True,
            text=True,
            timeout=100
        )
        if proc.returncode == 0 and proc.stdout:
            data = json.loads(proc.stdout)
            if isinstance(data, dict) and "elements" in data:
                return data
    except Exception as e:
        print(f"   ⚠️ Native curl fallback notice [{endpoint}]: {e}")
    return None

def fetch_overpass_query(session, query):
    """Executes a single regional Overpass QL query with failover across resilient public mirrors."""
    payload = {"data": query}

    for endpoint in OVERPASS_ENDPOINTS:
        for attempt in range(2):
            try:
                print(f"   🌐 Querying Overpass mirror: {endpoint} (attempt {attempt + 1})...")
                res = session.post(endpoint, data=payload, headers=HEADERS_OVERPASS, timeout=95)
                if res.status_code == 200:
                    data = res.json()
                    if isinstance(data, dict) and "elements" in data:
                        return data
                else:
                    print(f"   ⚠️ Overpass mirror [{endpoint}] returned HTTP {res.status_code}")
            except requests.exceptions.SSLError:
                curl_data = fetch_via_native_curl(endpoint, query)
                if curl_data is not None:
                    return curl_data
                break
            except Exception as e:
                print(f"   ⚠️ Overpass mirror [{endpoint}]: {e}")
            time.sleep(2.0)

    return None

def resolve_population(slug, city_name, demographics, crime_stats, transit_radar):
    """Authoritative population resolution across verified municipal datasets."""
    pop = demographics.get(slug, {}).get("population")
    if pop and isinstance(pop, (int, float)) and pop > 0:
        return int(pop)

    pop_crime = crime_stats.get(city_name, {}).get("reported_population")
    if pop_crime and isinstance(pop_crime, (int, float)) and pop_crime > 0:
        return int(pop_crime)

    pop_transit = transit_radar.get(slug, {}).get("population")
    if pop_transit and isinstance(pop_transit, (int, float)) and pop_transit > 0:
        return int(pop_transit)

    return None

def extract_element_coords(el):
    """Extracts (lat, lon) from Overpass node coordinates or way/relation center geometry."""
    lat = el.get("lat")
    lon = el.get("lon")
    if lat is None or lon is None:
        center = el.get("center") or {}
        lat = center.get("lat")
        lon = center.get("lon")
    if lat is None or lon is None:
        return None, None
    try:
        return float(lat), float(lon)
    except (ValueError, TypeError):
        return None, None

def main():
    print("📍 Ingesting Regional OpenStreetMap Amenities & Clipping to Incorporated City Boundaries...")
    if not os.path.exists(CITY_DATA_PATH):
        print(f"❌ Required city data missing at `{CITY_DATA_PATH}`.")
        return

    if not os.path.exists(CITY_BOUNDARIES_PATH):
        print(f"❌ Required city boundaries missing at `{CITY_BOUNDARIES_PATH}`.")
        return

    try:
        with open(CITY_DATA_PATH, "r", encoding="utf-8") as f:
            raw_cities = json.load(f)
        with open(CITY_BOUNDARIES_PATH, "r", encoding="utf-8") as f:
            boundaries_geo = json.load(f)
    except Exception as e:
        print(f"❌ Failed to parse municipal JSON inputs: {e}")
        return

    demographics = {}
    if os.path.exists(DEMOGRAPHICS_PATH):
        with open(DEMOGRAPHICS_PATH, "r", encoding="utf-8") as f:
            demographics = json.load(f)

    crime_stats = {}
    if os.path.exists(CRIME_STATS_PATH):
        with open(CRIME_STATS_PATH, "r", encoding="utf-8") as f:
            crime_stats = json.load(f)

    transit_radar = {}
    if os.path.exists(TRANSIT_RADAR_PATH):
        with open(TRANSIT_RADAR_PATH, "r", encoding="utf-8") as f:
            transit_radar = json.load(f)

    # Build municipal polygon lookup and compute unified King + Snohomish regional bounding box
    city_polygons = []
    global_min_lng, global_min_lat = 180.0, 90.0
    global_max_lng, global_max_lat = -180.0, -90.0

    for feat in boundaries_geo.get("features", []):
        props = feat.get("properties", {})
        c_slug = props.get("slug") or slugify(props.get("CityName") or props.get("name") or "")
        c_name = props.get("CityName") or props.get("name") or ""
        geom = feat.get("geometry", {})
        bbox = compute_bbox(geom)
        if bbox != (0, 0, 0, 0):
            min_lng, min_lat, max_lng, max_lat = bbox
            global_min_lng = min(global_min_lng, min_lng)
            global_min_lat = min(global_min_lat, min_lat)
            global_max_lng = max(global_max_lng, max_lng)
            global_max_lat = max(global_max_lat, max_lat)
        city_polygons.append({
            "slug": c_slug,
            "name": c_name,
            "geometry": geom,
            "bbox": bbox
        })

    if global_min_lng >= global_max_lng or global_min_lat >= global_max_lat:
        south, west, north, east = 47.08, -122.55, 48.30, -121.05
    else:
        south = round(global_min_lat - 0.01, 4)
        west = round(global_min_lng - 0.01, 4)
        north = round(global_max_lat + 0.01, 4)
        east = round(global_max_lng + 0.01, 4)

    bbox_str = f"{south},{west},{north},{east}"
    print(f"   🗺️ Executing single regional Overpass query across bounding box ({bbox_str})...")

    overpass_query = f"""[out:json][timeout:90];
(
  nwr["leisure"="dog_park"]({bbox_str});
  nwr["amenity"="cafe"]({bbox_str});
  nwr["leisure"="park"]({bbox_str});
  nwr["natural"="beach"]({bbox_str});
  nwr["shop"="pet"]({bbox_str});
  nwr["leisure"="golf_course"]({bbox_str});
  nwr["craft"="brewery"]({bbox_str});
  nwr["amenity"="pub"]({bbox_str});
  nwr["craft"="winery"]({bbox_str});
  nwr["shop"="wine"]({bbox_str});
);
out center tags qt;"""

    session = requests.Session()
    res = fetch_overpass_query(session, overpass_query)
    if not res or "elements" not in res:
        print(f"❌ Regional Overpass query failed across all mirrors. Preserving existing {OUT_PATH}.")
        return

    elements = res.get("elements", [])
    print(f"   📦 Retrieved {len(elements):,} regional OSM elements. Clipping to city boundaries locally...")

    # Initialize per-city counters
    city_counts = {
        c["slug"]: {
            "dog_parks": 0,
            "coffee_shops": 0,
            "parks": 0,
            "beaches": 0,
            "pet_stores": 0,
            "golf_courses": 0,
            "breweries_pubs": 0,
            "wineries_wine_shops": 0
        }
        for c in city_polygons
    }

    seen_elements = set()
    matched_count = 0

    for el in elements:
        el_key = (el.get("type"), el.get("id"))
        if el_key in seen_elements:
            continue
        seen_elements.add(el_key)

        el_lat, el_lon = extract_element_coords(el)
        if el_lat is None or el_lon is None:
            continue

        tags = el.get("tags", {})
        leisure = tags.get("leisure")
        amenity = tags.get("amenity")
        natural = tags.get("natural")
        shop = tags.get("shop")
        craft = tags.get("craft")

        category = None
        if leisure == "dog_park":
            category = "dog_parks"
        elif amenity == "cafe":
            category = "coffee_shops"
        elif leisure == "park":
            category = "parks"
        elif natural == "beach":
            category = "beaches"
        elif shop == "pet":
            category = "pet_stores"
        elif leisure == "golf_course":
            category = "golf_courses"
        elif craft == "brewery" or amenity == "pub":
            category = "breweries_pubs"
        elif craft == "winery" or shop == "wine":
            category = "wineries_wine_shops"

        if not category:
            continue

        for c in city_polygons:
            min_lng, min_lat, max_lng, max_lat = c["bbox"]
            if min_lng <= el_lon <= max_lng and min_lat <= el_lat <= max_lat:
                if is_point_in_geojson_geometry(el_lon, el_lat, c["geometry"]):
                    city_counts[c["slug"]][category] += 1
                    matched_count += 1
                    break

    print(f"   🎯 Matched {matched_count:,} amenities inside incorporated municipal polygons.")

    items = raw_cities if isinstance(raw_cities, list) else list(raw_cities.values())
    output = {}
    now_iso = datetime.now(timezone.utc).isoformat()

    for it in items:
        raw_name = it.get("City") or it.get("name") or ""
        if not raw_name:
            continue

        city_name = str(raw_name).strip()
        slug = slugify(city_name)
        pop = resolve_population(slug, city_name, demographics, crime_stats, transit_radar)

        if not pop:
            print(f"   ⚠️ Warning: No verified population found for {city_name}. Scores will default to 0.")

        counts = city_counts.get(slug, {
            "dog_parks": 0,
            "coffee_shops": 0,
            "parks": 0,
            "beaches": 0,
            "pet_stores": 0,
            "golf_courses": 0,
            "breweries_pubs": 0,
            "wineries_wine_shops": 0
        })

        bark_pts = (counts["pet_stores"] * 1) + (counts["dog_parks"] * 5)
        scores = {
            "bark_score": calculate_index(bark_pts, pop, BENCHMARKS["bark"]["count"], BENCHMARKS["bark"]["per_capita"]),
            "park_score": calculate_index(counts["parks"], pop, BENCHMARKS["park"]["count"], BENCHMARKS["park"]["per_capita"]),
            "shore_score": calculate_index(counts["beaches"], pop, BENCHMARKS["shore"]["count"], BENCHMARKS["shore"]["per_capita"]),
            "caffeine_score": calculate_index(counts["coffee_shops"], pop, BENCHMARKS["caffeine"]["count"], BENCHMARKS["caffeine"]["per_capita"]),
            "golf_score": calculate_index(counts["golf_courses"], pop, BENCHMARKS["golf"]["count"], BENCHMARKS["golf"]["per_capita"]),
            "brew_score": calculate_index(counts["breweries_pubs"], pop, BENCHMARKS["brew"]["count"], BENCHMARKS["brew"]["per_capita"]),
            "wine_score": calculate_index(counts["wineries_wine_shops"], pop, BENCHMARKS["wine"]["count"], BENCHMARKS["wine"]["per_capita"])
        }

        output[slug] = {
            "name": city_name,
            "population": pop,
            "amenities": counts,
            "scores": scores,
            "last_updated": now_iso
        }

    # Safety check: Prevent overwriting dataset if fewer than 40 municipalities are processed
    if len(output) < 40:
        print(f"❌ Safety check failed: Only {len(output)} cities processed. Preserving existing {OUT_PATH}.")
        return

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"💾 Successfully saved municipal amenities and scores for {len(output)} cities to {OUT_PATH}")

if __name__ == "__main__":
    main()