import os
import json
import time
import urllib.request
import urllib.parse
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")
BUSINESSES_PATH = os.path.join(DATA_DIR, "city_businesses.json")

def slugify(text):
    if not text: return ""
    text = str(text).lower().strip()
    out = [ch if ch.isalnum() else '-' for ch in text]
    res = "".join(out)
    while '--' in res: res = res.replace('--', '-')
    return res.strip('-')

def http_get_json_simple(url, extra_headers=None, timeout=15):
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    if extra_headers: headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"   ⚠️ Yelp GET notice: {e}")
    return None

def main():
    print("🛒 Ingesting Yelp Fusion Local Business Spotlights...")
    yelp_key = os.environ.get("YELP_API_KEY", "").strip().strip("'").strip('"')
    if not yelp_key or not os.path.exists(CITY_DATA_PATH):
        print("ℹ️ YELP_API_KEY missing or city_data.json not found. Preserving local businesses.")
        return

    with open(CITY_DATA_PATH, "r", encoding="utf-8") as f:
        raw_cities = json.load(f)

    city_items = raw_cities if isinstance(raw_cities, list) else list(raw_cities.values())
    TARGET_CATEGORIES = ["coffee", "bakeries", "pizza", "mexican", "seafood", "breweries", "thai", "steak"]
    headers = {"Authorization": f"Bearer {yelp_key}"}
    output = {}

    for c_obj in city_items:
        raw_name = c_obj.get("City") or c_obj.get("name") or ""
        if not raw_name: continue
        city_name = str(raw_name).strip()
        slug = slugify(city_name)

        city_categories = {cat: [] for cat in TARGET_CATEGORIES}
        batch_str = ",".join(TARGET_CATEGORIES)
        encoded_location = urllib.parse.quote(f"{city_name}, WA")
        yelp_url = f"https://api.yelp.com/v3/businesses/search?location={encoded_location}&categories={batch_str}&sort_by=rating&limit=50"

        res = http_get_json_simple(yelp_url, extra_headers=headers)
        if res and isinstance(res, dict) and "businesses" in res:
            for b in res.get("businesses", []):
                cat_titles = [c.get("title") for c in b.get("categories", []) if c.get("title")]
                category_display = ", ".join(cat_titles[:2]) if cat_titles else "Local Favorite"
                loc = b.get("location", {})
                address = loc.get("address1") or f"Downtown {city_name}"

                biz_spotlight = {
                    "category": category_display,
                    "name": b.get("name"),
                    "location": address,
                    "rating": b.get("rating", 4.5),
                    "review_count": b.get("review_count", 0),
                    "price_level": b.get("price", "$$"),
                    "summary": f"Top-rated spot in {city_name} with {b.get('review_count', 0)} reviews."
                }
                for c_alias in [c.get("alias") for c in b.get("categories", [])]:
                    if c_alias in city_categories:
                        city_categories[c_alias].append(biz_spotlight)

        processed_categories = {
            cat: sorted(biz_list, key=lambda x: (x["rating"], x["review_count"]), reverse=True)[:3]
            for cat, biz_list in city_categories.items()
        }

        output[slug] = {
            "name": city_name,
            "categories": processed_categories,
            "last_updated": datetime.utcnow().isoformat() + "Z"
        }
        time.sleep(0.15)

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(BUSINESSES_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"💾 Saved Yelp business spotlights for {len(output)} cities.")

if __name__ == "__main__":
    main()