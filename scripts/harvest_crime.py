#!/usr/bin/env python3
"""
Real Estate Platform - Washington State NIBRS Crime Data Pipeline
Features: Direct connection to modern data.wa.gov NIBRS repository (vvfu-ry7f),
          forgiving alphanumeric token matching for contract cities,
          and transparent automated calculation of per-capita metrics.
"""

import os
import json
import io
import requests
import pandas as pd

CSV_PATH = "data/InfoSparks Links - Sheet2.csv"
OUTPUT_JSON_PATH = "data/crime_stats.json"

# Modern Washington State NIBRS dataset (Covers all agencies up to recent years)
WA_STATE_NIBRS_URL = "https://data.wa.gov/resource/vvfu-ry7f.json?$limit=50000"

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

def fetch_wa_nibrs_data():
    """Downloads the entire state-level modern NIBRS matrix in a single step."""
    print("📡 Syncing official NIBRS crime ledger from data.wa.gov portals...")
    headers = {"User-Agent": "PugetSoundRealEstateCrimeIndexer/2.0"}
    try:
        response = requests.get(WA_STATE_NIBRS_URL, headers=headers, timeout=30)
        response.raise_for_status()
        records = response.json()
        print(f"✅ Successfully downloaded {len(records)} state NIBRS historical records.")
        return records
    except Exception as e:
        print(f"❌ Critical Error: Failed to pull state NIBRS database ({e})")
        return []

def normalize_string(text):
    """Strips all common boilerplate, spaces, and punctuation to match strings cleanly."""
    if not text or pd.isna(text):
        return ""
    text = str(text).lower()
    # Remove common words that muck up cross-database text alignment
    for word in ["police", "department", "office", "sheriff", "pd", "so", "county", "’s", "'s", "city", "of"]:
        text = text.replace(word, "")
    # Return only alphanumeric characters
    return "".join(c for c in text if c.isalnum()).strip()

def main():
    print("🚀 Initializing Washington State NIBRS Crime Data Pipeline...")
    
    if not os.path.exists(CSV_PATH):
        print(f"❌ Error: Required master spreadsheet missing at {CSV_PATH}")
        return
        
    df = clean_and_load_csv(CSV_PATH)
    state_records = fetch_wa_nibrs_data()
    
    if not state_records:
        print("❌ Aborting build: State crime reference table is completely empty.")
        return

    # Extract the absolute newest year available in this modern NIBRS set
    all_years = [int(r.get("indexyear", 0)) for r in state_records if r.get("indexyear")]
    if not all_years:
        print("❌ Aborting build: No valid reporting years detected in NIBRS payload.")
        return
        
    latest_year = str(max(all_years))
    print(f"📊 Filtering modern reference data for the newest reporting cycle: {latest_year}")
    
    # Isolate records for the newest reporting cycle
    current_year_records = [r for r in state_records if str(r.get("indexyear")) == latest_year]
    
    crime_registry = {}

    for _, row in df.iterrows():
        city_name = str(row['City']).strip()
        police_dept = str(row['Police Department Name']).strip()
        final_crime_link = str(row['Police Department Crime Page']).strip()
        
        if pd.isna(row['Police Department Crime Page']) or not final_crime_link:
            final_crime_link = "https://www.spotcrime.com"

        # Normalize our spreadsheet text values
        city_norm = normalize_string(city_name)
        dept_norm = normalize_string(police_dept)

        matched_row = None

        # Pass 1: Direct alphanumeric match on the specific City Name
        for record in current_year_records:
            loc_norm = normalize_string(record.get("location", ""))
            if city_norm == loc_norm or loc_norm == city_norm:
                matched_row = record
                break

        # Pass 2: Substring verification (e.g., "Auburn" matching "Auburn Police Department")
        if not matched_row:
            for record in current_year_records:
                loc_norm = normalize_string(record.get("location", ""))
                if city_norm in loc_norm or loc_norm in city_norm:
                    matched_row = record
                    break

        # Pass 3: Contract City Fallback (Match via the parent department name row)
        if not matched_row:
            for record in current_year_records:
                loc_norm = normalize_string(record.get("location", ""))
                if dept_norm == loc_norm or loc_norm == dept_norm or dept_norm in loc_norm:
                    matched_row = record
                    break

        # If a match is verified, parse the modern NIBRS columns cleanly
        if matched_row:
            try:
                population = int(matched_row.get("population", 0))
                # NIBRS uses prsntotal (Crimes Against Persons) and prprtytotal (Crimes Against Property)
                violent_incidents = int(matched_row.get("prsntotal", 0))
                property_incidents = int(matched_row.get("prprtytotal", 0))

                if population > 0:
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

    # Save output payload back down to disk
    os.makedirs(os.path.dirname(OUTPUT_JSON_PATH), exist_ok=True)
    with open(OUTPUT_JSON_PATH, 'w', encoding="utf-8") as f:
        json.dump(crime_registry, f, indent=2, ensure_ascii=False)
        
    print(f"🏁 Success! Clean data-driven crime profiles compiled to: {OUTPUT_JSON_PATH}")

if __name__ == "__main__":
    main()
