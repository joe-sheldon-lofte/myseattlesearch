# File: scripts/daily/sports_daily.py
import os
import json
import math
import time
import requests
import urllib3
from datetime import datetime, timezone

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

# Washington Team Identifiers
WA_EXACT_IDENTITIES = [
    "seahawks", "mariners", "kraken", "sounders", "seawolves", "rainiers",
    "aquasox", "dust devils", "velocity fc", "zephyr", "thunderbirds",
    "silvertips", "applesox", "pippins", "cowlitz black bears", "sweets",
    "ballard fc"
]

NON_WA_EXCLUSIONS = [
    "commanders", "spirit", "wizards", "nationals", "mystics",
    "george washington", "washington &", "washington univ", "washington college",
    "uconn", "northern illinois", "miami (oh)", "southeast missouri", "maine black bears"
]

WA_CITIES = [
    "seattle", "spokane", "tacoma", "everett", "tri-city", "tri cities",
    "wenatchee", "bellingham", "yakima"
]

def slugify(text):
    if not text:
        return ""
    text = str(text).lower().strip()
    out = [ch if ch.isalnum() else '-' for ch in text]
    res = "".join(out)
    while '--' in res:
        res = res.replace('--', '-')
    return res.strip('-')

def is_wa_team_name(team_name):
    if not team_name:
        return False
    t = str(team_name).lower().strip()
    if any(ex in t for ex in NON_WA_EXCLUSIONS):
        return False
    if any(m in t for m in WA_EXACT_IDENTITIES):
        return True
    if "washington huskies" in t or "uw huskies" in t or (t == "huskies" and "wash" in t):
        return True
    if "washington state" in t or "wsu" in t or ("cougars" in t and ("wsu" in t or "wash" in t)):
        return True
    if "gonzaga" in t:
        return True
    if "seattle u" in t or "seattle redhawks" in t or "seattle university" in t:
        return True
    if "eastern wash" in t or "central wash" in t or "western wash" in t:
        return True
    if "seattle pacific" in t or "pacific lutheran" in t or "puget sound loggers" in t or "whitman" in t or "whitworth" in t:
        return True
    if "seattle storm" in t or "seattle reign" in t:
        return True
    if any(c in t for c in WA_CITIES):
        return True
    return False

def fetch_json_deduped(session, url, timeout=10):
    if not url or not isinstance(url, str) or not url.strip() or url.strip().lower() == "nan":
        return None
    clean_url = url.strip()
    if clean_url in HTTP_CACHE:
        return HTTP_CACHE[clean_url]
    try:
        res = session.get(clean_url, timeout=timeout, verify=False)
        if res.status_code == 200:
            text_start = res.text.strip()[:10]
            if text_start.startswith("{") or text_start.startswith("["):
                data = res.json()
                HTTP_CACHE[clean_url] = data
                return data
    except Exception as e:
        print(f"   ⚠️ API fetch notice [{clean_url[:60]}]: {e}")
    HTTP_CACHE[clean_url] = None
    return None

def fetch_nhl_kraken_deep(session):
    """Fetches deep roster statistics, points, and goalie metrics for Seattle Kraken."""
    url = "https://api-web.nhle.com/v1/club-stats/SEA/now"
    data = fetch_json_deduped(session, url, timeout=10)
    leaders = []
    player_stats = []
    
    if data and isinstance(data, dict):
        skaters = data.get("skaters", [])
        goalies = data.get("goalies", [])
        
        # Sort top skaters by points
        skaters_sorted = sorted(skaters, key=lambda s: s.get("points", 0), reverse=True)
        for s in skaters_sorted[:10]:
            first = s.get("firstName", {}).get("default", "")
            last = s.get("lastName", {}).get("default", "")
            name = f"{first} {last}".strip()
            player_stats.append({
                "player": name,
                "position": s.get("positionCode"),
                "sweater": s.get("sweaterNumber"),
                "games_played": s.get("gamesPlayed"),
                "goals": s.get("goals"),
                "assists": s.get("assists"),
                "points": s.get("points"),
                "plus_minus": s.get("plusMinus"),
                "headshot": s.get("headshot")
            })

        # Top goalies
        for g in goalies[:3]:
            first = g.get("firstName", {}).get("default", "")
            last = g.get("lastName", {}).get("default", "")
            name = f"{first} {last}".strip()
            player_stats.append({
                "player": name,
                "position": "G",
                "sweater": g.get("sweaterNumber"),
                "games_played": g.get("gamesPlayed"),
                "wins": g.get("wins"),
                "losses": g.get("losses"),
                "save_pct": round(g.get("savePctg", 0), 3) if g.get("savePctg") else None,
                "gaa": round(g.get("goalsAgainstAverage", 0), 2) if g.get("goalsAgainstAverage") else None,
                "headshot": g.get("headshot")
            })

        # Key stat leaders cards
        if skaters_sorted:
            top_g = max(skaters, key=lambda s: s.get("goals", 0), default=None)
            top_a = max(skaters, key=lambda s: s.get("assists", 0), default=None)
            top_pts = skaters_sorted[0]
            if top_g and top_g.get("goals", 0) > 0:
                leaders.append({
                    "category": "Goals",
                    "player": f"{top_g.get('firstName', {}).get('default', '')} {top_g.get('lastName', {}).get('default', '')}".strip(),
                    "value": str(top_g.get("goals")),
                    "sweater": top_g.get("sweaterNumber"),
                    "position": top_g.get("positionCode"),
                    "headshot": top_g.get("headshot")
                })
            if top_a and top_a.get("assists", 0) > 0:
                leaders.append({
                    "category": "Assists",
                    "player": f"{top_a.get('firstName', {}).get('default', '')} {top_a.get('lastName', {}).get('default', '')}".strip(),
                    "value": str(top_a.get("assists")),
                    "sweater": top_a.get("sweaterNumber"),
                    "position": top_a.get("positionCode"),
                    "headshot": top_a.get("headshot")
                })
            if top_pts and top_pts.get("points", 0) > 0:
                leaders.append({
                    "category": "Points",
                    "player": f"{top_pts.get('firstName', {}).get('default', '')} {top_pts.get('lastName', {}).get('default', '')}".strip(),
                    "value": str(top_pts.get("points")),
                    "sweater": top_pts.get("sweaterNumber"),
                    "position": top_pts.get("positionCode"),
                    "headshot": top_pts.get("headshot")
                })
        if goalies:
            top_w = max(goalies, key=lambda g: g.get("wins", 0), default=None)
            if top_w and top_w.get("wins", 0) > 0:
                leaders.append({
                    "category": "Goalie Wins",
                    "player": f"{top_w.get('firstName', {}).get('default', '')} {top_w.get('lastName', {}).get('default', '')}".strip(),
                    "value": str(top_w.get("wins")),
                    "sweater": top_w.get("sweaterNumber"),
                    "position": "G",
                    "headshot": top_w.get("headshot")
                })

    return leaders, player_stats

def fetch_mlb_team_leaders(session, team_id):
    """Fetches batting & pitching leaders from MLB Stats API."""
    season_year = datetime.now(timezone.utc).year
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/leaders?leaderCategories=homeRuns,runsBattedIn,battingAverage,earnedRunAverage,strikeouts,wins&season={season_year}"
    data = fetch_json_deduped(session, url, timeout=10)
    leaders = []
    
    cat_labels = {
        "homeRuns": "Home Runs",
        "runsBattedIn": "RBI",
        "battingAverage": "Batting Avg",
        "earnedRunAverage": "ERA",
        "strikeouts": "Strikeouts",
        "wins": "Wins"
    }

    if data and isinstance(data, dict):
        for cat_obj in data.get("teamLeaders", []):
            cat_name = cat_obj.get("leaderCategory")
            label = cat_labels.get(cat_name, cat_name)
            top_leaders = cat_obj.get("leaders", [])
            if top_leaders:
                lead = top_leaders[0]
                person = lead.get("person", {})
                pid = person.get("id")
                val = lead.get("value")
                pname = person.get("fullName", "")
                headshot = f"https://img.mlbstatic.com/mlb-photos/image/upload/d_people:generic:headshot:67:current.png/w_213,q_auto:best/v1/people/{pid}/headshot/67/current" if pid else None
                leaders.append({
                    "category": label,
                    "player": pname,
                    "value": str(val),
                    "sweater": None,
                    "position": None,
                    "headshot": headshot
                })
    return leaders

def parse_espn_team_deep(raw_json):
    """Parses ESPN Team API for live records, standing summary, next game, and player leaders."""
    summary = {
        "record": "",
        "standing": "",
        "next_game": None,
        "team_leaders": [],
        "injuries": []
    }
    if not raw_json or not isinstance(raw_json, dict):
        return summary
    
    team = raw_json.get("team", {})
    record_items = team.get("record", {}).get("items", [])
    if record_items and isinstance(record_items, list):
        for item in record_items:
            if item.get("type") in ["total", "overall"] or item.get("description") == "Overall Record":
                summary["record"] = item.get("summary", "")
                break
        if not summary["record"] and len(record_items) > 0:
            summary["record"] = record_items[0].get("summary", "")

    summary["standing"] = str(team.get("standingSummary") or "").strip()

    next_event = team.get("nextEvent", [])
    if next_event and isinstance(next_event, list) and len(next_event) > 0:
        ev = next_event[0]
        summary["next_game"] = {
            "name": ev.get("name"),
            "date": ev.get("date"),
            "shortName": ev.get("shortName")
        }

    # ESPN Player Stat Leaders
    for cat_obj in team.get("leaders", []):
        cat_display = cat_obj.get("displayName") or cat_obj.get("name")
        for athlete_obj in cat_obj.get("leaders", []):
            val = athlete_obj.get("displayValue") or athlete_obj.get("value")
            ath = athlete_obj.get("athlete", {})
            name = ath.get("fullName") or ath.get("displayName")
            jersey = ath.get("jersey")
            pos = ath.get("position", {}).get("abbreviation")
            headshot = ath.get("headshot", {}).get("href")
            if name and val:
                summary["team_leaders"].append({
                    "category": cat_display,
                    "player": name,
                    "value": str(val),
                    "sweater": jersey,
                    "position": pos,
                    "headshot": headshot
                })

    return summary

def parse_mlb_standings(raw_json, team_name):
    if not raw_json or not isinstance(raw_json, dict):
        return {}
    summary = {"record": "", "standing": "", "next_game": None}
    search_term = team_name.lower().replace("seattle ", "").replace("tacoma ", "").replace("everett ", "").replace("spokane ", "").replace("tri-city ", "")
    try:
        for div_record in raw_json.get("records", []):
            for tr in div_record.get("teamRecords", []):
                tm = tr.get("team", {})
                t_name = tm.get("name", "").lower()
                if search_term in t_name or slugify(team_name) in slugify(t_name):
                    w = tr.get("wins")
                    l = tr.get("losses")
                    pct = tr.get("winningPercentage")
                    div_rank = tr.get("divisionRank")
                    div_gb = tr.get("divisionGamesBack")
                    if w is not None and l is not None:
                        summary["record"] = f"{w}-{l}"
                    parts = []
                    if div_rank: parts.append(f"Rank: #{div_rank}")
                    if div_gb: parts.append(f"GB: {div_gb}")
                    elif pct: parts.append(f"Pct: {pct}")
                    summary["standing"] = " | ".join(parts)
                    return summary
    except Exception as e:
        print(f"   ⚠️ MLB standings notice for {team_name}: {e}")
    return summary

def parse_nhl_standings(raw_json, team_name):
    if not raw_json or not isinstance(raw_json, dict):
        return {}
    summary = {"record": "", "standing": "", "next_game": None}
    try:
        for tr in raw_json.get("standings", []):
            abbrev = tr.get("teamAbbrev", {}).get("default", "")
            t_name = tr.get("teamName", {}).get("default", "").lower()
            if abbrev == "SEA" or "kraken" in t_name:
                w = tr.get("wins")
                l = tr.get("losses")
                otl = tr.get("otLosses", 0)
                pts = tr.get("points")
                div_rank = tr.get("divisionSequence")
                if w is not None and l is not None:
                    summary["record"] = f"{w}-{l}-{otl}" if otl else f"{w}-{l}"
                parts = []
                if div_rank: parts.append(f"Rank: #{div_rank}")
                if pts is not None: parts.append(f"Pts: {pts}")
                summary["standing"] = " | ".join(parts)
                return summary
    except Exception as e:
        print(f"   ⚠️ NHL standings notice for {team_name}: {e}")
    return summary

def parse_whl_standings(raw_json, team_name):
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
                if rank: parts.append(f"Rank: #{rank}")
                if pts is not None: parts.append(f"Pts: {pts}")
                summary["standing"] = " | ".join(parts)
                return summary
    except Exception as e:
        print(f"   ⚠️ WHL standings notice for {team_name}: {e}")
    return summary

def fetch_wa_recent_games(session):
    """Fetches box scores, odds, and recap articles for Washington pro & college teams."""
    wa_games_by_team = {}
    for sport in ["nfl", "mls", "wnba", "nwsl", "ncaaf", "ncaab"]:
        url = f"https://api.thescore.com/{sport}/events"
        events = fetch_json_deduped(session, url, timeout=10)
        if not events or not isinstance(events, list):
            continue
        for ev in events:
            if not isinstance(ev, dict):
                continue
            away = ev.get("away_team") or {}
            home = ev.get("home_team") or {}
            h_name = home.get("full_name") or home.get("name") or ""
            a_name = away.get("full_name") or away.get("name") or ""
            
            h_wa = is_wa_team_name(h_name)
            a_wa = is_wa_team_name(a_name)
            if not (h_wa or a_wa):
                continue

            scores = (ev.get("box_score") or {}).get("score") or {}
            recap = ev.get("recap_data") or {}
            preview = ev.get("preview_data") or {}
            odd = ev.get("odd") or {}

            clean_game = {
                "game_id": f"{sport}-{ev.get('id')}",
                "league": sport.upper(),
                "status": ev.get("status", "final"),
                "game_date": ev.get("game_date"),
                "home_team": h_name,
                "home_score": scores.get("home", {}).get("score") if isinstance(scores.get("home"), dict) else None,
                "away_team": a_name,
                "away_score": scores.get("away", {}).get("score") if isinstance(scores.get("away"), dict) else None,
                "headline": recap.get("headline") or preview.get("headline"),
                "abstract": recap.get("abstract") or preview.get("abstract"),
                "odds_line": odd.get("line"),
                "over_under": odd.get("over_under")
            }

            for t_name, is_target in [(h_name, h_wa), (a_name, a_wa)]:
                if is_target:
                    t_slug = slugify(t_name)
                    if t_slug not in wa_games_by_team:
                        wa_games_by_team[t_slug] = []
                    wa_games_by_team[t_slug].append(clean_game)

    return wa_games_by_team

def run_sports_daily_harvest():
    print("🏈 Harvesting Daily Washington Deep Sports Intelligence & Standings...")
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)

    if not os.path.exists(SPORTS_TEAMS_PATH):
        print(f"❌ Error: Source team roster `{SPORTS_TEAMS_PATH}` not found.")
        return

    with open(SPORTS_TEAMS_PATH, "r", encoding="utf-8") as f:
        teams_raw = json.load(f)

    if not isinstance(teams_raw, list):
        print("❌ Error: Expected array of teams in sports_teams.json.")
        return

    # 1. Harvest WA-specific boxscores & recaps
    wa_matchups = fetch_wa_recent_games(session)

    # 2. Pre-fetch NHL Kraken deep player stats
    kraken_leaders, kraken_skaters = fetch_nhl_kraken_deep(session)

    compiled_sports = []
    current_month = datetime.now(timezone.utc).month

    for team in teams_raw:
        team_name = team.get("TeamName", "").strip()
        if not team_name:
            continue

        slug = slugify(team_name)
        data_feed_url = team.get("DataFeed", "").strip()
        live_scores_url = team.get("LiveScores", "").strip()
        target_api_url = data_feed_url if data_feed_url and "http" in data_feed_url else live_scores_url

        stats_summary = {
            "record": "",
            "standing": "",
            "next_game": None,
            "team_leaders": [],
            "player_stats": []
        }

        # Collegiate Summer League (WCL) Off-Season Guard
        if "westcoastleague.com" in target_api_url and current_month not in [6, 7, 8]:
            stats_summary["standing"] = "Off-Season (June - August)"
        elif target_api_url and "http" in target_api_url:
            raw_data = fetch_json_deduped(session, target_api_url)
            if "statsapi.mlb.com" in target_api_url:
                stats_summary.update(parse_mlb_standings(raw_data, team_name))
                # MLB Mariners / MiLB affiliate leaders
                for tid, tmatch in [("136", "mariners"), ("529", "rainiers"), ("403", "aquasox"), ("486", "indians"), ("468", "dust devils")]:
                    if tmatch in slug:
                        stats_summary["team_leaders"] = fetch_mlb_team_leaders(session, tid)
                        break
            elif "api-web.nhle.com" in target_api_url:
                stats_summary.update(parse_nhl_standings(raw_data, team_name))
                if "kraken" in slug:
                    stats_summary["team_leaders"] = kraken_leaders
                    stats_summary["player_stats"] = kraken_skaters
            elif "hockeytech.com" in target_api_url:
                stats_summary.update(parse_whl_standings(raw_data, team_name))
            elif "site.api.espn.com" in target_api_url:
                stats_summary.update(parse_espn_team_deep(raw_data))

        # Match recent games
        team_recent_games = wa_matchups.get(slug, [])

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
            "teamLeaders": stats_summary.get("team_leaders", []),
            "playerStats": stats_summary.get("player_stats", []),
            "recentGames": team_recent_games[:5]
        }

        compiled_sports.append(compiled_team)
        lead_count = len(compiled_team["teamLeaders"])
        rec_str = compiled_team["currentRecord"] or "No active record"
        print(f"   ✅ Synchronized: {team_name} ({rec_str} | {lead_count} stat leaders)")

    output_payload = {
        "metadata": {
            "last_updated_utc": datetime.now(timezone.utc).isoformat(),
            "total_teams": len(compiled_sports),
            "description": "Comprehensive Washington sports intelligence with verified team records, player leaders, and game telemetry."
        },
        "teams": compiled_sports
    }

    os.makedirs(os.path.dirname(SPORTS_DATA_PATH), exist_ok=True)
    with open(SPORTS_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(output_payload, f, indent=2, ensure_ascii=False)

    print(f"🏁 Daily sports harvest complete! ({len(compiled_sports)} teams compiled into {SPORTS_DATA_PATH})")

def main():
    run_sports_daily_harvest()

if __name__ == "__main__":
    main()