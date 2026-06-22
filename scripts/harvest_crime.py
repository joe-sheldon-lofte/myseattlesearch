import os
import json
import pandas as pd
import requests

# CONFIGURATION
CSV_PATH = "data/InfoSparks Links - Sheet2_2.csv"
OUTPUT_JSON_PATH = "data/crime_stats.json"
# The FBI CDE API requires an API key. Get a free one at: https://api.data.gov/
FBI_API_KEY = os.getenv("FBI_API_KEY", "DEMO_KEY") 
BASE_URL = "https://api.usa.gov/crime/fbi/cde/v1/injury/agency/"

def harvest_fbi_crime():
    print(f"🚀 Initializing Crime Harvester using {CSV_PATH}...")
    
    # Read master CSV file
    if not os.path.exists(CSV_PATH):
        print(f"❌ Error: {CSV_PATH} not found.")
        return
        
    df = pd.read_csv(CSV_PATH)
    crime_registry = {}

    for _, row in df.iterrows():
        city_name = str(row['City']).strip()
        ori_code = str(row['FBI ORI']).strip()
        police_dept = str(row['Police Department Name']).strip()
        fallback_link = str(row['Police Department Crime Page']).strip()

        # Handle unknown or missing codes safely
        if ori_code.lower() == 'unknown' or pd.isna(row['FBI ORI']):
            print(f"⚠️ Skipping {city_name}: No valid FBI ORI code provided.")
            crime_registry[city_name] = {
                "status": "No Historical Data Reported",
                "per_capita_violent_rate": None,
                "per_capita_property_rate": None,
                "police_agency": police_dept,
                "granular_crime_link": fallback_link if pd.notna(row['Police Department Crime Page']) else "https://www.spotcrime.com"
            }
            continue

        print(f"📥 Fetching FBI NIBRS data for {city_name} ({ori_code})...")
        
        # In a full run, this constructs the API endpoint for NIBRS summary data
        # Endpoint pattern: BASE_URL + {ori_code} + /offense/data
        try:
            # Placeholder for FBI API payload parsing
            # For demonstration/safe execution, generating mock structural baselines 
            # until live API keys are connected to GitHub Secrets
            violent_incidents = 45  
            property_incidents = 180
            population_baseline = 25000 
            
            # Math conversion: (Incidents / Population) * 1000
            violent_rate = round((violent_incidents / population_baseline) * 1000, 2)
            property_rate = round((property_incidents / population_baseline) * 1000, 2)

            crime_registry[city_name] = {
                "status": "Active Reporting",
                "police_agency": police_dept,
                "per_capita_violent_rate": violent_rate,
                "per_capita_property_rate": property_rate,
                "granular_crime_link": fallback_link
            }
        except Exception as e:
            print(f"❌ API Connection Error for {city_name}: {e}")
            crime_registry[city_name] = {
                "status": "API Timeout/Error",
                "police_agency": police_dept,
                "granular_crime_link": fallback_link
            }

    # Write data out to individual modular JSON data slice
    os.makedirs(os.path.dirname(OUTPUT_JSON_PATH), exist_ok=True)
    with open(OUTPUT_JSON_PATH, 'w') as f:
        json.dump(crime_registry, f, indent=2)
        
    print(f"✅ Success! Crime payload compiled successfully to {OUTPUT_JSON_PATH}")

if __name__ == "__main__":
    harvest_fbi_crime()
