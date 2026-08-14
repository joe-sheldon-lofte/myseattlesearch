import os
import json
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUT_PATH = os.path.join(DATA_DIR, "king_county_raw.json")

def create_retry_session():
    """Creates a requests session that auto-retries transient network/server drops."""
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=2,  # Waits 2s, 4s, 8s, 16s, 32s between retries
        status_forcelist=[500, 502, 503, 504],
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

def harvest_king_condos():
    print("🚀 Starting King County Condo Data Harvester (ResILient Pull)...")
    os.makedirs(DATA_DIR, exist_ok=True)
    
    base_url = "https://data.kingcounty.gov/resource/4854-i48r.json"
    session = create_retry_session()
    
    all_records = []
    offset = 0
    limit = 1000  # Smaller batch size avoids Socrata backend query timeouts
    
    while True:
        params = {
            "$limit": str(limit),
            "$offset": str(offset),
            "$where": "upper(legal_description) like '%CONDOMINIUM%'"
        }
        
        print(f"   Fetching records {offset} to {offset + limit}...")
        
        try:
            # timeout=(connect_timeout, read_timeout) prevents hanging jobs
            response = session.get(base_url, params=params, timeout=(10, 60))
            response.raise_for_status()
            
            data = response.json()
            if not data or len(data) == 0:
                break
                
            all_records.extend(data)
            
            if len(data) < limit:
                break
                
            offset += limit
            
        except Exception as e:
            print(f"❌ Failed to fetch batch at offset {offset}: {e}")
            raise e  # Re-raise so safe_task and Sentry catch the exception

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(all_records, f, indent=2, ensure_ascii=False)

    print(f"💾 Successfully harvested {len(all_records)} King County condo records to {OUT_PATH}\n")

if __name__ == "__main__":
    harvest_king_condos()