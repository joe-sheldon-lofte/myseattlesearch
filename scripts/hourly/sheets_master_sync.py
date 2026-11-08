# File: scripts/sheets_master_sync.py

import os
import io
import re
import json
import math
import datetime
import requests
import boto3
from PIL import Image
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
COMMUTE_TOLLS_PATH = os.path.join(DATA_DIR, "city_commute_tolls.json")

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

def get_col_letter(col_idx):
    result = ""
    col_idx += 1
    while col_idx > 0:
        remainder = (col_idx - 1) % 26
        result = chr(65 + remainder) + result
        col_idx = (col_idx - 1) // 26
    return result

def clean_nan_tokens(node):
    if isinstance(node, dict):
        return {k: clean_nan_tokens(v) for k, v in node.items()}
    elif isinstance(node, list):
        return [clean_nan_tokens(element) for element in node]
    elif isinstance(node, float) and (math.isnan(node) or math.isinf(node)):
        return None
    return node

def slugify(text):
    if not text:
        return ""
    text = str(text).lower().strip()
    out = [ch if ch.isalnum() else '-' for ch in text if ch.isalnum() or ch in [' ', '-', '_']]
    res = "".join(out)
    while '--' in res:
        res = res.replace('--', '-')
    return res.strip('-')

def extract_google_id(url_string):
    if not isinstance(url_string, str):
        return None
    match = re.search(r'/d/([a-zA-Z0-9_-]+)', url_string)
    if match:
        return match.group(1)
    match = re.search(r'id=([a-zA-Z0-9_-]+)', url_string)
    return match.group(1) if match else None

def is_google_drive_link(url_string):
    if not isinstance(url_string, str) or not url_string.strip():
        return False
    u = url_string.lower().strip()
    if "assets.myseattlesearch.com" in u:
        return False
    return "drive.google.com" in u or "docs.google.com" in u or "drive.usercontent.google.com" in u or extract_google_id(url_string) is not None

def process_and_upload_image(drive_service, s3_client, r2_bucket, image_url, folder_name, filename_slug, index=1):
    file_id = extract_google_id(image_url)
    if not file_id:
        return image_url

    custom_domain = "https://assets.myseattlesearch.com"
    object_key = f"{folder_name.lower()}/{filename_slug}-img-{index}.webp"
    permanent_url = f"{custom_domain}/{object_key}"

    try:
        request = drive_service.files().get_media(fileId=file_id)
        raw_bytes = request.execute()

        file_stream = io.BytesIO(raw_bytes)
        img = Image.open(file_stream)

        max_dim = 1600
        if img.width > max_dim or img.height > max_dim:
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

        img = img.convert("RGBA") if img.mode in ("RGBA", "P") else img.convert("RGB")

        webp_buffer = io.BytesIO()
        img.save(webp_buffer, format="WEBP", quality=82)
        webp_buffer.seek(0)

        s3_client.put_object(
            Bucket=r2_bucket,
            Key=object_key,
            Body=webp_buffer,
            ContentType="image/webp",
            CacheControl="public, max-age=31536000, immutable"
        )

        try:
            drive_service.files().delete(fileId=file_id).execute()
        except Exception:
            pass

        return permanent_url
    except Exception as e:
        print(f"   ❌ Image upload notice for {file_id}: {e}")
        return image_url

def process_custom_upload_asset(drive_service, s3_client, r2_bucket, drive_link, target_dir, asset_name):
    file_id = extract_google_id(drive_link)
    if not file_id or not s3_client or not r2_bucket:
        return drive_link

    clean_dir = str(target_dir).strip().strip('/')
    clean_name = slugify(asset_name)
    object_key = f"{clean_dir}/{clean_name}.webp" if clean_dir else f"{clean_name}.webp"
    permanent_url = f"https://assets.myseattlesearch.com/{object_key}"

    try:
        request = drive_service.files().get_media(fileId=file_id)
        raw_bytes = request.execute()

        file_stream = io.BytesIO(raw_bytes)
        img = Image.open(file_stream)

        max_dim = 1600
        if img.width > max_dim or img.height > max_dim:
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

        img = img.convert("RGBA") if img.mode in ("RGBA", "P") else img.convert("RGB")

        webp_buffer = io.BytesIO()
        img.save(webp_buffer, format="WEBP", quality=82)
        webp_buffer.seek(0)

        s3_client.put_object(
            Bucket=r2_bucket,
            Key=object_key,
            Body=webp_buffer,
            ContentType="image/webp",
            CacheControl="public, max-age=31536000, immutable"
        )
        print(f"   🚀 Asset converted & uploaded to R2: {object_key}")

        try:
            drive_service.files().delete(fileId=file_id).execute()
        except Exception:
            pass

        return permanent_url
    except Exception as e:
        print(f"   ❌ Asset upload fault for {file_id}: {e}")
        return drive_link

def process_and_upload_pdf(drive_service, s3_client, r2_bucket, pdf_url, mls_number, index=1):
    file_id = extract_google_id(pdf_url)
    if not file_id:
        filename = pdf_url.split('/')[-1].split('?')[0]
        title = filename.replace('.pdf', '').replace('.PDF', '').replace('_', ' ').replace('-', ' ').title()
        return pdf_url, title or f"Document {index}"

    custom_domain = "https://assets.myseattlesearch.com"

    try:
        file_meta = drive_service.files().get(fileId=file_id, fields="name").execute()
        original_name = file_meta.get("name", f"Document_{index}.pdf")
        clean_name = re.sub(r'[^a-zA-Z0-9._-]', '_', original_name)
        if not clean_name.lower().endswith('.pdf'):
            clean_name += '.pdf'

        object_key = f"downloads/{str(mls_number).strip()}/{clean_name}"
        permanent_url = f"{custom_domain}/{object_key}"

        request = drive_service.files().get_media(fileId=file_id)
        raw_bytes = request.execute()

        s3_client.put_object(
            Bucket=r2_bucket,
            Key=object_key,
            Body=raw_bytes,
            ContentType="application/pdf"
        )

        try:
            drive_service.files().delete(fileId=file_id).execute()
        except Exception:
            pass

        display_title = original_name.replace('.pdf', '').replace('.PDF', '').replace('_', ' ').replace('-', ' ').title()
        return permanent_url, display_title
    except Exception as e:
        print(f"   ❌ PDF upload notice for {file_id}: {e}")
        return pdf_url, f"Document {index}"

def parse_sheet_values(rows):
    if not rows:
        return []
    headers = [str(h).strip() for h in rows[0]]
    records = []
    for row in rows[1:]:
        padded = list(row) + [""] * (len(headers) - len(row))
        sanitized = [str(item).strip() if item is not None else "" for item in padded]
        records.append(dict(zip(headers, sanitized)))
    return records

def clean_wsdot_facility_name(raw_name, travel_dir):
    if not raw_name:
        return "Express Toll Lane"
    clean_id = str(raw_name).strip().lower()
    wsdot_known_map = {
        "520tp00422": "SR 520 Floating Bridge (Eastbound)",
        "520tp00421": "SR 520 Floating Bridge (Westbound)",
        "099tp03060": "SR 99 Tunnel (Southbound)",
        "099tp03268": "SR 99 Tunnel (Northbound)",
        "509tp02050": "SR 509 Expressway (Southbound)",
    }
    return wsdot_known_map.get(clean_id, str(raw_name).strip())

def harvest_commute_and_tolls():
    wsdot_code = os.environ.get("WSDOT_ACCESS_CODE", "").strip().strip("'").strip('"')
    tolls_data = []

    if wsdot_code:
        headers = {"User-Agent": "Mozilla/5.0"}
        tolls_url = f"https://wsdot.wa.gov/Traffic/api/TollRates/TollRatesREST.svc/GetTollTripRatesAsJson?AccessCode={wsdot_code}"
        try:
            res = requests.get(tolls_url, headers=headers, timeout=15)
            if res.status_code == 200:
                raw_trips = res.json()
                facility_rate_map = {}
                for t in (raw_trips if isinstance(raw_trips, list) else []):
                    raw_facility = t.get("TripName") or t.get("LocationName") or ""
                    travel_dir = t.get("TravelDirection") or ""
                    facility_name = clean_wsdot_facility_name(raw_facility, travel_dir)
                    cents = int(t.get("CurrentTollCents") or 0)
                    dollars = round(cents / 100.0, 2)
                    if cents > 0:
                        key = f"{facility_name}_{travel_dir}"
                        facility_rate_map[key] = {
                            "facility": facility_name,
                            "travel_direction": travel_dir,
                            "current_toll_cents": cents,
                            "current_toll_dollars": dollars,
                            "sign_message": f"${dollars:.2f}"
                        }
                tolls_data = list(facility_rate_map.values())
        except Exception as e:
            print(f"   ⚠️ WSDOT Tolls live fetch notice: {e}")

    output = {
        "live_express_tolls": tolls_data,
        "static_rate_schedules": [],
        "commute_corridors": [],
        "last_updated": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
    with open(COMMUTE_TOLLS_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print("   Updated city_commute_tolls.json directly from WSDOT API.")

def main():
    print("📊 Running Hourly Platform Sync (Historical Log, Media, News, Sports & Live Tolls)...")
    os.makedirs(DATA_DIR, exist_ok=True)

    # 1. Harvest Live WSDOT Express Tolls
    harvest_commute_and_tolls()

    # 2. Connect to Google Sheets & R2 Engine
    master_sheet_id = os.environ.get("WEBSITE_DATA_CORE_SHEET_ID") or os.environ.get("WEBSITE_DATA_SHEET_ID")
    creds_path = "credentials.json"
    if not master_sheet_id or not os.path.exists(creds_path):
        print("❌ Missing credentials or Sheet ID. Exiting Sheets ingestion.")
        return

    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    sheets_service = build('sheets', 'v4', credentials=creds)
    drive_service = build('drive', 'v3', credentials=creds)

    r2_access_key = os.environ.get("R2_ACCESS_KEY_ID")
    r2_secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
    r2_endpoint = os.environ.get("R2_ENDPOINT_URL")
    r2_bucket = os.environ.get("R2_BUCKET_NAME")
    s3_client = None
    if all([r2_access_key, r2_secret_key, r2_endpoint, r2_bucket]):
        s3_client = boto3.client(
            "s3", endpoint_url=r2_endpoint,
            aws_access_key_id=r2_access_key, aws_secret_access_key=r2_secret_key,
            region_name="auto"
        )

    # 3. Pull strictly the 6 Hourly Tabs (BookingRules added)
    all_tabs = ["Historical_Log", "News", "Uploads", "Sports", "Publishers", "BookingRules"]
    ranges = [f"{tab}!A:BK" for tab in all_tabs]

    res = sheets_service.spreadsheets().values().batchGet(spreadsheetId=master_sheet_id, ranges=ranges).execute()
    data = dict(zip(all_tabs, res.get('valueRanges', [])))
    sheet_writebacks = []

    # Historical Log
    if data.get("Historical_Log", {}).get('values'):
        with open(os.path.join(DATA_DIR, "hourly_market_historical.json"), "w", encoding="utf-8") as f:
            json.dump(parse_sheet_values(data["Historical_Log"]['values']), f, indent=2, ensure_ascii=False)

    # R2 Image Asset Conversion Engine
    upload_rows = data.get("Uploads", {}).get('values', [])
    if upload_rows and len(upload_rows) >= 2:
        u_headers = [str(h).strip() for h in upload_rows[0]]
        col_u_link = next((i for i, h in enumerate(u_headers) if h in ["Link", "Drive Link", "URL"]), -1)
        col_u_dir = next((i for i, h in enumerate(u_headers) if h in ["Directory", "Image Directory", "Folder", "Dir"]), -1)
        col_u_name = next((i for i, h in enumerate(u_headers) if h in ["Name", "Asset Name", "File Name"]), -1)
        col_u_asset = next((i for i, h in enumerate(u_headers) if h in ["New Asset URL", "Asset URL", "New Asset Link", "New URL"]), col_u_link)
        col_u_done = next((i for i, h in enumerate(u_headers) if h in ["Done", "Status", "Complete", "Processed"]), -1)

        for idx, r in enumerate(upload_rows[1:]):
            padded = list(r) + [""] * (len(u_headers) - len(r))
            u_rec = dict(zip(u_headers, padded))
            row_num = idx + 2

            d_link = (u_rec.get("Link") or u_rec.get("Drive Link") or u_rec.get("URL") or "").strip()
            d_dir = (u_rec.get("Directory") or u_rec.get("Image Directory") or u_rec.get("Folder") or "").strip()
            d_name = (u_rec.get("Name") or u_rec.get("Asset Name") or u_rec.get("File Name") or "").strip()
            d_done = (u_rec.get("Done") or u_rec.get("Status") or u_rec.get("Complete") or "").strip().lower()

            if d_link and is_google_drive_link(d_link) and d_done != "yes" and s3_client:
                new_url = process_custom_upload_asset(drive_service, s3_client, r2_bucket, d_link, d_dir, d_name)
                if new_url and new_url != d_link:
                    if col_u_asset != -1:
                        sheet_writebacks.append({'range': f"Uploads!{get_col_letter(col_u_asset)}{row_num}", 'values': [[new_url]]})
                    if col_u_done != -1:
                        sheet_writebacks.append({'range': f"Uploads!{get_col_letter(col_u_done)}{row_num}", 'values': [["Yes"]]})

    # Array JSON Outputs (BookingRules mapped to booking_rules.json)
    for tab_name, json_name in [
        ("News", "news.json"), 
        ("Sports", "sports_teams.json"), 
        ("Uploads", "uploads.json"), 
        ("Publishers", "publishers.json"),
        ("BookingRules", "booking_rules.json")
    ]:
        rows = data.get(tab_name, {}).get('values', [])
        if rows:
            with open(os.path.join(DATA_DIR, json_name), "w", encoding="utf-8") as f:
                json.dump(clean_nan_tokens(parse_sheet_values(rows)), f, indent=2, ensure_ascii=False)

    # Flush Cell Updates back to the Sheet
    if sheet_writebacks:
        try:
            sheets_service.spreadsheets().values().batchUpdate(
                spreadsheetId=master_sheet_id,
                body={'valueInputOption': 'USER_ENTERED', 'data': sheet_writebacks}
            ).execute()
        except Exception as e:
            print(f"   ⚠️ Sheet writeback notice: {e}")

    print("✅ Hourly Platform Sync complete.")

if __name__ == "__main__":
    main()