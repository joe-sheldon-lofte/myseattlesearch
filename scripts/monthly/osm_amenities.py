# File: scripts/monthly/osm_amenities.py
import os
import json
import time
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
OUT_PATH = os.path.join(DATA_DIR, "city_amenities.json")

# Verified OpenStreetMap Overpass Public Interpreters
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter"
]

# Policy-compliant application identity header to eliminate HTTP 406 blocks
HEADERS_OVERPASS = {
    "User-Agent": "MySeattleSearch-MunicipalAmenities/1.0 (https://myseattlesearch.com; contact@myseattlesearch.com)",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Accept": "application/json, */*"
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

def fetch_overpass_query(session, query):
    """Executes an optimized Overpass QL query with failover across resilient public mirrors."""
    payload = {"data": query}

    for endpoint in OVERPASS_ENDPOINTS:
        try:
            res = session.post(endpoint, data=payload, headers=HEADERS_OVERPASS, timeout=60)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, dict) and "elements" in data:
                    return data
                else:
                    print(f"   ⚠️ Malformed response from {endpoint}")
            else:
                print(f"   ⚠️ Overpass mirror notice [{endpoint}]: HTTP Error {res.status_code}")
        except Exception as e:
            print(f"   ⚠️ Overpass mirror notice [{endpoint}]: {e}")
        time.sleep(1.0)

    return None

def main():
    print("📍 Ingesting Municipal Amenities via OpenStreetMap Overpass Query...")
    if not os.path.exists(CITY_DATA_PATH):
        print(f"ℹ️ Required city data missing at `{CITY_DATA_PATH}`. Skipping OSM amenities.")
        return

    try:
        with open(CITY_DATA_PATH, "r", encoding="utf-8") as f:
            raw_cities = json.load(f)
    except Exception as e:
        print(f"❌ Failed to parse {CITY_DATA_PATH}: {e}")
        return

    items = raw_cities if isinstance(raw_cities, list) else list(raw_cities.values())
    valid_cities = []
    for it in items:
        name = it.get("City") or it.get("name") or ""
        lat = it.get("Latitude") or it.get("lat") or it.get("latitude")
        lon = it.get("Longitude") or it.get("lon") or it.get("lng") or it.get("longitude")
        if name and lat is not None and lon is not None:
            try:
                valid_cities.append({
                    "slug": slugify(name),
                    "name": str(name).strip(),
                    "lat": float(str(lat).strip()),
                    "lon": float(str(lon).strip())
                })
            except (ValueError, TypeError):
                pass

    if not valid_cities:
        print("ℹ️ No valid city GPS coordinates found in city_data.json.")
        return

    session = requests.Session()

    # Bounding box covering Puget Sound corridor: South Pierce through North Snohomish
    bbox = "47.0,-122.6,48.2,-121.8"

    # [maxsize:536870912] sets 512MB RAM cap; 'out center qt;' sorts geographically (eliminating HTTP 500 crashes)
    overpass_query = f"""[out:json][timeout:90][maxsize:536870912];
(
  nwr["leisure"="dog_park"]({bbox});
  nwr["amenity"="cafe"]({bbox});
  nwr["leisure"="park"]({bbox});
  nwr["natural"="beach"]({bbox});
  nwr["shop"="pet"]({bbox});
  nwr["leisure"="golf_course"]({bbox});
  nwr["craft"="brewery"]({bbox});
  nwr["amenity"="pub"]({bbox});
  nwr["craft"="winery"]({bbox});
  nwr["shop"="wine"]({bbox});
);
out center qt;"""

    res = fetch_overpass_query(session, overpass_query)
    if not res or not isinstance(res, dict) or "elements" not in res:
        print("⚠️ Unable to retrieve Overpass nodes. Preserving existing amenities dataset.")
        return

    nodes = res["elements"]
    print(f"   ✅ Ingested {len(nodes)} amenity nodes from OpenStreetMap.")

    output = {}
    radius_deg = 0.035  # ~2.4 mile radius perimeter from city centroid

    for city in valid_cities:
        slug = city["slug"]
        clat, clon = city["lat"], city["lon"]

        counts = {
            "dog_parks": 0,
            "coffee_shops": 0,
            "parks": 0,
            "beaches": 0,
            "pet_stores": 0,
            "golf_courses": 0,
            "breweries_pubs": 0,
            "wineries_wine_shops": 0
        }

        for node in nodes:
            nlat = node.get("lat") or node.get("center", {}).get("lat")
            nlon = node.get("lon") or node.get("center", {}).get("lon")
            if nlat is None or nlon is None:
                continue

            try:
                nlat_f, nlon_f = float(nlat), float(nlon)
            except (ValueError, TypeError):
                continue

            if abs(nlat_f - clat) <= radius_deg and abs(nlon_f - clon) <= radius_deg:
                tags = node.get("tags", {})
                leisure = tags.get("leisure")
                amenity = tags.get("amenity")
                natural = tags.get("natural")
                shop = tags.get("shop")
                craft = tags.get("craft")

                if leisure == "dog_park":
                    counts["dog_parks"] += 1
                elif amenity == "cafe":
                    counts["coffee_shops"] += 1
                elif leisure == "park":
                    counts["parks"] += 1
                elif natural == "beach":
                    counts["beaches"] += 1
                elif shop == "pet":
                    counts["pet_stores"] += 1
                elif leisure == "golf_course":
                    counts["golf_courses"] += 1
                elif craft == "brewery" or amenity == "pub":
                    counts["breweries_pubs"] += 1
                elif craft == "winery" or shop == "wine":
                    counts["wineries_wine_shops"] += 1

        output[slug] = {
            "name": city["name"],
            "amenities": counts,
            "last_updated": datetime.now(timezone.utc).isoformat()
        }

    # Anti-wipeout guard: ensure city data is populated before writing to disk
    if len(output) < 40:
        print(f"❌ Safety check failed: Only {len(output)} cities processed. Preserving existing {OUT_PATH}.")
        return

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"💾 Saved OSM amenities data for {len(output)} cities to {OUT_PATH}")

if __name__ == "__main__":
    main()