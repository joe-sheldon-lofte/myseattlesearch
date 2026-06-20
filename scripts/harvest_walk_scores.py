#!/usr/bin/env python3
"""
Real Estate Platform - Multi-Score Location Harvester
Fetches Walk Score, Transit Score, and Bike Score in a single combined pass.
"""

import os
import json
import csv
import sys
import requests

# Configuration Paths
CSV_PATH = os.path.join("data", "InfoSparks Links - Sheet2.csv")
OUTPUT_PATH = os.path.join("data", "walk_transit_bike_scores.json")
API_ENDPOINT = "https://api.walkscore.com/score"

def main():
    # Grab the API key securely from GitHub Secrets / Env
    api_key = os.environ.get("WALK_SCORE_API_KEY")
    if not api_key:
        print("❌ Critical Error: WALK_SCORE_API_KEY environment variable is not set.")
        sys.exit(1)

    if not os.path.exists(CSV_PATH):
        print(f"❌ Critical Error: Centroid configuration sheet not found at {CSV_PATH}")
        sys.exit(1)

    scores_database = {}

    print("🚀 Initializing Multi-Score Ingestion Engine...")

    with open(CSV_PATH, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            city = row.get("City", "").strip()
            lat = row.get("Latitude", "").strip()
            lng = row.get("Longitude", "").strip()

            if not city or not lat or not lng:
                continue

            # Build parameters enabling both transit and biking arrays explicitly
            params = {
                "format": "json",
                "address": f"{city}, WA",
                "lat": lat,
                "lon": lng,
                "wsapikey": api_key,
                "transit": 1,  # ← Triggers Transit Score lookup
                "bike": 1      # ← Triggers Bike Score lookup
            }

            try:
                response = requests.get(API_ENDPOINT, params=params, timeout=15)
                
                if response.status_code == 403:
                    print(f"⚠️ Server propagation delay: Key not activated yet for {city}. Bailing out.")
                    break
                    
                response.raise_for_status()
                data = response.json()

                # Parse the response dictionary structures safely
                walk_val = data.get("walkscore")
                walk_desc = data.get("description", "No Data")
                
                # Nested objects inside the updated API profile
                transit_data = data.get("transit", {})
                transit_val = transit_data.get("score")
                transit_desc = transit_data.get("description", "No Data")

                bike_data = data.get("bike", {})
                bike_val = bike_data.get("score")
                bike_desc = bike_data.get("description", "No Data")

                scores_database[city] = {
                    "walk_score": walk_val,
                    "walk_description": walk_desc,
                    "transit_score": transit_val,
                    "transit_description": transit_desc,
                    "bike_score": bike_val,
                    "bike_description": bike_desc
                }
                print(f"✅ Synced: {city} [Walk: {walk_val} | Transit: {transit_val} | Bike: {bike_val}]")

            except Exception as e:
                print(f"❌ Processing failure on market '{city}': {e}")
                continue

    # Ensure output targets exist cleanly
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(scores_database, f, indent=2, ensure_ascii=False)

    print(f"🏁 Complete. Centralized lifestyle index built at: {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
