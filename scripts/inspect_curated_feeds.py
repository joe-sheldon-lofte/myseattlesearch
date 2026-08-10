# File: scripts/inspect_curated_feeds.py

import os
import csv
import re
import xml.etree.ElementTree as ET
from datetime import datetime
import urllib3
import requests

# Suppress insecure SSL warnings for municipal government servers
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CSV_PATH = os.path.join(DATA_DIR, "city_feed_data.csv")
REPORT_PATH = os.path.join(DATA_DIR, "feed_verification_report.md")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, text/calendar, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9"
}

def clean_html_text(text):
    """Strips raw HTML tags and cleans whitespace for Markdown presentation."""
    if not text:
        return ""
    text = str(text)
    if HAS_BS4:
        text = BeautifulSoup(text, "html.parser").get_text()
    else:
        text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:250] + "..." if len(text) > 250 else text

def fetch_content(url):
    """Fetches feed payload safely with a 10-second timeout."""
    if not url or not url.startswith("http"):
        return None, "Invalid URL"
    
    if url.startswith("webcal://"):
        url = "https://" + url[9:]

    try:
        resp = requests.get(url, headers=HEADERS, timeout=10, verify=False)
        if resp.status_code == 200:
            return resp.text, None
        return None, f"HTTP Status {resp.status_code}"
    except Exception as e:
        return None, str(e)

def parse_rss_atom(xml_text):
    """Parses up to 10 RSS or Atom items."""
    items = []
    if not xml_text:
        return items

    try:
        # Strip namespaces for simpler ElementTree querying
        xml_clean = re.sub(r'\sxmlns="[^"]+"', '', xml_text, count=1)
        xml_clean = re.sub(r'xmlns:[a-zA-Z0-9]+="[^"]+"', '', xml_clean)
        root = ET.fromstring(xml_clean)

        # 1. RSS 2.0 Check (<channel><item>...)
        channel_items = root.findall(".//item")
        if channel_items:
            for item in channel_items[:10]:
                title = item.findtext("title") or "Untitled Entry"
                link = item.findtext("link") or ""
                date = item.findtext("pubDate") or item.findtext("dc:date") or "Date Unknown"
                desc = item.findtext("description") or item.findtext("encoded") or ""
                items.append({
                    "title": clean_html_text(title),
                    "link": link.strip(),
                    "date": clean_html_text(date),
                    "excerpt": clean_html_text(desc)
                })
            return items

        # 2. Atom Feed Check (<feed><entry>...)
        atom_entries = root.findall(".//entry")
        if atom_entries:
            for entry in atom_entries[:10]:
                title = entry.findtext("title") or "Untitled Video/Post"
                date = entry.findtext("published") or entry.findtext("updated") or "Date Unknown"
                
                # Atom link extraction
                link_node = entry.find("link")
                link = link_node.get("href") if link_node is not None else ""
                
                # YouTube / Atom description
                desc = entry.findtext("summary") or entry.findtext("content") or ""
                media_desc = entry.find(".//{http://search.yahoo.com/mrss/}description")
                if media_desc is not None and media_desc.text:
                    desc = media_desc.text

                items.append({
                    "title": clean_html_text(title),
                    "link": link.strip(),
                    "date": clean_html_text(date),
                    "excerpt": clean_html_text(desc)
                })
            return items

    except Exception as e:
        # Fallback regex extraction if ElementTree fails on malformed XML
        raw_items = re.findall(r'<item>(.*?)</item>', xml_text, re.DOTALL | re.IGNORECASE)
        for raw in raw_items[:10]:
            t = re.search(r'<title>(.*?)</title>', raw, re.DOTALL | re.IGNORECASE)
            l = re.search(r'<link>(.*?)</link>', raw, re.DOTALL | re.IGNORECASE)
            d = re.search(r'<pubDate>(.*?)</pubDate>', raw, re.DOTALL | re.IGNORECASE)
            desc = re.search(r'<description>(.*?)</description>', raw, re.DOTALL | re.IGNORECASE)
            items.append({
                "title": clean_html_text(t.group(1)) if t else "Untitled Entry",
                "link": l.group(1).strip() if l else "",
                "date": clean_html_text(d.group(1)) if d else "Date Unknown",
                "excerpt": clean_html_text(desc.group(1)) if desc else ""
            })

    return items

def parse_ical(ical_text):
    """Parses up to 10 VEVENT blocks from an iCalendar stream."""
    items = []
    if not ical_text:
        return items

    events = re.findall(r'BEGIN:VEVENT(.*?)END:VEVENT', ical_text, re.DOTALL)
    for ev in events[:10]:
        summary_m = re.search(r'SUMMARY:(.*?\r?\n)', ev, re.IGNORECASE)
        dtstart_m = re.search(r'DTSTART.*?:(.*?)(?:\r?\n)', ev, re.IGNORECASE)
        url_m = re.search(r'URL:(.*?\r?\n)', ev, re.IGNORECASE)
        desc_m = re.search(r'DESCRIPTION:(.*?\r?\n)', ev, re.IGNORECASE)

        title = clean_html_text(summary_m.group(1)) if summary_m else "Untitled Event"
        date = clean_html_text(dtstart_m.group(1)) if dtstart_m else "Date Unknown"
        link = url_m.group(1).strip() if url_m else ""
        desc = clean_html_text(desc_m.group(1)) if desc_m else ""

        items.append({
            "title": title,
            "link": link,
            "date": date,
            "excerpt": desc
        })
    return items

def main():
    print("==================================================")
    print("      MUNICIPAL FEED DATA INSPECTOR & REPORT     ")
    print("==================================================\n")

    if not os.path.exists(CSV_PATH):
        print(f"❌ Error: Could not find {CSV_PATH}")
        return

    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))

    print(f"📡 Loaded {len(reader)} feed records from {CSV_PATH}")
    print("🚀 Fetching live payloads and compiling 10-item samples per feed...\n")

    # Group records by City for structured Markdown hierarchy
    city_groups = {}
    for row in reader:
        city = row.get("City", "Unknown").strip()
        city_groups.setdefault(city, []).append(row)

    md_lines = []
    md_lines.append("# Municipal Feed Data Inspection Report")
    md_lines.append(f"**Generated:** {datetime.now().strftime('%B %d, %Y at %I:%M %p')}")
    md_lines.append(f"**Total Feeds Analyzed:** {len(reader)}\n")
    md_lines.append("---")

    for city, feeds in city_groups.items():
        md_lines.append(f"\n## {city}\n")

        for feed in feeds:
            feed_name = feed.get("Feed Name", "Unnamed Feed")
            feed_format = feed.get("Feed Format", "unknown").lower()
            scope = feed.get("Scope", "city")
            category = feed.get("Category", "General")
            notes = feed.get("Notes", "")
            feed_url = feed.get("Feed URL", "").strip()

            md_lines.append(f"### [{scope.upper()}] {feed_name} (`{feed_format}`)")
            md_lines.append(f"- **Category:** {category}")
            md_lines.append(f"- **Feed URL:** [{feed_url}]({feed_url})")
            if notes:
                md_lines.append(f"- **Notes:** {notes}")

            # Non-data portals
            if feed_format in ["granicus", "swagit", "legistar", "external_link"] or "feeds/videos.xml" not in feed_url and feed_format == "youtube_channel":
                md_lines.append("> *Portal / Live Embed Route — Visit portal link directly to view active media player.*\n")
                continue

            # Fetch payload for data feeds (RSS, YouTube Atom, iCal)
            content, err = fetch_content(feed_url)
            if err:
                md_lines.append(f"❌ **Fetch Error:** `{err}`\n")
                continue

            items = []
            if feed_format in ["rss", "youtube_channel"] or "xml" in feed_url or "rss" in feed_url:
                items = parse_rss_atom(content)
            elif feed_format == "ical" or "ics" in feed_url:
                items = parse_ical(content)

            if not items:
                md_lines.append("⚠️ *Endpoint active (HTTP 200), but no recent items were returned in payload.*\n")
                continue

            md_lines.append(f"- **Items Retrieved:** {len(items)}\n")

            for idx, item in enumerate(items, 1):
                item_title = item["title"]
                item_link = item["link"]
                item_date = item["date"]
                item_excerpt = item["excerpt"]

                md_lines.append(f"{idx}. **{item_title}**")
                if item_date:
                    md_lines.append(f"   - **Date:** {item_date}")
                if item_link:
                    md_lines.append(f"   - **Direct Link:** [{item_link}]({item_link})")
                if item_excerpt:
                    md_lines.append(f"   - **Excerpt:** {item_excerpt}")
                md_lines.append("")

            md_lines.append("---")

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    print(f"\n🎉 Inspection complete! Markdown report generated at:\n   {REPORT_PATH}")

if __name__ == "__main__":
    main()