import os
import json
import urllib.request
import urllib.parse
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")

def slugify(text):
    if not text: return ""
    text = str(text).lower().strip()
    out = [ch if ch.isalnum() else '-' for ch in text]
    res = "".join(out)
    while '--' in res: res = res.replace('--', '-')
    return res.strip('-')

def main():
    print("📍 Ingesting Municipal Amenities via OpenStreetMap Overpass Query...")
    if not os.path.exists(CITY_DATA_PATH):
        print("ℹ️ city_data.json missing. Skipping OSM amenities.")
        return

    with open(CITY_DATA_PATH, "r", encoding="utf-8") as f:
        raw_cities = json.load(f)

    items = raw_cities if isinstance(raw_cities, list) else list(raw_cities.values())
    valid_cities = []
    for item in items:
        name = item.get("City") or item.get("name") or ""
        lat = item.get("Latitude") or item.get("lat")
        lon = item.get("Longitude") or item.get("lon")
        if name and lat and lon:
            try:
                valid_cities.append({"slug": slugify(name), "name": name, "lat": float(lat), "lon": float(lon)})
            except Exception: pass

    bbox = "47.0,-122.6,48.2,-121.8"
    overpass_query = f"""[out:json][timeout:60];(nwr["leisure"="dog_park"]({bbox});nwr["amenity"="cafe"]({bbox});nwr["leisure"="park"]({bbox});nwr["natural"="beach"]({bbox});nwr["shop"="pet"]({bbox});nwr["leisure"="golf_course"]({bbox});nwr["craft"="brewery"]({bbox});nwr["amenity"="pub"]({bbox}););out center;"""

    nodes = []
    encoded_query = urllib.parse.quote(overpass_query)
    url = f"https://overpass-api.de/api/interpreter?data={encoded_query}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=50) as resp:
            if resp.status == 200:
                res = json.loads(resp.read().decode("utf-8"))
                nodes = res.get("elements", [])
    except Exception as e:
        print(f"⚠️ Overpass query notice: {e}")

    output = {}
    radius_deg = 0.035
    for city in valid_cities:
        slug = city["slug"]
        clat, clon = city["lat"], city["lon"]
        counts = {"dog_parks": 0, "coffee_shops": 0, "parks": 0, "beaches": 0, "pet_stores": 0, "golf_courses": 0, "breweries_pubs": 0}

        for node in nodes:
            nlat = node.get("lat") or node.get("center", {}).get("lat")
            nlon = node.get("lon") or node.get("center", {}).get("lon")
            if not nlat or not nlon: continue
            try:
                if abs(float(nlat) - clat) <= radius_deg and abs(float(nlon) - clon) <= radius_deg:
                    tags = node.get("tags", {})
                    leisure, amenity, natural, shop, craft = tags.get("leisure"), tags.get("amenity"), tags.get("natural"), tags.get("shop"), tags.get("craft")
                    if leisure == "dog_park": counts["dog_parks"] += 1
                    elif amenity == "cafe": counts["coffee_shops"] += 1
                    elif leisure == "park": counts["parks"] += 1
                    elif natural == "beach": counts["beaches"] += 1
                    elif shop == "pet": counts["pet_stores"] += 1
                    elif leisure == "golf_course": counts["golf_courses"] += 1
                    elif craft == "brewery" or amenity == "pub": counts["breweries_pubs"] += 1
            except Exception: pass

        output[slug] = {"name": city["name"], "amenities": counts, "last_updated": datetime.utcnow().isoformat() + "Z"}

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "city_amenities.json"), "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print("💾 Saved OSM amenities data.")

if __name__ == "__main__":
    main()