#!/usr/bin/env python3
"""
Real Estate Platform - Multi-Score Location Harvester
Fetches Walk Score, Transit Score, and Bike Score while maintaining original schema.
"""

import os
import json
import csv
import sys
from datetime import datetime, timezone
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

    print("🚀 Initializing Retrofitted Multi-Score Ingestion Engine...")

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
                "transit": 1,
                "bike": 1
            }

            try:
                response = requests.get(API_ENDPOINT, params=params, timeout=15)
                
                if response.status_code == 403:
                    print(f"⚠️ Server propagation delay: Key not activated yet for {city}. Bailing out.")
                    break
                    
                response.raise_for_status()
                data = response.json()

                # Generate the exact high-fidelity timestamp string requested
                timestamp = datetime.now(timezone.utc).isoformat(timespec='microseconds').replace("+00:00", "Z")
                
                # Reconstruct the original deep-link URL pattern
                deep_link = f"https://www.walkscore.com/score/loc/lat={lat}/lon={lng}"

                # Extract nested data payloads safely
                transit_data = data.get("transit", {})
                bike_data = data.get("bike", {})

                # Merge the new values directly into your original data structure layout
                scores_database[city] = {
                    "walk_score": data.get("walkscore"),
                    "description": data.get("description", "No Data"),  # Keeps backward compatibility
                    "transit_score": transit_data.get("score"),
                    "transit_description": transit_data.get("description", "No Data"),
                    "bike_score": bike_data.get("score"),
                    "bike_description": bike_data.get("description", "No Data"),
                    "link": deep_link,
                    "last_updated": timestamp
                }
                
                print(f"✅ Synced: {city} [W: {data.get('walkscore')} | T: {transit_data.get('score')} | B: {bike_data.get('score')}]")

            except Exception as e:
                print(f"❌ Processing failure on market '{city}': {e}")
                continue

    # Ensure output targets exist cleanly
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(scores_database, f, indent=2, ensure_ascii=False)

    print(f"🏁 Complete. Retrofitted lifestyle database built at: {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
