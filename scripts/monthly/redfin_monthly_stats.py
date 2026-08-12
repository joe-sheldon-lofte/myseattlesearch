import os
import json
import io
import requests
import pandas as pd
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
REDFIN_MONTHLY_OUT = os.path.join(DATA_DIR, "redfin_monthly_stats.json")
REDFIN_MIGRATION_OUT = os.path.join(DATA_DIR, "redfin_migration.json")

# Redfin S3 Endpoints
ENDPOINTS = {
    "affordability": "https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_data_center/housing_affordability_tracker/top_100_metros.csv",
    "migration": "https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_data_center/migration_traffic/od_pairs/all_metros.csv",
    "loan_types": "https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_data_center/all_cash_loan_types/all_metros.csv",
    "investors": "https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_data_center/investors/by_metro/all_metros.csv",
    "balance_of_power": "https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_data_center/buyers_and_sellers/monthly/top_50_metros.csv"
}

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

def fetch_csv(url):
    try:
        res = requests.get(url, headers=HEADERS_HTTP, timeout=45)
        if res.status_code == 200:
            return pd.read_csv(io.StringIO(res.text))
        else:
            print(f"   ❌ HTTP {res.status_code} error fetching {url}")
    except Exception as e:
        print(f"   ⚠️ Exception querying {url}: {e}")
    return None

def process_affordability():
    print("  • Fetching Housing Affordability Tracker...")
    df = fetch_csv(ENDPOINTS["affordability"])
    if df is None or df.empty: return []
    
    seattle_df = df[df['REGION NAME'].astype(str).str.contains('Seattle', case=False, na=False)].copy()
    if seattle_df.empty: return []
    
    latest_period = seattle_df['PERIOD END'].max()
    filtered_df = seattle_df[seattle_df['PERIOD END'] == latest_period].copy()
    return filtered_df.fillna("").to_dict(orient="records")

def process_balance_of_power():
    print("  • Fetching Buyers vs. Sellers Balance of Power...")
    df = fetch_csv(ENDPOINTS["balance_of_power"])
    if df is None or df.empty: return []
    
    seattle_df = df[df['REGION NAME'].astype(str).str.contains('Seattle', case=False, na=False)].copy()
    if seattle_df.empty: return []
    
    latest_period = seattle_df['PERIOD END'].max()
    filtered_df = seattle_df[seattle_df['PERIOD END'] == latest_period].copy()
    return filtered_df.fillna("").to_dict(orient="records")

def process_investor_purchases():
    print("  • Fetching Investor Home Purchases...")
    df = fetch_csv(ENDPOINTS["investors"])
    if df is None or df.empty: return []
    
    seattle_df = df[df['REGION NAME'].astype(str).str.contains('Seattle', case=False, na=False)].copy()
    if seattle_df.empty: return []
    
    latest_period = seattle_df['PERIOD END'].max()
    filtered_df = seattle_df[seattle_df['PERIOD END'] == latest_period].copy()
    return filtered_df.fillna("").to_dict(orient="records")

def process_loan_types():
    print("  • Fetching Cash Purchases & Loan Types Breakdown...")
    df = fetch_csv(ENDPOINTS["loan_types"])
    if df is None or df.empty: return []
    return df.fillna("").to_dict(orient="records")

def process_migration():
    print("  • Fetching Nationwide Origin-Destination Migration Traffic...")
    df = fetch_csv(ENDPOINTS["migration"])
    if df is None or df.empty: return {}

    # Filter latest period and remove self-migration
    latest_period = df['PERIOD END'].max()
    df_clean = df[
        (df['PERIOD END'] == latest_period) & 
        (df['ORIGIN REGION NAME'] != df['DESTINATION REGION NAME'])
    ].copy()

    # Calculate Top 5 Outflow and Top 5 Inflow for every metro area
    top5_outflow = df_clean.sort_values(by=['ORIGIN REGION NAME', 'FLOW'], ascending=[True, False]).groupby('ORIGIN REGION NAME').head(5)
    top5_inflow = df_clean.sort_values(by=['DESTINATION REGION NAME', 'FLOW'], ascending=[True, False]).groupby('DESTINATION REGION NAME').head(5)

    all_metros = set(df_clean['ORIGIN REGION NAME']).union(set(df_clean['DESTINATION REGION NAME']))

    migration_map = {}
    for metro in sorted(all_metros):
        out_recs = top5_outflow[top5_outflow['ORIGIN REGION NAME'] == metro][
            ['DESTINATION REGION NAME', 'FLOW', 'PCT OF ORIGIN OUTFLOW (%)', 'NET FLOW (ORIGIN TO DESTINATION)']
        ].fillna("").to_dict(orient='records')
        
        in_recs = top5_inflow[top5_inflow['DESTINATION REGION NAME'] == metro][
            ['ORIGIN REGION NAME', 'FLOW', 'PCT OF DESTINATION INFLOW (%)', 'NET FLOW (ORIGIN TO DESTINATION)']
        ].fillna("").to_dict(orient='records')
        
        if out_recs or in_recs:
            migration_map[metro] = {
                "top_outflow": out_recs,
                "top_inflow": in_recs
            }

    return {
        "latest_period": latest_period,
        "metros": migration_map
    }

def main():
    print("==================================================")
    print("   RED FIN MONTHLY ADVANCED DATA HARVESTER        ")
    print("==================================================\n")

    os.makedirs(DATA_DIR, exist_ok=True)

    # Compile Combined Monthly Stats Object
    monthly_stats = {
        "last_updated_utc": datetime.now(timezone.utc).isoformat(),
        "affordability": process_affordability(),
        "balance_of_power": process_balance_of_power(),
        "investor_purchases": process_investor_purchases(),
        "loan_types": process_loan_types()
    }

    with open(REDFIN_MONTHLY_OUT, "w", encoding="utf-8") as f:
        json.dump(monthly_stats, f, indent=2, ensure_ascii=False)
    print(f"💾 Saved combined Redfin monthly metrics to {REDFIN_MONTHLY_OUT}")

    # Compile Migration Object
    migration_payload = {
        "last_updated_utc": datetime.now(timezone.utc).isoformat(),
        "data": process_migration()
    }

    with open(REDFIN_MIGRATION_OUT, "w", encoding="utf-8") as f:
        json.dump(migration_payload, f, indent=2, ensure_ascii=False)
    print(f"💾 Saved nationwide Redfin migration matrix to {REDFIN_MIGRATION_OUT}")

    print("\n🎉 Redfin monthly harvesting sequence complete!")

if __name__ == "__main__":
    main()