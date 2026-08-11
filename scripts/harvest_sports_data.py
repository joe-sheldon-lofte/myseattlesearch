import os
import json
import requests
from datetime import datetime, timezone

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*"
}

ENDPOINTS = {
    "pro_sports": {
        # Official direct APIs (Working)
        "mlb_official": "https://statsapi.mlb.com/api/v1/schedule?sportId=1",
        "nhl_official": "https://api-web.nhle.com/v1/score/now",
        # TheScore API alternatives (Bypasses GitHub Actions 403 blocks)
        "nfl": "https://api.thescore.com/nfl/events",
        "mls": "https://api.thescore.com/mls/events",
        "wnba": "https://api.thescore.com/wnba/events",
        "nwsl": "https://api.thescore.com/nwsl/events"
    },
    "minor_leagues": {
        # Official MLB / MiLB APIs (Working)
        "milb_schedule": "https://statsapi.mlb.com/api/v1/schedule?sportId=11,13&teamId=529,487,468",
        "milb_standings": "https://statsapi.mlb.com/api/v1/standings?leagueId=126",
        # TheScore soccer alternatives
        "usl_league_one": "https://api.thescore.com/usl/events"
    },
    "college_sports": {
        # TheScore & NCAA Casper feeds (Cloud friendly)
        "ncaa_football": "https://api.thescore.com/ncaaf/events",
        "ncaa_mens_basketball": "https://api.thescore.com/ncaab/events",
        "ncaa_womens_basketball": "https://api.thescore.com/wcb/events"
    }
}

def fetch_feed(session: requests.Session, url: str) -> dict:
    try:
        response = session.get(url, timeout=15)
        response.raise_for_status()
        text = response.text.strip()
        if not text:
            return {"status": "error", "message": "Empty response body", "url": url}
        return response.json()
    except Exception as err:
        return {"status": "error", "message": str(err), "url": url}

def main():
    print("Starting sports data harvest...")

    output_data = {
        "metadata": {
            "last_updated_utc": datetime.now(timezone.utc).isoformat(),
            "description": "Comprehensive raw sports data feed from open APIs."
        },
        "pro_sports": {},
        "minor_leagues": {},
        "college_sports": {}
    }

    session = requests.Session()
    session.headers.update(HEADERS)

    for category, feeds in ENDPOINTS.items():
        print(f"Fetching {category}...")
        for key, url in feeds.items():
            print(f"  - Pulling {key}...")
            output_data[category][key] = fetch_feed(session, url)

    output_dir = "data"
    os.makedirs(output_dir, exist_ok=True)
    file_path = os.path.join(output_dir, "sports_data.json")

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2)

    print(f"Harvest complete! File saved to {file_path}")

if __name__ == "__main__":
    main()
