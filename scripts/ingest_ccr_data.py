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
HEADERS = {
    "Authorization": f"Bearer {CF_API_TOKEN}",
    "Content-Type": "application/json"
}

def create_retry_session():
    """Creates a requests session that auto-retries transient drops."""
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

    response = requests.post(D1_API_URL, headers=HEADERS, json=payload, timeout=30)
    data = response.json()
    
    if not data.get("success"):
        raise RuntimeError(f"D1 API Error: {data.get('errors')}")
    return data.get("result", [])

def clean_text(text):
    """Normalizes whitespace and removes odd encoding artifacts."""
    if not text:
        return ""
    text = html.unescape(text)
    text = text.replace("\xa0", " ").replace("Â", "")
    return re.sub(r"\s+", " ", text).strip()

def extract_recording_number(text):
    """Extracts an AFN or Book/Volume identifier if mentioned in notes or names."""
    match = re.search(r'\b(?:AFN|CCR|vol(?:ume)?|rec(?:ording)?\.?\s*(?:no\.?|number)?)\s*[:#]?\s*([0-9]{4,14}(?:-[0-9]+)?)', text, re.IGNORECASE)
    return match.group(1) if match else ""

# ------------------------------------------------------------------------------
# 2. PARSE KING COUNTY RESTRICTIONS
# ------------------------------------------------------------------------------
def fetch_king_subdivisions(session):
    url = "https://depts.washington.edu/covenants/map_restrictions_king.shtml"
    print("🌐 Scraping King County restricted subdivisions from UW...")
    
    response = session.get(url, timeout=(10, 30))
    response.raise_for_status()
    
    soup = BeautifulSoup(response.text, "html.parser")
    tables = soup.find_all("table")
    print(f"   Found {len(tables)} regional tables for King County.")
    
    records = []
    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 4:
                continue  # Skip table header rows
                
            city = clean_text(cols[0].get_text())
            neighborhood = clean_text(cols[1].get_text())
            subdiv_col = cols[2]
            subdivision = clean_text(subdiv_col.get_text())
            
            # Skip if this is an internal header row
            if subdivision.lower() in ["subdivision (plat)", "subdivision/plat"]:
                continue
                
            # Extract document scan URL
            link = subdiv_col.find("a")
            doc_url = ""
            if link and link.has_attr("href"):
                doc_url = urljoin(url, link["href"].strip())

            restriction = clean_text(cols[3].get_text())
            afn = extract_recording_number(subdivision) or extract_recording_number(restriction)

            records.append({
                "county": "King",
                "subdivision_name": subdivision,
                "recording_number": afn,
                "recording_date": "",
                "covenant_text": restriction,
                "document_url": doc_url
            })
            
    print(f"✅ Extracted {len(records)} King County subdivision records.")
    return records

# ------------------------------------------------------------------------------
# 3. PARSE SNOHOMISH COUNTY RESTRICTIONS
# ------------------------------------------------------------------------------
def fetch_snohomish_subdivisions(session):
    url = "https://depts.washington.edu/covenants/map_restrictions_snohomish.shtml"
    print("🌐 Scraping Snohomish County restricted subdivisions from UW...")
    
    response = session.get(url, timeout=(10, 30))
    response.raise_for_status()
    
    soup = BeautifulSoup(response.text, "html.parser")
    tables = soup.find_all("table")
    
    records = []
    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 3:
                continue
                
            city = clean_text(cols[0].get_text())
            subdiv_col = cols[1]
            subdivision = clean_text(subdiv_col.get_text())
            
            if subdivision.lower() in ["subdivision (plat)", "subdivision/plat"]:
                continue
                
            link = subdiv_col.find("a")
            doc_url = ""
            if link and link.has_attr("href"):
                doc_url = urljoin(url, link["href"].strip())

            restriction = clean_text(cols[2].get_text())
            afn = extract_recording_number(subdivision) or extract_recording_number(restriction)

            records.append({
                "county": "Snohomish",
                "subdivision_name": subdivision,
                "recording_number": afn,
                "recording_date": "",
                "covenant_text": restriction,
                "document_url": doc_url
            })
            
    print(f"✅ Extracted {len(records)} Snohomish County subdivision records.")
    return records

# ------------------------------------------------------------------------------
# 4. MAIN INGESTION WORKFLOW
# ------------------------------------------------------------------------------
def run_ingestion():
    print("🚀 Starting WA Covenants D1 Ingestion Pipeline...")
    session = create_retry_session()
    
    king_records = fetch_king_subdivisions(session)
    snohomish_records = fetch_snohomish_subdivisions(session)
    all_records = king_records + snohomish_records
    
    if not all_records:
        print("⚠️ No subdivision data collected.")
        return

    print(f"📤 Uploading {len(all_records)} subdivisions into 'covenant_documents' table...")
    
    insert_sql = """
    INSERT OR REPLACE INTO covenant_documents 
    (county, subdivision_name, recording_number, recording_date, covenant_text, document_url)
    VALUES (?, ?, ?, ?, ?, ?);
    """
    
    success_count = 0
    for doc in all_records:
        try:
            execute_d1(insert_sql, [
                doc["county"],
                doc["subdivision_name"],
                doc["recording_number"],
                doc["recording_date"],
                doc["covenant_text"],
                doc["document_url"]
            ])
            success_count += 1
            if success_count % 50 == 0:
                print(f"   Saved {success_count}/{len(all_records)} records...")
        except Exception as e:
            print(f"⚠️ Error saving '{doc['subdivision_name']}': {e}")

    print(f"🎉 Ingestion complete! Successfully loaded {success_count} restricted subdivisions into D1.")

if __name__ == "__main__":
    run_ingestion()