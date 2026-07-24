# File: scripts/harvest_city_data.py

import os
import json
import warnings
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

def parse_sheet_values(rows):
    """
    Parses raw Google Sheets 2D array into a list of dictionaries with header keys.
    """
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

def harvest_city_data():
    print("📡 Starting Google Service Agent City Data Pipeline...")
    
    output_file = "data/city_data.json"
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    
    creds_path = "credentials.json"
    if not os.path.exists(creds_path):
        print("❌ Error: credentials.json missing from root execution context.")
        exit(1)
        
    sheet_id = os.environ.get("CITY_DATA_SHEET_ID")
    if not sheet_id:
        print("❌ Error: CITY_DATA_SHEET_ID environment variable is missing.")
        exit(1)
        
    scopes = ['https://www.googleapis.com/auth/spreadsheets']
    
    try:
        creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
        sheets_service = build('sheets', 'v4', credentials=creds)
        
        print(f"📡 Fetching 'CityData' tab via Sheets API from ID: {sheet_id}...")
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range="CityData!A:Z"
        ).execute()
        
        rows = result.get('values', [])
        if not rows:
            print("⚠️ Warning: No rows returned from CityData tab.")
            records = []
        else:
            records = parse_sheet_values(rows)
            # Filter out entries where 'City' is blank or unpopulated
            records = [r for r in records if r.get("City")]
            
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(records, f, indent=4, ensure_ascii=False)
            
        print(f"✅ Successfully harvested and saved {len(records)} city records to {output_file}")
        
    except Exception as e:
        print(f"❌ Error harvesting city data via API: {e}")
        exit(1)

if __name__ == "__main__":
    harvest_city_data()