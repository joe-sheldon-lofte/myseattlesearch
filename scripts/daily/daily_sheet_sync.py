import os
import re
import json
import math
import datetime
import requests
import io
from urllib.parse import unquote
from PIL import Image
import boto3
from botocore.client import Config
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/documents.readonly',
    'https://www.googleapis.com/auth/drive.readonly'
]

def load_local_env():
    for env_file in [".dev.vars", ".env"]:
        env_path = os.path.join(BASE_DIR, env_file)
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line: continue
                        k, v = line.split("=", 1)
                        if k and k not in os.environ:
                            os.environ[k] = v.strip().strip("\"'")
            except Exception: pass

def get_col_letter(col_idx):
    result = ""
    col_idx += 1
    while col_idx > 0:
        remainder = (col_idx - 1) % 26
        result = chr(65 + remainder) + result
        col_idx = (col_idx - 1) // 26
    return result

def clean_nan_tokens(node):
    if isinstance(node, dict): return {k: clean_nan_tokens(v) for k, v in node.items()}
    elif isinstance(node, list): return [clean_nan_tokens(element) for element in node]
    elif isinstance(node, float) and (math.isnan(node) or math.isinf(node)): return None
    return node

def slugify(text):
    if not text: return ""
    text = str(text).lower().strip()
    out = "".join(ch if ch.isalnum() else '-' for ch in text)
    while '--' in out: out = out.replace('--', '-')
    return out.strip('-')

def extract_google_id(url_string):
    if not isinstance(url_string, str): return None
    match = re.search(r'/d/([a-zA-Z0-9_-]+)', url_string)
    if match: return match.group(1)
    match = re.search(r'id=([a-zA-Z0-9_-]+)', url_string)
    return match.group(1) if match else None

def is_google_drive_link(url_string):
    if not isinstance(url_string, str) or not url_string.strip(): return False
    return "docs.google.com" in url_string.lower().strip() or "drive.google.com" in url_string.lower().strip() or extract_google_id(url_string) is not None

def apply_markdown_style(content, style_type, url=None):
    if not content or content.isspace(): return content
    match = re.match(r'^(\s*)(.*?)(\s*)$', content, re.DOTALL)
    if match:
        lead, core, trail = match.groups()
        if style_type == 'bold': core = f"**{core}**"
        elif style_type == 'italic': core = f"*{core}*"
        elif style_type == 'link' and url:
            core = core.replace('[', '').replace(']', '')
            core = f"[{core}]({url})"
        return f"{lead}{core}{trail}"
    return content

def get_google_doc_as_markdown(docs_service, doc_url):
    doc_id = extract_google_id(doc_url)
    if not doc_id: return ""
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
                        if style.get('bold'): content = apply_markdown_style(content, 'bold')
                        if style.get('italic'): content = apply_markdown_style(content, 'italic')
                        if 'link' in style and 'url' in style['link']:
                            content = apply_markdown_style(content, 'link', style['link']['url'])
                        p_text += content
                if named_style == 'HEADING_1': markdown_text.append(f"# {p_text.strip()}\n\n")
                elif named_style == 'HEADING_2': markdown_text.append(f"## {p_text.strip()}\n\n")
                elif named_style == 'HEADING_3': markdown_text.append(f"### {p_text.strip()}\n\n")
                else: markdown_text.append(p_text)
        return "".join(markdown_text)
    except Exception as e:
        print(f"   ⚠️ Doc parsing fault on ID {doc_id}: {e}")
        return ""

def parse_sheet_values(rows):
    if not rows: return []
    headers = [str(h).strip() for h in rows[0]]
    records = []
    for row in rows[1:]:
        padded = list(row) + [""] * (len(headers) - len(row))
        records.append(dict(zip(headers, [str(item).strip() if item is not None else "" for item in padded])))
    return records

def sync_professionals_to_d1(records):
    account_id = os.environ.get("CF_ACCOUNT_ID")
    database_id = os.environ.get("CF_DATABASE_CUSTOMERS_ID")
    api_token = os.environ.get("CF_D1_API_TOKEN") or os.environ.get("CF_API_TOKEN")

    if not all([account_id, database_id, api_token]):
        print("   ⚠️ D1 credentials missing. Skipping Professional Sync.")
        return False

    def clean_val(v):
        if v is None: return None
        s = str(v).strip()
        return s if s else None

    mapped_rows = []
    for rec in records:
        category = clean_val(rec.get("Category") or rec.get("category")) or "General"
        biz_name = clean_val(rec.get("Business/Vendor Name") or rec.get("business_name") or rec.get("Business Name")) or "Unknown Vendor"
        pro_id = clean_val(rec.get("ProID") or rec.get("pro_id")) or slugify(f"{category}-{biz_name}")
        mapped_rows.append((
            pro_id, category, biz_name,
            clean_val(rec.get("Phone Number") or rec.get("phone_number") or rec.get("Phone")),
            clean_val(rec.get("Email") or rec.get("email")),
            clean_val(rec.get("Website") or rec.get("website")),
            clean_val(rec.get("Additional Info") or rec.get("additional_info") or rec.get("AdditionalInfo")),
            clean_val(rec.get("Legal Requirements") or rec.get("legal_requirements")),
            clean_val(rec.get("Legal Requirements Link") or rec.get("legal_requirements_link"))
        ))

    endpoint = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{database_id}/query"
    headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
    
    chunk_size = 10
    synced_count = 0
    for i in range(0, len(mapped_rows), chunk_size):
        chunk = mapped_rows[i:i + chunk_size]
        placeholders = ", ".join(["(?, ?, ?, ?, ?, ?, ?, ?, ?)"] * len(chunk))
        sql = f"INSERT OR REPLACE INTO professionals (pro_id, category, business_name, phone_number, email, website, additional_info, legal_requirements, legal_requirements_link) VALUES {placeholders};"
        flat_params = [item for row in chunk for item in row]
        try:
            res = requests.post(endpoint, headers=headers, json={"sql": sql, "params": flat_params}, timeout=30)
            if res.json().get("success"): synced_count += len(chunk)
            else: print(f"   ❌ D1 Query Batch Error: {res.json().get('errors')}")
        except Exception as e:
            print(f"   ❌ D1 Network Error in batch {i // chunk_size + 1}: {e}")

    print(f"   ⚡ Synchronized {synced_count}/{len(mapped_rows)} vendors into D1.")
    return synced_count == len(mapped_rows)

# --- Cloudflare R2 Asset Engine ---
def get_r2_client():
    account_id = os.environ.get("CF_ACCOUNT_ID")
    access_key = os.environ.get("R2_ALL_ACCESS_TOKEN")
    secret_key = os.environ.get("R2_ALL_SECRET_ACCESS_KEY")
    if not all([account_id, access_key, secret_key]): return None
    return boto3.client(
        's3',
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name='auto',
        config=Config(signature_version='s3v4')
    )

def process_and_upload_image(image_url, mls_number, image_index, r2_client, drive_service):
    if not image_url or not str(image_url).startswith("http"): return ""
    if "assets.myseattlesearch.com" in image_url: return image_url

    bucket_name = os.environ.get("R2_BUCKET_NAME", "myseattlesearch-assets")
    r2_key = f"sales/{mls_number}-img-{image_index}.webp"
    public_url = f"https://assets.myseattlesearch.com/{r2_key}"

    try:
        if is_google_drive_link(image_url):
            file_id = extract_google_id(image_url)
            if not file_id: return image_url

            request = drive_service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
            fh.seek(0)
            img = Image.open(fh)
        else:
            req = requests.get(image_url, timeout=10)
            req.raise_for_status()
            img = Image.open(io.BytesIO(req.content))

        if img.mode in ("RGBA", "P"): img = img.convert("RGB")
        img.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
        webp_buffer = io.BytesIO()
        img.save(webp_buffer, format="WEBP", quality=80, method=6)
        webp_buffer.seek(0)
        r2_client.upload_fileobj(webp_buffer, bucket_name, r2_key, ExtraArgs={'ContentType': 'image/webp'})
        return public_url
    except Exception as e:
        print(f"   ⚠️ Image Processing Failed for {mls_number} (Img {image_index}): {e}")
        return image_url

def process_and_upload_pdf(pdf_url, mls_number, pdf_index, r2_client, drive_service):
    if not pdf_url or not str(pdf_url).startswith("http"): return ""
    if "assets.myseattlesearch.com" in pdf_url: return pdf_url

    file_id = extract_google_id(pdf_url)
    if not file_id: return pdf_url

    bucket_name = os.environ.get("R2_BUCKET_NAME", "myseattlesearch-assets")
    try:
        file_meta = drive_service.files().get(fileId=file_id, fields="name").execute()
        original_filename = file_meta.get('name', f'document-{pdf_index}.pdf').replace(" ", "-")
        if not original_filename.endswith(".pdf"): original_filename += ".pdf"
        
        r2_key = f"downloads/{mls_number}/{original_filename}"
        public_url = f"https://assets.myseattlesearch.com/{r2_key}"

        request = drive_service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
        fh.seek(0)
        r2_client.upload_fileobj(fh, bucket_name, r2_key, ExtraArgs={'ContentType': 'application/pdf'})
        return public_url
    except Exception as e:
        print(f"   ⚠️ PDF Extraction Failed for {mls_number} (PDF {pdf_index}): {e}")
        return pdf_url

def main():
    print("🌅 Running Daily Sheets Ingestion...")
    load_local_env()
    os.makedirs(DATA_DIR, exist_ok=True)
    editorials_dir = os.path.join(DATA_DIR, "editorials")
    os.makedirs(editorials_dir, exist_ok=True)
    r2_client = get_r2_client()

    master_sheet_id = os.environ.get("WEBSITE_DATA_CORE_SHEET_ID")
    creds_path = "credentials.json"
    if not master_sheet_id or not os.path.exists(creds_path):
        print("❌ Missing credentials or Sheet ID.")
        return

    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    sheets_service = build('sheets', 'v4', credentials=creds)
    docs_service = build('docs', 'v1', credentials=creds)
    drive_service = build('drive', 'v3', credentials=creds)

    tabs = ["Rates", "CityData", "Stats", "Professionals", "Sales", "Translations", "BoldPrint", "VideoLibrary", "AudioLibrary", "VideoChannels", "VideoChannelSchedules", "PublicEvents"]
    ranges = [f"{tab}!A:BK" for tab in tabs]
    res = sheets_service.spreadsheets().values().batchGet(spreadsheetId=master_sheet_id, ranges=ranges).execute()
    data = dict(zip(tabs, res.get('valueRanges', [])))
    sheet_writebacks = []

    # --- 1. Basic JSON Generations ---
    if data.get("Rates", {}).get('values'):
        with open(os.path.join(DATA_DIR, "hourly_rates.json"), "w", encoding="utf-8") as f:
            json.dump(parse_sheet_values(data["Rates"]['values']), f, indent=2, ensure_ascii=False)

    stats_rows = data.get("Stats", {}).get('values', [])
    if len(stats_rows) >= 2:
        stats_dict = {str(r[0]).strip(): (str(r[1]).strip() if len(r) > 1 and r[1] is not None else "") for r in stats_rows[1:] if r and str(r[0]).strip()}
        with open(os.path.join(DATA_DIR, "stats.json"), "w", encoding="utf-8") as f:
            json.dump(clean_nan_tokens(stats_dict), f, indent=2, ensure_ascii=False)

    # --- 2. CityData & Editorial Processing ---
    city_rows = data.get("CityData", {}).get('values', [])
    if city_rows and len(city_rows) >= 2:
        headers = [str(h).strip() for h in city_rows[0]]
        parsed_city_data = parse_sheet_values(city_rows)
        with open(CITY_DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(clean_nan_tokens(parsed_city_data), f, indent=2, ensure_ascii=False)

        col_status_idx = next((i for i, h in enumerate(headers) if h in ["EditorialStatus", "Editorial Status", "Editorial_Status"]), -1)
        for idx, r in enumerate(city_rows[1:]):
            padded = list(r) + [""] * (len(headers) - len(r))
            rec = dict(zip(headers, padded))
            city_name = rec.get("City", "").strip()
            if not city_name: continue
            slug = slugify(city_name)
            doc_url = rec.get("Editorial", "").strip()
            status = (rec.get("EditorialStatus") or rec.get("Editorial Status") or "").strip()

            if doc_url and is_google_drive_link(doc_url) and status.lower() == "pending":
                md_content = get_google_doc_as_markdown(docs_service, doc_url)
                if md_content and md_content.strip():
                    with open(os.path.join(editorials_dir, f"{slug}.md"), "w", encoding="utf-8") as f_md:
                        f_md.write(md_content)
                    if col_status_idx != -1:
                        sheet_writebacks.append({'range': f"CityData!{get_col_letter(col_status_idx)}{idx + 2}", 'values': [["Complete"]]})

    # --- 3. Sales Portfolio & R2 Multi-Asset Pipeline ---
    sales_rows = data.get("Sales", {}).get('values', [])
    if sales_rows:
        print("   📸 Processing Sales Records & Cloudflare Asset Pipeline...")
        headers = [h.strip() for h in sales_rows[0]]
        compiled_sales = []
        today_date = datetime.datetime.now().date()
        
        for idx, r in enumerate(sales_rows[1:]):
            padded = list(r) + [""] * (len(headers) - len(r))
            row_dict = dict(zip(headers, padded))
            mls_number = slugify(row_dict.get("MLS Number") or row_dict.get("mlsNumber") or f"listing-{idx}")

            if row_dict.get("Status", "").strip() != "Sold":
                s_date = row_dict.get("Selling Date")
                if s_date and str(s_date).strip():
                    try:
                        dt_obj = datetime.datetime.strptime(str(s_date).strip(), "%m/%d/%Y").date()
                        row_dict["DOM"] = max(0, (today_date - dt_obj).days)
                    except Exception: row_dict["DOM"] = "-"
            
            if r2_client:
                # 3a. Process Images
                for i in range(1, 6):
                    img_key = f"Image URL {i}"
                    raw_url = row_dict.get(img_key, "")
                    if raw_url and "assets.myseattlesearch.com" not in raw_url:
                        processed_url = process_and_upload_image(raw_url, mls_number, i, r2_client, drive_service)
                        if processed_url != raw_url:
                            row_dict[img_key] = processed_url
                            sheet_writebacks.append({'range': f"Sales!{get_col_letter(headers.index(img_key))}{idx + 2}", 'values': [[processed_url]]})

                # 3b. Process PDFs
                has_downloads = str(row_dict.get("Downloads", "")).strip().lower() == "yes"
                extracted_docs = []
                for i in range(1, 6):
                    pdf_key = f"PDF URL {i}"
                    raw_pdf = row_dict.get(pdf_key, "")
                    if raw_pdf:
                        processed_pdf = raw_pdf
                        if has_downloads and is_google_drive_link(raw_pdf):
                            processed_pdf = process_and_upload_pdf(raw_pdf, mls_number, i, r2_client, drive_service)
                            if processed_pdf != raw_pdf:
                                row_dict[pdf_key] = processed_pdf
                                sheet_writebacks.append({'range': f"Sales!{get_col_letter(headers.index(pdf_key))}{idx + 2}", 'values': [[processed_pdf]]})
                        
                        filename_guess = unquote(processed_pdf.split('/')[-1]).replace('-', ' ').replace('.pdf', '')
                        extracted_docs.append({"url": processed_pdf, "title": filename_guess})
                row_dict["pdfDownloads"] = extracted_docs

            compiled_sales.append(row_dict)
            
        with open(os.path.join(DATA_DIR, "sales.json"), "w", encoding="utf-8") as f:
            json.dump(clean_nan_tokens(compiled_sales), f, indent=2, ensure_ascii=False)

    # --- 4. Arrays & D1 Sync ---
    mappings = [("Professionals", "professionals.json"), ("Translations", "translations.json"), ("BoldPrint", "bold_print.json"), ("VideoLibrary", "video_library.json"), ("AudioLibrary", "audio_library.json"), ("VideoChannels", "video_channels.json"), ("VideoChannelSchedules", "video_channel_schedules.json"), ("PublicEvents", "public_events.json")]
    for tab_name, json_name in mappings:
        rows = data.get(tab_name, {}).get('values', [])
        if rows:
            parsed_records = parse_sheet_values(rows)
            with open(os.path.join(DATA_DIR, json_name), "w", encoding="utf-8") as f:
                json.dump(clean_nan_tokens(parsed_records), f, indent=2, ensure_ascii=False)
            if tab_name == "Professionals": sync_professionals_to_d1(parsed_records)

    if sheet_writebacks:
        try:
            print(f"   📝 Committing {len(sheet_writebacks)} asset URLs back to Google Sheets...")
            sheets_service.spreadsheets().values().batchUpdate(
                spreadsheetId=master_sheet_id,
                body={'valueInputOption': 'USER_ENTERED', 'data': sheet_writebacks}
            ).execute()
        except Exception as e:
            print(f"   ⚠️ Sheet writeback exception: {e}")

    print("✅ Daily Sheets Sync complete.")

if __name__ == "__main__":
    main()