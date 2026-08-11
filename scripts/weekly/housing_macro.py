import os
import json
import io
import gzip
import requests
import pandas as pd
from datetime import datetime, timezone
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
INFOSPARKS_LINKS_OUT = os.path.join(DATA_DIR, "infosparks_links.json")
INFOSPARKS_STATS_OUT = os.path.join(DATA_DIR, "infosparks_stats.json")
REDFIN_OUT = os.path.join(DATA_DIR, "redfin_stats.json")
CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")

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

# STEP 1: Sync Google Sheet links tab to data/infosparks_links.json
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

# STEP 2: Download live CSV data using data/infosparks_links.json
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
                    df = pd.read_csv(io.StringIO(csv_res.text))
                    df = df.loc[:, ~df.columns.str.contains('^Unnamed')]
                    df = df.fillna("")
                    
                    data_records = df.to_dict(orient="records")
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

# STEP 3: Redfin Public Data Center Ingestion
def fetch_redfin_data():
    print("📈 Ingesting Redfin Data Center WA city market tracker...")
    redfin_url = "https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_market_tracker/city_market_tracker.tsv.gz"
    
    target_cities = set()
    if os.path.exists(CITY_DATA_PATH):
        try:
            with open(CITY_DATA_PATH, "r", encoding="utf-8") as f:
                c_data = json.load(f)
                items = c_data if isinstance(c_data, list) else list(c_data.values())
                for it in items:
                    name = it.get("City") or it.get("name") or ""
                    if name: target_cities.add(str(name).strip().lower())
        except Exception:
            pass

    try:
        headers_http = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(redfin_url, headers=headers_http, timeout=30)
        if res.status_code == 200:
            with gzip.open(io.BytesIO(res.content), 'rt', encoding='utf-8') as gz:
                df = pd.read_csv(gz, sep='\t')

            df_wa = df[(df['state_code'] == 'WA') & (df['city'].str.lower().isin(target_cities))]
            
            desired_cols = [
                'period_begin', 'period_end', 'region_type', 'city', 'state', 'state_code',
                'property_type', 'median_sale_price', 'median_sale_price_yoy', 'median_dom',
                'avg_sale_to_list', 'homes_sold', 'homes_sold_yoy', 'inventory', 'months_of_supply',
                'sold_above_list', 'price_drops', 'off_market_in_two_weeks'
            ]
            
            avail_cols = [c for c in desired_cols if c in df_wa.columns]
            df_filtered = df_wa[avail_cols].copy()
            df_filtered = df_filtered.sort_values(by=['city', 'period_begin'], ascending=[True, True])
            
            df_filtered['market_friction_index'] = (df_filtered['months_of_supply'].fillna(0) * 10).round().astype(int)
            df_filtered = df_filtered.fillna("")

            records = df_filtered.to_dict(orient="records")
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(REDFIN_OUT, "w", encoding="utf-8") as f:
                json.dump(records, f, indent=2, ensure_ascii=False)
            print(f"💾 Saved {len(records)} Redfin city market trend records to {REDFIN_OUT}")

    except Exception as e:
        print(f"⚠️ Redfin live fetch notice (preserving existing dataset): {e}")

def main():
    sync_infosparks_links()
    parse_infosparks_csv_data()
    fetch_redfin_data()

if __name__ == "__main__":
    main()