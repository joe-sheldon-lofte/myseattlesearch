# File: scripts/daily/sports_daily.py
import os
import json
import math
import time
import io
import requests
import urllib3
import boto3
from PIL import Image
from botocore.exceptions import ClientError
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

# Cloudflare R2 Credentials
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY")
R2_ENDPOINT_URL = os.environ.get("R2_ENDPOINT_URL")
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME")

HTTP_CACHE = {}

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
    """Idempotently checks if WebP logo exists in R2; downloads and converts only if missing."""
    r2_key = f"sports/logos/{team_slug}.webp"
    public_url = f"https://assets.myseattlesearch.com/{r2_key}"

    if not s3_client or not R2_BUCKET_NAME:
        return logo_url or ""

    force_refresh = os.environ.get("FORCE_LOGO_REFRESH", "").strip().lower() in ["1", "true", "yes"]

    # 1. Existence Check: Skip network fetch if already uploaded
    if not force_refresh:
        try:
            s3_client.head_object(Bucket=R2_BUCKET_NAME, Key=r2_key)
            return public_url
        except ClientError:
            pass
        except Exception:
            pass

    if not logo_url:
        return public_url

    # 2. Upload missing logo to R2
    try:
        res = requests.get(logo_url, headers=BROWSER_HEADERS, timeout=10, verify=False)
        if res.status_code == 200:
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
            print(f"   🖼️ New team logo converted & stored in R2: {r2_key}")
            return public_url
    except Exception as e:
        print(f"   ⚠️ Logo process notice for {team_slug}: {e}")

    return public_url

def calculate_season_status(sport, level):
    """Dynamically calculates season period, human label, and active status flag."""
    now = datetime.now(timezone.utc)
    month = now.month
    year = now.year
    sport_lower = str(sport).lower()
    level_lower = str(level).lower()

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

    if "football" in sport_lower and "college" not in level_lower:
        if month == 8:
            return {"season_status": "Pre-Season", "season_label": f"{year} Training Camp & Preseason", "is_active_now": True}
        elif month in [9, 10, 11, 12, 1]:
            return {"season_status": "In-Season", "season_label": f"Active {year} NFL Regular Season", "is_active_now": True}
        elif month == 2:
            return {"season_status": "Postseason", "season_label": f"{year} Super Bowl & Playoffs", "is_active_now": True}
        else:
            return {"season_status": "Off-Season", "season_label": f"{year} Off-Season Workouts & Training", "is_active_now": False}

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

    if "basketball" in sport_lower and "college" not in level_lower:
        if month in [5, 6, 7, 8, 9]:
            return {"season_status": "In-Season", "season_label": f"Active {year} Regular Season", "is_active_now": True}
        elif month == 10:
            return {"season_status": "Postseason", "season_label": f"{year} WNBA Finals & Playoffs", "is_active_now": True}
        else:
            next_yr = year if month < 5 else year + 1
            return {"season_status": "Off-Season", "season_label": f"{next_yr} Season Begins May {next_yr}", "is_active_now": False}

    if "rugby" in sport_lower:
        if month in [2, 3, 4, 5, 6, 7]:
            return {"season_status": "In-Season", "season_label": f"Active {year} Major League Rugby Season", "is_active_now": True}
        else:
            next_yr = year if month < 2 else year + 1
            return {"season_status": "Off-Season", "season_label": f"{next_yr} Season Begins February {next_yr}", "is_active_now": False}

    if "college" in level_lower or "ncaa" in level_lower:
        if month in [9, 10, 11, 12, 1, 2, 3, 4, 5]:
            yr_str = f"{year}-{str(year+1)[2:]}" if month >= 8 else f"{year-1}-{str(year)[2:]}"
            return {"season_status": "In-Season", "season_label": f"Active {yr_str} Collegiate Season", "is_active_now": True}
        elif month == 8:
            return {"season_status": "Pre-Season", "season_label": f"{year}-{str(year+1)[2:]} Fall Camp & Training", "is_active_now": True}
        else:
            return {"season_status": "Off-Season", "season_label": f"{year}-{str(year+1)[2:]} Competition Begins September {year}", "is_active_now": False}

    return {"season_status": "Active Year-Round", "season_label": f"{year} Program", "is_active_now": True}

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
    url = "https://api-web.nhle.com/v1/club-stats/SEA/now"
    data = fetch_json_deduped(session, url, timeout=10)
    leaders = []
    player_stats = []
    
    if data and isinstance(data, dict):
        skaters = data.get("skaters", [])
        goalies = data.get("goalies", [])
        
        skaters_sorted = sorted(skaters, key=lambda s: s.get("points", 0), reverse=True)
        for s in skaters_sorted[:10]:
            first = s.get("firstName", {}).get("default", "")
            last = s.get("lastName", {}).get("default", "")
            player_stats.append({
                "player": f"{first} {last}".strip(),
                "position": s.get("positionCode"),
                "sweater": s.get("sweaterNumber"),
                "games_played": s.get("gamesPlayed"),
                "goals": s.get("goals"),
                "assists": s.get("assists"),
                "points": s.get("points"),
                "plus_minus": s.get("plusMinus"),
                "headshot": s.get("headshot")
            })

        for g in goalies[:3]:
            first = g.get("firstName", {}).get("default", "")
            last = g.get("lastName", {}).get("default", "")
            player_stats.append({
                "player": f"{first} {last}".strip(),
                "position": "G",
                "sweater": g.get("sweaterNumber"),
                "games_played": g.get("gamesPlayed"),
                "wins": g.get("wins"),
                "losses": g.get("losses"),
                "save_pct": round(g.get("savePctg", 0), 3) if g.get("savePctg") else None,
                "gaa": round(g.get("goalsAgainstAverage", 0), 2) if g.get("goalsAgainstAverage") else None,
                "headshot": g.get("headshot")
            })

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
    season_year = datetime.now(timezone.utc).year
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/leaders?leaderCategories=homeRuns,runsBattedIn,battingAverage,earnedRunAverage,strikeouts,wins&season={season_year}"
    data = fetch_json_deduped(session, url, timeout=10)
    leaders = []
    
    cat_labels = {
        "homeRuns": "Home Runs", "runsBattedIn": "RBI", "battingAverage": "Batting Avg",
        "earnedRunAverage": "ERA", "strikeouts": "Strikeouts", "wins": "Wins"
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
    summary = {
        "record": "", "standing": "", "next_game": None,
        "team_leaders": [], "injuries": []
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
    if not raw_json or not isinstance(raw_json, dict): return {}
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
    if not raw_json or not isinstance(raw_json, dict): return {}
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
    if not raw_json or not isinstance(raw_json, dict): return {}
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
    s3_client = get_r2_client()

    if not os.path.exists(SPORTS_TEAMS_PATH):
        print(f"❌ Error: Source team roster `{SPORTS_TEAMS_PATH}` not found.")
        return

    with open(SPORTS_TEAMS_PATH, "r", encoding="utf-8") as f:
        teams_raw = json.load(f)

    if not isinstance(teams_raw, list):
        print("❌ Error: Expected array of teams in sports_teams.json.")
        return

    wa_matchups = fetch_wa_recent_games(session)
    kraken_leaders, kraken_skaters = fetch_nhl_kraken_deep(session)

    compiled_sports = []
    current_month = datetime.now(timezone.utc).month

    for team in teams_raw:
        team_name = team.get("TeamName", "").strip()
        if not team_name:
            continue

        slug = slugify(team_name)
        sport = team.get("Sport", "").strip()
        level = team.get("Level", "").strip()

        # 1. Idempotent R2 WebP Logo Verification
        source_logo = DEFAULT_LOGOS.get(slug, "")
        r2_logo_url = process_and_upload_logo(s3_client, source_logo, slug)

        # 2. Season Status Engine
        status_info = calculate_season_status(sport, level)

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

        # 3. Summer Wood-Bat (WCL) Off-Season Guard
        if "westcoastleague.com" in target_api_url and current_month not in [6, 7, 8]:
            stats_summary["standing"] = "Off-Season (June - August)"
        elif target_api_url and "http" in target_api_url:
            raw_data = fetch_json_deduped(session, target_api_url)
            if "statsapi.mlb.com" in target_api_url:
                stats_summary.update(parse_mlb_standings(raw_data, team_name))
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

        team_recent_games = wa_matchups.get(slug, [])

        compiled_team = {
            "teamName": team_name,
            "altName": team.get("AltName", "").strip(),
            "mascot": team.get("Mascot", "").strip(),
            "slug": slug,
            "level": level,
            "sport": sport,
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
            "audioBlackout": str(team.get("AudioBlackout", "No")).strip().lower() == "yes",
            "liveVideo": team.get("LiveVideo", "").strip(),
            "videoBlackout": str(team.get("VideoBlackout", "No")).strip().lower() == "yes",
            "logo": r2_logo_url,
            "season_status": status_info["season_status"],
            "season_label": status_info["season_label"],
            "is_active_now": status_info["is_active_now"],
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
            "description": "Comprehensive Washington sports intelligence with verified team records, R2 WebP logos, player leaders, and game telemetry."
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