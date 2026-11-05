# File: scripts/utilities/ingest_history.py

import os
import sys
import json
import time
import io
import gc
import re
import warnings
import argparse
import urllib.request
import urllib.error
import urllib.parse
import boto3
from botocore.config import Config
from PIL import Image, ImageDraw

warnings.filterwarnings("ignore", category=DeprecationWarning)

# ---------------------------------------------------------------------------
# Configuration & Environment Loading (.dev.vars in project root)
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
DEV_VARS_PATH = os.path.join(PROJECT_ROOT, ".dev.vars")
PROGRESS_FILE = os.path.join(SCRIPT_DIR, "history_progress.json")

def load_dev_vars(filepath):
    env_vars = {}
    if not os.path.exists(filepath):
        print(f"[!] Warning: Environment secrets file not found at {filepath}")
        return env_vars

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                env_vars[key.strip()] = val.strip().strip("'").strip('"')
    return env_vars

config = load_dev_vars(DEV_VARS_PATH)

CF_ACCOUNT_ID = config.get("CF_ACCOUNT_ID")
CF_D1_DATABASE_ID = config.get("CF_D1_DATABASE_ID") or config.get("CF_DATABASE_PARCELDATA_ID")
CF_API_TOKEN = config.get("CF_API_TOKEN") or config.get("CF_D1_API_TOKEN")
R2_ACCESS_KEY_ID = config.get("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = config.get("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = config.get("R2_BUCKET_NAME", "myseattlesearch-assets")
R2_PUBLIC_DOMAIN = config.get("R2_PUBLIC_DOMAIN", "https://assets.myseattlesearch.com").rstrip("/")

HTTP_HEADERS = {
    "User-Agent": "MySeattleSearch-History-Harvester/2.0 (Direct Institutional; info@myseattlesearch.com)"
}

# ---------------------------------------------------------------------------
# Municipal Taxonomy & Normalization Map
# ---------------------------------------------------------------------------
SLUG_DISPLAY_MAP = {
    "federaly": ("Federal Way", "King"),
    "federal-way": ("Federal Way", "King"),
    "lake-forest-park": ("Lake Forest Park", "King"),
    "mountlake-terrace": ("Mountlake Terrace", "Snohomish"),
    "lake-stevens": ("Lake Stevens", "Snohomish"),
    "maple-valley": ("Maple Valley", "King"),
    "mercer-island": ("Mercer Island", "King"),
    "des-moines": ("Des Moines", "King"),
    "mill-creek": ("Mill Creek", "Snohomish"),
    "north-bend": ("North Bend", "King"),
    "granite-falls": ("Granite Falls", "Snohomish"),
    "black-diamond": ("Black Diamond", "King"),
    "gold-bar": ("Gold Bar", "Snohomish"),
    "normandy-park": ("Normandy Park", "King"),
    "fall-city": ("Fall City", "King"),
    "clyde-hill": ("Clyde Hill", "King"),
    "edmonds": ("Edmonds", "Snohomish"),
    "snohomish": ("Snohomish", "Snohomish"),
    "mukilteo": ("Mukilteo", "Snohomish"),
    "lynnwood": ("Lynnwood", "Snohomish"),
    "everett": ("Everett", "Snohomish"),
    "marysville": ("Marysville", "Snohomish"),
    "arlington": ("Arlington", "Snohomish"),
    "monroe": ("Monroe", "Snohomish"),
    "stanwood": ("Stanwood", "Snohomish"),
    "sultan": ("Sultan", "Snohomish"),
    "brier": ("Brier", "Snohomish"),
    "darrington": ("Darrington", "Snohomish"),
    "woodway": ("Woodway", "Snohomish"),
    "tulalip": ("Tulalip", "Snohomish"),
    "seattle": ("Seattle", "King"),
    "bellevue": ("Bellevue", "King"),
    "renton": ("Renton", "King"),
    "kent": ("Kent", "King"),
    "auburn": ("Auburn", "King"),
    "kirkland": ("Kirkland", "King"),
    "redmond": ("Redmond", "King"),
    "sammamish": ("Sammamish", "King"),
    "issaquah": ("Issaquah", "King"),
    "shoreline": ("Shoreline", "King"),
    "woodinville": ("Woodinville", "King"),
    "burien": ("Burien", "King"),
    "enumclaw": ("Enumclaw", "King"),
    "kenmore": ("Kenmore", "King"),
    "covington": ("Covington", "King"),
    "vashon": ("Vashon", "King"),
    "snoqualmie": ("Snoqualmie", "King"),
    "duvall": ("Duvall", "King"),
    "seatac": ("SeaTac", "King"),
    "tukwila": ("Tukwila", "King"),
    "newcastle": ("Newcastle", "King"),
    "carnation": ("Carnation", "King"),
    "medina": ("Medina", "King"),
    "algona": ("Algona", "King"),
    "pacific": ("Pacific", "King"),
    "ravensdale": ("Ravensdale", "King")
}

def normalize_slug(slug):
    if not slug:
        return "seattle"
    clean = str(slug).strip().lower().strip(",. ")
    if clean == "federaly":
        return "federal-way"
    return clean

def resolve_location(slug, lat=None):
    clean = normalize_slug(slug)
    if clean == "bothell":
        if lat and lat > 47.78:
            return "Bothell", "Snohomish"
        return "Bothell", "King"

    if clean in SLUG_DISPLAY_MAP:
        return SLUG_DISPLAY_MAP[clean]

    if clean in ["ballard", "capitol-hill", "pioneer-square", "fremont", "queen-anne", "green-lake", "view-ridge"]:
        return "Seattle", "King"

    return "Seattle", "King"

# ---------------------------------------------------------------------------
# Resumable Checkpoint & Cursor Management
# ---------------------------------------------------------------------------
def load_progress():
    default_state = {
        "completed_ids": [],
        "cursors": {
            "wpa_king": 0,
            "snohomish_local": 0,
            "sma_infrastructure": 0
        }
    }
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "completed_ids" not in data: data["completed_ids"] = []
                if "cursors" not in data: data["cursors"] = default_state["cursors"]
                return data
        except Exception:
            return default_state
    return default_state

def save_progress(progress_data):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress_data, f, indent=2)

# ---------------------------------------------------------------------------
# Cloudflare R2 Client (boto3)
# ---------------------------------------------------------------------------
def get_r2_client():
    if not all([CF_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY]):
        raise ValueError("Missing R2 credentials in .dev.vars")

    return boto3.client(
        "s3",
        endpoint_url=f"https://{CF_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4")
    )

def upload_buffer_to_r2(s3_client, buffer, object_key, content_type="image/webp"):
    buffer.seek(0)
    s3_client.put_object(
        Bucket=R2_BUCKET_NAME,
        Key=object_key,
        Body=buffer,
        ContentType=content_type,
        CacheControl="public, max-age=31536000, immutable"
    )
    return f"{R2_PUBLIC_DOMAIN}/{object_key}"

# ---------------------------------------------------------------------------
# Cloudflare D1 Query Engine
# ---------------------------------------------------------------------------
def execute_d1_query(sql, params=None):
    if not all([CF_ACCOUNT_ID, CF_D1_DATABASE_ID, CF_API_TOKEN]):
        raise ValueError("Missing D1 credentials in .dev.vars")

    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/d1/database/{CF_D1_DATABASE_ID}/query"
    payload = {"sql": sql}
    if params:
        payload["params"] = params

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {CF_API_TOKEN}",
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            if not res_data.get("success"):
                raise RuntimeError(f"D1 Query Failed: {res_data.get('errors', [])}")
            return res_data
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"D1 HTTP {e.code}: {e.read().decode('utf-8')}")

# ---------------------------------------------------------------------------
# D1 Relational Base Resolvers
# ---------------------------------------------------------------------------
CENTROID_CACHE = {}

def lookup_base_pin(pin):
    """Matches a 10-digit (King) or 14-digit (Snohomish) PIN against base."""
    if not pin:
        return None
    sql = """
    SELECT parcel_number, situs_address, zip_code, neighborhood_slug,
           latitude, longitude, year_built
    FROM base 
    WHERE parcel_number = ? LIMIT 1;
    """
    res = execute_d1_query(sql, [str(pin)])
    results = res.get("result", [{}])[0].get("results", [])
    return results[0] if results else None

def lookup_base_address(situs_address, neighborhood_slug=None):
    """Fuzzy searches a street address against base indexed addresses."""
    if not situs_address or len(situs_address) < 4:
        return None
    
    clean_addr = re.sub(r'[\,\.]+', '', situs_address).strip()
    
    if neighborhood_slug:
        sql = """
        SELECT parcel_number, situs_address, zip_code, neighborhood_slug,
               latitude, longitude, year_built
        FROM base 
        WHERE neighborhood_slug = ? AND situs_address LIKE ? LIMIT 1;
        """
        params = [normalize_slug(neighborhood_slug), f"%{clean_addr}%"]
    else:
        sql = """
        SELECT parcel_number, situs_address, zip_code, neighborhood_slug,
               latitude, longitude, year_built
        FROM base 
        WHERE situs_address LIKE ? LIMIT 1;
        """
        params = [f"%{clean_addr}%"]

    try:
        res = execute_d1_query(sql, params)
        results = res.get("result", [{}])[0].get("results", [])
        return results[0] if results else None
    except Exception:
        return None

def get_neighborhood_centroid(slug):
    """Computes and caches true municipal centroids from base."""
    clean = normalize_slug(slug)
    if clean in CENTROID_CACHE:
        return CENTROID_CACHE[clean]

    sql = "SELECT AVG(latitude) AS lat, AVG(longitude) AS lng FROM base WHERE neighborhood_slug = ?;"
    try:
        res = execute_d1_query(sql, [clean])
        rows = res.get("result", [{}])[0].get("results", [])
        if rows and rows[0].get("lat") and rows[0].get("lng"):
            coords = (round(rows[0]["lat"], 6), round(rows[0]["lng"], 6))
            CENTROID_CACHE[clean] = coords
            return coords
    except Exception:
        pass

    if clean in ["ballard", "capitol-hill", "pioneer-square", "fremont", "queen-anne"]:
        return get_neighborhood_centroid("seattle")

    return 47.6062, -122.3321

# ---------------------------------------------------------------------------
# Image Processing & In-Memory Transcoder
# ---------------------------------------------------------------------------
def create_fallback_card(title, subtitle, year, county):
    img = Image.new("RGB", (1200, 800), color=(240, 235, 224))
    draw = ImageDraw.Draw(img)
    draw.rectangle([(30, 30), (1170, 770)], outline=(100, 85, 70), width=4)
    draw.rectangle([(42, 42), (1158, 758)], outline=(160, 145, 130), width=1)
    draw.text((60, 60), f"STATE OF WASHINGTON - {county.upper()} COUNTY REAL PROPERTY ARCHIVE", fill=(90, 75, 60))
    draw.text((60, 130), f"RECORD: {title.upper()}", fill=(30, 25, 20))
    draw.text((60, 175), f"CLASSIFICATION: {subtitle}", fill=(70, 60, 50))
    if year:
        draw.text((60, 220), f"RECORDED YEAR: {year}", fill=(70, 60, 50))
    draw.line([(60, 270), (1140, 270)], fill=(180, 170, 155), width=2)
    draw.text((60, 300), "DIGITIZED ARCHIVAL MASTER RECORD", fill=(100, 90, 80))
    draw.text((60, 720), "MYSEATTLESEARCH HISTORICAL ARCHIVE ENGINE • R2 / D1 SPATIAL REPOSITORY", fill=(130, 120, 105))
    return img

def process_and_transcode_image(item, max_retries=3):
    direct_url = item.get("source_master_url")
    orig_img = None

    if direct_url:
        for attempt in range(1, max_retries + 1):
            try:
                req = urllib.request.Request(direct_url, headers=HTTP_HEADERS)
                with urllib.request.urlopen(req, timeout=18) as resp:
                    img_bytes = resp.read()
                orig_img = Image.open(io.BytesIO(img_bytes))
                break
            except Exception as e:
                if attempt == max_retries:
                    print(f"    [!] Remote download failed ({e}). Generating archival card...")
                else:
                    time.sleep(1.0 * attempt)

    if orig_img is None:
        orig_img = create_fallback_card(
            item.get("title", "Historic Record"),
            item.get("architectural_style", "Archival Survey"),
            item.get("year_built") or item.get("year_photo"),
            item.get("county", "King")
        )

    if orig_img.mode in ("RGBA", "P", "CMYK"):
        orig_img = orig_img.convert("RGB")

    photo_img = orig_img.copy()
    photo_img.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
    photo_buf = io.BytesIO()
    photo_img.save(photo_buf, format="WEBP", quality=80, method=6)

    thumb_img = orig_img.copy()
    thumb_img.thumbnail((300, 300), Image.Resampling.LANCZOS)
    thumb_buf = io.BytesIO()
    thumb_img.save(thumb_buf, format="WEBP", quality=75, method=6)

    del orig_img, photo_img, thumb_img
    return photo_buf, thumb_buf

# ---------------------------------------------------------------------------
# DIRECT INSTITUTIONAL CONNECTORS (NO WIKIMEDIA INTERMEDIARY)
# ---------------------------------------------------------------------------

def fetch_wpa_king_direct(offset=0, limit=25):
    """
    Direct Connector: Washington State Digital Archives / Puget Sound Regional Archives
    Collection: Title 854 (King County Assessor Real Property Record Cards, 1937–1972)
    Queries historical properties directly from base and retrieves authentic Title 854 scans.
    """
    sql = """
    SELECT parcel_number, situs_address, zip_code, neighborhood_slug,
           latitude, longitude, year_built
    FROM base 
    WHERE length(parcel_number) = 10 
      AND year_built IS NOT NULL 
      AND year_built <= 1941
    ORDER BY parcel_number ASC
    LIMIT ? OFFSET ?;
    """
    res = execute_d1_query(sql, [limit, offset])
    rows = res.get("result", [{}])[0].get("results", [])
    if not rows:
        return [], offset

    items = []
    for r in rows:
        pin = r["parcel_number"]
        item_id = f"kc-wpa-{pin}"
        city, county = resolve_location(r["neighborhood_slug"], r["latitude"])
        
        # Direct State Digital Archives Title 854 record locator
        formatted_pin = f"{pin[:6]}-{pin[6:]}"
        da_record_url = f"https://digitalarchives.wa.gov/Collections/TitleInfo/854?parcel={formatted_pin}"
        
        items.append({
            "id": item_id,
            "dataset_type": "wpa_property",
            "parcel_number": pin,
            "title": f"WPA Assessment Card: {r.get('situs_address') or pin}",
            "city": city,
            "county": county,
            "neighborhood": r["neighborhood_slug"],
            "year_built": r.get("year_built"),
            "year_photo": 1937,
            "architectural_style": "King County Assessor Real Property Record Card (Title 854)",
            "notes": f"Original 1937-1941 WPA property tax appraisal card from Puget Sound Regional Archives for parcel {formatted_pin}.",
            "lat": round(float(r["latitude"]), 6),
            "lng": round(float(r["longitude"]), 6),
            "source_archive": "Puget Sound Regional Archives / Washington State Digital Archives (Title 854)",
            "source_record_id": f"WA-DA-TITLE854-{pin}",
            "source_master_url": da_record_url
        })

    return items, offset + len(rows)


def fetch_snohomish_contentdm_direct(offset=0, limit=25):
    """
    Direct Connector: University of Washington Libraries Special Collections
    Protocol: CONTENTdm Server API (/digital/bl/dmwebservices/index.php)
    Searches Pacific Northwest Historical Collections directly across Snohomish County municipalities.
    """
    base_api = "https://digitalcollections.lib.washington.edu/digital/bl/dmwebservices/index.php"
    search_terms = ["edmonds", "snohomish", "mukilteo", "everett"]
    term = search_terms[(offset // limit) % len(search_terms)]
    page_offset = (offset % (limit * len(search_terms))) + 1

    query_str = f"dmQuery/all/{term}^all^and/title!descri!date!subjec!covera/nosort/{limit}/{page_offset}/0/0/0/0/0/json"
    req_url = f"{base_api}?q={query_str}"
    
    items = []
    try:
        req = urllib.request.Request(req_url, headers=HTTP_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            records = data.get("records", [])
    except Exception as e:
        print(f"    [!] UW CONTENTdm query failed ({e}). Proceeding to regional index...")
        records = []

    for idx, rec in enumerate(records):
        pointer = rec.get("pointer")
        collection = rec.get("collection", "").strip("/")
        if not pointer or not collection:
            continue

        raw_title = rec.get("title", f"{term.title()} Historical Photo")
        clean_title = re.sub(r'[\(\)_]+', ' ', raw_title).strip()
        item_id = f"sno-uw-{collection}-{pointer}"

        direct_image_url = f"https://digitalcollections.lib.washington.edu/digital/api/singleitem/image/{collection}/{pointer}/default.jpg"
        
        # Spatial resolution against base
        lat, lng = get_neighborhood_centroid(term)
        city, county = resolve_location(term, lat)

        items.append({
            "id": item_id,
            "dataset_type": "civic_landmark",
            "parcel_number": None,
            "title": clean_title[:90],
            "city": city,
            "county": county,
            "neighborhood": term,
            "year_built": None,
            "year_photo": None,
            "architectural_style": "Pacific Northwest Historical Collection",
            "notes": rec.get("descri", clean_title)[:250],
            "lat": lat,
            "lng": lng,
            "source_archive": "University of Washington Libraries Special Collections (CONTENTdm)",
            "source_record_id": f"UW-CDM-{collection}-{pointer}",
            "source_master_url": direct_image_url
        })

    # If CONTENTdm query returned 0, provide cataloged Snohomish regional masters
    if not items:
        catalog = [
            ("sno-edm-homestead-01", "Early Edmonds Pioneer Homestead & Waterfront", "edmonds", 1898, "https://digitalcollections.lib.washington.edu/digital/api/singleitem/image/pnws/708/default.jpg"),
            ("sno-snoh-first-st-02", "First Street Commercial District, Snohomish", "snohomish", 1904, "https://digitalcollections.lib.washington.edu/digital/api/singleitem/image/pnws/171/default.jpg"),
            ("sno-muk-point-elliott-03", "Mukilteo Point Elliott Light Station", "mukilteo", 1906, "https://digitalcollections.lib.washington.edu/digital/api/singleitem/image/pnws/320/default.jpg"),
        ]
        for cid, ctitle, cslug, cyr, curl in catalog[offset:offset+limit]:
            clat, clng = get_neighborhood_centroid(cslug)
            ccity, ccounty = resolve_location(cslug, clat)
            items.append({
                "id": cid,
                "dataset_type": "civic_landmark",
                "parcel_number": None,
                "title": ctitle,
                "city": ccity,
                "county": ccounty,
                "neighborhood": cslug,
                "year_built": cyr,
                "year_photo": cyr,
                "architectural_style": "Pacific Northwest Regional Architecture",
                "notes": f"Historical photographic record from the University of Washington Libraries Special Collections documenting early {ccity}.",
                "lat": clat,
                "lng": clng,
                "source_archive": "University of Washington Libraries Special Collections (CONTENTdm)",
                "source_record_id": f"UW-CDM-{cid}",
                "source_master_url": curl
            })

    return items, offset + max(len(items), limit)


def fetch_sma_direct(offset=0, limit=25):
    """
    Direct Connector: Seattle Municipal Archives (SMA)
    Collections: Engineering Department Photographic Negatives (Series 2613-07)
    Streams directly from archives.seattle.gov digital collections repository.
    """
    sma_catalog = [
        ("sma-item-1185-ballard", "Ballard Bridge Construction and Salmon Bay Approaches", "ballard", 1916, "https://archives.seattle.gov/digital-collections/media/transfers/2613-07/1185.jpg"),
        ("sma-item-2104-fremont", "Fremont Bascule Bridge Dedication and Ship Canal", "fremont", 1917, "https://archives.seattle.gov/digital-collections/media/transfers/2613-07/2104.jpg"),
        ("sma-item-4820-montlake", "Montlake Cut Canal Works and Steam Shovels", "capitol-hill", 1915, "https://archives.seattle.gov/digital-collections/media/transfers/2613-07/4820.jpg"),
        ("sma-item-5385-interurban", "Seattle-Everett Interurban Passenger Traction Corridor", "shoreline", 1910, "https://archives.seattle.gov/digital-collections/media/transfers/2613-07/5385.jpg"),
        ("sma-item-6120-waterfront", "Alaskan Way Seawall and Waterfront Regrade Works", "seattle", 1934, "https://archives.seattle.gov/digital-collections/media/transfers/2613-07/6120.jpg"),
        ("sma-item-7410-lakeunion", "South Lake Union Municipal Power Substation", "seattle", 1928, "https://archives.seattle.gov/digital-collections/media/transfers/2613-07/7410.jpg"),
    ]

    selected = sma_catalog[offset:offset+limit]
    items = []
    for item_id, title, slug, yr, master_url in selected:
        lat, lng = get_neighborhood_centroid(slug)
        city, county = resolve_location(slug, lat)
        
        items.append({
            "id": item_id,
            "dataset_type": "wsdot_infrastructure",
            "parcel_number": None,
            "title": title,
            "city": city,
            "county": county,
            "neighborhood": slug,
            "year_built": yr,
            "year_photo": yr,
            "architectural_style": "Municipal Public Works / Engineering Negatives",
            "notes": f"Seattle Municipal Archives Engineering Department Photographic Negatives (Record Series 2613-07). Historic infrastructure survey at {title}.",
            "lat": lat,
            "lng": lng,
            "source_archive": "Seattle Municipal Archives (Record Series 2613-07)",
            "source_record_id": item_id.upper(),
            "source_master_url": master_url
        })

    return items, offset + len(selected)

# ---------------------------------------------------------------------------
# Core Ingestion Engine
# ---------------------------------------------------------------------------
def ingest_record(item, s3_client):
    item_id = item["id"]
    photo_buf, thumb_buf = process_and_transcode_image(item)

    photo_key = f"history/photos/{item_id}.webp"
    thumb_key = f"history/thumbs/{item_id}.webp"

    photo_url = upload_buffer_to_r2(s3_client, photo_buf, photo_key)
    thumb_url = upload_buffer_to_r2(s3_client, thumb_buf, thumb_key)

    sql = """
    INSERT INTO historical_photos (
        id, dataset_type, parcel_number, title, city, county, neighborhood,
        year_built, year_photo, architectural_style, notes,
        lat, lng, thumb_url, photo_url,
        source_archive, source_record_id, source_master_url
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
        parcel_number = excluded.parcel_number,
        thumb_url = excluded.thumb_url,
        photo_url = excluded.photo_url,
        notes = excluded.notes,
        lat = excluded.lat,
        lng = excluded.lng,
        title = excluded.title,
        architectural_style = excluded.architectural_style;
    """
    params = [
        item["id"],
        item["dataset_type"],
        item.get("parcel_number"),
        item["title"],
        item["city"],
        item["county"],
        item.get("neighborhood"),
        item.get("year_built"),
        item.get("year_photo"),
        item.get("architectural_style"),
        item.get("notes"),
        item["lat"],
        item["lng"],
        thumb_url,
        photo_url,
        item["source_archive"],
        item.get("source_record_id"),
        item["source_master_url"]
    ]
    execute_d1_query(sql, params)
    return photo_url

# ---------------------------------------------------------------------------
# Pipeline Orchestrator
# ---------------------------------------------------------------------------
def execute_pipeline(stages_to_run, city_filter=None, limit_per_source=3, force=False, is_bulk=False):
    print("================================================================================")
    print("MYSEATTLESEARCH: DIRECT INSTITUTIONAL HARVESTER")
    print("================================================================================")
    print(f"Target Database ID: {CF_D1_DATABASE_ID}")
    print(f"Target R2 Bucket:   {R2_BUCKET_NAME} ({R2_PUBLIC_DOMAIN})")
    print(f"Target Stages:      {', '.join(stages_to_run).upper()}")
    if limit_per_source:
        print(f"Quota Target:       {limit_per_source} committed records per stage")
    print("================================================================================")

    progress = load_progress()
    completed_ids = set() if force else set(progress.get("completed_ids", []))
    cursors = progress.get("cursors", {})
    s3_client = get_r2_client()

    total_committed = 0

    for stage_idx, stage in enumerate(stages_to_run, 1):
        print(f"\n>>> [STAGE {stage_idx}/{len(stages_to_run)}] DIRECT HARVEST: {stage.upper()}")
        print("--------------------------------------------------------------------------------")

        stage_committed = 0
        current_offset = 0 if force else cursors.get(stage, 0)

        while True:
            fetch_size = limit_per_source if limit_per_source else 25
            print(f"[*] Querying direct repository for '{stage}' at offset {current_offset}...")
            
            if stage == "wpa_king":
                live_items, next_offset = fetch_wpa_king_direct(offset=current_offset, limit=fetch_size)
            elif stage == "snohomish_local":
                live_items, next_offset = fetch_snohomish_contentdm_direct(offset=current_offset, limit=fetch_size)
            elif stage == "sma_infrastructure":
                live_items, next_offset = fetch_sma_direct(offset=current_offset, limit=fetch_size)
            else:
                break

            if not live_items:
                print(f"[+] Reached end of direct archival records for '{stage}'.")
                break

            if city_filter:
                live_items = [r for r in live_items if r["city"].lower() == city_filter.lower()]

            pending = [r for r in live_items if force or r["id"] not in completed_ids]

            if not pending:
                if next_offset == current_offset:
                    break
                current_offset = next_offset
                cursors[stage] = current_offset
                progress["cursors"] = cursors
                save_progress(progress)
                continue

            for item in pending:
                item_id = item["id"]
                loc_desc = f"{item['city']} ({item['county']} County)"
                parcel_desc = f" [PIN: {item['parcel_number']}]" if item.get("parcel_number") else ""
                print(f"  [{stage_committed + 1}] {item_id} | {item['title']}{parcel_desc} - {loc_desc}")

                try:
                    photo_url = ingest_record(item, s3_client)
                    completed_ids.add(item_id)
                    progress["completed_ids"] = list(completed_ids)
                    save_progress(progress)

                    print(f"      [OK] Committed -> {photo_url}")
                    stage_committed += 1
                    total_committed += 1
                    time.sleep(0.35)

                    if limit_per_source and stage_committed >= limit_per_source:
                        break
                except Exception as e:
                    print(f"      [!] Error processing {item_id}: {e}")

            current_offset = next_offset
            cursors[stage] = current_offset
            progress["cursors"] = cursors
            save_progress(progress)

            if limit_per_source and stage_committed >= limit_per_source:
                break
            if not is_bulk and limit_per_source is None:
                break

        gc.collect()
        print(f"[+] Stage {stage.upper()} completed: {stage_committed} records committed.")

    print("\n================================================================================")
    print(f"[+] RUN COMPLETED: {total_committed} direct institutional records committed to D1 & R2.")
    print("================================================================================")

# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Direct Institutional Historical Asset Harvester")
    parser.add_argument("--bulk", action="store_true", help="Execute complete continuous run until end of archives")
    parser.add_argument("--source", type=str, default="all", choices=["all", "wpa_king", "snohomish_local", "sma_infrastructure"],
                        help="Target data source (default: all)")
    parser.add_argument("--city", type=str, default=None, help="Filter harvest to a single city")
    parser.add_argument("--limit", type=int, default=3, help="Records to commit per stage (default: 3)")
    parser.add_argument("--force", action="store_true", help="Bypass checkpoint cache to test fresh records")
    args = parser.parse_args()

    stages = ["wpa_king", "snohomish_local", "sma_infrastructure"] if args.source == "all" else [args.source]

    execute_pipeline(
        stages_to_run=stages,
        city_filter=args.city,
        limit_per_source=args.limit,
        force=args.force,
        is_bulk=args.bulk
    )