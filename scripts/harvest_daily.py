# File: scripts/harvest_daily.py

import os
import json
import traceback
import gspread
from google.oauth2.service_account import Credentials

# --- GOOGLE SHEETS AUTHENTICATION ---
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly"
]

def get_gspread_client():
    # 1. Try reading JSON string directly from environment variable
    creds_json = (
        os.environ.get("GA_GOOGLE_CREDENTIALS") or 
        os.environ.get("GOOGLE_CREDENTIALS") or 
        os.environ.get("GA_CREDENTIALS")
    )
    if creds_json and creds_json.strip():
        try:
            creds_dict = json.loads(creds_json)
            creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
            return gspread.authorize(creds)
        except Exception as e:
            print(f"⚠️ Could not parse JSON from environment variable: {e}")

    # 2. Fallback to local credentials.json file on disk
    if os.path.exists("credentials.json"):
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
        return gspread.authorize(creds)

    raise FileNotFoundError("Google service account credentials not found. Ensure GA_GOOGLE_CREDENTIALS secret is configured.")

def safe_run(task_name, func):
    print(f"🚀 Starting daily task: {task_name}...")
    try:
        func()
        print(f"✅ Completed daily task: {task_name}\n")
    except Exception as e:
        print(f"❌ Error during {task_name}: {e}")
        print(traceback.format_exc())
        print(f"⚠️ Skipping {task_name}. Existing JSON dataset preserved.\n")

# --- HARVEST TASK 1: CITY DATA MASTER WORKBOOK ---
def harvest_city_data():
    client = get_gspread_client()
    sheet_id = os.environ.get("CITY_DATA_SHEET_ID")
    if not sheet_id:
        print("ℹ️ CITY_DATA_SHEET_ID environment variable not set. Skipping.")
        return

    doc = client.open_by_key(sheet_id)
    
    # Try tab named 'CityData' or 'City Data'
    try:
        worksheet = doc.worksheet("CityData")
    except gspread.exceptions.WorksheetNotFound:
        worksheet = doc.worksheet("City Data")
        
    records = worksheet.get_all_records()

    os.makedirs("data", exist_ok=True)
    out_path = os.path.join("data", "city_data.json")
    
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    
    print(f"💾 Saved {len(records)} city master records to {out_path}")

# --- HARVEST TASK 2: WEBSITE STATS TAB ---
def harvest_website_stats():
    client = get_gspread_client()
    sheet_id = os.environ.get("WEBSITE_DATA_SHEET_ID")
    if not sheet_id:
        print("ℹ️ WEBSITE_DATA_SHEET_ID environment variable not set. Skipping stats sync.")
        return

    doc = client.open_by_key(sheet_id)
    try:
        worksheet = doc.worksheet("Stats")
        records = worksheet.get_all_records()
        
        os.makedirs("data", exist_ok=True)
        out_path = os.path.join("data", "stats.json")
        
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
        
        print(f"💾 Saved stats records to {out_path}")
    except gspread.exceptions.WorksheetNotFound:
        print("ℹ️ 'Stats' worksheet not found in Website Data workbook. Skipping.")

def main():
    print("==================================================")
    print("       MYSEATTLESEARCH DAILY DATA HARVESTER       ")
    print("==================================================\n")
    
    safe_run("City Data Master Sheet Sync (data/city_data.json)", harvest_city_data)
    safe_run("Website Data Stats Sync (data/stats.json)", harvest_website_stats)
    
    print("🎉 Daily data harvesting sequence completed.")

if __name__ == "__main__":
    main()