# File: scripts/daily/sports_daily.py
import os
import json
import datetime
import urllib3
import requests

# Suppress unverified HTTPS request warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Robust Repository Root Path Resolution
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(CURRENT_DIR) == "daily":
    REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
elif os.path.basename(CURRENT_DIR) == "scripts":
    REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
else:
    REPO_ROOT = os.path.abspath(CURRENT_DIR)

DATA_DIR = os.path.join(REPO_ROOT, "data")
SPORTS_TEAMS_PATH = os.path.join(DATA_DIR, "sports_teams.json")
SPORTS_DATA_PATH = os.path.join(DATA_DIR, "sports_data.json")

HTTP_CACHE = {}

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
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

def fetch_json_deduped(url, timeout=10):
    if not url or not isinstance(url, str) or not url.strip() or url.strip().lower() == "nan":
        return None
    
    clean_url = url.strip()
    if clean_url in HTTP_CACHE:
        return HTTP_CACHE[clean_url]

    try:
        res = requests.get(clean_url, headers=BROWSER_HEADERS, timeout=timeout, verify=False)
        if res.status_code == 200:
            text_start = res.text.strip()[:10]
            if text_start.startswith("{") or text_start.startswith("["):
                data = res.json()
                HTTP_CACHE[clean_url] = data
                return data
    except Exception as e:
        print(f"   ⚠️ Standings fetch notice [{clean_url[:60]}]: {e}")
    
    HTTP_CACHE[clean_url] = None
    return None

def parse_mlb_standings(raw_json, team_name):
    """Searches MLB/MiLB standings array for matching team record."""
    if not raw_json or not isinstance(raw_json, dict):
        return {}
    
    summary = {"record": "", "standing": "", "next_game": None}
    search_term = team_name.lower().replace("seattle ", "").replace("tacoma ", "").replace("everett ", "").replace("spokane ", "").replace("tri-city ", "")
    
    try:
        records = raw_json.get("records", [])
        for div_record in records:
            team_records = div_record.get("teamRecords", [])
            for tr in team_records:
                tm = tr.get("team", {})
                t_name = tm.get("name", "").lower()
                if search_term in t_name or slugify(team_name) in slugify(t_name):
                    wins = tr.get("wins")
                    losses = tr.get("losses")
                    pct = tr.get("winningPercentage")
                    div_rank = tr.get("divisionRank")
                    div_gb = tr.get("divisionGamesBack")
                    
                    if wins is not None and losses is not None:
                        summary["record"] = f"{wins}-{losses}"
                    
                    parts = []
                    if div_rank:
                        parts.append(f"Rank: #{div_rank}")
                    if div_gb:
                        parts.append(f"GB: {div_gb}")
                    elif pct:
                        parts.append(f"Pct: {pct}")
                        
                    summary["standing"] = " | ".join(parts)
                    return summary
    except Exception as e:
        print(f"   ⚠️ MLB standings parse notice for {team_name}: {e}")
        
    return summary

def parse_nhl_standings(raw_json, team_name):
    """Searches NHL open standings API for Seattle Kraken."""
    if not raw_json or not isinstance(raw_json, dict):
        return {}
    
    summary = {"record": "", "standing": "", "next_game": None}
    
    try:
        standings = raw_json.get("standings", [])
        for tr in standings:
            abbrev = tr.get("teamAbbrev", {}).get("default", "")
            t_name = tr.get("teamName", {}).get("default", "").lower()
            if abbrev == "SEA" or "kraken" in t_name:
                wins = tr.get("wins")
                losses = tr.get("losses")
                ot_losses = tr.get("otLosses", 0)
                pts = tr.get("points")
                div_rank = tr.get("divisionSequence")
                
                if wins is not None and losses is not None:
                    summary["record"] = f"{wins}-{losses}-{ot_losses}" if ot_losses else f"{wins}-{losses}"
                
                parts = []
                if div_rank:
                    parts.append(f"Rank: #{div_rank}")
                if pts is not None:
                    parts.append(f"Pts: {pts}")
                    
                summary["standing"] = " | ".join(parts)
                return summary
    except Exception as e:
        print(f"   ⚠️ NHL standings parse notice for {team_name}: {e}")
        
    return summary

def parse_whl_standings(raw_json, team_name):
    """Searches WHL HockeyTech standings array for Washington junior hockey teams."""
    if not raw_json or not isinstance(raw_json, dict):
        return {}
    
    summary = {"record": "", "standing": "", "next_game": None}
    search_term = team_name.lower().replace("seattle ", "").replace("everett ", "").replace("spokane ", "").replace("tri-city ", "")
    
    try:
        statview = raw_json.get("SiteKit", {}).get("Statview", [])
        rows = statview if isinstance(statview, list) else statview.get("rows", []) if isinstance(statview, dict) else []
        for r in rows:
            name = str(r.get("name") or r.get("team_name") or "").lower()
            if search_term in name or slugify(team_name) in slugify(name):
                w = r.get("wins") or r.get("w")
                l = r.get("losses") or r.get("l")
                otl = r.get("ot_losses") or r.get("otl", 0)
                pts = r.get("points") or r.get("pts")
                rank = r.get("rank")
                if w is not None and l is not None:
                    summary["record"] = f"{w}-{l}-{otl}" if otl else f"{w}-{l}"
                parts = []
                if rank:
                    parts.append(f"Rank: #{rank}")
                if pts is not None:
                    parts.append(f"Pts: {pts}")
                summary["standing"] = " | ".join(parts)
                return summary
    except Exception as e:
        print(f"   ⚠️ WHL standings parse notice for {team_name}: {e}")
        
    return summary

def parse_espn_team(raw_json):
    """Parses ESPN Team API endpoints for NFL, MLS, WNBA, NWSL and NCAA College teams."""
    if not raw_json or not isinstance(raw_json, dict):
        return {}
    
    summary = {"record": "", "standing": "", "next_game": None}
    try:
        team = raw_json.get("team", {})
        record_items = team.get("record", {}).get("items", [])
        if record_items and isinstance(record_items, list):
            for item in record_items:
                if item.get("type") in ["total", "overall"] or item.get("description") == "Overall Record":
                    summary["record"] = item.get("summary", "")
                    break
            if not summary["record"] and len(record_items) > 0:
                summary["record"] = record_items[0].get("summary", "")
        
        standing = team.get("standingSummary")
        if standing:
            summary["standing"] = str(standing).strip()
            
        next_event = team.get("nextEvent", [])
        if next_event and isinstance(next_event, list) and len(next_event) > 0:
            ev = next_event[0]
            summary["next_game"] = {
                "name": ev.get("name"),
                "date": ev.get("date"),
                "shortName": ev.get("shortName")
            }
    except Exception as e:
        print(f"   ⚠️ ESPN API parse notice: {e}")
        
    return summary

def run_sports_daily_harvest():
    print("🏈 Harvesting Daily Washington Sports Standings & Records...")
    
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
        live_scores_url = team.get("LiveScores", "").strip()
        
        target_api_url = data_feed_url if data_feed_url and "http" in data_feed_url else live_scores_url

        # Standings & Records Harvest (No RSS Stories)
        stats_summary = {}
        if target_api_url and "http" in target_api_url:
            raw_data = fetch_json_deduped(target_api_url)
            if "statsapi.mlb.com" in target_api_url:
                stats_summary = parse_mlb_standings(raw_data, team_name)
            elif "api-web.nhle.com" in target_api_url:
                stats_summary = parse_nhl_standings(raw_data, team_name)
            elif "hockeytech.com" in target_api_url:
                stats_summary = parse_whl_standings(raw_data, team_name)
            elif "site.api.espn.com" in target_api_url:
                stats_summary = parse_espn_team(raw_data)
                
        # Assemble Clean Local Team Record
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
            "nextGame": stats_summary.get("next_game")
        }
        
        compiled_sports.append(compiled_team)
        
        rec_str = stats_summary.get("record", "")
        log_rec = f"Record: {rec_str}" if rec_str else "No active record"
        print(f"   ✅ Synchronized: {team_name} ({log_rec})")

    output_payload = {
        "last_updated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_teams": len(compiled_sports),
        "teams": compiled_sports
    }

    os.makedirs(os.path.dirname(SPORTS_DATA_PATH), exist_ok=True)
    with open(SPORTS_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(output_payload, f, indent=2, ensure_ascii=False)

    print(f"🏁 Daily sports harvest complete! ({len(compiled_sports)} teams compiled into data/sports_data.json)")

def main():
    run_sports_daily_harvest()

if __name__ == "__main__":
    main()