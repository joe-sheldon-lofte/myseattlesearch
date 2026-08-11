import os
import json
import requests
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_PATH = os.path.join(DATA_DIR, "hourly_sports.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*"
}

LOCAL_NETWORKS = ["FOX", "CBS", "NBC", "ESPN", "ROOT Sports", "ROOT Sports NW", "KING 5", "KONG", "93.3 KJR", "710 Seattle Sports", "NFL+"]

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
    url = "https://statsapi.mlb.com/api/v1/schedule?sportId=1,11,13&teamId=136,529,487,468"
    try:
        res = session.get(url, timeout=15)
        if res.status_code != 200:
            return []
        data = res.json()
        games = []
        for date_obj in data.get("dates", []):
            for g in date_obj.get("games", []):
                away = g.get("teams", {}).get("away", {})
                home = g.get("teams", {}).get("home", {})
                status = g.get("status", {})
                games.append({
                    "game_id": f"mlb-{g.get('gamePk')}",
                    "league": "MLB/MiLB",
                    "status": status.get("detailedState", "Scheduled"),
                    "is_live": status.get("abstractGameState") == "Live",
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
        print(f"   ⚠️ MLB Hourly fetch notice: {e}")
        return []

def fetch_nhl_scores(session):
    url = "https://api-web.nhle.com/v1/score/now"
    try:
        res = session.get(url, timeout=15)
        if res.status_code != 200:
            return []
        data = res.json()
        games = []
        for g in data.get("games", []):
            away = g.get("awayTeam", {})
            home = g.get("homeTeam", {})
            if away.get("abbrev") == "SEA" or home.get("abbrev") == "SEA":
                games.append({
                    "game_id": f"nhl-{g.get('id')}",
                    "league": "NHL",
                    "status": g.get("gameState", "FUT"),
                    "is_live": g.get("gameState") == "LIVE",
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

def fetch_thescore_events(session, sport_key):
    url = f"https://api.thescore.com/{sport_key}/events"
    try:
        res = session.get(url, timeout=15)
        if res.status_code != 200:
            return []
        events = res.json()
        games = []
        for ev in events:
            away = ev.get("away_team", {})
            home = ev.get("home_team", {})
            box = ev.get("box_score") or {}
            progress = box.get("progress") or {}
            scores = box.get("score") or {}

            games.append({
                "game_id": f"{sport_key}-{ev.get('id')}",
                "league": sport_key.upper(),
                "status": ev.get("status", "pre_game"),
                "is_live": ev.get("status") == "in_progress",
                "game_date": ev.get("game_date"),
                "home_team": home.get("full_name") or home.get("name"),
                "home_score": scores.get("home", {}).get("score", 0) if isinstance(scores.get("home"), dict) else 0,
                "away_team": away.get("full_name") or away.get("name"),
                "away_score": scores.get("away", {}).get("score", 0) if isinstance(scores.get("away"), dict) else 0,
                "clock": progress.get("clock_label") or progress.get("clock"),
                "period": progress.get("segment_string"),
                "broadcast": parse_local_broadcast(ev.get("tv_listings_by_country_code")),
                "ticket_link": ev.get("stubhub_url")
            })
        return games
    except Exception as e:
        print(f"   ⚠️ theScore ({sport_key}) Hourly fetch notice: {e}")
        return []

def main():
    print("⚡ Starting Hourly Sports Scoreboard Harvester...")
    session = requests.Session()
    session.headers.update(HEADERS)

    scoreboard = {
        "last_updated_utc": datetime.now(timezone.utc).isoformat(),
        "live_games": [],
        "upcoming_games": [],
        "recent_finals": []
    }

    all_games = []
    all_games.extend(fetch_mlb_scores(session))
    all_games.extend(fetch_nhl_scores(session))
    for s_key in ["nfl", "mls", "wnba", "nwsl"]:
        all_games.extend(fetch_thescore_events(session, s_key))

    for g in all_games:
        if g.get("is_live"):
            scoreboard["live_games"].append(g)
        elif str(g.get("status")).lower() in ["final", "f"]:
            scoreboard["recent_finals"].append(g)
        else:
            scoreboard["upcoming_games"].append(g)

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(scoreboard, f, indent=2, ensure_ascii=False)

    print(f"✅ Saved clean hourly sports scoreboard ({len(all_games)} games) to {OUTPUT_PATH}")

if __name__ == "__main__":
    main()