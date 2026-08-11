import os
import json
import requests
from datetime import datetime, timezone

# Headers to prevent requests from being blocked by anti-bot rules
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Endpoints mapping covering all leagues, minor leagues, and college sports
ENDPOINTS = {
    "pro_sports": {
        "nfl": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
        "mlb": "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard",
        "nhl": "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard",
        "mls": "https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/scoreboard",
        "wnba": "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard",
        "nwsl": "https://site.api.espn.com/apis/site/v2/sports/soccer/usa.nwsl/scoreboard"
    },
    "minor_leagues": {
        "milb_schedule": "https://statsapi.mlb.com/api/v1/schedule?sportId=11,13&teamId=529,487,468",
        "milb_standings": "https://statsapi.mlb.com/api/v1/standings?leagueId=126",
        "usl_league_one": "https://site.api.espn.com/apis/site/v2/sports/soccer/usa.usl.l1/scoreboard",
        "usl_super_league_w": "https://site.api.espn.com/apis/site/v2/sports/soccer/usa.w.usl.1/scoreboard",
        "mls_next_pro": "https://site.api.espn.com/apis/site/v2/sports/soccer/usa.mlsnextpro/scoreboard",
        "whl_hockey": "https://lscluster.hockeytech.com/feed/index.php?feed=statviewfeed&view=schedule&client_code=whl&key=41b12024197022d1"
    },
    "college_sports": {
        "ncaa_football_d1": "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?teams=264,265,325",
        "ncaa_mens_basketball_d1": "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?teams=264,265,2250,325,2547",
        "ncaa_womens_basketball_d1": "https://site.api.espn.com/apis/site/v2/sports/basketball/womens-college-basketball/scoreboard?teams=264,265,2250",
        "ncaa_womens_volleyball_d1": "https://site.api.espn.com/apis/site/v2/sports/volleyball/womens-college-volleyball/scoreboard?teams=264,265",
        "ncaa_softball_d1": "https://site.api.espn.com/apis/site/v2/sports/softball/college-softball/scoreboard?teams=264,2547"
    }
}

def fetch_feed(url: str) -> dict:
    """Helper function to safely fetch JSON data from a feed endpoint."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "url": url
        }

def main():
    print("Starting sports data fetch...")
    
    output_data = {
        "metadata": {
            "last_updated_utc": datetime.now(timezone.utc).isoformat(),
            "description": "Comprehensive raw data feed dump for Pro, Minor, and College sports."
        },
        "pro_sports": {},
        "minor_leagues": {},
        "college_sports": {}
    }

    # Iterate through categories and pull raw responses
    for category, feeds in ENDPOINTS.items():
        print(f"Fetching {category}...")
        for key, url in feeds.items():
            print(f"  - Pulling {key}...")
            output_data[category][key] = fetch_feed(url)

    # Ensure output directory exists
    output_dir = "data"
    os.makedirs(output_dir, exist_ok=True)
    file_path = os.path.join(output_dir, "sports_data.json")

    # Save to JSON file
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2)

    print(f"Successfully saved all sports data to {file_path}")

if __name__ == "__main__":
    main()
