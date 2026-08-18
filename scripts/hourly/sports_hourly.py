import os
import json
import re
import time
import requests
import urllib3
from datetime import datetime, timezone

# Suppress unverified HTTPS request warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Robust Repository Root Path Resolution
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(SCRIPT_DIR) == "scripts":
    REPO_ROOT = os.path.dirname(SCRIPT_DIR)
else:
    REPO_ROOT = SCRIPT_DIR

DATA_DIR = os.path.join(REPO_ROOT, "data")
OUTPUT_PATH = os.path.join(DATA_DIR, "hourly_sports.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/"
}

# 1. Washington State Locations & Distinct Identity Keywords
WA_LOCATIONS = [
    "seattle", "spokane", "tacoma", "everett", "tri-city", "tri cities", 
    "wenatchee", "bellingham", "yakima", "ridgefield", "cowlitz", "walla walla", 
    "gonzaga", "whitman", "whitworth", "ballard"
]

WA_SPECIFIC_NAMES = [
    "seahawks", "mariners", "kraken", "sounders", "seawolves", "rainiers", 
    "aquasox", "dust devils", "velocity fc", "zephyr", "thunderbirds", 
    "silvertips", "applesox", "pippins", "black bears", "sweets", 
    "huskies", "redhawks", "lutes"
]

# Exclude Washington D.C. teams to avoid false "Washington" location matches
DC_EXCLUSIONS = ["commanders", "spirit", "wizards", "nationals", "mystics"]

# Modern regional and national broadcast networks
LOCAL_NETWORKS = [
    "FOX", "CBS", "NBC", "ESPN", "KING 5", "KONG", "KSTW", "CW", "CW Seattle", 
    "93.3 KJR", "710 Seattle Sports", "NFL+", "Apple TV", "Prime Video", "Peacock", "Netflix"
]

def is_wa_team_name(team_name):
    """Evaluates whether a team name strictly belongs to Washington state."""
    if not team_name:
        return False
    t = str(team_name).lower().strip()
    
    # Exclude Washington D.C. franchises
    if any(dc in t for dc in DC_EXCLUSIONS):
        return False
        
    # Check Washington city/region names
    if any(loc in t for loc in WA_LOCATIONS):
        return True
        
    # Check unique mascot names
    if any(spec in t for spec in WA_SPECIFIC_NAMES):
        return True
        
    # Check collegiate variants
    if "washington state" in t or "wsu" in t or "u of washington" in t or "univ of washington" in t:
        return True
    if "eastern wash" in t or "central wash" in t or "western wash" in t or "seattle pacific" in t or "pacific lutheran" in t or "puget sound" in t:
        return True
        
    return False

def is_wa_game(game):
    """Filters events to strictly include games involving Washington teams."""
    home = game.get("home_team")
    away = game.get("away_team")
    return is_wa_team_name(home) or is_wa_team_name(away)

def parse_local_broadcast(tv_listings):
    if not tv_listings or not isinstance(tv_listings, dict):
        return "Check Local Listings"
    
    us_listings = tv_listings.get("us", [])
    for item in us_listings:
        name = item.get("short_name") or item.get("long_name") or ""
        if any(net.lower() in name.lower() for net in LOCAL_NETWORKS):
            return name
            
    if us_listings and isinstance(us_listings, list) and len(us_listings) > 0:
        return us_listings[0].get("short_name", "National Broadcast")
        
    return "Check Local Listings"

def fetch_mlb_scores(session):
    """Fetches live schedule and scores for MLB Mariners & MiLB WA affiliates."""
    url = "https://statsapi.mlb.com/api/v1/schedule?sportId=1,11,13,14&teamId=136,529,403,486,468"
    try:
        res = session.get(url, timeout=15, verify=False)
        if res.status_code != 200:
            return []
        data = res.json()
        games = []
        for date_obj in data.get("dates", []):
            for g in date_obj.get("games", []):
                away = g.get("teams", {}).get("away", {})
                home = g.get("teams", {}).get("home", {})
                status = g.get("status", {})
                
                abstract_state = status.get("abstractGameState", "")
                detailed_state = status.get("detailedState", "Scheduled")
                
                is_live = abstract_state == "Live"
                is_final = abstract_state == "Final" or "final" in detailed_state.lower()
                
                games.append({
                    "game_id": f"mlb-{g.get('gamePk')}",
                    "league": "MLB/MiLB",
                    "status": detailed_state,
                    "is_live": is_live,
                    "is_final": is_final,
                    "game_date": g.get("gameDate"),
                    "home_team": home.get("team", {}).get("name"),
                    "home_score": home.get("score", 0),
                    "away_team": away.get("team", {}).get("name"),
                    "away_score": away.get("score", 0),
                    "venue": g.get("venue", {}).get("name"),
                    "ticket_link": "https://www.mlb.com/tickets"
                })
        return games
    except Exception as e:
        print(f"   ⚠️ MLB/MiLB Hourly fetch notice: {e}")
        return []

def fetch_nhl_scores(session):
    """Fetches live NHL scores filtering for Seattle Kraken."""
    url = "https://api-web.nhle.com/v1/score/now"
    try:
        res = session.get(url, timeout=15, verify=False)
        if res.status_code != 200:
            return []
        data = res.json()
        games = []
        for g in data.get("games", []):
            away = g.get("awayTeam", {})
            home = g.get("homeTeam", {})
            if away.get("abbrev") == "SEA" or home.get("abbrev") == "SEA":
                game_state = g.get("gameState", "FUT")
                is_live = game_state in ["LIVE", "CRIT"]
                is_final = game_state in ["OFF", "FINAL"]
                
                games.append({
                    "game_id": f"nhl-{g.get('id')}",
                    "league": "NHL",
                    "status": game_state,
                    "is_live": is_live,
                    "is_final": is_final,
                    "game_date": g.get("startTimeUTC"),
                    "home_team": home.get("name", {}).get("default"),
                    "home_score": home.get("score", 0),
                    "away_team": away.get("name", {}).get("default"),
                    "away_score": away.get("score", 0),
                    "period": g.get("periodDescriptor", {}).get("number"),
                    "clock": g.get("clock", {}).get("timeRemaining"),
                    "ticket_link": g.get("ticketsLink")
                })
        return games
    except Exception as e:
        print(f"   ⚠️ NHL Hourly fetch notice: {e}")
        return []

def fetch_whl_scores(session):
    """Fetches WHL junior hockey schedule & scores for WA teams."""
    url = "https://lscluster.hockeytech.com/feed/?feed=modulekit&view=schedule&client_code=whl"
    try:
        res = session.get(url, timeout=15, verify=False)
        if res.status_code != 200:
            return []
        
        text = res.text.strip()
        if not (text.startswith("{") or text.startswith("[")):
            return []
            
        data = res.json()
        games = []
        
        schedule = data.get("SiteKit", {}).get("Schedule", []) if isinstance(data, dict) else []
        for g in schedule:
            home_name = g.get("home_team_name", "")
            away_name = g.get("visiting_team_name", "")
            
            game_obj = {
                "game_id": f"whl-{g.get('game_id')}",
                "league": "WHL",
                "status": g.get("status_name", "Scheduled"),
                "is_live": g.get("status") == "1",
                "is_final": g.get("status") in ["2", "3", "4"],
                "game_date": g.get("date_time"),
                "home_team": home_name,
                "home_score": int(g.get("home_goal_count", 0) or 0),
                "away_team": away_name,
                "away_score": int(g.get("visiting_goal_count", 0) or 0),
                "venue": g.get("venue_name", ""),
                "ticket_link": "https://chl.ca/whl/tickets/"
            }
            if is_wa_game(game_obj):
                games.append(game_obj)
        return games
    except Exception as e:
        print(f"   ⚠️ WHL HockeyTech Hourly fetch notice: {e}")
        return []

def fetch_thescore_events(session, sport_key):
    """Fetches pro/college league events with retry logic and PNW filtering."""
    url = f"https://api.thescore.com/{sport_key}/events"
    
    res = None
    for attempt in range(2):
        try:
            res = session.get(url, timeout=15, verify=False)
            if res.status_code == 200:
                break
        except requests.exceptions.RequestException as req_err:
            if attempt == 1:
                print(f"   ⚠️ theScore ({sport_key}) Hourly fetch notice: {req_err}")
                return []
            time.sleep(1)

    if not res or res.status_code != 200:
        return []

    try:
        events = res.json()
        games = []
        for ev in events:
            away = ev.get("away_team", {})
            home = ev.get("home_team", {})
            box = ev.get("box_score") or {}
            progress = box.get("progress") or {}
            scores = box.get("score") or {}

            ev_status = str(ev.get("status", "pre_game")).lower()
            is_live = ev_status in ["in_progress", "live"]
            is_final = ev_status in ["final", "completed"]

            game_obj = {
                "game_id": f"{sport_key}-{ev.get('id')}",
                "league": sport_key.upper(),
                "status": ev.get("status", "pre_game"),
                "is_live": is_live,
                "is_final": is_final,
                "game_date": ev.get("game_date"),
                "home_team": home.get("full_name") or home.get("name"),
                "home_score": scores.get("home", {}).get("score", 0) if isinstance(scores.get("home"), dict) else 0,
                "away_team": away.get("full_name") or away.get("name"),
                "away_score": scores.get("away", {}).get("score", 0) if isinstance(scores.get("away"), dict) else 0,
                "clock": progress.get("clock_label") or progress.get("clock"),
                "period": progress.get("segment_string"),
                "broadcast": parse_local_broadcast(ev.get("tv_listings_by_country_code")),
                "ticket_link": ev.get("stubhub_url")
            }
            
            if is_wa_game(game_obj):
                games.append(game_obj)
                
        return games
    except Exception as e:
        print(f"   ⚠️ theScore ({sport_key}) parse notice: {e}")
        return []

def main():
    print("⚡ Starting Filtered Hourly Sports Scoreboard Harvester...")
    session = requests.Session()
    session.headers.update(HEADERS)

    scoreboard = {
        "last_updated_utc": datetime.now(timezone.utc).isoformat(),
        "live_games": [],
        "upcoming_games": [],
        "recent_finals": []
    }

    all_games = []
    
    # 1. MLB Mariners & High-A MiLB Washington Teams
    all_games.extend(fetch_mlb_scores(session))
    
    # 2. NHL Seattle Kraken
    all_games.extend(fetch_nhl_scores(session))
    
    # 3. WHL Junior Hockey Washington Teams
    all_games.extend(fetch_whl_scores(session))
    
    # 4. Pro & NCAA College Sports (Filtered strictly for WA teams)
    for s_key in ["nfl", "mls", "wnba", "nwsl", "ncaaf", "ncaab"]:
        all_games.extend(fetch_thescore_events(session, s_key))

    # Categorize and deduplicate
    seen_ids = set()
    for g in all_games:
        gid = g.get("game_id")
        if gid in seen_ids:
            continue
        seen_ids.add(gid)
        
        is_live = g.pop("is_live", False)
        is_final = g.pop("is_final", False)
        
        if is_live:
            scoreboard["live_games"].append(g)
        elif is_final or str(g.get("status")).lower() in ["final", "f", "off", "completed"]:
            scoreboard["recent_finals"].append(g)
        else:
            scoreboard["upcoming_games"].append(g)

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(scoreboard, f, indent=2, ensure_ascii=False)

    print(f"✅ Saved clean WA hourly sports scoreboard ({len(seen_ids)} local games) to {OUTPUT_PATH}")

if __name__ == "__main__":
    main()