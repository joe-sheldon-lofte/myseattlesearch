#!/usr/bin/env python3
"""
Real Estate Platform - Emergency Services Pipeline
Calculates proximity to the nearest regional trauma center/ER using 
Haversine coordinate math and appends federal CMS quality star ratings.
"""

import os
import json
import io
import math
import pandas as pd

CSV_PATH = "data/InfoSparks Links - Sheet2.csv"
OUTPUT_JSON_PATH = "data/public_safety_emergency.json"

# High-fidelity regional hospital coordinate registry with official federal CMS Star Ratings
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
    """Computes the straight-line distance in miles between two coordinate spheres."""
    # Radius of the Earth in miles
    earth_radius_miles = 3958.8
    
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    
    a = (math.sin(d_lat / 2) ** 2 + 
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return round(earth_radius_miles * c, 1)

def clean_and_load_csv(file_path):
    """Self-healing CSV string builder that handles newline injection errors."""
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    reconstructed_lines = []
    header_count = len(lines[0].split(","))
    buffer_line = ""
    
    for line in lines:
        cleaned_line = line.strip()
        if not cleaned_line:
            continue
        if buffer_line:
            buffer_line = buffer_line + " " + cleaned_line
        else:
            buffer_line = cleaned_line
            
        if len(buffer_line.split(",")) >= header_count or any(x in buffer_line for x in ["WA0", "Unknown"]):
            reconstructed_lines.append(buffer_line)
            buffer_line = ""
            
    if buffer_line:
        reconstructed_lines.append(buffer_line)
        
    return pd.read_csv(io.StringIO("\n".join(reconstructed_lines)))

def main():
    print(f"🚀 Initializing Spatial Emergency Infrastructure Harvester...")
    
    if not os.path.exists(CSV_PATH):
        print(f"❌ Error: Required master spreadsheet missing at {CSV_PATH}")
        return
        
    df = clean_and_load_csv(CSV_PATH)
    emergency_registry = {}

    for _, row in df.iterrows():
        city_name = str(row['City']).strip()
        city_lat = float(row['Latitude'])
        city_lon = float(row['Longitude'])
        fire_dept = str(row['Fire Department Name']).strip()
        wsrb_val = str(row['FD WSRB Rating']).strip()

        # 1. Fire Department Rating Pass-Through Assessment
        if wsrb_val.lower() == 'unknown' or pd.isna(row['FD WSRB Rating']):
            insurance_outlook = "Data Review Pending"
            wsrb_output = None
        else:
            # WSRB standard class scale: Lower numbers represent superior protection coverage
            wsrb_output = int(float(wsrb_val))
            insurance_outlook = "Highly Favorable" if wsrb_output <= 3 else "Standard Premium"

        # 2. Nearest Emergency Room Proximity Loop
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

    # Save the independent dataset to file array storage
    os.makedirs(os.path.dirname(OUTPUT_JSON_PATH), exist_ok=True)
    with open(OUTPUT_JSON_PATH, 'w', encoding="utf-8") as f:
        json.dump(emergency_registry, f, indent=2, ensure_ascii=False)
        
    print(f"🏁 Success! Emergency medical and fire infrastructure logs written to: {OUTPUT_JSON_PATH}")

if __name__ == "__main__":
    main()
