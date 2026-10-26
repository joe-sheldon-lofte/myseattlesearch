import html
import os
import re
import sys
import time
from bs4 import BeautifulSoup
import requests

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

# ------------------------------------------------------------------------------
# 2. PARSE SUBDIVISION TABLES (KING & SNOHOMISH)
# ------------------------------------------------------------------------------
def fetch_county_subdivisions(county_name, url):
    print(f"🌐 Fetching {county_name} County subdivisions from UW...")
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    try:
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, "html.parser")
        tables = soup.find_all("table")
        
        if not tables:
            print(f"⚠️ No tables found on page for {county_name}")
            return []
            
        records = []
        
        # King County has multiple tables divided by geographic zone; Snohomish has one
        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cols = row.find_all("td")
                if not cols:
                    continue  # Header row
                
                # King: City (0), Neighborhood (1), Subdivision/Plat (2), Restriction (3), Properties (4)
                # Snohomish: City (0), Subdivision/Plat (1), Restriction (2), Properties (3), Doc Type (4)
                if county_name == "King" and len(cols) >= 4:
                    subdiv_cell = cols[2]
                    subdivision = subdiv_cell.get_text(strip=True)
                    link_tag = subdiv_cell.find("a")
                    doc_url = link_tag["href"].strip() if link_tag and link_tag.has_attr("href") else ""
                    restriction = cols[3].get_text(strip=True)
                elif county_name == "Snohomish" and len(cols) >= 3:
                    subdiv_cell = cols[1]
                    subdivision = subdiv_cell.get_text(strip=True)
                    link_tag = subdiv_cell.find("a")
                    doc_url = link_tag["href"].strip() if link_tag and link_tag.has_attr("href") else ""
                    restriction = cols[2].get_text(strip=True)
                else:
                    continue

                # Clean non-breaking spaces and formatting quirks
                subdivision = subdivision.replace("\xa0", " ").strip()
                restriction = restriction.replace("\xa0", " ").strip()

                if subdivision and subdivision.lower() != "subdivision (plat)":
                    records.append({
                        "county": county_name,
                        "subdivision_name": subdivision,
                        "recording_number": "",  # Populated via deed reference or search
                        "recording_date": "",
                        "covenant_text": restriction,
                        "document_url": doc_url
                    })
                    
        print(f"✅ Extracted {len(records)} subdivisions for {county_name}.")
        return records

    except Exception as e:
        print(f"⚠️ Error parsing {county_name} subdivisions: {e}")
        return []

# ------------------------------------------------------------------------------
# 3. INGESTION RUNNER
# ------------------------------------------------------------------------------
def run_ingestion():
    print("🚀 Starting WA Covenants D1 Ingestion Pipeline...")
    
    king_covenants = fetch_county_subdivisions(
        "King", 
        "https://depts.washington.edu/covenants/map_restrictions_king.shtml"
    )
    snohomish_covenants = fetch_county_subdivisions(
        "Snohomish", 
        "https://depts.washington.edu/covenants/map_restrictions_snohomish.shtml"
    )
    all_covenants = king_covenants + snohomish_covenants
    
    if not all_covenants:
        print("⚠️ No subdivision data found to insert.")
        return

    print(f"📤 Uploading {len(all_covenants)} records into covenant_documents...")
    
    insert_sql = """
    INSERT INTO covenant_documents (county, subdivision_name, recording_number, recording_date, covenant_text, document_url)
    VALUES (?, ?, ?, ?, ?, ?);
    """
    
    success_count = 0
    for doc in all_covenants:
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
        except Exception as e:
            # Silently skip duplicate constraint errors if rerun
            if "UNIQUE constraint failed" not in str(e):
                print(f"⚠️ Failed row insertion: {e}")

    print(f"🎉 Inserted {success_count} subdivision documents into Cloudflare D1.")

if __name__ == "__main__":
    run_ingestion()
