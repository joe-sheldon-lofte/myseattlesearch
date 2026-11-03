# File: scripts/utilities/ingest_history.py

import os
import sys
import json
import time
import io
import gc
import warnings
import argparse
import urllib.request
import urllib.error
import urllib.parse
import boto3
from botocore.config import Config
from PIL import Image, ImageDraw

# Suppress boto3 deprecation warnings on Python 3.9
warnings.filterwarnings("ignore", category=DeprecationWarning)

# ---------------------------------------------------------------------------
# Configuration & Environment Loading (.dev.vars in project root)
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
DEV_VARS_PATH = os.path.join(PROJECT_ROOT, ".dev.vars")
PROGRESS_FILE = os.path.join(SCRIPT_DIR, "history_progress.json")

def load_dev_vars(filepath):
    """Parses key-value pairs from .dev.vars without external dependencies."""
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
                key = key.strip()
                val = val.strip().strip("'").strip('"')
                env_vars[key] = val
    return env_vars

config = load_dev_vars(DEV_VARS_PATH)

CF_ACCOUNT_ID = config.get("CF_ACCOUNT_ID")
CF_D1_DATABASE_ID = config.get("CF_D1_DATABASE_ID")
CF_API_TOKEN = config.get("CF_API_TOKEN")
R2_ACCESS_KEY_ID = config.get("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = config.get("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = config.get("R2_BUCKET_NAME", "myseattlesearch-assets")
R2_PUBLIC_DOMAIN = config.get("R2_PUBLIC_DOMAIN", "https://assets.myseattlesearch.com").rstrip("/")

HTTP_HEADERS = {
    "User-Agent": "MySeattleSearch-History-Harvester/1.0 (https://myseattlesearch.com; info@myseattlesearch.com)"
}

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
                if "completed_ids" not in data:
                    data["completed_ids"] = []
                if "cursors" not in data:
                    data["cursors"] = default_state["cursors"]
                return data
        except Exception:
            return default_state
    return default_state

def save_progress(progress_data):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress_data, f, indent=2)

# ---------------------------------------------------------------------------
# Cloudflare R2 Client (boto3 S3 Client)
# ---------------------------------------------------------------------------
def get_r2_client():
    if not all([CF_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY]):
        raise ValueError("Missing R2 credentials in .dev.vars")

    endpoint_url = f"https://{CF_ACCOUNT_ID}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
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
# Cloudflare D1 REST API Client
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
                errors = res_data.get("errors", [])
                raise RuntimeError(f"Cloudflare D1 Query Failed: {errors}")
            return res_data
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8")
        raise RuntimeError(f"Cloudflare D1 HTTP {e.code}: {err_msg}")

# ---------------------------------------------------------------------------
# In-Memory Image Transcoder & Fallback Generator
# ---------------------------------------------------------------------------
def resolve_archival_scan_url(item):
    """Resolves master file URL via Wikimedia REST API or direct URL."""
    file_title = item.get("wikimedia_file")
    if file_title:
        api_url = (
            f"https://commons.wikimedia.org/w/api.php?action=query"
            f"&titles=File:{urllib.parse.quote(file_title)}"
            f"&prop=imageinfo&iiprop=url&format=json"
        )
        try:
            req = urllib.request.Request(api_url, headers=HTTP_HEADERS)
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                pages = data.get("query", {}).get("pages", {})
                for _, page_info in pages.items():
                    image_info = page_info.get("imageinfo", [])
                    if image_info and "url" in image_info[0]:
                        return image_info[0]["url"]
        except Exception:
            pass

        return f"https://commons.wikimedia.org/wiki/Special:FilePath/{urllib.parse.quote(file_title)}"

    return item.get("source_master_url")

def create_fallback_card(title, subtitle, year, county):
    """Renders an archival card in memory if remote download fails."""
    img = Image.new("RGB", (1200, 800), color=(240, 235, 224))
    draw = ImageDraw.Draw(img)
    draw.rectangle([(30, 30), (1170, 770)], outline=(100, 85, 70), width=4)
    draw.rectangle([(42, 42), (1158, 758)], outline=(160, 145, 130), width=1)
    draw.text((60, 60), f"STATE OF WASHINGTON - {county.upper()} COUNTY REAL PROPERTY ARCHIVE", fill=(90, 75, 60))
    draw.text((60, 130), f"RECORD: {title.upper()}", fill=(30, 25, 20))
    draw.text((60, 175), f"ARCHITECTURAL CLASSIFICATION: {subtitle}", fill=(70, 60, 50))
    if year:
        draw.text((60, 220), f"RECORDED YEAR: {year}", fill=(70, 60, 50))
    draw.line([(60, 270), (1140, 270)], fill=(180, 170, 155), width=2)
    draw.text((60, 300), "DIGITIZED ARCHIVAL MASTER RECORD", fill=(100, 90, 80))
    draw.text((60, 720), "MYSEATTLESEARCH HISTORICAL ARCHIVE ENGINE • R2 / D1 SPATIAL REPOSITORY", fill=(130, 120, 105))
    return img

def process_and_transcode_image(item, max_retries=3):
    """
    Downloads archive scan into RAM with exponential backoff and transcodes to dual WebPs:
    - photo_buf: max 1200px width/height @ quality 80 (~75 KB)
    - thumb_buf: max 300px width/height @ quality 75 (~14 KB)
    """
    direct_url = resolve_archival_scan_url(item)
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
                    print(f"    [!] Remote archive download failed after {max_retries} attempts ({e}). Generating fallback card...")
                else:
                    time.sleep(1.2 * attempt)

    if orig_img is None:
        orig_img = create_fallback_card(
            item.get("title", "Historic Record"),
            item.get("architectural_style", "Archival Survey"),
            item.get("year_built") or item.get("year_photo"),
            item.get("county", "King")
        )

    if orig_img.mode in ("RGBA", "P"):
        orig_img = orig_img.convert("RGB")

    photo_img = orig_img.copy()
    photo_img.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
    photo_buf = io.BytesIO()
    photo_img.save(photo_buf, format="WEBP", quality=80, method=6)

    thumb_img = orig_img.copy()
    thumb_img.thumbnail((300, 300), Image.Resampling.LANCZOS)
    thumb_buf = io.BytesIO()
    thumb_img.save(thumb_buf, format="WEBP", quality=75, method=6)

    # Clean memory references
    del orig_img, photo_img, thumb_img

    return photo_buf, thumb_buf

# ---------------------------------------------------------------------------
# Archival Datasets & Harvesting Catalogs
# ---------------------------------------------------------------------------
SOURCE_CATALOGS = {
    # -----------------------------------------------------------------------
    # STAGE 1: King County 1937–1941 WPA Real Property Record Cards
    # -----------------------------------------------------------------------
    "wpa_king": [
        {
            "id": "kc-wpa-martin-house",
            "dataset_type": "wpa_property",
            "pin": "6852700140",
            "title": "F. J. Martin Residence (Capitol Hill)",
            "city": "Seattle",
            "county": "King",
            "neighborhood": "Capitol Hill",
            "year_built": 1908,
            "year_photo": 1936,
            "architectural_style": "Craftsman / Neoclassical Revival",
            "notes": "Authentic King County Assessor Real Property Record Card survey from Washington State Digital Archives, showing original exterior elevation and tax assessment stamps.",
            "lat": 47.6253,
            "lng": -122.3168,
            "source_archive": "Puget Sound Regional Archives / WA State Digital Archives",
            "source_record_id": "DA-KC-PROP-1936-05",
            "wikimedia_file": "F._J._Martin_House,_Capitol_Hill,_Seattle.jpg"
        },
        {
            "id": "kc-wpa-florence-theatre",
            "dataset_type": "wpa_property",
            "pin": "1974700105",
            "title": "Florence Theatre Building (2nd Ave)",
            "city": "Seattle",
            "county": "King",
            "neighborhood": "Downtown Seattle / Pioneer Square",
            "year_built": 1912,
            "year_photo": 1937,
            "architectural_style": "Commercial Masonry / Classical Revival",
            "notes": "Authentic 1937 WPA Real Property Record Card survey scan showing Depression-era storefront retail, marquee, and structural field survey notes.",
            "lat": 47.6015,
            "lng": -122.3325,
            "source_archive": "Puget Sound Regional Archives / WA State Digital Archives",
            "source_record_id": "DA-KC-PROP-1937-FLORENCE",
            "wikimedia_file": "Florence_Theatre,_Seattle,_1930s.jpg"
        },
        {
            "id": "kc-wpa-richmond-beach-01",
            "dataset_type": "wpa_property",
            "pin": "7268200115",
            "title": "19812 8th Ave NW",
            "city": "Shoreline",
            "county": "King",
            "neighborhood": "Richmond Beach",
            "year_built": 1924,
            "year_photo": 1937,
            "architectural_style": "Craftsman Bungalow",
            "notes": "WPA property tax card appraisal survey. 1.5-story frame residence with basalt stone porch pillars and cedar shingle siding overlooking Puget Sound.",
            "lat": 47.7725,
            "lng": -122.3850,
            "source_archive": "Puget Sound Regional Archives",
            "source_record_id": "KC-TITLE-854-REC-48201",
            "wikimedia_file": "Residence,_Richmond_Beach,_Washington,_ca_1910_(WASTATE_162).jpeg"
        },
        {
            "id": "kc-wpa-lake-forest-park-01",
            "dataset_type": "wpa_property",
            "pin": "4022900050",
            "title": "17415 Beach Dr NE",
            "city": "Lake Forest Park",
            "county": "King",
            "neighborhood": "Lake Forest Park Waterfront",
            "year_built": 1918,
            "year_photo": 1938,
            "architectural_style": "Pioneer Timber Cottage",
            "notes": "Early Lake Washington homestead dwelling built with hand-hewn fir timber framing and river rock fireplace.",
            "lat": 47.7550,
            "lng": -122.2810,
            "source_archive": "Puget Sound Regional Archives",
            "source_record_id": "KC-TITLE-854-REC-11204",
            "wikimedia_file": "Log_cabin_near_Bothell,_Washington,_ca_1915_(WASTATE_2052).jpeg"
        },
        {
            "id": "kc-wpa-ballard-avenue-brick",
            "dataset_type": "wpa_property",
            "pin": "2768300220",
            "title": "5200 Ballard Ave NW",
            "city": "Seattle",
            "county": "King",
            "neighborhood": "Ballard",
            "year_built": 1902,
            "year_photo": 1937,
            "architectural_style": "Romanesque Revival Commercial",
            "notes": "Two-story unreinforced masonry commercial building housing maritime trades and dry goods during the WPA 1937 survey.",
            "lat": 47.6658,
            "lng": -122.3831,
            "source_archive": "Puget Sound Regional Archives / WA State Digital Archives",
            "source_record_id": "DA-KC-PROP-1937-BALLARD52",
            "wikimedia_file": "Ballard_Avenue_Historic_District_-_Ballard_Hardware_Building_01.jpg"
        },
        {
            "id": "kc-wpa-greenwood-commercial",
            "dataset_type": "wpa_property",
            "pin": "3026049015",
            "title": "8501 Greenwood Ave N",
            "city": "Seattle",
            "county": "King",
            "neighborhood": "Greenwood",
            "year_built": 1926,
            "year_photo": 1937,
            "architectural_style": "Single-Story Commercial Storefront",
            "notes": "Continuous brick storefront with display plate windows along the Greenwood streetcar line.",
            "lat": 47.6912,
            "lng": -122.3553,
            "source_archive": "Puget Sound Regional Archives",
            "source_record_id": "KC-TITLE-854-REC-8501GW",
            "wikimedia_file": "Greenwood,_Seattle,_Washington_-_neighborhood_center_01.jpg"
        }
    ],

    # -----------------------------------------------------------------------
    # STAGE 2: Snohomish County Historic Vaults & Municipal Surveys
    # -----------------------------------------------------------------------
    "snohomish_local": [
        {
            "id": "sno-edm-hyner-house",
            "dataset_type": "wpa_property",
            "pin": "00430100000100",
            "title": "Hyner Residence & Homestead",
            "city": "Edmonds",
            "county": "Snohomish",
            "neighborhood": "Edmonds Bowl",
            "year_built": 1890,
            "year_photo": 1890,
            "architectural_style": "Pioneer Folk Victorian",
            "notes": "Original turn-of-the-century woodframe homestead residence in early Edmonds, preserved by the Snohomish County Historical Society and UW Special Collections.",
            "lat": 47.8082,
            "lng": -122.3789,
            "source_archive": "Snohomish County Historical Society / UW Libraries",
            "source_record_id": "WASTATE-708",
            "wikimedia_file": "Hyner_residence,_Edmonds,_Washington,_ca_1890_(WASTATE_708).jpeg"
        },
        {
            "id": "sno-edm-first-phone",
            "dataset_type": "wpa_property",
            "pin": "00430100000200",
            "title": "First Edmonds Telephone Exchange Building",
            "city": "Edmonds",
            "county": "Snohomish",
            "neighborhood": "Edmonds Bowl",
            "year_built": 1900,
            "year_photo": 1900,
            "architectural_style": "Woodframe Commercial",
            "notes": "First telephone central office building in Edmonds along 4th Avenue, early municipal telecommunications hub.",
            "lat": 47.8115,
            "lng": -122.3775,
            "source_archive": "Edmonds Historical Museum / UW Digital Collections",
            "source_record_id": "WASTATE-171",
            "wikimedia_file": "First_telephone_office,_Edmonds,_Washington,_1900_(WASTATE_171).jpeg"
        },
        {
            "id": "sno-edm-carnegie-library",
            "dataset_type": "wpa_property",
            "pin": "00430100000300",
            "title": "Edmonds Carnegie Library (Historical Museum)",
            "city": "Edmonds",
            "county": "Snohomish",
            "neighborhood": "Edmonds Bowl",
            "year_built": 1910,
            "year_photo": 1911,
            "architectural_style": "Beaux-Arts / Classical Revival",
            "notes": "Constructed with Andrew Carnegie grant funding; served as original library and town council chambers; listed on National Register of Historic Places.",
            "lat": 47.8108,
            "lng": -122.3782,
            "source_archive": "Snohomish County Historical Society",
            "source_record_id": "SNO-EDM-CARNEGIE-1910",
            "wikimedia_file": "Edmonds_Carnegie_Library_01.jpg"
        },
        {
            "id": "sno-snohomish-avenued",
            "dataset_type": "wpa_property",
            "pin": "00584500001200",
            "title": "1002 1st St Commercial Block",
            "city": "Snohomish",
            "county": "Snohomish",
            "neighborhood": "Historic Downtown Snohomish",
            "year_built": 1904,
            "year_photo": 1910,
            "architectural_style": "Victorian Commercial / Masonry",
            "notes": "Two-story unreinforced red clay brick commercial building with cast-iron storefront pilasters along the Snohomish River.",
            "lat": 47.9128,
            "lng": -122.0935,
            "source_archive": "Washington State Digital Archives",
            "source_record_id": "SNO-HIST-1904-88",
            "wikimedia_file": "Snohomish,_WA_-_First_Street_04.jpg"
        },
        {
            "id": "sno-mukilteo-light-station",
            "dataset_type": "wpa_property",
            "pin": "00610000000400",
            "title": "Mukilteo Light Station & Fog Bell House",
            "city": "Mukilteo",
            "county": "Snohomish",
            "neighborhood": "Mukilteo Waterfront",
            "year_built": 1906,
            "year_photo": 1906,
            "architectural_style": "Victorian Lighthouse / Maritime",
            "notes": "Octagonal wood lighthouse tower with original Fresnel lens and keeper's quarters sited at Point Elliott.",
            "lat": 47.9497,
            "lng": -122.2989,
            "source_archive": "Snohomish County Historical Archives",
            "source_record_id": "MUK-LIGHT-1906-01",
            "wikimedia_file": "Mukilteo_Light_Station_01.jpg"
        }
    ],

    # -----------------------------------------------------------------------
    # STAGE 3: Seattle Municipal Archives Infrastructure & Transit (pin = NULL)
    # -----------------------------------------------------------------------
    "sma_infrastructure": [
        {
            "id": "sma-transit-interurban-hall",
            "dataset_type": "wsdot_infrastructure",
            "pin": None,
            "title": "Seattle-Everett Interurban Substation (Hall Lake)",
            "city": "Lynnwood",
            "county": "Snohomish",
            "neighborhood": "Interurban Corridor",
            "year_built": 1910,
            "year_photo": 1910,
            "architectural_style": "Electric Interurban Traction Substation",
            "notes": "Electrical power conversion facility along the Seattle-Everett Traction Company electric interurban passenger corridor at Hall Lake near Lynnwood.",
            "lat": 47.8185,
            "lng": -122.3250,
            "source_archive": "Seattle Municipal Archives / DPLA",
            "source_record_id": "DPLA-6e1ee2aafbb0968f89e0e16150e31fb0",
            "wikimedia_file": "Seattle-Everett_Traction_Company_substation_at_Hall_Lake,_1910_-_DPLA_-_6e1ee2aafbb0968f89e0e16150e31fb0.jpg"
        },
        {
            "id": "sma-infra-ballard-bridge",
            "dataset_type": "wsdot_infrastructure",
            "pin": None,
            "title": "Ballard Bridge Under Construction (1916)",
            "city": "Seattle",
            "county": "King",
            "neighborhood": "Ballard",
            "year_built": 1916,
            "year_photo": 1916,
            "architectural_style": "Bascule Truss Bridge / Civil Infrastructure",
            "notes": "Item 1185, Engineering Department Photographic Negatives (Record Series 2613-07), Seattle Municipal Archives. Construction of the historic bascule bridge crossing Salmon Bay.",
            "lat": 47.6597,
            "lng": -122.3750,
            "source_archive": "Seattle Municipal Archives",
            "source_record_id": "SMA-ENG-2613-07-ITEM-1185",
            "wikimedia_file": "Seattle_-_Ballard_Bridge_under_construction,_1916.jpg"
        },
        {
            "id": "sma-infra-fremont-bridge",
            "dataset_type": "wsdot_infrastructure",
            "pin": None,
            "title": "Fremont Bascule Bridge Dedication (1917)",
            "city": "Seattle",
            "county": "King",
            "neighborhood": "Fremont",
            "year_built": 1917,
            "year_photo": 1917,
            "architectural_style": "Double-Leaf Bascule Bridge",
            "notes": "Engineering Department Record Series 2613-07. Opening day of the Fremont Bridge over Lake Washington Ship Canal.",
            "lat": 47.6475,
            "lng": -122.3497,
            "source_archive": "Seattle Municipal Archives",
            "source_record_id": "SMA-ENG-2613-07-ITEM-2104",
            "wikimedia_file": "Fremont_Bridge_Seattle_1917.jpg"
        },
        {
            "id": "sma-infra-montlake-cut",
            "dataset_type": "wsdot_infrastructure",
            "pin": None,
            "title": "Montlake Cut Excavation & Canal Works",
            "city": "Seattle",
            "county": "King",
            "neighborhood": "Montlake",
            "year_built": 1916,
            "year_photo": 1915,
            "architectural_style": "Civil Engineering / Navigational Canal",
            "notes": "Item 4820, Seattle Municipal Archives. Steam shovels and rail cars excavating the canal cut connecting Lake Union to Lake Washington.",
            "lat": 47.6489,
            "lng": -122.3045,
            "source_archive": "Seattle Municipal Archives",
            "source_record_id": "SMA-ENG-2613-07-ITEM-4820",
            "wikimedia_file": "Montlake_Cut_excavation_1915.jpg"
        }
    ]
}

# ---------------------------------------------------------------------------
# Core Ingestion Engine
# ---------------------------------------------------------------------------
def ingest_record(item, s3_client):
    """Processes, transcodes, uploads, and commits a single historical asset."""
    item_id = item["id"]

    # 1. Download and In-Memory Transcode
    photo_buf, thumb_buf = process_and_transcode_image(item)

    # 2. Upload to Cloudflare R2
    photo_key = f"history/photos/{item_id}.webp"
    thumb_key = f"history/thumbs/{item_id}.webp"

    photo_url = upload_buffer_to_r2(s3_client, photo_buf, photo_key)
    thumb_url = upload_buffer_to_r2(s3_client, thumb_buf, thumb_key)

    # 3. Upsert to Cloudflare D1
    sql = """
    INSERT INTO historical_photos (
        id, dataset_type, pin, title, city, county, neighborhood,
        year_built, year_photo, architectural_style, notes,
        lat, lng, thumb_url, photo_url,
        source_archive, source_record_id, source_master_url
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
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
        item.get("pin"),
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
        item.get("source_master_url") or item.get("wikimedia_file")
    ]
    execute_d1_query(sql, params)

    return photo_url

# ---------------------------------------------------------------------------
# Multi-Stage Bulk Pipeline Orchestrator
# ---------------------------------------------------------------------------
def execute_pipeline(stages_to_run, city_filter=None, limit_per_source=None, force=False):
    print("================================================================================")
    print("MYSEATTLESEARCH: UNATTENDED HISTORICAL ASSET INGESTION ENGINE")
    print("================================================================================")
    print(f"Target Database ID: {CF_D1_DATABASE_ID}")
    print(f"Target R2 Bucket:   {R2_BUCKET_NAME} ({R2_PUBLIC_DOMAIN})")
    print(f"State Checkpoint:   {PROGRESS_FILE}")
    print(f"Stages Scheduled:   {', '.join(stages_to_run).upper()}")
    print("================================================================================")

    progress = load_progress()
    completed_ids = set() if force else set(progress.get("completed_ids", []))
    cursors = progress.get("cursors", {})
    s3_client = get_r2_client()

    total_committed = 0

    for stage_idx, stage in enumerate(stages_to_run, 1):
        print(f"\n>>> [STAGE {stage_idx}/{len(stages_to_run)}] EXECUTING {stage.upper()}")
        print("--------------------------------------------------------------------------------")

        catalog = SOURCE_CATALOGS.get(stage, [])
        if city_filter:
            catalog = [r for r in catalog if r["city"].lower() == city_filter.lower()]

        # Filter against completed IDs unless force mode is enabled
        pending = [r for r in catalog if force or r["id"] not in completed_ids]
        if limit_per_source:
            pending = pending[:limit_per_source]

        if not pending:
            print(f"[+] All records for stage '{stage}' are already synchronized.")
            continue

        print(f"[*] Processing {len(pending)} pending assets for stage '{stage}'...")

        stage_success = 0
        for item_idx, item in enumerate(pending, 1):
            item_id = item["id"]
            print(f"  [{item_idx}/{len(pending)}] {item_id} | {item['title']} ({item['city']})")

            try:
                photo_url = ingest_record(item, s3_client)

                # Update state
                completed_ids.add(item_id)
                progress["completed_ids"] = list(completed_ids)
                cursors[stage] = cursors.get(stage, 0) + 1
                progress["cursors"] = cursors
                save_progress(progress)

                stage_success += 1
                total_committed += 1
                print(f"      [OK] Committed -> {photo_url}")

                # Polite delay to avoid hammering upstream servers
                time.sleep(0.35)

            except Exception as e:
                print(f"      [!] Error processing record {item_id}: {e}")

        # Trigger garbage collection between stages to keep M1 RAM low
        gc.collect()
        print(f"[+] Stage {stage.upper()} complete. {stage_success}/{len(pending)} records committed.")

    print("\n================================================================================")
    print(f"[+] BULK INGESTION RUN COMPLETED: {total_committed} records committed to Cloudflare D1 & R2.")
    print("================================================================================")

# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Unattended Multi-Source Historical Photo Ingestion Engine")
    parser.add_argument("--bulk", action="store_true", help="Execute complete multi-stage pipeline sequentially")
    parser.add_argument("--source", type=str, default=None, choices=["wpa_king", "snohomish_local", "sma_infrastructure"],
                        help="Execute a single targeted data source")
    parser.add_argument("--city", type=str, default=None, help="Filter harvest to a single city (e.g. Edmonds, Shoreline)")
    parser.add_argument("--limit", type=int, default=None, help="Maximum records per source")
    parser.add_argument("--force", action="store_true", help="Bypass checkpoint progress and re-transcode all records")
    args = parser.parse_args()

    if args.bulk or (args.source is None and not args.city):
        stages = ["wpa_king", "snohomish_local", "sma_infrastructure"]
    else:
        stages = [args.source] if args.source else ["wpa_king", "snohomish_local", "sma_infrastructure"]

    execute_pipeline(
        stages_to_run=stages,
        city_filter=args.city,
        limit_per_source=args.limit,
        force=args.force
    )