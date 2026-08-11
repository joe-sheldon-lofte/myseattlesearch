import os
import json
import time
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")
OUT_PATH = os.path.join(DATA_DIR, "walk_transit_bike_scores.json")

def main():
    print("🚶 Polling Walk Score API for all cities in dataset...")
    os.makedirs(DATA_DIR, exist_ok=True)

    ws_key = os.environ.get("WALK_SCORE_API_KEY")
    if not ws_key:
        print("ℹ️ WALK_SCORE_API_KEY not configured in secrets. Skipping Walk Score harvest.")
        return

    if not os.path.exists(CITY_DATA_PATH):
        print("ℹ️ city_data.json not found. Skipping Walk Score harvest.")
        return

    try:
        with open(CITY_DATA_PATH, "r", encoding="utf-8") as f:
            raw_cities = json.load(f)
    except Exception as e:
        print(f"⚠️ Failed to read city_data.json: {e}")
        return

    city_items = raw_cities if isinstance(raw_cities, list) else list(raw_cities.values())
    scores_data = {}
    if os.path.exists(OUT_PATH):
        try:
            with open(OUT_PATH, "r", encoding="utf-8") as f:
                scores_data = json.load(f)
        except Exception:
            scores_data = {}

    fetched_count = 0
    for item in city_items:
        city_name = str(item.get("City") or item.get("name") or "").strip()
        if not city_name:
            continue

        lat = item.get("Latitude") or item.get("lat") or item.get("latitude")
        lon = item.get("Longitude") or item.get("lon") or item.get("lng") or item.get("longitude")
        if not lat or not lon:
            continue

        try:
            lat_val, lon_val = float(lat), float(lon)
        except (ValueError, TypeError):
            continue

        url = f"https://api.walkscore.com/score?format=json&transit=1&bike=1&lat={lat_val}&lon={lon_val}&wsapikey={ws_key}"
        try:
            res = requests.get(url, timeout=10)
            if res.status_code == 200:
                scores_data[city_name] = res.json()
                fetched_count += 1
            else:
                print(f"   ⚠️ WalkScore HTTP {res.status_code} for {city_name}")
        except Exception as e:
            print(f"   ⚠️ WalkScore fetch failed for {city_name}: {e}")

        time.sleep(0.25)

    if scores_data:
        with open(OUT_PATH, "w", encoding="utf-8") as f:
            json.dump(scores_data, f, indent=2, ensure_ascii=False)
        print(f"💾 Updated Walk, Transit & Bike Scores for {fetched_count} cities.")

if __name__ == "__main__":
    main()