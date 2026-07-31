# File: scripts/publish_social.py

import os
import json
import time
import requests
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


def get_sheets_service():
    """
    Authenticates using credentials.json in the root directory,
    matching the authentication pattern in harvest_hourly.py.
    """
    creds_path = "credentials.json"
    if not os.path.exists(creds_path):
        print(f"❌ Core Error: {creds_path} identity file is missing from root path.")
        return None

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]

    try:
        print("🔐 Authenticating Google Service Account via credentials.json...")
        creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
        return build("sheets", "v4", credentials=creds)
    except Exception as auth_err:
        print(f"❌ Cloud authorization handshake failed: {auth_err}")
        return None


def publish_to_facebook(page_id, access_token, text, link=None, image_url=None):
    """
    Publishes text, link attachments, or WebP images to the Facebook Page feed.
    """
    if not page_id or not access_token:
        print("   ⚠️ Facebook credentials missing. Skipping FB publish step.")
        return None

    try:
        if image_url:
            url = f"https://graph.facebook.com/v19.0/{page_id}/photos"
            payload = {
                "url": image_url,
                "caption": text,
                "access_token": access_token,
            }
        else:
            url = f"https://graph.facebook.com/v19.0/{page_id}/feed"
            payload = {"message": text, "access_token": access_token}
            if link:
                payload["link"] = link

        res = requests.post(url, data=payload, timeout=15)
        res_data = res.json()

        if res.status_code == 200 and "id" in res_data:
            post_id = res_data["id"]
            print(f"   ✅ Facebook post published successfully! Post ID: {post_id}")
            return post_id
        else:
            print(f"   ❌ Facebook API Error: {res_data}")
            return None
    except Exception as e:
        print(f"   ❌ Exception during Facebook publish: {e}")
        return None


def publish_to_threads(user_id, access_token, text, image_url=None):
    """
    Publishes via Meta Threads API two-stage container deployment pipeline.
    """
    if not user_id or not access_token:
        print("   ⚠️ Threads credentials missing. Skipping Threads publish step.")
        return None

    try:
        # Step 1: Create Container
        container_url = f"https://graph.threads.net/v1.0/{user_id}/threads"
        if image_url:
            c_payload = {
                "media_type": "IMAGE",
                "image_url": image_url,
                "text": text,
                "access_token": access_token,
            }
        else:
            c_payload = {
                "media_type": "TEXT",
                "text": text,
                "access_token": access_token,
            }

        c_res = requests.post(container_url, data=c_payload, timeout=15)
        c_data = c_res.json()
        container_id = c_data.get("id")

        if not container_id:
            print(f"   ❌ Threads Container Creation Error: {c_data}")
            return None

        time.sleep(3)  # Processing buffer for container registration

        # Step 2: Publish Container
        pub_url = f"https://graph.threads.net/v1.0/{user_id}/threads_publish"
        p_payload = {
            "creation_id": container_id,
            "access_token": access_token,
        }
        p_res = requests.post(pub_url, data=p_payload, timeout=15)
        p_data = p_res.json()
        post_id = p_data.get("id")

        if p_res.status_code == 200 and post_id:
            print(f"   ✅ Threads post published successfully! Thread ID: {post_id}")
            return post_id
        else:
            print(f"   ❌ Threads Publish Error: {p_data}")
            return None
    except Exception as e:
        print(f"   ❌ Exception during Threads publish: {e}")
        return None


def publish_to_linkedin(author_urn, access_token, text, link=None, title=None):
    """
    Publishes post or article payload to LinkedIn Posts API (v2).
    """
    if not author_urn or not access_token:
        print("   ⚠️ LinkedIn credentials missing. Skipping LinkedIn publish step.")
        return None

    try:
        url = "https://api.linkedin.com/v2/posts"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }

        payload = {
            "author": author_urn,
            "commentary": text,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
        }

        if link:
            payload["content"] = {
                "article": {
                    "source": link,
                    "title": title or "MySeattleSearch Update",
                }
            }

        res = requests.post(url, headers=headers, json=payload, timeout=15)
        if res.status_code in (200, 201):
            post_id = (
                res.headers.get("x-restli-id")
                or res.json().get("id")
                or "published"
            )
            print(f"   ✅ LinkedIn post published successfully! Post URN: {post_id}")
            return post_id
        else:
            print(f"   ❌ LinkedIn API Error ({res.status_code}): {res.text}")
            return None
    except Exception as e:
        print(f"   ❌ Exception during LinkedIn publish: {e}")
        return None


def main():
    print("🚀 Starting Social Media Auto-Publisher Engine...")

    sheets_service = get_sheets_service()
    if not sheets_service:
        return

    cms_sheet_id = os.environ.get("CMS_SHEET_ID")
    if not cms_sheet_id:
        print("❌ Core Error: CMS_SHEET_ID environment variable is missing.")
        return

    fb_page_id = os.environ.get("FB_PAGE_ID")
    fb_token = os.environ.get("FB_PAGE_ACCESS_TOKEN")
    threads_user_id = os.environ.get("THREADS_USER_ID")
    threads_token = os.environ.get("THREADS_ACCESS_TOKEN")
    li_author = os.environ.get("LINKEDIN_AUTHOR_URN")
    li_token = os.environ.get("LINKEDIN_ACCESS_TOKEN")

    try:
        print(f"📡 Scanning Content Workbook `{cms_sheet_id}` range `Posts!A:AD`...")
        res = (
            sheets_service.spreadsheets()
            .values()
            .get(spreadsheetId=cms_sheet_id, range="Posts!A:AD")
            .execute()
        )
        rows = res.get("values", [])

        if not rows or len(rows) < 2:
            print("ℹ️ No post records found in sheet.")
            return

        headers = [str(h).strip() for h in rows[0]]

        # Dynamic Column Mapping
        col_map = {
            "active": headers.index("Active") if "Active" in headers else -1,
            "title": headers.index("Title") if "Title" in headers else -1,
            "headline": headers.index("Headline") if "Headline" in headers else -1,
            "subhead": headers.index("Subhead") if "Subhead" in headers else -1,
            "content": headers.index("Content") if "Content" in headers else -1,
            "url_1": headers.index("URL 1") if "URL 1" in headers else -1,
            "img_1": headers.index("Image 1 URL") if "Image 1 URL" in headers else -1,
            "fb_switch": headers.index("FB") if "FB" in headers else -1,
            "fb_id": headers.index("FB ID") if "FB ID" in headers else -1,
            "threads_switch": headers.index("Threads") if "Threads" in headers else -1,
            "threads_id": headers.index("Threads ID") if "Threads ID" in headers else -1,
            "li_switch": headers.index("LI") if "LI" in headers else -1,
            "li_id": headers.index("LI ID") if "LI ID" in headers else -1,
        }

        writeback_updates = []

        for idx, row in enumerate(rows[1:]):
            row_num = idx + 2
            padded = list(row) + [""] * (len(headers) - len(row))

            def get_val(col_idx):
                return padded[col_idx].strip() if col_idx != -1 else ""

            active = get_val(col_map["active"]).lower()
            if active != "yes":
                continue

            title = get_val(col_map["title"])
            headline = get_val(col_map["headline"])
            subhead = get_val(col_map["subhead"])
            url_1 = get_val(col_map["url_1"])
            image_1 = get_val(col_map["img_1"])

            # Construct Post Text Payload
            primary_text = headline or title
            if not primary_text:
                continue

            post_text = primary_text
            if subhead:
                post_text += f"\n\n{subhead}"
            if url_1 and "docs.google.com" not in url_1:
                post_text += f"\n\n{url_1}"

            # 1. Facebook Publishing Sequence
            fb_sw = get_val(col_map["fb_switch"]).lower()
            fb_id_val = get_val(col_map["fb_id"])
            if fb_sw == "yes" and not fb_id_val:
                print(f"📢 [Row {row_num}] Publishing to Facebook: '{primary_text[:40]}...'")
                published_id = publish_to_facebook(
                    fb_page_id, fb_token, post_text, link=url_1, image_url=image_1
                )
                if published_id and col_map["fb_id"] != -1:
                    col_let = get_col_letter(col_map["fb_id"])
                    writeback_updates.append(
                        {
                            "range": f"Posts!{col_let}{row_num}",
                            "values": [[published_id]],
                        }
                    )

            # 2. Threads Publishing Sequence
            th_sw = get_val(col_map["threads_switch"]).lower()
            th_id_val = get_val(col_map["threads_id"])
            if th_sw == "yes" and not th_id_val:
                print(f"📢 [Row {row_num}] Publishing to Threads: '{primary_text[:40]}...'")
                published_id = publish_to_threads(
                    threads_user_id, threads_token, post_text, image_url=image_1
                )
                if published_id and col_map["threads_id"] != -1:
                    col_let = get_col_letter(col_map["threads_id"])
                    writeback_updates.append(
                        {
                            "range": f"Posts!{col_let}{row_num}",
                            "values": [[published_id]],
                        }
                    )

            # 3. LinkedIn Publishing Sequence
            li_sw = get_val(col_map["li_switch"]).lower()
            li_id_val = get_val(col_map["li_id"])
            if li_sw == "yes" and not li_id_val:
                print(f"📢 [Row {row_num}] Publishing to LinkedIn: '{primary_text[:40]}...'")
                published_id = publish_to_linkedin(
                    li_author, li_token, post_text, link=url_1, title=primary_text
                )
                if published_id and col_map["li_id"] != -1:
                    col_let = get_col_letter(col_map["li_id"])
                    writeback_updates.append(
                        {
                            "range": f"Posts!{col_let}{row_num}",
                            "values": [[published_id]],
                        }
                    )

        # Flush Cell Writebacks to Google Sheets (Matching Module 7 Pattern)
        if writeback_updates:
            print(
                f"📝 Executing unified cell data writeback pass ({len(writeback_updates)} updates) to Workbook ID: {cms_sheet_id}..."
            )
            sheets_service.spreadsheets().values().batchUpdate(
                spreadsheetId=cms_sheet_id,
                body={
                    "valueInputOption": "USER_ENTERED",
                    "data": writeback_updates,
                },
            ).execute()
            print("   ✅ Social Post ID cell writebacks successfully synchronized.")
        else:
            print("ℹ️ No pending social posts required cell writeback updates.")

    except Exception as err:
        print(f"❌ Critical error executing social publisher sequence: {err}")

    print("🏁 Social Media Auto-Publisher Sequence Complete.")


if __name__ == "__main__":
    main()