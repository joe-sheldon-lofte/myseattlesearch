# File: scripts/weekly/keep_alive_matrix.py
import os
import json
import time
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_FILE = os.path.join(BASE_DIR, "data", "matrix_keep_alive.json")

def main():
    print("🌐 Launching Matrix / OneHome Headless Keep-Alive Engine...")

    if not os.path.exists(DATA_FILE):
        print(f"ℹ️ Keep-alive configuration not found at {DATA_FILE}. Skipping ping routine.")
        return

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            records = json.load(f)
    except Exception as e:
        print(f"❌ Failed to parse {DATA_FILE}: {e}")
        return

    if not isinstance(records, list) or len(records) == 0:
        print("ℹ️ No portal URLs found in matrix_keep_alive.json. Exiting.")
        return

    # Filter entries that contain a non-empty URL string
    active_targets = []
    for r in records:
        url = (r.get("URL") or r.get("url") or "").strip()
        search_name = (r.get("Search") or r.get("search") or "Unnamed Search").strip()
        if url:
            active_targets.append({"name": search_name, "url": url})

    print(f"📋 Found {len(active_targets)} portal URLs to ping.")
    if not active_targets:
        return

    with sync_playwright() as p:
        # Launch headless Chromium
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()

        success_count = 0
        failure_count = 0

        for idx, target in enumerate(active_targets, start=1):
            name = target["name"]
            url = target["url"]
            print(f"[{idx}/{len(active_targets)}] Loading OneHome portal: {name}...")

            try:
                # Load page and allow DOM to parse
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                
                # Dwell time to allow the React SPA to hydrate and CoreLogic tracking beacons to fire
                time.sleep(7)
                
                print(f"   ✅ Successfully pinged: {name}")
                success_count += 1
            except Exception as err:
                print(f"   ⚠️ Navigation notice for '{name}' ({url}): {err}")
                failure_count += 1

        context.close()
        browser.close()

    print(f"\n🎉 OneHome Keep-Alive complete: {success_count} succeeded, {failure_count} notices.")

if __name__ == "__main__":
    main()