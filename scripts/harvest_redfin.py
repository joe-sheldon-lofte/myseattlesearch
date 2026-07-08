# File: scripts/harvest_redfin.py
import os
import json
import urllib.request
import pandas as pd

# Define Constants
REDFIN_CITY_URL = "https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_market_tracker/city_market_tracker.tsv000.gz"
REDFIN_METRO_URL = "https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_market_tracker/redfin_metro_market_tracker.tsv000.gz"

CITY_DATA_PATH = "data/city_data.json"
REDFIN_OUTPUT_PATH = "data/redfin_stats.json"

START_DATE = "2024-01-01"

REDFIN_COLUMNS = [
    "period_begin", "period_end", "region_type", "city", "state", "state_code", "property_type",
    "median_sale_price", "median_sale_price_yoy", "median_dom", "avg_sale_to_list",
    "homes_sold", "homes_sold_yoy", "inventory", "months_of_supply",
    "sold_above_list", "price_drops", "off_market_in_two_weeks", "market_friction_index"
]

def load_target_cities():
    fallback_cities = ["Shoreline", "Lake Forest Park", "Mountlake Terrace", "Lynnwood", "Mukilteo", "Brier", "Kenmore", "Kirkland", "Edmonds"]
    if not os.path.exists(CITY_DATA_PATH):
        return fallback_cities
    try:
        with open(CITY_DATA_PATH, 'r') as f:
            city_data = json.load(f)
        cities_list = [item['City'] for item in city_data if 'City' in item and item['City'].strip()]
        return cities_list if cities_list else fallback_cities
    except Exception as e:
        return fallback_cities

def run_redfin_pipeline(target_cities):
    print("Starting Dynamic Redfin data pipeline...")
    filtered_chunks = []
    target_cities_lower = [c.lower() for c in target_cities]
    
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

    try:
        print("Streaming Metro-Level Data for Seattle Metro...")
        req_metro = urllib.request.Request(REDFIN_METRO_URL, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req_metro) as response:
            chunks = pd.read_csv(response, compression="gzip", sep="\t", chunksize=50000, low_memory=False)
            for chunk in chunks:
                chunk.columns = chunk.columns.str.lower()
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
        os.makedirs(os.path.dirname(REDFIN_OUTPUT_PATH), exist_ok=True)
        with open(REDFIN_OUTPUT_PATH, "w") as f:
            json.dump(data_dict, f, indent=2)
        print(f"✅ Redfin regional database compiled successfully. Saved {len(data_dict)} rows.")
    else:
        print("Warning: No Redfin rows matched regional filtering constraints.")

if __name__ == "__main__":
    cities_to_track = load_target_cities()
    run_redfin_pipeline(cities_to_track)