# File: scripts/harvest_professionals.py
import os
import io
import json
import math
import requests
import pandas as pd

def scrub_nan_tokens(data_node):
    """
    Recursively tracks and converts standalone float NaN tokens into 
    valid JSON null definitions, eliminating downstream parsing crashes.
    """
    if isinstance(data_node, dict):
        return {key: scrub_nan_tokens(val) for key, val in data_node.items()}
    elif isinstance(data_node, list):
        return [scrub_nan_tokens(element) for element in data_node]
    elif isinstance(data_node, float) and math.isnan(data_node):
        return None
    return data_node

def harvest_professionals_pipeline():
    # Dedicated published Google Sheets CSV stream coordinate
    TARGET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSntu7panLCFdXqZNXaJTHezzjKzajniQDJGopLfGJnIKgGEd773sQ0zfm0q8qEnnBzZDBzEjUd0ZAN/pub?gid=0&single=true&output=csv"
    OUTPUT_FILE_PATH = "data/professionals.json"
    
    print("📡 Initializing handshake with Preferred Professionals spreadsheet node...")
    
    try:
        # Request stream over HTTP with an isolated timeout threshold
        response = requests.get(TARGET_CSV_URL, timeout=20)
        response.raise_for_status()
        
        # Ingest the clean string byte response directly into a Pandas dataframe layout
        dataframe = pd.read_csv(io.StringIO(response.text))
        print("📥 Live data collection retrieved successfully from cloud workbook stream.")
        
    except Exception as connection_fault:
        print(f"❌ Pipeline Failure: Unable to fetch live vendor data: {connection_fault}")
        return

    # Filter out empty or unpopulated rows from the dataset
    dataframe = dataframe.dropna(subset=['Business/Vendor Name'])
    
    # Strip any trailing whitespaces from the column headers
    dataframe.columns = [col.strip() for col in dataframe.columns]
    
    # Unroll the dataframe into a standard flat Python list of records
    raw_records = dataframe.to_dict(orient='records')
    
    # Run the dataset through our NaN scrubbing sequence
    sanitized_records = scrub_nan_tokens(raw_records)
    
    # Guarantee target destination folder exists before writing
    os.makedirs(os.path.dirname(OUTPUT_FILE_PATH), exist_ok=True)
    
    # Write the clean data asset to disk
    with open(OUTPUT_FILE_PATH, 'w', encoding='utf-8') as output_sink:
        json.dump(sanitized_records, output_sink, indent=2, ensure_ascii=False)
        
    print(f"💾 Data pipeline complete. Exported {len(sanitized_records)} clean records to: {OUTPUT_FILE_PATH}")

if __name__ == "__main__":
    harvest_professionals_pipeline()