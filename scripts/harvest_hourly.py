import pandas as pd
import json
import os
import urllib.request
import urllib.parse
import ssl
from datetime import datetime

# ====================================================================
# CONFIGURATION
# ====================================================================
MARKET_DASHBOARD_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQ4Q94pArPoza2zWVI7dZagdcDBhIzdX9wtmrDbgJ_4h1rRr_WFuaMTjTfrJVVGQwbNGGLiSK2zCGnh/pub?gid=701119614&single=true&output=csv"
RATES_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQ4Q94pArPoza2zWVI7dZagdcDBhIzdX9wtmrDbgJ_4h1rRr_WFuaMTjTfrJVVGQwbNGGLiSK2zCGnh/pub?gid=1486733951&single=true&output=csv"

# Output Target Directories
OUTPUT_MARKET_FILE = "data/hourly_market.json"
OUTPUT_RATES_FILE = "data/hourly_rates.json"
SALES_JSON_FILE = "data/sales.json"  # Central real estate repository registry
OUTPUT_SPORTS_SCORES_FILE = "data/sports_scores.json"
OUTPUT_SPORTS_LINKS_FILE = "data/local_sports_links.json"
CITY_DATA_FILE = "data/city_data.json"  # Geographic source of truth for districts

# ====================================================================
# DYNAMIC SPORTS PIPELINE HELPERS
# ====================================================================

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
    """
    Gathers scores and upcoming matches from ESPN's public endpoints.
    Filters exclusively for Pacific Northwest franchises and universities.
    """
    print(" -> Querying ESPN API nodes for regional WA scores...")
    
    endpoints = {
        "NFL": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
        "MLB": "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard",
        "NHL": "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard",
        "MLS": "https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/scoreboard",
        "College Football": "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard",
        "College Basketball (M)": "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard",
        "College Basketball (W)": "https://site.api.espn.com/apis/site/v2/sports/basketball/womens-college-basketball/scoreboard"
    }

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
            game_title = event.get("name", "")
            is_local_game = any(team in game_title for team in WASHINGTON_TEAMS)
            
            if is_local_game:
                game_model = extract_game_details(event, sport_key)
                if game_model:
                    scraped_games.append(game_model)

    os.makedirs(os.path.dirname(OUTPUT_SPORTS_SCORES_FILE), exist_ok=True)
    
    with open(OUTPUT_SPORTS_SCORES_FILE, "w", encoding="utf-8") as f:
        json.dump(scraped_games, f, indent=2, ensure_ascii=False)
        
    print(f"✅ Saved {len(scraped_games)} active sports matches to {OUTPUT_SPORTS_SCORES_FILE}")

def fetch_ospi_gis_schools(lea_codes):
    """
    Queries the live Washington State OSPI GIS FeatureServer for active public high schools.
    """
    if not lea_codes:
        return []

    lea_list_str = ",".join([f"'{code}'" for code in lea_codes])
    base_url = "https://services2.arcgis.com/qvkYvS4b266YNoe2/arcgis/rest/services/Public_Schools_in_Washington_State/FeatureServer/0/query"
    where_clause = f"LEACode IN ({lea_list_str}) AND GradeMax >= 12 AND GradeMin <= 9"
    
    params = {
        "where": where_clause,
        "outFields": "SchoolName,LEACode,LEAName,County,City",
        "f": "json",
        "returnGeometry": "false"
    }
    
    encoded_params = urllib.parse.urlencode(params)
    full_url = f"{base_url}?{encoded_params}"
    ssl_context = ssl._create_unverified_context()
    
    try:
        req = urllib.request.Request(
            full_url,
            headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
        )
        print(" -> Querying WA State OSPI OpenData GIS Server...")
        with urllib.request.urlopen(req, context=ssl_context, timeout=15) as response:
            raw_data = json.loads(response.read().decode('utf-8'))
            if "features" in raw_data:
                return raw_data["features"]
            else:
                print("⚠️ GIS server returned an empty or unexpected payload structure.")
                return []
    except Exception as e:
        print(f"⚠️ OSPI GIS Server connection failed: {e}")
        return []

def get_fallback_mascot(school_name):
    """
    Assigns recognizable mascots based on keywords, defaulting to 'Athletics'.
    """
    mascots = {
        "Ballard": "Beavers", "Roosevelt": "Roughriders", "Garfield": "Bulldogs",
        "Chief Sealth": "Seahawks", "Ingraham": "Rams", "Franklin": "Quakers",
        "West Seattle": "Wildcats", "Nathan Hale": "Raiders", "Cleveland": "Eagles",
        "Edmonds-Woodway": "Warriors", "Meadowdale": "Mavericks", "Lynnwood": "Royals",
        "Mountlake Terrace": "Hawks", "Bothell": "Cougars", "Woodinville": "Falcons",
        "Inglemoor": "Vikings", "Shorewood": "Stormrays", "Shorecrest": "Highlanders",
        "Everett": "Seagulls", "Cascade": "Bruins", "Henry M. Jackson": "Timberwolves",
        "Bellevue": "Wolverines", "Newport": "Knights", "Sammamish": "Redhawks",
        "Interlake": "Saints", "Lake Washington": "Kangs", "Redmond": "Mustangs",
        "Eastlake": "Wolves", "Juanita": "Ravens", "Issaquah": "Eagles",
        "Skyline": "Spartans", "Liberty": "Patriots", "Renton": "Redhawks",
        "Hazen": "Highlanders", "Lindbergh": "Eagles", "Kentwood": "Conquerors",
        "Kentridge": "Chargers", "Kentlake": "Falcons", "Kent-Meridian": "Royals",
        "Federal Way": "Eagles", "Decatur": "Gators", "Thomas Jefferson": "Raiders",
        "Todd Beamer": "Titans", "Auburn": "Trojans", "Auburn Riverside": "Ravens",
        "Auburn Mountainview": "Lions", "Highline": "Pirates", "Mount Rainier": "Rams",
        "Evergreen": "Wolverines", "Tyee": "Totems", "Mount Si": "Wildcats",
        "Marysville Pilchuck": "Tomahawks", "Marysville Getchell": "Chargers",
        "Snohomish": "Panthers", "Glacier Peak": "Grizzlies", "Lake Stevens": "Vikings",
        "Monroe": "Bearcats", "Arlington": "Eagles", "Stanwood": "Spartans"
    }
    for key, mascot in mascots.items():
        if key in school_name:
            return mascot
    return "Athletics"

def generate_sports_directory():
    """
    Reads the geographic database of target cities, extracts State OSPI district numbers,
    queries the GIS database, and outputs a dynamic high school sports portal catalog.
    """
    print(" -> Compiling high school sports directory...")
    if not os.path.exists(CITY_DATA_FILE):
        print(f"⚠️ Warning: Source file '{CITY_DATA_FILE}' is missing. Skipping sports directory gen.")
        return

    with open(CITY_DATA_FILE, "r", encoding="utf-8") as f:
        try:
            cities_list = json.load(f)
        except json.JSONDecodeError:
            print("⚠️ Warning: city_data.json formatting is corrupt. Skipping sports directory gen.")
            return

    if not isinstance(cities_list, list):
        cities_list = list(cities_list.values())

    districts_metadata = {}
    for entry in cities_list:
        district_name = entry.get("School_District", entry.get("School District", "")).strip()
        ospi_number = entry.get("School_District_OSPI", entry.get("OSPI", entry.get("OSPI_Number", "")))
        county_raw = entry.get("County", "").strip().lower()
        
        if not district_name or not ospi_number:
            continue

        lea_code = str(ospi_number).strip().zfill(5)
        slug = district_name.lower().replace(" ", "-").replace(".", "").replace(",", "")
        
        if slug not in districts_metadata:
            districts_metadata[slug] = {
                "districtName": district_name,
                "slug": slug,
                "leaCode": lea_code,
                "county": "snohomish" if "snohomish" in county_raw else "king",
                "schools": []
            }

    unique_lea_codes = list(set([d["leaCode"] for d in districts_metadata.values()]))
    features = fetch_ospi_gis_schools(unique_lea_codes)
    
    matched_count = 0
    if features:
        for item in features:
            attributes = item.get("attributes", {})
            school_name = attributes.get("SchoolName", "").strip()
            lea_code = str(attributes.get("LEACode", "")).strip().zfill(5)
            
            if not school_name:
                continue

            ignore_keywords = ["Alternative", "Virtual", "Online", "Academy", "Center", "Opportunity", "Parent", "Transition", "School District"]
            if any(keyword in school_name for keyword in ignore_keywords):
                continue

            for slug, dist in districts_metadata.items():
                if dist["leaCode"] == lea_code:
                    if not any(s["name"] == school_name for s in dist["schools"]):
                        school_name_escaped = urllib.parse.quote(school_name)
                        league_url = "https://www.wescoathletics.com/" if dist["county"] == "snohomish" else "https://www.kingcoathletics.com/"
                        
                        dist["schools"].append({
                            "name": school_name,
                            "mascot": get_fallback_mascot(school_name),
                            "leagueUrl": league_url,
                            "mensUrl": f"https://www.maxpreps.com/search/school.aspx?q={school_name_escaped}&state=wa",
                            "womensUrl": f"https://www.maxpreps.com/search/school.aspx?q={school_name_escaped}&state=wa"
                        })
                        matched_count += 1

    # Safe compile-time fallback in case the state service has a connectivity failure
    if matched_count == 0:
        print("⚠️ No schools retrieved from OSPI. Deploying safe fallback generator...")
        for slug, dist in districts_metadata.items():
            clean_name = dist["districtName"].replace("School District", "").replace("Public Schools", "").strip()
            fallback_school = f"{clean_name} High School"
            school_name_escaped = urllib.parse.quote(fallback_school)
            league_url = "https://www.wescoathletics.com/" if dist["county"] == "snohomish" else "https://www.kingcoathletics.com/"
            
            dist["schools"].append({
                "name": fallback_school,
                "mascot": "Athletics",
                "leagueUrl": league_url,
                "mensUrl": f"https://www.maxpreps.com/search/school.aspx?q={school_name_escaped}&state=wa",
                "womensUrl": f"https://www.maxpreps.com/search/school.aspx?q={school_name_escaped}&state=wa"
            })
            matched_count += 1

    compiled_districts_list = list(districts_metadata.values())
    compiled_districts_list.sort(key=lambda x: x["districtName"])
    final_output = [d for d in compiled_districts_list if len(d["schools"]) > 0]

    os.makedirs(os.path.dirname(OUTPUT_SPORTS_LINKS_FILE), exist_ok=True)
    with open(OUTPUT_SPORTS_LINKS_FILE, "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2, ensure_ascii=False)

    print(f"✅ Saved sports directory with {len(final_output)} districts to {OUTPUT_SPORTS_LINKS_FILE}")


# ====================================================================
# MAIN HARVEST CONTROL FLOW
# ====================================================================

def harvest_hourly_data():
    print("Fetching Hourly Dashboard & Rates Data...")
    try:
        print(" -> Downloading Market Dashboard...")
        df_market = pd.read_csv(MARKET_DASHBOARD_CSV_URL)
        if 'City' in df_market.columns:
            df_market = df_market.dropna(subset=['City'])
        df_market = df_market.fillna("")
        
        market_records = df_market.to_dict(orient='records')
        os.makedirs(os.path.dirname(OUTPUT_MARKET_FILE), exist_ok=True)
        
        with open(OUTPUT_MARKET_FILE, 'w', encoding='utf-8') as f:
            json.dump(market_records, f, indent=4)
        print(f"✅ Saved {len(market_records)} cities to {OUTPUT_MARKET_FILE}")

        print(" -> Downloading Mortgage Rates...")
        df_rates = pd.read_csv(RATES_CSV_URL)
        df_rates = df_rates.fillna("")
        
        rates_records = df_rates.to_dict(orient='records')
        with open(OUTPUT_RATES_FILE, 'w', encoding='utf-8') as f:
            json.dump(rates_records, f, indent=4)
        print(f"✅ Saved {len(rates_records)} daily rate entries to {OUTPUT_RATES_FILE}")

        # ====================================================================
        # AUTOMATED REAL-TIME DAYS ON MARKET (DOM) CALCULATION STAGE
        # ====================================================================
        print(" -> Analyzing Portfolio Registry for Days on Market (DOM)...")
        if os.path.exists(SALES_JSON_FILE):
            with open(SALES_JSON_FILE, 'r', encoding='utf-8') as f:
                try:
                    sales_data = json.load(f)
                except json.JSONDecodeError:
                    print(f"❌ Error: {SALES_JSON_FILE} contains corrupted or invalid JSON markup structure.")
                    sales_data = None

            if sales_data is not None:
                today_date = datetime.now().date()
                calculated_listings_count = 0
                
                for listing in sales_data:
                    status = listing.get("Status", "").strip()
                    
                    if status == "Sold":
                        continue
                    
                    else:
                        start_date_string = listing.get("Selling Date")
                        
                        if start_date_string and str(start_date_string).strip():
                            try:
                                list_date_object = datetime.strptime(str(start_date_string).strip(), "%m/%d/%Y").date()
                                elapsed_days = (today_date - list_date_object).days
                                listing["DOM"] = max(0, elapsed_days)
                                calculated_listings_count += 1
                            except ValueError:
                                listing["DOM"] = "-"
                        else:
                            listing["DOM"] = "-"
                
                with open(SALES_JSON_FILE, 'w', encoding='utf-8') as f:
                    json.dump(sales_data, f, indent=4, ensure_ascii=False)
                print(f"✅ Dynamically calibrated live DOM track values for {calculated_listings_count} properties.")
        else:
            print(f"⚠️ Secondary Data Alert: File '{SALES_JSON_FILE}' was not detected. Skipping DOM math stages.")

        # ====================================================================
        # AUTOMATED SPORTS INGESTION PIPELINE STAGES
        # ====================================================================
        print(" -> Initializing Local Sports Ingestion Pipelines...")
        
        try:
            harvest_regional_sports()
        except Exception as e:
            print(f"⚠️ Warning: Regional sports harvest encountered an exception: {e}")

        try:
            generate_sports_directory()
        except Exception as e:
            print(f"⚠️ Warning: Sports directory compilation encountered an exception: {e}")

        print("🎉 Hourly data harvest complete!")
        
    except Exception as e:
        print(f"❌ Error harvesting hourly data: {e}")
        exit(1)

if __name__ == "__main__":
    harvest_hourly_data()