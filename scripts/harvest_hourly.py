/* File: scripts/harvest_hourly.py */
import pandas as pd
import json
import os

# ==========================================
# CONFIGURATION
# ==========================================
MARKET_DASHBOARD_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQ4Q94pArPoza2zWVI7dZagdcDBhIzdX9wtmrDbgJ_4h1rRr_WFuaMTjTfrJVVGQwbNGGLiSK2zCGnh/pub?gid=0&single=true&output=csv"
RATES_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQ4Q94pArPoza2zWVI7dZagdcDBhIzdX9wtmrDbgJ_4h1rRr_WFuaMTjTfrJVVGQwbNGGLiSK2zCGnh/pub?gid=1486733951&single=true&output=csv"

OUTPUT_MARKET_FILE = "data/hourly_market.json"
OUTPUT_RATES_FILE = "data/hourly_rates.json"

def harvest_hourly_data():
    print("Fetching Hourly Dashboard & Rates Data...")
    try:
        # 1. Fetch & Save Market Dashboard
        print(" -> Downloading Market Dashboard...")
        df_market = pd.read_csv(MARKET_DASHBOARD_CSV_URL)
        if 'City' in df_market.columns:
            df_market = df_market.dropna(subset=['City'])
        df_market = df_market.fillna("")
        
        market_records = df_market.to_dict(orient='records')
        os.makedirs(os.path.dirname(OUTPUT_MARKET_FILE), exist_ok=True)
        
        with open(OUTPUT_MARKET_FILE, 'w', encoding='utf-8') as f:
            json.dump(market_records, f, indent=4)
        print(f"✅ Saved {len(market_records)} cities to {OUTPUT_MARKET_FILE}")

        # 2. Fetch & Save Mortgage Rates
        print(" -> Downloading Mortgage Rates...")
        df_rates = pd.read_csv(RATES_CSV_URL)
        df_rates = df_rates.fillna("")
        
        rates_records = df_rates.to_dict(orient='records')
        with open(OUTPUT_RATES_FILE, 'w', encoding='utf-8') as f:
            json.dump(rates_records, f, indent=4)
        print(f"✅ Saved {len(rates_records)} daily rate entries to {OUTPUT_RATES_FILE}")

        print("🎉 Hourly data harvest complete!")
        
    except Exception as e:
        print(f"❌ Error harvesting hourly data: {e}")
        exit(1)

if __name__ == "__main__":
    harvest_hourly_data()