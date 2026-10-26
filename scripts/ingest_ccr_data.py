import os
import sys
import time
import requests
import pandas as pd

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
# 2. SCRAPE SUBDIVISION COVENANTS (KING & SNOHOMISH)
# ------------------------------------------------------------------------------
def fetch_county_subdivisions(county_name, url):
    print(f"🌐 Scraping {county_name} County subdivisions from UW...")
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        tables = pd.read_html(response.text)
        if not tables:
            print(f"⚠️ No tables found for {county_name}")
            return []
            
        df = tables[0]
        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
        
        records = []
        for _, row in df.iterrows():
            subdivision = str(row.get("plat_name", row.get("subdivision", row.get("neighborhood", "Unknown")))).strip()
            afn = str(row.get("recording_number", row.get("auditor_file_number", row.get("afn", "")))).strip()
            date = str(row.get("date", row.get("recording_date", ""))).strip()
            text = str(row.get("covenant_text", row.get("restriction", row.get("text", "")))).strip()
            link = str(row.get("link", row.get("document", ""))).strip()
            
            if subdivision and subdivision.lower() != "nan":
                records.append({
                    "county": county_name,
                    "subdivision_name": subdivision,
                    "recording_number": afn if afn != "nan" else "",
                    "recording_date": date if date != "nan" else "",
                    "covenant_text": text if text != "nan" else "",
                    "document_url": link if link != "nan" else ""
                })
        print(f"✅ Found {len(records)} subdivisions for {county_name}.")
        return records
    except Exception as e:
        print(f"⚠️ Could not scrape {county_name} subdivisions: {e}")
        return []

# ------------------------------------------------------------------------------
# 3. QUERY PARCEL-LEVEL REST LAYER
# ------------------------------------------------------------------------------
def fetch_parcels(max_records=60000):
    print("🌐 Querying parcel GIS layers from UW ArcGIS REST endpoint...")
    base_url = "https://services.arcgis.com/8rmP1QtlndtPlezP/arcgis/rest/services/King_County_Covenants_Parcels/FeatureServer/0/query"
    
    records = []
    offset = 0
    chunk_size = 2000
    
    while offset < max_records:
        params = {
            "where": "1=1",
            "outFields": "PIN,ADDRESS,PLAT_NAME,COUNTY",
            "f": "json",
            "resultRecordCount": chunk_size,
            "resultOffset": offset
        }
        try:
            res = requests.get(base_url, params=params, timeout=25)
            data = res.json()
            features = data.get("features", [])
            if not features:
                break
                
            for feat in features:
                attrs = feat.get("attributes", {})
                pin = str(attrs.get("PIN", "")).strip()
                if pin and pin.lower() != "none" and pin.lower() != "nan":
                    records.append({
                        "parcel_id": pin.zfill(10),
                        "county": attrs.get("COUNTY", "King") or "King",
                        "address": str(attrs.get("ADDRESS", "")).strip(),
                        "subdivision_name": str(attrs.get("PLAT_NAME", "")).strip()
                    })
            
            offset += len(features)
            print(f"📦 Retrieved {len(records)} parcel records so far...")
            if len(features) < chunk_size:
                break
        except Exception as e:
            print(f"⚠️ Parcel query interrupted at offset {offset}: {e}")
            break
            
    print(f"✅ Total parcel records collected: {len(records)}")
    return records

# ------------------------------------------------------------------------------
# 4. MAIN INGESTION WORKFLOW
# ------------------------------------------------------------------------------
def run_ingestion():
    print("🚀 Starting WA Covenants D1 Ingestion Pipeline...")
    
    # 1. Scrape subdivisions for King and Snohomish
    king_covenants = fetch_county_subdivisions("King", "https://depts.washington.edu/covenants/map_restrictions_king.shtml")
    snohomish_covenants = fetch_county_subdivisions("Snohomish", "https://depts.washington.edu/covenants/map_restrictions_snohomish.shtml")
    all_covenants = king_covenants + snohomish_covenants
    
    # Map subdivisions to numeric IDs
    subdivision_to_id = {}
    doc_id = 1
    
    print(f"📤 Uploading {len(all_covenants)} documents into covenant_documents table...")
    for doc in all_covenants:
        key = (doc["county"].lower(), doc["subdivision_name"].lower())
        if key not in subdivision_to_id:
            subdivision_to_id[key] = doc_id
            sql = """
            INSERT OR IGNORE INTO covenant_documents 
            (id, county, subdivision_name, recording_number, recording_date, covenant_text, document_url)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """
            execute_d1(sql, [
                doc_id, doc["county"], doc["subdivision_name"],
                doc["recording_number"], doc["recording_date"],
                doc["covenant_text"], doc["document_url"]
            ])
            doc_id += 1

    # 2. Fetch all mapped parcels
    parcels = fetch_parcels()
    total_parcels = len(parcels)
    if total_parcels == 0:
        print("⚠️ No parcels found to ingest.")
        return

    print(f"📤 Batch-uploading {total_parcels} parcels into Cloudflare D1...")
    batch_size = 150
    for i in range(0, total_parcels, batch_size):
        chunk = parcels[i:i + batch_size]
        placeholders = []
        flat_params = []
        
        for p in chunk:
            key = (p["county"].lower(), p["subdivision_name"].lower())
            parent_id = subdivision_to_id.get(key)
            
            # Register placeholder document if parcel belongs to subdivision not listed in table
            if not parent_id:
                parent_id = doc_id
                subdivision_to_id[key] = parent_id
                execute_d1(
                    "INSERT OR IGNORE INTO covenant_documents (id, county, subdivision_name) VALUES (?, ?, ?);",
                    [parent_id, p["county"], p["subdivision_name"]]
                )
                doc_id += 1

            placeholders.append("(?, ?, ?, ?)")
            flat_params.extend([p["parcel_id"], p["county"], p["address"], parent_id])
        
        batch_sql = f"INSERT OR REPLACE INTO parcels (parcel_id, county, address, subdivision_id) VALUES {','.join(placeholders)};"
        execute_d1(batch_sql, flat_params)
        
        if (i // batch_size) % 15 == 0 or (i + batch_size) >= total_parcels:
            print(f"💾 Ingested {min(i + batch_size, total_parcels)} / {total_parcels} parcels...")
            time.sleep(0.05)

    print("🎉 Ingestion complete! D1 database is fully hydrated.")

if __name__ == "__main__":
    run_ingestion()