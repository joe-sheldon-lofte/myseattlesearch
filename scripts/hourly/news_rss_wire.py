# File: scripts/news_rss_wire.py
import os
import json
import re
import requests
import feedparser
from dateutil import parser
from zoneinfo import ZoneInfo
import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
NEWS_CONFIG_PATH = os.path.join(DATA_DIR, "news.json")
OUTPUT_PATH = os.path.join(DATA_DIR, "market_news.json")

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
            # Skip inactive feeds if 'Active' column exists
            if str(src.get("Active", "Yes")).strip().lower() in ["no", "n", "false"]:
                continue

            feed_name = src.get("Name") or src.get("SourceName") or "Local Wire"
            rss_url = src.get("RSS Feed URL") or src.get("RSS_URL")
            if not rss_url: 
                continue

            # Determine per-feed quota
            quota_raw = src.get("ArticleCap") or src.get("Article Cap") or src.get("Max Articles") or src.get("MaxArticles")
            try:
                max_articles = int(quota_raw)
            except (ValueError, TypeError):
                max_articles = 5

            paywall_val = str(src.get("Paywall", "No")).strip()
            is_paywall = paywall_val.lower() == "yes"
            
            city_raw = src.get("City", "").strip()
            cities_array = [city_raw.lower()] if city_raw and city_raw.lower() != "nan" else []
            
            # Read 'Tags' key first, fallback to 'Categories'
            tags_raw = src.get("Tags") or src.get("Categories") or ""
            tags_array = [t.strip().lower() for t in tags_raw.split(",") if t.strip()]

            try:
                res = requests.get(rss_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
                if res.status_code == 200:
                    feed = feedparser.parse(res.content)
                    
                    # Enforce per-feed quota
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
                            p_dt = parser.parse(str(raw_date))
                            if p_dt.tzinfo is None: p_dt = p_dt.replace(tzinfo=ZoneInfo("UTC"))
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

        # Write all aggregated articles without global truncation
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(compiled_articles, f, indent=2, ensure_ascii=False)

        print(f"✅ Compiled {len(compiled_articles)} total news articles from {len(sources)} sources into {OUTPUT_PATH}")

    except Exception as e:
        print(f"❌ RSS Wire aggregation failed: {e}")

if __name__ == "__main__":
    main()