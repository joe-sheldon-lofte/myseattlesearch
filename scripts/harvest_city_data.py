# File: scripts/harvest_city_data.py
import pandas as pd
import json
import os

# ==========================================
# CONFIGURATION
# ==========================================
CITY_DATA_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRJ4hZJC9sUesHsGz6ixvm6_nQUFD9FaOGxAr3Dy5g3teqtUuDzJrjT31Vl5mQn2jGi9L8qe90hZ_7P/pub?gid=1615447090&single=true&output=csv"

OUTPUT_FILE = "data/city_data.json"

def harvest_city_data():
    print("Fetching City Data from Google Sheets...")
    try:
        df = pd.read_csv(CITY_DATA_CSV_URL)
        df = df.loc[:, ~df.columns.duplicated()]
        
        if 'City' in df.columns:
            df = df.dropna(subset=['City'])
        
        df = df.fillna("")
        records = df.to_dict(orient='records')
        
        os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
        
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(records, f, indent=4)
            
        print(f"✅ Successfully harvested and saved {len(records)} cities to {OUTPUT_FILE}")
        
    except Exception as e:
        print(f"❌ Error harvesting city data: {e}")
        exit(1)

if __name__ == "__main__":
    harvest_city_data()