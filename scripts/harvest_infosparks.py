# File: scripts/harvest_infosparks.py
import pandas as pd
import json
import os
import io
import urllib.request
from datetime import datetime

# ==========================================
# CONFIGURATION
# ==========================================
INFOSPARKS_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRJ4hZJC9sUesHsGz6ixvm6_nQUFD9FaOGxAr3Dy5g3teqtUuDzJrjT31Vl5mQn2jGi9L8qe90hZ_7P/pub?gid=0&single=true&output=csv"

OUTPUT_FILE = "data/infosparks_stats.json"

def harvest_infosparks():
    print("Starting InfoSparks Live Feed Pipeline...")
    try:
        config_df = pd.read_csv(INFOSPARKS_CSV_URL)
        
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
                continue

            clean_key = f"group_{group_val}_{metric_val}".lower()
            for char in [" ", "-", "/", "(", ")", ","]:
                clean_key = clean_key.replace(char, "_")
            while "__" in clean_key:
                clean_key = clean_key.replace("__", "_")
            clean_key = clean_key.strip("_")

            print(f"Fetching MLS Feed: {clean_key}...")
            
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
        
        os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
        with open(OUTPUT_FILE, "w") as f:
            json.dump(output_payload, f, indent=4)
            
        print("✅ InfoSparks master file generation complete!")
        
    except Exception as e:
        print(f"❌ Critical error in InfoSparks pipeline: {e}")
        exit(1)

if __name__ == "__main__":
    harvest_infosparks()