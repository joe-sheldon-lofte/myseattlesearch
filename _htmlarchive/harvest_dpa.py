# File: scripts/harvest_dpa.py

import os
import json
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

DPA_OUTPUT_PATH = "data/dpa_programs.json"

def parse_sheet_values(rows):
    if not rows or len(rows) < 2:
        return []
    headers = [str(h).strip() for h in rows[0]]
    records = []
    for row in rows[1:]:
        padded = list(row) + [""] * (len(headers) - len(row))
        sanitized = {}
        for header, item in zip(headers, padded):
            val = str(item).strip() if item is not None else ""
            sanitized[header] = val
        records.append(sanitized)
    return records

def run_dpa_pipeline():
    print("📡 Starting Google Service Agent Down Payment Assistance Pipeline...")
    
    creds_path = "credentials.json"
    if not os.path.exists(creds_path):
        print("❌ Error: credentials.json missing from root execution context.")
        return

    sheet_id = os.environ.get("WEBSITE_DATA_SHEET_ID") or os.environ.get("CITY_DATA_SHEET_ID")
    if not sheet_id:
        print("❌ Error: WEBSITE_DATA_SHEET_ID environment variable is missing.")
        return

    scopes = ['https://www.googleapis.com/auth/spreadsheets']

    try:
        creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
        sheets_service = build('sheets', 'v4', credentials=creds)

        print(f"📡 Ingesting 'DPA' tab via API from Sheet ID: {sheet_id}...")
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range="DPA!A:Z"
        ).execute()

        rows = result.get('values', [])
        records = parse_sheet_values(rows)

        os.makedirs(os.path.dirname(DPA_OUTPUT_PATH), exist_ok=True)
        with open(DPA_OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)

        print(f"✅ Success! Compiled {len(records)} assistance programs into {DPA_OUTPUT_PATH}")

    except Exception as e:
        print(f"❌ Failure compiling DPA spreadsheet via API: {e}")

if __name__ == "__main__":
    run_dpa_pipeline()