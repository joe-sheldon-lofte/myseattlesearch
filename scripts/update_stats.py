import os
import json
import datetime
import pandas as pd

# Ensure output directory exists
os.makedirs('data', exist_ok=True)

# Generate a master timestamp for this execution
master_timestamp = datetime.datetime.utcnow().isoformat() + "Z"

# ==========================================
# CONFIGURATION
# ==========================================
TARGET_STATE = "WA"
# Cities matched to your exact spreadsheet requirements + Edmonds
TARGET_CITIES = [
    "Shoreline", "Lake Forest Park", "Mountlake Terrace", 
    "Lynnwood", "Mukilteo", "Brier", "Kenmore", "Kirkland", "Edmonds"
]
TARGET_PROPERTY_TYPES = ["Single Family Residential", "Condo/Co-op"]
START_DATE = "2024-01-01"

REDFIN_URL = "https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_market_tracker/city_market_tracker.tsv000.gz"
LINKS_CSV_PATH = "data/InfoSparks Links - Sheet1.csv"

# ==========================================
# 1. PROCESS REDFIN PIPELINE (Competition & Sentiment)
# ==========================================
print("Starting Redfin data pipeline...")
chunks = []

try:
    # Stream the large file in chunks to prevent GitHub runner memory overflow
    for chunk in pd.read_csv(REDFIN_URL, sep='\t', compression='gzip', chunksize=100000, low_memory=False):
        
        # DEFENSIVE FIX 1: Force all column headers to lowercase to bypass ALL CAPS shifts
        chunk.columns = chunk.columns.str.lower()
        
        # DEFENSIVE FIX 2: Dynamically detect if the file is using 'state_code' or 'state'
        state_column = 'state_code' if 'state_code' in chunk.columns else 'state'
        
        # Apply the filters safely using our normalized column schema
        filtered_chunk = chunk[
            (chunk[state_column] == TARGET_STATE) & 
            (chunk['city'].isin(TARGET_CITIES)) &
            (chunk['property_type'].isin(TARGET_PROPERTY_TYPES)) &
            (chunk['period_duration'].isin([30, 90])) & 
            (chunk['period_begin'] >= START_DATE)
        ]
        if not filtered_chunk.empty:
            chunks.append(filtered_chunk)

    if chunks:
        df_redfin = pd.concat(chunks, ignore_index=True)
        
        # Base columns we want to retain
        # Base columns we want to retain
        columns_to_keep = [
            'period_begin', 'period_end', 'city', 'state', 'state_code', 'property_type', 
            'median_sale_price', 'median_sale_price_yoy', 'homes_sold', 'homes_sold_yoy',
            'inventory', 'months_of_supply', 'median_dom', 'avg_sale_to_list',
            
            # --- ADD THESE FOR ADVANCED COMPETITION CHARTS ---
            'sold_above_list',        # % of homes that closed over asking price
            'price_drops',             # % of active listings that cut their price
            'off_market_in_two_weeks', # % of homes pending in under 14 days
            'median_days_to_close'     # Median days from contract to closing table
        ]
        
        # DEFENSIVE FIX 3: Keep only the columns that actually exist to prevent extraction errors
        available_cols = [col for col in columns_to_keep if col in df_redfin.columns]
        df_redfin = df_redfin[available_cols]
        
        redfin_output = {
            "last_compiled": master_timestamp,
            "records": df_redfin.to_dict(orient='records')
        }
        with open('data/redfin_stats.json', 'w') as f:
            json.dump(redfin_output, f, indent=2)
        print("Redfin data compiled successfully.")
    else:
        print("Warning: No Redfin data matched target criteria.")
        
except Exception as e:
    print(f"Critical error processing Redfin data: {e}")


# ==========================================
# 2. PROCESS INFOSPARKS PIPELINE
# ==========================================
print("Starting InfoSparks multi-feed pipeline...")
compiled_sparks_feeds = {}

if not os.path.exists(LINKS_CSV_PATH):
    print(f"Error: Link configuration file not found at {LINKS_CSV_PATH}")
else:
    try:
        # Read the file verbatim as uploaded
        df_links = pd.read_csv(LINKS_CSV_PATH)
        
        for idx, row in df_links.iterrows():
            group_num = str(row['Group']).strip()
            cities_desc = str(row['Cities']).strip()
            metric_desc = str(row['Metric']).strip()
            feed_url = str(row['CSV Link']).strip()
            
            if not feed_url.startswith("http"):
                print(f"Skipping row {idx}: Invalid URL format.")
                continue
                
            # Create a clean programmatic key for front-end JS mapping
            clean_key = f"group_{group_num}_{metric_desc}".lower()
            for char in [" ", "-", "/", "(", ")", ","]:
                clean_key = clean_key.replace(char, "_")
            while "__" in clean_key:
                clean_key = clean_key.replace("__", "_")
            clean_key = clean_key.strip("_")
            
            print(f"Fetching InfoSparks Live Feed: {clean_key}...")
            try:
                df_feed = pd.read_csv(feed_url)
                
                # Bundle data arrays alongside useful descriptive metadata
                compiled_sparks_feeds[clean_key] = {
                    "meta": {
                        "group": group_num,
                        "metric": metric_desc,
                        "geographies": [c.strip() for c in cities_desc.split(",")]
                    },
                    "data": df_feed.to_dict(orient='records')
                }
            except Exception as feederr:
                print(f"Error downloading feed from URL on row {idx}: {feederr}")
                
        # Consolidate all individual metric feeds into a single master payload
        infosparks_output = {
            "last_compiled": master_timestamp,
            "feeds": compiled_sparks_feeds
        }
        
        with open('data/infosparks_stats.json', 'w') as f:
            json.dump(infosparks_output, f, indent=2)
        print("InfoSparks master file generation complete.")
        
    except Exception as csverr:
        print(f"Critical error parsing InfoSparks configuration CSV: {csverr}")
