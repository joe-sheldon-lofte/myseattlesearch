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

def main():
    print("🌙 Running Quarterly Sheets Ingestion & Edge Sync...")
    os.makedirs(DATA_DIR, exist_ok=True)
    load_dev_vars()

    master_sheet_id = os.environ.get("WEBSITE_DATA_CORE_SHEET_ID")
    creds_path = "credentials.json"
    if not master_sheet_id or not os.path.exists(creds_path):
        print("❌ [Quarterly Sync] Missing credentials.json or WEBSITE_DATA_CORE_SHEET_ID.")
        return

    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    sheets_service = build('sheets', 'v4', credentials=creds)

    # --------------------------------------------------------------------------
    # PLACEHOLDER TABS FOR QUARTERLY ARCHITECTURE
    # Replace "QuarterlyTab1" with actual Google Sheet tab names once established
    # --------------------------------------------------------------------------
    tabs = ["QuarterlyTab1", "QuarterlyTab2"]
    ranges = [f"{tab}!A:BK" for tab in tabs]
    
    try:
        res = sheets_service.spreadsheets().values().batchGet(
            spreadsheetId=master_sheet_id, 
            ranges=ranges
        ).execute()
        data = dict(zip(tabs, res.get('valueRanges', [])))
        
        # TAB 1 EXTRACT
        tab1_rows = data.get("QuarterlyTab1", {}).get('values', [])
        if tab1_rows:
            parsed_tab1 = parse_sheet_values(tab1_rows)
            with open(os.path.join(DATA_DIR, "quarterly_tab1.json"), "w", encoding="utf-8") as f:
                json.dump(clean_nan_tokens(parsed_tab1), f, indent=2, ensure_ascii=False)
            print(f"   Updated quarterly_tab1.json ({len(parsed_tab1):,} records).")
        else:
            print("   ⚠️ QuarterlyTab1 is empty or missing.")

        # TAB 2 EXTRACT
        tab2_rows = data.get("QuarterlyTab2", {}).get('values', [])
        if tab2_rows:
            parsed_tab2 = parse_sheet_values(tab2_rows)
            with open(os.path.join(DATA_DIR, "quarterly_tab2.json"), "w", encoding="utf-8") as f:
                json.dump(clean_nan_tokens(parsed_tab2), f, indent=2, ensure_ascii=False)
            print(f"   Updated quarterly_tab2.json ({len(parsed_tab2):,} records).")
        else:
            print("   ⚠️ QuarterlyTab2 is empty or missing.")

        print("✅ Quarterly Sheets Sync & Edge Ingestion complete.")
        
    except Exception as e:
        print(f"❌ Quarterly sheet extraction failed: {e}")

if __name__ == "__main__":
    main()