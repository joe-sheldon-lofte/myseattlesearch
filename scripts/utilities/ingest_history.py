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
from PIL import Image

warnings.filterwarnings("ignore", category=DeprecationWarning)
# Treat decompression bomb warnings as errors so oversized files skip cleanly
warnings.filterwarnings("error", category=Image.DecompressionBombWarning)

# Maximum raster dimension allowed before download (75 Megapixels)
MAX_PIXEL_CEILING = 75_000_000

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
    "User-Agent": "MySeattleSearch-History-Harvester/6.0 (CirrusSearch-Uncapped; info@myseattlesearch.com)"
}

# ---------------------------------------------------------------------------
# Strict Geographic Bounding Box (King & Snohomish Counties + 3mi Buffer)
# ---------------------------------------------------------------------------
BOUNDING_BOX = {
    "lat_min": 47.1000,   # South King County buffer (Pierce Co line)
    "lat_max": 48.3500,   # North Snohomish County buffer (Skagit Co line)
    "lng_min": -122.6000,  # West boundary (Puget Sound / Vashon buffer)
    "lng_max": -121.0000   # East boundary (Cascade Mountain Crest buffer)
}

def is_inside_bounding_box(lat, lng):
    """Returns True only if coordinates fall cleanly inside King/Snohomish boundaries."""
    if lat is None or lng is None:
        return False
    return (BOUNDING_BOX["lat_min"] <= lat <= BOUNDING_BOX["lat_max"] and
            BOUNDING_BOX["lng_min"] <= lng <= BOUNDING_BOX["lng_max"])

# ---------------------------------------------------------------------------
# Pre-Seeded Municipal & Neighborhood Centroids (Zero-Scan Memory Cache)
# ---------------------------------------------------------------------------
CENTROIDS = {
    # Snohomish County Municipalities
    "edmonds": (47.8107, -122.3774),
    "snohomish": (47.9128, -122.0933),
    "mukilteo": (47.9030, -122.3043),
    "lynnwood": (47.8209, -122.3151),
    "everett": (47.9789, -122.2021),
    "marysville": (48.0518, -122.1771),
    "mountlake-terrace": (47.7884, -122.3085),
    "mill-creek": (47.8604, -122.2046),
    "lake-stevens": (48.0151, -122.0635),
    "arlington": (48.1987, -122.1251),
    "monroe": (47.8557, -121.9699),
    "stanwood": (48.2415, -122.3707),
    "granite-falls": (48.0837, -121.9696),
    "sultan": (47.8623, -121.8157),
    "gold-bar": (47.8584, -121.6948),
    "brier": (47.7801, -122.2818),
    "woodway": (47.7884, -122.3854),
    "darrington": (48.2559, -121.6026),
    "tulalip": (48.0645, -122.2846),
    "index": (47.8207, -121.5540),
    "silvana": (48.2012, -122.2504),

    # King County Municipalities
    "seattle": (47.6062, -122.3321),
    "bellevue": (47.6101, -122.2015),
    "renton": (47.4829, -122.2171),
    "kent": (47.3809, -122.2348),
    "auburn": (47.3073, -122.2284),
    "kirkland": (47.6815, -122.2087),
    "redmond": (47.6740, -122.1215),
    "federal-way": (47.3223, -122.3126),
    "federaly": (47.3223, -122.3126),
    "sammamish": (47.6163, -122.0356),
    "issaquah": (47.5301, -122.0326),
    "shoreline": (47.7560, -122.3457),
    "woodinville": (47.7543, -122.1635),
    "bothell": (47.7601, -122.2054),
    "maple-valley": (47.3654, -122.0437),
    "mercer-island": (47.5707, -122.2221),
    "burien": (47.4704, -122.3468),
    "enumclaw": (47.2043, -121.9915),
    "des-moines": (47.4018, -122.3243),
    "kenmore": (47.7573, -122.2440),
    "covington": (47.3648, -122.0918),
    "north-bend": (47.4957, -121.7868),
    "vashon": (47.4476, -122.4632),
    "snoqualmie": (47.5287, -121.8254),
    "duvall": (47.7423, -121.9857),
    "seatac": (47.4439, -122.2961),
    "tukwila": (47.4740, -122.2610),
    "newcastle": (47.5390, -122.1671),
    "black-diamond": (47.3087, -122.0032),
    "lake-forest-park": (47.7537, -122.2776),
    "carnation": (47.6479, -121.9118),
    "normandy-park": (47.4390, -122.3396),
    "fall-city": (47.5670, -121.8987),
    "pacific": (47.2645, -122.2504),
    "ravensdale": (47.3548, -121.9915),
    "medina": (47.6209, -122.2348),
    "clyde-hill": (47.6301, -122.2179),
    "algona": (47.2815, -122.2490),
    "yarrow-point": (47.6454, -122.2157),
    "hunts-point": (47.6395, -122.2271),
    "beaux-arts-village": (47.5884, -122.1996),
    "skykomish": (47.7095, -121.3598),

    # Common Sub-Neighborhoods (Seattle & Suburbs)
    "ballard": (47.6677, -122.3846),
    "capitol-hill": (47.6253, -122.3222),
    "pioneer-square": (47.6015, -122.3343),
    "fremont": (47.6505, -122.3499),
    "queen-anne": (47.6373, -122.3571),
    "green-lake": (47.6797, -122.3275),
    "view-ridge": (47.6837, -122.2687),
    "mount-baker": (47.5815, -122.2932),
    "magnolia": (47.6401, -122.3999),
    "west-seattle": (47.5615, -122.3867),
    "wallingford": (47.6592, -122.3357),
    "georgetown": (47.5415, -122.3243),
    "columbia-city": (47.5604, -122.2857),
    "south-lake-union": (47.6221, -122.3364),
    "belltown": (47.6145, -122.3457),
    "first-hill": (47.6101, -122.3243),
    "international-district": (47.5987, -122.3243),
    "beacon-hill": (47.5798, -122.3126),
    "ravenna": (47.6765, -122.3023),
    "phinney-ridge": (47.6740, -122.3548),
    "madrona": (47.6123, -122.2887),
    "leschi": (47.6015, -122.2871),
    "madison-park": (47.6345, -122.2776),
    "wedgwood": (47.6912, -122.2907),
    "laurelhurst": (47.6592, -122.2776),
    "bitter-lake": (47.7245, -122.3548),
    "crown-hill": (47.6954, -122.3707),
    "greenwood": (47.6912, -122.3548),
    "interbay": (47.6454, -122.3776),
    "montlake": (47.6415, -122.3043),
    "richmond-beach": (47.7687, -122.3854),
    "edmonds-bowl": (47.8107, -122.3774),
    "silver-lake": (47.8945, -122.2157)
}

# ---------------------------------------------------------------------------
# Authoritative Slug-To-City-Slug & County Mapping
# ---------------------------------------------------------------------------
SLUG_TAXONOMY_MAP = {
    # Snohomish County
    "edmonds": ("edmonds", "Snohomish"),
    "snohomish": ("snohomish", "Snohomish"),
    "mukilteo": ("mukilteo", "Snohomish"),
    "lynnwood": ("lynnwood", "Snohomish"),
    "everett": ("everett", "Snohomish"),
    "marysville": ("marysville", "Snohomish"),
    "mountlake-terrace": ("mountlake-terrace", "Snohomish"),
    "mill-creek": ("mill-creek", "Snohomish"),
    "lake-stevens": ("lake-stevens", "Snohomish"),
    "arlington": ("arlington", "Snohomish"),
    "monroe": ("monroe", "Snohomish"),
    "stanwood": ("stanwood", "Snohomish"),
    "granite-falls": ("granite-falls", "Snohomish"),
    "sultan": ("sultan", "Snohomish"),
    "gold-bar": ("gold-bar", "Snohomish"),
    "brier": ("brier", "Snohomish"),
    "woodway": ("woodway", "Snohomish"),
    "darrington": ("darrington", "Snohomish"),
    "tulalip": ("tulalip", "Snohomish"),
    "index": ("index", "Snohomish"),
    "silvana": ("silvana", "Snohomish"),
    "edmonds-bowl": ("edmonds", "Snohomish"),
    "silver-lake": ("everett", "Snohomish"),

    # King County
    "seattle": ("seattle", "King"),
    "bellevue": ("bellevue", "King"),
    "renton": ("renton", "King"),
    "kent": ("kent", "King"),
    "auburn": ("auburn", "King"),
    "kirkland": ("kirkland", "King"),
    "redmond": ("redmond", "King"),
    "federal-way": ("federal-way", "King"),
    "federaly": ("federal-way", "King"),
    "sammamish": ("sammamish", "King"),
    "issaquah": ("issaquah", "King"),
    "shoreline": ("shoreline", "King"),
    "woodinville": ("woodinville", "King"),
    "maple-valley": ("maple-valley", "King"),
    "mercer-island": ("mercer-island", "King"),
    "burien": ("burien", "King"),
    "enumclaw": ("enumclaw", "King"),
    "des-moines": ("des-moines", "King"),
    "kenmore": ("kenmore", "King"),
    "covington": ("covington", "King"),
    "north-bend": ("north-bend", "King"),
    "vashon": ("vashon", "King"),
    "snoqualmie": ("snoqualmie", "King"),
    "duvall": ("duvall", "King"),
    "seatac": ("seatac", "King"),
    "tukwila": ("tukwila", "King"),
    "newcastle": ("newcastle", "King"),
    "black-diamond": ("black-diamond", "King"),
    "lake-forest-park": ("lake-forest-park", "King"),
    "carnation": ("carnation", "King"),
    "normandy-park": ("normandy-park", "King"),
    "fall-city": ("fall-city", "King"),
    "pacific": ("pacific", "King"),
    "ravensdale": ("ravensdale", "King"),
    "medina": ("medina", "King"),
    "clyde-hill": ("clyde-hill", "King"),
    "algona": ("algona", "King"),
    "yarrow-point": ("yarrow-point", "King"),
    "hunts-point": ("hunts-point", "King"),
    "beaux-arts-village": ("beaux-arts-village", "King"),
    "skykomish": ("skykomish", "King"),

    # Common Sub-Neighborhoods
    "ballard": ("seattle", "King"),
    "capitol-hill": ("seattle", "King"),
    "pioneer-square": ("seattle", "King"),
    "fremont": ("seattle", "King"),
    "queen-anne": ("seattle", "King"),
    "green-lake": ("seattle", "King"),
    "view-ridge": ("seattle", "King"),
    "mount-baker": ("seattle", "King"),
    "magnolia": ("seattle", "King"),
    "west-seattle": ("seattle", "King"),
    "wallingford": ("seattle", "King"),
    "georgetown": ("seattle", "King"),
    "columbia-city": ("seattle", "King"),
    "south-lake-union": ("seattle", "King"),
    "belltown": ("seattle", "King"),
    "first-hill": ("seattle", "King"),
    "international-district": ("seattle", "King"),
    "beacon-hill": ("seattle", "King"),
    "ravenna": ("seattle", "King"),
    "phinney-ridge": ("seattle", "King"),
    "madrona": ("seattle", "King"),
    "leschi": ("seattle", "King"),
    "madison-park": ("seattle", "King"),
    "wedgwood": ("seattle", "King"),
    "laurelhurst": ("seattle", "King"),
    "bitter-lake": ("seattle", "King"),
    "crown-hill": ("seattle", "King"),
    "greenwood": ("seattle", "King"),
    "interbay": ("seattle", "King"),
    "montlake": ("seattle", "King"),
    "richmond-beach": ("shoreline", "King")
}

# ---------------------------------------------------------------------------
# Institutional Boilerplate Sanitization & Out-of-Area Filters
# ---------------------------------------------------------------------------
OUT_OF_AREA_EXCLUSIONS = [
    "fairbanks", "alaska", "yukon", "klondike", "nome", "juneau", "skagway",
    "spokane", "cheney", "pomeroy", "walla walla", "yakima", "tri-cities",
    "bellingham", "olympia", "portland", "oregon", "california", "idaho",
    "british columbia", "canada"
]

def strip_institutional_boilerplate(text):
    """Strips university/museum donor credits that falsely inject 'Seattle' into non-Seattle photos."""
    if not text:
        return ""
    cleaned = re.sub(r'University of Washington Libraries[^\.\;]*', '', text, flags=re.IGNORECASE)
    cleaned = re.sub(r'Museum of History & Industry[^\.\;]*', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'MOHAI[^\.\;]*', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'Asahel Curtis \([^\)]*Seattle[^\)]*\)', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'Special Collections Division[^\.\;]*', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'Seattle Municipal Archives via Flickr', '', cleaned, flags=re.IGNORECASE)
    return cleaned

def is_out_of_area(title, desc):
    """Rejects photos whose subject or location explicitly references out-of-area regions."""
    combined = f"{title} {desc}".lower()
    for kw in OUT_OF_AREA_EXCLUSIONS:
        if re.search(r'\b' + re.escape(kw) + r'\b', combined):
            return True
    return False

def normalize_slug(slug):
    if not slug:
        return None
    clean = str(slug).strip().lower().strip(",. ")
    if clean == "federaly":
        return "federal-way"
    return clean

def resolve_location(slug, lat=None):
    """
    Returns (city_slug, county_name) where city_slug is ALWAYS an incorporated
    city slug (e.g. 'seattle', 'shoreline', 'edmonds', 'federal-way').
    """
    clean = normalize_slug(slug)
    if clean == "bothell":
        if lat and lat > 47.78:
            return "bothell", "Snohomish"
        return "bothell", "King"

    if clean in SLUG_TAXONOMY_MAP:
        return SLUG_TAXONOMY_MAP[clean]

    return None, None

def match_slug_from_text(title, desc):
    """Matches known municipal or neighborhood slug, checking title first with sanitized text."""
    clean_title = strip_institutional_boilerplate(title).lower()
    for slug_candidate in SLUG_TAXONOMY_MAP.keys():
        readable = slug_candidate.replace("-", " ")
        if re.search(r'\b' + re.escape(readable) + r'\b', clean_title):
            return slug_candidate

    clean_desc = strip_institutional_boilerplate(desc).lower()
    for slug_candidate in SLUG_TAXONOMY_MAP.keys():
        readable = slug_candidate.replace("-", " ")
        if re.search(r'\b' + re.escape(readable) + r'\b', clean_desc):
            return slug_candidate

    return None

def find_nearest_slug_by_coords(lat, lng):
    """Resolves coordinates inside bounding box to the closest footprint municipality."""
    best_slug = None
    min_dist = float("inf")
    for slug, (c_lat, c_lng) in CENTROIDS.items():
        dist = (lat - c_lat) ** 2 + (lng - c_lng) ** 2
        if dist < min_dist:
            min_dist = dist
            best_slug = slug
    return best_slug or "seattle"

# ---------------------------------------------------------------------------
# 5-Stage Institutional Harvest Configuration (CirrusSearch OR Syntax)
# ---------------------------------------------------------------------------
SOURCE_CONFIGS = {
    "residential_properties": {
        "query": 'incategory:"Houses in Seattle" OR incategory:"Houses in King County, Washington" OR incategory:"Seattle Department of Neighborhoods Historic Sites"',
        "prefix": "res-prop",
        "archive": "Seattle Department of Neighborhoods / King County Historic Resources",
        "dataset_type": "residential_property"
    },
    "historic_districts": {
        "query": 'incategory:"National Register of Historic Places in King County, Washington" OR incategory:"National Register of Historic Places in Snohomish County, Washington" OR incategory:"Historic district contributing properties in Washington (state)"',
        "prefix": "hist-dist",
        "archive": "National Register of Historic Places / WA DAHP",
        "dataset_type": "historic_district"
    },
    "photographer_surveys": {
        "query": 'incategory:"Photographs by Asahel Curtis" OR incategory:"Photographs by Webster & Stevens" OR incategory:"Webster & Stevens"',
        "prefix": "photo-surv",
        "archive": "Puget Sound Historical Survey Collections (Asahel Curtis / Webster & Stevens)",
        "dataset_type": "photographer_survey"
    },
    "snohomish_local": {
        "query": 'incategory:"Buildings in Snohomish County, Washington" OR incategory:"Snohomish County, Washington"',
        "prefix": "sno-hist",
        "archive": "Snohomish County Historical Collections / UW Libraries Special Collections",
        "dataset_type": "civic_landmark"
    },
    "sma_infrastructure": {
        "query": 'incategory:"Seattle Municipal Archives via Flickr"',
        "prefix": "sma-infra",
        "archive": "Seattle Municipal Archives (Record Series 2613-07)",
        "dataset_type": "wsdot_infrastructure"
    }
}

ALL_SOURCES = list(SOURCE_CONFIGS.keys())

# ---------------------------------------------------------------------------
# Resumable Checkpoint & Cursor Management
# ---------------------------------------------------------------------------
def load_progress():
    default_state = {
        "completed_ids": [],
        "cursors": {src: 0 for src in ALL_SOURCES}
    }
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "completed_ids" not in data:
                    data["completed_ids"] = []
                if "cursors" not in data:
                    data["cursors"] = default_state["cursors"]
                for src in ALL_SOURCES:
                    if src not in data["cursors"]:
                        data["cursors"][src] = 0
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
# Cloudflare D1 Query Engine with Exponential Retry Backoff
# ---------------------------------------------------------------------------
def execute_d1_query(sql, params=None, max_retries=3):
    if not all([CF_ACCOUNT_ID, CF_D1_DATABASE_ID, CF_API_TOKEN]):
        raise ValueError("Missing D1 credentials in .dev.vars")

    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/d1/database/{CF_D1_DATABASE_ID}/query"
    payload = {"sql": sql}
    if params:
        payload["params"] = params

    for attempt in range(1, max_retries + 1):
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
                    errs = res_data.get("errors", [])
                    if any(e.get("code") == 7429 for e in errs) and attempt < max_retries:
                        time.sleep(2.5 * attempt)
                        continue
                    raise RuntimeError(f"D1 Query Failed: {errs}")
                return res_data
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8")
            if (e.code == 429 or "7429" in err_body) and attempt < max_retries:
                time.sleep(2.5 * attempt)
                continue
            raise RuntimeError(f"D1 HTTP {e.code}: {err_body}")

# ---------------------------------------------------------------------------
# Targeted D1 Index Lookups (Single-Row Point Queries Only)
# ---------------------------------------------------------------------------
def lookup_base_pin(pin):
    """Indexed primary key lookup against base table."""
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
    """Indexed address lookup against base table."""
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

# ---------------------------------------------------------------------------
# Strict Zero-Fallback Image Processor & Validator
# ---------------------------------------------------------------------------
def process_and_transcode_image(item, max_retries=3):
    """
    Downloads and strictly verifies authentic archival images in RAM.
    Zero synthetic cards: rejects non-200s, non-image MIME types, and corrupt bytes.
    Returns (photo_buf, thumb_buf) on success, or (None, None) on any failure.
    """
    direct_url = item.get("source_master_url")
    if not direct_url:
        return None, None

    img_bytes = None
    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(direct_url, headers=HTTP_HEADERS)
            with urllib.request.urlopen(req, timeout=18) as resp:
                if resp.status != 200:
                    raise ValueError(f"HTTP status {resp.status}")
                
                content_type = resp.headers.get("Content-Type", "").lower()
                valid_mimes = ["image/jpeg", "image/png", "image/webp", "image/tiff"]
                if not any(m in content_type for m in valid_mimes):
                    raise ValueError(f"Invalid MIME content-type: {content_type}")
                
                img_bytes = resp.read()
                break
        except Exception as e:
            if attempt == max_retries:
                print(f"    [!] Download failed after {max_retries} attempts ({e}). Skipping record.")
                return None, None
            time.sleep(1.0 * attempt)

    if not img_bytes:
        return None, None

    try:
        orig_img = Image.open(io.BytesIO(img_bytes))
        orig_img.load()  # Force load raster data into memory to verify integrity
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as e:
        print(f"    [SKIP] Image exceeds decompression safe limits ({e}). Skipping record.")
        del img_bytes
        return None, None
    except Exception as e:
        print(f"    [!] Image raster verification failed ({e}). Skipping record.")
        del img_bytes
        return None, None

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

    del orig_img, photo_img, thumb_img, img_bytes
    return photo_buf, thumb_buf

# ---------------------------------------------------------------------------
# Category Query & Strict Zero-Fallback Spatial Gate
# ---------------------------------------------------------------------------
def fetch_live_archive_records(source_key, offset=0, limit=50):
    cfg = SOURCE_CONFIGS.get(source_key)
    if not cfg:
        return [], offset

    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": cfg["query"],
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
        print(f"[!] API query failed for {source_key}: {e}")
        return [], offset

    pages = data.get("query", {}).get("pages", {})
    if not pages:
        return [], offset

    sorted_pages = sorted(pages.values(), key=lambda p: p.get("index", 0))
    next_offset = data.get("continue", {}).get("gsroffset", offset + len(sorted_pages))

    items = []
    prefix = cfg["prefix"]
    source_archive = cfg["archive"]

    for page in sorted_pages:
        page_id = str(page.get("pageid"))
        raw_file_title = page.get("title", "").replace("File:", "").strip()
        imageinfo = page.get("imageinfo", [])
        if not imageinfo:
            continue

        ii = imageinfo[0]
        direct_url = ii.get("url")
        mime = ii.get("mime", "").lower()
        if not direct_url or not mime.startswith("image/"):
            continue

        # Pre-Download Dimension Guard (Skip ultra-massive composite scans before downloading)
        width = ii.get("width", 0)
        height = ii.get("height", 0)
        if width and height and (width * height > MAX_PIXEL_CEILING):
            print(f"    [SKIP] Exceeds {MAX_PIXEL_CEILING}px ceiling ({width}x{height}): {raw_file_title[:45]}")
            continue

        base_name = os.path.splitext(raw_file_title)[0]
        clean_title = re.sub(r'[\(\)_]+', ' ', base_name).strip()
        clean_slug = re.sub(r'[^a-zA-Z0-9]', '-', clean_title[:28]).strip('-').lower()
        item_id = f"{prefix}-{clean_slug}-{page_id}"

        extmetadata = ii.get("extmetadata", {})
        raw_desc = extmetadata.get("ImageDescription", {}).get("value", "")
        clean_desc = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', raw_desc)).strip()
        if not clean_desc or len(clean_desc) < 10:
            clean_desc = clean_title

        # Check for explicit out-of-area entities
        if is_out_of_area(clean_title, clean_desc):
            continue

        date_val = extmetadata.get("DateTimeOriginal", {}).get("value", "") or extmetadata.get("DateTime", {}).get("value", "")
        year_match = re.search(r'\b(18\d{2}|19\d{2})\b', f"{date_val} {clean_desc} {clean_title}")
        year_found = int(year_match.group(1)) if year_match else None

        combined_text = f"{clean_title} {clean_desc}"

        # -------------------------------------------------------------------
        # SPATIAL FILTERING & ZERO-FALLBACK VALIDATION GATE
        # -------------------------------------------------------------------
        lat, lng = None, None
        if "coordinates" in page and page["coordinates"]:
            lat = float(page["coordinates"][0].get("lat", 0.0))
            lng = float(page["coordinates"][0].get("lon", 0.0))
        elif "GPSLatitude" in extmetadata and "GPSLongitude" in extmetadata:
            try:
                lat = float(extmetadata["GPSLatitude"]["value"])
                lng = float(extmetadata["GPSLongitude"]["value"])
            except Exception:
                pass

        matched_slug = None
        parcel_number = None
        base_record = None
        dataset_type = cfg["dataset_type"]

        # CASE 1: Archive scan HAS native GPS coordinates
        if lat is not None and lng is not None:
            # 1. Bounding box gate: strictly reject anything outside King & Snohomish counties
            if not is_inside_bounding_box(lat, lng):
                continue

            # 2. Inside bounding box: determine municipal entity
            matched_slug = match_slug_from_text(clean_title, clean_desc)
            if not matched_slug:
                matched_slug = find_nearest_slug_by_coords(lat, lng)

            # Check if property PIN can be attached
            pin_match = re.search(r'\b\d{10}\b', combined_text)
            if pin_match:
                base_record = lookup_base_pin(pin_match.group(0))

            if base_record:
                parcel_number = base_record["parcel_number"]
                dataset_type = "residential_property"
                if base_record.get("year_built"):
                    year_found = int(base_record["year_built"])

        # CASE 2: Archive scan DOES NOT have native GPS coordinates
        else:
            # A. Check for 10-digit (King) or 14-digit (Snohomish) PIN
            pin_match = re.search(r'\b\d{10}\b', combined_text) or re.search(r'\b\d{14}\b', combined_text)
            if pin_match:
                base_record = lookup_base_pin(pin_match.group(0))

            # B. Check for street address match in base
            if not base_record:
                addr_match = re.search(r'\b\d{2,5}\s+[A-Za-z0-9\.\s]+(?:St|Street|Ave|Avenue|Pl|Place|Rd|Road|Way|Blvd|Dr)\b', clean_desc, re.IGNORECASE)
                if addr_match:
                    cand_slug = match_slug_from_text(clean_title, clean_desc)
                    base_record = lookup_base_address(addr_match.group(0), cand_slug)

            if base_record:
                parcel_number = base_record["parcel_number"]
                lat = float(base_record["latitude"])
                lng = float(base_record["longitude"])
                matched_slug = base_record["neighborhood_slug"]
                if base_record.get("year_built"):
                    year_found = int(base_record["year_built"])
                dataset_type = "residential_property"
            else:
                # C. Check for verified 59-city or neighborhood slug in text
                matched_slug = match_slug_from_text(clean_title, clean_desc)
                
                # Special allowance for SMA: SMA is explicitly City of Seattle engineering negatives
                if not matched_slug and source_key == "sma_infrastructure":
                    matched_slug = "seattle"

                # STRICT ZERO-FALLBACK: If no local anchor exists, DROP RECORD COMPLETELY
                if not matched_slug:
                    continue

                centroid = CENTROIDS.get(matched_slug)
                if not centroid:
                    continue
                lat, lng = centroid

        city_slug, county_name = resolve_location(matched_slug, lat)
        if not city_slug or not county_name:
            continue

        items.append({
            "id": item_id,
            "dataset_type": dataset_type,
            "parcel_number": parcel_number,
            "title": clean_title[:90],
            "city": city_slug,                # Lowercase hyphenated city slug (e.g. 'seattle', 'edmonds')
            "county": county_name,            # Preserves 'King' or 'Snohomish'
            "neighborhood": matched_slug,     # Sub-neighborhood slug or city slug
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
    item_id = item["id"]
    photo_buf, thumb_buf = process_and_transcode_image(item)
    if not photo_buf or not thumb_buf:
        return None

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
def execute_pipeline(stages_to_run, city_filter=None, limit_per_source=None, force=False, is_bulk=False):
    print("================================================================================")
    print("MYSEATTLESEARCH: ZERO-FALLBACK BULK HISTORICAL HARVESTER")
    print("================================================================================")
    print(f"Target Database ID: {CF_D1_DATABASE_ID}")
    print(f"Target R2 Bucket:   {R2_BUCKET_NAME} ({R2_PUBLIC_DOMAIN})")
    print(f"Bounding Bounds:    Lat [{BOUNDING_BOX['lat_min']}, {BOUNDING_BOX['lat_max']}] | Lng [{BOUNDING_BOX['lng_min']}, {BOUNDING_BOX['lng_max']}]")
    print(f"Memory Centroids:   {len(CENTROIDS)} municipal entities pre-seeded in RAM (0 D1 row scans)")
    print(f"Pixel Ceiling:      Max {MAX_PIXEL_CEILING} pixels (oversized images skipped before download)")
    print(f"Target Stages:      {', '.join(stages_to_run).upper()}")
    if limit_per_source:
        print(f"Quota Target:       {limit_per_source} verified records per stage")
    else:
        print("Quota Target:       UNCAPPED BULK (Continuous harvest to end of archives)")
    print("================================================================================")

    progress = load_progress()
    completed_ids = set() if force else set(progress.get("completed_ids", []))
    cursors = progress.get("cursors", {})
    s3_client = get_r2_client()

    total_committed = 0

    for stage_idx, stage in enumerate(stages_to_run, 1):
        print(f"\n>>> [STAGE {stage_idx}/{len(stages_to_run)}] PROCESSING: {stage.upper()}")
        print("--------------------------------------------------------------------------------")

        stage_committed = 0
        current_offset = 0 if force else cursors.get(stage, 0)

        while True:
            fetch_size = 50 if is_bulk else (max(25, limit_per_source) if limit_per_source else 25)
            print(f"[*] Querying '{stage}' at offset {current_offset} (fetch buffer: {fetch_size})...")
            live_items, next_offset = fetch_live_archive_records(stage, offset=current_offset, limit=fetch_size)

            if not live_items:
                print(f"[+] Reached end of verified archive records for '{stage}'.")
                break

            if city_filter:
                live_items = [r for r in live_items if r["city"].lower() == city_filter.lower()]

            pending = [r for r in live_items if force or r["id"] not in completed_ids]

            if not pending:
                if next_offset == current_offset:
                    break
                print(f"[*] Advancing offset from {current_offset} -> {next_offset} to find eligible local candidates...")
                current_offset = next_offset
                cursors[stage] = current_offset
                progress["cursors"] = cursors
                save_progress(progress)
                continue

            for item in pending:
                item_id = item["id"]
                loc_desc = f"{item['city']} ({item['county']}) [{item['neighborhood']}] @ [{item['lat']}, {item['lng']}]"
                parcel_desc = f" [PIN: {item['parcel_number']}]" if item.get("parcel_number") else ""
                print(f"  [{stage_committed + 1}] {item_id} | {item['title']}{parcel_desc} - {loc_desc}")

                try:
                    photo_url = ingest_record(item, s3_client)
                    if not photo_url:
                        print(f"      [SKIP] Binary validation rejected asset: {item_id}")
                        continue

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
        print(f"[+] Stage {stage.upper()} completed: {stage_committed} verified records committed.")

    print("\n================================================================================")
    print(f"[+] RUN COMPLETED: {total_committed} strictly verified historical records committed to D1 & R2.")
    print("================================================================================")

# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Zero-Fallback Bulk Historical Asset Harvester")
    parser.add_argument("--bulk", action="store_true", help="Execute complete continuous run until end of archives")
    parser.add_argument("--source", type=str, default="all", choices=["all"] + ALL_SOURCES,
                        help="Target data source (default: all)")
    parser.add_argument("--city", type=str, default=None, help="Filter harvest to a single city")
    parser.add_argument("--limit", type=int, default=3, help="Records to commit per stage (default: 3)")
    parser.add_argument("--force", action="store_true", help="Bypass checkpoint cache to test fresh records")
    args = parser.parse_args()

    stages = ALL_SOURCES if args.source == "all" else [args.source]
    limit_target = None if args.bulk else args.limit

    execute_pipeline(
        stages_to_run=stages,
        city_filter=args.city,
        limit_per_source=limit_target,
        force=args.force,
        is_bulk=args.bulk
    )