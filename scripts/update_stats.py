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
START_DATE = "2024-01-01"

REDFIN_COLUMNS = [
    "period_begin", "period_end", "city", "state", "state_code", "property_type",
    "median_sale_price", "median_sale_price_yoy", "median_dom", "avg_sale_to_list",
    "homes_sold", "homes_sold_yoy", "inventory", "months_of_supply",
    "sold_above_list", "price_drops", "off_market_in_two_weeks", "median_days_to_close"
]

def run_redfin_pipeline():
    print("Starting Redfin data pipeline...")
    try:
        req = urllib.request.Request(REDFIN_URL, headers={'User-Agent': 'Mozilla/5.0'})
        
        with urllib.request.urlopen(req) as response:
            chunks = pd.read_csv(response, compression="gzip", sep="\t", chunksize=50000, low_memory=False)
            filtered_chunks = []
            
            target_cities_lower = [c.lower() for c in TARGET_CITIES]
            printed_diagnostics = False
            
            for chunk in chunks:
                chunk.columns = chunk.columns.str.lower()
                
                # --- LIVE DEBUG DIAGNOSTICS ---
                # This prints a snapshot of Redfin's actual schema to your GitHub Actions logs
                if not printed_diagnostics:
                    print("\n--- DEBUG DIAGNOSTICS FOR FIRST CHUNK ---")
                    print("Columns found in file:", chunk.columns.tolist())
                    if 'state' in chunk.columns:
                        print("Sample 'state' values:", chunk['state'].dropna().unique()[:5].tolist())
                    if 'state_code' in chunk.columns:
                        print("Sample 'state_code' values:", chunk['state_code'].dropna().unique()[:5].tolist())
                    if 'city' in chunk.columns:
                        print("Sample 'city' values:", chunk['city'].dropna().unique()[:5].tolist())
                    if 'property_type' in chunk.columns:
                        print("Sample 'property_type' values:", chunk['property_type'].dropna().unique()[:5].tolist())
                    print("---------------------------------------\n")
                    printed_diagnostics = True
                
                # 1. Robust State Filter (Checks 'state' or 'state_code' columns for WA / Washington)
                state_mask = pd.Series(False, index=chunk.index)
                for col in ['state', 'state_code']:
                    if col in chunk.columns:
                        state_mask = state_mask | (chunk[col].astype(str).str.strip().str.upper().isin(["WA", "WASHINGTON"]))
                
                # 2. Robust Fuzzy City Filter (Checks if row contains any of our target names)
                city_mask = pd.Series(False, index=chunk.index)
                if 'city' in chunk.columns:
                    city_lower = chunk['city'].astype(str).str.lower()
                    for city in target_cities_lower:
                        city_mask = city_mask | (city_lower.str.contains(city, na=False))
                
                # 3. Robust Property Type Filter (Fuzzy matches keywords 'single family' or 'condo')
                prop_mask = pd.Series(False, index=chunk.index)
                if 'property_type' in chunk.columns:
                    prop_lower = chunk['property_type'].astype(str).str.lower()
                    prop_mask = prop_lower.str.contains("single family", na=False) | prop_lower.str.contains("condo", na=False)
                
                # 4. Robust Date Filter
                date_mask = pd.Series(True, index=chunk.index)
                if 'period_begin' in chunk.columns:
                    period_date = pd.to_datetime(chunk["period_begin"], errors='coerce')
                    date_mask = period_date >= pd.to_datetime(START_DATE)
                    
                # Combine masks dynamically
                mask = state_mask & city_mask & prop_mask & date_mask
                filtered_chunk = chunk[mask].copy()
                
                if not filtered_chunk.empty:
                    # Clean up city names to standard Title Case for uniform frontend display
                    if 'city' in filtered_chunk.columns:
                        for city in TARGET_CITIES:
                            filtered_chunk.loc[filtered_chunk['city'].astype(str).str.lower().str.contains(city.lower()), 'city'] = city
                    
                    # Standardize property type descriptions for your frontend mapping rules
                    if 'property_type' in filtered_chunk.columns:
                        filtered_chunk.loc[filtered_chunk['property_type'].astype(str).str.lower().str.contains("single family"), 'property_type'] = "Single Family Residential"
                        filtered_chunk.loc[filtered_chunk['property_type'].astype(str).str.lower().str.contains("condo"), 'property_type'] = "Condo/Co-op"
                    
                    existing_cols = [c for c in REDFIN_COLUMNS if c in filtered_chunk.columns]
                    filtered_chunks.append(filtered_chunk[existing_cols])
                    
            if filtered_chunks:
                master_df = pd.concat(filtered_chunks, ignore_index=True)
                master_df = master_df.sort_values(by=["city", "property_type", "period_begin"], ascending=[True, True, True])
                
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
        
        group_col = next((c for c in config_df.columns if "group" in c.lower()), None)
        cities_col = next((c for c in config_df.columns if "city" in c.lower() or "cities" in c.lower()), None)
        metric_col = next((c for c in config_df.columns if "metric" in c.lower()), None)
        link_col = next((c for c in config_df.columns if "link" in c.lower() or "url" in c.lower() or "csv" in c.lower()), None)

        master_feeds = {}

        for idx, row in config_df.iterrows():
            group_val = str(row[group_col]).strip() if group_col and pd.notna(row[group_col]) else f"{idx}"
            metric_val = str(row[metric_col]).strip() if metric_col and pd.notna(row[metric_col]) else "metric"
            cities_val = str(row[cities_col]).strip() if cities_col and pd.notna(row[cities_col]) else ""
            url = str(row[link_col]).strip() if link_col and pd.notna(row[link_col]) else ""
            
            if not url.startswith("http"):
                print(f"Skipping row {idx}: Invalid URL protocol.")
                continue

            clean_key = f"group_{group_val}_{metric_val}".lower()
            for char in [" ", "-", "/", "(", ")", ","]:
                clean_key = clean_key.replace(char, "_")
            while "__" in clean_key:
                clean_key = clean_key.replace("__", "_")
            clean_key = clean_key.strip("_")

            print(f"Fetching InfoSparks Live Feed: {clean_key}...")
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req) as response:
                    raw_text = response.read().decode('utf-8')
                
                lines = raw_text.strip().split('\n')
                header_idx = 0
                for line_num, line in enumerate(lines):
                    first_cell = line.split(',')[0].strip().strip('"').strip("'").lower()
                    if first_cell in ['month', 'date']:
                        header_idx = line_num
                        break
                
                clean_csv_text = '\n'.join(lines[header_idx:])
                df = pd.read_csv(io.StringIO(clean_csv_text))
                df.columns = [c.strip() for c in df.columns]
                
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
    run_infosparks_pipeline()            filtered_chunks = []
            
            # Lowercase targets for flexible, case-insensitive matching
            target_cities_lower = [c.lower() for c in TARGET_CITIES]
            target_props_lower = [p.lower() for p in TARGET_PROPERTY_TYPES]
            
            for chunk in chunks:
                chunk.columns = chunk.columns.str.lower()
                
                if "state_code" in chunk.columns and "state" not in chunk.columns:
                    chunk["state"] = chunk["state_code"]
                elif "state" in chunk.columns and "state_code" not in chunk.columns:
                    chunk["state_code"] = chunk["state"]
                    
                state_col = "state" if "state" in chunk.columns else "state_code"
                
                # Normalize values to isolate city names (e.g., "Kirkland, WA" -> "kirkland")
                city_clean = chunk["city"].astype(str).str.lower().str.split(',').str[0].str.strip()
                prop_clean = chunk["property_type"].astype(str).str.lower().str.strip()
                
                # Apply the flexible filter mask
                mask = (
                    (chunk[state_col].astype(str).str.upper() == "WA") &
                    (city_clean.isin(target_cities_lower)) &
                    (prop_clean.isin(target_props_lower)) &
                    (chunk["period_begin"] >= START_DATE)
                )
                filtered_chunk = chunk[mask].copy()
                
                if not filtered_chunk.empty:
                    # Clean up city names to standard Title Case for the frontend
                    filtered_chunk["city"] = filtered_chunk["city"].astype(str).str.split(',').str[0].str.strip().str.title()
                    
                    existing_cols = [c for c in REDFIN_COLUMNS if c in filtered_chunk.columns]
                    filtered_chunks.append(filtered_chunk[existing_cols])
                    
            if filtered_chunks:
                master_df = pd.concat(filtered_chunks, ignore_index=True)
                master_df = master_df.sort_values(by=["city", "property_type", "period_begin"], ascending=[True, True, True])
                
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
        
        group_col = next((c for c in config_df.columns if "group" in c.lower()), None)
        cities_col = next((c for c in config_df.columns if "city" in c.lower() or "cities" in c.lower()), None)
        metric_col = next((c for c in config_df.columns if "metric" in c.lower()), None)
        link_col = next((c for c in config_df.columns if "link" in c.lower() or "url" in c.lower() or "csv" in c.lower()), None)

        master_feeds = {}

        for idx, row in config_df.iterrows():
            group_val = str(row[group_col]).strip() if group_col and pd.notna(row[group_col]) else f"{idx}"
            metric_val = str(row[metric_col]).strip() if metric_col and pd.notna(row[metric_col]) else "metric"
            cities_val = str(row[cities_col]).strip() if cities_col and pd.notna(row[cities_col]) else ""
            url = str(row[link_col]).strip() if link_col and pd.notna(row[link_col]) else ""
            
            if not url.startswith("http"):
                print(f"Skipping row {idx}: Invalid URL protocol.")
                continue

            clean_key = f"group_{group_val}_{metric_val}".lower()
            for char in [" ", "-", "/", "(", ")", ","]:
                clean_key = clean_key.replace(char, "_")
            while "__" in clean_key:
                clean_key = clean_key.replace("__", "_")
            clean_key = clean_key.strip("_")

            print(f"Fetching InfoSparks Live Feed: {clean_key}...")
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req) as response:
                    raw_text = response.read().decode('utf-8')
                
                lines = raw_text.strip().split('\n')
                header_idx = 0
                for line_num, line in enumerate(lines):
                    first_cell = line.split(',')[0].strip().strip('"').strip("'").lower()
                    if first_cell in ['month', 'date']:
                        header_idx = line_num
                        break
                
                clean_csv_text = '\n'.join(lines[header_idx:])
                df = pd.read_csv(io.StringIO(clean_csv_text))
                df.columns = [c.strip() for c in df.columns]
                
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
