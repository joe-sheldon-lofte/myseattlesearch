# File: scripts/generate_sports_directory.py
import os
import json
import urllib.request
import urllib.parse
import ssl

def fetch_ospi_gis_schools(lea_codes):
    """
    Queries the official Washington State OSPI GIS REST Feature Server.
    Filters for active public schools carrying high school grade spans (9-12)
    associated with our specific district LEA codes.
    """
    if not lea_codes:
        return []

    # Standardize LEA Codes into a clean string array for the SQL query
    lea_list_str = ",".join([f"'{code}'" for code in lea_codes])
    
    # OSPI GIS FeatureServer Endpoint - Washington Public Schools
    base_url = "https://services2.arcgis.com/qvkYvS4b266YNoe2/arcgis/rest/services/Public_Schools_in_Washington_State/FeatureServer/0/query"
    
    # SQL query: Match our district codes and select schools teaching 10th/11th/12th grades (High Schools)
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
        print("🌐 Querying WA State OSPI OpenData GIS Server...")
        with urllib.request.urlopen(req, context=ssl_context, timeout=15) as response:
            raw_data = json.loads(response.read().decode('utf-8'))
            
            # Verify valid features returned from ESRI schema
            if "features" in raw_data:
                return raw_data["features"]
            else:
                print("⚠️ GIS server returned an empty or unexpected payload structure.")
                return []
    except Exception as e:
        print(f"❌ OSPI GIS Server connection failed: {e}")
        return []

def get_fallback_mascot(school_name):
    """
    Quick helper to assign recognizable local mascots, falling back to 'Athletics'.
    """
    mascots = {
        "Ballard": "Beavers",
        "Roosevelt": "Roughriders",
        "Garfield": "Bulldogs",
        "Chief Sealth": "Seahawks",
        "Ingraham": "Rams",
        "Franklin": "Quakers",
        "West Seattle": "Wildcats",
        "Nathan Hale": "Raiders",
        "Cleveland": "Eagles",
        "Edmonds-Woodway": "Warriors",
        "Meadowdale": "Mavericks",
        "Lynnwood": "Royals",
        "Mountlake Terrace": "Hawks",
        "Bothell": "Cougars",
        "Woodinville": "Falcons",
        "Inglemoor": "Vikings",
        "Shorewood": "Stormrays",
        "Shorecrest": "Highlanders",
        "Everett": "Seagulls",
        "Cascade": "Bruins",
        "Henry M. Jackson": "Timberwolves",
        "Bellevue": "Wolverines",
        "Newport": "Knights",
        "Sammamish": "Redhawks",
        "Interlake": "Saints",
        "Lake Washington": "Kangs",
        "Redmond": "Mustangs",
        "Eastlake": "Wolves",
        "Juanita": "Ravens",
        "Issaquah": "Eagles",
        "Skyline": "Spartans",
        "Liberty": "Patriots",
        "Renton": "Redhawks",
        "Hazen": "Highlanders",
        "Lindbergh": "Eagles",
        "Kentwood": "Conquerors",
        "Kentridge": "Chargers",
        "Kentlake": "Falcons",
        "Kent-Meridian": "Royals",
        "Federal Way": "Eagles",
        "Decatur": "Gators",
        "Thomas Jefferson": "Raiders",
        "Todd Beamer": "Titans",
        "Auburn": "Trojans",
        "Auburn Riverside": "Ravens",
        "Auburn Mountainview": "Lions",
        "Highline": "Pirates",
        "Mount Rainier": "Rams",
        "Evergreen": "Wolverines",
        "Tyee": "Totems",
        "Mount Si": "Wildcats",
        "Marysville Pilchuck": "Tomahawks",
        "Marysville Getchell": "Chargers",
        "Snohomish": "Panthers",
        "Glacier Peak": "Grizzlies",
        "Lake Stevens": "Vikings",
        "Monroe": "Bearcats",
        "Arlington": "Eagles",
        "Stanwood": "Spartans"
    }
    for key, mascot in mascots.items():
        if key in school_name:
            return mascot
    return "Athletics"

def generate_sports_directory():
    city_data_path = "data/city_data.json"
    output_path = "data/local_sports_links.json"
    
    if not os.path.exists(city_data_path):
        print(f"❌ Aborting: Source file '{city_data_path}' is missing.")
        return

    with open(city_data_path, "r", encoding="utf-8") as f:
        try:
            cities_list = json.load(f)
        except json.JSONDecodeError:
            print("❌ Aborting: city_data.json formatting is corrupt.")
            return

    # Normalize source input
    if not isinstance(cities_list, list):
        cities_list = list(cities_list.values())

    # Map target metadata dynamically from your source of truth database
    districts_metadata = {}
    for entry in cities_list:
        district_name = entry.get("School_District", entry.get("School District", "")).strip()
        ospi_number = entry.get("School_District_OSPI", entry.get("OSPI", entry.get("OSPI_Number", "")))
        county_raw = entry.get("County", "").strip().lower()
        
        if not district_name or not ospi_number:
            continue

        # OSPI LEA codes inside GIS databases are 5-character zero-padded strings
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

    # Pull list of unique district codes to feed the GIS query
    unique_lea_codes = list(set([d["leaCode"] for d in districts_metadata.values()]))
    
    # Query live state database
    features = fetch_ospi_gis_schools(unique_lea_codes)
    
    # Group matched schools back into our district configurations
    matched_count = 0
    if features:
        # Loop through ArcGIS results
        for item in features:
            attributes = item.get("attributes", {})
            school_name = attributes.get("SchoolName", "").strip()
            lea_code = str(attributes.get("LEACode", "")).strip().zfill(5)
            
            if not school_name:
                continue

            # Bypass alternative, virtual, or adult-learning campuses to keep links clean
            ignore_keywords = ["Alternative", "Virtual", "Online", "Academy", "Center", "Opportunity", "Parent", "Transition", "School District"]
            if any(keyword in school_name for keyword in ignore_keywords):
                continue

            # Match school to its parent district metadata structure
            for slug, dist in districts_metadata.items():
                if dist["leaCode"] == lea_code:
                    # Guard against duplicates
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

    # ROBUST PIPELINE GUARD: If API call failed or returned empty, build fallback structures
    # This prevents your Eleventy site builds from ever failing due to an external server timeout.
    if matched_count == 0:
        print("⚠️ No schools retrieved from OSPI. Deploying static fallback generator...")
        for slug, dist in districts_metadata.items():
            # Form standard high school names programmatically
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

    # Format the dictionary output back into a sorted list
    compiled_districts_list = list(districts_metadata.values())
    compiled_districts_list.sort(key=lambda x: x["districtName"])

    # Eliminate districts that generated no viable public high schools
    final_output = [d for d in compiled_districts_list if len(d["schools"]) > 0]

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2, ensure_ascii=False)

    print(f"📊 Process Complete! Structured {len(final_output)} school districts. Saved to -> {output_path}")

if __name__ == "__main__":
    generate_sports_directory()