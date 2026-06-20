#!/usr/bin/env python3
"""
Real Estate Platform - School District Data Harvester
Source: Washington OSPI Report Card Assessment Data (Data.WA.gov)
Cost: 100% Free (No API Key Required for Public SODA Read)
"""

import os
import json
import sys
import requests

# -----------------------------------------------------------------------------
# 1. CONFIGURATION & BENCHMARKS
# -----------------------------------------------------------------------------
# Official OSPI 2024-25 Report Card Assessment Dataset Identifier
DATASET_ID = "h5d9-vgwi"
SOCRATA_ENDPOINT = f"https://data.wa.gov/resource/{DATASET_ID}.json"
OUTPUT_FILE = os.path.join("data", "school_ratings.json")

# Latest statewide baseline metrics for context comparison
STATE_MATH_BASELINE = 40.0
STATE_ELA_BASELINE = 51.0

# Explicit mapping for core municipal markets. 
# Any city not listed here will fall back automatically to "[City Name] School District"
CITY_TO_DISTRICT_MAP = {
    "seattle": "Seattle Public Schools",
    "bellevue": "Bellevue School District",
    "kirkland": "Lake Washington School District",
    "redmond": "Lake Washington School District",
    "sammamish": "Issaquah School District",
    "issaquah": "Issaquah School District",
    "tacoma": "Tacoma School District",
    "spokane": "Spokane School District",
    "bellingham": "Bellingham School District",
    "olympia": "Olympia School District",
    "vancouver": "Vancouver School District",
    "renton": "Renton School District",
    "everett": "Everett School District",
    "bothell": "Northshore School District",
    "kenmore": "Northshore School District",
    "woodinville": "Northshore School District"
}

# -----------------------------------------------------------------------------
# 2. UTILITY FUNCTIONS
# -----------------------------------------------------------------------------
def clean_percentage(val):
    """Parses and sanitizes Socrata's mixed-type string/numeric percentage data."""
    if val is None:
        return None
    
    val_str = str(val).strip().replace("%", "")
    
    # Filter out legal/privacy data suppressions (e.g., '<10%', 'Suppressed', 'Null')
    suppression_flags = ["<", ">", "suppressed", "null", "no students", "n/a"]
    if any(flag in val_str.lower() for flag in suppression_flags):
        return None
        
    try:
        return float(val_str)
    except ValueError:
        return None

def calculate_psai(math_score, ela_score):
    """
    Computes the Proprietary Puget Sound Academic Index (PSAI) on a 1.0 - 10.0 scale.
    Formula: (Math% + ELA%) / 20
    """
    if math_score is None or ela_score is None:
        return None
    return round((math_score + ela_score) / 20.0, 1)

# -----------------------------------------------------------------------------
# 3. CORE INGESTION PIPELINE
# -----------------------------------------------------------------------------
def main():
    print(f"🚀 Initializing Washington OSPI Ingestion Client [Dataset: {DATASET_ID}]...")
    
    # Build efficient SODA API selection filters
    # We restrict rows directly at the API gateway layer to keep payload overhead low
    query_params = {
        "$where": "organizationlevel='District' AND studentgroup='All Students' AND gradelevel='All Grades' AND testsubject IN('Math', 'ELA')",
        "$limit": 5000
    }
    
    try:
        response = requests.get(SOCRATA_ENDPOINT, params=query_params, timeout=30)
        response.raise_for_status()
        raw_rows = response.json()
    except requests.exceptions.RequestException as e:
        print(f"❌ Critical Error connecting to Data.WA.gov SODA API: {e}", file=sys.stderr)
        sys.exit(1)
        
    print(f"📥 Successfully parsed {len(raw_rows)} raw compliance rows. Indexing data...")

    # Organize raw rows into structured local district storage
    # Accommodates both historic or current Socrata naming schema keys
    processed_districts = {}
    
    for row in raw_rows:
        district_name = row.get("districtname")
        if not district_name:
            continue
            
        subject = row.get("testsubject", "").strip()
        
        # Pull raw performance values from known alternative schema keys
        raw_pct = row.get("percent_consistent_grade_level_knowledge_and_above") or row.get("percentmetstandard")
        clean_pct = clean_percentage(raw_pct)
        
        if clean_pct is None:
            continue
            
        if district_name not in processed_districts:
            processed_districts[district_name] = {"Math": None, "ELA": None}
            
        if subject in ["Math", "ELA"]:
            processed_districts[district_name][subject] = clean_pct

    # Ensure output target directories are created safely
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    
    # Process final structured city payload output
    final_payload = {}
    
    # List of target markets to cycle through (Your 59 system cities)
    # For representation, we iterate over our dictionary & a list of verified cities
    target_cities = ["Seattle", "Bellevue", "Kirkland", "Redmond", "Sammamish", "Issaquah", 
                     "Tacoma", "Spokane", "Bellingham", "Olympia", "Vancouver", "Renton", "Everett"]

    for city in target_cities:
        city_lower = city.lower()
        
        # Determine the mapped official district name
        if city_lower in CITY_TO_DISTRICT_MAP:
            target_district = CITY_TO_DISTRICT_MAP[city_lower]
        else:
            target_district = f"{city} School District"
            
        # Match with parsed API records
        district_data = processed_districts.get(target_district)
        
        if district_data and district_data["Math"] and district_data["ELA"]:
            math_val = district_data["Math"]
            ela_val = district_data["ELA"]
            custom_score = calculate_psai(math_val, ela_val)
            
            final_payload[city] = {
                "district_name": target_district,
                "district_math_proficiency": math_val,
                "district_ela_proficiency": ela_val,
                "custom_score": custom_score,
                "state_math_baseline": STATE_MATH_BASELINE,
                "state_ela_baseline": STATE_ELA_BASELINE
            }
        else:
            print(f"⚠️ Warning: No complete matching data found for {city} (Searched: '{target_district}')")

    # Save output to static JSON storage
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final_payload, f, indent=2, ensure_ascii=False)
        
    print(f"🏁 Execution Complete. Processed metrics compiled to: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
