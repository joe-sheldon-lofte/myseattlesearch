# File: scripts/news_rss_wire.py
import os
import json
import re
import datetime
import warnings
import urllib3
import requests
import feedparser
from dateutil import parser
from dateutil.parser import UnknownTimezoneWarning
from zoneinfo import ZoneInfo

# Suppress timezone and SSL handshake warnings
warnings.filterwarnings("ignore", category=UnknownTimezoneWarning)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Robust Repository Root Path Resolution
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(CURRENT_DIR) == "hourly":
    REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
elif os.path.basename(CURRENT_DIR) == "scripts":
    REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
else:
    REPO_ROOT = os.path.abspath(CURRENT_DIR)

DATA_DIR = os.path.join(REPO_ROOT, "data")
NEWS_CONFIG_PATH = os.path.join(DATA_DIR, "news.json")
OUTPUT_PATH = os.path.join(DATA_DIR, "market_news.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, */*"
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

def main():
    print("📡 Starting Local RSS News Wire Aggregator (Per-Feed Quota & Prefixed Tags Model)...")
    if not os.path.exists(NEWS_CONFIG_PATH):
        print("ℹ️ news.json config missing. Skipping RSS wire aggregation.")
        return

    try:
        with open(NEWS_CONFIG_PATH, "r", encoding="utf-8") as f:
            sources = json.load(f)

        compiled_articles = []
        for src in sources:
            if str(src.get("Active", "Yes")).strip().lower() in ["no", "n", "false"]:
                continue

            feed_name = src.get("Name") or src.get("SourceName") or "Local Wire"
            rss_url = src.get("RSS Feed URL") or src.get("RSS_URL")
            if not rss_url: 
                continue

            quota_raw = src.get("ArticleCap") or src.get("Article Cap") or src.get("Max Articles") or src.get("MaxArticles")
            try:
                max_articles = int(quota_raw)
            except (ValueError, TypeError):
                max_articles = 5

            paywall_val = str(src.get("Paywall", "No")).strip()
            is_paywall = paywall_val.lower() == "yes"
            
            city_raw = src.get("City", "").strip()
            cities_array = [city_raw.lower()] if city_raw and city_raw.lower() != "nan" else []
            
            tags_raw = src.get("Tags") or src.get("Categories") or ""
            tags_array = [t.strip().lower() for t in tags_raw.split(",") if t.strip()]

            try:
                # SSL-safe get with timeout and browser agent
                res = requests.get(rss_url, headers=HEADERS, timeout=8, verify=False)
                if res.status_code == 200:
                    feed = feedparser.parse(res.content)
                    feed_entries = feed.entries[:max_articles]
                    
                    for entry in feed_entries:
                        title = entry.get("title", "").strip()
                        link = entry.get("link", "").strip()
                        if not title or not link: 
                            continue

                        excerpt = re.sub(r'<[^>]+>', '', entry.get("summary") or entry.get("description") or "")
                        excerpt = " ".join(excerpt.split())
                        if len(excerpt) > 220: 
                            excerpt = excerpt[:220] + "..."

                        raw_date = entry.get("published") or entry.get("updated")
                        try:
                            p_dt = parser.parse(str(raw_date), tzinfos=TZINFOS)
                            if p_dt.tzinfo is None:
                                p_dt = p_dt.replace(tzinfo=ZoneInfo("UTC"))
                            p_local = p_dt.astimezone(ZoneInfo("America/Los_Angeles"))
                            pub_str = p_local.strftime("%a, %b %d, %Y at %I:%M %p")
                            sort_str = p_local.isoformat()
                        except Exception:
                            now_pac = datetime.datetime.now(ZoneInfo("America/Los_Angeles"))
                            pub_str = now_pac.strftime("%a, %b %d, %Y at %I:%M %p")
                            sort_str = now_pac.isoformat()

                        compiled_articles.append({
                            "source": feed_name,
                            "title": title,
                            "link": link,
                            "excerpt": excerpt if excerpt else "Click view details to read full update.",
                            "published": pub_str,
                            "paywall": is_paywall,
                            "cities": cities_array,
                            "tags": tags_array,
                            "categories": tags_array,
                            "_iso": sort_str
                        })
            except Exception as e:
                print(f"   ⚠️ Feed notice on '{feed_name}': {e}")

        # Sort master list chronologically
        compiled_articles.sort(key=lambda x: x.get("_iso", ""), reverse=True)
        for a in compiled_articles: 
            a.pop("_iso", None)

        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(compiled_articles, f, indent=2, ensure_ascii=False)

        print(f"✅ Compiled {len(compiled_articles)} total news articles from {len(sources)} sources into {OUTPUT_PATH}")

    except Exception as e:
        print(f"❌ RSS Wire aggregation failed: {e}")

if __name__ == "__main__":
    main()