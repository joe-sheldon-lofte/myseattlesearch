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
    
    # Correct Assessor Property Roll Socrata Dataset (4854-i48r)
    base_url = "https://data.kingcounty.gov/resource/4854-i48r.json"
    
    all_records = []
    limit = 5000 # Socrata allows larger batches
    offset = 0
    
    while True:
        params = {
            "$limit": limit,
            "$offset": offset,
            # Query the legal description for condominiums natively on the server
            "$where": "upper(legal_description) like '%CONDOMINIUM%'"
        }
        
        print(f"   Fetching records {offset} to {offset + limit}...")
        
        response = requests.get(base_url, params=params)
        response.raise_for_status()
        
        data = response.json()
        
        if not data or len(data) == 0:
            break
            
        all_records.extend(data)
        
        # If we got fewer records than the limit, we've hit the end
        if len(data) < limit:
            break
            
        offset += limit
        time.sleep(0.5)
        
    print(f"Successfully pulled {len(all_records)} King County condo records.")
    
    # Save the raw data directly to JSON
    df = pd.DataFrame(all_records)
    df.to_json(OUT_PATH, orient='records', indent=2)
    print(f"💾 Saved to {OUT_PATH}\n")

if __name__ == "__main__":
    harvest_king_condos()