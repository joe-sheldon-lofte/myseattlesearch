import os
import json
import gspread
from google.oauth2.service_account import Credentials

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly"
]

def get_gspread_client():
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
            print(f"⚠️ Could not parse JSON credentials env var: {e}")

    if os.path.exists("credentials.json"):
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
        return gspread.authorize(creds)

    raise FileNotFoundError("Google service account credentials not found.")

def harvest_city_data(client):
    sheet_id = os.environ.get("CITY_DATA_SHEET_ID")
    if not sheet_id:
        print("ℹ️ CITY_DATA_SHEET_ID environment variable not set. Skipping CityData.")
        return

    doc = client.open_by_key(sheet_id)
    try:
        worksheet = doc.worksheet("CityData")
    except gspread.exceptions.WorksheetNotFound:
        worksheet = doc.worksheet("City Data")
        
    records = worksheet.get_all_records()
    os.makedirs(DATA_DIR, exist_ok=True)
    out_path = os.path.join(DATA_DIR, "city_data.json")
    
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    
    print(f"💾 Saved {len(records)} city master records to {out_path}")

def harvest_website_stats(client):
    sheet_id = os.environ.get("WEBSITE_DATA_SHEET_ID")
    if not sheet_id:
        print("ℹ️ WEBSITE_DATA_SHEET_ID environment variable not set. Skipping Stats sync.")
        return

    doc = client.open_by_key(sheet_id)
    try:
        worksheet = doc.worksheet("Stats")
        records = worksheet.get_all_records()
        os.makedirs(DATA_DIR, exist_ok=True)
        out_path = os.path.join(DATA_DIR, "stats.json")
        
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
        
        print(f"💾 Saved stats records to {out_path}")
    except gspread.exceptions.WorksheetNotFound:
        print("ℹ️ 'Stats' worksheet not found in Website Data workbook. Skipping.")

def harvest_transit_data(client):
    sheet_id = os.environ.get("CITY_DATA_SHEET_ID")
    if not sheet_id:
        print("ℹ️ CITY_DATA_SHEET_ID environment variable not set. Skipping TransitData sync.")
        return

    doc = client.open_by_key(sheet_id)
    try:
        worksheet = doc.worksheet("TransitData")
        records = worksheet.get_all_records()
        os.makedirs(DATA_DIR, exist_ok=True)
        out_path = os.path.join(DATA_DIR, "transit_data.json")
        
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
        
        print(f"💾 Saved {len(records)} transit rules to {out_path}")
    except gspread.exceptions.WorksheetNotFound:
        print("ℹ️ 'TransitData' worksheet not found in City Data workbook. Skipping.")

def main():
    print("📊 Starting Daily Google Sheets Tab Ingestion...")
    client = get_gspread_client()
    harvest_city_data(client)
    harvest_website_stats(client)
    harvest_transit_data(client)

if __name__ == "__main__":
    main()