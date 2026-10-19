# File: scripts/monthly/harvest_businesses.py
import os
import json
import time
import requests
import urllib3
import urllib.parse
from datetime import datetime, timezone

# Suppress unverified HTTPS request warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Robust Repository Root Path Resolution
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(CURRENT_DIR) == "monthly":
    REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
elif os.path.basename(CURRENT_DIR) == "scripts":
    REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
else:
    REPO_ROOT = os.path.abspath(CURRENT_DIR)

DATA_DIR = os.path.join(REPO_ROOT, "data")
CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")
BUSINESSES_PATH = os.path.join(DATA_DIR, "city_businesses.json")

# Mapping of site categories to Google Places API (New) Table A primary types
CATEGORY_TYPES = {
    "coffee": ["coffee_shop", "cafe"],
    "bakeries": ["bakery"],
    "pizza": ["pizza_restaurant"],
    "mexican": ["mexican_restaurant"],
    "seafood": ["seafood_restaurant"],
    "breweries": ["brewery"],
    "thai": ["thai_restaurant"],
    "steak": ["steak_house"]
}

CATEGORY_DISPLAY_FALLBACK = {
    "coffee": "Coffee & Tea",
    "bakeries": "Bakery & Desserts",
    "pizza": "Pizza & Casual",
    "mexican": "Mexican & Cantina",
    "seafood": "Seafood & Grill",
    "breweries": "Brewery & Craft Beer",
    "thai": "Thai Cuisine",
    "steak": "Steakhouse & Grill"
}

PRICE_MAP = {
    "PRICE_LEVEL_FREE": "$",
    "PRICE_LEVEL_INEXPENSIVE": "$", "PRICE_LEVEL_MODERATE": "$$", "PRICE_LEVEL_EXPENSIVE": "$$$", "PRICE_LEVEL_VERY_EXPENSIVE": "$$$$"
}

HEADERS_BASE = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)"
}

def slugify(text):
    if not text:
        return ""
    text = str(text).lower().strip()
    out = [ch if ch.isalnum() else '-' for ch in text]
    res = "".join(out)
    while '--' in res:
        res = res.replace('--', '-')
    return res.strip('-')

def resolve_photo_cdn_url(session, photo_name, api_key):
    """Fetches high-res public CDN URL using skipHttpRedirect so API keys remain private."""
    if not photo_name or not api_key:
        return ""
    url = f"https://places.googleapis.com/v1/{photo_name}/media?maxHeightPx=600&maxWidthPx=800&skipHttpRedirect=true&key={api_key}"
    try:
        res = session.get(url, timeout=6)
        if res.status_code == 200:
            return res.json().get("photoUri", "")
    except Exception:
        pass
    return ""

def search_google_places_nearby(session, lat, lon, place_types, api_key):
    """Executes Places API (New) Nearby Search within an 8km perimeter."""
    url = "https://places.googleapis.com/v1/places:searchNearby"
    headers = {
        **HEADERS_BASE,
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.rating,places.userRatingCount,places.priceLevel,places.googleMapsUri,places.primaryTypeDisplayName,places.photos"
    }
    payload = {
        "includedTypes": place_types,
        "maxResultCount": 10,
        "locationRestriction": {
            "circle": {
                "center": {"latitude": lat, "longitude": lon},
                "radius": 8000.0  # ~5 mile perimeter radius
            }
        }
    }
    try:
        res = session.post(url, headers=headers, json=payload, timeout=12)
        if res.status_code == 200:
            return res.json().get("places", [])
        else:
            print(f"   ⚠️ Google Places notice: HTTP {res.status_code} - {res.text[:120]}")
    except Exception as e:
        print(f"   ⚠️ Places request exception: {e}")
    return []

def main():
    print("🛒 Starting Google Places API Local Business Spotlight Harvester...")
    api_key = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip().strip("'").strip('"')

    if not api_key:
        print("ℹ️ GOOGLE_PLACES_API_KEY missing from environment. Preserving existing city_businesses.json.")
        return

    if not os.path.exists(CITY_DATA_PATH):
        print(f"❌ Error: Required city database `{CITY_DATA_PATH}` not found.")
        return

    with open(CITY_DATA_PATH, "r", encoding="utf-8") as f:
        raw_cities = json.load(f)

    city_items = raw_cities if isinstance(raw_cities, list) else list(raw_cities.values())
    session = requests.Session()
    output = {}

    for c_obj in city_items:
        raw_name = c_obj.get("City") or c_obj.get("name") or ""
        if not raw_name:
            continue
        city_name = str(raw_name).strip()
        slug = slugify(city_name)

        lat = c_obj.get("latitude") or c_obj.get("Latitude")
        lon = c_obj.get("longitude") or c_obj.get("Longitude")
        if lat is None or lon is None:
            continue

        try:
            lat_f = float(str(lat).strip())
            lon_f = float(str(lon).strip())
        except (ValueError, TypeError):
            continue

        print(f"📍 Harvesting spotlights: {city_name}...")
        city_categories = {cat: [] for cat in CATEGORY_TYPES.keys()}
        seen_place_ids = set()
        seen_names = set()

        for cat_key, place_types in CATEGORY_TYPES.items():
            places = search_google_places_nearby(session, lat_f, lon_f, place_types, api_key)
            
            # Sort by rating (primary) and review volume (secondary)
            places.sort(key=lambda p: (float(p.get("rating", 0.0)), int(p.get("userRatingCount", 0))), reverse=True)

            for p in places:
                p_id = p.get("id")
                name = p.get("displayName", {}).get("text", "").strip()
                name_clean = name.lower()

                # Deduplicate within the same municipality
                if not name or p_id in seen_place_ids or name_clean in seen_names:
                    continue

                seen_place_ids.add(p_id)
                seen_names.add(name_clean)

                address = p.get("formattedAddress", f"Downtown {city_name}")
                rating = float(p.get("rating", 4.5))
                reviews = int(p.get("userRatingCount", 0))
                price_level = PRICE_MAP.get(p.get("priceLevel"), "$$")
                display_cat = p.get("primaryTypeDisplayName", {}).get("text") or CATEGORY_DISPLAY_FALLBACK.get(cat_key, "Local Favorite")
                maps_url = p.get("googleMapsUri") or f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(name + ' ' + address)}"

                # Resolve public CDN photo URL if available
                photo_url = ""
                photos = p.get("photos", [])
                if photos and isinstance(photos, list):
                    photo_name = photos[0].get("name")
                    photo_url = resolve_photo_cdn_url(session, photo_name, api_key)

                biz_entry = {
                    "category": display_cat,
                    "name": name,
                    "location": address,
                    "rating": rating,
                    "review_count": reviews,
                    "price_level": price_level,
                    "url": maps_url,
                    "image_url": photo_url,
                    "summary": f"Top-rated spot in {city_name} with {reviews} reviews on Google."
                }

                city_categories[cat_key].append(biz_entry)
                if len(city_categories[cat_key]) >= 5:
                    break

            # Pacing to remain well within Google API rate limits
            time.sleep(0.12)

        output[slug] = {
            "name": city_name,
            "categories": city_categories,
            "last_updated": datetime.now(timezone.utc).isoformat()
        }

    # Anti-wipeout safeguard: abort if less than 40 cities harvested
    if len(output) < 40:
        print(f"❌ Safety check failed: Only {len(output)} cities harvested. Preserving existing {BUSINESSES_PATH}.")
        return

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(BUSINESSES_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"💾 Saved Google Places business spotlights for {len(output)} cities ➔ {BUSINESSES_PATH}")

if __name__ == "__main__":
    main()