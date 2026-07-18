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

def load_git_cache_index():
    """
    Scans the local src/posts path to index existing markdown configurations.
    Enables high-performance smart bypass checks to protect API limits.
    """
    existing_slugs = set()
    posts_dir = "src/posts"
    if not os.path.exists(posts_dir):
        return existing_slugs
    
    for file_name in os.listdir(posts_dir):
        if file_name.endswith(".md"):
            slug = os.path.splitext(file_name)[0]
            existing_slugs.add(slug)
    return existing_slugs

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

def get_google_doc_body_text(docs_service, doc_url):
    """
    Uses the authenticated Google Docs API Agent profile to download and parse 
    document copy structural nodes into a clean plain text string block.
    """
    doc_id = extract_google_id(doc_url)
    if not doc_id:
        return ""
    
    try:
        doc = docs_service.documents().get(documentId=doc_id).execute()
        content = doc.get('body').get('content', [])
        text_lines = []
        
        for element in content:
            if 'paragraph' in element:
                elements = element.get('paragraph').get('elements', [])
                for text_run in elements:
                    if 'textRun' in text_run:
                        text_lines.append(text_run.get('textRun').get('content', ''))
        return "".join(text_lines)
    except Exception as e:
        print(f"⚠️ Error downloading Google Doc content for ID {doc_id}: {e}")
        return ""

def process_and_upload_image(drive_service, s3_client, r2_bucket, image_url, slug, index):
    """
    Downloads raw image assets from Drive, applies WebP compression metrics, 
    and transfers the optimized files directly to Cloudflare R2 bucket.
    """
    file_id = extract_google_id(image_url)
    if not file_id:
        return image_url # Fallback if not a Google Drive URL
        
    custom_domain = "https://assets.myseattlesearch.com"
    object_key = f"cms/{slug}-image-{index}.webp"
    permanent_url = f"{custom_domain}/{object_key}"
    
    try:
        # Request file data via Google Drive Binary Stream API
        request = drive_service.files().get_media(fileId=file_id)
        file_stream = io.BytesIO(request.execute())
        
        # Open via Pillow optimization frame layers
        img = Image.open(file_stream)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGBA")
        else:
            img = img.convert("RGB")
            
        # Convert and compress directly in memory
        webp_buffer = io.BytesIO()
        img.save(webp_buffer, format="WEBP", quality=80)
        webp_buffer.seek(0)
        
        # Dispatch file directly to Cloudflare infrastructure network tier
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
    
    # Target file paths
    posts_dir = "src/posts"
    os.makedirs(posts_dir, exist_ok=True)
    
    # 1. Credentials Authentication setup profiles
    creds_path = "credentials.json"
    if not os.path.exists(creds_path):
        print("❌ Error: credentials.json missing from environment root path. Operation aborted.")
        return
        
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets.readonly',
        'https://www.googleapis.com/auth/documents.readonly',
        'https://www.googleapis.com/auth/drive.readonly'
    ]
    
    creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
    sheets_service = build('sheets', 'v4', credentials=creds)
    docs_service = build('docs', 'v1', credentials=creds)
    drive_service = build('drive', 'v3', credentials=creds)
    
    # 2. Cloudflare API configuration layers
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
        print("⚠️ Cloudflare R2 environment parameters are missing. Image uploads will fallback.")

    # 3. Request Spreadsheet configuration
    spreadsheet_id = os.environ.get("GOOGLE_SPREADSHEET_ID", "YOUR_FALLBACK_SPREADSHEET_ID_HERE")
    sheet_range = "Posts!A:W" 
    
    try:
        sheet_result = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=sheet_range
        ).execute()
        rows = sheet_result.get('values', [])
    except Exception as err:
        print(f"❌ Failed to fetch parameters from Google Sheets API: {err}")
        return

    if not rows:
        print("⚠️ Spreadsheet targeted range contains zero data elements.")
        return
        
    # Extract headers and compile clean data records map
    headers = rows[0]
    data_records = []
    for r in rows[1:]:
        # Pad row array layout to match header boundaries safely
        padded_row = r + [""] * (len(headers) - len(r))
        data_records.append(dict(zip(headers, padded_row)))
        
    git_cache = load_git_cache_index()
    active_slugs = set()
    
    # Paywall verification tracking filters
    paywall_domains = ["seattletimes.com", "bizjournals.com", "djc.com", "heraldnet.com"]
    
    # 4. Core Parsing Synchronization Loop
    for record in data_records:
        slug = record.get("Content ID", "").strip()
        active_status = record.get("Active", "").strip().lower()
        
        if not slug:
            continue
            
        # Enforce remote workspace kill-switch configurations
        if active_status != "yes":
            target_path = os.path.join(posts_dir, f"{slug}.md")
            if os.path.exists(target_path):
                os.remove(target_path)
                print(f"🗑️ Kill-Switch Triggered: Deleted deactivated file asset: {slug}.md")
            continue
            
        active_slugs.add(slug)
        
        # SMART BYPASS ENGINE: Evaluate cache state
        if slug in git_cache:
            print(f"⚡ Cache Hit: Preserving updated static layout state for ID: {slug}")
            continue
            
        print(f"📝 Cache Miss: Ingesting new CMS post element node: [{slug}]...")
        
        # Image link compilation processing steps
        optimized_images = []
        for i in range(1, 6):
            img_url = record.get(f"Image {i} URL", "")
            if img_url and s3_client:
                print(f"   📷 Optimizing asset slot {i} for R2 Cloud network routing arrays...")
                r2_url = process_and_upload_image(drive_service, s3_client, r2_bucket, img_url, slug, i)
                optimized_images.append(r2_url)
            else:
                optimized_images.append(img_url)

        # Content parsing strategy filters
        post_type = record.get("Type", "").strip()
        content_field = record.get("Content", "").strip()
        body_text = ""
        
        if post_type.lower() == "article" and "docs.google.com" in content_field:
            print("   📄 Fetching written copy layers directly from Google Docs API infrastructure...")
            body_text = get_google_doc_body_text(docs_service, content_field)
        else:
            body_text = content_field # Use cell fallback text directly if not a document link

        # Enforce Dual-Tagging Overlap Policy
        raw_tags = [t.strip().lower() for t in record.get("Tags", "").split(",") if t.strip()]
        if "north-sound" in raw_tags and "snohomish-county" not in raw_tags:
            raw_tags.append("snohomish-county")
        formatted_tags = ", ".join(raw_tags)
        
        # Enforce Paywall Protection Detection Strategy
        is_paywalled = "false"
        combined_text_for_audit = f"{body_text} {record.get('URL 1', '')} {record.get('URL 2', '')}".lower()
        if any(domain in combined_text_for_audit for domain in paywall_domains):
            is_paywalled = "true"

        # 5. Compile Static Eleventy Production File Target
        markdown_filename = os.path.join(posts_dir, f"{slug}.md")
        
        # Enforce Token-Based styling metrics & Front-matter Rules explicitly
        front_matter_block = (
f"""---
layout: base.njk
title: "{record.get('Title', '').replace('"', '\\"')}"
headline: "{record.get('Headline', '').replace('"', '\\"')}"
subhead: "{record.get('Subhead', '').replace('"', '\\"')}"
date: {record.get('Publish Date', datetime.date.today().strftime('%Y-%m-%d'))}
author: "{record.get('Author', 'Joe Sheldon')}"
tags: [{formatted_tags}]
type: "{post_type}"
paywall: {is_paywalled}
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
        
        # Deliver compiled content directly to local project tree
        with open(markdown_filename, "w", encoding="utf-8") as post_file:
            post_file.write(front_matter_block)
        print(f"✅ Static page generated successfully at: {markdown_filename}")
        
    print("🏁 MySeattleSearch CMS Synchronization Engine Routine Completed.")

if __name__ == "__main__":
    main()