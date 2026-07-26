# File: scripts/harvest_emergency.py

import os
import json
import math

CITY_DATA_PATH = os.path.join("data", "city_data.json")
OUTPUT_JSON_PATH = os.path.join("data", "public_safety_emergency.json")

REGIONAL_HOSPITALS = [
    {"name": "EvergreenHealth Medical Center (Kirkland)", "lat": 47.7121, "lon": -122.1818, "stars": "⭐⭐⭐⭐⭐ (5/5 Stars)"},
    {"name": "Overlake Medical Center (Bellevue)", "lat": 47.6192, "lon": -122.1819, "stars": "⭐⭐⭐⭐⭐ (5/5 Stars)"},
    {"name": "Swedish Edmonds Campus (Edmonds)", "lat": 47.7981, "lon": -122.3703, "stars": "⭐⭐⭐⭐ (4/5 Stars)"},
    {"name": "Providence Regional Medical Center (Everett)", "lat": 47.9944, "lon": -122.2039, "stars": "⭐⭐⭐ (3/5 Stars)"},
    {"name": "Harborview Medical Center (Seattle - Level I Trauma)", "lat": 47.6044, "lon": -122.3219, "stars": "⭐⭐⭐⭐ (4/5 Stars)"},
    {"name": "UW Medical Center - Montlake (Seattle)", "lat": 47.6515, "lon": -122.3075, "stars": "⭐⭐⭐⭐⭐ (5/5 Stars)"},
    {"name": "Valley Medical Center (Renton)", "lat": 47.4533, "lon": -122.2307, "stars": "⭐⭐⭐ (3/5 Stars)"},
    {"name": "St. Francis Hospital (Federal Way)", "lat": 47.3117, "lon": -122.3023, "stars": "⭐⭐⭐⭐ (4/5 Stars)"},
    {"name": "MultiCare Auburn Medical Center (Auburn)", "lat": 47.3103, "lon": -122.2227, "stars": "⭐⭐⭐ (3/5 Stars)"},
    {"name": "Cascade Valley Hospital (Arlington)", "lat": 48.1923, "lon": -122.1332, "stars": "⭐⭐⭐⭐ (4/5 Stars)"},
    {"name": "Swedish First Hill Campus (Seattle)", "lat": 47.6101, "lon": -122.3214, "stars": "⭐⭐⭐⭐ (4/5 Stars)"}
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
    print("🚀 Initializing Spatial Emergency Infrastructure Harvester...")
    
    if not os.path.exists(CITY_DATA_PATH):
        print(f"❌ Error: Required master city data file missing at {CITY_DATA_PATH}")
        return
        
    with open(CITY_DATA_PATH, "r", encoding="utf-8") as f:
        city_records = json.load(f)

    emergency_registry = {}

    for row in city_records:
        city_name = str(row.get('City', '')).strip()
        if not city_name:
            continue

        try:
            city_lat = float(row.get('Latitude', 0))
            city_lon = float(row.get('Longitude', 0))
        except (ValueError, TypeError):
            continue

        fire_dept = str(row.get('Fire Department Name', '')).strip()
        wsrb_raw = str(row.get('FD WSRB Rating', '')).strip()

        if not wsrb_raw or wsrb_raw.lower() in ['unknown', 'none', 'nan', '']:
            insurance_outlook = "Data Review Pending"
            wsrb_output = None
        else:
            try:
                wsrb_output = int(float(wsrb_raw))
                insurance_outlook = "Highly Favorable" if wsrb_output <= 3 else "Standard Premium"
            except (ValueError, TypeError):
                insurance_outlook = "Data Review Pending"
                wsrb_output = None

        closest_hospital = None
        min_distance = float('inf')
        
        for hosp in REGIONAL_HOSPITALS:
            dist = calculate_haversine_distance(city_lat, city_lon, hosp["lat"], hosp["lon"])
            if dist < min_distance:
                min_distance = dist
                closest_hospital = hosp

        print(f"📍 {city_name} -> Nearest ER: {closest_hospital['name']} ({min_distance} mi)")

        emergency_registry[city_name] = {
            "fire_service": {
                "agency_name": fire_dept,
                "wsrb_protection_class": wsrb_output,
                "homeowners_insurance_impact": insurance_outlook
            },
            "emergency_medical": {
                "nearest_hospital_facility": closest_hospital["name"],
                "distance_proximity_miles": min_distance,
                "cms_hospital_quality_rating": closest_hospital["stars"]
            }
        }

    os.makedirs(os.path.dirname(OUTPUT_JSON_PATH), exist_ok=True)
    with open(OUTPUT_JSON_PATH, 'w', encoding="utf-8") as f:
        json.dump(emergency_registry, f, indent=2, ensure_ascii=False)
        
    print(f"🏁 Success! Emergency medical and fire infrastructure logs written to: {OUTPUT_JSON_PATH}")

if __name__ == "__main__":
    main()