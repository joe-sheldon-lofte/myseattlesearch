import os
import time
import requests
import pandas as pd

# Navigate up two levels: /scripts/quarterly -> /scripts -> /repo_root
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUT_PATH = os.path.join(DATA_DIR, "king_county_raw.json")

def harvest_king_condos():
    print("Starting King County data pull...")
    os.makedirs(DATA_DIR, exist_ok=True)
    
    # Socrata API for King County Assessor Data
    base_url = "https://data.kingcounty.gov/resource/4zn9-h6cw.json"
    
    all_records = []
    limit = 2000
    offset = 0
    
    while True:
        query_url = f"{base_url}?$limit={limit}&$offset={offset}"
        print(f"   Fetching records {offset} to {offset + limit}...")
        
        response = requests.get(query_url)
        response.raise_for_status()
        
        data = response.json()
        
        if not data:
            break
            
        all_records.extend(data)
        offset += limit
        time.sleep(0.5)
        
    print(f"Successfully pulled {len(all_records)} King County records.")
    
    # Save the raw data directly to JSON
    df = pd.DataFrame(all_records)
    # orient='records' creates a standard JSON array of objects
    df.to_json(OUT_PATH, orient='records', indent=2)
    print(f"💾 Saved to {OUT_PATH}\n")

if __name__ == "__main__":
    harvest_king_condos()
