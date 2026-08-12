# File: scripts/sports_weekly.py
import os
import re
import json
import io
import urllib3
import requests
import boto3
from PIL import Image
from datetime import datetime, timezone

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
SOURCE_TEAMS_PATH = os.path.join(DATA_DIR, "sports_teams.json")
OUTPUT_PATH = os.path.join(DATA_DIR, "weekly_sports.json")

# Cloudflare R2 S3 Credentials from Environment
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY")
R2_ENDPOINT_URL = os.environ.get("R2_ENDPOINT_URL")
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME")

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, image/*, */*"
}

# High-Res Master Vector & Raster Logo Mapping for 36 Washington Teams
DEFAULT_LOGOS = {
    "seattle-seahawks": "https://assets-sports-gcp.thescore.com/football/team/24/logo.png",
    "seattle-mariners": "https://www.mlbstatic.com/team-logos/136.svg",
    "seattle-kraken": "https://assets.nhle.com/logos/nhl/svg/SEA_light.svg",
    "seattle-sounders-fc": "https://assets-sports-gcp.thescore.com/soccer/team/1004/logo.png",
    "seattle-storm": "https://assets-sports-gcp.thescore.com/basketball/team/wnba/sea/logo.png",
    "seattle-reign-fc": "https://assets-sports-gcp.thescore.com/soccer/team/18525/logo.png",
    "seattle-seawolves": "https://seawolves.rugby/wp-content/uploads/2021/11/Seawolves_Logo_2021.png",
    "spokane-zephyr-fc": "https://www.spokanezephyrfc.com/wp-content/uploads/sites/16/2023/11/Spokane_Zephyr_FC_Logo.png",
    "tacoma-rainiers": "https://www.mlbstatic.com/team-logos/529.svg",
    "everett-aquasox": "https://www.mlbstatic.com/team-logos/403.svg",
    "spokane-indians": "https://www.mlbstatic.com/team-logos/486.svg",
    "tri-city-dust-devils": "https://www.mlbstatic.com/team-logos/468.svg",
    "spokane-velocity-fc": "https://www.spokanevelocityfc.com/wp-content/uploads/sites/15/2023/11/Spokane_Velocity_FC_Logo.png",
    "ballard-fc": "https://www.ballardfc.com/wp-content/uploads/2021/12/Ballard_FC_Logo.png",
    "seattle-thunderbirds": "https://chl.ca/whl-thunderbirds/wp-content/uploads/sites/18/2021/08/Seattle_Thunderbirds_Logo.png",
    "everett-silvertips": "https://everettsilvertips.com/wp-content/uploads/sites/11/2021/08/Everett_Silvertips_Logo.png",
    "spokane-chiefs": "https://spokanechiefs.com/wp-content/uploads/sites/12/2021/08/Spokane_Chiefs_Logo.png",
    "tri-city-americans": "https://amshockey.com/wp-content/uploads/sites/15/2021/08/Tri-City_Americans_Logo.png",
    "wenatchee-applesox": "https://applesox.com/images/logo.png",
    "bellingham-bells": "https://bellinghambells.com/wp-content/uploads/2021/03/bellingham-bells-logo.png",
    "yakima-valley-pippins": "https://pippinsbaseball.com/images/logo.png",
    "ridgefield-raptors": "https://ridgefieldraptors.com/wp-content/uploads/2018/11/Raptors_Logo_Final_Primary.png",
    "cowlitz-black-bears": "https://cowlitzblackbears.com/wp-content/uploads/2021/03/cowlitz-black-bears-logo.png",
    "walla-walla-sweets": "https://wallawallasweets.com/wp-content/uploads/2021/03/walla-walla-sweets-logo.png",
    "washington-huskies": "https://a.espncdn.com/i/teamlogos/ncaa/500/264.png",
    "washington-state-cougars": "https://a.espncdn.com/i/teamlogos/ncaa/500/265.png",
    "gonzaga-bulldogs": "https://a.espncdn.com/i/teamlogos/ncaa/500/2250.png",
    "seattle-university-redhawks": "https://a.espncdn.com/i/teamlogos/ncaa/500/2547.png",
    "eastern-washington-eagles": "https://a.espncdn.com/i/teamlogos/ncaa/500/324.png",
    "central-washington-wildcats": "https://wildcatsports.com/images/logos/site/site.png",
    "western-washington-vikings": "https://wwuvikings.com/images/logos/site/site.png",
    "seattle-pacific-falcons": "https://spufalcons.com/images/logos/site/site.png",
    "pacific-lutheran-lutes": "https://golutes.com/images/logos/site/site.png",
    "university-of-puget-sound-loggers": "https://loggerathletics.com/images/logos/site/site.png",
    "whitman-blues": "https://athletics.whitman.edu/images/logos/site/site.png",
    "whitworth-pirates": "https://whitworthpirates.com/images/logos/site/site.png"
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

def get_r2_client():
    if R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY and R2_ENDPOINT_URL:
        try:
            return boto3.client(
                "s3",
                endpoint_url=R2_ENDPOINT_URL,
                aws_access_key_id=R2_ACCESS_KEY_ID,
                aws_secret_access_key=R2_SECRET_ACCESS_KEY,
                region_name="auto"
            )
        except Exception as e:
            print(f"⚠️ Failed to initialize Cloudflare R2 client: {e}")
    return None

def process_and_upload_logo(s3_client, logo_url, team_slug):
    if not logo_url or not s3_client or not R2_BUCKET_NAME:
        return logo_url

    r2_key = f"sports/logos/{team_slug}.webp"
    public_url = f"https://assets.myseattlesearch.com/{r2_key}"
    
    try:
        res = requests.get(logo_url, headers=BROWSER_HEADERS, timeout=10, verify=False)
        if res.status_code != 200:
            return logo_url
            
        img = Image.open(io.BytesIO(res.content)).convert("RGBA")
        webp_buffer = io.BytesIO()
        img.save(webp_buffer, format="WEBP", quality=85)
        webp_buffer.seek(0)

        s3_client.put_object(
            Bucket=R2_BUCKET_NAME,
            Key=r2_key,
            Body=webp_buffer,
            ContentType="image/webp",
            CacheControl="public, max-age=31536000, immutable"
        )
        print(f"   🖼️ Logo converted & uploaded to R2: {r2_key}")
        return public_url
    except Exception as e:
        print(f"   ⚠️ Logo process notice for {team_slug}: {e}")
        return logo_url

def calculate_season_status(sport, level):
    """Dynamically calculates season period, human label, and active status flag."""
    now = datetime.now(timezone.utc)
    month = now.month
    year = now.year
    sport_lower = str(sport).lower()
    level_lower = str(level).lower()

    # 1. Baseball (MLB, MiLB, Collegiate Summer)
    if "baseball" in sport_lower:
        if "collegiate summer" in level_lower or "summer" in level_lower:
            if month in [6, 7, 8]:
                return {"season_status": "In-Season", "season_label": f"Active {year} Summer Season", "is_active_now": True}
            else:
                next_yr = year if month < 6 else year + 1
                return {"season_status": "Off-Season", "season_label": f"{next_yr} Summer Season Begins June {next_yr}", "is_active_now": False}
        else:
            if month in [4, 5, 6, 7, 8, 9]:
                return {"season_status": "In-Season", "season_label": f"Active {year} Regular Season", "is_active_now": True}
            elif month == 10:
                return {"season_status": "Postseason", "season_label": f"{year} Playoffs & World Series", "is_active_now": True}
            else:
                next_yr = year if month < 4 else year + 1
                return {"season_status": "Off-Season", "season_label": f"{next_yr} Spring Training Begins February {next_yr}", "is_active_now": False}

    # 2. Football (NFL)
    if "football" in sport_lower and "college" not in level_lower:
        if month == 8:
            return {"season_status": "Pre-Season", "season_label": f"{year} Training Camp & Preseason", "is_active_now": True}
        elif month in [9, 10, 11, 12, 1]:
            return {"season_status": "In-Season", "season_label": f"Active {year} NFL Regular Season", "is_active_now": True}
        elif month == 2:
            return {"season_status": "Postseason", "season_label": f"{year} Super Bowl & Playoffs", "is_active_now": True}
        else:
            return {"season_status": "Off-Season", "season_label": f"{year} Off-Season Workouts & Training", "is_active_now": False}

    # 3. Hockey (NHL, WHL)
    if "hockey" in sport_lower:
        if month in [10, 11, 12, 1, 2, 3, 4]:
            yr_str = f"{year}-{str(year+1)[2:]}" if month >= 8 else f"{year-1}-{str(year)[2:]}"
            return {"season_status": "In-Season", "season_label": f"Active {yr_str} Season", "is_active_now": True}
        elif month in [5, 6]:
            return {"season_status": "Postseason", "season_label": f"{year} Playoffs & Championship Series", "is_active_now": True}
        elif month == 9:
            return {"season_status": "Pre-Season", "season_label": f"{year} Training Camp", "is_active_now": True}
        else:
            next_yr = year if month >= 7 else year
            return {"season_status": "Off-Season", "season_label": f"{next_yr}-{str(next_yr+1)[2:]} Season Begins October {next_yr}", "is_active_now": False}

    # 4. Soccer (MLS, NWSL, USL, Pre-Pro)
    if "soccer" in sport_lower:
        if "pre-professional" in level_lower or "usl2" in level_lower:
            if month in [5, 6, 7]:
                return {"season_status": "In-Season", "season_label": f"Active {year} League Two Season", "is_active_now": True}
            else:
                next_yr = year if month < 5 else year + 1
                return {"season_status": "Off-Season", "season_label": f"{next_yr} Season Begins May {next_yr}", "is_active_now": False}
        else:
            if month in [2, 3, 4, 5, 6, 7, 8, 9, 10]:
                return {"season_status": "In-Season", "season_label": f"Active {year} Regular Season", "is_active_now": True}
            elif month == 11:
                return {"season_status": "Postseason", "season_label": f"{year} Cup Playoffs", "is_active_now": True}
            else:
                next_yr = year if month == 12 else year
                return {"season_status": "Off-Season", "season_label": f"{next_yr} Training Begins February {next_yr}", "is_active_now": False}

    # 5. Basketball (WNBA)
    if "basketball" in sport_lower and "college" not in level_lower:
        if month in [5, 6, 7, 8, 9]:
            return {"season_status": "In-Season", "season_label": f"Active {year} Regular Season", "is_active_now": True}
        elif month == 10:
            return {"season_status": "Postseason", "season_label": f"{year} WNBA Finals & Playoffs", "is_active_now": True}
        else:
            next_yr = year if month < 5 else year + 1
            return {"season_status": "Off-Season", "season_label": f"{next_yr} Season Begins May {next_yr}", "is_active_now": False}

    # 6. Rugby (MLR)
    if "rugby" in sport_lower:
        if month in [2, 3, 4, 5, 6, 7]:
            return {"season_status": "In-Season", "season_label": f"Active {year} Major League Rugby Season", "is_active_now": True}
        else:
            next_yr = year if month < 2 else year + 1
            return {"season_status": "Off-Season", "season_label": f"{next_yr} Season Begins February {next_yr}", "is_active_now": False}

    # 7. NCAA College Multi-Sport
    if "college" in level_lower or "ncaa" in level_lower:
        if month in [9, 10, 11, 12, 1, 2, 3, 4, 5]:
            yr_str = f"{year}-{str(year+1)[2:]}" if month >= 8 else f"{year-1}-{str(year)[2:]}"
            return {"season_status": "In-Season", "season_label": f"Active {yr_str} Collegiate Season", "is_active_now": True}
        elif month == 8:
            return {"season_status": "Pre-Season", "season_label": f"{year}-{str(year+1)[2:]} Fall Camp & Training", "is_active_now": True}
        else:
            return {"season_status": "Off-Season", "season_label": f"{year}-{str(year+1)[2:]} Competition Begins September {year}", "is_active_now": False}

    return {"season_status": "Active Year-Round", "season_label": f"{year} Program", "is_active_now": True}

def fetch_mlb_macro_standings():
    """Fetches macro standings for MLB and High-A MiLB."""
    url = "https://statsapi.mlb.com/api/v1/standings?leagueId=103,112,126"
    try:
        res = requests.get(url, headers=BROWSER_HEADERS, timeout=10, verify=False)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        print(f"   ⚠️ MLB Standings fetch notice: {e}")
    return None

def fetch_nhl_macro_standings():
    """Fetches macro standings for NHL."""
    url = "https://api-web.nhle.com/v1/standings/now"
    try:
        res = requests.get(url, headers=BROWSER_HEADERS, timeout=10, verify=False)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        print(f"   ⚠️ NHL Standings fetch notice: {e}")
    return None

def extract_team_standings(slug, mlb_data, nhl_data):
    """Extracts wins, losses, division rank, and points for matching team slug."""
    summary = {"wins": None, "losses": None, "pct": None, "rank": None, "formatted": ""}
    
    # 1. MLB / MiLB
    if mlb_data and isinstance(mlb_data, dict):
        search_key = slug.replace("seattle-", "").replace("tacoma-", "").replace("everett-", "").replace("spokane-", "").replace("tri-city-", "")
        for record in mlb_data.get("records", []):
            for tr in record.get("teamRecords", []):
                tm_name = str(tr.get("team", {}).get("name", "")).lower()
                if search_key in slugify(tm_name):
                    w = tr.get("wins")
                    l = tr.get("losses")
                    p = tr.get("winningPercentage")
                    r = tr.get("divisionRank")
                    summary["wins"] = w
                    summary["losses"] = l
                    summary["pct"] = p
                    summary["rank"] = r
                    summary["formatted"] = f"{w}-{l} (Rank: #{r})" if r else f"{w}-{l}"
                    return summary

    # 2. NHL (Kraken)
    if nhl_data and isinstance(nhl_data, dict) and slug == "seattle-kraken":
        for tr in nhl_data.get("standings", []):
            if tr.get("teamAbbrev", {}).get("default") == "SEA":
                w = tr.get("wins")
                l = tr.get("losses")
                ot = tr.get("otLosses", 0)
                pts = tr.get("points")
                r = tr.get("divisionSequence")
                summary["wins"] = w
                summary["losses"] = l
                summary["rank"] = r
                summary["formatted"] = f"{w}-{l}-{ot} ({pts} pts, #{r} Div)" if ot else f"{w}-{l} ({pts} pts)"
                return summary

    return summary

def main():
    print("📅 Starting Macro Weekly Sports Metadata & Logo Engine...")
    s3_client = get_r2_client()

    # Load 36 teams harvested from Google Sheet
    raw_teams = []
    if os.path.exists(SOURCE_TEAMS_PATH):
        try:
            with open(SOURCE_TEAMS_PATH, "r", encoding="utf-8") as f:
                raw_teams = json.load(f)
        except Exception as e:
            print(f"❌ Error loading sports_teams.json: {e}")

    if not raw_teams or not isinstance(raw_teams, list):
        print("⚠️ Warning: sports_teams.json missing or invalid. Falling back to default list.")
        raw_teams = []

    # Fetch macro league standings
    mlb_standings = fetch_mlb_macro_standings()
    nhl_standings = fetch_nhl_macro_standings()

    compiled_teams = []
    for t in raw_teams:
        team_name = t.get("TeamName", "").strip()
        if not team_name:
            continue
            
        slug = slugify(team_name)
        sport = t.get("Sport", "").strip()
        level = t.get("Level", "").strip()
        
        # Determine best source logo URL
        source_logo = DEFAULT_LOGOS.get(slug, "")
        
        # Convert and upload logo to Cloudflare R2 WebP
        r2_logo_url = process_and_upload_logo(s3_client, source_logo, slug)
        
        # Calculate dynamic season status and active label
        status_info = calculate_season_status(sport, level)
        
        # Extract standings
        standings_info = extract_team_standings(slug, mlb_standings, nhl_standings)

        team_record = {
            "teamName": team_name,
            "altName": t.get("AltName", "").strip(),
            "mascot": t.get("Mascot", "").strip(),
            "slug": slug,
            "level": level,
            "sport": sport,
            "gender": t.get("Gender", "").strip(),
            "homeFacilityName": t.get("HomeFacilityName", "").strip(),
            "facilityAddress": t.get("FacilityAddress", "").strip(),
            "facilityCity": t.get("FacilityCity", "").strip(),
            "facilityCoordinates": t.get("FacilityCoordinates", "").strip(),
            "teamSite": t.get("TeamSite", "").strip(),
            "liveScores": t.get("LiveScores", "").strip(),
            "dataFeed": t.get("DataFeed", "").strip(),
            "liveAudio": t.get("LiveAudio", "").strip(),
            "audioBlackout": str(t.get("AudioBlackout", "No")).strip().lower() == "yes",
            "liveVideo": t.get("LiveVideo", "").strip(),
            "videoBlackout": str(t.get("VideoBlackout", "No")).strip().lower() == "yes",
            "logo": r2_logo_url,
            "season_status": status_info["season_status"],
            "season_label": status_info["season_label"],
            "is_active_now": status_info["is_active_now"],
            "standings": standings_info
        }

        compiled_teams.append(team_record)
        print(f"   ✅ Processed [{status_info['season_status']}]: {team_name}")

    output_payload = {
        "last_updated_utc": datetime.now(timezone.utc).isoformat(),
        "total_teams": len(compiled_teams),
        "teams": compiled_teams
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output_payload, f, indent=2, ensure_ascii=False)

    print(f"🏁 Macro Weekly Sports Engine Complete! ({len(compiled_teams)} teams saved to {OUTPUT_PATH})")

if __name__ == "__main__":
    main()