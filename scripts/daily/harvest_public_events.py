# File: scripts/daily/harvest_public_events.py

import os
import re
import json
import warnings
import datetime
import urllib3
import requests
import feedparser
from dateutil import parser
from dateutil.parser import UnknownTimezoneWarning
from zoneinfo import ZoneInfo

# Suppress timezone and SSL warnings
warnings.filterwarnings("ignore", category=UnknownTimezoneWarning)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(CURRENT_DIR) == "daily":
    REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
elif os.path.basename(CURRENT_DIR) == "scripts":
    REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
else:
    REPO_ROOT = os.path.abspath(CURRENT_DIR)

DATA_DIR = os.path.join(REPO_ROOT, "data")
PUBLIC_EVENTS_CONFIG = os.path.join(DATA_DIR, "public_events.json")
OUTPUT_PATH = os.path.join(DATA_DIR, "public_events_feed.json")

PACIFIC_TZ = ZoneInfo("America/Los_Angeles")

# High-fidelity browser headers to bypass Cloudflare WAF and satisfy DoStuff Media (HTTP 406) checks
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,application/json,text/calendar;q=0.8,*/*;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1"
}

TZINFOS = {
    "PST": ZoneInfo("America/Los_Angeles"),
    "PDT": ZoneInfo("America/Los_Angeles"),
    "MST": ZoneInfo("America/Denver"),
    "MDT": ZoneInfo("America/Denver"),
    "CST": ZoneInfo("America/Chicago"),
    "CDT": ZoneInfo("America/Chicago"),
    "EST": ZoneInfo("America/New_York"),
    "EDT": ZoneInfo("America/New_York"),
    "UTC": ZoneInfo("UTC"),
    "GMT": ZoneInfo("UTC")
}

# Regex to filter parking vouchers, ticket add-ons, and VIP passes
TICKETMASTER_JUNK_REGEX = re.compile(
    r'\b(parking|fast lane|club pass|vip access|amplified access|upgrade|not an event ticket|lounge access)\b',
    re.IGNORECASE
)

# Prevents small bar music gigs from dominating the feed
MAX_TICKETMASTER_MUSIC = 12

def clean_html(text):
    if not text:
        return ""
    cleaned = re.sub(r'<[^>]+>', '', str(text))
    return " ".join(cleaned.split()).strip()

def slugify(text):
    if not text:
        return ""
    text = str(text).lower().strip()
    return re.sub(r'[^a-z0-9]+', '-', text).strip('-')

def get_feed_limit(source_meta):
    raw_limit = source_meta.get("Limit") or source_meta.get("Max Events") or ""
    try:
        val = str(raw_limit).strip()
        if val and val.lower() != "nan":
            parsed = int(float(val))
            return parsed if parsed > 0 else None
    except (ValueError, TypeError):
        pass
    return None

def normalize_date(raw_date_str):
    if not raw_date_str:
        return None, None, None
    try:
        clean_str = str(raw_date_str).strip()
        dt = parser.parse(clean_str, tzinfos=TZINFOS)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=PACIFIC_TZ)
        dt_pacific = dt.astimezone(PACIFIC_TZ)
        display_date = dt_pacific.strftime("%A, %b %d, %Y")
        display_time = dt_pacific.strftime("%I:%M %p").lstrip("0")
        return dt_pacific, display_date, display_time
    except Exception:
        return None, None, None

def parse_ics_calendar(content, source_meta):
    events = []
    limit = get_feed_limit(source_meta)
    blocks = re.findall(r'BEGIN:VEVENT(.*?)END:VEVENT', content, re.DOTALL)
    
    for block in blocks:
        if limit is not None and len(events) >= limit:
            break

        summary_m = re.search(r'SUMMARY(?:;[^:]*)?:(.*)', block)
        title = summary_m.group(1).strip() if summary_m else ""
        if not title:
            continue

        desc_m = re.search(r'DESCRIPTION(?:;[^:]*)?:(.*)', block)
        excerpt = clean_html(desc_m.group(1))[:220] if desc_m else ""

        url_m = re.search(r'URL(?:;[^:]*)?:(.*)', block)
        link = url_m.group(1).strip() if url_m else source_meta.get("Feed", "")

        loc_m = re.search(r'LOCATION(?:;[^:]*)?:(.*)', block)
        location = loc_m.group(1).strip().replace('\\,', ',') if loc_m else ""

        start_m = re.search(r'DTSTART(?:;[^:]*)?:([0-9TZ]+)', block)
        raw_start = start_m.group(1).strip() if start_m else ""

        end_m = re.search(r'DTEND(?:;[^:]*)?:([0-9TZ]+)', block)
        raw_end = end_m.group(1).strip() if end_m else ""

        dt_pacific, d_date, d_time = normalize_date(raw_start)
        if not dt_pacific:
            continue

        _, end_d_date, end_d_time = normalize_date(raw_end)

        events.append({
            "source_id": source_meta.get("SourceID", ""),
            "source_name": source_meta.get("SourceName", ""),
            "title": title,
            "link": link,
            "excerpt": excerpt if excerpt else "View municipal event details.",
            "start_date": dt_pacific.isoformat(),
            "end_date": raw_end if raw_end else dt_pacific.isoformat(),
            "display_date": d_date,
            "display_time": f"{d_time} – {end_d_time}" if end_d_time and end_d_time != d_time else d_time,
            "location": location,
            "city": extract_city_tag(source_meta.get("Tags", "")),
            "is_all_day": "T" not in raw_start,
            "cost": "Free",
            "tags": [t.strip().lower() for t in source_meta.get("Tags", "").split(",") if t.strip()],
            "categories": [source_meta.get("SourceName", "")],
            "_dt": dt_pacific,
            "_venue": location or source_meta.get("SourceName", "")
        })
    return events

def parse_trumba_json(data, source_meta):
    events = []
    limit = get_feed_limit(source_meta)
    items = data if isinstance(data, list) else data.get("events", [])
    
    for item in items:
        if limit is not None and len(events) >= limit:
            break

        title = item.get("title", "").strip()
        link = item.get("permaLink") or item.get("webLink") or source_meta.get("Feed", "")
        if not title:
            continue

        excerpt = clean_html(item.get("description", ""))[:220]
        raw_start = item.get("startDateTime")
        raw_end = item.get("endDateTime")

        dt_pacific, d_date, d_time = normalize_date(raw_start)
        if not dt_pacific:
            continue

        _, _, end_d_time = normalize_date(raw_end)
        location = item.get("location") or ""
        city = extract_city_tag(source_meta.get("Tags", ""))

        events.append({
            "source_id": source_meta.get("SourceID", ""),
            "source_name": source_meta.get("SourceName", ""),
            "title": title,
            "link": link,
            "excerpt": excerpt if excerpt else "View municipal event calendar details.",
            "start_date": dt_pacific.isoformat(),
            "end_date": raw_end if raw_end else dt_pacific.isoformat(),
            "display_date": d_date,
            "display_time": f"{d_time} – {end_d_time}" if end_d_time and end_d_time != d_time else d_time,
            "location": location,
            "city": city,
            "is_all_day": item.get("allDay", False),
            "cost": "Free / Public",
            "tags": [t.strip().lower() for t in source_meta.get("Tags", "").split(",") if t.strip()],
            "categories": item.get("categoryArray", [source_meta.get("SourceName", "")]),
            "_dt": dt_pacific,
            "_venue": location or source_meta.get("SourceName", "")
        })
    return events

def parse_squarespace_json(data, source_meta):
    events = []
    limit = get_feed_limit(source_meta)
    
    # Resolves Squarespace list and collection formats (/cal?format=json)
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = (
            data.get("upcoming", []) or 
            data.get("items", []) or 
            (data.get("collection", {}).get("items", []) if isinstance(data.get("collection"), dict) else []) or 
            []
        )
    else:
        items = []
    
    for item in items:
        if limit is not None and len(events) >= limit:
            break

        title = item.get("title", "").strip()
        if not title:
            continue

        url_path = item.get("fullUrl", "")
        if url_path.startswith("/"):
            link = f"https://www.liveineverett.com{url_path}"
        elif url_path:
            link = url_path
        else:
            link = source_meta.get("Feed", "")

        excerpt = clean_html(item.get("excerpt") or item.get("body") or "")[:220]

        start_ts = item.get("startDate")
        end_ts = item.get("endDate")

        if isinstance(start_ts, (int, float)):
            dt_pacific = datetime.datetime.fromtimestamp(start_ts / 1000.0, tz=PACIFIC_TZ)
            d_date = dt_pacific.strftime("%A, %b %d, %Y")
            d_time = dt_pacific.strftime("%I:%M %p").lstrip("0")
        else:
            dt_pacific, d_date, d_time = normalize_date(start_ts)

        if not dt_pacific:
            continue

        end_d_time = ""
        if isinstance(end_ts, (int, float)):
            end_dt = datetime.datetime.fromtimestamp(end_ts / 1000.0, tz=PACIFIC_TZ)
            end_d_time = end_dt.strftime("%I:%M %p").lstrip("0")
        else:
            _, _, end_d_time = normalize_date(end_ts)

        loc_data = item.get("location", {})
        loc_str = ""
        if isinstance(loc_data, dict):
            loc_str = loc_data.get("addressTitle", "") or loc_data.get("addressLine1", "")
        elif isinstance(loc_data, str):
            loc_str = loc_data

        tags_raw = source_meta.get("Tags", "")
        tags_array = [t.strip().lower() for t in tags_raw.split(",") if t.strip()]
        if isinstance(item.get("tags"), list):
            tags_array.extend([slugify(t) for t in item["tags"]])

        events.append({
            "source_id": source_meta.get("SourceID", ""),
            "source_name": source_meta.get("SourceName", ""),
            "title": title,
            "link": link,
            "excerpt": excerpt if excerpt else "Explore local community event details.",
            "start_date": dt_pacific.isoformat(),
            "end_date": dt_pacific.isoformat(),
            "display_date": d_date,
            "display_time": f"{d_time} – {end_d_time}" if end_d_time and end_d_time != d_time else d_time,
            "location": loc_str if loc_str else "Everett, WA",
            "city": "everett",
            "is_all_day": False,
            "cost": "Community",
            "tags": list(set(tags_array)),
            "categories": item.get("categories", ["Local Events"]),
            "_dt": dt_pacific,
            "_venue": loc_str or "Everett"
        })
    return events

def parse_live_music_project_api(data, source_meta):
    events = []
    limit = get_feed_limit(source_meta)
    items = data if isinstance(data, list) else data.get("events", []) or data.get("results", [])
    
    for item in items:
        if limit is not None and len(events) >= limit:
            break

        title = item.get("title", "").strip()
        link = item.get("url") or item.get("event_url") or source_meta.get("Feed", "")
        if not title:
            continue

        excerpt = clean_html(item.get("description") or item.get("excerpt") or "")[:220]
        raw_start = item.get("start_time") or item.get("start_date") or item.get("starts_at")
        dt_pacific, d_date, d_time = normalize_date(raw_start)
        if not dt_pacific:
            continue

        venue = item.get("venue", {})
        loc_str = venue.get("name", "") if isinstance(venue, dict) else str(venue)
        city_str = venue.get("city", "seattle").lower() if isinstance(venue, dict) else "seattle"

        events.append({
            "source_id": source_meta.get("SourceID", ""),
            "source_name": source_meta.get("SourceName", ""),
            "title": title,
            "link": link,
            "excerpt": excerpt if excerpt else "Live regional musical performance.",
            "start_date": dt_pacific.isoformat(),
            "end_date": dt_pacific.isoformat(),
            "display_date": d_date,
            "display_time": d_time,
            "location": loc_str,
            "city": city_str,
            "is_all_day": False,
            "cost": item.get("price") or "Ticketed",
            "tags": ["music", "concerts", "live-music", "county-king"],
            "categories": item.get("genres", ["Classical", "Live Music"]),
            "_dt": dt_pacific,
            "_venue": loc_str
        })
    return events

def harvest_ticketmaster_events(api_key, source_meta):
    if not api_key:
        print("   ℹ️ TICKETMASTER_API_KEY missing. Gracefully skipping Ticketmaster Discovery.")
        return []

    events = []
    limit = get_feed_limit(source_meta) or 60

    endpoint = "https://app.ticketmaster.com/discovery/v2/events.json"
    params = {
        "apikey": api_key,
        "latlong": "47.7000,-122.2500",  # Centroid: North Lake Washington / Kirkland
        "radius": "35",
        "unit": "miles",
        "classificationName": "Arts & Theatre,Fairs & Festivals,Family,Music",
        "size": "100",
        "sort": "date,asc"
    }

    try:
        res = requests.get(endpoint, params=params, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            payload = res.json()
            items = payload.get("_embedded", {}).get("events", [])
            music_count = 0

            for item in items:
                if len(events) >= limit:
                    break

                title = item.get("name", "").strip()
                link = item.get("url", "")
                if not title or not link:
                    continue

                if TICKETMASTER_JUNK_REGEX.search(title):
                    continue

                classifications = item.get("classifications", [])
                segment = classifications[0].get("segment", {}).get("name", "") if classifications else ""
                genre = classifications[0].get("genre", {}).get("name", "") if classifications else ""
                is_family_bool = bool(classifications[0].get("family", False)) if classifications else False

                if segment in ["Sports", "Film"]:
                    continue

                if segment == "Music":
                    if music_count >= MAX_TICKETMASTER_MUSIC:
                        continue
                    music_count += 1

                dates_data = item.get("dates", {})
                start_data = dates_data.get("start", {})
                raw_datetime = start_data.get("dateTime") or start_data.get("localDate")
                dt_pacific, d_date, d_time = normalize_date(raw_datetime)
                if not dt_pacific:
                    continue

                venue_list = item.get("_embedded", {}).get("venues", [])
                venue = venue_list[0] if venue_list else {}
                loc_name = venue.get("name", "")
                city_name = venue.get("city", {}).get("name", "Seattle").lower()

                tags = ["entertainment", "major-events", "tickets"]
                if segment:
                    tags.append(slugify(segment))
                if genre:
                    tags.append(slugify(genre))
                if is_family_bool or segment.lower() == "family":
                    tags.extend(["family-friendly", "all-ages"])

                events.append({
                    "source_id": source_meta.get("SourceID", "pe-10"),
                    "source_name": "Ticketmaster Discovery",
                    "title": title,
                    "link": link,
                    "excerpt": f"{segment} — {genre} live at {loc_name}." if genre else f"{segment} live at {loc_name}.",
                    "start_date": dt_pacific.isoformat(),
                    "end_date": dt_pacific.isoformat(),
                    "display_date": d_date,
                    "display_time": d_time,
                    "location": f"{loc_name}, {city_name.title()}",
                    "city": city_name,
                    "is_all_day": False,
                    "cost": "Ticketed",
                    "tags": list(set(tags)),
                    "categories": [segment, genre] if genre else [segment],
                    "_dt": dt_pacific,
                    "_venue": loc_name
                })
        else:
            print(f"   ⚠️ Ticketmaster API notice: HTTP {res.status_code}")
    except Exception as e:
        print(f"   ⚠️ Ticketmaster harvesting notice: {e}")

    return events

def parse_bibliocommons_html_fallback(html_content, source_meta):
    """Fallback parser for BiblioCommons (KCLS / Sno-Isle) library event schedules."""
    events = []
    limit = get_feed_limit(source_meta) or 25
    now_pacific = datetime.datetime.now(PACIFIC_TZ)

    # Identifies BiblioCommons event search blocks
    raw_blocks = re.findall(
        r'<div[^>]*class="[^"]*bc-event[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</div>',
        html_content,
        re.DOTALL
    ) or re.findall(r'<li[^>]*class="[^"]*event-item[^"]*"[^>]*>(.*?)</li>', html_content, re.DOTALL)

    for block in raw_blocks:
        if len(events) >= limit:
            break

        title_m = re.search(r'<a[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</a>', block, re.DOTALL) or re.search(r'<h[234][^>]*>(.*?)</h[234]>', block, re.DOTALL)
        if not title_m:
            continue
        title = clean_html(title_m.group(1))

        link_m = re.search(r'href="([^"]+)"', block)
        raw_link = link_m.group(1) if link_m else ""
        if raw_link.startswith("/"):
            domain = "https://kcls.bibliocommons.com" if "kcls" in source_meta.get("Feed", "") else "https://sno-isle.bibliocommons.com"
            link = f"{domain}{raw_link}"
        else:
            link = raw_link or source_meta.get("Feed", "")

        dt_pacific = extract_date_from_text(block, now_pacific)
        if not dt_pacific:
            continue

        d_date = dt_pacific.strftime("%A, %b %d, %Y")
        d_time = dt_pacific.strftime("%I:%M %p").lstrip("0")

        loc_m = re.search(r'<span[^>]*class="[^"]*location[^"]*"[^>]*>(.*?)</span>', block, re.DOTALL)
        location_str = clean_html(loc_m.group(1)) if loc_m else source_meta.get("SourceName", "Library")

        tags_raw = source_meta.get("Tags", "")
        tags_array = [t.strip().lower() for t in tags_raw.split(",") if t.strip()]
        if any(w in title.lower() for w in ["story", "toddler", "kids", "family", "lego", "craft"]):
            tags_array.extend(["family-friendly", "all-ages"])

        events.append({
            "source_id": source_meta.get("SourceID", ""),
            "source_name": source_meta.get("SourceName", ""),
            "title": title,
            "link": link,
            "excerpt": f"Library program at {location_str}.",
            "start_date": dt_pacific.isoformat(),
            "end_date": dt_pacific.isoformat(),
            "display_date": d_date,
            "display_time": d_time,
            "location": location_str,
            "city": extract_city_tag(source_meta.get("Tags", "")),
            "is_all_day": False,
            "cost": "Free",
            "tags": list(set(tags_array)),
            "categories": ["Library", "Community"],
            "_dt": dt_pacific,
            "_venue": location_str
        })
    return events

def parse_rss_feed(content, source_meta):
    events = []
    limit = get_feed_limit(source_meta)
    
    feed = feedparser.parse(content)
    now_pacific = datetime.datetime.now(PACIFIC_TZ)
    
    # Check if BiblioCommons returned an HTML page instead of parseable RSS entries
    if "bibliocommons" in source_meta.get("Feed", "").lower() and len(feed.entries) == 0:
        return parse_bibliocommons_html_fallback(content.decode("utf-8", errors="ignore"), source_meta)

    entries = feed.entries if limit is None else feed.entries[:limit]
    
    for entry in entries:
        title = entry.get("title", "").strip()
        link = entry.get("link", "").strip()
        if not title or not link:
            continue

        raw_event_date = (
            entry.get("bc_start_date") or 
            entry.get("bc_event_date") or 
            entry.get("ev_startdate") or 
            entry.get("event_start_date") or 
            entry.get("start_date") or 
            entry.get("x-trumba_dtstart") or 
            entry.get("dc_date") or 
            entry.get("date")
        )

        if raw_event_date:
            dt_pacific, d_date, d_time = normalize_date(raw_event_date)
        else:
            raw_pub_date = entry.get("published") or entry.get("updated")
            dt_pacific, d_date, d_time = normalize_date(raw_pub_date)
            
            # Scans text for upcoming date patterns if publication date is in the past
            if dt_pacific and dt_pacific < now_pacific:
                text_to_search = f"{title} {entry.get('summary', '')} {entry.get('description', '')}"
                found_dt = extract_date_from_text(text_to_search, now_pacific)
                if found_dt:
                    dt_pacific = found_dt
                    d_date = dt_pacific.strftime("%A, %b %d, %Y")
                    d_time = dt_pacific.strftime("%I:%M %p").lstrip("0")
                else:
                    if "/event" in source_meta.get("Feed", "").lower() or "calendar" in source_meta.get("Feed", "").lower():
                        dt_pacific = now_pacific + datetime.timedelta(days=2)
                        d_date = dt_pacific.strftime("%A, %b %d, %Y")
                        d_time = "Community Event"

        if not dt_pacific:
            continue

        excerpt = clean_html(entry.get("summary") or entry.get("description") or "")[:220]
        city_tag = extract_city_tag(source_meta.get("Tags", ""))

        tags_raw = source_meta.get("Tags", "")
        tags_array = [t.strip().lower() for t in tags_raw.split(",") if t.strip()]

        location_str = entry.get("bc_location") or entry.get("location") or source_meta.get("SourceName", "")

        if any(w in (title + " " + excerpt).lower() for w in ["kids", "family", "children", "story time", "all ages", "preschool", "toddler"]):
            tags_array.extend(["family-friendly", "all-ages"])

        events.append({
            "source_id": source_meta.get("SourceID", ""),
            "source_name": source_meta.get("SourceName", ""),
            "title": title,
            "link": link,
            "excerpt": excerpt if excerpt else f"Community event hosted by {source_meta.get('SourceName', 'Local Organizer')}.",
            "start_date": dt_pacific.isoformat(),
            "end_date": dt_pacific.isoformat(),
            "display_date": d_date,
            "display_time": d_time,
            "location": location_str,
            "city": city_tag,
            "is_all_day": False,
            "cost": "Public / Community",
            "tags": list(set(tags_array)),
            "categories": [source_meta.get("SourceName", "")],
            "_dt": dt_pacific,
            "_venue": location_str
        })
    return events

def extract_date_from_text(text, fallback_now):
    match = re.search(r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+([0-9]{1,2})\b', text, re.IGNORECASE)
    if match:
        month_str, day_str = match.groups()
        try:
            date_candidate = parser.parse(f"{month_str} {day_str}, {fallback_now.year}", tzinfos=TZINFOS)
            date_candidate = date_candidate.replace(tzinfo=PACIFIC_TZ)
            if date_candidate >= fallback_now - datetime.timedelta(days=1):
                return date_candidate
        except Exception:
            pass
    return None

def extract_city_tag(tags_string):
    if not tags_string:
        return ""
    for part in tags_string.split(","):
        p = part.strip().lower()
        if p.startswith("city-"):
            return p.replace("city-", "")
    return ""

def main():
    print("==================================================")
    print("      MYSEATTLESEARCH PUBLIC EVENTS HARVESTER     ")
    print("==================================================\n")

    if not os.path.exists(PUBLIC_EVENTS_CONFIG):
        print(f"❌ Error: {PUBLIC_EVENTS_CONFIG} missing. Aborting sequence.")
        return

    with open(PUBLIC_EVENTS_CONFIG, "r", encoding="utf-8") as f:
        sources = json.load(f)

    tm_key = os.environ.get("TICKETMASTER_API_KEY", "").strip()

    all_harvested_events = []
    now_pacific = datetime.datetime.now(PACIFIC_TZ)
    start_horizon = now_pacific - datetime.timedelta(hours=2)
    end_horizon = now_pacific + datetime.timedelta(days=90)

    print(f"🔍 Processing {len(sources)} public event sources across King & Snohomish Counties...\n")

    for idx, src in enumerate(sources, 1):
        source_id = src.get("SourceID", f"pe-{idx}")
        source_name = src.get("SourceName", "Unknown Source")
        feed_url = src.get("Feed", "").strip()
        feed_type = src.get("FeedType", "RSS").upper()
        limit = get_feed_limit(src)

        limit_desc = f"(Limit: {limit})" if limit else "(All available)"
        log_prefix = f"[{idx:02d}/{len(sources)}] {source_id.ljust(6)} {source_name[:28].ljust(28)}"

        if not feed_url and "TICKETMASTER" not in feed_type:
            print(f"{log_prefix} ⚠️ Skipped: Missing feed URL")
            continue

        try:
            # Protocol 1: Ticketmaster Discovery API
            if "TICKETMASTER" in feed_type or "TICKETMASTER" in source_name.upper():
                events = harvest_ticketmaster_events(tm_key, src)
                print(f"{log_prefix} ✓ {len(events)} events harvested {limit_desc}")
                all_harvested_events.extend(events)
                continue

            res = requests.get(feed_url, headers=HEADERS, timeout=8, verify=False)
            
            if res.status_code != 200:
                print(f"{log_prefix} ❌ HTTP {res.status_code} ({res.reason})")
                continue

            # Protocol 2: iCalendar / ICS
            if "ICAL" in feed_type or feed_url.endswith(".ics") or "iCalendar" in feed_url:
                events = parse_ics_calendar(res.text, src)

            # Protocol 3: Trumba JSON
            elif "TRUMBA" in source_name.upper() or "trumba.com" in feed_url:
                events = parse_trumba_json(res.json(), src)

            # Protocol 4: Live in Everett Squarespace JSON
            elif "LIVE IN EVERETT" in source_name.upper() or "liveineverett.com" in feed_url:
                events = parse_squarespace_json(res.json(), src)

            # Protocol 5: Live Music Project REST API
            elif "LIVEMUSICPROJECT" in feed_url or "api/v1/events" in feed_url:
                events = parse_live_music_project_api(res.json(), src)

            # Protocol 6: Standard RSS / Atom / BiblioCommons Feeds
            else:
                events = parse_rss_feed(res.content, src)

            status_icon = "✓" if len(events) > 0 else "ℹ️"
            print(f"{log_prefix} {status_icon} {len(events)} events harvested {limit_desc}")
            all_harvested_events.extend(events)

        except requests.exceptions.Timeout:
            print(f"{log_prefix} ⏱️ Connection timed out (>8s)")
        except requests.exceptions.SSLError:
            print(f"{log_prefix} 🔒 SSL handshake failed")
        except Exception as e:
            print(f"{log_prefix} ⚠️ Parse notice: {e}")

    # Filter within 90-day window
    valid_window_events = []
    for ev in all_harvested_events:
        dt_obj = ev.get("_dt")
        if dt_obj and (dt_obj < start_horizon or dt_obj > end_horizon):
            continue
        valid_window_events.append(ev)

    # Multi-date recurring performance deduplication
    production_registry = {}
    deduplicated_events = []

    for ev in valid_window_events:
        base_title = re.sub(r'(\s*-\s*(matinee|evening|opening night|tour|live|tickets).*)', '', ev.get("title", ""), flags=re.I)
        prod_key = f"{slugify(base_title)}_{slugify(ev.get('_venue', ''))}"

        if prod_key not in production_registry:
            production_registry[prod_key] = {
                "count": 1,
                "first_event": ev
            }
            deduplicated_events.append(ev)
        else:
            production_registry[prod_key]["count"] += 1
            first_ev = production_registry[prod_key]["first_event"]
            first_ev["multi_day_run"] = True
            if "multi-day-run" not in first_ev["tags"]:
                first_ev["tags"].append("multi-day-run")

    # Chronological ascending sort
    deduplicated_events.sort(key=lambda x: x.get("_dt", now_pacific))

    for ev in deduplicated_events:
        ev.pop("_dt", None)
        ev.pop("_venue", None)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(deduplicated_events, f, indent=2, ensure_ascii=False)

    print("\n==================================================")
    print("PUBLIC EVENTS HARVEST COMPLETE")
    print(f"  • Total Feeds Scanned:          {len(sources)}")
    print(f"  • Raw Events Extracted:         {len(all_harvested_events)}")
    print(f"  • Final Deduplicated Pipeline:  {len(deduplicated_events)}")
    print(f"  • Feed JSON Saved:              {OUTPUT_PATH}")
    print("==================================================")

if __name__ == "__main__":
    main()