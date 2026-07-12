# File: scripts/harvest_website_data_sheet.py */
import os
import io
import json
import math
import re
import datetime
import requests
import pandas as pd
import urllib.parse
import boto3
from PIL import Image

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

def generate_url_slug(text_input):
    """
    Normalizes human names into clean, URL-safe string identifiers.
    """
    processed_string = str(text_input).lower().strip()
    processed_string = re.sub(r'[^a-z0-9\s-]', '', processed_string)
    return re.sub(r'[\s-]+', '-', processed_string)

def load_existing_r2_cache():
    """
    Scans the repository's data directory for pre-compiled JSON files. Extracts all
    historical Cloudflare R2 URLs to build a high-performance local cache mapping
    Google Drive File IDs directly to their custom subdomain assets.
    """
    cache_index = {}
    data_folder = "data"
    
    if not os.path.exists(data_folder):
        return cache_index
        
    print("🧠 Initializing Git-Based JSON Cache Engine...")
    for target_json_file in os.listdir(data_folder):
        if not target_json_file.endswith(".json") or target_json_file == "quizzes.json":
            continue
            
        full_file_path = os.path.join(data_folder, target_json_file)
        try:
            with open(full_file_path, "r", encoding="utf-8") as file_stream:
                raw_json_text = file_stream.read()
                
            # Regex sweeps for any assets.myseattlesearch.com image URL configurations
            discovered_urls = re.findall(r'https://assets\.myseattlesearch\.com/[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+\.webp', raw_json_text)
            for asset_url in discovered_urls:
                # Extract the unique file ID component right before the extension block
                file_id_match = re.search(r'/([a-zA-Z0-9_-]+)\.webp$', asset_url)
                if file_id_match:
                    extracted_id = file_id_match.group(1)
                    cache_index[extracted_id] = asset_url
        except Exception as cache_fault:
            print(f"⚠️ Warning: Skipping cache indexing parse on file {target_json_file}: {cache_fault}")
            
    if cache_index:
        print(f"✅ Cache Engine Online. Indexed {len(cache_index)} historical assets across your repository files.")
    else:
        print("ℹ️ Zero historical asset records indexed. Starting a clean-slate compilation pass.")
    return cache_index

# Global initialization of the local image cache matrix index
GLOBAL_R2_CACHE = load_existing_r2_cache()

def convert_and_upload_to_r2(cell_value, sheet_name):
    """
    Checks if an individual cell contains a Google Drive link. Cross-references 
    the file ID against the repository cache index. Reuses historical URLs instantly,
    or falls back to download, compress, and upload new media on demand.
    """
    if not isinstance(cell_value, str) or "drive.google.com" not in cell_value:
        return cell_value

    # Extract the unique file ID from common Google Drive link structures
    match = re.search(r'/file/d/([a-zA-Z0-9_-]+)', cell_value)
    if not match:
        match = re.search(r'id=([a-zA-Z0-9_-]+)', cell_value)
        
    if not match:
        return cell_value  

    file_id = match.group(1)
    
    # 🌟 THE SMART BYPASS: Check if this asset file ID has already been converted historically
    if file_id in GLOBAL_R2_CACHE:
        print(f"⚡ Cache Hit! Reusing optimized R2 asset for ID: {file_id}")
        return GLOBAL_R2_CACHE[file_id]
        
    # Cache Miss: Process and upload a new asset
    r2_access_key = os.environ.get("R2_ACCESS_KEY_ID")
    r2_secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
    r2_endpoint = os.environ.get("R2_ENDPOINT_URL")
    r2_bucket = os.environ.get("R2_BUCKET_NAME")
    custom_domain = "https://assets.myseattlesearch.com"
    
    if not all([r2_access_key, r2_secret_key, r2_endpoint, r2_bucket]):
        print(f"⚠️ R2 environment secrets missing. Preserving original Drive link for ID: {file_id}")
        return cell_value

    print(f"📸 New image discovered in tab '{sheet_name}' (ID: {file_id}). Compressing to WebP...")
    
    try:
        # 1. Download raw image from Google's delivery server
        download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
        download_response = requests.get(download_url, timeout=30)
        download_response.raise_for_status()
        
        # 2. Feed raw bytes into Pillow image processor
        raw_image_bytes = io.BytesIO(download_response.content)
        processed_image = Image.open(raw_image_bytes)
        
        if processed_image.mode in ("RGBA", "P"):
            processed_image = processed_image.convert("RGBA")
        else:
            processed_image = processed_image.convert("RGB")
            
        # 3. Compress image directly into an in-memory byte buffer
        webp_byte_stream = io.BytesIO()
        processed_image.save(webp_byte_stream, format="WEBP", quality=80)
        webp_byte_stream.seek(0)
        
        # 4. Connect to Cloudflare R2 API
        s3_client = boto3.client(
            "s3",
            endpoint_url=r2_endpoint,
            aws_access_key_id=r2_access_key,
            aws_secret_access_key=r2_secret_key,
            region_name="auto"
        )
        
        object_key = f"{sheet_name.lower()}/{file_id}.webp"
        
        # 5. Deliver optimized file directly to Cloudflare
        s3_client.put_object(
            Bucket=r2_bucket,
            Key=object_key,
            Body=webp_byte_stream,
            ContentType="image/webp"
        )
        
        permanent_r2_url = f"{custom_domain}/{object_key}"
        print(f"🚀 Asset successfully transferred to Cloudflare: {permanent_r2_url}")
        return permanent_r2_url
        
    except Exception as process_fault:
        print(f"❌ Image processing error on asset {file_id}: {process_fault}")
        return cell_value

def harvest_workbook_pipeline():
    SOURCE_URL = os.environ.get("GOOGLE_SHEET_LIVE_URL")
    if not SOURCE_URL:
        print("❌ Error: GOOGLE_SHEET_LIVE_URL configuration parameter is missing from environment.")
        return

    print("📡 Handshaking real-time with Google Sheet master workbook node...")
    try:
        response = requests.get(SOURCE_URL, timeout=30)
        response.raise_for_status()
        workbook_bytes = io.BytesIO(response.content)
    except Exception as network_error:
        print(f"❌ Connection failure during spreadsheet fetch pass: {network_error}")
        return

    output_directory = "data"
    os.makedirs(output_directory, exist_ok=True)
    
    try:
        excel_file_wrapper = pd.ExcelFile(workbook_bytes)
        print(f"📋 Workbook loaded successfully. Tabs discovered: {excel_file_wrapper.sheet_names}")
        
        # Primary parsing pass: Build our master relational Team directory index
        team_lookup_directory = {}
        compiled_team_payload = []
        
        if "Team" in excel_file_wrapper.sheet_names:
            team_dataframe = pd.read_excel(excel_file_wrapper, sheet_name="Team")
            for _, team_row in team_dataframe.iterrows():
                raw_team_id = team_row.get("Team ID")
                if pd.notna(raw_team_id):
                    string_team_id = str(raw_team_id).strip().replace(".0", "")
                    member_name = str(team_row.get("Name", "")).strip()
                    
                    raw_photo_link = str(team_row.get("Photo", "")).strip() if pd.notna(team_row.get("Photo")) else ""
                    optimized_photo_link = convert_and_upload_to_r2(raw_photo_link, "Team")
                    
                    member_object = {
                        "id": string_team_id,
                        "teamPage": str(team_row.get("Team Page", "No")).strip().lower() == "yes",
                        "position": str(team_row.get("Position", "")).strip(),
                        "name": member_name,
                        "slug": generate_url_slug(member_name),
                        "phone": str(team_row.get("Phone", "")).strip() if pd.notna(team_row.get("Phone")) else "",
                        "email": str(team_row.get("Email", "")).strip() if pd.notna(team_row.get("Email")) else "",
                        "website": str(team_row.get("Website", "")).strip() if pd.notna(team_row.get("Website")) else "",
                        "description": str(team_row.get("Description", "")).strip() if pd.notna(team_row.get("Description")) else "",
                        "photo": optimized_photo_link
                    }
                    team_lookup_directory[string_team_id] = member_object
                    compiled_team_payload.append(member_object)

        for sheet_name in excel_file_wrapper.sheet_names:
            if sheet_name == "Team":
                sanitized_payload = clean_nan_values(compiled_team_payload)
                target_destination_path = os.path.join(output_directory, "team.json")
                with open(target_destination_path, 'w', encoding='utf-8') as output_file_sink:
                    json.dump(sanitized_payload, output_file_sink, indent=2, ensure_ascii=False)
                print(f"💾 Centralized Team roster metrics committed: {target_destination_path}")
                continue
                
            dataframe = pd.read_excel(excel_file_wrapper, sheet_name=sheet_name)
            target_file_name = f"{sheet_name.lower()}.json"
            target_destination_path = os.path.join(output_directory, target_file_name)
            final_formatted_payload = None
            
            if sheet_name == "Stats":
                stats_dict = dataframe.iloc[0].to_dict() if not dataframe.empty else {}
                for key, val in stats_dict.items():
                    if isinstance(val, str) and "drive.google.com" in val:
                        stats_dict[key] = convert_and_upload_to_r2(val, sheet_name)
                final_formatted_payload = stats_dict
                    
            elif sheet_name == "Disclaimers":
                disclaimers_lookup_map = {}
                for _, data_row in dataframe.iterrows():
                    page_key = data_row.get("Page")
                    if page_key:
                        disclaimers_lookup_map[str(page_key)] = data_row.get("Disclaimer")
                final_formatted_payload = disclaimers_lookup_map
                
            elif sheet_name == "Events":
                compiled_events = []
                today_date = datetime.date.today()
                
                for _, event_row in dataframe.iterrows():
                    if str(event_row.get("Status", "")).strip().lower() != "active":
                        continue
                        
                    event_id_clean = str(event_row.get("Event ID", "")).strip().lower()
                    if not event_id_clean or event_id_clean == "nan":
                        continue

                    raw_publish_date = event_row.get("Publish Date")
                    if pd.notna(raw_publish_date):
                        try:
                            publish_datetime = pd.to_datetime(raw_publish_date).date()
                            if publish_datetime > today_date:
                                continue
                        except:
                            pass

                    raw_date_stamp = event_row.get("Date")
                    clean_date_string = ""
                    if pd.notna(raw_date_stamp):
                        try:
                            clean_date_string = pd.to_datetime(raw_date_stamp).strftime('%Y-%m-%d')
                        except:
                            clean_date_string = str(raw_date_stamp).strip()

                    def build_time_string(time_input_node):
                        if pd.isna(time_input_node): return None
                        if hasattr(time_input_node, 'strftime'): return time_input_node.strftime('%H:%M')
                        time_string_raw = str(time_input_node).strip()
                        if ":" in time_string_raw:
                            time_segments = time_string_raw.split(":")
                            return f"{time_segments[0]}:{time_segments[1]}"
                        return time_string_raw

                    start_time_clean = build_time_string(event_row.get("Start Time"))
                    end_time_clean = build_time_string(event_row.get("End Time"))

                    host_ids_raw = str(event_row.get("Host IDs", "")).strip()
                    comma_separated_host_ids = host_ids_raw.split(",")
                    associated_host_objects = []
                    for host_id_element in comma_separated_host_ids:
                        target_host_key = host_id_element.strip().replace(".0", "")
                        if target_host_key in team_lookup_directory:
                            associated_host_objects.append(team_lookup_directory[target_host_key])

                    raw_city_text = str(event_row.get("City", "")).strip()
                    geographic_taxonomy_array = [raw_city_text.lower()] if raw_city_text and raw_city_text.lower() != "nan" else []

                    supplied_maps_link = str(event_row.get("Google Maps Link", "")).strip()
                    location_title = str(event_row.get("Location Name", "")).strip()
                    street_address_line = str(event_row.get("Street Address", "")).strip()

                    if supplied_maps_link and supplied_maps_link.lower() != "nan":
                        final_maps_endpoint = supplied_maps_link
                    else:
                        assembled_query = f"{location_title} {street_address_line} {raw_city_text} WA".strip()
                        final_maps_endpoint = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote_plus(assembled_query)}"

                    event_image_assets = []
                    for target_img_header in ["Image 1 Link", "Image 2 Link", "Image 3 Link"]:
                        individual_img_url = str(event_row.get(target_img_header, "")).strip()
                        if individual_img_url and individual_img_url.lower() != "nan":
                            optimized_img_url = convert_and_upload_to_r2(individual_img_url, "Events")
                            event_image_assets.append(optimized_img_url)

                    def evaluate_affirmative_switch(switch_value):
                        return str(switch_value).strip().lower() == "yes"

                    compiled_events.append({
                        "id": event_id_clean,
                        "type": str(event_row.get("Type", "")).strip() if pd.notna(event_row.get("Type")) else "Home Buying Class",
                        "status": "Active",
                        "title": str(event_row.get("Title", "")).strip() if pd.notna(event_row.get("Title")) else "",
                        "subtitle": str(event_row.get("Subtitle", "")).strip() if pd.notna(event_row.get("Subtitle")) and str(event_row.get("Subtitle")).lower() != "nan" else None,
                        "date": clean_date_string,
                        "startTime": start_time_clean,
                        "endTime": end_time_clean,
                        "locationName": location_title if location_title != "nan" else "",
                        "streetAddress": street_address_line if street_address_line != "nan" else "",
                        "city": raw_city_text if raw_city_text != "nan" else "",
                        "cities": geographic_taxonomy_array,
                        "display": evaluate_affirmative_switch(event_row.get("Display", "Yes")),
                        "registration": evaluate_affirmative_switch(event_row.get("Registration", "Yes")),
                        "legacyLink": str(event_row.get("Link", "")).strip() if pd.notna(event_row.get("Link")) and str(event_row.get("Link")).lower() != "nan" else "",
                        "description": str(event_row.get("Full Description", "")).strip() if pd.notna(event_row.get("Full Description")) and str(event_row.get("Full Description")).lower() != "nan" else "",
                        "mapsLink": final_maps_endpoint,
                        "images": event_image_assets,
                        "webhookUrl": str(event_row.get("Webhook URL", "")).strip() if pd.notna(event_row.get("Webhook URL")) and str(event_row.get("Webhook URL")).lower() != "nan" else "",
                        "hostIds": host_ids_raw,
                        "hosts": associated_host_objects
                    })
                final_formatted_payload = compiled_events
            else:
                generic_processed_records = []
                for _, basic_row in dataframe.iterrows():
                    row_dictionary = basic_row.to_dict()
                    for cell_key, cell_value in row_dictionary.items():
                        if isinstance(cell_value, str) and "drive.google.com" in cell_value:
                            row_dictionary[cell_key] = convert_and_upload_to_r2(cell_value, sheet_name)
                    generic_processed_records.append(row_dictionary)
                final_formatted_payload = generic_processed_records
            
            sanitized_payload = clean_nan_values(final_formatted_payload)
            with open(target_destination_path, 'w', encoding='utf-8') as output_file_sink:
                json.dump(sanitized_payload, output_file_sink, indent=2, ensure_ascii=False)
            print(f"💾 Static payload records exported cleanly: {target_destination_path}")
            
        print("✅ Data serialization complete. Spreadsheet assets synchronized.")
    except Exception as pipeline_fault:
        print(f"❌ Internal structural parsing error encountered: {pipeline_fault}")

if __name__ == "__main__":
    harvest_workbook_pipeline()