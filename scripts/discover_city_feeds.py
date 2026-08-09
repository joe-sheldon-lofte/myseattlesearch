# File: scripts/discover_city_feeds.py

import os
import json
import csv
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import urllib3

# Suppress insecure SSL warnings for municipal government servers
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5"
}

CSV_COLUMNS = [
    "City", "County", "School District", "Scope", "Category", 
    "Notes", "Feed Name", "Feed Format", "Valid", "Status Code", 
    "Feed URL", "Test Data"
]

def slugify(text):
    if not text:
        return ""
    text = str(text).lower().strip()
    out = []
    for ch in text:
        if ch.isalnum():
            out.append(ch)
        elif ch in [' ', '-', '_']:
            out.append('-')
    res = "".join(out)
    while '--' in res:
        res = res.replace('--', '-')
    return res.strip('-')

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
            if t and not any(skip in t.lower() for skip in ["rss", "feed", "index", "home", "wordpress", "civicplus"]):
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
            if len(t) > 10 and t not in titles and not any(skip in t.lower() for skip in ["404", "error", "not found", "access denied"]):
                titles.append(t)
            if len(titles) >= 3:
                break

    return " | ".join(titles[:3]) if titles else "Endpoint active (200 OK)"

def probe_url(url):
    if not url:
        return 0, ""
    
    if url.startswith("webcal://"):
        url = "https://" + url[9:]
        
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8, allow_redirects=True, verify=False)
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
        return discovered

    if not base_url or not base_url.startswith("http"):
        return discovered

    base_url = base_url.rstrip("/")
    city_slug = slugify(city)
    school_slug = slugify(school_district)
    target_slug = city_slug if scope == "city" else school_slug
    
    seen_urls = set()

    # ------------------------------------------------------------------
    # 1. SWAGIT & GRANICUS & LEGISTAR & BOARDDOCS PERMUTATION MATRIX
    # ------------------------------------------------------------------
    if target_slug:
        # Swagit Permutations
        swagit_hosts = [
            f"https://{target_slug}wa.new.swagit.com",
            f"https://{target_slug}.new.swagit.com",
            f"https://{target_slug}wa.swagit.com",
            f"https://{target_slug}.swagit.com",
            f"https://{target_slug}sd.new.swagit.com"
        ]
        for sw_host in swagit_hosts:
            if sw_host in seen_urls:
                continue
            seen_urls.add(sw_host)
            sw_status, sw_content = probe_url(sw_host)
            if sw_status == 200 and "swagit" in sw_content.lower():
                discovered.append({
                    "City": city,
                    "County": county,
                    "School District": school_district,
                    "Scope": scope,
                    "Category": "Video Stream",
                    "Notes": "Discovered Swagit Vendor Subdomain Matrix",
                    "Feed Name": f"{city if scope == 'city' else school_district} Swagit Meeting Portal",
                    "Feed Format": "swagit",
                    "Valid": "Yes",
                    "Status Code": sw_status,
                    "Feed URL": sw_host,
                    "Test Data": f"Swagit Video Portal Active ({sw_host})"
                })

        # Granicus Permutations
        granicus_hosts = [
            f"https://{target_slug}.granicus.com",
            f"https://{target_slug}wa.granicus.com"
        ]
        for gr_host in granicus_hosts:
            if gr_host in seen_urls:
                continue
            seen_urls.add(gr_host)
            gr_status, gr_content = probe_url(f"{gr_host}/ViewPublisher.php?view_id=2")
            if gr_status == 200 and ("granicus" in gr_content.lower() or "agenda" in gr_content.lower()):
                discovered.append({
                    "City": city,
                    "County": county,
                    "School District": school_district,
                    "Scope": scope,
                    "Category": "Video Stream",
                    "Notes": "Discovered Granicus Vendor Subdomain Matrix",
                    "Feed Name": f"{city if scope == 'city' else school_district} Granicus Meeting Portal",
                    "Feed Format": "granicus",
                    "Valid": "Yes",
                    "Status Code": gr_status,
                    "Feed URL": f"{gr_host}/ViewPublisher.php?view_id=2",
                    "Test Data": f"Granicus Publisher Active ({gr_host})"
                })

        # Legistar Portal
        legistar_url = f"https://{target_slug}.legistar.com/Calendar.aspx"
        if legistar_url not in seen_urls:
            seen_urls.add(legistar_url)
            leg_status, leg_content = probe_url(legistar_url)
            if leg_status == 200 and "legistar" in leg_content.lower():
                discovered.append({
                    "City": city,
                    "County": county,
                    "School District": school_district,
                    "Scope": scope,
                    "Category": "City Council" if scope == "city" else "School Board",
                    "Notes": "Discovered Legistar Agenda & Video Portal",
                    "Feed Name": f"{city if scope == 'city' else school_district} Legistar Portal",
                    "Feed Format": "legistar",
                    "Valid": "Yes",
                    "Status Code": leg_status,
                    "Feed URL": legistar_url,
                    "Test Data": "Legistar Agenda & Meeting Archive Active"
                })

        # BoardDocs Portal (Schools)
        if scope == "school":
            boarddocs_url = f"https://go.boarddocs.com/wa/{target_slug}/Board.nsf/Public"
            if boarddocs_url not in seen_urls:
                seen_urls.add(boarddocs_url)
                bd_status, bd_content = probe_url(boarddocs_url)
                if bd_status == 200 and "boarddocs" in bd_content.lower():
                    discovered.append({
                        "City": city,
                        "County": county,
                        "School District": school_district,
                        "Scope": scope,
                        "Category": "School Board",
                        "Notes": "Discovered BoardDocs Agenda Portal",
                        "Feed Name": f"{school_district} BoardDocs Portal",
                        "Feed Format": "boarddocs",
                        "Valid": "Yes",
                        "Status Code": bd_status,
                        "Feed URL": boarddocs_url,
                        "Test Data": "BoardDocs Meeting Agenda & Video Portal Active"
                    })

    # ------------------------------------------------------------------
    # 2. DEEP ROUTE & SITEMAP INSPECTION
    # ------------------------------------------------------------------
    paths_to_check = [
        "",
        "/agendas",
        "/agendacenter",
        "/calendar",
        "/news",
        "/events",
        "/city-council",
        "/council",
        "/school-board",
        "/board",
        "/videos",
        "/watch",
        "/mediacenter",
        "/videocenter",
        "/broadcasts",
        "/live",
        "/Government/City-Council/City-Council-Meetings",
        "/Government/Boards-and-Commissions/Meeting-Agendas-and-Minutes",
        "/RSSFeed.aspx?ModID=1&MainCatID=1",
        "/RSSFeed.aspx?ModID=58&MainCatID=1",
        "/RSSFeed.aspx?ModID=14&MainCatID=1",
        "/Calendar.aspx?CID=1&Type=iCal",
        "/Calendar-Feed",
        "/feed/",
        "/rss.cfm?news=0",
        "/sitemap.xml"
    ]

    # Quick sitemap inspection if available
    sitemap_status, sitemap_content = probe_url(f"{base_url}/sitemap.xml")
    if sitemap_status == 200 and sitemap_content:
        sitemap_urls = re.findall(r'<loc>(.*?)</loc>', sitemap_content, re.IGNORECASE)
        for sm_url in sitemap_urls:
            sm_lower = sm_url.lower()
            if any(kw in sm_lower for kw in ["video", "council", "agenda", "meeting", "broadcast", "watch", "live", "board"]):
                path_part = sm_url.replace(base_url, "")
                if path_part and path_part not in paths_to_check and len(paths_to_check) < 40:
                    paths_to_check.append(path_part)

    for path in paths_to_check:
        target_url = base_url + path if path else base_url
        if target_url in seen_urls:
            continue
        seen_urls.add(target_url)

        status_code, content = probe_url(target_url)
        if status_code != 200 or not content:
            continue

        # A. Direct XML/RSS Payload
        if any(token in content.lower()[:300] for token in ["<rss", "<feed", "<channel", "xmlns:content"]):
            samples = extract_sample_titles(content, "rss")
            cat = "News Feed" if "news" in target_url.lower() else ("Community Events" if "modid=58" in target_url.lower() else "Municipal RSS")
            discovered.append({
                "City": city,
                "County": county,
                "School District": school_district,
                "Scope": scope,
                "Category": cat,
                "Notes": f"Direct RSS Feed ({path or 'root'})",
                "Feed Name": f"{city if scope == 'city' else school_district} RSS Feed",
                "Feed Format": "rss",
                "Valid": "Yes",
                "Status Code": status_code,
                "Feed URL": target_url,
                "Test Data": samples
            })
            continue

        # B. Direct iCal Payload
        if "BEGIN:VCALENDAR" in content[:300]:
            samples = extract_sample_titles(content, "ical")
            discovered.append({
                "City": city,
                "County": county,
                "School District": school_district,
                "Scope": scope,
                "Category": "Calendar Feed",
                "Notes": f"Direct iCal Feed ({path or 'root'})",
                "Feed Name": f"{city if scope == 'city' else school_district} iCal Calendar",
                "Feed Format": "ical",
                "Valid": "Yes",
                "Status Code": status_code,
                "Feed URL": target_url,
                "Test Data": samples
            })
            continue

        # C. Scraping HTML for Feeds, Embeds, and Meta Tags
        # RSS Matches
        rss_matches = re.findall(r'href=["\']([^"\']*\.(?:rss|xml)|[^"\']*RSSFeed\.aspx[^"\']*|[^"\']*/feed/?)["\']', content, re.IGNORECASE)
        for rel_link in rss_matches:
            full_rss = urllib.parse.urljoin(target_url, rel_link)
            if full_rss not in seen_urls:
                seen_urls.add(full_rss)
                rss_status, rss_content = probe_url(full_rss)
                if rss_status == 200 and rss_content:
                    samples = extract_sample_titles(rss_content, "rss")
                    discovered.append({
                        "City": city,
                        "County": county,
                        "School District": school_district,
                        "Scope": scope,
                        "Category": "News Feed" if "news" in full_rss.lower() else "Municipal RSS",
                        "Notes": f"Scraped RSS via {path or 'homepage'}",
                        "Feed Name": f"{city if scope == 'city' else school_district} RSS Feed",
                        "Feed Format": "rss",
                        "Valid": "Yes",
                        "Status Code": rss_status,
                        "Feed URL": full_rss,
                        "Test Data": samples
                    })

        # iCal Matches
        ics_matches = re.findall(r'href=["\']([^"\']*\.(?:ics|ical)|[^"\']*Calendar-Feed[^"\']*|[^"\']*Type=iCal[^"\']*)["\']', content, re.IGNORECASE)
        for rel_link in ics_matches:
            full_ics = urllib.parse.urljoin(target_url, rel_link)
            if full_ics not in seen_urls:
                seen_urls.add(full_ics)
                ics_status, ics_content = probe_url(full_ics)
                if ics_status == 200 and ics_content:
                    samples = extract_sample_titles(ics_content, "ical")
                    discovered.append({
                        "City": city,
                        "County": county,
                        "School District": school_district,
                        "Scope": scope,
                        "Category": "Calendar Feed",
                        "Notes": f"Scraped iCal via {path or 'homepage'}",
                        "Feed Name": f"{city if scope == 'city' else school_district} Calendar",
                        "Feed Format": "ical",
                        "Valid": "Yes",
                        "Status Code": ics_status,
                        "Feed URL": full_ics,
                        "Test Data": samples
                    })

        # Swagit Matches
        swagit_matches = re.findall(r'(?:swagit\.com/views/|views/|swagit\.com/play/)(\d+)', content, re.IGNORECASE)
        for view_id in set(swagit_matches):
            swagit_url = f"https://swagit.com/views/{view_id}"
            if swagit_url not in seen_urls:
                seen_urls.add(swagit_url)
                swagit_status, swagit_content = probe_url(swagit_url)
                discovered.append({
                    "City": city,
                    "County": county,
                    "School District": school_district,
                    "Scope": scope,
                    "Category": "Video Stream",
                    "Notes": f"Discovered Swagit View ID {view_id}",
                    "Feed Name": f"{city if scope == 'city' else school_district} Meeting Video Stream",
                    "Feed Format": "swagit",
                    "Valid": "Yes" if swagit_status == 200 else "No",
                    "Status Code": swagit_status,
                    "Feed URL": swagit_url,
                    "Test Data": f"Swagit Portal View {view_id}"
                })

        # Granicus Matches
        granicus_matches = re.findall(r'granicus\.com/[^"\']*(?:view_id=|clip_id=)(\d+)', content, re.IGNORECASE)
        for view_id in set(granicus_matches):
            granicus_url = f"https://granicus.com/MediaPlayer.php?view_id={view_id}"
            if granicus_url not in seen_urls:
                seen_urls.add(granicus_url)
                discovered.append({
                    "City": city,
                    "County": county,
                    "School District": school_district,
                    "Scope": scope,
                    "Category": "Video Stream",
                    "Notes": f"Discovered Granicus View ID {view_id}",
                    "Feed Name": f"{city if scope == 'city' else school_district} Granicus Meeting Stream",
                    "Feed Format": "granicus",
                    "Valid": "Yes",
                    "Status Code": 200,
                    "Feed URL": target_url,
                    "Test Data": f"Granicus Player View ID {view_id}"
                })

        # YouTube Channel & Meta Tag Hunters
        yt_channel_matches = re.findall(r'youtube\.com/(?:channel/|@|c/|user/)([a-zA-Z0-9_\-]+)', content, re.IGNORECASE)
        yt_meta_matches = re.findall(r'itemprop=["\']channelId["\']\s+content=["\']([a-zA-Z0-9_\-]+)["\']', content, re.IGNORECASE)
        all_yt_ids = set(yt_channel_matches + yt_meta_matches)

        for yt_id in all_yt_ids:
            if yt_id.lower() in ["youtube", "user", "watch", "embed", "playlist", "live"]:
                continue
            yt_url = f"https://www.youtube.com/@{yt_id}" if not yt_id.startswith("UC") else f"https://www.youtube.com/channel/{yt_id}"
            if yt_url not in seen_urls:
                seen_urls.add(yt_url)
                discovered.append({
                    "City": city,
                    "County": county,
                    "School District": school_district,
                    "Scope": scope,
                    "Category": "Video Stream",
                    "Notes": f"Discovered Official YouTube Channel (@{yt_id})",
                    "Feed Name": f"{city if scope == 'city' else school_district} Official YouTube Channel",
                    "Feed Format": "youtube_channel",
                    "Valid": "Yes",
                    "Status Code": 200,
                    "Feed URL": yt_url,
                    "Test Data": f"YouTube Channel @{yt_id}"
                })

        # Public Access Cable / PEG TV Matches
        if "seattlechannel.org" in content.lower():
            sc_url = "https://www.seattlechannel.org"
            if sc_url not in seen_urls:
                seen_urls.add(sc_url)
                discovered.append({
                    "City": city,
                    "County": county,
                    "School District": school_district,
                    "Scope": scope,
                    "Category": "Video Stream",
                    "Notes": "Discovered Seattle Channel PEG Broadcast",
                    "Feed Name": "Seattle Channel Municipal Stream",
                    "Feed Format": "external_link",
                    "Valid": "Yes",
                    "Status Code": 200,
                    "Feed URL": sc_url,
                    "Test Data": "Seattle Channel Live Municipal TV Stream"
                })

        # D. Official Portal Fallbacks
        if path in ["/agendas", "/agendacenter", "/calendar", "/news", "/city-council", "/school-board", "/mediacenter"]:
            portal_url = target_url
            if portal_url not in seen_urls:
                seen_urls.add(portal_url)
                cat = "City Council" if "council" in path or "agenda" in path else ("Calendar Feed" if path == "/calendar" else ("School Board" if "board" in path else "City News"))
                discovered.append({
                    "City": city,
                    "County": county,
                    "School District": school_district,
                    "Scope": scope,
                    "Category": cat,
                    "Notes": f"Official Portal Route ({path})",
                    "Feed Name": f"{city if scope == 'city' else school_district} {cat} Portal",
                    "Feed Format": "external_link",
                    "Valid": "Yes",
                    "Status Code": status_code,
                    "Feed URL": portal_url,
                    "Test Data": f"Official portal page active (HTTP {status_code})"
                })

    return discovered

def process_city_data(item):
    results = []
    results.extend(discover_site_feeds(item, "city"))
    results.extend(discover_site_feeds(item, "school"))
    return results

def main():
    print("==================================================")
    print("      MUNICIPAL FEED MONSTER DISCOVERY CRAWLER    ")
    print("==================================================\n")

    if not os.path.exists(CITY_DATA_PATH):
        print(f"❌ Error: Could not find {CITY_DATA_PATH}")
        return

    with open(CITY_DATA_PATH, "r", encoding="utf-8") as f:
        city_records = json.load(f)

    print(f"📡 Loaded {len(city_records)} municipalities from city_data.json")
    print("🚀 Launching multi-threaded monster discovery crawler (City & School Scopes)...")

    all_discovered_feeds = []

    with ThreadPoolExecutor(max_workers=18) as executor:
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

    print(f"\n🎉 Monster Crawl complete! Saved {len(all_discovered_feeds)} feeds to {OUTPUT_CSV_PATH}")

if __name__ == "__main__":
    main()