import os
import io
import json
import math
import re
import time
import datetime
import urllib.request
import urllib.parse
import requests
import boto3
from PIL import Image
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")
COMMUTE_TOLLS_PATH = os.path.join(DATA_DIR, "city_commute_tolls.json")

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/documents.readonly',
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
    out = []
    for ch in text:
        if ch.isalnum():
            out.append(ch)
        elif ch in [' ', '-', '_']:
            out.append('-')
    res = "".join(out)
    while '--' in res:
        res = res.replace('--', '-')
    return res.strip('-')

def generate_url_slug(text_input):
    processed = str(text_input).lower().strip()
    processed = re.sub(r'[^a-z0-9\s-]', '', processed)
    return re.sub(r'[\s-]+', '-', processed)

def extract_google_id(url_string):
    if not isinstance(url_string, str):
        return None
    match = re.search(r'/d/([a-zA-Z0-9_-]+)', url_string)
    if match:
        return match.group(1)
    match = re.search(r'id=([a-zA-Z0-9_-]+)', url_string)
    if match:
        return match.group(1)
    return None

def is_google_drive_link(url_string):
    if not isinstance(url_string, str) or not url_string.strip():
        return False
    u = url_string.lower().strip()
    if "assets.myseattlesearch.com" in u:
        return False
    return "drive.google.com" in u or "docs.google.com" in u or "drive.usercontent.google.com" in u or extract_google_id(url_string) is not None

def apply_markdown_style(content, style_type, url=None):
    if not content or content.isspace():
        return content
    match = re.match(r'^(\s*)(.*?)(\s*)$', content, re.DOTALL)
    if match:
        lead, core, trail = match.groups()
        if style_type == 'bold':
            core = f"**{core}**"
        elif style_type == 'italic':
            core = f"*{core}*"
        elif style_type == 'link' and url:
            core = core.replace('[', '').replace(']', '')
            core = f"[{core}]({url})"
        return f"{lead}{core}{trail}"
    return content

def get_google_doc_as_markdown(docs_service, doc_url):
    doc_id = extract_google_id(doc_url)
    if not doc_id:
        return ""
    try:
        doc = docs_service.documents().get(documentId=doc_id).execute()
        elements = doc.get('body', {}).get('content', [])
        markdown_text = []
        for element in elements:
            if 'paragraph' in element:
                paragraph = element['paragraph']
                named_style = paragraph.get('paragraphStyle', {}).get('namedStyleType', 'NORMAL_TEXT')
                p_text = ""
                for p_element in paragraph.get('elements', []):
                    if 'textRun' in p_element:
                        text_run = p_element['textRun']
                        content = text_run.get('content', '')
                        style = text_run.get('textStyle', {})
                        if style.get('bold'):
                            content = apply_markdown_style(content, 'bold')
                        if style.get('italic'):
                            content = apply_markdown_style(content, 'italic')
                        if 'link' in style and 'url' in style['link']:
                            content = apply_markdown_style(content, 'link', style['link']['url'])
                        p_text += content
                if named_style == 'HEADING_1':
                    markdown_text.append(f"# {p_text.strip()}\n\n")
                elif named_style == 'HEADING_2':
                    markdown_text.append(f"## {p_text.strip()}\n\n")
                elif named_style == 'HEADING_3':
                    markdown_text.append(f"### {p_text.strip()}\n\n")
                else:
                    markdown_text.append(p_text)
        return "".join(markdown_text)
    except Exception as e:
        print(f"   ⚠️ Doc parsing fault on ID {doc_id}: {e}")
        return ""

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
        img = img.convert("RGBA") if img.mode in ("RGBA", "P") else img.convert("RGB")
        
        webp_buffer = io.BytesIO()
        img.save(webp_buffer, format="WEBP", quality=80)
        webp_buffer.seek(0)
        
        s3_client.put_object(
            Bucket=r2_bucket,
            Key=object_key,
            Body=webp_buffer,
            ContentType="image/webp"
        )

        try:
            drive_service.files().delete(fileId=file_id).execute()
        except Exception:
            pass

        return permanent_url
    except Exception as e:
        print(f"   ❌ Image upload notice for {file_id}: {e}")
        return image_url

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
    if clean_id in wsdot_known_map:
        return wsdot_known_map[clean_id]
    return str(raw_name).strip()

def harvest_commute_and_tolls(toll_schedules_from_sheet=None):
    wsdot_code = os.environ.get("WSDOT_ACCESS_CODE", "").strip().strip("'").strip('"')
    tolls_data = []
    travel_times_data = []

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
            print(f"   ⚠️ Tolls fetch notice: {e}")

    static_schedules = toll_schedules_from_sheet if toll_schedules_from_sheet else []
    output = {
        "live_express_tolls": tolls_data,
        "static_rate_schedules": static_schedules,
        "commute_corridors": travel_times_data,
        "last_updated": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
    with open(COMMUTE_TOLLS_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

def main():
    print("📊 Running Sheets Master Ingestion & Sync...")
    os.makedirs(DATA_DIR, exist_ok=True)
    editorials_dir = os.path.join(DATA_DIR, "editorials")
    os.makedirs(editorials_dir, exist_ok=True)

    creds_path = "credentials.json"
    if not os.path.exists(creds_path):
        print("❌ credentials.json missing.")
        return

    creds = Credentials.from_service_account_file(
        creds_path,
        scopes=SCOPES
    )
    sheets_service = build('sheets', 'v4', credentials=creds)
    docs_service = build('docs', 'v1', credentials=creds)
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

    batch_sheet_writebacks = {}

    # Module 1: Command Center
    cc_sheet_id = os.environ.get("COMMAND_CENTER_SHEET_ID")
    if cc_sheet_id:
        try:
            cc_ranges = ["Market_Dashboard!A:Z", "Rates!A:Z", "Historical_Log!A:Z"]
            cc_batch = sheets_service.spreadsheets().values().batchGet(
                spreadsheetId=cc_sheet_id, ranges=cc_ranges
            ).execute().get('valueRanges', [])

            if len(cc_batch) > 0 and cc_batch[0].get('values'):
                with open(os.path.join(DATA_DIR, "hourly_market.json"), "w", encoding="utf-8") as f:
                    json.dump(parse_sheet_values(cc_batch[0]['values']), f, indent=2, ensure_ascii=False)
            if len(cc_batch) > 1 and cc_batch[1].get('values'):
                with open(os.path.join(DATA_DIR, "hourly_rates.json"), "w", encoding="utf-8") as f:
                    json.dump(parse_sheet_values(cc_batch[1]['values']), f, indent=2, ensure_ascii=False)
            if len(cc_batch) > 2 and cc_batch[2].get('values'):
                with open(os.path.join(DATA_DIR, "hourly_market_historical.json"), "w", encoding="utf-8") as f:
                    json.dump(parse_sheet_values(cc_batch[2]['values']), f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"   ⚠️ Command Center notice: {e}")

    # Module 1B: City Data
    city_sheet_id = os.environ.get("CITY_DATA_SHEET_ID")
    if city_sheet_id:
        try:
            if city_sheet_id not in batch_sheet_writebacks:
                batch_sheet_writebacks[city_sheet_id] = []

            rows = sheets_service.spreadsheets().values().get(
                spreadsheetId=city_sheet_id, range="CityData!A:AZ"
            ).execute().get('values', [])

            if rows and len(rows) >= 2:
                headers = [str(h).strip() for h in rows[0]]
                parsed_city_data = parse_sheet_values(rows)

                with open(CITY_DATA_PATH, "w", encoding="utf-8") as f:
                    json.dump(clean_nan_tokens(parsed_city_data), f, indent=2, ensure_ascii=False)

                col_status_idx = -1
                for candidate in ["EditorialStatus", "Editorial Status", "Editorial_Status"]:
                    if candidate in headers:
                        col_status_idx = headers.index(candidate)
                        break

                for idx, r in enumerate(rows[1:]):
                    padded = list(r) + [""] * (len(headers) - len(r))
                    record = dict(zip(headers, padded))
                    row_num = idx + 2
                    city_name = record.get("City", "").strip()
                    if not city_name: continue

                    slug = slugify(city_name)
                    doc_url = record.get("Editorial", "").strip()
                    status = (record.get("EditorialStatus", "") or record.get("Editorial Status", "") or "").strip()

                    if doc_url and is_google_drive_link(doc_url) and status.lower() == "pending":
                        md_content = get_google_doc_as_markdown(docs_service, doc_url)
                        if md_content and md_content.strip():
                            with open(os.path.join(editorials_dir, f"{slug}.md"), "w", encoding="utf-8") as f_md:
                                f_md.write(md_content)
                            if col_status_idx != -1:
                                batch_sheet_writebacks[city_sheet_id].append({
                                    'range': f"CityData!{get_col_letter(col_status_idx)}{row_num}",
                                    'values': [["Complete"]]
                                })
        except Exception as e:
            print(f"   ⚠️ CityData notice: {e}")

    # Module 2: Website Data Workbook (Celebrations Removed)
    web_sheet_id = os.environ.get("WEBSITE_DATA_SHEET_ID")
    if web_sheet_id:
        target_tabs = ["Stats", "Team", "Disclaimers", "Events", "DPA", "Professionals", "Reviews", "ThirdPartyPrograms", "News", "Sales", "Live_Archive", "Uploads", "Sports", "TollData"]
        try:
            web_ranges = [f"{tab}!A:AZ" for tab in target_tabs]
            web_batch = sheets_service.spreadsheets().values().batchGet(
                spreadsheetId=web_sheet_id, ranges=web_ranges
            ).execute().get('valueRanges', [])

            tabs_data = dict(zip(target_tabs, web_batch))
            if web_sheet_id not in batch_sheet_writebacks:
                batch_sheet_writebacks[web_sheet_id] = []

            toll_rows = tabs_data.get("TollData", {}).get('values', [])
            harvest_commute_and_tolls(parse_sheet_values(toll_rows) if toll_rows else [])

            # Write out simple tabs
            for tab_name, json_name in [
                ("Stats", "stats.json"), ("Disclaimers", "disclaimers.json"),
                ("DPA", "dpa_programs.json"), ("Professionals", "professionals.json"), 
                ("Reviews", "reviews.json"), ("ThirdPartyPrograms", "thirdpartyprograms.json"), 
                ("News", "news.json"), ("Sports", "sports_teams.json")
            ]:
                rows = tabs_data.get(tab_name, {}).get('values', [])
                if rows:
                    recs = parse_sheet_values(rows)
                    data_obj = recs[0] if tab_name == "Stats" else recs
                    with open(os.path.join(DATA_DIR, json_name), "w", encoding="utf-8") as f:
                        json.dump(clean_nan_tokens(data_obj), f, indent=2, ensure_ascii=False)

            # Sales & DOM Calibration
            sales_rows = tabs_data.get("Sales", {}).get('values', [])
            if sales_rows:
                headers = [h.strip() for h in sales_rows[0]]
                compiled_sales = []
                today_date = datetime.datetime.now().date()
                for idx, r in enumerate(sales_rows[1:]):
                    padded = list(r) + [""] * (len(headers) - len(r))
                    row_dict = dict(zip(headers, padded))
                    if row_dict.get("Status", "").strip() != "Sold":
                        s_date = row_dict.get("Selling Date")
                        if s_date and str(s_date).strip():
                            try:
                                dt_obj = datetime.datetime.strptime(str(s_date).strip(), "%m/%d/%Y").date()
                                row_dict["DOM"] = max(0, (today_date - dt_obj).days)
                            except Exception:
                                row_dict["DOM"] = "-"
                    compiled_sales.append(row_dict)
                with open(os.path.join(DATA_DIR, "sales.json"), "w", encoding="utf-8") as f:
                    json.dump(clean_nan_tokens(compiled_sales), f, indent=4, ensure_ascii=False)

        except Exception as e:
            print(f"   ⚠️ Website Data workbook notice: {e}")

    # Flush Cell Writebacks
    for s_id, updates in batch_sheet_writebacks.items():
        if updates:
            try:
                sheets_service.spreadsheets().values().batchUpdate(
                    spreadsheetId=s_id, body={'valueInputOption': 'USER_ENTERED', 'data': updates}
                ).execute()
            except Exception as write_err:
                print(f"   ⚠️ Sheet writeback notice: {write_err}")

    print("✅ Sheets Master Sync complete.")

if __name__ == "__main__":
    main()