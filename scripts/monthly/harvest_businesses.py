# File: scripts/monthly/harvest_businesses.py
import os
import sys
import io
import json
import time
import requests
import urllib3
import urllib.parse
from datetime import datetime, timezone
from PIL import Image
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
    "PRICE_LEVEL_INEXPENSIVE": "$",
    "PRICE_LEVEL_MODERATE": "$$",
    "PRICE_LEVEL_EXPENSIVE": "$$$",
    "PRICE_LEVEL_VERY_EXPENSIVE": "$$$$"
}

HEADERS_BASE = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)"
}


def load_local_env():
    for env_file in [".env", ".dev.vars"]:
        env_path = os.path.join(REPO_ROOT, env_file)
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        k = k.strip()
                        if k and k not in os.environ:
                            os.environ[k] = v.strip().strip("\"'")
            except Exception:
                pass


def slugify(text):
    if not text:
        return ""
    text = str(text).lower().strip()
    out = [ch if ch.isalnum() else "-" for ch in text]
    res = "".join(out)
    while "--" in res:
        res = res.replace("--", "-")
    return res.strip("-")


def get_r2_client():
    account_id = (os.environ.get("CF_MASTER_ACCOUNT_ID") or "").strip()
    access_key = (os.environ.get("CF_MASTER_ACCESS_KEY_ID") or "").strip()
    secret_key = (os.environ.get("CF_MASTER_SECRET_ACCESS_KEY") or "").strip()
    endpoint_url = (
        os.environ.get("CF_MASTER_S3_API_ENDPOINT")
        or (f"https://{account_id}.r2.cloudflarestorage.com" if account_id else "")
    ).strip()

    if not all([endpoint_url, access_key, secret_key]):
        return None

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
        config=Config(signature_version="s3v4")
    )


def r2_object_exists(r2_client, bucket_name, key):
    try:
        r2_client.head_object(Bucket=bucket_name, Key=key)
        return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey"):
            return False
        return False
    except Exception:
        return False


def ingest_place_photo_to_r2(session, photo_name, place_id, api_key, r2_client, assets_bucket, force_refresh=False):
    """Downloads Google Places photo server-side, converts to WebP, and stores in R2 assets bucket."""
    if not place_id:
        return ""

    safe_id = slugify(place_id)
    r2_key = f"businessimages/{safe_id}.webp"
    public_url = f"https://assets.myseattlesearch.com/{r2_key}"

    if r2_client and not force_refresh and r2_object_exists(r2_client, assets_bucket, r2_key):
        return public_url

    if not photo_name or not api_key or not r2_client:
        return ""

    meta_url = f"https://places.googleapis.com/v1/{photo_name}/media?maxHeightPx=600&maxWidthPx=800&skipHttpRedirect=true&key={api_key}"
    try:
        meta_res = session.get(meta_url, timeout=8)
        if meta_res.status_code != 200:
            return ""
        cdn_uri = meta_res.json().get("photoUri", "")
        if not cdn_uri:
            return ""

        img_res = session.get(cdn_uri, headers={"User-Agent": HEADERS_BASE["User-Agent"]}, timeout=12)
        img_res.raise_for_status()

        img = Image.open(io.BytesIO(img_res.content))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.thumbnail((800, 800), Image.Resampling.LANCZOS)

        webp_buffer = io.BytesIO()
        img.save(webp_buffer, format="WEBP", quality=80, method=6)
        webp_buffer.seek(0)

        r2_client.upload_fileobj(
            webp_buffer,
            assets_bucket,
            r2_key,
            ExtraArgs={"ContentType": "image/webp"}
        )
        return public_url
    except Exception as e:
        print(f"   ⚠️ R2 photo ingestion failed for {place_id}: {e}")
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
                "radius": 8000.0
            }
        }
    }
    try:
        res = session.post(url, headers=headers, json=payload, timeout=12)
        if res.status_code == 200:
            return res.json().get("places", [])
        print(f"   ⚠️ Google Places notice: HTTP {res.status_code} - {res.text[:120]}")
    except Exception as e:
        print(f"   ⚠️ Places request exception: {e}")
    return []


def main():
    print("🛒 Starting Google Places API Local Business Spotlight Harvester...")
    load_local_env()

    force_refresh = "--force-refresh" in sys.argv
    api_key = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip().strip("'").strip('"')
    assets_bucket = (os.environ.get("R2_BUCKET_NAME") or "myseattlesearch-assets").strip()
    r2_client = get_r2_client()

    if not api_key:
        print("ℹ️ GOOGLE_PLACES_API_KEY missing from environment. Preserving existing city_businesses.json.")
        return

    if not r2_client:
        print("⚠️ R2 credentials missing from environment. Photos will be skipped to prevent expiring Google links.")

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
            places.sort(key=lambda p: (float(p.get("rating", 0.0)), int(p.get("userRatingCount", 0))), reverse=True)

            for p in places:
                p_id = p.get("id")
                name = p.get("displayName", {}).get("text", "").strip()
                name_clean = name.lower()

                if not name or not p_id or p_id in seen_place_ids or name_clean in seen_names:
                    continue

                seen_place_ids.add(p_id)
                seen_names.add(name_clean)

                address = p.get("formattedAddress", f"Downtown {city_name}")
                rating = float(p.get("rating", 4.5))
                reviews = int(p.get("userRatingCount", 0))
                price_level = PRICE_MAP.get(p.get("priceLevel"), "$$")
                display_cat = p.get("primaryTypeDisplayName", {}).get("text") or CATEGORY_DISPLAY_FALLBACK.get(cat_key, "Local Favorite")
                maps_url = p.get("googleMapsUri") or f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(name + ' ' + address)}"

                photo_url = ""
                photos = p.get("photos", [])
                if photos and isinstance(photos, list):
                    photo_name = photos[0].get("name")
                    photo_url = ingest_place_photo_to_r2(
                        session,
                        photo_name,
                        p_id,
                        api_key,
                        r2_client,
                        assets_bucket,
                        force_refresh=force_refresh
                    )

                city_categories[cat_key].append({
                    "place_id": p_id,
                    "category": display_cat,
                    "name": name,
                    "location": address,
                    "rating": rating,
                    "review_count": reviews,
                    "price_level": price_level,
                    "url": maps_url,
                    "image_url": photo_url,
                    "summary": f"Top-rated spot in {city_name} with {reviews} reviews on Google."
                })
                if len(city_categories[cat_key]) >= 5:
                    break

            time.sleep(0.12)

        output[slug] = {
            "name": city_name,
            "categories": city_categories,
            "last_updated": datetime.now(timezone.utc).isoformat()
        }

    if len(output) < 40:
        print(f"❌ Safety check failed: Only {len(output)} cities harvested. Preserving existing {BUSINESSES_PATH}.")
        return

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(BUSINESSES_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"💾 Saved Google Places business spotlights for {len(output)} cities ➔ {BUSINESSES_PATH}")


if __name__ == "__main__":
    main()
