# File: scripts/harvest_climate.py

import os
import json
import math

CITY_DATA_PATH = os.path.join("data", "city_data.json")
OUTPUT_JSON_PATH = os.path.join("data", "climate_comfort.json")

CLIMATE_NODES = [
    {
        "node_id": "sound_inland_basin",
        "name": "Seattle-Tacoma Inland Basin (KSEA)",
        "lat": 47.4502, "lon": -122.3088,
        "summer_high_f": 77.0,
        "winter_low_f": 37.0,
        "annual_rainfall_inches": 39.3,
        "annual_sunny_days": 152,
        "comfort_index": 7.8,
        "description": "Standard marine-influenced climate with mild, temperate summers and moderate winter rainfall."
    },
    {
        "node_id": "north_sound_coast",
        "name": "North Sound & Snohomish Coast (KPAE)",
        "lat": 47.9073, "lon": -122.2816,
        "summer_high_f": 73.0,
        "winter_low_f": 35.0,
        "annual_rainfall_inches": 33.2,
        "annual_sunny_days": 158,
        "comfort_index": 8.1,
        "description": "Noticeably cooler summer peaks with reduced annual rainfall due to the Olympic mountain rain shadow effect."
    },
    {
        "node_id": "eastside_lake_basin",
        "name": "Eastside Lake Basin & Renton Hills (KRNT)",
        "lat": 47.4931, "lon": -122.2158,
        "summer_high_f": 79.0,
        "winter_low_f": 36.0,
        "annual_rainfall_inches": 41.5,
        "annual_sunny_days": 150,
        "comfort_index": 7.6,
        "description": "Slightly warmer, sunnier summer afternoons with typical lowland precipitation patterns."
    },
    {
        "node_id": "cascade_foothills_south",
        "name": "Snoqualmie Valley & Cascade Foothills (North Bend)",
        "lat": 47.4957, "lon": -121.7867,
        "summer_high_f": 78.0,
        "winter_low_f": 32.0,
        "annual_rainfall_inches": 60.5,
        "annual_sunny_days": 138,
        "comfort_index": 6.8,
        "description": "Heavy foothill precipitation with cooler winter baselines and occasional lowland snow accumulation."
    },
    {
        "node_id": "north_snohomish_foothills",
        "name": "North Snohomish Foothills (KAWO)",
        "lat": 48.1608, "lon": -122.1586,
        "summer_high_f": 75.0,
        "winter_low_f": 33.0,
        "annual_rainfall_inches": 46.5,
        "annual_sunny_days": 144,
        "comfort_index": 7.2,
        "description": "Subject to frequent Convergence Zone activity resulting in higher rainfall thresholds than the coastal strip."
    }
]

def calculate_haversine_distance(lat1, lon1, lat2, lon2):
    earth_radius_miles = 3958.8
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    
    a = (math.sin(d_lat / 2) ** 2 + 
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(earth_radius_miles * c, 1)

def main():
    print("🚀 Initializing Puget Sound Microclimate Node Engine...")
    
    if not os.path.exists(CITY_DATA_PATH):
        print(f"❌ Error: Required master city data file missing at {CITY_DATA_PATH}")
        return
        
    with open(CITY_DATA_PATH, "r", encoding="utf-8") as f:
        city_records = json.load(f)

    climate_registry = {}

    for row in city_records:
        city_name = str(row.get('City', '')).strip()
        if not city_name:
            continue
            
        try:
            city_lat = float(row.get('Latitude', 0))
            city_lon = float(row.get('Longitude', 0))
        except (ValueError, TypeError):
            continue

        closest_node = None
        min_distance = float('inf')
        
        for node in CLIMATE_NODES:
            dist = calculate_haversine_distance(city_lat, city_lon, node["lat"], node["lon"])
            if dist < min_distance:
                min_distance = dist
                closest_node = node

        print(f"🌤️ {city_name} tied to {closest_node['name']} ({min_distance} mi)")

        climate_registry[city_name] = {
            "assigned_weather_station": closest_node["name"],
            "proximity_to_station_miles": min_distance,
            "metrics": {
                "average_summer_high_f": closest_node["summer_high_f"],
                "average_winter_low_f": closest_node["winter_low_f"],
                "annual_rainfall_inches": closest_node["annual_rainfall_inches"],
                "annual_sunny_days": closest_node["annual_sunny_days"]
            },
            "comfort_index_score": closest_node["comfort_index"],
            "microclimate_summary": closest_node["description"]
        }

    os.makedirs(os.path.dirname(OUTPUT_JSON_PATH), exist_ok=True)
    with open(OUTPUT_JSON_PATH, 'w', encoding="utf-8") as f:
        json.dump(climate_registry, f, indent=2, ensure_ascii=False)
        
    print(f"🏁 Success! Climate Comfort metrics written to: {OUTPUT_JSON_PATH}")

if __name__ == "__main__":
    main()