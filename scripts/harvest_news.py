# File: scripts/harvest_news.py
import os
import json
import re
import feedparser
import requests
from dateutil import parser
from datetime import datetime
from zoneinfo import ZoneInfo

def harvest_news_feeds():
    input_config_path = os.path.join("data", "news.json")
    output_feed_path = os.path.join("data", "market_news.json")
    
    if not os.path.exists(input_config_path):
        print(f"❌ Error: Configuration source file missing at {input_config_path}")
        return

    # Protect raw data integrity by enforcing a strict read-only process
    print("📖 Reading master news source registry from spreadsheet ledger...")
    with open(input_config_path, "r", encoding="utf-8") as file_stream:
        sources_list = json.load(file_stream)

    compiled_articles = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    for source in sources_list:
        feed_name = source.get("Name", "Unknown Source")
        rss_url = source.get("RSS Feed URL")
        paywall_flag = str(source.get("Paywall", "No")).strip().lower() == "yes"
        
        city_raw = source.get("City")
        cities_array = [str(city_raw).strip().lower().replace(" ", "-")] if city_raw and str(city_raw).lower() != "nan" else []
        
        # Parse and translate categories into clean, deduplicated URL slugs
        categories_raw = source.get("Categories", "")
        categories_array = []
        if categories_raw:
            for cat in categories_raw.split(","):
                clean_cat = cat.strip().lower().replace(" ", "-")
                if clean_cat and clean_cat not in categories_array:
                    categories_array.append(clean_cat)

        if not rss_url:
            continue

        print(f"📡 Ingesting Source: {feed_name}...")
        try:
            response = requests.get(rss_url, headers=headers, timeout=15)
            if response.status_code != 200:
                continue
                
            feed_data = feedparser.parse(response.content)
            
            for entry in feed_data.entries:
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                
                raw_summary = entry.get("summary") or entry.get("description") or ""
                clean_excerpt = re.sub(r'<[^>]+>', '', raw_summary)
                clean_excerpt = " ".join(clean_excerpt.split())
                
                if len(clean_excerpt) > 220:
                    clean_excerpt = clean_excerpt[:220] + "..."

                # Explicitly parse and normalize timestamps to Pacific Time parameters
                raw_date = entry.get("published") or entry.get("updated") or entry.get("created")
                published_str = ""
                iso_sort_str = ""
                
                if raw_date:
                    try:
                        parsed_datetime = parser.parse(str(raw_date))
                        if parsed_datetime.tzinfo is None:
                            parsed_datetime = parsed_datetime.replace(tzinfo=ZoneInfo("UTC"))
                        
                        pacific_datetime = parsed_datetime.astimezone(ZoneInfo("America/Los_Angeles"))
                        published_str = pacific_datetime.strftime("%a, %b %d, %Y at %I:%M %p")
                        iso_sort_str = pacific_datetime.isoformat()
                    except Exception:
                        now_pac = datetime.now(ZoneInfo("America/Los_Angeles"))
                        published_str = now_pac.strftime("%a, %b %d, %Y at %I:%M %p")
                        iso_sort_str = now_pac.isoformat()
                else:
                    now_pac = datetime.now(ZoneInfo("America/Los_Angeles"))
                    published_str = now_pac.strftime("%a, %b %d, %Y at %I:%M %p")
                    iso_sort_str = now_pac.isoformat()

                if not title or not link:
                    continue

                compiled_articles.append({
                    "source": feed_name,
                    "title": title,
                    "link": link,
                    "excerpt": clean_excerpt if clean_excerpt else "Click view details to read the full update on the publisher's main wire feed.",
                    "published": published_str,
                    "paywall": paywall_flag,
                    "cities": cities_array,
                    "categories": categories_array,
                    "_isoSort": iso_sort_str
                })
        except Exception as error:
            print(f"⚠️ Skipping entry pass for {feed_name}: {error}")

    # Order articles by ISO timestamp strings (Newest First)
    compiled_articles.sort(key=lambda x: x.get("_isoSort", ""), reverse=True)
    final_truncated_feed = compiled_articles[:200]

    # Drop tracking keys before committing output parameters to disk
    for article in final_truncated_feed:
        article.pop("_isoSort", None)

    with open(output_feed_path, "w", encoding="utf-8") as output_stream:
        json.dump(final_truncated_feed, output_stream, indent=2, ensure_ascii=False)
        
    print(f"✅ Data processing complete. Synchronized {len(final_truncated_feed)} articles inside {output_feed_path}")

if __name__ == "__main__":
    harvest_news_feeds()