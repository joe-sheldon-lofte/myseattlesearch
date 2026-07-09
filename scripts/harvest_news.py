# File: scripts/harvest_news.py
import os
import json
import re
import feedparser
from datetime import datetime
from dateutil import parser

MASTER_FEEDS = [
    # === Macro Market Verticals ===
    {"source": "Seattle Times Real Estate", "url": "https://www.seattletimes.com/business/real-estate/feed/", "category": "real-estate", "paywall": True, "cities": []},
    {"source": "Redfin Blog", "url": "https://www.redfin.com/blog/feed/", "category": "real-estate", "paywall": False, "cities": []},
    {"source": "Mortgage News Daily", "url": "https://www.mortgagenewsdaily.com/rss", "category": "real-estate", "paywall": False, "cities": []},
    {"source": "GeekWire Business & Tech", "url": "https://www.geekwire.com/feed/", "category": "business", "paywall": False, "cities": []},
    {"source": "Puget Sound Business Journal", "url": "https://www.bizjournals.com/seattle/feed/", "category": "business", "paywall": True, "cities": []},
    {"source": "Daily Journal of Commerce", "url": "https://www.djc.com/rss/", "category": "business", "paywall": True, "cities": []},

    # === North Sound Footprint ===
    {"source": "Edmonds Beacon", "url": "https://www.edmondsbeacon.com/feed/", "category": "north-sound", "paywall": False, "cities": ["edmonds"]},
    {"source": "MyEdmondsNews", "url": "https://myedmondsnews.com/feed/", "category": "north-sound", "paywall": False, "cities": ["edmonds"]},
    {"source": "Lynnwood Times", "url": "https://lynnwoodtimes.com/feed/", "category": "north-sound", "paywall": False, "cities": ["lynnwood"]},
    {"source": "MLTnews", "url": "https://mltnews.com/feed/", "category": "north-sound", "paywall": False, "cities": ["mountlake-terrace"]},
    {"source": "Shoreline Area News", "url": "https://www.shorelineareanews.com/feeds/posts/default?alt=rss", "category": "north-sound", "paywall": False, "cities": ["shoreline", "lake-forest-park"]},
    {"source": "Bothell Kenmore Reporter", "url": "https://www.bothell-reporter.com/feed/", "category": "north-sound", "paywall": False, "cities": ["bothell", "kenmore"]},
    {"source": "Kirkland Reporter", "url": "https://www.kirklandreporter.com/feed/", "category": "north-sound", "paywall": False, "cities": ["kirkland"]},

    # === Seattle Proper Footprint ===
    {"source": "The Urbanist", "url": "https://www.theurbanist.org/feed/", "category": "seattle", "paywall": False, "cities": ["seattle"]},
    {"source": "Capitol Hill Seattle News", "url": "https://capitolhillseattle.com/feed", "category": "seattle", "paywall": False, "cities": ["seattle"]},
    {"source": "West Seattle Blog", "url": "https://westseattleblog.com/feed", "category": "seattle", "paywall": False, "cities": ["seattle"]},
    {"source": "Seattle Weekly", "url": "https://www.seattleweekly.com/feed/", "category": "seattle", "paywall": False, "cities": ["seattle"]},
    {"source": "Seattle PI", "url": "https://www.seattlepi.com/feed/", "category": "seattle", "paywall": False, "cities": ["seattle"]},
    {"source": "My Ballard", "url": "https://www.myballard.com/feed/", "category": "seattle", "paywall": False, "cities": ["seattle"]},
    {"source": "Phinneywood", "url": "https://www.phinneywood.com/feed/", "category": "seattle", "paywall": False, "cities": ["seattle"]},

    # === Eastside Footprint ===
    {"source": "425 Magazine", "url": "https://425magazine.com/feed/", "category": "eastside", "paywall": False, "cities": ["bellevue", "issaquah", "kirkland", "redmond"]},

    # === Snohomish County Macro Footprint ===
    {"source": "Everett Herald", "url": "https://www.heraldnet.com/feed/", "category": "snohomish-county", "paywall": True, "cities": ["everett"]},
    {"source": "Stanwood Camano News", "url": "https://www.scnews.com/search/?f=rss", "category": "snohomish-county", "paywall": False, "cities": ["stanwood"]},
    {"source": "Marysville Globe", "url": "https://www.marysvilleglobe.com/feed/", "category": "snohomish-county", "paywall": False, "cities": ["marysville"]},
    {"source": "Arlington Times", "url": "https://www.arlingtontimes.com/feed/", "category": "snohomish-county", "paywall": False, "cities": ["arlington"]},

    # === South King Footprint ===
    {"source": "Kent Reporter", "url": "https://www.kentreporter.com/feed/", "category": "south-king", "paywall": False, "cities": ["kent"]},
    {"source": "Renton Reporter", "url": "https://www.rentonreporter.com/feed/", "category": "south-king", "paywall": False, "cities": ["renton"]},
    {"source": "Federal Way Mirror", "url": "https://www.federalwaymirror.com/feed/", "category": "south-king", "paywall": False, "cities": ["federal-way"]},
    {"source": "The Waterland Blog", "url": "https://waterlandblog.com/feed/", "category": "south-king", "paywall": False, "cities": ["des-moines"]},
    {"source": "Covington-Maple Valley-Black Diamond Reporter", "url": "https://www.covingtonreporter.com/feed/", "category": "south-king", "paywall": False, "cities": ["covington", "maple-valley", "black-diamond"]},
    {"source": "Auburn Reporter", "url": "https://www.auburnreporter.com/feed/", "category": "south-king", "paywall": False, "cities": ["auburn"]},
    {"source": "Enumclaw Courier-Herald", "url": "https://www.courierherald.com/feed/", "category": "south-king", "paywall": False, "cities": ["enumclaw"]}
]

def harvest_and_normalize_all():
    normalized_collection = []
    
    for entry in MASTER_FEEDS:
        try:
            feed_payload = feedparser.parse(entry["url"])
            for item in feed_payload.entries[:15]:
                # Extract and clean summary text (remove HTML blocks cleanly)
                raw_summary = item.get("summary", item.get("description", ""))
                clean_summary = re.sub(r'<[^>]+>', '', raw_summary)
                clean_summary = clean_summary.replace('\n', ' ').strip()
                
                # Truncate summary into a clean presentation excerpt
                excerpt = clean_summary[:150] + "..." if len(clean_summary) > 150 else clean_summary
                if not excerpt or excerpt == "...":
                    excerpt = "Click to view full coverage article from the publisher source feed."

                # Clean and re-format published time layout, stripping "+0000" or offsets
                raw_date = item.get("published", datetime.utcnow().isoformat())
                try:
                    parsed_dt = parser.parse(raw_date)
                    clean_date = parsed_dt.strftime("%a, %b %d, %Y at %I:%M %p")
                except:
                    clean_date = str(raw_date).replace(" +0000", "").replace(" GMT", "")

                story_record = {
                    "title": item.get("title", "Local Market Update Node"),
                    "link": item.get("link", "#"),
                    "source": entry["source"],
                    "category": entry["category"],
                    "paywall": entry["paywall"],
                    "cities": entry["cities"],
                    "excerpt": excerpt,
                    "published": clean_date,
                    "timestamp": parsed_dt.timestamp() if 'parsed_dt' in locals() else 0
                }
                normalized_collection.append(story_record)
        except Exception as err:
            pass
            
    # CRITICAL: Sort the entire multi-source array chronologically descending by true timestamp
    normalized_collection.sort(key=lambda x: x["timestamp"], reverse=True)

    target_destination = os.path.join("data", "market_news.json")
    os.makedirs(os.path.dirname(target_destination), exist_ok=True)
    
    with open(target_destination, "w", encoding="utf-8") as file_pointer:
        json.dump(normalized_collection, file_pointer, indent=2)

if __name__ == "__main__":
    harvest_and_normalize_all()