import os
import re
import json
import math
import requests
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
DEV_VARS_PATH = os.path.join(BASE_DIR, ".dev.vars")
SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']

def load_dev_vars():
    if os.path.exists(DEV_VARS_PATH):
        with open(DEV_VARS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

def clean_nan_tokens(node):
    if isinstance(node, dict):
        return {k: clean_nan_tokens(v) for k, v in node.items()}
    elif isinstance(node, list):
        return [clean_nan_tokens(element) for element in node]
    elif isinstance(node, float) and (math.isnan(node) or math.isinf(node)):
        return None
    return node

def parse_sheet_values(rows):
    if not rows:
        return []
    headers = [str(h).strip() for h in rows[0]]
    records = []
    for row in rows[1:]:
        padded = list(row) + [""] * (len(headers) - len(row))
        sanitized = [str(item).strip() if item is not None else "" for item in padded]
        records.append(dict(zip(headers, sanitized)))
    return records

def sql_escape(val):
    if val is None:
        return "NULL"
    if isinstance(val, (int, float)):
        return str(val)
    escaped = str(val).replace("'", "''")
    return f"'{escaped}'"

def execute_d1_raw(session, endpoint, headers, sql_chunk):
    response = session.post(endpoint, headers=headers, json={"sql": sql_chunk}, timeout=45)
    data = response.json()
    if not data.get("success"):
        raise RuntimeError(f"Cloudflare D1 SQL Error: {data.get('errors', [])}")
    return data

def sync_utility_directory_to_d1(utility_records):
    cf_account_id = os.environ.get("CF_ACCOUNT_ID")
    cf_api_token = os.environ.get("CF_D1_API_TOKEN")
    cf_db_id = os.environ.get("CF_DATABASE_PARCELDATA_ID")

    if not all([cf_account_id, cf_api_token, cf_db_id]):
        print("   ⚠️ Cloudflare D1 environment variables missing. Skipping utility_directory edge sync.")
        return

    print("   ⚡ Syncing UtilityData into Cloudflare D1 (utility_directory)...")
    endpoint = f"https://api.cloudflare.com/client/v4/accounts/{cf_account_id}/d1/database/{cf_db_id}/query"
    headers = {
        "Authorization": f"Bearer {cf_api_token}",
        "Content-Type": "application/json"
    }
    session = requests.Session()

    batch_size = 50
    committed = 0

    for i in range(0, len(utility_records), batch_size):
        chunk = utility_records[i:i + batch_size]
        values_clauses = []

        for rec in chunk:
            entity_id = rec.get("entity_id") or rec.get("EntityID") or rec.get("ID")
            city = rec.get("City") or rec.get("city")
            service_category = rec.get("ServiceCategory") or rec.get("Category") or rec.get("service_category")
            provider_name = rec.get("ProviderName") or rec.get("Provider") or rec.get("provider_name")
            phone = rec.get("Phone") or rec.get("phone")
            website_url = rec.get("Website") or rec.get("WebsiteURL") or rec.get("website_url")
            coverage_type = rec.get("CoverageType") or rec.get("coverage_type") or "Municipal"

            if not provider_name or not service_category:
                continue

            if not entity_id:
                clean_city = re.sub(r'[^a-zA-Z0-9]', '', str(city or "regional")).lower()
                clean_prov = re.sub(r'[^a-zA-Z0-9]', '', str(provider_name)).lower()
                clean_cat = re.sub(r'[^a-zA-Z0-9]', '', str(service_category)).lower()
                entity_id = f"{clean_city}_{clean_cat}_{clean_prov}"[:64]

            val_tuple = (
                sql_escape(entity_id),
                sql_escape(city),
                sql_escape(service_category),
                sql_escape(provider_name),
                sql_escape(phone),
                sql_escape(website_url),
                sql_escape(coverage_type)
            )
            values_clauses.append(f"({', '.join(val_tuple)}, CURRENT_TIMESTAMP)")

        if not values_clauses:
            continue

        sql = f"""
        INSERT INTO utility_directory (
          entity_id, city, service_category, provider_name, phone, website_url, coverage_type, updated_utc
        ) VALUES {', '.join(values_clauses)}
        ON CONFLICT(entity_id) DO UPDATE SET
          city = excluded.city,
          service_category = excluded.service_category,
          provider_name = excluded.provider_name,
          phone = excluded.phone,
          website_url = excluded.website_url,
          coverage_type = excluded.coverage_type,
          updated_utc = CURRENT_TIMESTAMP;
        """

        execute_d1_raw(session, endpoint, headers, sql)
        committed += len(values_clauses)

    print(f"   ✅ Committed {committed:,} utility records to Cloudflare D1.")

def main():
    print("🌙 Running Complete Monthly Sheets Ingestion & Edge Sync...")
    os.makedirs(DATA_DIR, exist_ok=True)
    load_dev_vars()

    master_sheet_id = os.environ.get("WEBSITE_DATA_CORE_SHEET_ID")
    creds_path = "credentials.json"
    if not master_sheet_id or not os.path.exists(creds_path):
        print("❌ [Monthly Sync] Missing credentials.json or WEBSITE_DATA_CORE_SHEET_ID.")
        return

    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    sheets_service = build('sheets', 'v4', credentials=creds)

    tabs = ["MunicipalFeeds", "DPA", "UtilityData"]
    ranges = [f"{tab}!A:BK" for tab in tabs]
    
    res = sheets_service.spreadsheets().values().batchGet(
        spreadsheetId=master_sheet_id, 
        ranges=ranges
    ).execute()
    data = dict(zip(tabs, res.get('valueRanges', [])))

    muni_rows = data.get("MunicipalFeeds", {}).get('values', [])
    if muni_rows:
        parsed_muni = parse_sheet_values(muni_rows)
        with open(os.path.join(DATA_DIR, "municipal_feeds.json"), "w", encoding="utf-8") as f:
            json.dump(clean_nan_tokens(parsed_muni), f, indent=2, ensure_ascii=False)
        print(f"   Updated municipal_feeds.json ({len(parsed_muni):,} records).")

    dpa_rows = data.get("DPA", {}).get('values', [])
    if dpa_rows:
        parsed_dpa = parse_sheet_values(dpa_rows)
        with open(os.path.join(DATA_DIR, "dpa_programs.json"), "w", encoding="utf-8") as f:
            json.dump(clean_nan_tokens(parsed_dpa), f, indent=2, ensure_ascii=False)
        print(f"   Updated dpa_programs.json ({len(parsed_dpa):,} records).")

    utility_rows = data.get("UtilityData", {}).get('values', [])
    if utility_rows:
        parsed_utilities = parse_sheet_values(utility_rows)
        with open(os.path.join(DATA_DIR, "utility_directory.json"), "w", encoding="utf-8") as f:
            json.dump(clean_nan_tokens(parsed_utilities), f, indent=2, ensure_ascii=False)
        print(f"   Updated utility_directory.json ({len(parsed_utilities):,} records).")

        sync_utility_directory_to_d1(parsed_utilities)

    print("✅ Monthly Sheets Sync & Edge Ingestion complete.")

if __name__ == "__main__":
    main()