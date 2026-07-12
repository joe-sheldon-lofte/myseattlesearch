# File: scripts/harvest_quizzes.py
import csv
import json
import requests
import os
import io
import re
import boto3
from PIL import Image

CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQONZjmRRou9IqJNV_ZY_8jp7y5pL0tDhuwEqZjCb5ShLhw8alckr2ukPGFD2o7ihJVyRP0gqZtuWkp/pub?gid=0&single=true&output=csv"
DATA_DIR = "data"
OUTPUT_FILE = os.path.join(DATA_DIR, "quizzes.json")

def convert_and_upload_to_r2(cell_value, sheet_name="Quizzes"):
    """
    Checks if a configuration cell contains a raw Google Drive asset link.
    Converts it to optimized WebP format, uploads it to Cloudflare R2, 
    and pings the Quiz Apps Script webhook to overwrite the cell.
    """
    if not isinstance(cell_value, str) or "drive.google.com" not in cell_value:
        return cell_value

    # Extract file ID string from standard share URLs
    match = re.search(r'/file/d/([a-zA-Z0-9_-]+)', cell_value)
    if not match:
        match = re.search(r'id=([a-zA-Z0-9_-]+)', cell_value)
    if not match:
        return cell_value

    file_id = match.group(1)
    
    # Retrieve environment variables from vault
    r2_access_key = os.environ.get("R2_ACCESS_KEY_ID")
    r2_secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
    r2_endpoint = os.environ.get("R2_ENDPOINT_URL")
    r2_bucket = os.environ.get("R2_BUCKET_NAME")
    sheets_api_url = os.environ.get("SHEETS_API_URL_QUIZZES")
    
    custom_domain = "https://assets.myseattlesearch.com"
    
    if not all([r2_access_key, r2_secret_key, r2_endpoint, r2_bucket]):
        print(f"⚠️ R2 environment secrets missing for Quizzes. Preserving original asset ID: {file_id}")
        return cell_value

    print(f"📸 Found Google Drive image in Quiz config (ID: {file_id}). Optimizing to WebP...")
    
    try:
        # 1. Stream file bytes from Google's delivery server
        download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
        download_response = requests.get(download_url, timeout=30)
        download_response.raise_for_status()
        
        # 2. Process image parameters using Pillow
        raw_image_bytes = io.BytesIO(download_response.content)
        processed_image = Image.open(raw_image_bytes)
        
        if processed_image.mode in ("RGBA", "P"):
            processed_image = processed_image.convert("RGBA")
        else:
            processed_image = processed_image.convert("RGB")
            
        # 3. Compress directly into byte block
        webp_byte_stream = io.BytesIO()
        processed_image.save(webp_byte_stream, format="WEBP", quality=80)
        webp_byte_stream.seek(0)
        
        # 4. Open connection channel to Cloudflare R2
        s3_client = boto3.client(
            "s3",
            endpoint_url=r2_endpoint,
            aws_access_key_id=r2_access_key,
            aws_secret_access_key=r2_secret_key,
            region_name="auto"
        )
        
        # Organizes under an explicit quizzes folder path inside the R2 asset bucket
        object_key = f"quizzes/{file_id}.webp"
        
        s3_client.put_object(
            Bucket=r2_bucket,
            Key=object_key,
            Body=webp_byte_stream,
            ContentType="image/webp"
        )
        
        permanent_r2_url = f"{custom_domain}/{object_key}"
        print(f"🚀 Quiz asset uploaded successfully to R2: {permanent_r2_url}")
        
        # 5. Handshake write-back to Google Sheet cells via our custom traffic cop router
        if sheets_api_url:
            print(f"✍️ Updating Quiz Google Sheet data cell...")
            writeback_payload = {
                "sheetName": sheet_name,
                "oldValue": cell_value,
                "newValue": permanent_r2_url
            }
            api_response = requests.post(sheets_api_url, json=writeback_payload, timeout=30)
            if api_response.status_code == 200:
                print(f"✅ Quiz Sheet cell successfully synchronized: {api_response.json().get('message')}")
            else:
                print(f"❌ Quiz API writeback returned error state: {api_response.status_code}")
        else:
            print("⚠️ SHEETS_API_URL_QUIZZES secret missing. Skipping cell update.")
            
        return permanent_r2_url
        
    except Exception as error_fault:
        print(f"❌ Image extraction failure on Quiz file ID {file_id}: {error_fault}")
        return cell_value

def harvest_quizzes():
    print("Initiating flat-column data harvest pull from Google Sheets...")
    response = requests.get(CSV_URL)
    if response.status_code != 200:
        raise Exception(f"Network endpoint unreachable. Status Code: {response.status_code}")
    
    response.encoding = 'utf-8'
    csv_text = response.text.splitlines()
    reader = csv.DictReader(csv_text)
    
    quizzes_db = {}
    
    for row in reader:
        quiz_id = row.get("Quiz ID", "").strip()
        if not quiz_id:
            continue
            
        print(f"Serializing Quiz ID: {quiz_id} - {row.get('Quiz Name')}")
        
        try:
            rank_value = int(row.get("Rank", "0").strip() or 0)
        except ValueError:
            rank_value = 0
        
        # Harvest Unrolled Questions
        questions = []
        for i in range(1, 21):
            q_text = row.get(f"Q{i} Text", "").strip()
            q_bucket = row.get(f"Q{i} Bucket", "").strip()
            if q_text:
                questions.append({
                    "text": q_text,
                    "bucket": q_bucket
                })
                
        # Harvest Unrolled Results Slots
        routing = []
        for j in range(1, 11):
            r_key = row.get(f"R{j} Key", "").strip()
            r_url = row.get(f"R{j} URL", "").strip()
            
            # Future proof result URLs if they reference drive links
            if r_url and "drive.google.com" in r_url:
                r_url = convert_and_upload_to_r2(r_url, "Quizzes")
                
            if r_key or r_url:
                routing.append({
                    "key": r_key,
                    "url": r_url,
                    "heading": row.get(f"R{j} Heading", "").strip(),
                    "subheading": row.get(f"R{j} Subheading", "").strip(),
                    "details": row.get(f"R{j} Details", "").strip(),
                    "additionalDetails": row.get(f"R{j} Additional Details", "").strip()
                })
        
        # Process the Quiz cover image property
        raw_quiz_image = row.get("Quiz Image", "").strip()
        optimized_quiz_image = convert_and_upload_to_r2(raw_quiz_image, "Quizzes")
                
        quizzes_db[quiz_id] = {
            "id": int(quiz_id),
            "name": row.get("Quiz Name", "").strip(),
            "webTitle": row.get("Quiz Web Title", "").strip(),
            "introText": row.get("Intro Text", "").strip(),
            "scoringType": row.get("Scoring Type", "").strip(),
            "requiredFields": row.get("Required Fields", "").strip(),
            "rank": rank_value,
            "quizImage": optimized_quiz_image, 
            "showInCatalog": row.get("Show In Catalog", "").strip(),
            "startDate": row.get("Start Date", "").strip(),
            "endDate": row.get("End Date", "").strip(),
            "webhookUrl": row.get("Webhook URL", "").strip(),
            "emailSubject": row.get("Email Subject", "").strip(),
            "userTags": row.get("User Tags", "").strip(),
            "questions": questions,
            "routing": routing
        }
        
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(quizzes_db, f, indent=4, ensure_ascii=False)
        
    print(f"Compilation finished! Local schema saved to: {OUTPUT_FILE}")

if __name__ == "__main__":
    harvest_quizzes()