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
    print("📅 Running Weekly Sheets Ingestion...")
    os.makedirs(DATA_DIR, exist_ok=True)

    master_sheet_id = os.environ.get("WEBSITE_DATA_CORE_SHEET_ID")
    creds_path = "credentials.json"
    if not master_sheet_id or not os.path.exists(creds_path):
        print("❌ Missing credentials or Sheet ID.")
        return

    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    sheets_service = build('sheets', 'v4', credentials=creds)

    tabs = [
        "Team", "Reviews", "ThirdPartyPrograms", "MatrixKeepAlive",
        "BuyerGuide", "SellerGuide", "GuideFAQs", "ElectionSchedule", "CommuteHubBaselines"
    ]
    ranges = [f"{tab}!A:Z" for tab in tabs]
    res = sheets_service.spreadsheets().values().batchGet(spreadsheetId=master_sheet_id, ranges=ranges).execute()
    data = dict(zip(tabs, res.get('valueRanges', [])))

    mappings = [
        ("Team", "team.json"),
        ("Reviews", "reviews.json"),
        ("ThirdPartyPrograms", "thirdpartyprograms.json"),
        ("BuyerGuide", "buyer_guide.json"),
        ("SellerGuide", "seller_guide.json"),
        ("GuideFAQs", "guide_faqs.json"),
        ("ElectionSchedule", "election_schedule.json")
        ("CommuteHubBaselines", "commute_hub_baselines.json")
    ]
    for tab_name, json_name in mappings:
        rows = data.get(tab_name, {}).get('values', [])
        if rows:
            with open(os.path.join(DATA_DIR, json_name), "w", encoding="utf-8") as f:
                json.dump(parse_sheet_values(rows), f, indent=2, ensure_ascii=False)

    matrix_rows = data.get("MatrixKeepAlive", {}).get('values', [])
    if matrix_rows:
        recs = [r for r in parse_sheet_values(matrix_rows) if r.get("URL", "").strip()]
        with open(os.path.join(DATA_DIR, "matrix_keep_alive.json"), "w", encoding="utf-8") as f:
            json.dump(recs, f, indent=2, ensure_ascii=False)

    print("✅ Weekly Sheets Sync complete.")

if __name__ == "__main__":
    main()