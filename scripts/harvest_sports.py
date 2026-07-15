# File: scripts/harvest_sports.py
import os
import json
import urllib.request
import ssl

def fetch_espn_endpoint(url):
    """
    Safely issues network requests to ESPN's public endpoints,
    bypassing SSL verification parameters in runner environments.
    """
    ssl_ctx = ssl._create_unverified_context()
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
        )
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=10) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"⚠️ API pipeline connection warning for {url}: {e}")
        return None

def extract_game_details(event, sport_name):
    """
    Normalizes ESPN API structures into a uniform, readable scoreboard model.
    """
    try:
        competition = event["competitions"][0]
        status_type = event["status"]["type"]
        
        # Pull team competitor details
        home_team = None
        away_team = None
        
        for competitor in competition["competitors"]:
            team_details = {
                "name": competitor["team"]["displayName"],
                "logo": competitor["team"].get("logo", ""),
                "score": competitor.get("score", "0"),
                "record": competitor["team"].get("record", "") if competitor["team"].get("record") else ""
            }
            if competitor["homeAway"] == "home":
                home_team = team_details
            else:
                away_team = team_details

        # Fallback values for empty records
        if isinstance(home_team["record"], list) and len(home_team["record"]) > 0:
            home_team["record"] = home_team["record"][0].get("summary", "")
        if isinstance(away_team["record"], list) and len(away_team["record"]) > 0:
            away_team["record"] = away_team["record"][0].get("summary", "")

        return {
            "sport": sport_name,
            "shortName": event.get("shortName", ""),
            "status": status_type.get("detail", "Scheduled"),
            "isCompleted": status_type.get("completed", False),
            "isLive": status_type.get("state", "pre") == "in",
            "home": home_team,
            "away": away_team,
            "gamecastUrl": event["links"][0]["href"] if event.get("links") else "#"
        }
    except Exception as e:
        print(f"⚠️ Error cleaning game event node: {e}")
        return None

def harvest_regional_sports():
    print("🏟️ Querying ESPN API nodes for regional WA scores...")
    
    endpoints = {
        "NFL": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
        "MLB": "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard",
        "NHL": "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard",
        "MLS": "https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/scoreboard",
        "College Football": "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard",
        "College Basketball (M)": "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard",
        "College Basketball (W)": "https://site.api.espn.com/apis/site/v2/sports/basketball/womens-college-basketball/scoreboard"
    }

    # Our curated list of local teams
    WASHINGTON_TEAMS = [
        "Seahawks", "Mariners", "Kraken", "Sounders FC", "Sounders",
        "Washington Huskies", "Washington State Cougars", "Gonzaga Bulldogs"
    ]

    scraped_games = []

    for sport_key, url in endpoints.items():
        raw_data = fetch_espn_endpoint(url)
        if not raw_data or "events" not in raw_data:
            continue
            
        for event in raw_data["events"]:
            # Check if any Washington team is playing in this game
            game_title = event.get("name", "")
            is_local_game = any(team in game_title for team in WASHINGTON_TEAMS)
            
            if is_local_game:
                game_model = extract_game_details(event, sport_key)
                if game_model:
                    scraped_games.append(game_model)

    # Output paths
    os.makedirs("data", exist_ok=True)
    destination = "data/sports_scores.json"
    
    with open(destination, "w", encoding="utf-8") as f:
        json.dump(scraped_games, f, indent=2, ensure_ascii=False)
        
    print(f"💾 Sports pipeline compilation successful. Saved {len(scraped_games)} active games -> {destination}")

if __name__ == "__main__":
    harvest_regional_sports()