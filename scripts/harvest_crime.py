#!/usr/bin/env python3
"""
Real Estate Platform - Live FBI Crime Data Pipeline
Features: Live federal API synchronization, dynamic population extraction, 
          and automated per-capita conversion math.
"""

import os
import json
import io
import time
import requests
import pandas as pd

CSV_PATH = "data/InfoSparks Links - Sheet2.csv"
OUTPUT_JSON_PATH = "data/crime_stats.json"

# Pull the API key dynamically from your system environment variables (secure)
FBI_API_KEY = os.environ.get("FBI_API_KEY")

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

def main():
    print("🚀 Initializing Live Federal Crime Data Pipeline...")
    
    if not FBI_API_KEY:
        print("❌ Error: Missing 'FBI_API_KEY' environment variable.")
        print("💡 Please get a free key from api.data.gov and add it to your environment.")
        return

    if not os.path.exists(CSV_PATH):
        print(f"❌ Error: Required master spreadsheet missing at {CSV_PATH}")
        return
        
    df = clean_and_load_csv(CSV_PATH)
    crime_registry = {}

    for _, row in df.iterrows():
        city_name = str(row['City']).strip()
        ori_code = str(row['FBI ORI']).strip()
        police_dept = str(row['Police Department Name']).strip()
        final_crime_link = str(row['Police Department Crime Page']).strip()
        
        if pd.isna(row['Police Department Crime Page']) or not final_crime_link:
            final_crime_link = "https://www.spotcrime.com"

        # Safe Skip for Unmapped/Pending Regions
        if ori_code.lower() == 'unknown' or pd.isna(row['FBI ORI']) or len(ori_code) < 5:
            print(f"⚠️ Data Pending for {city_name} -> Using fallback link routing.")
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
            continue

        print(f"📥 Querying live FBI NIBRS database for: {city_name} ({ori_code})...")
        
        # Official Federal Crime Estimates Endpoint by Agency ORI
        api_url = f"https://api.usa.gov/crime/fbi/sapi/api/estimates/agencies/{ori_code}?api_key={FBI_API_KEY}"
        
        try:
            response = requests.get(api_url, timeout=20)
            
            # Catch rate limiters or server rejections gracefully
            if response.status_code == 403:
                print(f"   ❌ API Key rejected or unauthorized for {city_name}.")
                continue
                
            response.raise_for_status()
            payload = response.json()
            results = payload.get("results", [])

            if not results:
                print(f"   ⚠️ No historical logs returned by FBI for code {ori_code}.")
                raise ValueError("Empty results payload")

            # Sort the results array to grab the absolute newest reporting year available
            results_sorted = sorted(results, key=lambda x: x.get("year", 0))
            latest_year_data = results_sorted[-1]
            reporting_year = latest_year_data.get("year")

            population = int(latest_year_data.get("population", 0))
            violent_incidents = int(latest_year_data.get("violent_crime", 0))
            property_incidents = int(latest_year_data.get("property_crime", 0))

            if population <= 0:
                print(f"   ⚠️ Population returned as 0 for {city_name}. Skipping rates calculation.")
                raise ValueError("Zero population boundary error")

            # Execute dynamic per-capita math conversions: (Crimes / Pop) * 1,000
            violent_rate = round((violent_incidents / population) * 1000, 2)
            property_rate = round((property_incidents / population) * 1000, 2)

            print(f"   ✅ Data Loaded ({reporting_year}): Pop: {population} | Violent: {violent_incidents}")

            crime_registry[city_name] = {
                "status": f"Active Reporting ({reporting_year})",
                "police_agency": police_dept,
                "reported_population": population,
                "total_violent_crimes": violent_incidents,
                "per_capita_violent_rate": violent_rate,
                "total_property_crimes": property_incidents,
                "per_capita_property_rate": property_rate,
                "granular_crime_link": final_crime_link
            }

        except Exception as e:
            print(f"   ❌ Network/Parsing fault for {city_name}: {e}")
            crime_registry[city_name] = {
                "status": "API Connection Offline",
                "police_agency": police_dept,
                "reported_population": None,
                "total_violent_crimes": None,
                "per_capita_violent_rate": None,
                "total_property_crimes": None,
                "per_capita_property_rate": None,
                "granular_crime_link": final_crime_link
            }

        # Politeness throttle to respect federal network rate limit boundaries
        time.sleep(1.0)

    # Save cleanly structured files back to disk array
    os.makedirs(os.path.dirname(OUTPUT_JSON_PATH), exist_ok=True)
    with open(OUTPUT_JSON_PATH, 'w', encoding="utf-8") as f:
        json.dump(crime_registry, f, indent=2, ensure_ascii=False)
        
    print(f"🏁 Success! Genuine live crime statistics compiled to: {OUTPUT_JSON_PATH}")

if __name__ == "__main__":
    main()
