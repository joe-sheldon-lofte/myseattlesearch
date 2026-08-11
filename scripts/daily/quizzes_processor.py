import os
import io
import json
import re
import requests
import boto3
from PIL import Image
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_PATH = os.path.join(DATA_DIR, "quizzes.json")

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets.readonly',
    'https://www.googleapis.com/auth/drive'
]

# R2 Environment Credentials
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY")
R2_ENDPOINT_URL = os.environ.get("R2_ENDPOINT_URL")
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME")

def get_google_services():
    creds_json = (
        os.environ.get("GA_GOOGLE_CREDENTIALS") or 
        os.environ.get("GOOGLE_CREDENTIALS") or 
        os.environ.get("GA_CREDENTIALS")
    )
    creds = None
    if creds_json and creds_json.strip():
        try:
            creds_dict = json.loads(creds_json)
            creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        except Exception as e:
            print(f"⚠️ Could not parse JSON credentials env var: {e}")

    if not creds and os.path.exists("credentials.json"):
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)

    if not creds:
        raise FileNotFoundError("Google service account credentials not found.")

    sheets = build('sheets', 'v4', credentials=creds)
    drive = build('drive', 'v3', credentials=creds)
    return sheets, drive

def get_r2_client():
    if all([R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ENDPOINT_URL, R2_BUCKET_NAME]):
        try:
            return boto3.client(
                "s3",
                endpoint_url=R2_ENDPOINT_URL,
                aws_access_key_id=R2_ACCESS_KEY_ID,
                aws_secret_access_key=R2_SECRET_ACCESS_KEY,
                region_name="auto"
            )
        except Exception as e:
            print(f"⚠️ R2 Client init error: {e}")
    return None

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
    return "drive.google.com" in u or "docs.google.com" in u or extract_google_id(url_string) is not None

def generate_url_slug(text_input):
    processed = str(text_input).lower().strip()
    processed = re.sub(r'[^a-z0-9\s-]', '', processed)
    return re.sub(r'[\s-]+', '-', processed)

def process_and_upload_image(drive_service, s3_client, image_url, folder_name, filename_slug, index=1):
    file_id = extract_google_id(image_url)
    if not file_id or not s3_client:
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
            Bucket=R2_BUCKET_NAME,
            Key=object_key,
            Body=webp_buffer,
            ContentType="image/webp"
        )
        print(f"   🚀 Quiz WebP uploaded to R2: {permanent_url}")

        try:
            drive_service.files().delete(fileId=file_id).execute()
        except Exception:
            pass

        return permanent_url
    except Exception as e:
        print(f"   ⚠️ Quiz image process notice: {e}")
        return image_url

def main():
    print("🎯 Starting Daily Polymorphic Quizzes Processor...")
    quiz_sheet_id = os.environ.get("QUIZZES_SHEET_ID")
    if not quiz_sheet_id:
        print("ℹ️ QUIZZES_SHEET_ID not set in secrets. Skipping quiz harvest.")
        return

    sheets_service, drive_service = get_google_services()
    s3_client = get_r2_client()

    res = sheets_service.spreadsheets().values().get(
        spreadsheetId=quiz_sheet_id, range="Quizzes!A:DB"
    ).execute()
    rows = res.get('values', [])

    if not rows or len(rows) < 2:
        print("ℹ️ No quiz records found in Quizzes tab.")
        return

    headers = [str(h).strip() for h in rows[0]]
    quizzes_db = {}

    for idx, r in enumerate(rows[1:]):
        padded = list(r) + [""] * (len(headers) - len(r))
        row_dict = dict(zip(headers, padded))
        quiz_id = row_dict.get("Quiz ID", "").strip()
        if not quiz_id:
            continue

        quiz_slug = generate_url_slug(row_dict.get("Quiz Name", "quiz"))
        cover_img = row_dict.get("Quiz Image", "").strip()
        if cover_img and is_google_drive_link(cover_img) and s3_client:
            cover_img = process_and_upload_image(drive_service, s3_client, cover_img, "Quizzes", quiz_slug, "cover")

        questions = []
        for i in range(1, 21):
            q_text = row_dict.get(f"Q{i} Text", "").strip()
            if q_text:
                questions.append({
                    "text": q_text,
                    "bucket": row_dict.get(f"Q{i} Bucket", "").strip()
                })

        routing = []
        for j in range(1, 11):
            r_url = row_dict.get(f"R{j} URL", "").strip()
            r_key = row_dict.get(f"R{j} Key", "").strip()
            if r_url and is_google_drive_link(r_url) and s3_client:
                r_url = process_and_upload_image(drive_service, s3_client, r_url, "Quizzes", f"{quiz_slug}-res-{j}")

            if r_key or r_url:
                routing.append({
                    "key": r_key,
                    "url": r_url,
                    "heading": row_dict.get(f"R{j} Heading", "").strip(),
                    "subheading": row_dict.get(f"R{j} Subheading", "").strip(),
                    "details": row_dict.get(f"R{j} Details", "").strip(),
                    "additionalDetails": row_dict.get(f"R{j} Additional Details", "").strip()
                })

        try:
            q_id_int = int(quiz_id)
        except ValueError:
            q_id_int = quiz_id

        try:
            rank_int = int(row_dict.get("Rank", "0").strip() or 0)
        except ValueError:
            rank_int = 0

        quizzes_db[str(quiz_id)] = {
            "id": q_id_int,
            "name": row_dict.get("Quiz Name", "").strip(),
            "webTitle": row_dict.get("Quiz Web Title", "").strip(),
            "introText": row_dict.get("Intro Text", "").strip(),
            "scoringType": row_dict.get("Scoring Type", "").strip(),
            "requiredFields": row_dict.get("Required Fields", "").strip(),
            "rank": rank_int,
            "quizImage": cover_img,
            "showInCatalog": row_dict.get("Show In Catalog", ""),
            "webhookUrl": row_dict.get("Webhook URL", ""),
            "emailSubject": row_dict.get("Email Subject", ""),
            "userTags": row_dict.get("User Tags", ""),
            "questions": questions,
            "routing": routing
        }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(quizzes_db, f, indent=4, ensure_ascii=False)

    print(f"✅ Saved {len(quizzes_db)} quizzes to {OUTPUT_PATH}")

if __name__ == "__main__":
    main()