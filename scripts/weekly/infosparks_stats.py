import os
import json
import io
import requests
import pandas as pd
from datetime import datetime, timezone
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
INFOSPARKS_LINKS_OUT = os.path.join(DATA_DIR, "infosparks_links.json")
INFOSPARKS_STATS_OUT = os.path.join(DATA_DIR, "infosparks_stats.json")

SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']

METRIC_SLUG_MAP = {
    "Median Sale Price": "median_sale_price",
    "Closed Sales": "closed_sales",
    "Average Days on Market": "average_days_on_market",
    "Months Supply Closed": "months_supply_closed",
    "Shows Per Listing": "shows_per_listing",
    "Percent of List Price Average": "percent_of_list_price_average"
}

def slugify(text):
    if not text: return ""
    text = str(text).lower().strip()
    out = [ch if ch.isalnum() else '-' for ch in text]
    res = "".join(out)
    while '--' in res: res = res.replace('--', '-')
    return res.strip('-')

def get_sheets_service():
    creds_path = "credentials.json"
    creds = None
    creds_json = os.environ.get("GA_GOOGLE_CREDENTIALS") or os.environ.get("GA_CREDENTIALS")
    if creds_json and creds_json.strip():
        try:
            creds_dict = json.loads(creds_json)
            creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        except Exception:
            pass
    if not creds and os.path.exists(creds_path):
        try:
            creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
        except Exception:
            pass
    if creds:
        return build('sheets', 'v4', credentials=creds)
    return None

def parse_infosparks_csv_text(csv_text):
    if not csv_text or not csv_text.strip():
        return []
    lines = csv_text.splitlines()
    header_idx = None
    for idx, line in enumerate(lines):
        if line.startswith('Date') or line.startswith('"Date"'):
            header_idx = idx
            break
            
    if header_idx is not None:
        table_text = "\n".join(lines[header_idx:])
        df = pd.read_csv(io.StringIO(table_text))
        df = df.loc[:, ~df.columns.str.contains('^Unnamed')]
        if 'Date' in df.columns:
            df = df[~df['Date'].astype(str).str.contains('Northwest Multiple Listing Service|ShowingTime|All data from', case=False, na=False)]
        df = df.fillna("")
        return df.to_dict(orient="records")
    return []

def sync_infosparks_links():
    print("📋 [Step 1] Syncing InfoSparks CSV links from Google Sheet...")
    sheet_id = os.environ.get("CITY_DATA_SHEET_ID")
    service = get_sheets_service()

    if not sheet_id or not service:
        print("ℹ️ CITY_DATA_SHEET_ID or credentials missing. Skipping Google Sheet sync, using local infosparks_links.json.")
        return

    try:
        res = service.spreadsheets().values().get(spreadsheetId=sheet_id, range="InfoSparks!A:D").execute()
        rows = res.get('values', [])
        if not rows or len(rows) < 2:
            print("ℹ️ No rows found in InfoSparks sheet tab.")
            return

        headers = [str(h).strip() for h in rows[0]]
        col_group = headers.index("Group") if "Group" in headers else 0
        col_cities = headers.index("Cities") if "Cities" in headers else 1
        col_metric = headers.index("Metric") if "Metric" in headers else 2
        col_link = headers.index("CSV Link") if "CSV Link" in headers else 3

        links_registry = {}
        for idx, r in enumerate(rows[1:]):
            padded = list(r) + [""] * (len(headers) - len(r))
            group_num = str(padded[col_group]).strip()
            cities_str = str(padded[col_cities]).strip()
            metric_raw = str(padded[col_metric]).strip()
            csv_url = str(padded[col_link]).strip()

            if not csv_url or not csv_url.startswith("http"):
                continue

            geographies = [c.strip() for c in cities_str.split(",") if c.strip()]
            metric_slug = METRIC_SLUG_MAP.get(metric_raw, slugify(metric_raw).replace('-', '_'))
            feed_key = f"group_{group_num}_{metric_slug}"

            links_registry[feed_key] = {
                "group": group_num,
                "metric": metric_raw,
                "geographies": geographies,
                "csv_url": csv_url
            }

        if links_registry:
            links_payload = {
                "last_synced_utc": datetime.now(timezone.utc).isoformat(),
                "total_links": len(links_registry),
                "links": links_registry
            }
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(INFOSPARKS_LINKS_OUT, "w", encoding="utf-8") as f:
                json.dump(links_payload, f, indent=4, ensure_ascii=False)
            print(f"   ✅ Saved {len(links_registry)} links to {INFOSPARKS_LINKS_OUT}")

    except Exception as e:
        print(f"⚠️ Google Sheet InfoSparks link sync notice: {e}")

def parse_infosparks_csv_data():
    print("📊 [Step 2] Ingesting live InfoSparks CSV data using infosparks_links.json...")
    if not os.path.exists(INFOSPARKS_LINKS_OUT):
        print("ℹ️ infosparks_links.json not found. Preserving local infosparks_stats.json.")
        return

    try:
        with open(INFOSPARKS_LINKS_OUT, "r", encoding="utf-8") as f:
            links_file = json.load(f)

        links_registry = links_file.get("links", {})
        if not links_registry:
            print("ℹ️ No links contained in infosparks_links.json.")
            return

        feeds_output = {}
        headers_http = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

        for feed_key, info in links_registry.items():
            csv_url = info.get("csv_url", "")
            if not csv_url or not csv_url.startswith("http"):
                continue

            try:
                csv_res = requests.get(csv_url, headers=headers_http, timeout=15)
                if csv_res.status_code == 200:
                    data_records = parse_infosparks_csv_text(csv_res.text)
                    if data_records:
                        feeds_output[feed_key] = {
                            "meta": {
                                "group": info.get("group"),
                                "metric": info.get("metric"),
                                "geographies": info.get("geographies", [])
                            },
                            "data": data_records
                        }
            except Exception as e:
                print(f"   ⚠️ Failed to download CSV [{csv_url[:50]}...]: {e}")

        if feeds_output:
            final_payload = {
                "last_compiled": datetime.now(timezone.utc).isoformat(),
                "feeds": feeds_output
            }
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(INFOSPARKS_STATS_OUT, "w", encoding="utf-8") as f:
                json.dump(final_payload, f, indent=4, ensure_ascii=False)
            print(f"💾 Saved {len(feeds_output)} live InfoSparks metrics to {INFOSPARKS_STATS_OUT}")

    except Exception as e:
        print(f"❌ Error during InfoSparks CSV data parsing: {e}")

def main():
    sync_infosparks_links()
    parse_infosparks_csv_data()

if __name__ == "__main__":
    main()