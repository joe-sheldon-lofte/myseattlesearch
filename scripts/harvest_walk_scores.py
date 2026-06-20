import os
import json
import time
from datetime import datetime
import pandas as pd
import requests

# Configuration
CSV_PATH = "data/InfoSparks Links - Sheet2.csv"
OUTPUT_JSON_PATH = "data/walk_scores.json"
WALK_SCORE_API_KEY = os.getenv("WALK_SCORE_API_KEY") 

def fetch_walk_score(lat, lon, city_name):
    """Queries the Walk Score API for a single pair of coordinates."""
    if not WALK_SCORE_API_KEY:
        raise ValueError("Missing WALK_SCORE_API_KEY environment variable.")

    url = "https://api.walkscore.com/score"
    
    # Pack parameters, including the highly recommended 'address' field
    params = {
        "format": "json",
        "address": f"{city_name}, WA", 
        "lat": lat,
        "lon": lon,
        "wskey": WALK_SCORE_API_KEY
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            
            # Status 1 is Walk Score's official code for a successful data payload
            if data.get("status") == 1:
                return {
                    "walk_score": data.get("walkscore"),
                    "description": data.get("description"),
                    "link": data.get("ws_link"),
                    "last_updated": datetime.utcnow().isoformat() + "Z"
                }
            else:
                # Upgraded to print the complete raw response payload for debugging
                print(f"⚠️ Walk Score API rejected {city_name}. Raw Response: {data}")
        else:
            print(f"❌ HTTP Error {response.status_code} for {city_name}")
    except Exception as e:
        print(f"❌ Request failed for {city_name}: {str(e)}")
        
    return None

def main():
    print("🚀 Starting Sunday Night Walk Score Harvest...")
    
    if not os.path.exists(CSV_PATH):
        print(f"❌ Error: Could not find source file at {CSV_PATH}")
        return
        
    if not WALK_SCORE_API_KEY:
        print("❌ Error: WALK_SCORE_API_KEY environment variable is not set.")
        return

    df = pd.read_csv(CSV_PATH)
    
    if "City" not in df.columns or "Latitude" not in df.columns or "Longitude" not in df.columns:
        print("❌ Error: CSV must contain 'City', 'Latitude', and 'Longitude' columns.")
        return

    walk_scores_db = {}
    if os.path.exists(OUTPUT_JSON_PATH):
        try:
            with open(OUTPUT_JSON_PATH, "r") as f:
                walk_scores_db = json.load(f)
        except json.JSONDecodeError:
            pass

    total_cities = len(df)
    for index, row in df.iterrows():
        city = row["City"]
        lat = row["Latitude"]
        lon = row["Longitude"]
        
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

        # Polite 1-second delay
        time.sleep(1.0)

    os.makedirs(os.path.dirname(OUTPUT_JSON_PATH), exist_ok=True)
    with open(OUTPUT_JSON_PATH, "w") as f:
        json.dump(walk_scores_db, f, indent=2)
        
    print(f"\n🎉 Process finished. Static database written to {OUTPUT_JSON_PATH}")

if __name__ == "__main__":
    main()
