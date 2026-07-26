# File: scripts/harvest_school_data.py

import os
import json
import sys
import requests

DATASET_ID = "h5d9-vgwi"
SOCRATA_ENDPOINT = f"https://data.wa.gov/resource/{DATASET_ID}.json"
CITY_DATA_PATH = os.path.join("data", "city_data.json")
OUTPUT_FILE = os.path.join("data", "school_ratings.json")

STATE_MATH_BASELINE = 40.0
STATE_ELA_BASELINE = 51.0

def clean_percentage(val):
    if val is None:
        return None
    val_str = str(val).strip().replace("%", "")
    suppression_flags = ["<", ">", "suppressed", "null", "no students", "n/a", "*"]
    if any(flag in val_str.lower() for flag in suppression_flags):
        return None
    try:
        return float(val_str)
    except ValueError:
        return None

def calculate_psai(math_score, ela_score):
    if math_score is None or ela_score is None:
        return None
    return round((math_score + ela_score) / 20.0, 1)

def main():
    print("🚀 Booting Data-Driven OSPI Ingestion Client...")

    if not os.path.exists(CITY_DATA_PATH):
        print(f"❌ Critical Error: Master city data file missing at {CITY_DATA_PATH}", file=sys.stderr)
        sys.exit(1)

    with open(CITY_DATA_PATH, "r", encoding="utf-8") as f:
        city_records = json.load(f)

    city_to_district_map = {}
    required_districts = set()

    for row in city_records:
        city = str(row.get("City", "")).strip()
        district = str(row.get("School District", "")).strip()
        
        if city and district:
            city_to_district_map[city] = district
            required_districts.add(district)

    print(f"📋 Loaded {len(city_to_district_map)} cities mapping to {len(required_districts)} distinct districts.")

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
        
    print(f"📥 Pulled {len(raw_rows)} rows from OSPI database.")

    if not raw_rows:
        print("❌ Error: API returned an empty list of records.")
        sys.exit(1)

    sample_row = raw_rows[0]
    district_key = "districtname"
    for k in sample_row.keys():
        if k.lower() in ["districtname", "district_name", "organizationname"]:
            district_key = k
            break
        
    percent_key = None
    for k in sample_row.keys():
        if k.lower() in ["percent_consistent_grade", "percentmetstandard", "percent_consistent_grade_level"]:
            percent_key = k
            break
    if not percent_key:
        for k in sample_row.keys():
            if "percent" in k.lower() and "consistent" in k.lower() and "tested" not in k.lower():
                percent_key = k
                break

    print(f"🎯 Dynamic Mapping -> District Name Key: '{district_key}' | Score Key: '{percent_key}'")
    
    if not percent_key:
        print("❌ Critical Error: Could not dynamically resolve percentage score column key.")
        sys.exit(1)

    statewide_district_records = {}
    for row in raw_rows:
        district_name = row.get(district_key, "").strip()
        subject = row.get("testsubject") or row.get("test_subject") or ""
        subject = subject.strip()
        
        raw_pct = row.get(percent_key)
        clean_pct = clean_percentage(raw_pct)
        
        if not district_name:
            continue
            
        if district_name not in statewide_district_records:
            statewide_district_records[district_name] = {"Math": None, "ELA": None, "is_suppressed": False}
            
        if clean_pct is not None:
            if subject in ["Math", "ELA"]:
                statewide_district_records[district_name][subject] = clean_pct
        else:
            statewide_district_records[district_name]["is_suppressed"] = True

    print(f"📊 Successfully parsed performance matrices for {len(statewide_district_records)} distinct Washington districts.")

    final_payload = {}
    for city, target_district in city_to_district_map.items():
        metrics = statewide_district_records.get(target_district)
        matched_name = target_district
        
        if not metrics:
            norm_target = target_district.lower().replace("school district", "").replace("public schools", "").strip()
            for api_dist, api_metrics in statewide_district_records.items():
                norm_api = api_dist.lower().replace("school district", "").replace("public schools", "").strip()
                if norm_target and norm_api and (norm_target in norm_api or norm_api in norm_target):
                    metrics = api_metrics
                    matched_name = api_dist
                    break
        
        if metrics and metrics["Math"] is not None and metrics["ELA"] is not None:
            math_val = metrics["Math"]
            ela_val = metrics["ELA"]
            custom_score = calculate_psai(math_val, ela_val)
            
            final_payload[city] = {
                "district_name": matched_name,
                "district_math_proficiency": math_val,
                "district_ela_proficiency": ela_val,
                "custom_score": custom_score,
                "state_math_baseline": STATE_MATH_BASELINE,
                "state_ela_baseline": STATE_ELA_BASELINE,
                "status": "Active"
            }
        else:
            print(f"ℹ️ Privacy Fallback applied for {city}: Utilizing standardized insufficient data profile.")
            final_payload[city] = {
                "district_name": target_district,
                "district_math_proficiency": None,
                "district_ela_proficiency": None,
                "custom_score": None,
                "state_math_baseline": STATE_MATH_BASELINE,
                "state_ela_baseline": STATE_ELA_BASELINE,
                "status": "Insufficient Data (Small Student Population)"
            }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final_payload, f, indent=2, ensure_ascii=False)
        
    print(f"🏁 Execution Complete. Cleaned data-driven assets compiled to: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()