# File: scripts/harvest_redfin.py

import os
import json
import time
import math
import requests
import io
import pandas as pd

CITY_DATA_PATH = "data/city_data.json"
REDFIN_OUTPUT_PATH = "data/redfin_stats.json"

ROLLING_MONTHS = 13  # Retains 13 rolling months for 1-year trends + YoY context

REDFIN_COLUMNS = [
    "period_begin", "period_end", "region_type", "city", "state", "state_code", "property_type",
    "median_sale_price", "median_sale_price_yoy", "median_dom", "avg_sale_to_list",
    "homes_sold", "homes_sold_yoy", "inventory", "months_of_supply",
    "sold_above_list", "price_drops", "off_market_in_two_weeks", "market_friction_index"
]

def get_rolling_start_date():
    """
    Calculates dynamic start date offset relative to current run execution date.
    """
    today = pd.Timestamp.now()
    return (today - pd.DateOffset(months=ROLLING_MONTHS)).replace(day=1)

def clean_nan_tokens(node):
    """
    Recursively purges Python float NaN and inf tokens into standard JSON null parameters.
    """
    if isinstance(node, dict):
        return {k: clean_nan_tokens(v) for k, v in node.items()}
    elif isinstance(node, list):
        return [clean_nan_tokens(element) for element in node]
    elif isinstance(node, float) and (math.isnan(node) or math.isinf(node)):
        return None
    return node

def load_target_cities():
    """
    Reads active target cities from city_data.json or falls back to core North Sound defaults.
    """
    fallback_cities = ["Shoreline", "Lake Forest Park", "Mountlake Terrace", "Lynnwood", "Mukilteo", "Brier", "Kenmore", "Kirkland", "Edmonds"]
    if not os.path.exists(CITY_DATA_PATH):
        return fallback_cities
    try:
        with open(CITY_DATA_PATH, 'r', encoding='utf-8') as f:
            city_data = json.load(f)
        cities_list = [item['City'] for item in city_data if isinstance(item, dict) and 'City' in item and str(item['City']).strip()]
        return cities_list if cities_list else fallback_cities
    except Exception as e:
        print(f"⚠️ Warning: Could not read target cities from {CITY_DATA_PATH}: {e}")
        return fallback_cities

def fetch_s3_partitions(base_url_pattern, dataset_label):
    """
    Fetches sequential AWS S3 partition parts (tsv000.gz, tsv001.gz, etc.) or fallback .tsv.gz with cache-busting headers.
    """
    partition_index = 0
    all_chunks = []
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
        'Expires': '0'
    }

    while True:
        part_str = f"tsv{partition_index:03d}.gz"
        timestamp = int(time.time())
        url = f"{base_url_pattern}.{part_str}?t={timestamp}"
        print(f"   📥 Requesting {dataset_label} partition [{part_str}]...")

        try:
            res = requests.get(url, headers=headers, timeout=60, stream=True)
            if res.status_code == 200:
                print(f"   ✅ Downloaded {part_str} ({len(res.content)} bytes). Parsing tab-separated stream...")
                chunks = pd.read_csv(io.BytesIO(res.content), compression="gzip", sep="\t", chunksize=50000, low_memory=False)
                all_chunks.append(chunks)
                partition_index += 1
            else:
                if partition_index == 0:
                    # Fallback check for unpartitioned .tsv.gz naming format
                    fallback_url = f"{base_url_pattern}.tsv.gz?t={timestamp}"
                    print(f"   ℹ️ {part_str} returned HTTP {res.status_code}. Trying fallback: {fallback_url}...")
                    fb_res = requests.get(fallback_url, headers=headers, timeout=60, stream=True)
                    if fb_res.status_code == 200:
                        print(f"   ✅ Downloaded fallback .tsv.gz ({len(fb_res.content)} bytes). Parsing stream...")
                        chunks = pd.read_csv(io.BytesIO(fb_res.content), compression="gzip", sep="\t", chunksize=50000, low_memory=False)
                        all_chunks.append(chunks)
                else:
                    print(f"   ℹ️ Reached end of partition sequence at index {partition_index}.")
                break
        except Exception as err:
            print(f"   ⚠️ Partition scan halted on {part_str}: {err}")
            break

    return all_chunks

def run_redfin_pipeline(target_cities):
    print("📡 Starting Multi-Partition Rolling Redfin Market Harvester Pipeline...")
    rolling_start = get_rolling_start_date()
    print(f"📅 Target Rolling Timeframe Cutoff: {rolling_start.strftime('%Y-%m-%d')}")

    filtered_chunks = []
    target_cities_lower = [c.lower().strip() for c in target_cities]

    # ==========================================
    # STEP 1: CITY-LEVEL DATASET INGESTION
    # ==========================================
    city_base_url = "https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_market_tracker/city_market_tracker"
    city_partition_chunks = fetch_s3_partitions(city_base_url, "City")

    for chunk_stream in city_partition_chunks:
        for chunk in chunk_stream:
            chunk.columns = chunk.columns.str.lower()
            if "state_code" in chunk.columns and "state" not in chunk.columns:
                chunk["state"] = chunk["state_code"]
            
            state_col = "state" if "state" in chunk.columns else "state_code"
            state_mask = chunk[state_col].astype(str).str.strip().str.upper().isin(["WA", "WASHINGTON"])

            city_mask = pd.Series(False, index=chunk.index)
            if 'city' in chunk.columns:
                city_lower = chunk['city'].astype(str).str.lower()
                for city in target_cities_lower:
                    city_mask = city_mask | (city_lower == city) | (city_lower.str.startswith(f"{city},"))

            prop_mask = pd.Series(False, index=chunk.index)
            if 'property_type' in chunk.columns:
                prop_lower = chunk['property_type'].astype(str).str.lower()
                prop_mask = prop_lower.str.contains("single family", na=False) | prop_lower.str.contains("condo", na=False)

            date_mask = pd.Series(False, index=chunk.index)
            if 'period_begin' in chunk.columns:
                period_dt = pd.to_datetime(chunk['period_begin'], errors='coerce')
                date_mask = period_dt >= rolling_start

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

    # ==========================================
    # STEP 2: METRO-LEVEL DATASET INGESTION
    # ==========================================
    metro_base_url = "https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_market_tracker/redfin_metro_market_tracker"
    metro_partition_chunks = fetch_s3_partitions(metro_base_url, "Metro")

    for chunk_stream in metro_partition_chunks:
        for chunk in chunk_stream:
            chunk.columns = chunk.columns.str.lower()
            if "region" in chunk.columns and "city" not in chunk.columns:
                chunk["city"] = chunk["region"]
            if "state_code" in chunk.columns and "state" not in chunk.columns:
                chunk["state"] = chunk["state_code"]

            prop_clean = chunk["property_type"].astype(str).str.lower().str.strip()
            period_dt = pd.to_datetime(chunk["period_begin"], errors='coerce')

            mask = (
                (chunk["city"].astype(str).str.lower().str.contains("seattle", na=False)) &
                (chunk["state"].astype(str).str.upper().isin(["WA", "WASHINGTON"])) &
                (prop_clean.str.contains("single family", na=False) | prop_clean.str.contains("condo", na=False)) &
                (period_dt >= rolling_start)
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

    # ==========================================
    # STEP 3: CONSOLIDATION & METRIC CALCULATION
    # ==========================================
    if filtered_chunks:
        master_df = pd.concat(filtered_chunks, ignore_index=True)
        master_df = master_df.drop_duplicates(subset=["region_type", "city", "property_type", "period_begin"])

        off_mkt = pd.to_numeric(master_df["off_market_in_two_weeks"], errors='coerce').fillna(0)
        drops = pd.to_numeric(master_df["price_drops"], errors='coerce').fillna(0)

        master_df["market_friction_index"] = (off_mkt / (drops + 0.02)) * 10
        master_df["market_friction_index"] = master_df["market_friction_index"].clip(0, 100).round(0).astype(int)

        final_cols = [c for c in REDFIN_COLUMNS if c in master_df.columns]
        master_df = master_df[final_cols]
        master_df = master_df.sort_values(by=["region_type", "city", "property_type", "period_begin"], ascending=[True, True, True, True])

        records = master_df.to_dict(orient="records")
        cleaned_records = clean_nan_tokens(records)

        os.makedirs(os.path.dirname(REDFIN_OUTPUT_PATH), exist_ok=True)
        with open(REDFIN_OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(cleaned_records, f, indent=2, ensure_ascii=False)

        print(f"✅ Redfin master database successfully updated! Saved {len(cleaned_records)} records to {REDFIN_OUTPUT_PATH}.")
    else:
        print("⚠️ Warning: No Redfin rows matched regional filtering constraints.")

if __name__ == "__main__":
    cities_to_track = load_target_cities()
    run_redfin_pipeline(cities_to_track)