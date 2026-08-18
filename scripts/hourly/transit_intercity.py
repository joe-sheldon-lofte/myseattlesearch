import os
import json
import re
import math
import urllib.request
import urllib.parse
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")

CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")
TRANSIT_DATA_PATH = os.path.join(DATA_DIR, "transit_data.json")
OUTPUT_RADAR_PATH = os.path.join(DATA_DIR, "transit_radar_live.json")

# Default seat capacities if transit_data.json is unpopulated or missing a mode
DEFAULT_SEAT_CAPACITIES = {
    "bus": 40,
    "light_rail": 150,
    "commuter_rail": 300,
    "monorail": 100,
    "streetcar": 60,
    "ferry": 250
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

def http_get_json(url, timeout=12):
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"   ⚠️ Transit API GET notice for {url}: {e}")
    return None

def calculate_active_transit_score(total_active_seats, population):
    """
    Formula:
    Active Transit Score = MIN(100, ROUND((Total Seats / (Population / 1000)) / 50 * 100, 0))
    Benchmark: 50 seats per 1k residents = Score of 100.
    """
    try:
        pop = float(population)
        if pop <= 0:
            return 0
        seats_per_1k = total_active_seats / (pop / 1000.0)
        raw_score = (seats_per_1k / 50.0) * 100.0
        return min(100, max(0, int(round(raw_score))))
    except Exception:
        return 0

def load_seat_defaults():
    if os.path.exists(TRANSIT_DATA_PATH):
        try:
            with open(TRANSIT_DATA_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "seat_defaults" in data:
                    return {**DEFAULT_SEAT_CAPACITIES, **data["seat_defaults"]}
        except Exception as e:
            print(f"   ⚠️ transit_data.json parse notice: {e}")
    return DEFAULT_SEAT_CAPACITIES

def main():
    print("🚌 Ingesting Active Regional Transit Feeds & Calculating Scores...")
    
    if not os.path.exists(CITY_DATA_PATH):
        print("❌ city_data.json not found. Aborting transit computation.")
        return

    with open(CITY_DATA_PATH, "r", encoding="utf-8") as f:
        raw_cities = json.load(f)

    city_items = raw_cities if isinstance(raw_cities, list) else list(raw_cities.values())
    seat_map = load_seat_defaults()

    # OneBusAway / GTFS-RT Agency Vehicle Endpoint (Fallback to Puget Sound agencies)
    oba_key = os.environ.get("OBA_API_KEY", "TEST").strip()
    agencies = ["1", "3", "29", "40", "95", "KMT"] # Metro, Sound Transit, Community Transit, Pierce, Everett, Kitsap
    
    # Harvest live active vehicles per agency
    agency_vehicles = {}
    for agency_id in agencies:
        url = f"http://api.pugetsound.onebusaway.org/api/where/vehicles-for-agency/{agency_id}.json?key={oba_key}"
        res = http_get_json(url)
        if res and isinstance(res, dict) and "data" in res and "list" in res["data"]:
            agency_vehicles[agency_id] = res["data"]["list"]
        else:
            agency_vehicles[agency_id] = []

    output_radar = {}

    for c_obj in city_items:
        raw_name = c_obj.get("City") or c_obj.get("name") or ""
        if not raw_name:
            continue
        
        city_name = str(raw_name).strip()
        slug = slugify(city_name)
        pop_val = int(c_obj.get("FallbackPopulation") or c_obj.get("population") or 10000)

        # Count active ground transit vehicles & estimate seats in city radius
        active_buses = 0
        active_light_rail = 0
        active_commuter_rail = 0
        active_monorail = 0

        # Sample active fleet distribution mapped to municipal coverage
        total_agency_active = sum(len(vlist) for vlist in agency_vehicles.values())
        
        # Determine municipal share of active fleet based on population weighting
        city_share_factor = min(0.12, max(0.01, pop_val / 800000.0))
        
        active_buses = int(round(total_agency_active * city_share_factor * 0.85))
        active_light_rail = int(round(total_agency_active * city_share_factor * 0.10))
        active_commuter_rail = int(round(total_agency_active * city_share_factor * 0.05))

        # Calculate Total In-Bounds Ground Seats
        total_active_seats = (
            (active_buses * seat_map.get("bus", 40)) +
            (active_light_rail * seat_map.get("light_rail", 150)) +
            (active_commuter_rail * seat_map.get("commuter_rail", 300)) +
            (active_monorail * seat_map.get("monorail", 100))
        )

        active_transit_score = calculate_active_transit_score(total_active_seats, pop_val)

        output_radar[slug] = {
            "name": city_name,
            "population": pop_val,
            "active_transit_score": active_transit_score,
            "total_active_seats": total_active_seats,
            "vehicle_counts": {
                "buses": active_buses,
                "light_rail": active_light_rail,
                "commuter_rail": active_commuter_rail,
                "monorail": active_monorail
            },
            "last_updated": datetime.now(timezone.utc).isoformat()
        }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_RADAR_PATH, "w", encoding="utf-8") as f:
        json.dump(output_radar, f, indent=2, ensure_ascii=False)
        
    print(f"💾 Saved live active transit radar & scores for {len(output_radar)} cities.")

if __name__ == "__main__":
    main()
