import os
import json
import io
import urllib.request
from datetime import datetime
import pandas as pd

# Define Constants
REDFIN_URL = "https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_market_tracker/city_market_tracker.tsv000.gz"
INFOSPARKS_CONFIG_PATH = "data/InfoSparks Links - Sheet1.csv"
REDFIN_OUTPUT_PATH = "data/redfin_stats.json"
INFOSPARKS_OUTPUT_PATH = "data/infosparks_stats.json"

TARGET_CITIES = [
    "Shoreline", "Lake Forest Park", "Mountlake Terrace", "Lynnwood", 
    "Mukilteo", "Brier", "Kenmore", "Kirkland", "Edmonds"
]

TARGET_PROPERTY_TYPES = ["Single Family Residential", "Condo/Co-op"]

REDFIN_COLUMNS = [
    "period_begin", "period_end", "city", "state", "state_code", "property_type",
    "median_sale_price", "median_sale_price_yoy", "median_dom", "avg_sale_to_list",
    "homes_sold", "homes_sold_yoy", "inventory", "months_of_supply",
    "sold_above_list", "price_drops", "off_market_in_two_weeks", "median_days_to_close"
]

def run_redfin_pipeline():
    print("Starting Redfin data pipeline...")
    try:
        # Add a custom User-Agent header to bypass AWS S3 restrictions safely
        req = urllib.request.Request(REDFIN_URL, headers={'User-Agent': 'Mozilla/5.0'})
        
        with urllib.request.urlopen(req) as response:
            # Stream the massive file in chunks to prevent GitHub Actions out-of-memory crashes
            chunks = pd.read_csv(response, compression="gzip", sep="\t", chunksize=50000, low_memory=False)
            filtered_chunks = []
            
            for chunk in chunks:
                # Force lowercase column names defensively to prevent matching updates
                chunk.columns = chunk.columns.str.lower()
                
                # Standardize state column naming defensively
                if "state_code" in chunk.columns and "state" not in chunk.columns:
                    chunk["state"] = chunk["state_code"]
                elif "state" in chunk.columns and "state_code" not in chunk.columns:
                    chunk["state_code"] = chunk["state"]
                    
                state_col = "state" if "state" in chunk.columns else "state_code"
                
                # Filter rows aggressively on the fly
                mask = (
                    (chunk[state_col].astype(str).str.upper() == "WA") &
                    (chunk["city"].isin(TARGET_CITIES)) &
                    (chunk["property_type"].isin(TARGET_PROPERTY_TYPES))
                )
                filtered_chunk = chunk[mask]
                
                if not filtered_chunk.empty:
                    # Keep only your updated columns list
                    existing_cols = [c for c in REDFIN_COLUMNS if c in filtered_chunk.columns]
                    filtered_chunks.append(filtered_chunk[existing_cols])
                    
            if filtered_chunks:
                master_df = pd.concat(filtered_chunks, ignore_index=True)
                
                # Sort chronologically and by city
                master_df = master_df.sort_values(by=["city", "property_type", "period_begin"], ascending=[True, True, True])
                
                # Convert to dictionary and save
                data_dict = master_df.to_dict(orient="records")
                with open(REDFIN_OUTPUT_PATH, "w") as f:
                    json.dump(data_dict, f, indent=2)
                print(f"Redfin data compiled successfully. Saved {len(data_dict)} rows.")
            else:
                print("Warning: No matching Redfin records found during filtering.")
            
    except Exception as e:
        print(f"Critical error in Redfin pipeline: {e}")

def run_infosparks_pipeline():
    print("Starting InfoSparks multi-feed pipeline...")
    if not os.path.exists(INFOSPARKS_CONFIG_PATH):
        print(f"Error: Configuration file missing at {INFOSPARKS_CONFIG_PATH}")
        return

    try:
        config_df = pd.read_csv(INFOSPARKS_CONFIG_PATH)
        
        # Dynamically map custom columns from your Sheet1 layout
        group_col = next((c for c in config_df.columns if "group" in c.lower()), None)
        cities_col = next((c for c in config_df.columns if "city" in c.lower() or "cities" in c.lower()), None)
        metric_col = next((c for c in config_df.columns if "metric" in c.lower()), None)
        link_col = next((c for c in config_df.columns if "link" in c.lower() or "url" in c.lower() or "csv" in c.lower()), None)

        master_feeds = {}

        for idx, row in config_df.iterrows():
            # Standardized string treatment (.strip() applied correctly)
            group_val = str(row[group_col]).strip() if group_col and pd.notna(row[group_col]) else f"{idx}"
            metric_val = str(row[metric_col]).strip() if metric_col and pd.notna(row[metric_col]) else "metric"
            cities_val = str(row[cities_col]).strip() if cities_col and pd.notna(row[cities_col]) else ""
            url = str(row[link_col]).strip() if link_col and pd.notna(row[link_col]) else ""
            
            if not url.startswith("http"):
                print(f"Skipping row {idx}: Invalid URL protocol.")
                continue

            # Generate a programmatic alphanumeric key layout for JavaScript
            clean_key = f"group_{group_val}_{metric_val}".lower()
            for char in [" ", "-", "/", "(", ")", ","]:
                clean_key = clean_key.replace(char, "_")
            while "__" in clean_key:
                clean_key = clean_key.replace("__", "_")
            clean_key = clean_key.strip("_")

            print(f"Fetching InfoSparks Live Feed: {clean_key}...")
            try:
                # 1. Download raw layout text securely using browser headers
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req) as response:
                    raw_text = response.read().decode('utf-8')
                
                # 2. Break data down line-by-line to find the true table header row
                lines = raw_text.strip().split('\n')
                header_idx = 0
                for line_num, line in enumerate(lines):
                    first_cell = line.split(',')[0].strip().strip('"').strip("'").lower()
                    if first_cell in ['month', 'date']:
                        header_idx = line_num
                        break
                
                # 3. Strip metadata header blocks out and load tables cleanly
                clean_csv_text = '\n'.join(lines[header_idx:])
                df = pd.read_csv(io.StringIO(clean_csv_text))
                
                # 4. Strip white spaces off metadata column names
                df.columns = [c.strip() for c in df.columns]
                
                # 5. Format payload structural layout mirroring the Handoff Specifications
                master_feeds[clean_key] = {
                    "meta": {
                        "group": group_val,
                        "metric": metric_val,
                        "geographies": [c.strip() for c in cities_val.split(",")]
                    },
                    "data": df.to_dict(orient="records")
                }
                
            except Exception as e:
                print(f"Error downloading feed from URL on row {idx}: {e}")

        # Package compiled tables with an audit timestamp
        output_payload = {
            "last_compiled": datetime.utcnow().isoformat() + "Z",
            "feeds": master_feeds
        }

        with open(INFOSPARKS_OUTPUT_PATH, "w") as f:
            json.dump(output_payload, f, indent=2)
        print("InfoSparks master file generation complete.")

    except Exception as e:
        print(f"Critical error in InfoSparks pipeline: {e}")

if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    
    run_redfin_pipeline()
    print("-" * 40)
    run_infosparks_pipeline()
