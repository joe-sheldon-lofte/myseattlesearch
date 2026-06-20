import os
import json
import time
from datetime import datetime
import pandas as pd
import requests

# Configuration
CSV_PATH = "data/InfoSparks Links - Sheet2.csv"
OUTPUT_JSON_PATH = "data/walk_scores.json"
# Safely pull your API key from environment variables
WALK_SCORE_API_KEY = os.getenv("WALK_SCORE_API_KEY") 

def fetch_walk_score(lat, lon, city_name):
    """Queries the Walk Score API for a single pair of coordinates."""
    if not WALK_SCORE_API_KEY:
        raise ValueError("Missing WALK_SCORE_API_KEY environment variable.")

    url = "https://api.walkscore.com/score"
    params = {
        "format": "json",
        "lat": lat,
        "lon": lon,
        "wskey": WALK_SCORE_API_KEY
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            # Walk Score API status 1 means successful data retrieval
            if data.get("status") == 1:
                return {
                    "walk_score": data.get("walkscore"),
                    "description": data.get("description"),
                    "link": data.get("ws_link"),
                    "last_updated": datetime.utcnow().isoformat() + "Z"
                }
            else:
                print(f"⚠️ Walk Score API warning for {city_name}: {data.get('more_info_text', 'Unknown issue')}")
        else:
            print(f"❌ HTTP Error {response.status_code} for {city_name}")
    except Exception as e:
        print(f"❌ Request failed for {city_name}: {str(e)}")
        
    return None

def main():
    print("🚀 Starting Sunday Night Walk Score Harvest...")
    
    # 1. Verify files and keys exist
    if not os.path.exists(CSV_PATH):
        print(f"❌ Error: Could not find source file at {CSV_PATH}")
        return
        
    if not WALK_SCORE_API_KEY:
        print("❌ Error: WALK_SCORE_API_KEY environment variable is not set.")
        print("Run: export WALK_SCORE_API_KEY='your_key_here' before running the script.")
        return

    # 2. Read the city matrix
    df = pd.read_csv(CSV_PATH)
    
    if "City" not in df.columns or "Latitude" not in df.columns or "Longitude" not in df.columns:
        print("❌ Error: CSV must contain 'City', 'Latitude', and 'Longitude' columns.")
        return

    # Load existing data if it exists to preserve historical pulls in case an API call fails
    walk_scores_db = {}
    if os.path.exists(OUTPUT_JSON_PATH):
        try:
            with open(OUTPUT_JSON_PATH, "r") as f:
                walk_scores_db = json.load(f)
        except json.JSONDecodeError:
            pass

    # 3. Process each city
    total_cities = len(df)
    for index, row in df.iterrows():
        city = row["City"]
        lat = row["Latitude"]
        lon = row["Longitude"]
        
        # Guard against empty coordinate cells
        if pd.isna(lat) or pd.isna(lon):
            print(f"⏩ Skipping {city}: Missing Latitude or Longitude.")
            continue
            
        print(f"📥 [{index + 1}/{total_cities}] Fetching scores for {city}...")
        
        result = fetch_walk_score(lat, lon, city)
        
        if result:
            walk_scores_db[city] = result
            print(f"✅ Saved {city}: Score {result['walk_score']} ({result['description']})")
        else:
            print(f"⚠️ Keeping stale data (if any) for {city} due to fetch failure.")

        # Polite rate limiting: 1-second pause between requests to respect API boundaries
        time.sleep(1.0)

    # 4. Save the finalized JSON dictionary
    os.makedirs(os.path.dirname(OUTPUT_JSON_PATH), exist_ok=True)
    with open(OUTPUT_JSON_PATH, "w") as f:
        json.dump(walk_scores_db, f, indent=2)
        
    print(f"\n🎉 Success! Static database written to {OUTPUT_JSON_PATH}")

if __name__ == "__main__":
    main()
