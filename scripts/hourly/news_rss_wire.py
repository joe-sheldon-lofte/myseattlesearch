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
    print("📡 Starting Local RSS News Wire Aggregator...")
    if not os.path.exists(NEWS_CONFIG_PATH):
        print("ℹ️ news.json config missing. Skipping RSS wire aggregation.")
        return

    try:
        with open(NEWS_CONFIG_PATH, "r", encoding="utf-8") as f:
            sources = json.load(f)

        compiled_articles = []
        for src in sources:
            feed_name = src.get("Name", "Local Wire")
            rss_url = src.get("RSS Feed URL")
            if not rss_url: continue

            paywall_val = str(src.get("Paywall", "No")).strip()
            is_paywall = paywall_val.lower() == "yes"
            city_raw = src.get("City", "").strip()
            cities_array = [city_raw.lower()] if city_raw and city_raw.lower() != "nan" else []
            categories_array = [c.strip().lower().replace(" ", "-") for c in src.get("Categories", "").split(",") if c.strip()]

            try:
                res = requests.get(rss_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
                if res.status_code == 200:
                    feed = feedparser.parse(res.content)
                    for entry in feed.entries:
                        title = entry.get("title", "").strip()
                        link = entry.get("link", "").strip()
                        if not title or not link: continue

                        excerpt = re.sub(r'<[^>]+>', '', entry.get("summary") or entry.get("description") or "")
                        excerpt = " ".join(excerpt.split())
                        if len(excerpt) > 220: excerpt = excerpt[:220] + "..."

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
                            "categories": categories_array,
                            "_iso": sort_str
                        })
            except Exception as e:
                print(f"   ⚠️ Feed notice on '{feed_name}': {e}")

        compiled_articles.sort(key=lambda x: x.get("_iso", ""), reverse=True)
        for a in compiled_articles: a.pop("_iso", None)

        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(compiled_articles[:200], f, indent=2, ensure_ascii=False)

        print(f"✅ Compiled {len(compiled_articles[:200])} news articles into {OUTPUT_PATH}")

    except Exception as e:
        print(f"❌ RSS Wire aggregation failed: {e}")

if __name__ == "__main__":
    main()