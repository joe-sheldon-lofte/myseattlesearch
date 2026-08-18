
import os
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

MUNICIPAL_FEEDS_PATH = os.path.join(DATA_DIR, "municipal_feeds.json")
SITE_EVENTS_PATH = os.path.join(DATA_DIR, "events.json")
OUTPUT_CITY_EVENTS_PATH = os.path.join(DATA_DIR, "city_events.json")

def slugify(text):
    if not text:
        return ""
    text = str(text).lower().strip()
    out = [ch if ch.isalnum() else '-' for ch in text]
    res = "".join(out)
    while '--' in res:
        res = res.replace('--', '-')
    return res.strip('-')

def http_fetch_text(url, timeout=10):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"   ⚠️ Event feed fetch notice for {url}: {e}")
    return None

def parse_ical_feed(ics_text):
    events = []
    if not ics_text or "BEGIN:VCALENDAR" not in ics_text:
        return events

    raw_events = ics_text.split("BEGIN:VEVENT")
    for block in raw_events[1:]:
        summary_match = re.search(r'SUMMARY:(.*)', block)
        dtstart_match = re.search(r'DTSTART.*:(.*)', block)
        location_match = re.search(r'LOCATION:(.*)', block)
        url_match = re.search(r'URL:(.*)', block)

        title = summary_match.group(1).strip() if summary_match else None
        dt_str = dtstart_match.group(1).strip() if dtstart_match else None
        location = location_match.group(1).strip() if location_match else "Community Venue"
        link = url_match.group(1).strip() if url_match else "#"

        if title and dt_str:
            # Clean ICS date format YYYYMMDDTHHMMSSZ or YYYYMMDD
            clean_date = re.sub(r'[^0-9T]', '', dt_str)
            formatted_date = clean_date[:8] if len(clean_date) >= 8 else ""
            
            if len(formatted_date) == 8:
                year, month, day = formatted_date[:4], formatted_date[4:6], formatted_date[6:8]
                date_display = f"{year}-{month}-{day}"
                
                events.append({
                    "title": title.replace("\\", ""),
                    "date": date_display,
                    "time_location": f"{location.replace('\\', '')}",
                    "link": link,
                    "type": "Community Meeting",
                    "source": "Municipal Feed"
                })
    return events

def parse_rss_feed(xml_text):
    events = []
    if not xml_text:
        return events
    try:
        root = ET.fromstring(xml_text)
        # Search for RSS <item> or Atom <entry>
        for item in root.findall(".//item") + root.findall(".//{http://www.w3.org/2005/Atom}entry"):
            title = item.findtext("title") or item.findtext("{http://www.w3.org/2005/Atom}title")
            link = item.findtext("link") or item.findtext("{http://www.w3.org/2005/Atom}link") or "#"
            pub_date = item.findtext("pubDate") or item.findtext("{http://www.w3.org/2005/Atom}updated") or ""

            if title:
                events.append({
                    "title": title.strip(),
                    "date": pub_date.strip()[:16] if pub_date else "Upcoming",
                    "time_location": "Local City Venue",
                    "link": link.strip(),
                    "type": "Special Event",
                    "source": "City Feed"
                })
    except Exception as e:
        print(f"   ⚠️ XML parse notice: {e}")
    return events

def main():
    print("📅 Harvesting City & Site Events Feeds...")
    compiled_events = {}

    # 1. Ingest Site-Wide Personal Events
    site_events = []
    if os.path.exists(SITE_EVENTS_PATH):
        try:
            with open(SITE_EVENTS_PATH, "r", encoding="utf-8") as f:
                site_events = json.load(f)
                if not isinstance(site_events, list):
                    site_events = []
        except Exception as e:
            print(f"   ⚠️ events.json parse notice: {e}")

    # 2. Ingest Municipal Feeds from municipal_feeds.json
    if os.path.exists(MUNICIPAL_FEEDS_PATH):
        try:
            with open(MUNICIPAL_FEEDS_PATH, "r", encoding="utf-8") as f:
                muni_feeds = json.load(f)

            feed_list = muni_feeds if isinstance(muni_feeds, list) else list(muni_feeds.values())

            for feed_item in feed_list:
                city_name = feed_item.get("City") or feed_item.get("city") or feed_item.get("name") or ""
                feed_url = feed_item.get("Feed URL") or feed_item.get("Calendar URL") or feed_item.get("url") or ""
                
                if not city_name:
                    continue

                slug = slugify(city_name)
                if slug not in compiled_events:
                    compiled_events[slug] = []

                if feed_url and feed_url.startswith("http"):
                    raw_content = http_fetch_text(feed_url)
                    if raw_content:
                        if "VCALENDAR" in raw_content:
                            parsed = parse_ical_feed(raw_content)
                        else:
                            parsed = parse_rss_feed(raw_content)
                        compiled_events[slug].extend(parsed[:5])
        except Exception as e:
            print(f"   ⚠️ municipal_feeds.json processing notice: {e}")

    # Merge site events across all city feeds
    for slug in compiled_events:
        city_specific_site_events = [
            ev for ev in site_events 
            if slugify(ev.get("city", "")) == slug or ev.get("global") is True
        ]
        combined = city_specific_site_events + compiled_events[slug]
        
        # Deduplicate by title
        seen_titles = set()
        deduped = []
        for ev in combined:
            t = ev.get("title")
            if t and t not in seen_titles:
                seen_titles.add(t)
                deduped.append(ev)

        compiled_events[slug] = deduped[:5] # Keep top 5 upcoming events per city

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_CITY_EVENTS_PATH, "w", encoding="utf-8") as f:
        json.dump(compiled_events, f, indent=2, ensure_ascii=False)

    print(f"💾 Successfully compiled event calendars for {len(compiled_events)} cities.")

if __name__ == "__main__":
    main()
