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
DEMOGRAPHICS_PATH = os.path.join(DATA_DIR, "city_demographics.json")
CRIME_STATS_PATH = os.path.join(DATA_DIR, "crime_stats.json")
TRANSIT_RADAR_PATH = os.path.join(DATA_DIR, "transit_radar_live.json")
OUT_PATH = os.path.join(DATA_DIR, "city_amenities.json")

# Verified OpenStreetMap Overpass Public Interpreters
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter"
]

HEADERS_OVERPASS = {
    "User-Agent": "MySeattleSearch-MunicipalAmenities/2.0 (https://myseattlesearch.com; contact@myseattlesearch.com)",
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

def fetch_overpass_query(session, query):
    """Executes an Overpass QL query with failover across resilient public mirrors."""
    payload = {"data": query}

    for endpoint in OVERPASS_ENDPOINTS:
        try:
            res = session.post(endpoint, data=payload, headers=HEADERS_OVERPASS, timeout=45)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, dict) and "elements" in data:
                    return data
        except Exception as e:
            print(f"   ⚠️ Overpass mirror [{endpoint}]: {e}")
        time.sleep(1.0)

    return None

def resolve_population(slug, city_name, demographics, crime_stats, transit_radar):
    """Authoritative population resolution across verified municipal datasets (Zero Fallback)."""
    # 1. Primary: city_demographics.json
    pop = demographics.get(slug, {}).get("population")
    if pop and isinstance(pop, (int, float)) and pop > 0:
        return int(pop)

    # 2. Secondary: crime_stats.json (title-cased)
    pop_crime = crime_stats.get(city_name, {}).get("reported_population")
    if pop_crime and isinstance(pop_crime, (int, float)) and pop_crime > 0:
        return int(pop_crime)

    # 3. Tertiary: transit_radar_live.json (slug-cased)
    pop_transit = transit_radar.get(slug, {}).get("population")
    if pop_transit and isinstance(pop_transit, (int, float)) and pop_transit > 0:
        return int(pop_transit)

    return None

def main():
    print("📍 Ingesting Municipal Amenities Strictly Within Official City Limits...")
    if not os.path.exists(CITY_DATA_PATH):
        print(f"❌ Required city data missing at `{CITY_DATA_PATH}`.")
        return

    try:
        with open(CITY_DATA_PATH, "r", encoding="utf-8") as f:
            raw_cities = json.load(f)
    except Exception as e:
        print(f"❌ Failed to parse {CITY_DATA_PATH}: {e}")
        return

    # Ingest verification datasets for population lookup
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

    items = raw_cities if isinstance(raw_cities, list) else list(raw_cities.values())
    valid_cities = []
    for it in items:
        name = it.get("City") or it.get("name") or ""
        if name:
            valid_cities.append({
                "slug": slugify(name),
                "name": str(name).strip()
            })

    session = requests.Session()
    output = {}

    for city in valid_cities:
        slug = city["slug"]
        city_name = city["name"]
        pop = resolve_population(slug, city_name, demographics, crime_stats, transit_radar)

        if not pop:
            print(f"   ⚠️ Warning: No verified population found for {city_name}. Skipping index calculation.")

        print(f"   🏛️ Querying incorporated limits for {city_name} (Pop: {pop})...")

        # Overpass Area Query: Strictly targets the city's official incorporated boundary (admin_level=8)
        overpass_query = f"""[out:json][timeout:60];
area["name"="{city_name}"]["boundary"="administrative"]["admin_level"="8"]->.cityArea;
(
  nwr["leisure"="dog_park"](area.cityArea);
  nwr["amenity"="cafe"](area.cityArea);
  nwr["leisure"="park"](area.cityArea);
  nwr["natural"="beach"](area.cityArea);
  nwr["shop"="pet"](area.cityArea);
  nwr["leisure"="golf_course"](area.cityArea);
  nwr["craft"="brewery"](area.cityArea);
  nwr["amenity"="pub"](area.cityArea);
  nwr["craft"="winery"](area.cityArea);
  nwr["shop"="wine"](area.cityArea);
);
out tags qt;"""

        res = fetch_overpass_query(session, overpass_query)
        elements = res.get("elements", []) if res else []

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

        for el in elements:
            tags = el.get("tags", {})
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

        # Calculate scores using population
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
            "last_updated": datetime.now(timezone.utc).isoformat()
        }

        # Rate-limiting pause between cities to protect public Overpass API servers
        time.sleep(1.2)

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