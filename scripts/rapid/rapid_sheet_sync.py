import os
import json
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']

def parse_sheet_values(rows):
    if not rows:
        return []
    headers = [str(h).strip() for h in rows[0]]
    records = []
    for row in rows[1:]:
        padded = list(row) + [""] * (len(headers) - len(row))
        records.append(dict(zip(headers, [str(i).strip() if i is not None else "" for i in padded])))
    return records

def main():
    print("⚡ [Rapid Sync] Ingesting Market Dashboard telemetry...")
    os.makedirs(DATA_DIR, exist_ok=True)

    master_sheet_id = os.environ.get("WEBSITE_DATA_CORE_SHEET_ID")
    creds_path = "credentials.json"
    if not master_sheet_id or not os.path.exists(creds_path):
        print("❌ [Rapid Sync] Missing credentials or Sheet ID.")
        return

    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    sheets_service = build('sheets', 'v4', credentials=creds)

    res = sheets_service.spreadsheets().values().get(
        spreadsheetId=master_sheet_id,
        range="Market_Dashboard!A:Z"
    ).execute()

    rows = res.get('values', [])
    if rows:
        records = parse_sheet_values(rows)
        with open(os.path.join(DATA_DIR, "hourly_market.json"), "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
        print(f"   Updated hourly_market.json ({len(records)} records).")

    print("✅ [Rapid Sync] Market telemetry refresh complete.")

if __name__ == "__main__":
    main()