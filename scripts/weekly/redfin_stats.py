import os
import json
import io
import requests
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
REDFIN_OUT = os.path.join(DATA_DIR, "redfin_stats.json")
CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")

# Redfin S3 Endpoints
REDFIN_KEY_METRICS_URL = "https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_data_center/housing_market/monthly/all_cities.csv"
REDFIN_CANCELLATIONS_URL = "https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_data_center/contract_cancellations/monthly/all_cities.csv"

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
    print("📈 Ingesting Redfin Key Metrics & Contract Cancellations for Local Cities...")
    
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

    def match_city(region_name):
        if not isinstance(region_name, str):
            return None
        parts = region_name.split(',')
        if len(parts) == 2 and parts[1].strip().upper() == 'WA':
            c_name = parts[0].strip().lower()
            if c_name in target_cities:
                return parts[0].strip()
        return None

    # 1. Download Key Housing Metrics
    df_km = None
    try:
        res_km = requests.get(REDFIN_KEY_METRICS_URL, headers=HEADERS_HTTP, timeout=45)
        if res_km.status_code == 200:
            df_km = pd.read_csv(io.StringIO(res_km.text))
            print(f"   ✅ Fetched Key Housing Metrics dataset ({len(df_km)} rows)")
    except Exception as e:
        print(f"   ⚠️ Exception querying Redfin Key Metrics endpoint: {e}")

    if df_km is None or df_km.empty:
        print("⚠️ Unable to retrieve Redfin key metrics. Preserving existing local dataset.")
        return

    # 2. Download Contract Cancellations
    df_canc = None
    try:
        res_canc = requests.get(REDFIN_CANCELLATIONS_URL, headers=HEADERS_HTTP, timeout=45)
        if res_canc.status_code == 200:
            df_canc = pd.read_csv(io.StringIO(res_canc.text))
            print(f"   ✅ Fetched Contract Cancellations dataset ({len(df_canc)} rows)")
    except Exception as e:
        print(f"   ⚠️ Exception querying Redfin Cancellations endpoint: {e}")

    try:
        # Match cities and filter for the latest PERIOD END
        df_km['matched_city'] = df_km['REGION NAME'].apply(match_city)
        latest_period = df_km[df_km['matched_city'].notnull()]['PERIOD END'].max()
        
        df_km_latest = df_km[
            (df_km['matched_city'].notnull()) & 
            (df_km['PERIOD END'] == latest_period)
        ].copy()

        # Filter Cancellations dataset
        canc_dict = {}
        if df_canc is not None and not df_canc.empty:
            df_canc['matched_city'] = df_canc['REGION NAME'].apply(match_city)
            df_canc_latest = df_canc[
                (df_canc['matched_city'].notnull()) & 
                (df_canc['PERIOD END'] == latest_period)
            ].copy()

            for _, row in df_canc_latest.iterrows():
                c_city = row['matched_city']
                canc_dict[c_city] = {
                    "cancellations": float(row["HOME PURCHASE CANCELLATIONS"]) if pd.notnull(row.get("HOME PURCHASE CANCELLATIONS")) else 0.0,
                    "cancellation_rate_pct": float(row["PERCENT OF PENDING SALES (%)"]) if pd.notnull(row.get("PERCENT OF PENDING SALES (%)")) else 0.0
                }

        records = []
        for _, row in df_km_latest.iterrows():
            city_name = row['matched_city']
            homes_sold = float(row["HOMES SOLD"]) if pd.notnull(row.get("HOMES SOLD")) else 0.0
            active_listings = float(row["ACTIVE LISTINGS"]) if pd.notnull(row.get("ACTIVE LISTINGS")) else 0.0
            
            # Calculate months of supply (3-month rolling absorption rate ~ homes_sold / 3)
            mos = round(active_listings / (homes_sold / 3.0), 1) if homes_sold > 0 else 0.0

            c_info = canc_dict.get(city_name, {"cancellations": 0.0, "cancellation_rate_pct": 0.0})

            rec = {
                "period_begin": str(row.get("PERIOD BEGIN", "")),
                "period_end": str(row.get("PERIOD END", "")),
                "region_type": str(row.get("REGION TYPE", "City")),
                "city": city_name,
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
                "contract_cancellations": c_info["cancellations"],
                "cancellation_rate_pct": c_info["cancellation_rate_pct"],
                "months_of_supply": mos,
                "last_updated": str(row.get("LAST UPDATED", ""))
            }
            records.append(rec)

        print(f"   🔍 Verified latest period_end: {latest_period}")
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(REDFIN_OUT, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
        print(f"💾 Saved {len(records)} active Redfin market records (with contract cancellations) to {REDFIN_OUT}")

    except Exception as e:
        print(f"❌ Error combining Redfin datasets: {e}")

if __name__ == "__main__":
    main()