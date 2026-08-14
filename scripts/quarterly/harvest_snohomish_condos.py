import os
import time
import requests
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUT_PATH = os.path.join(DATA_DIR, "snohomish_county_raw.json")

def harvest_snohomish_condos():
    print("Starting Snohomish County data pull...")
    os.makedirs(DATA_DIR, exist_ok=True)
    
    base_url = "https://services6.arcgis.com/z6WYi9VRHfgwgtyW/arcgis/rest/services/Parcels/FeatureServer/0/query"
    
    all_features = []
    limit = 2000
    offset = 0
    
    while True:
        # We only search columns we know exist in their schema
        sql_query = "UPPER(USECODE) LIKE '%CONDO%' OR UPPER(TAXPRNAME) LIKE '%CONDO%' OR UPPER(OWNERNAME) LIKE '%CONDO%'"
        
        params = {
            'where': sql_query,
            'outFields': '*', 
            'outSR': '4326', # Request standard GPS coordinates
            'f': 'json',
            'resultOffset': offset,
            'resultRecordCount': limit
        }
        
        print(f"   Fetching records {offset} to {offset + limit}...")
        response = requests.get(base_url, params=params)
        response.raise_for_status()
        
        data = response.json()
        features = data.get('features', [])
        
        if not features:
            break
            
        for feature in features:
            attr = feature.get('attributes', {})
            geom = feature.get('geometry', {})
            
            # ArcGIS wraps the GPS coordinates in a separate geometry dictionary, so we flatten it
            if 'x' in geom and 'y' in geom:
                attr['longitude'] = geom['x']
                attr['latitude'] = geom['y']
                
            all_features.append(attr)
            
        if not data.get('exceededTransferLimit', False):
            break
            
        offset += limit
        time.sleep(0.5)

    print(f"Successfully pulled {len(all_features)} Snohomish County records.")
    
    df = pd.DataFrame(all_features)
    df.to_json(OUT_PATH, orient='records', indent=2)
    print(f"💾 Saved to {OUT_PATH}\n")

if __name__ == "__main__":
    harvest_snohomish_condos()