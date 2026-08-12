import os
import json
import io
import requests
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
REDFIN_OUT = os.path.join(DATA_DIR, "redfin_stats.json")
CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")

REDFIN_CSV_URL = "https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_data_center/housing_market/monthly/all_cities.csv"

HEADERS_HTTP = {
    'Origin': 'https://www.redfin.com',
    'Referer': 'https://www.redfin.com/',
    'Accept': '*/*',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'cross-site',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.5.2 Safari/605.1.15',
    'Pragma': 'no-cache',
    'Cache-Control': 'no-cache',
}

def main():
    print("📈 Ingesting Redfin Data Center WA city market tracker (Latest Period Only)...")
    
    target_cities = set()
    if os.path.exists(CITY_DATA_PATH):
        try:
            with open(CITY_DATA_PATH, "r", encoding="utf-8") as f:
                c_data = json.load(f)
                items = c_data if isinstance(c_data, list) else list(c_data.values())
                for it in items:
                    name = it.get("City") or it.get("name") or ""
                    if name: 
                        target_cities.add(str(name).strip().lower())
        except Exception as e:
            print(f"   ⚠️ City data read notice: {e}")

    df_raw = None
    try:
        res = requests.get(REDFIN_CSV_URL, headers=HEADERS_HTTP, timeout=45)
        if res.status_code == 200:
            df_raw = pd.read_csv(io.StringIO(res.text))
            print(f"   ✅ Successfully downloaded active Redfin CSV dataset ({len(df_raw)} total rows)")
        else:
            print(f"   ❌ HTTP {res.status_code} error fetching Redfin CSV endpoint.")
    except Exception as e:
        print(f"   ⚠️ Exception querying Redfin CSV endpoint: {e}")

    if df_raw is None or df_raw.empty:
        print("⚠️ Unable to retrieve Redfin CSV dataset. Preserving existing local data.")
        return

    try:
        # Match "City, WA" format in REGION NAME against target_cities
        def match_city(region_name):
            if not isinstance(region_name, str):
                return None
            parts = region_name.split(',')
            if len(parts) == 2 and parts[1].strip().upper() == 'WA':
                c_name = parts[0].strip().lower()
                if c_name in target_cities:
                    return parts[0].strip()
            return None

        df_raw['matched_city'] = df_raw['REGION NAME'].apply(match_city)
        df_matched = df_raw[df_raw['matched_city'].notnull()].copy()

        if df_matched.empty:
            print("⚠️ No matching Washington target cities found in Redfin CSV file.")
            return

        # FILTER: Retain ONLY rows corresponding to the absolute latest PERIOD END date
        if 'PERIOD END' in df_matched.columns:
            latest_period = df_matched['PERIOD END'].max()
            df_matched = df_matched[df_matched['PERIOD END'] == latest_period].copy()
            print(f"   🔍 Filtered Redfin dataset to latest period_end only: {latest_period}")

        records = []
        for _, row in df_matched.iterrows():
            homes_sold = float(row["HOMES SOLD"]) if pd.notnull(row.get("HOMES SOLD")) else 0.0
            active_listings = float(row["ACTIVE LISTINGS"]) if pd.notnull(row.get("ACTIVE LISTINGS")) else 0.0
            
            # For 3-month rolling window, monthly absorption rate ~ homes_sold / 3
            mos = round(active_listings / (homes_sold / 3.0), 1) if homes_sold > 0 else 0.0
            friction = int(round(mos * 10))

            rec = {
                "period_begin": str(row.get("PERIOD BEGIN", "")),
                "period_end": str(row.get("PERIOD END", "")),
                "region_type": str(row.get("REGION TYPE", "City")),
                "city": str(row.get("matched_city", "")),
                "state": "WA",
                "state_code": "WA",
                "property_type": "All Residential",
                "median_sale_price": float(row["MEDIAN SALE PRICE NSA ($)"]) if pd.notnull(row.get("MEDIAN SALE PRICE NSA ($)")) else None,
                "median_dom": float(row["MEDIAN DAYS ON MARKET (DAYS)"]) if pd.notnull(row.get("MEDIAN DAYS ON MARKET (DAYS)")) else None,
                "homes_sold": homes_sold,
                "active_listings": active_listings,
                "inventory": active_listings,
                "new_listings": float(row["NEW LISTINGS"]) if pd.notnull(row.get("NEW LISTINGS")) else None,
                "pending_sales": float(row["PENDING SALES"]) if pd.notnull(row.get("PENDING SALES")) else None,
                "price_per_sqft": float(row["MEDIAN NEW LISTING PRICE PER SQ.FT. ($)"]) if pd.notnull(row.get("MEDIAN NEW LISTING PRICE PER SQ.FT. ($)")) else None,
                "months_of_supply": mos,
                "market_friction_index": friction,
                "last_updated": str(row.get("LAST UPDATED", ""))
            }
            records.append(rec)

        os.makedirs(DATA_DIR, exist_ok=True)
        with open(REDFIN_OUT, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
        print(f"💾 Saved {len(records)} active latest-period Redfin market records to {REDFIN_OUT}")

    except Exception as e:
        print(f"❌ Error transforming Redfin CSV dataset: {e}")

if __name__ == "__main__":
    main()