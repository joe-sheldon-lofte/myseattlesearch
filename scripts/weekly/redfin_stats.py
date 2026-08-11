import os
import json
import io
import gzip
import requests
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
REDFIN_OUT = os.path.join(DATA_DIR, "redfin_stats.json")
CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")

REDFIN_ENDPOINTS = [
    "https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_market_tracker/city_market_tracker.tsv000.gz",
    "https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_market_tracker/city_market_tracker.tsv.gz"
]

def main():
    print("📈 Ingesting Redfin Data Center WA city market tracker...")
    
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

    headers_http = {"User-Agent": "Mozilla/5.0"}
    df_raw = None

    for url in REDFIN_ENDPOINTS:
        try:
            res = requests.get(url, headers=headers_http, timeout=45)
            if res.status_code == 200:
                with gzip.open(io.BytesIO(res.content), 'rt', encoding='utf-8') as gz:
                    df_raw = pd.read_csv(gz, sep='\t')
                print(f"   ✅ Successfully fetched Redfin S3 stream: {url}")
                break
        except Exception as e:
            print(f"   ⚠️ Notice querying {url}: {e}")

    if df_raw is None or df_raw.empty:
        print("⚠️ Unable to retrieve Redfin dataset across endpoints. Preserving existing local data.")
        return

    try:
        df_wa = df_raw[(df_raw['state_code'] == 'WA') & (df_raw['city'].str.lower().isin(target_cities))]
        
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
        
        if 'period_end' in df_filtered.columns and not df_filtered.empty:
            latest_period = df_filtered['period_end'].max()
            print(f"   🔍 Verified Redfin dataset latest period_end: {latest_period}")

        df_filtered = df_filtered.fillna("")
        records = df_filtered.to_dict(orient="records")
        
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(REDFIN_OUT, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
        print(f"💾 Saved {len(records)} Redfin city market trend records to {REDFIN_OUT}")

    except Exception as e:
        print(f"❌ Error transforming Redfin dataset: {e}")

if __name__ == "__main__":
    main()