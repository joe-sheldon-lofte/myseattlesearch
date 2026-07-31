# File: scripts/harvest_infosparks.py

import os
import io
import json
import urllib.request
import pandas as pd
from datetime import datetime
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

def harvest_infosparks():
    print("📡 Starting Google Service Agent InfoSparks Live Feed Pipeline...")
    
    output_file = "data/infosparks_stats.json"
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
        
        print(f"📡 Ingesting 'InfoSparks' configuration tab via API from ID: {sheet_id}...")
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range="InfoSparks!A:Z"
        ).execute()
        
        rows = result.get('values', [])
        config_records = parse_sheet_values(rows)
        
        master_feeds = {}

        for idx, row in enumerate(config_records):
            group_val = row.get("Group", f"{idx}").strip()
            cities_val = row.get("Cities", "").strip()
            metric_val = row.get("Metric", "metric").strip()
            
            # Accommodate variations in column naming ('CSV Link', 'Link', 'URL')
            url = (
                row.get("CSV Link") 
                or row.get("Link") 
                or row.get("URL") 
                or ""
            ).strip()
            
            if not url.startswith("http"):
                continue

            # Build standardized dictionary key
            clean_key = f"group_{group_val}_{metric_val}".lower()
            for char in [" ", "-", "/", "(", ")", ","]:
                clean_key = clean_key.replace(char, "_")
            while "__" in clean_key:
                clean_key = clean_key.replace("__", "_")
            clean_key = clean_key.strip("_")

            print(f"   📥 Downloading live InfoSparks feed: {clean_key}...")
            
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=10) as response:
                    raw_text = response.read().decode('utf-8')
                
                lines = raw_text.strip().split('\n')
                header_idx = 0
                for line_num, line in enumerate(lines):
                    first_cell = line.split(',')[0].strip().strip('"').strip("'").lower()
                    if first_cell in ['month', 'date']:
                        header_idx = line_num
                        break
                
                clean_csv_text = '\n'.join(lines[header_idx:])
                df = pd.read_csv(io.StringIO(clean_csv_text))
                df.columns = [c.strip() for c in df.columns]
                df = df.fillna("")
                
                master_feeds[clean_key] = {
                    "meta": {
                        "group": group_val,
                        "metric": metric_val,
                        "geographies": [c.strip() for c in cities_val.split(",") if c.strip()]
                    },
                    "data": df.to_dict(orient="records")
                }
            except Exception as feed_err:
                print(f"   ⚠️ Warning: Failed downloading feed row {idx} ({clean_key}): {feed_err}")

        output_payload = {
            "last_compiled": datetime.utcnow().isoformat() + "Z",
            "feeds": master_feeds
        }
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(output_payload, f, indent=4, ensure_ascii=False)
            
        print(f"✅ InfoSparks pipeline complete! ({len(master_feeds)} feeds compiled into {output_file})")
        
    except Exception as e:
        print(f"❌ Critical failure in InfoSparks pipeline: {e}")
        exit(1)

if __name__ == "__main__":
    harvest_infosparks()