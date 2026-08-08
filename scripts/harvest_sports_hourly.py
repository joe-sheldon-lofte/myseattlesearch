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

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*"
}

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

def fetch_json_deduped(url, timeout=6):
    """Fetches JSON with browser headers, SSL fallback, deduplication, and JSON verification."""
    if not url or not isinstance(url, str) or not url.strip() or url.strip().lower() == "nan":
        return None
    
    clean_url = url.strip()
    if clean_url in HTTP_CACHE:
        return HTTP_CACHE[clean_url]

    try:
        try:
            res = requests.get(clean_url, headers=BROWSER_HEADERS, timeout=timeout, verify=True)
        except requests.exceptions.SSLError:
            res = requests.get(clean_url, headers=BROWSER_HEADERS, timeout=timeout, verify=False)

        if res.status_code == 200:
            text_start = res.text.strip()[:10]
            if text_start.startswith("{") or text_start.startswith("["):
                data = res.json()
                HTTP_CACHE[clean_url] = data
                return data
            else:
                print(f"   ⚠️ DataFeed non-JSON body [{clean_url[:60]}]")
        else:
            print(f"   ⚠️ DataFeed HTTP {res.status_code} [{clean_url[:60]}]")
    except Exception as e:
        print(f"   ⚠️ DataFeed fetch error [{clean_url[:60]}]: {e}")
    
    HTTP_CACHE[clean_url] = None
    return None

def fetch_rss_stories(url, max_items=3, timeout=5):
    """Parses up to max_items articles from an RSS feed with SSL fallback."""
    if not url or not isinstance(url, str) or not url.strip() or url.strip().lower() == "nan":
        return []
    
    clean_url = url.strip()
    stories = []
    
    try:
        try:
            res = requests.get(clean_url, headers=BROWSER_HEADERS, timeout=timeout, verify=True)
        except requests.exceptions.SSLError:
            res = requests.get(clean_url, headers=BROWSER_HEADERS, timeout=timeout, verify=False)

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
        
        # 1. Record parsing with multi-level fallbacks
        record_obj = team_obj.get("record", {})
        if isinstance(record_obj, dict):
            items = record_obj.get("items", [])
            if items and isinstance(items, list) and len(items) > 0:
                first_item = items[0]
                summary["record"] = (
                    first_item.get("summary") or 
                    first_item.get("displayValue") or 
                    first_item.get("description", "")
                )
            if not summary["record"]:
                summary["record"] = record_obj.get("summary") or record_obj.get("displayValue", "")
        
        # 2. Standing summary
        standing_val = team_obj.get("standingSummary")
        if not standing_val and isinstance(team_obj.get("standing"), dict):
            standing_val = team_obj.get("standing", {}).get("summary")
        summary["standing"] = standing_val or ""
        
        # 3. Next Game parsing
        next_events = team_obj.get("nextEvent", [])
        if next_events and isinstance(next_events, list) and len(next_events) > 0:
            evt = next_events[0]
            evt_name = evt.get("name") or evt.get("shortName") or evt.get("displayName", "")
            evt_date = evt.get("date", "")
            summary["next_game"] = {
                "name": evt_name,
                "date": evt_date
            }
    except Exception as e:
        print(f"   ⚠️ ESPN payload parse notice: {e}")
        
    return summary

def parse_mlb_data(raw_json):
    """Extracts hydrated wins, losses, and standing info from MLB Stats API payloads."""
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
            pct = rec.get("winningPercentage") or rec.get("pct")
            
            if wins is None and "leagueRecord" in rec:
                lrec = rec.get("leagueRecord", {})
                wins = lrec.get("wins")
                losses = lrec.get("losses")
                pct = pct or lrec.get("pct")
                
            if wins is not None and losses is not None:
                summary["record"] = f"{wins}-{losses}"
                
            div_rank = rec.get("divisionRank") or tm.get("divisionRank")
            div_gb = rec.get("divisionGamesBack") or rec.get("gamesBack")
            
            standing_parts = []
            if div_rank:
                standing_parts.append(f"Rank: #{div_rank}")
            if div_gb:
                standing_parts.append(f"GB: {div_gb}")
            elif pct:
                standing_parts.append(f"Pct: {pct}")
                
            summary["standing"] = " | ".join(standing_parts)
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
        
        # Evaluate DataFeed first, falling back to LiveScores if DataFeed is empty or invalid
        data_feed_url = team.get("DataFeed", "").strip()
        live_scores_url = team.get("LiveScores", "").strip()
        
        target_api_url = ""
        if any(domain in data_feed_url for domain in KNOWN_JSON_DOMAINS):
            target_api_url = data_feed_url
        elif any(domain in live_scores_url for domain in KNOWN_JSON_DOMAINS):
            target_api_url = live_scores_url

        # 1. Standings & Stats Harvest
        stats_summary = {}
        if target_api_url:
            raw_data = fetch_json_deduped(target_api_url)
            if "api.espn.com" in target_api_url or "site.api.espn.com" in target_api_url:
                stats_summary = parse_espn_data(raw_data)
            elif "statsapi.mlb.com" in target_api_url:
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
            "liveScores": live_scores_url,
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
        
        rec_str = stats_summary.get("record", "")
        log_rec = f"Record: {rec_str}" if rec_str else "No active record"
        print(f"   ✅ Synchronized: {team_name} ({log_rec} | {len(news_items)} news articles)")

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