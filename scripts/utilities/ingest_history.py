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
CF_D1_DATABASE_ID = config.get("CF_D1_DATABASE_ID") or config.get("CF_DATABASE_PARCELDATA_ID")
CF_API_TOKEN = config.get("CF_API_TOKEN") or config.get("CF_D1_API_TOKEN")
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
# Live Archival Repositories & Standardized Category Queries
# ---------------------------------------------------------------------------
SOURCE_SEARCH_QUERIES = {
    "wpa_king": 'incategory:"Black and white photographs of Seattle|Seattle in the 1930s|History of Seattle"',
    "snohomish_local": '"Edmonds, Washington" OR "Snohomish, Washington" OR "Mukilteo, Washington"',
    "sma_infrastructure": 'incategory:"Seattle Municipal Archives via Flickr"'
}

SOURCE_ARCHIVE_NAMES = {
    "wpa_king": "Puget Sound Regional Archives / Washington State Digital Archives",
    "snohomish_local": "Snohomish County Historical Collections / UW Libraries",
    "sma_infrastructure": "Seattle Municipal Archives"
}

SOURCE_PREFIXES = {
    "wpa_king": "kc-wpa",
    "snohomish_local": "sno-hist",
    "sma_infrastructure": "sma-infra"
}

def fetch_live_archive_records(source_key, offset=0, limit=25):
    """
    Queries digital archive APIs via MediaWiki generator search,
    extracting master high-res scans, embedded metadata, dates, and coordinates.
    """
    search_query = SOURCE_SEARCH_QUERIES.get(source_key)
    if not search_query:
        return [], offset

    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": search_query,
        "gsrnamespace": "6",
        "gsrlimit": str(limit),
        "gsroffset": str(offset),
        "prop": "imageinfo|coordinates",
        "iiprop": "url|extmetadata|dimensions|mime",
        "format": "json"
    }

    api_url = f"https://commons.wikimedia.org/w/api.php?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(api_url, headers=HTTP_HEADERS)

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[!] Live query failed for {source_key}: {e}")
        return [], offset

    query_obj = data.get("query", {})
    pages = query_obj.get("pages", {})
    if not pages:
        return [], offset

    sorted_pages = sorted(pages.values(), key=lambda p: p.get("index", 0))

    continue_obj = data.get("continue", {})
    next_offset = continue_obj.get("gsroffset", offset + len(sorted_pages))

    items = []
    prefix = SOURCE_PREFIXES.get(source_key, "hist")
    source_archive = SOURCE_ARCHIVE_NAMES.get(source_key, "Washington State Archives")

    for page in sorted_pages:
        page_id = str(page.get("pageid"))
        raw_file_title = page.get("title", "").replace("File:", "").strip()
        imageinfo = page.get("imageinfo", [])
        if not imageinfo:
            continue

        ii = imageinfo[0]
        direct_url = ii.get("url")
        if not direct_url:
            continue

        base_name = os.path.splitext(raw_file_title)[0]
        clean_title = re.sub(r'[\(\)_]+', ' ', base_name).strip()
        clean_slug = re.sub(r'[^a-zA-Z0-9]', '-', clean_title[:28]).strip('-').lower()
        item_id = f"{prefix}-{clean_slug}-{page_id}"

        extmetadata = ii.get("extmetadata", {})
        raw_desc = extmetadata.get("ImageDescription", {}).get("value", "")
        clean_desc = re.sub(r'<[^>]+>', ' ', raw_desc).strip()
        clean_desc = re.sub(r'\s+', ' ', clean_desc)
        if not clean_desc or len(clean_desc) < 10:
            clean_desc = clean_title

        date_val = extmetadata.get("DateTimeOriginal", {}).get("value", "") or extmetadata.get("DateTime", {}).get("value", "")
        year_match = re.search(r'\b(18\d{2}|19\d{2})\b', f"{date_val} {clean_desc} {clean_title}")
        year_found = int(year_match.group(1)) if year_match else None

        lat = None
        lng = None
        if "coordinates" in page and page["coordinates"]:
            lat = float(page["coordinates"][0].get("lat", 0.0))
            lng = float(page["coordinates"][0].get("lon", 0.0))
        elif "GPSLatitude" in extmetadata and "GPSLongitude" in extmetadata:
            try:
                lat = float(extmetadata["GPSLatitude"]["value"])
                lng = float(extmetadata["GPSLongitude"]["value"])
            except (ValueError, TypeError):
                pass

        combined_text = f"{clean_title} {clean_desc}".lower()
        city = "Seattle"
        county = "King"
        neighborhood = None

        if "edmonds" in combined_text:
            city = "Edmonds"
            county = "Snohomish"
            neighborhood = "Edmonds Bowl"
            if not lat: lat, lng = 47.8107, -122.3774
        elif "snohomish" in combined_text:
            city = "Snohomish"
            county = "Snohomish"
            neighborhood = "Historic Snohomish"
            if not lat: lat, lng = 47.9129, -122.0982
        elif "mukilteo" in combined_text:
            city = "Mukilteo"
            county = "Snohomish"
            neighborhood = "Waterfront"
            if not lat: lat, lng = 47.9493, -122.3046
        elif "lynnwood" in combined_text:
            city = "Lynnwood"
            county = "Snohomish"
            neighborhood = "Interurban Corridor"
            if not lat: lat, lng = 47.8209, -122.3151
        elif "shoreline" in combined_text or "richmond beach" in combined_text:
            city = "Shoreline"
            county = "King"
            neighborhood = "Richmond Beach" if "richmond" in combined_text else "Shoreline"
            if not lat: lat, lng = 47.7560, -122.3457
        elif "lake forest park" in combined_text:
            city = "Lake Forest Park"
            county = "King"
            neighborhood = "Waterfront"
            if not lat: lat, lng = 47.7540, -122.2779
        elif "ballard" in combined_text:
            city = "Seattle"
            county = "King"
            neighborhood = "Ballard"
            if not lat: lat, lng = 47.6769, -122.3860
        elif "capitol hill" in combined_text:
            city = "Seattle"
            county = "King"
            neighborhood = "Capitol Hill"
            if not lat: lat, lng = 47.6253, -122.3168
        elif "pioneer square" in combined_text:
            city = "Seattle"
            county = "King"
            neighborhood = "Pioneer Square"
            if not lat: lat, lng = 47.6015, -122.3325
        else:
            if source_key == "snohomish_local":
                city = "Edmonds"
                county = "Snohomish"
                if not lat: lat, lng = 47.8107, -122.3774
            else:
                city = "Seattle"
                county = "King"
                if not lat: lat, lng = 47.6062, -122.3321

        if lat and lat > 47.78 and county == "King":
            county = "Snohomish"

        parcel_number = None
        if source_key == "wpa_king":
            dataset_type = "wpa_property"
            pin_match = re.search(r'\b\d{10}\b', clean_desc)
            if pin_match:
                parcel_number = pin_match.group(0)
        elif source_key == "snohomish_local":
            dataset_type = "wpa_property"
        else:
            dataset_type = "wsdot_infrastructure"

        items.append({
            "id": item_id,
            "dataset_type": dataset_type,
            "parcel_number": parcel_number,
            "title": clean_title[:90],
            "city": city,
            "county": county,
            "neighborhood": neighborhood,
            "year_built": year_found,
            "year_photo": year_found,
            "architectural_style": "Archival Photographic Record",
            "notes": clean_desc[:250],
            "lat": round(lat, 6),
            "lng": round(lng, 6),
            "source_archive": source_archive,
            "source_record_id": f"COMMONS-{page_id}",
            "source_master_url": direct_url
        })

    return items, next_offset

# ---------------------------------------------------------------------------
# Core Ingestion Engine
# ---------------------------------------------------------------------------
def ingest_record(item, s3_client):
    """Processes, transcodes, uploads, and commits a single historical asset."""
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
# Multi-Stage Bulk Pipeline Orchestrator
# ---------------------------------------------------------------------------
def execute_pipeline(stages_to_run, city_filter=None, limit_per_source=None, force=False, is_bulk=False):
    print("================================================================================")
    print("MYSEATTLESEARCH: LIVE HISTORICAL ASSET INGESTION ENGINE")
    print("================================================================================")
    print(f"Target Database ID: {CF_D1_DATABASE_ID}")
    print(f"Target R2 Bucket:   {R2_BUCKET_NAME} ({R2_PUBLIC_DOMAIN})")
    print(f"State Checkpoint:   {PROGRESS_FILE}")
    print(f"Stages Scheduled:   {', '.join(stages_to_run).upper()}")
    if limit_per_source:
        print(f"Record Target:      {limit_per_source} committed records per stage")
    print("================================================================================")

    progress = load_progress()
    completed_ids = set() if force else set(progress.get("completed_ids", []))
    cursors = progress.get("cursors", {})
    s3_client = get_r2_client()

    total_committed = 0

    for stage_idx, stage in enumerate(stages_to_run, 1):
        print(f"\n>>> [STAGE {stage_idx}/{len(stages_to_run)}] HARVESTING LIVE: {stage.upper()}")
        print("--------------------------------------------------------------------------------")

        stage_committed = 0
        current_offset = 0 if force else cursors.get(stage, 0)

        while True:
            batch_fetch_size = max(25, limit_per_source) if limit_per_source else 25

            print(f"[*] Querying repository for '{stage}' at offset {current_offset}...")
            live_items, next_offset = fetch_live_archive_records(stage, offset=current_offset, limit=batch_fetch_size)

            if not live_items:
                print(f"[+] Reached end of live repository records for '{stage}'.")
                break

            if city_filter:
                live_items = [r for r in live_items if r["city"].lower() == city_filter.lower()]

            pending = [r for r in live_items if force or r["id"] not in completed_ids]

            if not pending:
                if next_offset == current_offset:
                    break
                print(f"[*] Advancing offset from {current_offset} -> {next_offset} to find new candidates...")
                current_offset = next_offset
                cursors[stage] = current_offset
                progress["cursors"] = cursors
                save_progress(progress)
                continue

            for item in pending:
                item_id = item["id"]
                print(f"  [{stage_committed + 1}] {item_id} | {item['title']} ({item['city']}, {item['county']} County)")

                try:
                    photo_url = ingest_record(item, s3_client)

                    completed_ids.add(item_id)
                    progress["completed_ids"] = list(completed_ids)
                    save_progress(progress)

                    stage_success_msg = f"      [OK] Committed -> {photo_url}"
                    if item.get("parcel_number"):
                        stage_success_msg += f" (Parcel: {item['parcel_number']})"
                    print(stage_success_msg)

                    stage_committed += 1
                    total_committed += 1

                    time.sleep(0.35)

                    if limit_per_source and stage_committed >= limit_per_source:
                        break

                except Exception as e:
                    print(f"      [!] Error processing record {item_id}: {e}")

            current_offset = next_offset
            cursors[stage] = current_offset
            progress["cursors"] = cursors
            save_progress(progress)

            if limit_per_source and stage_committed >= limit_per_source:
                break

            if not is_bulk and limit_per_source is None:
                break

        gc.collect()
        print(f"[+] Stage {stage.upper()} complete. {stage_committed} records committed.")

    print("\n================================================================================")
    print(f"[+] INGESTION RUN FINISHED: {total_committed} live records committed to Cloudflare D1 & R2.")
    print("================================================================================")

# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Live Multi-Source Historical Photo Ingestion Engine")
    parser.add_argument("--bulk", action="store_true", help="Execute complete multi-stage pipeline continuously until end of repositories")
    parser.add_argument("--source", type=str, default="all", choices=["all", "wpa_king", "snohomish_local", "sma_infrastructure"],
                        help="Target data source (default: all)")
    parser.add_argument("--city", type=str, default=None, help="Filter harvest to a single city (e.g. Edmonds, Shoreline)")
    parser.add_argument("--limit", type=int, default=None, help="Maximum records per source (e.g. 3)")
    parser.add_argument("--force", action="store_true", help="Bypass checkpoint cache to test fresh records")
    args = parser.parse_args()

    if args.source == "all":
        stages = ["wpa_king", "snohomish_local", "sma_infrastructure"]
    else:
        stages = [args.source]

    execute_pipeline(
        stages_to_run=stages,
        city_filter=args.city,
        limit_per_source=args.limit,
        force=args.force,
        is_bulk=args.bulk
    )