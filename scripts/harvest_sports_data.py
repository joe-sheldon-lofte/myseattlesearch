import os
import json
from datetime import datetime, timezone

# Use curl_cffi to spoof browser TLS signatures and bypass Akamai 403 blocks
try:
    from curl_cffi import requests
    USE_CURL_CFFI = True
except ImportError:
    import requests
    USE_CURL_CFFI = False

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.espn.com/",
    "Origin": "https://www.espn.com"
}

ENDPOINTS = {
    "pro_sports": {
        # Official open APIs (100% cloud friendly)
        "mlb_official": "https://statsapi.mlb.com/api/v1/schedule?sportId=1",
        "nhl_official": "https://api-web.nhle.com/v1/score/now",
        # ESPN feeds (requires TLS spoofing)
        "nfl": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
        "mls": "https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/scoreboard",
        "wnba": "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard",
        "nwsl": "https://site.api.espn.com/apis/site/v2/sports/soccer/usa.nwsl/scoreboard"
    },
    "minor_leagues": {
        "milb_schedule": "https://statsapi.mlb.com/api/v1/schedule?sportId=11,13&teamId=529,487,468",
        "milb_standings": "https://statsapi.mlb.com/api/v1/standings?leagueId=126",
        "usl_league_one": "https://site.api.espn.com/apis/site/v2/sports/soccer/usa.usl.l1/scoreboard",
        "usl_super_league_w": "https://site.api.espn.com/apis/site/v2/sports/soccer/usa.w.usl.1/scoreboard",
        "mls_next_pro": "https://site.api.espn.com/apis/site/v2/sports/soccer/usa.mlsnextpro/scoreboard"
    },
    "college_sports": {
        "ncaa_football_d1": "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?teams=264,265,325",
        "ncaa_mens_basketball_d1": "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?teams=264,265,2250,325,2547",
        "ncaa_womens_basketball_d1": "https://site.api.espn.com/apis/site/v2/sports/basketball/womens-college-basketball/scoreboard?teams=264,265,2250"
    }
}

def fetch_feed(url: str) -> dict:
    try:
        if USE_CURL_CFFI:
            # Impersonate Chrome 120 browser handshake
            response = requests.get(url, headers=HEADERS, impersonate="chrome120", timeout=15)
        else:
            response = requests.get(url, headers=HEADERS, timeout=15)

        response.raise_for_status()
        text = response.text.strip()
        if not text:
            return {"status": "error", "message": "Empty response body", "url": url}

        return response.json()

    except Exception as err:
        return {"status": "error", "message": str(err), "url": url}

def main():
    print(f"Starting harvest (Using curl_cffi TLS impersonation: {USE_CURL_CFFI})...")

    output_data = {
        "metadata": {
            "last_updated_utc": datetime.now(timezone.utc).isoformat(),
            "description": "Comprehensive raw sports data feed."
        },
        "pro_sports": {},
        "minor_leagues": {},
        "college_sports": {}
    }

    for category, feeds in ENDPOINTS.items():
        print(f"Fetching {category}...")
        for key, url in feeds.items():
            print(f"  - Pulling {key}...")
            output_data[category][key] = fetch_feed(url)

    output_dir = "data"
    os.makedirs(output_dir, exist_ok=True)
    file_path = os.path.join(output_dir, "sports_data.json")

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2)

    print(f"Saved to {file_path}")

if __name__ == "__main__":
    main()
