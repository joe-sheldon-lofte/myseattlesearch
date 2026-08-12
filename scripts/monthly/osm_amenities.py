import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")
OUT_PATH = os.path.join(DATA_DIR, "city_amenities.json")

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter"
]

def slugify(text):
    if not text: return ""
    text = str(text).lower().strip()
    out = [ch if ch.isalnum() else '-' for ch in text]
    res = "".join(out)
    while '--' in res: res = res.replace('--', '-')
    return res.strip('-')

def fetch_overpass_post(query):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept": "*/*"
    }
    data_encoded = urllib.parse.urlencode({"data": query}).encode("utf-8")

    for ep in OVERPASS_ENDPOINTS:
        try:
            req = urllib.request.Request(ep, data=data_encoded, headers=headers)
            with urllib.request.urlopen(req, timeout=45) as resp:
                if resp.status == 200:
                    raw = resp.read().decode("utf-8")
                    return json.loads(raw)
        except Exception as e:
            print(f"   ⚠️ Overpass mirror notice [{ep}]: {e}")
    return None

def main():
    print("📍 Ingesting Municipal Amenities via OpenStreetMap Overpass Query...")
    if not os.path.exists(CITY_DATA_PATH):
        print("ℹ️ city_data.json missing. Skipping OSM amenities.")
        return

    with open(CITY_DATA_PATH, "r", encoding="utf-8") as f:
        raw_cities = json.load(f)

    items = raw_cities if isinstance(raw_cities, list) else list(raw_cities.values())
    valid_cities = []
    for it in items:
        name = it.get("City") or it.get("name") or ""
        lat = it.get("Latitude") or it.get("lat") or it.get("latitude")
        lon = it.get("Longitude") or it.get("lon") or it.get("lng") or it.get("longitude")
        if name and lat and lon:
            try:
                valid_cities.append({"slug": slugify(name), "name": str(name).strip(), "lat": float(lat), "lon": float(lon)})
            except (ValueError, TypeError):
                pass

    if not valid_cities:
        print("ℹ️ No valid city GPS coordinates found in city_data.json.")
        return

    bbox = "47.0,-122.6,48.2,-121.8"
    overpass_query = f"""[out:json][timeout:60];(nwr["leisure"="dog_park"]({bbox});nwr["amenity"="cafe"]({bbox});nwr["leisure"="park"]({bbox});nwr["natural"="beach"]({bbox});nwr["shop"="pet"]({bbox});nwr["leisure"="golf_course"]({bbox});nwr["craft"="brewery"]({bbox});nwr["amenity"="pub"]({bbox});nwr["craft"="winery"]({bbox});nwr["shop"="wine"]({bbox}););out center;"""

    res = fetch_overpass_post(overpass_query)
    if not res or not isinstance(res, dict) or "elements" not in res:
        print("⚠️ Unable to retrieve Overpass nodes. Preserving existing amenities dataset.")
        return

    nodes = res["elements"]
    print(f"   ✅ Ingested {len(nodes)} amenity nodes from OpenStreetMap.")

    output = {}
    radius_deg = 0.035

    for city in valid_cities:
        slug = city["slug"]
        clat, clon = city["lat"], city["lon"]

        counts = {
            "dog_parks": 0, "coffee_shops": 0, "parks": 0, "beaches": 0,
            "pet_stores": 0, "golf_courses": 0, "breweries_pubs": 0, "wineries_wine_shops": 0
        }

        for node in nodes:
            nlat = node.get("lat") or node.get("center", {}).get("lat")
            nlon = node.get("lon") or node.get("center", {}).get("lon")
            try:
                nlat, nlon = float(nlat), float(nlon)
            except (ValueError, TypeError):
                continue

            if abs(nlat - clat) <= radius_deg and abs(nlon - clon) <= radius_deg:
                tags = node.get("tags", {})
                leisure, amenity, natural = tags.get("leisure"), tags.get("amenity"), tags.get("natural")
                shop, craft = tags.get("shop"), tags.get("craft")

                if leisure == "dog_park": counts["dog_parks"] += 1
                elif amenity == "cafe": counts["coffee_shops"] += 1
                elif leisure == "park": counts["parks"] += 1
                elif natural == "beach": counts["beaches"] += 1
                elif shop == "pet": counts["pet_stores"] += 1
                elif leisure == "golf_course": counts["golf_courses"] += 1
                elif craft == "brewery" or amenity == "pub": counts["breweries_pubs"] += 1
                elif craft == "winery" or shop == "wine": counts["wineries_wine_shops"] += 1

        output[slug] = {
            "name": city["name"],
            "amenities": counts,
            "last_updated": datetime.now(timezone.utc).isoformat()
        }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"💾 Saved OSM amenities data for {len(output)} cities to {OUT_PATH}")

if __name__ == "__main__":
    main()