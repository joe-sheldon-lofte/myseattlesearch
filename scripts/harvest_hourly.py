import os
import io
import json
import math
import re
import datetime
import ssl
import urllib.request
import urllib.parse
import requests
import feedparser
import boto3
import pandas as pd
from PIL import Image
from dateutil import parser
from zoneinfo import ZoneInfo
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

def get_col_letter(col_idx):
    """
    Translates a 0-indexed column integer into standard Google Sheets A-Z/AA-ZZ formatting coordinates.
    """
    result = ""
    col_idx += 1
    while col_idx > 0:
        remainder = (col_idx - 1) % 26
        result = chr(65 + remainder) + result
        col_idx = (col_idx - 1) // 26
    return result

def clean_nan_tokens(node):
    """
    Recursively purges standalone float NaN tokens into clean standard JSON null parameters.
    """
    if isinstance(node, dict):
        return {k: clean_nan_tokens(v) for k, v in node.items()}
    elif isinstance(node, list):
        return [clean_nan_tokens(element) for element in node]
    elif isinstance(node, float) and math.isnan(node):
        return None
    return node

def generate_url_slug(text_input):
    """
    Normalizes human names and titles into clean, URL-safe string tokens.
    """
    processed = str(text_input).lower().strip()
    processed = re.sub(r'[^a-z0-9\s-]', '', processed)
    return re.sub(r'[\s-]+', '-', processed)

def extract_google_id(url_string):
    """
    Safely extracts unique file IDs from standard Google Drive and Doc file URL paths.
    """
    if not isinstance(url_string, str):
        return None
    match = re.search(r'/d/([a-zA-Z0-9_-]+)', url_string)
    if match:
        return match.group(1)
    match = re.search(r'id=([a-zA-Z0-9_-]+)', url_string)
    if match:
        return match.group(1)
    return None

def apply_markdown_style(content, style_type, url=None):
    """
    Applies markdown text styling blocks while preserving structural white-space layouts.
    """
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
    """
    Converts rich Google Doc body copy structures into clean structural Markdown strings.
    """
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
        print(f"   ⚠️ Warning: Doc parsing fault on ID {doc_id}: {e}")
        return ""

def process_and_upload_image(drive_service, s3_client, r2_bucket, image_url, folder_name, filename_slug, index=1):
    """
    Downloads raw image files from Drive, compresses them to WebP, and pushes them to R2.
    """
    file_id = extract_google_id(image_url)
    if not file_id:
        return image_url
        
    custom_domain = "https://assets.myseattlesearch.com"
    object_key = f"{folder_name.lower()}/{filename_slug}-img-{index}.webp"
    permanent_url = f"{custom_domain}/{object_key}"
    
    try:
        request = drive_service.files().get_media(fileId=file_id)
        file_stream = io.BytesIO(request.execute())
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
        print(f"   🚀 WebP uploaded safely to R2 bucket path: {permanent_url}")
        return permanent_url
    except Exception as e:
        print(f"   ❌ Image optimization fallback triggered on ID {file_id}: {e}")
        return image_url

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

def main():
    print("🧠 Starting the MySeattleSearch Master Omnibus Data Engine...")
    data_dir = "data"
    posts_dir = "src/posts"
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(posts_dir, exist_ok=True)
    
    creds_path = "credentials.json"
    if not os.path.exists(creds_path):
        print("❌ Core Error: credentials.json identity file is missing from root path.")
        return
        
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/documents.readonly',
        'https://www.googleapis.com/auth/drive.readonly'
    ]
    
    try:
        creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
        sheets_service = build('sheets', 'v4', credentials=creds)
        docs_service = build('docs', 'v1', credentials=creds)
        drive_service = build('drive', 'v3', credentials=creds)
    except Exception as auth_err:
        print(f"❌ Core Error: Cloud authorization handshake failed: {auth_err}")
        return
        
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
    else:
        print("⚠️ Warning: R2 secrets missing. Image optimizations will default to original urls.")

    batch_sheet_writebacks = {}

    # ====================================================================
    # MODULE 1: COMMAND CENTER INGESTION (MARKET & INTEREST RATES)
    # ====================================================================
    cc_sheet_id = os.environ.get("COMMAND_CENTER_SHEET_ID")
    if cc_sheet_id:
        print("📡 Pulling market data and interest rates from Command Center Workbook...")
        try:
            cc_ranges = ["Market_Dashboard!A:Z", "Rates!A:Z"]
            cc_batch = sheets_service.spreadsheets().values().batchGet(
                spreadsheetId=cc_sheet_id, ranges=cc_ranges
            ).execute().get('valueRanges', [])
            
            market_rows = cc_batch[0].get('values', []) if len(cc_batch) > 0 else []
            rates_rows = cc_batch[1].get('values', []) if len(cc_batch) > 1 else []
            
            if market_rows:
                market_data = parse_sheet_values(market_rows)
                with open(os.path.join(data_dir, "hourly_market.json"), "w", encoding="utf-8") as f:
                    json.dump(market_data, f, indent=2, ensure_ascii=False)
            if rates_rows:
                rates_data = parse_sheet_values(rates_rows)
                with open(os.path.join(data_dir, "hourly_rates.json"), "w", encoding="utf-8") as f:
                    json.dump(rates_data, f, indent=2, ensure_ascii=False)
            print("   ✅ Command Center indices successfully synchronized.")
        except Exception as e:
            print(f"   ⚠️ Warning: Command Center download pass skipped: {e}")

    # ====================================================================
    # MODULE 2: WEBSITE DATA SHEET MULTI-TAB INGESTION
    # ====================================================================
    web_sheet_id = os.environ.get("WEBSITE_DATA_SHEET_ID")
    team_lookup = {}
    if web_sheet_id:
        print("📡 Ingesting multi-tab dataset from the Website Data Workbook...")
        target_tabs = ["Stats", "Team", "Disclaimers", "Events", "Celebrations", "DPA", "Professionals", "Reviews", "ThirdPartyPrograms", "News"]
        try:
            web_ranges = [f"{tab}!A:Z" for tab in target_tabs]
            web_batch = sheets_service.spreadsheets().values().batchGet(
                spreadsheetId=web_sheet_id, ranges=web_ranges
            ).execute().get('valueRanges', [])
            
            tabs_data = dict(zip(target_tabs, web_batch))
            batch_sheet_writebacks[web_sheet_id] = []

            # A. Process Team roster profiles first
            team_rows = tabs_data["Team"].get('values', [])
            if team_rows:
                headers = [h.strip() for h in team_rows[0]]
                photo_col_idx = headers.index("Photo") if "Photo" in headers else -1
                compiled_team = []
                for idx, r in enumerate(team_rows[1:]):
                    padded = list(r) + [""] * (len(headers) - len(r))
                    row_dict = dict(zip(headers, padded))
                    row_num = idx + 2
                    member_name = row_dict.get("Name", "").strip()
                    if not member_name: continue
                    slug = generate_url_slug(member_name)
                    photo_url = row_dict.get("Photo", "").strip()
                    if photo_url and "drive.google.com" in photo_url and s3_client:
                        r2_url = process_and_upload_image(drive_service, s3_client, r2_bucket, photo_url, "Team", slug)
                        if "assets.myseattlesearch.com" in r2_url:
                            row_dict["Photo"] = r2_url
                            batch_sheet_writebacks[web_sheet_id].append({
                                'range': f"Team!{get_col_letter(photo_col_idx)}{row_num}", 'values': [[r2_url]]
                            })
                    member_obj = {
                        "id": row_dict.get("Team ID", "").strip().replace(".0", ""),
                        "teamPage": row_dict.get("Team Page", "No").strip().lower() == "yes",
                        "position": row_dict.get("Position", "").strip(), "name": member_name, "slug": slug,
                        "phone": row_dict.get("Phone", "").strip(), "email": row_dict.get("Email", "").strip(),
                        "website": row_dict.get("Website", "").strip(), "description": row_dict.get("Description", "").strip(),
                        "photo": row_dict.get("Photo", "").strip()
                    }
                    team_lookup[member_obj["id"]] = member_obj
                    compiled_team.append(member_obj)
                with open(os.path.join(data_dir, "team.json"), "w", encoding="utf-8") as f:
                    json.dump(clean_nan_tokens(compiled_team), f, indent=2, ensure_ascii=False)

            # B. Process Personal Stats Row
            stats_rows = tabs_data["Stats"].get('values', [])
            if stats_rows:
                records = parse_sheet_values(stats_rows)
                with open(os.path.join(data_dir, "stats.json"), "w", encoding="utf-8") as f:
                    json.dump(clean_nan_tokens(records[0] if records else {}), f, indent=2, ensure_ascii=False)

            # C. Process Page Disclaimers
            disc_rows = tabs_data["Disclaimers"].get('values', [])
            if disc_rows:
                disc_map = {r[0].strip(): r[1].strip() for r in disc_rows[1:] if len(r) >= 2 and r[0].strip()}
                with open(os.path.join(data_dir, "disclaimers.json"), "w", encoding="utf-8") as f:
                    json.dump(clean_nan_tokens(disc_map), f, indent=2, ensure_ascii=False)

            # D. Process Events tab mapping
            event_rows = tabs_data["Events"].get('values', [])
            if event_rows:
                headers = [h.strip() for h in event_rows[0]]
                img_cols = [headers.index(f"Image {i} Link") for i in range(1, 4) if f"Image {i} Link" in headers]
                compiled_events = []
                for idx, r in enumerate(event_rows[1:]):
                    padded = list(r) + [""] * (len(headers) - len(r))
                    row_dict = dict(zip(headers, padded))
                    row_num = idx + 2
                    if row_dict.get("Status", "").strip().lower() != "active": continue
                    evt_id = row_dict.get("Event ID", "").strip().lower()
                    if not evt_id or evt_id == "nan": continue
                    
                    event_images = []
                    for c_idx in img_cols:
                        img_url = padded[c_idx].strip()
                        if img_url and "drive.google.com" in img_url and s3_client:
                            r2_url = process_and_upload_image(drive_service, s3_client, r2_bucket, img_url, "Events", f"{evt_id}-{c_idx}")
                            if "assets.myseattlesearch.com" in r2_url:
                                event_images.append(r2_url)
                                batch_sheet_writebacks[web_sheet_id].append({
                                    'range': f"Events!{get_col_letter(c_idx)}{row_num}", 'values': [[r2_url]]
                                })
                        elif img_url:
                            event_images.append(img_url)

                    hosts = [team_lookup[hid.strip()] for hid in row_dict.get("Host IDs", "").split(",") if hid.strip() in team_lookup]
                    city_val = row_dict.get("City", "").strip()
                    
                    cities_array = [city_val.lower()] if city_val and city_val.lower() != "nan" else []
                    if "edmonds" in cities_array or "lynnwood" in cities_array or "mountlake-terrace" in cities_array:
                        if "snohomish-county" not in cities_array:
                            cities_array.append("snohomish-county")

                    compiled_events.append({
                        "id": evt_id, "type": row_dict.get("Type", "Home Buying Class"), "status": "Active",
                        "title": row_dict.get("Title", ""), "subtitle": row_dict.get("Subtitle", None),
                        "date": row_dict.get("Date", ""), "startTime": row_dict.get("Start Time", ""), "endTime": row_dict.get("End Time", ""),
                        "locationName": row_dict.get("Location Name", ""), "streetAddress": row_dict.get("Street Address", ""), "city": city_val,
                        "cities": cities_array, "display": row_dict.get("Display", "Yes").lower() == "yes",
                        "registration": row_dict.get("Registration", "Yes").lower() == "yes", "legacyLink": row_dict.get("Link", ""),
                        "description": row_dict.get("Full Description", ""), "mapsLink": row_dict.get("Google Maps Link", ""),
                        "images": event_images, "hosts": hosts
                    })
                with open(os.path.join(data_dir, "events.json"), "w", encoding="utf-8") as f:
                    json.dump(clean_nan_tokens(compiled_events), f, indent=2, ensure_ascii=False)

            # E. Process Celebrations / Client Success tab
            cel_rows = tabs_data["Celebrations"].get('values', [])
            if cel_rows:
                records = parse_sheet_values(cel_rows)
                with open(os.path.join(data_dir, "celebrations.json"), "w", encoding="utf-8") as f:
                    json.dump(clean_nan_tokens(records), f, indent=2, ensure_ascii=False)

            # F. Process DPA Programs tab
            dpa_rows = tabs_data["DPA"].get('values', [])
            if dpa_rows:
                records = parse_sheet_values(dpa_rows)
                with open(os.path.join(data_dir, "dpa_programs.json"), "w", encoding="utf-8") as f:
                    json.dump(clean_nan_tokens(records), f, indent=2, ensure_ascii=False)

            # G. Process Preferred Professionals tab
            prof_rows = tabs_data["Professionals"].get('values', [])
            if prof_rows:
                records = parse_sheet_values(prof_rows)
                with open(os.path.join(data_dir, "professionals.json"), "w", encoding="utf-8") as f:
                    json.dump(clean_nan_tokens(records), f, indent=2, ensure_ascii=False)

            # H. Process Reviews Roster
            rev_rows = tabs_data["Reviews"].get('values', [])
            if rev_rows:
                records = parse_sheet_values(rev_rows)
                with open(os.path.join(data_dir, "reviews.json"), "w", encoding="utf-8") as f:
                    json.dump(clean_nan_tokens(records), f, indent=2, ensure_ascii=False)

            # I. Process Third Party Alternative Programs
            tpp_rows = tabs_data["ThirdPartyPrograms"].get('values', [])
            if tpp_rows:
                records = parse_sheet_values(tpp_rows)
                with open(os.path.join(data_dir, "thirdpartyprograms.json"), "w", encoding="utf-8") as f:
                    json.dump(clean_nan_tokens(records), f, indent=2, ensure_ascii=False)

            # J. Process News Sources Sheet
            news_rows = tabs_data["News"].get('values', [])
            if news_rows:
                records = parse_sheet_values(news_rows)
                with open(os.path.join(data_dir, "news.json"), "w", encoding="utf-8") as f:
                    json.dump(clean_nan_tokens(records), f, indent=2, ensure_ascii=False)

        except Exception as e:
            print(f"   ❌ Critical error compiling Website Data workbook: {e}")

    # ====================================================================
    # MODULE 3: CMS HEADLESS GENERATOR & EXPORT PATTERNS
    # ====================================================================
    cms_sheet_id = os.environ.get("CMS_SHEET_ID")
    if cms_sheet_id:
        print("📡 Accessing Headless CMS Content Workbook parameters...")
        try:
            batch_sheet_writebacks[cms_sheet_id] = []
            rows = sheets_service.spreadsheets().values().get(spreadsheetId=cms_sheet_id, range="Posts!A:X").execute().get('values', [])
            if rows:
                headers = rows[0]
                col_map = {i: headers.index(f"Image {i} URL") for i in range(1, 6) if f"Image {i} URL" in headers}
                for idx, r in enumerate(rows[1:]):
                    padded = list(r) + [""] * (len(headers) - len(r))
                    record = dict(zip(headers, padded))
                    row_num = idx + 2
                    slug = record.get("Content ID", "").strip()
                    if not slug: continue
                    if record.get("Active", "").strip().lower() != "yes":
                        target_md = os.path.join(posts_dir, f"{slug}.md")
                        if os.path.exists(target_md): os.remove(target_md)
                        continue
                        
                    optimized_images = []
                    for i in range(1, 6):
                        img_url = record.get(f"Image {i} URL", "").strip()
                        if img_url and "drive.google.com" in img_url and s3_client:
                            r2_url = process_and_upload_image(drive_service, s3_client, r2_bucket, img_url, "CMS", slug, i)
                            optimized_images.append(r2_url)
                            if "assets.myseattlesearch.com" in r2_url:
                                batch_sheet_writebacks[cms_sheet_id].append({
                                    'range': f"Posts!{get_col_letter(col_map[i])}{row_num}", 'values': [[r2_url]]
                                })
                        else:
                            optimized_images.append(img_url)
                            
                    post_type = record.get("Type", "").strip()
                    content_field = record.get("Content", "").strip()
                    body_text = get_google_doc_as_markdown(docs_service, content_field) if post_type.lower() == "article" and "docs.google.com" in content_field else content_field
                    
                    raw_tags = record.get("Tags", "")
                    tags_list = ", ".join([f'"{t.strip()}"' for t in raw_tags.split(",") if t.strip()])
                    
                    # Compute safe parameters outside the template expression string boundaries
                    clean_title = record.get('Title', '').replace('"', '\\"')
                    clean_headline = record.get('Headline', '').replace('"', '\\"')
                    clean_subhead = record.get('Subhead', '').replace('"', '\\"')
                    
                    front_matter = (
f"""---
layout: post.njk
title: "{clean_title}"
headline: "{clean_headline}"
subhead: "{clean_subhead}"
date: {record.get('Publish Date', datetime.date.today().strftime('%Y-%m-%d'))}
author: "{record.get('Author', 'Joe Sheldon')}"
tags: [{tags_list}]
type: "{post_type}"
url_1_label: "{record.get('URL 1 Label', '')}"
url_1: "{record.get('URL 1', '')}"
url_2_label: "{record.get('URL 2 Label', '')}"
url_2: "{record.get('URL 2', '')}"
image_1: "{optimized_images[0] if len(optimized_images) > 0 else ''}"
image_2: "{optimized_images[1] if len(optimized_images) > 1 else ''}"
image_3: "{optimized_images[2] if len(optimized_images) > 2 else ''}"
image_4: "{optimized_images[3] if len(optimized_images) > 3 else ''}"
image_5: "{optimized_images[4] if len(optimized_images) > 4 else ''}"
---
{body_text}
""")
                    with open(os.path.join(posts_dir, f"{slug}.md"), "w", encoding="utf-8") as f:
                        f.write(front_matter)
        except Exception as e:
            print(f"   ❌ Headless CMS module execution failure: {e}")

    # ====================================================================
    # MODULE 4: POLYMORPHIC QUIZZES PROCESSING LAYER
    # ====================================================================
    quiz_sheet_id = os.environ.get("QUIZZES_SHEET_ID")
    if quiz_sheet_id:
        print("📡 Accessing Polymorphic interactive lead assessments...")
        try:
            batch_sheet_writebacks[quiz_sheet_id] = []
            rows = sheets_service.spreadsheets().values().get(spreadsheetId=quiz_sheet_id, range="Quizzes!A:DB").execute().get('values', [])
            if rows:
                headers = rows[0]
                img_col_idx = headers.index("Quiz Image") if "Quiz Image" in headers else -1
                quizzes_db = {}
                
                for idx, r in enumerate(rows[1:]):
                    padded = list(r) + [""] * (len(headers) - len(r))
                    row_dict = dict(zip(headers, padded))
                    row_num = idx + 2
                    quiz_id = row_dict.get("Quiz ID", "").strip()
                    if not quiz_id: continue
                    
                    quiz_slug = generate_url_slug(row_dict.get("Quiz Name", "quiz"))
                    cover_img = row_dict.get("Quiz Image", "").strip()
                    if cover_img and "drive.google.com" in cover_img and s3_client:
                        r2_url = process_and_upload_image(drive_service, s3_client, r2_bucket, cover_img, "Quizzes", quiz_slug, "cover")
                        if "assets.myseattlesearch.com" in r2_url:
                            row_dict["Quiz Image"] = r2_url
                            batch_sheet_writebacks[quiz_sheet_id].append({
                                'range': f"Quizzes!{get_col_letter(img_col_idx)}{row_num}", 'values': [[r2_url]]
                            })
                            
                    questions = []
                    for i in range(1, 21):
                        q_text = row_dict.get(f"Q{i} Text", "").strip()
                        if q_text: questions.append({"text": q_text, "bucket": row_dict.get(f"Q{i} Bucket", "").strip()})
                        
                    routing = []
                    for j in range(1, 11):
                        r_url = row_dict.get(f"R{j} URL", "").strip()
                        r_key = row_dict.get(f"R{j} Key", "").strip()
                        if r_url and "drive.google.com" in r_url and s3_client:
                            r2_url = process_and_upload_image(drive_service, s3_client, r2_bucket, r_url, "Quizzes", f"{quiz_slug}-res-{j}")
                            if "assets.myseattlesearch.com" in r2_url:
                                r_url = r2_url
                                url_col_idx = headers.index(f"R{j} URL")
                                batch_sheet_writebacks[quiz_sheet_id].append({
                                    'range': f"Quizzes!{get_col_letter(url_col_idx)}{row_num}", 'values': [[r2_url]]
                                })
                        if r_key or r_url:
                            routing.append({
                                "key": r_key, "url": r_url, "heading": row_dict.get(f"R{j} Heading", "").strip(),
                                "subheading": row_dict.get(f"R{j} Subheading", "").strip(), "details": row_dict.get(f"R{j} Details", "").strip(),
                                "additionalDetails": row_dict.get(f"R{j} Additional Details", "").strip()
                            })
                    quizzes_db[quiz_id] = {
                        "id": int(quiz_id), "name": row_dict.get("Quiz Name", "").strip(), "webTitle": row_dict.get("Quiz Web Title", "").strip(),
                        "introText": row_dict.get("Intro Text", "").strip(), "scoringType": row_dict.get("Scoring Type", "").strip(),
                        "requiredFields": row_dict.get("Required Fields", "").strip(), "rank": int(row_dict.get("Rank", "0").strip() or 0),
                        "quizImage": row_dict.get("Quiz Image", ""), "showInCatalog": row_dict.get("Show In Catalog", ""),
                        "webhookUrl": row_dict.get("Webhook URL", ""), "emailSubject": row_dict.get("Email Subject", ""), "userTags": row_dict.get("User Tags", ""),
                        "questions": questions, "routing": routing
                    }
                with open(os.path.join(data_dir, "quizzes.json"), "w", encoding="utf-8") as f:
                    json.dump(quizzes_db, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"   ❌ Assessment processing fault: {e}")

    # ====================================================================
    # MODULE 5: ISOLATED 5-SEC TIMEOUT LOCAL RSS REAL ESTATE WIRE
    # ====================================================================
    news_config = os.path.join(data_dir, "news.json")
    if os.path.exists(news_config):
        print("📡 Starting isolated neighborhood news aggregator parsing pass...")
        try:
            with open(news_config, "r", encoding="utf-8") as f:
                sources = json.load(f)
            compiled_articles = []
            for src in sources:
                feed_name = src.get("Name", "Local Wire")
                rss_url = src.get("RSS Feed URL")
                if not rss_url: continue
                
                paywall_val = str(src.get("Paywall", "No")).strip()
                is_paywall = paywall_val.lower() == "yes"
                
                city_raw = src.get("City", "").strip()
                cities_array = [city_raw.lower()] if city_raw and city_raw.lower() != "nan" else []
                
                categories_array = [c.strip().lower().replace(" ", "-") for c in src.get("Categories", "").split(",") if c.strip()]
                
                if "north-sound" in categories_array and "snohomish-county" not in categories_array:
                    categories_array.append("snohomish-county")
                    
                try:
                    res = requests.get(rss_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
                    if res.status_code == 200:
                        feed = feedparser.parse(res.content)
                        for entry in feed.entries:
                            title = entry.get("title", "").strip()
                            link = entry.get("link", "").strip()
                            if not title or not link: continue
                            
                            excerpt = re.sub(r'<[^>]+>', '', entry.get("summary") or entry.get("description") or "")
                            excerpt = " ".join(excerpt.split())
                            if len(excerpt) > 220: excerpt = excerpt[:220] + "..."
                            
                            raw_date = entry.get("published") or entry.get("updated")
                            try:
                                p_dt = parser.parse(str(raw_date))
                                if p_dt.tzinfo is None: p_dt = p_dt.replace(tzinfo=ZoneInfo("UTC"))
                                p_local = p_dt.astimezone(ZoneInfo("America/Los_Angeles"))
                                pub_str = p_local.strftime("%a, %b %d, %Y at %I:%M %p")
                                sort_str = p_local.isoformat()
                            except:
                                now_pac = datetime.datetime.now(ZoneInfo("America/Los_Angeles"))
                                pub_str = now_pac.strftime("%a, %b %d, %Y at %I:%M %p")
                                sort_str = now_pac.isoformat()
                                
                            compiled_articles.append({
                                "source": feed_name, "title": title, "link": link,
                                "excerpt": excerpt if excerpt else "Click view details to read full update.",
                                "published": pub_str, 
                                "paywall": is_paywall,  # Output a standard boolean toggle (True/False)
                                "cities": cities_array, "categories": categories_array, "_iso": sort_str
                            })
                except Exception as e:
                    print(f"   ⚠️ Feed skip warning on '{feed_name}': {e}")
                    
            compiled_articles.sort(key=lambda x: x.get("_iso", ""), reverse=True)
            for a in compiled_articles: a.pop("_iso", None)
            with open(os.path.join(data_dir, "market_news.json"), "w", encoding="utf-8") as f:
                json.dump(compiled_articles[:200], f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"   ❌ News compilation halted: {e}")

    # ====================================================================
    # MODULE 6: CALIBRATE ACTIVE DAYS ON MARKET (DOM) INDICES
    # ====================================================================
    sales_file = os.path.join(data_dir, "sales.json")
    if os.path.exists(sales_file):
        print("📡 Calibrating active inventory Days on Market values...")
        try:
            with open(sales_file, "r", encoding="utf-8") as f:
                sales_data = json.load(f)
            if isinstance(sales_data, list):
                today_date = datetime.datetime.now().date()
                for item in sales_data:
                    if item.get("Status", "").strip() == "Sold": continue
                    s_date = item.get("Selling Date")
                    if s_date and str(s_date).strip():
                        try:
                            dt_obj = datetime.datetime.strptime(str(s_date).strip(), "%m/%d/%Y").date()
                            item["DOM"] = max(0, (today_date - dt_obj).days)
                        except: item["DOM"] = "-"
                    else: item["DOM"] = "-"
                with open(sales_file, "w", encoding="utf-8") as f:
                    json.dump(sales_data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"   ⚠️ Portfolio DOM sync pass bypassed: {e}")

    # ====================================================================
    # MODULE 7: FLUSH BULK CELL WRITEBACKS TO REUSE CDN URL FOOTPRINTS
    # ====================================================================
    for s_id, updates in batch_sheet_writebacks.items():
        if updates:
            print(f"📝 Executing unified cell data writeback pass to Workbook ID: {s_id}...")
            try:
                sheets_service.spreadsheets().values().batchUpdate(
                    spreadsheetId=s_id, body={'valueInputOption': 'USER_ENTERED', 'data': updates}
                ).execute()
            except Exception as write_err:
                print(f"   ⚠️ Sheet cells writeback bypass warning: {write_err}")

    # ====================================================================
    # MODULE 8: ACCURATE CLOUDFLARE R2 ACCOUNTING METRICS GENERATOR
    # ====================================================================
    out_dir = "_data"
    os.makedirs(out_dir, exist_ok=True)
    out_f = os.path.join(out_dir, "r2_storage.json")
    r2_payload = {"usedGB": "0.00", "usedBytes": 0, "lastChecked": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    if s3_client and r2_bucket:
        try:
            total_bytes = 0
            paginator = s3_client.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=r2_bucket):
                if 'Contents' in page:
                    for obj in page['Contents']: total_bytes += obj.get('Size', 0)
            r2_payload["usedGB"] = f"{(total_bytes / (1024 ** 3)):.2f}"
            r2_payload["usedBytes"] = total_bytes
        except: pass
    with open(out_f, "w", encoding="utf-8") as f: json.dump(r2_payload, f, indent=2)

    print("🏁 Real-Time Master Locomotive Processing Sequence Complete. Site data fresh.")

if __name__ == "__main__":
    main()