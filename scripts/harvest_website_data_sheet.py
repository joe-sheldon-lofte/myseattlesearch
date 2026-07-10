# File: scripts/harvest_website_data_sheet.py
import os
import io
import json
import math
import requests
import pandas as pd

def clean_nan_values(data_node):
    """
    Recursively scrubs data objects to replace standalone float NaN parameters 
    with clean standard JSON null representations, preventing compiler breaks.
    """
    if isinstance(data_node, dict):
        return {key: clean_nan_values(val) for key, val in data_node.items()}
    elif isinstance(data_node, list):
        return [clean_nan_values(element) for element in data_node]
    elif isinstance(data_node, float) and math.isnan(data_node):
        return None
    return data_node

def harvest_workbook_pipeline():
    # Absolute master spreadsheet connection string
    SOURCE_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQyiu3qLYVO9khl6k5s_whzg_UZFzKu7-RHc5fa2tpe3aIlf4wm4IaqQeVd75enhpJvS_lxXgfQRfQ_/pub?output=csv"
    
    # Coerce the URL query parameter to download the full multi-tab workbook
    xlsx_target_url = SOURCE_URL.replace("output=csv", "output=xlsx")
    
    print("📡 Handshaking with Google Sheet workbook node...")
    
    try:
        response = requests.get(xlsx_target_url, timeout=30)
        response.raise_for_status()
        workbook_bytes = io.BytesIO(response.content)
    except Exception as network_error:
        print(f"❌ Connection failure during spreadsheet fetch pass: {network_error}")
        return

    # Enforce standard read-only data directory constraints
    output_directory = "data"
    os.makedirs(output_directory, exist_ok=True)
    
    try:
        excel_file_wrapper = pd.ExcelFile(workbook_bytes)
        print(f"📋 Workbook loaded successfully. Tabs discovered: {excel_file_wrapper.sheet_names}")
        
        for sheet_name in excel_file_wrapper.sheet_names:
            # Load individual sheet frames into pandas datasets
            dataframe = pd.read_excel(excel_file_wrapper, sheet_name=sheet_name)
            
            # Standardize structural target filenames
            target_file_name = f"{sheet_name.lower()}.json"
            target_destination_path = os.path.join(output_directory, target_file_name)
            
            final_formatted_payload = None
            
            if sheet_name == "Stats":
                # Unroll single transaction metric row into a direct lookup object mapper
                if not dataframe.empty:
                    final_formatted_payload = dataframe.iloc[0].to_dict()
                else:
                    final_formatted_payload = {}
                    
            elif sheet_name == "Disclaimers":
                # Pivot sequential disclosure rows into an instant lookup map dictionary
                disclaimers_lookup_map = {}
                for _, data_row in dataframe.iterrows():
                    page_key = data_row.get("Page")
                    disclaimer_value = data_row.get("Disclaimer")
                    if page_key:
                        disclaimers_lookup_map[str(page_key)] = disclaimer_value
                final_formatted_payload = disclaimers_lookup_map
                
            elif sheet_name == "Events":
                # Clean structural timestamps down to clean YYYY-MM-DD strings
                if "Date" in dataframe.columns:
                    dataframe["Date"] = pd.to_datetime(dataframe["Date"]).dt.strftime('%Y-%m-%d')
                final_formatted_payload = dataframe.to_dict(orient='records')
                
            else:
                # Fallback mapping loop for general programmatic listings collections
                final_formatted_payload = dataframe.to_dict(orient='records')
            
            # Deep scrub the payloads to strip illegal NaN floats before exporting
            sanitized_payload = clean_nan_values(final_formatted_payload)
            
            # Commit structural json data strings down to the local file system
            with open(target_destination_path, 'w', encoding='utf-8') as output_file_sink:
                json.dump(sanitized_payload, output_file_sink, indent=2, ensure_ascii=False)
                
            print(f"💾 Raw static payload records exported cleanly: {target_destination_path}")
            
        print("✅ Data serialization complete. Spreadsheet assets synchronized.")
        
    except Exception as pipeline_fault:
        print(f"❌ Internal structural parsing error encountered: {pipeline_fault}")

if __name__ == "__main__":
    harvest_workbook_pipeline()