#!/usr/bin/env python3
"""
Real Estate Platform - Washington State Crime Data Pipeline
Features: Direct connection to data.wa.gov Socrata repository, 
          automatic contract-city fallback mapping, and keyless execution.
"""

import os
import json
import io
import time
import requests
import pandas as pd

CSV_PATH = "data/InfoSparks Links - Sheet2.csv"
OUTPUT_JSON_PATH = "data/crime_stats.json"

# Official data.wa.gov Uniform Crime Reporting dataset (Summary Reporting System API)
WA_STATE_CRIME_URL = "https://data.wa.gov/resource/6njs-53y5.json?$limit=50000"

def clean_and_load_csv(file_path):
    """Reads raw CSV text and repairs broken row-wraps before handing to pandas."""
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

def fetch_wa_state_crime_data():
    """Downloads the entire state-level historical UCR matrix in a single step."""
    print("📡 Syncing official crime ledger from data.wa.gov portals...")
    headers = {"User-Agent": "PugetSoundRealEstateCrimeIndexer/1.0"}
    try:
        response = requests.get(WA_STATE_CRIME_URL, headers=headers, timeout=30)
        response.raise_for_status()
        records = response.json()
        print(f"✅ Successfully downloaded {len(records)} state historical records.")
        return records
    except Exception as e:
        print(f"❌ Critical Error: Failed to pull state crime database ({e})")
        return []

def main():
    print("🚀 Initializing Washington State Crime Data Pipeline...")
    
    if not os.path.exists(CSV_PATH):
        print(f"❌ Error: Required master spreadsheet missing at {CSV_PATH}")
        return
        
    df = clean_and_load_csv(CSV_PATH)
    state_records = fetch_wa_state_crime_data()
    
    if not state_records:
        print("❌ Aborting build: State crime reference table is completely empty.")
        return

    # Determine the latest available reporting year present in the dataset dynamically
    all_years = [int(r.get("indexyear", 0)) for r in state_records if r.get("indexyear")]
    latest_year = str(max(all_years)) if all_years else "2024"
    print(f"📊 Filtering reference data for the newest reporting year cycle: {latest_year}")
    
    # Filter records to only operate on the latest reporting window
    current_year_records = [r for r in state_records if str(r.get("indexyear")) == latest_year]
    
    crime_registry = {}

    for _, row in df.iterrows():
        city_name = str(row['City']).strip()
        police_dept = str(row['Police Department Name']).strip()
        final_crime_link = str(row['Police Department Crime Page']).strip()
        
        if pd.isna(row['Police Department Crime Page']) or not final_crime_link:
            final_crime_link = "https://www.spotcrime.com"

        # Normalize strings to ensure robust matching loops
        city_clean = city_name.lower().replace("police", "").replace("department", "").replace("pd", "").strip()
        dept_clean = police_dept.lower().replace("police", "").replace("department", "").replace("office", "").replace("pd", "").replace("’s", "").replace("'s", "").strip()

        matched_row = None

        # Pass 1: Direct or substring match on the local city name
        for record in current_year_records:
            loc_name = str(record.get("location", "")).lower()
            loc_clean = loc_name.replace("police", "").replace("department", "").replace("pd", "").strip()
            
            if city_clean == loc_clean or loc_clean == city_clean or f"{city_clean} pd" in loc_name:
                matched_row = record
                break

        # Pass 2: Contract City Check (Fall back to matching the parent agency like King County Sheriff)
        if not matched_row:
            for record in current_year_records:
                loc_name = str(record.get("location", "")).lower().replace("’s", "").replace("'s", "")
                if dept_clean in loc_name or loc_name in dept_clean:
                    matched_row = record
                    break

        # Append matching variables if found
        if matched_row:
            try:
                population = int(matched_row.get("population", 0))
                violent_incidents = int(matched_row.get("vtotal", 0))
                property_incidents = int(matched_row.get("ptotal", 0))

                if population > 0:
                    # Math conversion: (Incidents / Population) * 1000
                    violent_rate = round((violent_incidents / population) * 1000, 2)
                    property_rate = round((property_incidents / population) * 1000, 2)
                else:
                    violent_rate, property_rate = None, None

                print(f"   ✅ Matched {city_name} -> {matched_row.get('location')} (Pop: {population})")
                
                crime_registry[city_name] = {
                    "status": f"Active Reporting ({latest_year})",
                    "police_agency": police_dept,
                    "reported_population": population,
                    "total_violent_crimes": violent_incidents,
                    "per_capita_violent_rate": violent_rate,
                    "total_property_crimes": property_incidents,
                    "per_capita_property_rate": property_rate,
                    "granular_crime_link": final_crime_link
                }
            except Exception as parse_error:
                print(f"   ⚠️ Parsing breakdown for {city_name}: {parse_error}")
                matched_row = None

        if not matched_row:
            print(f"   ⚠️ No historical logs returned for {city_name}. Mapping fallback link.")
            crime_registry[city_name] = {
                "status": "No Historical Data Reported",
                "police_agency": police_dept,
                "reported_population": None,
                "total_violent_crimes": None,
                "per_capita_violent_rate": None,
                "total_property_crimes": None,
                "per_capita_property_rate": None,
                "granular_crime_link": final_crime_link
            }

    os.makedirs(os.path.dirname(OUTPUT_JSON_PATH), exist_ok=True)
    with open(OUTPUT_JSON_PATH, 'w', encoding="utf-8") as f:
        json.dump(crime_registry, f, indent=2, ensure_ascii=False)
        
    print(f"🏁 Success! Clean data-driven crime profiles compiled to: {OUTPUT_JSON_PATH}")

if __name__ == "__main__":
    main()
