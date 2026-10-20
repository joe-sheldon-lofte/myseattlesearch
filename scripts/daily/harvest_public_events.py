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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, application/json, text/calendar, text/xml, */*"
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

def clean_html(text):
    if not text:
        return ""
    cleaned = re.sub(r'<[^>]+>', '', str(text))
    return " ".join(cleaned.split()).strip()

def get_feed_limit(source_meta):
    """
    Extracts numerical limit from the spreadsheet row.
    Returns an int if a valid limit exists, or None to pull all available items.
    """
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
            "_dt": dt_pacific
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
            "_dt": dt_pacific
        })
    return events

def parse_squarespace_json(data, source_meta):
    events = []
    limit = get_feed_limit(source_meta)
    items = data.get("upcoming", []) or data.get("items", []) or []
    
    for item in items:
        if limit is not None and len(events) >= limit:
            break

        title = item.get("title", "").strip()
        if not title:
            continue

        url_path = item.get("fullUrl", "")
        link = f"https://www.liveineverett.com{url_path}" if url_path.startswith("/") else url_path
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
        loc_str = loc_data.get("addressTitle", "") or loc_data.get("addressLine1", "")

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
            "location": loc_str,
            "city": "everett",
            "is_all_day": False,
            "cost": "Community",
            "tags": [t.strip().lower() for t in source_meta.get("Tags", "").split(",") if t.strip()] + item.get("tags", []),
            "categories": item.get("categories", ["Local Events"]),
            "_dt": dt_pacific
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
            "_dt": dt_pacific
        })
    return events

def harvest_ticketmaster_events(api_key, source_meta):
    if not api_key:
        print("   ℹ️ TICKETMASTER_API_KEY missing. Gracefully skipping Ticketmaster Discovery.")
        return []

    events = []
    limit = get_feed_limit(source_meta)
    
    # Respect custom limit if defined; otherwise request max batch size
    batch_size = str(min(limit, 200)) if limit is not None else "100"

    endpoint = "https://app.ticketmaster.com/discovery/v2/events.json"
    params = {
        "apikey": api_key,
        "latlong": "47.6062,-122.3321",  # Central Seattle coordinates
        "radius": "45",
        "unit": "miles",
        "size": batch_size,
        "sort": "date,asc"
    }

    try:
        res = requests.get(endpoint, params=params, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            payload = res.json()
            items = payload.get("_embedded", {}).get("events", [])
            for item in items:
                if limit is not None and len(events) >= limit:
                    break

                title = item.get("name", "").strip()
                link = item.get("url", "")
                if not title or not link:
                    continue

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

                classifications = item.get("classifications", [])
                genre = classifications[0].get("genre", {}).get("name", "") if classifications else ""
                segment = classifications[0].get("segment", {}).get("name", "Major Events") if classifications else "Major Events"

                events.append({
                    "source_id": source_meta.get("SourceID", "pe-10"),
                    "source_name": "Ticketmaster Discovery",
                    "title": title,
                    "link": link,
                    "excerpt": f"{segment} - {genre} live event at {loc_name}.",
                    "start_date": dt_pacific.isoformat(),
                    "end_date": dt_pacific.isoformat(),
                    "display_date": d_date,
                    "display_time": d_time,
                    "location": f"{loc_name}, {city_name.title()}",
                    "city": city_name,
                    "is_all_day": False,
                    "cost": "Ticketed",
                    "tags": ["entertainment", "major-events", "tickets", segment.lower()],
                    "categories": [segment, genre] if genre else [segment],
                    "_dt": dt_pacific
                })
        else:
            print(f"   ⚠️ Ticketmaster API notice: HTTP {res.status_code}")
    except Exception as e:
        print(f"   ⚠️ Ticketmaster harvesting notice: {e}")

    return events

def parse_rss_feed(content, source_meta):
    events = []
    limit = get_feed_limit(source_meta)
    feed = feedparser.parse(content)
    now_pacific = datetime.datetime.now(PACIFIC_TZ)
    
    # Process up to limit or examine all entries in the feed
    entries = feed.entries if limit is None else feed.entries[:limit]
    
    for entry in entries:
        title = entry.get("title", "").strip()
        link = entry.get("link", "").strip()
        if not title or not link:
            continue

        raw_date = entry.get("published") or entry.get("updated")
        dt_pacific, d_date, d_time = normalize_date(raw_date)

        # Fallback to tomorrow if the RSS feed lacks a formal publication date
        if not dt_pacific:
            dt_pacific = now_pacific + datetime.timedelta(days=1)
            d_date = dt_pacific.strftime("%A, %b %d, %Y")
            d_time = "Event Scheduled"

        excerpt = clean_html(entry.get("summary") or entry.get("description") or "")[:220]
        city_tag = extract_city_tag(source_meta.get("Tags", ""))

        tags_raw = source_meta.get("Tags", "")
        tags_array = [t.strip().lower() for t in tags_raw.split(",") if t.strip()]

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
            "location": source_meta.get("SourceName", ""),
            "city": city_tag,
            "is_all_day": False,
            "cost": "Public / Community",
            "tags": tags_array,
            "categories": [source_meta.get("SourceName", "")],
            "_dt": dt_pacific
        })
    return events

def extract_city_tag(tags_string):
    if not tags_string:
        return ""
    for part in tags_string.split(","):
        p = part.strip().lower()
        if p.startswith("city-"):
            return p.replace("city-", "")
    return ""

def main():
    print("📅 Starting Regional Public Events Harvester...")
    if not os.path.exists(PUBLIC_EVENTS_CONFIG):
        print(f"ℹ️ {PUBLIC_EVENTS_CONFIG} missing. Skipping public events harvesting.")
        return

    with open(PUBLIC_EVENTS_CONFIG, "r", encoding="utf-8") as f:
        sources = json.load(f)

    tm_key = os.environ.get("TICKETMASTER_API_KEY", "").strip()

    all_harvested_events = []
    now_pacific = datetime.datetime.now(PACIFIC_TZ)
    # Forward-looking window: Keep events from today up to 90 days out
    start_horizon = now_pacific - datetime.timedelta(hours=12)
    end_horizon = now_pacific + datetime.timedelta(days=90)

    for src in sources:
        source_id = src.get("SourceID", "")
        source_name = src.get("SourceName", "Unknown Source")
        feed_url = src.get("Feed", "").strip()
        feed_type = src.get("FeedType", "RSS").upper()

        if not feed_url and "TICKETMASTER" not in feed_type:
            continue

        try:
            # Protocol 1: Ticketmaster Discovery API
            if "TICKETMASTER" in feed_type or "TICKETMASTER" in source_name.upper():
                events = harvest_ticketmaster_events(tm_key, src)
                all_harvested_events.extend(events)
                continue

            res = requests.get(feed_url, headers=HEADERS, timeout=8, verify=False)
            if res.status_code != 200:
                continue

            # Protocol 2: iCalendar / ICS
            if "ICAL" in feed_type or feed_url.endswith(".ics") or "iCalendar" in feed_url:
                events = parse_ics_calendar(res.text, src)
                all_harvested_events.extend(events)

            # Protocol 3: Trumba JSON
            elif "TRUMBA" in source_name.upper() or "trumba.com" in feed_url:
                events = parse_trumba_json(res.json(), src)
                all_harvested_events.extend(events)

            # Protocol 4: Live in Everett Squarespace JSON
            elif "LIVE IN EVERETT" in source_name.upper() or "?format=json" in feed_url:
                events = parse_squarespace_json(res.json(), src)
                all_harvested_events.extend(events)

            # Protocol 5: Live Music Project REST API
            elif "LIVEMUSICPROJECT" in feed_url or "api/v1/events" in feed_url:
                events = parse_live_music_project_api(res.json(), src)
                all_harvested_events.extend(events)

            # Protocol 6: Default Standard RSS / Atom Feeds
            else:
                events = parse_rss_feed(res.content, src)
                all_harvested_events.extend(events)

        except Exception as e:
            print(f"   ⚠️ Event feed notice on '{source_name}' ({source_id}): {e}")

    # Deduplicate by unique title and date
    unique_events = {}
    for ev in all_harvested_events:
        dt_obj = ev.get("_dt")
        if dt_obj and (dt_obj < start_horizon or dt_obj > end_horizon):
            continue

        dedup_key = f"{slugify(ev.get('title', ''))}_{ev.get('display_date', '')}"
        if dedup_key not in unique_events:
            unique_events[dedup_key] = ev

    cleaned_list = list(unique_events.values())
    
    # Sort chronologically ascending by start date
    cleaned_list.sort(key=lambda x: x.get("_dt", now_pacific))

    # Clean internal datetime object
    for ev in cleaned_list:
        ev.pop("_dt", None)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(cleaned_list, f, indent=2, ensure_ascii=False)

    print(f"✅ Successfully compiled {len(cleaned_list)} public events across {len(sources)} sources into {OUTPUT_PATH}")

def slugify(text):
    if not text:
        return ""
    text = str(text).lower().strip()
    return re.sub(r'[^a-z0-9]+', '-', text).strip('-')

if __name__ == "__main__":
    main()