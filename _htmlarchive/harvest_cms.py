import os
import io
import re
import datetime
import requests
import urllib.parse
import boto3
import pandas as pd
from PIL import Image
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

def extract_google_id(url_string):
    """
    Safely extracts unique Google Drive or Doc file IDs from common URL architectures.
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

def apply_style(content, style_type, url=None):
    """
    Applies markdown styling markers to text content while keeping 
    surrounding structural whitespaces and newlines safe from syntax breaks.
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
    Uses the authenticated Agent profile to download a Google Doc, parse its rich styling 
    elements (bold, italics, headings, and hyper-links), and map them to clean Markdown.
    """
    doc_id = extract_google_id(doc_url)
    if not doc_id:
        return ""
    
    try:
        doc = docs_service.documents().get(documentId=doc_id).execute()
        body = doc.get('body', {})
        elements = body.get('content', [])
        markdown_text = []
        
        for element in elements:
            if 'paragraph' in element:
                paragraph = element['paragraph']
                paragraph_style = paragraph.get('paragraphStyle', {})
                named_style = paragraph_style.get('namedStyleType', 'NORMAL_TEXT')
                
                p_text = ""
                for p_element in paragraph.get('elements', []):
                    if 'textRun' in p_element:
                        text_run = p_element['textRun']
                        content = text_run.get('content', '')
                        style = text_run.get('textStyle', {})
                        
                        if style.get('bold'):
                            content = apply_style(content, 'bold')
                        if style.get('italic'):
                            content = apply_style(content, 'italic')
                        if 'link' in style and 'url' in style['link']:
                            content = apply_style(content, 'link', style['link']['url'])
                            
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
        print(f"   ⚠️ Warning: Could not parse Google Doc content for ID {doc_id}: {e}")
        return ""

def process_and_upload_image(drive_service, s3_client, r2_bucket, image_url, slug, index):
    """
    Downloads raw image assets from Drive, applies high-efficiency WebP 80% compression,
    and dispatches the optimized asset files directly to your Cloudflare R2 bucket.
    """
    file_id = extract_google_id(image_url)
    if not file_id:
        return image_url
        
    custom_domain = "https://assets.myseattlesearch.com"
    object_key = f"cms/{slug}-image-{index}.webp"
    permanent_url = f"{custom_domain}/{object_key}"
    
    try:
        request = drive_service.files().get_media(fileId=file_id)
        file_stream = io.BytesIO(request.execute())
        
        img = Image.open(file_stream)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGBA")
        else:
            img = img.convert("RGB")
            
        webp_buffer = io.BytesIO()
        img.save(webp_buffer, format="WEBP", quality=80)
        webp_buffer.seek(0)
        
        s3_client.put_object(
            Bucket=r2_bucket,
            Key=object_key,
            Body=webp_buffer,
            ContentType="image/webp"
        )
        print(f"   🚀 Asset successfully delivered to Cloudflare R2: {permanent_url}")
        return permanent_url
        
    except Exception as e:
        print(f"   ❌ Image optimization fault on ID {file_id}: {e}")
        return image_url

def main():
    print("🧠 Initializing MySeattleSearch Headless CMS Ingestion Engine...")
    posts_dir = "src/posts"
    os.makedirs(posts_dir, exist_ok=True)
    
    creds_path = "credentials.json"
    if not os.path.exists(creds_path):
        print("⚠️ Warning: credentials.json missing from root execution path. Skipping CMS fetch loop.")
        return
        
    # Open access scopes to allow data write-backs directly to your spreadsheet rows
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
        print(f"❌ Cloud Agent API initialization failed: {auth_err}")
        return
    
    r2_access_key = os.environ.get("R2_ACCESS_KEY_ID")
    r2_secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
    r2_endpoint = os.environ.get("R2_ENDPOINT_URL")
    r2_bucket = os.environ.get("R2_BUCKET_NAME")
    
    s3_client = None
    if all([r2_access_key, r2_secret_key, r2_endpoint, r2_bucket]):
        s3_client = boto3.client(
            "s3",
            endpoint_url=r2_endpoint,
            aws_access_key_id=r2_access_key,
            aws_secret_access_key=r2_secret_key,
            region_name="auto"
        )
    else:
        print("⚠️ Cloudflare R2 environment secrets missing. Image uploads will fallback to raw links.")

    spreadsheet_id = os.environ.get("CMS_SHEET_ID")
    if not spreadsheet_id:
        print("❌ Error: CMS_SHEET_ID missing from environment configuration vault.")
        return
        
    # Extended range to column X to prevent Image 5 URL from being truncated
    sheet_range = "Posts!A:X"
    try:
        sheet_result = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=sheet_range
        ).execute()
        rows = sheet_result.get('values', [])
    except Exception as err:
        print(f"❌ Failed to fetch parameter rows from Google Sheets API: {err}")
        return

    if not rows:
        print("⚠️ Spreadsheet targeted 'Posts' range contains zero data rows.")
        return
        
    headers = rows[0]
    data_records = []
    
    # Store exact row positions alongside metadata objects
    for idx, r in enumerate(rows[1:]):
        padded_row = r + [""] * (len(headers) - len(r))
        record_dict = dict(zip(headers, padded_row))
        record_dict["_row_num"] = idx + 2
        data_records.append(record_dict)
        
    batch_sheet_updates = []
    
    for record in data_records:
        slug = record.get("Content ID", "").strip()
        active_status = record.get("Active", "").strip().lower()
        row_num = record["_row_num"]
        
        if not slug:
            continue
            
        if active_status != "yes":
            target_path = os.path.join(posts_dir, f"{slug}.md")
            if os.path.exists(target_path):
                os.remove(target_path)
                print(f"🗑️ Kill-Switch Triggered: Deleted deactivated file asset: {slug}.md")
            continue
            
        print(f"📝 Sync Pass: Processing content row: [{slug}]...")
        
        optimized_images = []
        # Structural mapping coordinates for columns P, R, T, V, X
        col_letter_map = {1: 'P', 2: 'R', 3: 'T', 4: 'V', 5: 'X'}
        
        for i in range(1, 6):
            img_url = record.get(f"Image {i} URL", "").strip()
            
            # Stateless Cache: Immediately skip if already processed into your CDN bucket
            if img_url and "assets.myseattlesearch.com" in img_url:
                optimized_images.append(img_url)
            elif img_url and s3_client:
                # Optimize image and upload to Cloudflare R2
                r2_url = process_and_upload_image(drive_service, s3_client, r2_bucket, img_url, slug, i)
                optimized_images.append(r2_url)
                
                # Queue cell updates back to Google Sheet if upload is successful
                if r2_url.startswith("https://assets.myseattlesearch.com"):
                    col_letter = col_letter_map[i]
                    batch_sheet_updates.append({
                        'range': f"Posts!{col_letter}{row_num}",
                        'values': [[r2_url]]
                    })
            else:
                optimized_images.append(img_url)

        post_type = record.get("Type", "").strip()
        content_field = record.get("Content", "").strip()
        body_text = ""
        
        if post_type.lower() == "article" and "docs.google.com" in content_field:
            body_text = get_google_doc_as_markdown(docs_service, content_field)
        else:
            body_text = content_field

        raw_tags_field = record.get("Tags", "")
        clean_tags = [t.strip() for t in raw_tags_field.split(",") if t.strip()]
        formatted_tags_list = ", ".join([f'"{tag}"' for tag in clean_tags])
        
        markdown_filename = os.path.join(posts_dir, f"{slug}.md")
        
        # Clean structural properties to satisfy Python compiler specifications
        clean_title = record.get('Title', '').replace('"', '\\"')
        clean_headline = record.get('Headline', '').replace('"', '\\"')
        clean_subhead = record.get('Subhead', '').replace('"', '\\"')
        
        front_matter_block = (
f"""---
layout: post.njk
title: "{clean_title}"
headline: "{clean_headline}"
subhead: "{clean_subhead}"
date: {record.get('Publish Date', datetime.date.today().strftime('%Y-%m-%d'))}
author: "{record.get('Author', 'Joe Sheldon')}"
tags: [{formatted_tags_list}]
type: "{post_type}"
url_1_label: "{record.get('URL 1 Label', '')}"
url_1: "{record.get('URL 1', '')}"
url_2_label: "{record.get('URL 2 Label', '')}"
url_2: "{record.get('URL 2', '')}"
image_1: "{optimized_images[0]}"
image_2: "{optimized_images[1]}"
image_3: "{optimized_images[2]}"
image_4: "{optimized_images[3]}"
image_5: "{optimized_images[4]}"
---
{body_text}
""")
        
        with open(markdown_filename, "w", encoding="utf-8") as post_file:
            post_file.write(front_matter_block)
        print(f"   ✅ Static file generated successfully at: {markdown_filename}")
        
    # Execute batch update requests in a single transaction payload to respect quotas
    if batch_sheet_updates:
        print(f"   📝 Transmitting {len(batch_sheet_updates)} optimized CDN links back to Google Sheet ledger...")
        body = {
            'valueInputOption': 'USER_ENTERED',
            'data': batch_sheet_updates
        }
        sheets_service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id, body=body
        ).execute()
        print("   ✅ Spreadsheet synchronization complete.")
    else:
        print("   ✨ All image assets are already optimized. Spreadsheet write-back loop bypassed.")
        
    print("🏁 CMS Ingestion Routine Successfully Completed.")

if __name__ == "__main__":
    main()