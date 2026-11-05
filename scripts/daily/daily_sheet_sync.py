import os
import re
import json
import math
import datetime
import requests
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/documents.readonly'
]

def load_local_env():
    """Load development environment variables if running outside GitHub Actions."""
    for env_file in [".dev.vars", ".env"]:
        env_path = os.path.join(BASE_DIR, env_file)
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("\"'")
                        if k and k not in os.environ:
                            os.environ[k] = v
            except Exception:
                pass

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
    return "docs.google.com" in u or extract_google_id(url_string) is not None

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

def sync_professionals_to_d1(records):
    """Upserts normalized professional directory records into Cloudflare D1."""
    account_id = os.environ.get("CF_ACCOUNT_ID")
    database_id = os.environ.get("CF_DATABASE_CUSTOMERS_ID")
    api_token = os.environ.get("CF_D1_API_TOKEN") or os.environ.get("CF_API_TOKEN")

    if not account_id or not database_id or not api_token:
        print("   ⚠️ Cloudflare D1 credentials missing (CF_ACCOUNT_ID, CF_DATABASE_CUSTOMERS_ID, CF_D1_API_TOKEN). Skipping D1 sync.")
        return False

    def clean_val(v):
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None

    mapped_rows = []
    for rec in records:
        category = clean_val(rec.get("Category") or rec.get("category")) or "General"
        biz_name = clean_val(rec.get("Business/Vendor Name") or rec.get("business_name") or rec.get("Business Name")) or "Unknown Vendor"
        pro_id = clean_val(rec.get("ProID") or rec.get("pro_id"))
        if not pro_id:
            pro_id = f"{category}-{biz_name}".replace(" ", "-")

        phone = clean_val(rec.get("Phone Number") or rec.get("phone_number") or rec.get("Phone"))
        email = clean_val(rec.get("Email") or rec.get("email"))
        website = clean_val(rec.get("Website") or rec.get("website"))
        additional_info = clean_val(rec.get("Additional Info") or rec.get("additional_info") or rec.get("AdditionalInfo"))
        legal_req = clean_val(rec.get("Legal Requirements") or rec.get("legal_requirements"))
        legal_link = clean_val(rec.get("Legal Requirements Link") or rec.get("legal_requirements_link"))

        mapped_rows.append((
            pro_id,
            category,
            biz_name,
            phone,
            email,
            website,
            additional_info,
            legal_req,
            legal_link
        ))

    if not mapped_rows:
        return True

    endpoint = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{database_id}/query"
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json"
    }

    # Cloudflare D1 variable ceiling: maximum 100 bound parameters (?) per query.
    # 9 columns * 10 rows = 90 parameters, safely below the 100-variable ceiling.
    chunk_size = 10
    synced_count = 0

    for i in range(0, len(mapped_rows), chunk_size):
        chunk = mapped_rows[i:i + chunk_size]
        placeholders = ", ".join(["(?, ?, ?, ?, ?, ?, ?, ?, ?)"] * len(chunk))
        sql = f"""
            INSERT OR REPLACE INTO professionals (
                pro_id, category, business_name, phone_number, email,
                website, additional_info, legal_requirements, legal_requirements_link
            ) VALUES {placeholders};
        """
        flat_params = [item for row in chunk for item in row]

        try:
            res = requests.post(
                endpoint,
                headers=headers,
                json={"sql": sql, "params": flat_params},
                timeout=30
            )
            res_json = res.json()
            if res_json.get("success"):
                synced_count += len(chunk)
            else:
                print(f"   ❌ D1 Query Batch Error: {res_json.get('errors')}")
        except Exception as e:
            print(f"   ❌ D1 Network Error in batch {i // chunk_size + 1}: {e}")

    print(f"   ⚡ Synchronized {synced_count}/{len(mapped_rows)} vendors into D1 table 'professionals'.")
    return synced_count == len(mapped_rows)

def main():
    print("🌅 Running Daily Sheets Ingestion...")
    load_local_env()
    os.makedirs(DATA_DIR, exist_ok=True)
    editorials_dir = os.path.join(DATA_DIR, "editorials")
    os.makedirs(editorials_dir, exist_ok=True)

    master_sheet_id = os.environ.get("WEBSITE_DATA_CORE_SHEET_ID")
    creds_path = "credentials.json"
    if not master_sheet_id or not os.path.exists(creds_path):
        print("❌ Missing credentials or Sheet ID.")
        return

    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    sheets_service = build('sheets', 'v4', credentials=creds)
    docs_service = build('docs', 'v1', credentials=creds)

    tabs = [
        "Rates", "CityData", "Stats", "Professionals", "Sales",
        "Translations", "BoldPrint", "VideoLibrary", "AudioLibrary",
        "VideoChannels", "VideoChannelSchedules", "PublicEvents"
    ]
    ranges = [f"{tab}!A:BK" for tab in tabs]
    res = sheets_service.spreadsheets().values().batchGet(spreadsheetId=master_sheet_id, ranges=ranges).execute()
    data = dict(zip(tabs, res.get('valueRanges', [])))
    sheet_writebacks = []

    # Rates
    if data.get("Rates", {}).get('values'):
        with open(os.path.join(DATA_DIR, "hourly_rates.json"), "w", encoding="utf-8") as f:
            json.dump(parse_sheet_values(data["Rates"]['values']), f, indent=2, ensure_ascii=False)

    # CityData & Editorial Processing
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
            row_num = idx + 2
            city_name = rec.get("City", "").strip()
            if not city_name:
                continue

            slug = slugify(city_name)
            doc_url = rec.get("Editorial", "").strip()
            status = (rec.get("EditorialStatus") or rec.get("Editorial Status") or "").strip()

            if doc_url and is_google_drive_link(doc_url) and status.lower() == "pending":
                md_content = get_google_doc_as_markdown(docs_service, doc_url)
                if md_content and md_content.strip():
                    with open(os.path.join(editorials_dir, f"{slug}.md"), "w", encoding="utf-8") as f_md:
                        f_md.write(md_content)
                    if col_status_idx != -1:
                        sheet_writebacks.append({
                            'range': f"CityData!{get_col_letter(col_status_idx)}{row_num}",
                            'values': [["Complete"]]
                        })

    # Stats
    stats_rows = data.get("Stats", {}).get('values', [])
    if len(stats_rows) >= 2:
        stats_dict = {str(r[0]).strip(): (str(r[1]).strip() if len(r) > 1 and r[1] is not None else "") for r in stats_rows[1:] if r and str(r[0]).strip()}
        with open(os.path.join(DATA_DIR, "stats.json"), "w", encoding="utf-8") as f:
            json.dump(clean_nan_tokens(stats_dict), f, indent=2, ensure_ascii=False)

    # Sales & DOM
    sales_rows = data.get("Sales", {}).get('values', [])
    if sales_rows:
        headers = [h.strip() for h in sales_rows[0]]
        compiled_sales = []
        today_date = datetime.datetime.now().date()
        for r in sales_rows[1:]:
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
            json.dump(clean_nan_tokens(compiled_sales), f, indent=2, ensure_ascii=False)

    # Direct Array JSON Tabs & D1 Dual-Ingestion
    mappings = [
        ("Professionals", "professionals.json"),
        ("Translations", "translations.json"),
        ("BoldPrint", "bold_print.json"),
        ("VideoLibrary", "video_library.json"),
        ("AudioLibrary", "audio_library.json"),
        ("VideoChannels", "video_channels.json"),
        ("VideoChannelSchedules", "video_channel_schedules.json"),
        ("PublicEvents", "public_events.json")
    ]
    for tab_name, json_name in mappings:
        rows = data.get(tab_name, {}).get('values', [])
        if rows:
            parsed_records = parse_sheet_values(rows)
            with open(os.path.join(DATA_DIR, json_name), "w", encoding="utf-8") as f:
                json.dump(clean_nan_tokens(parsed_records), f, indent=2, ensure_ascii=False)
            
            if tab_name == "Professionals":
                sync_professionals_to_d1(parsed_records)

    if sheet_writebacks:
        try:
            sheets_service.spreadsheets().values().batchUpdate(
                spreadsheetId=master_sheet_id,
                body={'valueInputOption': 'USER_ENTERED', 'data': sheet_writebacks}
            ).execute()
        except Exception as e:
            print(f"   ⚠️ Sheet writeback notice: {e}")

    print("✅ Daily Sheets Sync complete.")

if __name__ == "__main__":
    main()