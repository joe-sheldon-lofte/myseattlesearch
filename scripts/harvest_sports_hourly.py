# File: scripts/harvest_sports_hourly.py
import os
import re
import json
import requests
import feedparser
import datetime
import warnings
import urllib3
from zoneinfo import ZoneInfo
from dateutil import parser
from dateutil.parser import UnknownTimezoneWarning

# Suppress PST/PDT timezone warnings and unverified HTTPS request warnings
warnings.filterwarnings("ignore", category=UnknownTimezoneWarning)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
SPORTS_TEAMS_PATH = os.path.join(DATA_DIR, "sports_teams.json")
SPORTS_DATA_PATH = os.path.join(DATA_DIR, "sports_data.json")

HTTP_CACHE = {}
KNOWN_JSON_DOMAINS = [
    "api.espn.com",
    "site.api.espn.com",
    "statsapi.mlb.com",
    "api-web.nhle.com",
    "lscluster.hockeytech.com"
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

def fetch_json_deduped(url, timeout=5):
    """Fetches JSON with SSL fallback, deduplication, and JSON payload verification."""
    if not url or not isinstance(url, str) or not url.strip() or url.strip().lower() == "nan":
        return None
    
    clean_url = url.strip()
    if clean_url in HTTP_CACHE:
        return HTTP_CACHE[clean_url]

    headers = {"User-Agent": "MySeattleSearch/1.0"}
    
    try:
        try:
            res = requests.get(clean_url, headers=headers, timeout=timeout, verify=True)
        except requests.exceptions.SSLError:
            res = requests.get(clean_url, headers=headers, timeout=timeout, verify=False)

        if res.status_code == 200:
            text_start = res.text.strip()[:10]
            if text_start.startswith("{") or text_start.startswith("["):
                data = res.json()
                HTTP_CACHE[clean_url] = data
                return data
    except Exception as e:
        print(f"   ⚠️ DataFeed fetch warning [{clean_url[:60]}]: {e}")
    
    HTTP_CACHE[clean_url] = None
    return None

def fetch_rss_stories(url, max_items=3, timeout=5):
    """Parses up to max_items articles from an RSS feed with SSL fallback."""
    if not url or not isinstance(url, str) or not url.strip() or url.strip().lower() == "nan":
        return []
    
    clean_url = url.strip()
    stories = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MySeattleSearch/1.0"}
    
    try:
        try:
            res = requests.get(clean_url, headers=headers, timeout=timeout, verify=True)
        except requests.exceptions.SSLError:
            res = requests.get(clean_url, headers=headers, timeout=timeout, verify=False)

        if res.status_code == 200:
            feed = feedparser.parse(res.content)
            for entry in feed.entries[:max_items]:
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                if not title or not link:
                    continue
                
                excerpt = re.sub(r'<[^>]+>', '', entry.get("summary") or entry.get("description") or "")
                excerpt = " ".join(excerpt.split())
                if len(excerpt) > 200:
                    excerpt = excerpt[:200] + "..."
                
                raw_date = entry.get("published") or entry.get("updated")
                pub_str = ""
                if raw_date:
                    try:
                        p_dt = parser.parse(str(raw_date))
                        if p_dt.tzinfo is None:
                            p_dt = p_dt.replace(tzinfo=ZoneInfo("UTC"))
                        p_local = p_dt.astimezone(ZoneInfo("America/Los_Angeles"))
                        pub_str = p_local.strftime("%a, %b %d, %Y")
                    except Exception:
                        pub_str = ""
                        
                stories.append({
                    "title": title,
                    "link": link,
                    "excerpt": excerpt or "Click to read full update.",
                    "published": pub_str
                })
    except Exception as e:
        print(f"   ⚠️ RSS feed warning [{clean_url[:60]}]: {e}")
        
    return stories

def parse_espn_data(raw_json):
    """Extracts record, standing summary, and next game info from ESPN REST payloads."""
    if not raw_json or not isinstance(raw_json, dict):
        return {}
    
    summary = {
        "record": "",
        "standing": "",
        "next_game": None
    }
    
    try:
        team_obj = raw_json.get("team", {})
        record_obj = team_obj.get("record", {})
        items = record_obj.get("items", [])
        if items and isinstance(items, list):
            summary["record"] = items[0].get("summary", "")
        
        summary["standing"] = team_obj.get("standingSummary", "")
        
        next_event = team_obj.get("nextEvent", [])
        if next_event and isinstance(next_event, list) and len(next_event) > 0:
            evt = next_event[0]
            summary["next_game"] = {
                "name": evt.get("name", ""),
                "date": evt.get("date", "")
            }
    except Exception as e:
        print(f"   ⚠️ ESPN payload parse notice: {e}")
        
    return summary

def parse_mlb_data(raw_json):
    """Extracts record and league rank info from MLB Stats API payloads."""
    if not raw_json or not isinstance(raw_json, dict):
        return {}
    
    summary = {
        "record": "",
        "standing": "",
        "next_game": None
    }
    
    try:
        teams = raw_json.get("teams", [])
        if teams and isinstance(teams, list) and len(teams) > 0:
            tm = teams[0]
            rec = tm.get("record", {})
            wins = rec.get("wins")
            losses = rec.get("losses")
            pct = rec.get("winningPercentage")
            if wins is not None and losses is not None:
                summary["record"] = f"{wins}-{losses}"
                if pct:
                    summary["standing"] = f"Win Pct: {pct}"
    except Exception as e:
        print(f"   ⚠️ MLB payload parse notice: {e}")
        
    return summary

def run_sports_harvest():
    print("🏈 Harvesting Regional Sports Data & News Feeds...")
    
    if not os.path.exists(SPORTS_TEAMS_PATH):
        print(f"❌ Error: Source team roster `{SPORTS_TEAMS_PATH}` not found.")
        return
    
    try:
        with open(SPORTS_TEAMS_PATH, "r", encoding="utf-8") as f:
            teams_raw = json.load(f)
    except Exception as e:
        print(f"❌ Error reading sports teams JSON: {e}")
        return

    if not isinstance(teams_raw, list):
        print("❌ Error: Expected array of teams in sports_teams.json.")
        return

    compiled_sports = []
    
    for team in teams_raw:
        team_name = team.get("TeamName", "").strip()
        if not team_name:
            continue
            
        slug = slugify(team_name)
        data_feed_url = team.get("DataFeed", "").strip()
        
        # 1. Standings & Stats Harvest (Only call fetch_json_deduped if domain is a known REST API)
        stats_summary = {}
        if any(domain in data_feed_url for domain in KNOWN_JSON_DOMAINS):
            raw_data = fetch_json_deduped(data_feed_url)
            if "api.espn.com" in data_feed_url:
                stats_summary = parse_espn_data(raw_data)
            elif "statsapi.mlb.com" in data_feed_url:
                stats_summary = parse_mlb_data(raw_data)
        
        # 2. News Feeds Harvest
        news_items = []
        for feed_key in ["NewsFeed1", "NewsFeed2", "NewsFeed3"]:
            feed_url = team.get(feed_key, "").strip()
            if feed_url and feed_url.lower() != "nan":
                stories = fetch_rss_stories(feed_url, max_items=3)
                news_items.extend(stories)
                
        # 3. Assemble Team Record
        compiled_team = {
            "teamName": team_name,
            "altName": team.get("AltName", "").strip(),
            "mascot": team.get("Mascot", "").strip(),
            "slug": slug,
            "level": team.get("Level", "").strip(),
            "sport": team.get("Sport", "").strip(),
            "gender": team.get("Gender", "").strip(),
            "homeFacilityName": team.get("HomeFacilityName", "").strip(),
            "facilityAddress": team.get("FacilityAddress", "").strip(),
            "facilityCity": team.get("FacilityCity", "").strip(),
            "facilityCoordinates": team.get("FacilityCoordinates", "").strip(),
            "teamSite": team.get("TeamSite", "").strip(),
            "liveScores": team.get("LiveScores", "").strip(),
            "youTubeRSS": team.get("YouTubeRSS", "").strip(),
            "podcastRSS": team.get("PodcastRSS", "").strip(),
            "dataFeed": data_feed_url,
            "liveAudio": team.get("LiveAudio", "").strip(),
            "audioBlackout": team.get("AudioBlackout", "No").strip().lower() == "yes",
            "liveVideo": team.get("LiveVideo", "").strip(),
            "videoBlackout": team.get("VideoBlackout", "No").strip().lower() == "yes",
            "currentRecord": stats_summary.get("record", ""),
            "standingSummary": stats_summary.get("standing", ""),
            "nextGame": stats_summary.get("next_game"),
            "news": news_items
        }
        
        compiled_sports.append(compiled_team)
        print(f"   ✅ Synchronized: {team_name} ({len(news_items)} news articles)")

    output_payload = {
        "last_updated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_teams": len(compiled_sports),
        "teams": compiled_sports
    }

    with open(SPORTS_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(output_payload, f, indent=2, ensure_ascii=False)

    print(f"🏁 Sports harvest complete! ({len(compiled_sports)} teams compiled into data/sports_data.json)")

def main():
    run_sports_harvest()

if __name__ == "__main__":
    main()