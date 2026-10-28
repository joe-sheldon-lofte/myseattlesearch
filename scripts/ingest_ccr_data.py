import html
import os
import re
import sys
import time
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

# ------------------------------------------------------------------------------
# 1. RETRIEVE ENVIRONMENT CREDENTIALS
# ------------------------------------------------------------------------------
CF_ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID")
CF_DATABASE_ID = os.getenv("CF_DATABASE_ID")
CF_API_TOKEN = os.getenv("CF_API_TOKEN")

if not all([CF_ACCOUNT_ID, CF_DATABASE_ID, CF_API_TOKEN]):
    print("❌ Missing required Cloudflare environment variables:")
    print(f" - CF_ACCOUNT_ID: {'Found' if CF_ACCOUNT_ID else 'MISSING'}")
    print(f" - CF_DATABASE_ID: {'Found' if CF_DATABASE_ID else 'MISSING'}")
    print(f" - CF_API_TOKEN: {'Found' if CF_API_TOKEN else 'MISSING'}")
    sys.exit(1)

D1_API_URL = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/d1/database/{CF_DATABASE_ID}/query"
D1_HEADERS = {
    "Authorization": f"Bearer {CF_API_TOKEN}",
    "Content-Type": "application/json"
}

# ------------------------------------------------------------------------------
# 2. VERIFIED UW ARCGIS FEATURESERVER ENDPOINTS
# ------------------------------------------------------------------------------
KING_ARCGIS_ENDPOINT = "https://services.arcgis.com/JL4BwWcjcPuWhBm9/arcgis/rest/services/King_25_07_03/FeatureServer/9/query"
SNOHOMISH_ARCGIS_ENDPOINT = "https://services.arcgis.com/JL4BwWcjcPuWhBm9/arcgis/rest/services/Parcels_Snohomish_2_2_2025/FeatureServer/0/query"

def create_retry_session():
    """Builds a resilient HTTP session that handles transient network timeouts."""
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=[500, 502, 503, 504],
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

def execute_d1(sql, params=None):
    """Executes a SQL query against Cloudflare D1 via the REST API."""
    payload = {"sql": sql}
    if params:
        payload["params"] = params

    response = requests.post(D1_API_URL, headers=D1_HEADERS, json=payload, timeout=30)
    data = response.json()
    
    if not data.get("success"):
        raise RuntimeError(f"D1 API Error: {data.get('errors')}")
    return data.get("result", [])

def clean_text(text):
    if not text:
        return ""
    text = html.unescape(text)
    text = text.replace("\xa0", " ").replace("Â", "")
    return re.sub(r"\s+", " ", text).strip()

def sql_quote(val):
    """Safely escapes strings for raw SQLite statements."""
    if val is None:
        return "''"
    cleaned = str(val).replace("'", "''").strip()
    return f"'{cleaned}'"

def extract_field(attrs, candidate_keys, default=""):
    """Case-insensitive attribute lookup across varied ArcGIS schemas."""
    attrs_upper = {k.upper(): v for k, v in attrs.items() if v is not None}
    for key in candidate_keys:
        if key.upper() in attrs_upper:
            val = str(attrs_upper[key.upper()]).strip()
            if val and val.lower() not in ["none", "null", "nan"]:
                return val
    return default

# ------------------------------------------------------------------------------
# 3. HARVEST SUBDIVISION COVENANT DOCUMENTS
# ------------------------------------------------------------------------------
def fetch_county_subdivisions(session, county_name, url):
    print(f"🌐 Scraping {county_name} County subdivisions from UW...")
    try:
        response = session.get(url, timeout=(10, 30))
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        tables = soup.find_all("table")
        
        records = []
        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cols = row.find_all("td")
                if county_name == "King" and len(cols) >= 4:
                    subdiv_cell = cols[2]
                    subdivision = clean_text(subdiv_cell.get_text())
                    link = subdiv_cell.find("a")
                    doc_url = urljoin(url, link["href"].strip()) if link and link.has_attr("href") else ""
                    restriction = clean_text(cols[3].get_text())
                elif county_name == "Snohomish" and len(cols) >= 3:
                    subdiv_cell = cols[1]
                    subdivision = clean_text(subdiv_cell.get_text())
                    link = subdiv_cell.find("a")
                    doc_url = urljoin(url, link["href"].strip()) if link and link.has_attr("href") else ""
                    restriction = clean_text(cols[2].get_text())
                else:
                    continue

                if subdivision and subdivision.lower() not in ["subdivision (plat)", "subdivision/plat"]:
                    records.append({
                        "county": county_name,
                        "subdivision_name": subdivision,
                        "covenant_text": restriction,
                        "document_url": doc_url
                    })
        print(f"✅ Found {len(records)} subdivision documents for {county_name}.")
        return records
    except Exception as e:
        print(f"⚠️ Error fetching {county_name} subdivisions: {e}")
        return []

# ------------------------------------------------------------------------------
# 4. HARVEST PARCELS FROM ARCGIS FEATURESERVER
# ------------------------------------------------------------------------------
def fetch_arcgis_parcels(session, county_name, endpoint, max_records=60000):
    print(f"🌐 Fetching {county_name} County parcels from ArcGIS...")
    offset = 0
    batch_limit = 2000
    parcels = []

    while offset < max_records:
        params = {
            "where": "1=1",
            "outFields": "*",
            "f": "json",
            "resultOffset": offset,
            "resultRecordCount": batch_limit,
            "returnGeometry": "false",
            "orderByFields": "OBJECTID ASC"
        }
        
        try:
            res = session.get(endpoint, params=params, timeout=(10, 45))
            res.raise_for_status()
            data = res.json()
        except Exception as e:
            print(f"❌ Network drop at offset {offset} for {county_name}: {e}")
            break
            
        features = data.get("features", [])
        if not features:
            break
            
        for feat in features:
            attrs = feat.get("attributes", {})
            
            # 1. Extract PIN
            pin = extract_field(attrs, ["PIN", "PARCEL_ID", "PARCEL_ID_", "PARCEL_ID_W__00S", "ORIG_PARCE", "OBJECTID"])
            
            # 2. Extract and format Address using confirmed schema keys
            street = extract_field(attrs, ["SITUS_ADDR", "ADDR_FULL", "PRIMARY_ADDR", "SITUSLINE1"])
            city = extract_field(attrs, ["SITUS_CITY", "SITUSCITY", "CTYNAME", "POSTALCTYNAME"])
            zip_code = extract_field(attrs, ["SITUS_ZIP_", "SITUSZIP", "ZIP5"])
            
            if street:
                addr_parts = [street]
                if city:
                    addr_parts.append(city)
                if zip_code:
                    clean_zip = str(zip_code).split(".")[0].strip()
                    if clean_zip:
                        addr_parts.append(f"WA {clean_zip}")
                full_address = ", ".join(addr_parts)
            else:
                full_address = ""

            # 3. Extract Subdivision and Status
            subdiv = extract_field(attrs, ["PLAT_NAME", "PLAT_NAME", "PLAT_NAM_1", "PROP_NAME", "SUB_ADDRES"])
            status = extract_field(attrs, ["RESTRICTION_STATUS", "RESTRICTION STATUS", "RESTRICTION_TYPE", "STATUS"], default="Restricted")

            if pin:
                clean_pin = str(pin).replace("-", "").strip()
                if clean_pin.endswith(".0"):
                    clean_pin = clean_pin[:-2]
                    
                if county_name == "King" and len(clean_pin) < 10:
                    clean_pin = clean_pin.zfill(10)
                elif county_name == "Snohomish" and len(clean_pin) < 14:
                    clean_pin = clean_pin.zfill(14)

                parcels.append((clean_pin, county_name, full_address, subdiv, status))

        offset += len(features)
        print(f"   Collected {len(parcels)} {county_name} parcels...")
        
        if len(features) < batch_limit:
            break
        if data.get("exceededTransferLimit") is False:
            break
            
        time.sleep(0.15)
        
    print(f"✅ Harvested {len(parcels)} total parcels for {county_name}.")
    return parcels

# ------------------------------------------------------------------------------
# 5. D1 BATCH UPLOADERS
# ------------------------------------------------------------------------------
def upload_covenants_to_d1(covenants):
    if not covenants:
        return
    print(f"📤 Uploading {len(covenants)} records to 'covenant_documents'...")
    sql = """
    INSERT OR REPLACE INTO covenant_documents (county, subdivision_name, recording_number, recording_date, covenant_text, document_url)
    VALUES (?, ?, '', '', ?, ?);
    """
    for doc in covenants:
        try:
            execute_d1(sql, [doc["county"], doc["subdivision_name"], doc["covenant_text"], doc["document_url"]])
        except Exception:
            pass

def upload_parcels_to_d1(parcels, county_name):
    if not parcels:
        return
    print(f"📤 Batch-uploading {len(parcels)} {county_name} parcels into D1...")
    chunk_size = 50
    total = len(parcels)
    
    for i in range(0, total, chunk_size):
        chunk = parcels[i:i + chunk_size]
        row_values = [
            f"({sql_quote(p[0])}, {sql_quote(p[1])}, {sql_quote(p[2])}, {sql_quote(p[3])}, {sql_quote(p[4])})"
            for p in chunk
        ]
        
        sql = f"""
        INSERT OR REPLACE INTO parcels (parcel_id, county, address, subdivision_name, restriction_status)
        VALUES {','.join(row_values)};
        """
        execute_d1(sql)
        
        if (i // chunk_size) % 30 == 0 or (i + chunk_size) >= total:
            print(f"   Saved {min(i + chunk_size, total)}/{total} {county_name} parcels...")
            time.sleep(0.05)

# ------------------------------------------------------------------------------
# 6. MAIN PIPELINE EXECUTION
# ------------------------------------------------------------------------------
def run_ingestion():
    print("🚀 Starting Unified WA Covenants & Parcels Pipeline...")
    session = create_retry_session()

    # 1. Drop existing parcels table to clear old schemas, then recreate
    print("🔄 Ensuring clean D1 schema for 'parcels' and 'covenant_documents'...")
    execute_d1("DROP TABLE IF EXISTS parcels;")
    
    execute_d1("""
    CREATE TABLE IF NOT EXISTS covenant_documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        county TEXT NOT NULL,
        subdivision_name TEXT NOT NULL,
        recording_number TEXT,
        recording_date TEXT,
        covenant_text TEXT,
        document_url TEXT,
        UNIQUE(county, subdivision_name)
    );
    """)
    
    execute_d1("""
    CREATE TABLE parcels (
        parcel_id TEXT PRIMARY KEY,
        county TEXT NOT NULL,
        address TEXT,
        subdivision_name TEXT,
        restriction_status TEXT
    );
    """)
    execute_d1("CREATE INDEX idx_parcels_address ON parcels (address);")
    execute_d1("CREATE INDEX idx_parcels_subdiv ON parcels (subdivision_name);")

    # 2. Scrape & Update Covenant Documents (~442 rows)
    king_covenants = fetch_county_subdivisions(session, "King", "https://depts.washington.edu/covenants/map_restrictions_king.shtml")
    snohomish_covenants = fetch_county_subdivisions(session, "Snohomish", "https://depts.washington.edu/covenants/map_restrictions_snohomish.shtml")
    upload_covenants_to_d1(king_covenants + snohomish_covenants)

    # 3. Harvest & Ingest King County Parcels (~37,000 rows)
    king_parcels = fetch_arcgis_parcels(session, "King", KING_ARCGIS_ENDPOINT)
    upload_parcels_to_d1(king_parcels, "King")

    # 4. Harvest & Ingest Snohomish County Parcels (~7,000 rows)
    snohomish_parcels = fetch_arcgis_parcels(session, "Snohomish", SNOHOMISH_ARCGIS_ENDPOINT)
    upload_parcels_to_d1(snohomish_parcels, "Snohomish")

    print("🎉 Ingestion complete! Both covenant documents and parcel layers are live in D1.")

if __name__ == "__main__":
    run_ingestion()