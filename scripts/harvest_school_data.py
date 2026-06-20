#!/usr/bin/env python3
"""
Real Estate Platform - Data-Driven School District Harvester
Source: Washington OSPI Report Card Assessment Data (Data.WA.gov)
Strategy: Reads targets directly from local CSV configuration (Column C)
"""

import os
import json
import csv
import sys
import requests

# -----------------------------------------------------------------------------
# CONFIGURATION & STATIC PATHS
# -----------------------------------------------------------------------------
DATASET_ID = "h5d9-vgwi"
SOCRATA_ENDPOINT = f"https://data.wa.gov/resource/{DATASET_ID}.json"
CSV_PATH = os.path.join("data", "InfoSparks Links - Sheet2.csv")
OUTPUT_FILE = os.path.join("data", "school_ratings.json")

# State benchmarks for frontend contextualization
STATE_MATH_BASELINE = 40.0
STATE_ELA_BASELINE = 51.0

def clean_percentage(val):
    """Sanitizes raw Socrata metrics, discarding privacy-suppressed strings."""
    if val is None:
        return None
    val_str = str(val).strip().replace("%", "")
    suppression_flags = ["<", ">", "suppressed", "null", "no students", "n/a"]
    if any(flag in val_str.lower() for flag in suppression_flags):
        return None
    try:
        return float(val_str)
    except ValueError:
        return None

def calculate_psai(math_score, ela_score):
    """Computes Proprietary Puget Sound Academic Index (PSAI) on a 1.0 - 10.0 scale."""
    if math_score is None or ela_score is None:
        return None
    return round((math_score + ela_score) / 20.0, 1)

def main():
    print("🚀 Booting Data-Driven OSPI Ingestion Client...")

    # 1. Read single source of truth CSV to gather target cities and districts
    if not os.path.exists(CSV_PATH):
        print(f"❌ Critical Error: Master CSV not found at {CSV_PATH}", file=sys.stderr)
        sys.exit(1)

    city_to_district_map = {}
    required_districts = set()

    with open(CSV_PATH, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            city = row.get("City", "").strip()
            # Grabs your new Column C target mapping
            district = row.get("School District", "").strip()
            
            if city and district:
                city_to_district_map[city] = district
                required_districts.add(district)

    if not city_to_district_map:
        print("❌ Error: No valid city-to-district records parsed from CSV. Check column headers.")
        sys.exit(1)

    print(f"📋 Loaded {len(city_to_district_map)} cities mapping to {len(required_districts)} distinct districts.")

    # 2. Call Socrata API filtering down payloads at the gateway layer
    query_params = {
        "$where": "organizationlevel='District' AND studentgroup='All Students' AND gradelevel='All Grades' AND testsubject IN('Math', 'ELA')",
        "$limit": 5000
    }
    
    try:
        response = requests.get(SOCRATA_ENDPOINT, params=query_params, timeout=30)
        response.raise_for_status()
        raw_rows = response.json()
    except requests.exceptions.RequestException as e:
        print(f"❌ Critical Error connecting to SODA API: {e}", file=sys.stderr)
        sys.exit(1)
        
    print(f"📥 Pulled {len(raw_rows)} compliance blocks from OSPI database. Sorting performance rows...")

    # 3. Store proficiency values keyed by official district names
    statewide_district_records = {}
    for row in raw_rows:
        district_name = row.get("districtname", "").strip()
        subject = row.get("testsubject", "").strip()
        
        # Support both current and historical API schema columns
        raw_pct = row.get("percent_consistent_grade_level_knowledge_and_above") or row.get("percentmetstandard")
        clean_pct = clean_percentage(raw_pct)
        
        if clean_pct is None or not district_name:
            continue
            
        if district_name not in statewide_district_records:
            statewide_district_records[district_name] = {"Math": None, "ELA": None}
            
        if subject in ["Math", "ELA"]:
            statewide_district_records[district_name][subject] = clean_pct

    # 4. Generate final JSON file matched precisely back against your CSV
    final_payload = {}
    
    for city, target_district in city_to_district_map.items():
        metrics = statewide_district_records.get(target_district)
        
        if metrics and metrics["Math"] is not None and metrics["ELA"] is not None:
            math_val = metrics["Math"]
            ela_val = metrics["ELA"]
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
            print(f"⚠️ Warning: Mapped district '{target_district}' for '{city}' not found in raw OSPI API response.")

    # 5. Output static payload build artifact
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final_payload, f, indent=2, ensure_ascii=False)
        
    print(f"🏁 Execution Complete. Cleaned data-driven assets compiled to: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
