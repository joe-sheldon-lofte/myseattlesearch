# File: scripts/discover_city_feeds.py

import os
import json
import csv
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")
OUTPUT_CSV_PATH = os.path.join(DATA_DIR, "city_feeds_testing.csv")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

CSV_COLUMNS = [
    "City", "County", "School District", "Scope", "Category", 
    "Notes", "Feed Name", "Feed Format", "Valid", "Status Code", 
    "Feed URL", "Test Data"
]

def clean_text(text):
    if not text:
        return ""
    return re.sub(r'\s+', ' ', str(text)).strip()

def extract_sample_titles(content, feed_format):
    titles = []
    if not content:
        return ""

    if feed_format in ["rss", "xml"]:
        matches = re.findall(r'<title>(.*?)</title>', content, re.IGNORECASE | re.DOTALL)
        for m in matches:
            t = clean_text(re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', m))
            if t and not any(skip in t.lower() for skip in ["rss", "feed", "index", "home"]):
                titles.append(t)
            if len(titles) >= 3:
                break
    elif feed_format == "ical":
        matches = re.findall(r'SUMMARY:(.*?\r?\n)', content, re.IGNORECASE)
        for m in matches:
            t = clean_text(m)
            if t:
                titles.append(t)
            if len(titles) >= 3:
                break
    elif HAS_BS4:
        soup = BeautifulSoup(content, 'html.parser')
        for tag in soup.find_all(['h1', 'h2', 'h3', 'a', 'title']):
            t = clean_text(tag.get_text())
            if len(t) > 10 and t not in titles:
                titles.append(t)
            if len(titles) >= 3:
                break

    return " | ".join(titles[:3]) if titles else "Endpoint active (200 OK)"

def probe_url(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=6, allow_redirects=True)
        return resp.status_code, resp.text
    except Exception as e:
        return 0, str(e)

def discover_site_feeds(item, scope):
    discovered = []
    city = item.get("City", "").strip()
    county = item.get("County", "").strip()
    school_district = item.get("School District", "").strip()

    if scope == "city":
        base_url = item.get("City Website") or item.get("city_website") or item.get("City_Website") or ""
    elif scope == "school":
        base_url = item.get("School Website") or item.get("school_website") or item.get("School_Website") or ""
    else:
        base_url = item.get("County Website") or item.get("county_website") or item.get("County_Website") or ""

    if not base_url or not base_url.startswith("http"):
        return discovered

    base_url = base_url.rstrip("/")
    paths_to_check = [
        "",
        "/agendas",
        "/calendar",
        "/news",
        "/events",
        "/RSSFeed.aspx?ModID=1&MainCatID=1",
        "/Calendar-Feed"
    ]

    seen_urls = set()

    for path in paths_to_check:
        target_url = base_url + path if path else base_url
        if target_url in seen_urls:
            continue
        seen_urls.add(target_url)

        status_code, content = probe_url(target_url)
        if status_code != 200:
            continue

        # Check for RSS
        rss_matches = re.findall(r'href=["\']([^"\']*\.(?:rss|xml)|[^"\']*RSSFeed\.aspx[^"\']*)["\']', content, re.IGNORECASE)
        for rel_link in rss_matches:
            full_rss = urllib.parse.urljoin(target_url, rel_link)
            if full_rss not in seen_urls:
                seen_urls.add(full_rss)
                rss_status, rss_content = probe_url(full_rss)
                is_valid = "Yes" if rss_status == 200 else "No"
                samples = extract_sample_titles(rss_content, "rss") if rss_status == 200 else ""
                discovered.append({
                    "City": city,
                    "County": county,
                    "School District": school_district,
                    "Scope": scope,
                    "Category": "News Feed" if "news" in full_rss.lower() else "Municipal RSS",
                    "Notes": f"Auto-discovered via {path or 'homepage'}",
                    "Feed Name": f"{city} {scope.title()} RSS Feed",
                    "Feed Format": "rss",
                    "Valid": is_valid,
                    "Status Code": rss_status,
                    "Feed URL": full_rss,
                    "Test Data": samples
                })

        # Check for iCal
        ics_matches = re.findall(r'href=["\']([^"\']*\.(?:ics|ical)|[^"\']*Calendar-Feed[^"\']*)["\']', content, re.IGNORECASE)
        for rel_link in ics_matches:
            full_ics = urllib.parse.urljoin(target_url, rel_link)
            if full_ics not in seen_urls:
                seen_urls.add(full_ics)
                ics_status, ics_content = probe_url(full_ics)
                is_valid = "Yes" if ics_status == 200 else "No"
                samples = extract_sample_titles(ics_content, "ical") if ics_status == 200 else ""
                discovered.append({
                    "City": city,
                    "County": county,
                    "School District": school_district,
                    "Scope": scope,
                    "Category": "Calendar Feed",
                    "Notes": f"Auto-discovered iCal via {path or 'homepage'}",
                    "Feed Name": f"{city} {scope.title()} Calendar",
                    "Feed Format": "ical",
                    "Valid": is_valid,
                    "Status Code": ics_status,
                    "Feed URL": full_ics,
                    "Test Data": samples
                })

        # Check for Swagit
        swagit_matches = re.findall(r'swagit\.com/views/(\d+)', content, re.IGNORECASE)
        for view_id in set(swagit_matches):
            swagit_url = f"https://swagit.com/views/{view_id}"
            if swagit_url not in seen_urls:
                seen_urls.add(swagit_url)
                swagit_status, swagit_content = probe_url(swagit_url)
                is_valid = "Yes" if swagit_status == 200 else "No"
                samples = extract_sample_titles(swagit_content, "html") if swagit_status == 200 else ""
                discovered.append({
                    "City": city,
                    "County": county,
                    "School District": school_district,
                    "Scope": scope,
                    "Category": "Video Stream",
                    "Notes": f"Discovered Swagit view {view_id}",
                    "Feed Name": f"{city} Meeting Video Stream",
                    "Feed Format": "swagit",
                    "Valid": is_valid,
                    "Status Code": swagit_status,
                    "Feed URL": swagit_url,
                    "Test Data": samples
                })

        # Check for Granicus
        granicus_matches = re.findall(r'granicus\.com/[^"\']*view_id=(\d+)', content, re.IGNORECASE)
        for view_id in set(granicus_matches):
            granicus_url = target_url
            if granicus_url not in seen_urls:
                seen_urls.add(granicus_url)
                discovered.append({
                    "City": city,
                    "County": county,
                    "School District": school_district,
                    "Scope": scope,
                    "Category": "Video Stream",
                    "Notes": f"Discovered Granicus view_id={view_id}",
                    "Feed Name": f"{city} Granicus Meeting Stream",
                    "Feed Format": "granicus",
                    "Valid": "Yes" if status_code == 200 else "No",
                    "Status Code": status_code,
                    "Feed URL": target_url,
                    "Test Data": f"Granicus Player (View ID {view_id})"
                })

    return discovered

def process_city_data(item):
    results = []
    results.extend(discover_site_feeds(item, "city"))
    results.extend(discover_site_feeds(item, "school"))
    results.extend(discover_site_feeds(item, "county"))
    return results

def main():
    print("==================================================")
    print("      MUNICIPAL FEED AUTOMATED DISCOVERY TOOL     ")
    print("==================================================\n")

    if not os.path.exists(CITY_DATA_PATH):
        print(f"❌ Error: Could not find {CITY_DATA_PATH}")
        return

    with open(CITY_DATA_PATH, "r", encoding="utf-8") as f:
        city_records = json.load(f)

    print(f"📡 Loaded {len(city_records)} municipalities from city_data.json")
    print("🚀 Launching multithreaded discovery crawler...")

    all_discovered_feeds = []

    with ThreadPoolExecutor(max_workers=15) as executor:
        future_to_city = {executor.submit(process_city_data, item): item.get("City") for item in city_records}
        for future in as_completed(future_to_city):
            city_name = future_to_city[future]
            try:
                feeds = future.result()
                all_discovered_feeds.extend(feeds)
                print(f"  ✓ {city_name}: Found {len(feeds)} potential feed endpoints")
            except Exception as e:
                print(f"  ❌ {city_name}: Error during crawl - {e}")

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(all_discovered_feeds)

    print(f"\n🎉 Crawl complete! Saved {len(all_discovered_feeds)} feeds to {OUTPUT_CSV_PATH}")

if __name__ == "__main__":
    main()