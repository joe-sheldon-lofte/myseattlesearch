import os
import json
import io
import urllib.request
import pandas as pd

# Down Payment Assistance Configuration
# Change this GID once you create your DPA tab in your master Google Sheet.
DPA_TAB_GID = "345179894"
DPA_CSV_URL = f"https://docs.google.com/spreadsheets/d/e/2PACX-1vQyiu3qLYVO9khl6k5s_whzg_UZFzKu7-RHc5fa2tpe3aIlf4wm4IaqQeVd75enhpJvS_lxXgfQRfQ_/pub?gid={DPA_TAB_GID}&single=true&output=csv"
DPA_OUTPUT_PATH = "data/dpa_programs.json"

def run_dpa_pipeline():
    print("Starting independent Down Payment Assistance data harvesting...")
    if "CHANGE_ME" in DPA_TAB_GID:
        print("Pipeline note: GID placeholder active. Please update DPA_TAB_GID with your Google Sheet tab value.")
        return
    try:
        req = urllib.request.Request(DPA_CSV_URL, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            raw_data = response.read().decode('utf-8')
            
        df_dpa = pd.read_csv(io.StringIO(raw_data))
        
        # Clean white spaces from column headers naturally
        df_dpa.columns = [c.strip() for c in df_dpa.columns]
        data_dict = df_dpa.to_dict(orient="records")
        
        # Write clean read-only JSON pool into data folder
        with open(DPA_OUTPUT_PATH, "w") as f:
            json.dump(data_dict, f, indent=2)
            
        print(f"Success! Compiled {len(data_dict)} assistance programs into {DPA_OUTPUT_PATH}")
    except Exception as e:
        print(f"Failure compiling DPA spreadsheet: {e}")

if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    run_dpa_pipeline()