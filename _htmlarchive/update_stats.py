import os
import json
import io
import urllib.request
from datetime import datetime
import pandas as pd

# Define Constants - Fixed Metro URL to match Redfin's exact S3 key schema
REDFIN_CITY_URL = "https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_market_tracker/city_market_tracker.tsv000.gz"
REDFIN_METRO_URL = "https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_market_tracker/redfin_metro_market_tracker.tsv000.gz"

INFOSPARKS_CONFIG_PATH = "data/InfoSparks Links - Sheet1.csv"
CITIES_CONFIG_PATH = "data/InfoSparks Links - Sheet2.csv"

REDFIN_OUTPUT_PATH = "data/redfin_stats.json"
INFOSPARKS_OUTPUT_PATH = "data/infosparks_stats.json"

TARGET_PROPERTY_TYPES = ["Single Family Residential", "Condo/Co-op"]
START_DATE = "2024-01-01"

REDFIN_COLUMNS = [
    "period_begin", "period_end", "region_type", "city", "state", "state_code", "property_type",
    "median_sale_price", "median_sale_price_yoy", "median_dom", "avg_sale_to_list",
    "homes_sold", "homes_sold_yoy", "inventory", "months_of_supply",
    "sold_above_list", "price_drops", "off_market_in_two_weeks", "market_friction_index"
]

def load_target_cities():
    """Dynamically loads the city expansion list from the Sheet2 config file"""
    fallback_cities = ["Shoreline", "Lake Forest Park", "Mountlake Terrace", "Lynnwood", "Mukilteo", "Brier", "Kenmore", "Kirkland", "Edmonds"]
    if not os.path.exists(CITIES_CONFIG_PATH):
        print(f"Config note: {CITIES_CONFIG_PATH} not found. Utilizing default core city array.")
        return fallback_cities
    try:
        df_cities = pd.read_csv(CITIES_CONFIG_PATH)
        city_col = next((c for c in df_cities.columns if "city" in c.lower()), None)
        if city_col:
            cities_list = df_cities[city_col].dropna().astype(str).str.strip().tolist()
            cities_list = [c for c in cities_list if c]
            print(f"Successfully loaded {len(cities_list)} target markets dynamically from Sheet2.")
            return cities_list
        else:
            print("Warning: 'City' column heading missing in Sheet2.csv. Utilizing default array.")
            return fallback_cities
    except Exception as e:
        print(f"Error reading city configuration file: {e}. Falling back to default array.")
        return fallback_cities

def run_redfin_pipeline(target_cities):
    print("Starting Dynamic Redfin data pipeline...")
    filtered_chunks = []
    target_cities_lower = [c.lower() for c in target_cities]
    
    # ==========================================
    # PHASE A: FETCH TARGET PUGET SOUND CITIES
    # ==========================================
    try:
        print(f"Streaming City-Level Data for {len(target_cities)} target markets...")
        req_city = urllib.request.Request(REDFIN_CITY_URL, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req_city) as response:
            chunks = pd.read_csv(response, compression="gzip", sep="\t", chunksize=50000, low_memory=False)
            
            for chunk in chunks:
                chunk.columns = chunk.columns.str.lower()
                
                if "state_code" in chunk.columns and "state" not in chunk.columns:
                    chunk["state"] = chunk["state_code"]
                state_col = "state" if "state" in chunk.columns else "state_code"
                
                state_mask = chunk[state_col].astype(str).str.strip().str.upper().isin(["WA", "WASHINGTON"])
                
                city_mask = pd.Series(False, index=chunk.index)
                if 'city' in chunk.columns:
                    city_lower = chunk['city'].astype(str).str.lower()
                    for city in target_cities_lower:
                        city_mask = city_mask | (city_lower.str.contains(city, na=False))
                
                prop_mask = pd.Series(False, index=chunk.index)
                if 'property_type' in chunk.columns:
                    prop_lower = chunk['property_type'].astype(str).str.lower()
                    prop_mask = prop_lower.str.contains("single family", na=False) | prop_lower.str.contains("condo", na=False)
                
                date_mask = pd.Series(True, index=chunk.index)
                if 'period_begin' in chunk.columns:
                    period_date = pd.to_datetime(chunk["period_begin"], errors='coerce')
                    date_mask = period_date >= pd.to_datetime(START_DATE)
                    
                mask = state_mask & city_mask & prop_mask & date_mask
                filtered_chunk = chunk[mask].copy()
                
                if not filtered_chunk.empty:
                    filtered_chunk["region_type"] = "city"
                    filtered_chunk["city"] = filtered_chunk["city"].astype(str).str.split(',').str[0].str.strip().str.title()
                    filtered_chunk.loc[filtered_chunk['property_type'].astype(str).str.lower().str.contains("single family"), 'property_type'] = "Single Family Residential"
                    filtered_chunk.loc[filtered_chunk['property_type'].astype(str).str.lower().str.contains("condo"), 'property_type'] = "Condo/Co-op"
                    
                    calc_cols = list(set(REDFIN_COLUMNS + ["off_market_in_two_weeks", "price_drops"]))
                    existing_cols = [c for c in calc_cols if c in filtered_chunk.columns]
                    filtered_chunks.append(filtered_chunk[existing_cols])
    except Exception as e:
        print(f"Error processing Redfin City segments: {e}")

    # ==========================================
    # PHASE B: FETCH SEATTLE METRO AREA
    # ==========================================
    try:
        print("Streaming Metro-Level Data for Seattle Metro...")
        req_metro = urllib.request.Request(REDFIN_METRO_URL, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req_metro) as response:
            chunks = pd.read_csv(response, compression="gzip", sep="\t", chunksize=50000, low_memory=False)
            
            for chunk in chunks:
                chunk.columns = chunk.columns.str.lower()
                
                # Redfin uses 'region' column in the metro tracker file layout
                if "region" in chunk.columns and "city" not in chunk.columns:
                    chunk["city"] = chunk["region"]
                if "state_code" in chunk.columns and "state" not in chunk.columns:
                    chunk["state"] = chunk["state_code"]
                
                prop_clean = chunk["property_type"].astype(str).str.lower().str.strip()
                mask = (
                    (chunk["city"].astype(str).str.lower().str.contains("seattle", na=False)) &
                    (chunk["state"].astype(str).str.upper() == "WA") &
                    (prop_clean.str.contains("single family", na=False) | prop_clean.str.contains("condo", na=False)) &
                    (chunk["period_begin"] >= START_DATE)
                )
                filtered_chunk = chunk[mask].copy()
                
                if not filtered_chunk.empty:
                    filtered_chunk["region_type"] = "metro"
                    filtered_chunk["city"] = "Seattle Metro"
                    filtered_chunk.loc[filtered_chunk['property_type'].astype(str).str.lower().str.contains("single family"), 'property_type'] = "Single Family Residential"
                    filtered_chunk.loc[filtered_chunk['property_type'].astype(str).str.lower().str.contains("condo"), 'property_type'] = "Condo/Co-op"
                    
                    calc_cols = list(set(REDFIN_COLUMNS + ["off_market_in_two_weeks", "price_drops"]))
                    existing_cols = [c for c in calc_cols if c in filtered_chunk.columns]
                    filtered_chunks.append(filtered_chunk[existing_cols])
    except Exception as e:
        print(f"Error processing Redfin Metro segments: {e}")

    # ==========================================
    # PHASE C: CONSOLIDATE, CALCULATE & WRITE
    # ==========================================
    if filtered_chunks:
        master_df = pd.concat(filtered_chunks, ignore_index=True)
        
        off_mkt = pd.to_numeric(master_df["off_market_in_two_weeks"], errors='coerce').fillna(0)
        drops = pd.to_numeric(master_df["price_drops"], errors='coerce').fillna(0)
        
        master_df["market_friction_index"] = (off_mkt / (drops + 0.02)) * 10
        master_df["market_friction_index"] = master_df["market_friction_index"].clip(0, 100).round(0).astype(int)
        
        final_cols = [c for c in REDFIN_COLUMNS if c in master_df.columns]
        master_df = master_df[final_cols]
        
        master_df = master_df.sort_values(by=["region_type", "city", "property_type", "period_begin"], ascending=[True, True, True, True])
        
        data_dict = master_df.to_dict(orient="records")
        with open(REDFIN_OUTPUT_PATH, "w") as f:
            json.dump(data_dict, f, indent=2)
        print(f"Redfin regional database compiled successfully with Custom Index. Saved {len(data_dict)} rows.")
    else:
        print("Warning: No Redfin rows matched regional filtering constraints.")

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
    cities_to_track = load_target_cities()
    run_redfin_pipeline(cities_to_track)
    print("-" * 40)
    run_infosparks_pipeline()
