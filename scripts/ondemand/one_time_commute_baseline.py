"""
MYSEATTLESEARCH - ONE-TIME COMMUTE BASELINE GENERATOR
File: scripts/one_time_commute_baseline.py

Purpose:
  Calculates Northwest (Max Lat, Min Lng) and Southeast (Min Lat, Max Lng) 
  diagonal bounds for all 58 cities from city_boundaries.json, queries OSRM 
  for zero-traffic baseline drive times, and saves data/city_commute_baseline.json.
"""

import os
import json
import urllib.request
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

BOUNDARIES_PATH = os.path.join(DATA_DIR, "city_boundaries.json")
OUTPUT_BASELINE_PATH = os.path.join(DATA_DIR, "city_commute_baseline.json")

def slugify(text):
    if not text:
        return ""
    text = str(text).lower().strip()
    out = [ch if ch.isalnum() else '-' for ch in text]
    res = "".join(out)
    while '--' in res:
        res = res.replace('--', '-')
    return res.strip('-')

def compute_nw_se_bounds(geometry):
    """Calculates Northwest (Max Lat, Min Lng) and Southeast (Min Lat, Max Lng) coordinates."""
    gtype = geometry.get('type')
    coords = geometry.get('coordinates', [])
    all_lngs, all_lats = [], []

    def extract_pts(rings):
        for pt in rings:
            all_lngs.append(pt[0])
            all_lats.append(pt[1])

    if gtype == 'Polygon':
        for ring in coords:
            extract_pts(ring)
    elif gtype == 'MultiPolygon':
        for poly in coords:
            for ring in poly:
                extract_pts(ring)

    if not all_lngs or not all_lats:
        return None

    min_lng, max_lng = min(all_lngs), max(all_lngs)
    min_lat, max_lat = min(all_lats), max(all_lats)

    return {
        "nw_lat": round(max_lat, 6),
        "nw_lng": round(min_lng, 6),
        "se_lat": round(min_lat, 6),
        "se_lng": round(max_lng, 6)
    }

def fetch_osrm_baseline(nw_lat, nw_lng, se_lat, se_lng):
    """Queries OSRM routing engine for free-flow driving duration and distance."""
    url = f"http://router.project-osrm.org/route/v1/driving/{nw_lng},{nw_lat};{se_lng},{se_lat}?overview=false"
    headers = {"User-Agent": "MySeattleSearchBaseline/1.0", "Accept": "application/json"}
    req = urllib.request.Request(url, headers=headers)
    
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                routes = data.get("routes", [])
                if routes:
                    duration_sec = routes[0].get("duration", 0)
                    distance_m = routes[0].get("distance", 0)
                    duration_min = round(duration_sec / 60.0, 1)
                    distance_mi = round(distance_m / 1609.34, 1)
                    return duration_min, distance_mi
    except Exception as e:
        print(f"   ⚠️ OSRM baseline notice ({nw_lat},{nw_lng}): {e}")
    return None, None

def main():
    print("📍 Generating Static NW/SE Commute Coordinates & Baselines...")

    if not os.path.exists(BOUNDARIES_PATH):
        print(f"❌ {BOUNDARIES_PATH} missing. Aborting.")
        return

    with open(BOUNDARIES_PATH, "r", encoding="utf-8") as f:
        boundaries_geo = json.load(f)

    baseline_data = {}
    features = boundaries_geo.get('features', [])

    for feat in features:
        props = feat.get('properties', {})
        raw_name = props.get('CityName') or props.get('name') or ""
        if not raw_name:
            continue

        city_name = str(raw_name).strip()
        slug = slugify(city_name)
        geom = feat.get('geometry', {})

        coords = compute_nw_se_bounds(geom)
        if not coords:
            continue

        # Fetch zero-traffic OSRM baseline
        base_min, base_mi = fetch_osrm_baseline(
            coords["nw_lat"], coords["nw_lng"], 
            coords["se_lat"], coords["se_lng"]
        )

        baseline_data[slug] = {
            "name": city_name,
            "nw_lat": coords["nw_lat"],
            "nw_lng": coords["nw_lng"],
            "se_lat": coords["se_lat"],
            "se_lng": coords["se_lng"],
            "baseline_drive_minutes": base_min or 10.0,
            "diagonal_distance_miles": base_mi or 5.0,
            "generated_at": datetime.now(timezone.utc).isoformat()
        }

        print(f"  ✅ {city_name} ({slug}): NW ({coords['nw_lat']}, {coords['nw_lng']}) ➔ SE ({coords['se_lat']}, {coords['se_lng']}) = {base_min} mins ({base_mi} mi)")

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_BASELINE_PATH, "w", encoding="utf-8") as f:
        json.dump(baseline_data, f, indent=2, ensure_ascii=False)

    print(f"\n💾 Saved static commute baseline for {len(baseline_data)} cities ➔ {OUTPUT_BASELINE_PATH}")

if __name__ == "__main__":
    main()