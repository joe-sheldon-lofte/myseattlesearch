import os
import json
import re
import time
import datetime
import requests
import boto3
from PIL import Image
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
POSTS_DIR = os.path.join(BASE_DIR, "posts")

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

def publish_to_facebook(page_id, access_token, text, link=None, image_url=None):
    if not page_id or not access_token:
        return None
    try:
        if image_url:
            url = f"https://graph.facebook.com/v19.0/{page_id}/photos"
            payload = {"url": image_url, "caption": text, "access_token": access_token}
        else:
            url = f"https://graph.facebook.com/v19.0/{page_id}/feed"
            payload = {"message": text, "access_token": access_token}
            if link: payload["link"] = link

        res = requests.post(url, data=payload, timeout=15)
        res_data = res.json()
        if res.status_code == 200 and "id" in res_data:
            return res_data["id"]
    except Exception as e:
        print(f"   ❌ Facebook publish exception: {e}")
    return None

def publish_to_threads(user_id, access_token, text, image_url=None):
    if not user_id or not access_token:
        return None
    try:
        container_url = f"https://graph.threads.net/v1.0/{user_id}/threads"
        c_payload = {"media_type": "IMAGE" if image_url else "TEXT", "text": text, "access_token": access_token}
        if image_url: c_payload["image_url"] = image_url

        c_res = requests.post(container_url, data=c_payload, timeout=15).json()
        container_id = c_res.get("id")
        if not container_id: return None

        time.sleep(3)
        pub_url = f"https://graph.threads.net/v1.0/{user_id}/threads_publish"
        p_res = requests.post(pub_url, data={"creation_id": container_id, "access_token": access_token}, timeout=15).json()
        return p_res.get("id")
    except Exception as e:
        print(f"   ❌ Threads publish exception: {e}")
    return None

def publish_to_linkedin(author_urn, access_token, text, link=None, title=None):
    if not author_urn or not access_token:
        return None
    try:
        url = "https://api.linkedin.com/v2/posts"
        headers = {"Authorization": f"Bearer {access_token}", "X-Restli-Protocol-Version": "2.0.0", "Content-Type": "application/json"}
        payload = {
            "author": author_urn if author_urn.startswith("urn:li:") else f"urn:li:member:{author_urn}",
            "commentary": text, "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED"
        }
        if link: payload["content"] = {"article": {"source": link, "title": title or "Update"}}
        res = requests.post(url, headers=headers, json=payload, timeout=15)
        if res.status_code in (200, 201):
            return res.headers.get("x-restli-id") or res.json().get("id") or "published"
    except Exception as e:
        print(f"   ❌ LinkedIn publish exception: {e}")
    return None

def main():
    print("📰 Starting Headless CMS & Social Media Auto-Publisher...")
    os.makedirs(POSTS_DIR, exist_ok=True)

    cms_sheet_id = os.environ.get("CMS_SHEET_ID")
    if not cms_sheet_id:
        print("ℹ️ CMS_SHEET_ID not set. Skipping CMS generation.")
        return

    creds_path = "credentials.json"
    if not os.path.exists(creds_path):
        print("❌ credentials.json missing.")
        return

    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    sheets_service = build('sheets', 'v4', credentials=creds)
    docs_service = build('docs', 'v1', credentials=creds)

    writebacks = []
    res = sheets_service.spreadsheets().values().get(spreadsheetId=cms_sheet_id, range="Posts!A:AD").execute()
    rows = res.get('values', [])

    if not rows or len(rows) < 2:
        print("ℹ️ No CMS post rows found.")
        return

    headers = [str(h).strip() for h in rows[0]]
    col_map = {
        "active": headers.index("Active") if "Active" in headers else -1,
        "content_id": headers.index("Content ID") if "Content ID" in headers else -1,
        "title": headers.index("Title") if "Title" in headers else -1,
        "headline": headers.index("Headline") if "Headline" in headers else -1,
        "subhead": headers.index("Subhead") if "Subhead" in headers else -1,
        "content": headers.index("Content") if "Content" in headers else -1,
        "url_1": headers.index("URL 1") if "URL 1" in headers else -1,
        "fb_switch": headers.index("FB") if "FB" in headers else -1,
        "fb_id": headers.index("FB ID") if "FB ID" in headers else -1,
        "threads_switch": headers.index("Threads") if "Threads" in headers else -1,
        "threads_id": headers.index("Threads ID") if "Threads ID" in headers else -1,
        "li_switch": headers.index("LI") if "LI" in headers else -1,
        "li_id": headers.index("LI ID") if "LI ID" in headers else -1,
    }

    fb_page_id = os.environ.get("FB_PAGE_ID")
    fb_token = os.environ.get("FB_PAGE_ACCESS_TOKEN")
    threads_user_id = os.environ.get("THREADS_USER_ID")
    threads_token = os.environ.get("THREADS_ACCESS_TOKEN")
    li_author = os.environ.get("LINKEDIN_AUTHOR_URN")
    li_token = os.environ.get("LINKEDIN_ACCESS_TOKEN")

    for idx, r in enumerate(rows[1:]):
        row_num = idx + 2
        padded = list(r) + [""] * (len(headers) - len(r))
        def get_v(c_idx): return padded[c_idx].strip() if c_idx != -1 else ""

        if get_v(col_map["active"]).lower() != "yes":
            continue

        slug = get_v(col_map["content_id"])
        if not slug: continue

        title = get_v(col_map["title"])
        headline = get_v(col_map["headline"])
        subhead = get_v(col_map["subhead"])
        url_1 = get_v(col_map["url_1"])
        primary_text = headline or title

        # Execute Social Media Publishing
        post_text = f"{primary_text}\n\n{subhead}" if subhead else primary_text
        if url_1: post_text += f"\n\n{url_1}"

        if get_v(col_map["fb_switch"]).lower() == "yes" and not get_v(col_map["fb_id"]):
            pub_id = publish_to_facebook(fb_page_id, fb_token, post_text, link=url_1)
            if pub_id and col_map["fb_id"] != -1:
                writebacks.append({'range': f"Posts!{get_col_letter(col_map['fb_id'])}{row_num}", 'values': [[pub_id]]})

        if get_v(col_map["threads_switch"]).lower() == "yes" and not get_v(col_map["threads_id"]):
            pub_id = publish_to_threads(threads_user_id, threads_token, post_text)
            if pub_id and col_map["threads_id"] != -1:
                writebacks.append({'range': f"Posts!{get_col_letter(col_map['threads_id'])}{row_num}", 'values': [[pub_id]]})

        if get_v(col_map["li_switch"]).lower() == "yes" and not get_v(col_map["li_id"]):
            pub_id = publish_to_linkedin(li_author, li_token, post_text, link=url_1, title=primary_text)
            if pub_id and col_map["li_id"] != -1:
                writebacks.append({'range': f"Posts!{get_col_letter(col_map['li_id'])}{row_num}", 'values': [[pub_id]]})

    if writebacks:
        sheets_service.spreadsheets().values().batchUpdate(
            spreadsheetId=cms_sheet_id, body={'valueInputOption': 'USER_ENTERED', 'data': writebacks}
        ).execute()

    print("✅ CMS Posts & Social Publisher complete.")

if __name__ == "__main__":
    main()