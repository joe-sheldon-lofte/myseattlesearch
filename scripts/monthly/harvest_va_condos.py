import os
import json
import time
import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUT_PATH = os.path.join(DATA_DIR, "va_condos_raw.json")

def harvest_va_condos():
    print("🚀 Starting VA Condo Harvester...")
    os.makedirs(DATA_DIR, exist_ok=True)
    
    session = requests.Session()
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.5.2 Safari/605.1.15',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://lgy.va.gov/',
    }
    
    # 1. Establish initial session
    print("📡 Establishing session with VA LGY portal...")
    try:
        session.get('https://lgy.va.gov/', headers=headers, timeout=10)
    except Exception as e:
        print(f"⚠️ Initial session request failed: {e}")

    counties = ['King', 'Snohomish']
    all_va_condos = []
    
    for county in counties:
        print(f"Fetching VA data for {county} County...")
        
        params = {
            'approved': 'true', # Pull approved records
            'city': '',
            'condoId': '',
            'condoName': '',
            'county': county,
            'stateCode': 'WA',
            'station': '',
        }
        
        try:
            res = session.get('https://lgy.va.gov/lgyhub/api/condos/search', params=params, headers=headers, timeout=15)
            res.raise_for_status()
            
            data = res.json()
            # If the response is a list or wrapped in an object
            records = data if isinstance(data, list) else data.get('content', data.get('results', []))
            
            print(f"   Received {len(records)} VA records for {county} County.")
            for rec in records:
                if isinstance(rec, dict):
                    rec['source_county'] = county
                    all_va_condos.append(rec)
                    
        except Exception as e:
            print(f"❌ Error fetching VA data for {county}: {e}")
            
        time.sleep(1)

    print(f"\nSuccessfully harvested {len(all_va_condos)} total VA records.")
    
    with open(OUT_PATH, 'w') as f:
        json.dump(all_va_condos, f, indent=2)
        
    print(f"💾 Saved to {OUT_PATH}\n")

if __name__ == "__main__":
    harvest_va_condos()