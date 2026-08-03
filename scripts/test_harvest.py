import os
import json
import math
import urllib.request
import urllib.parse
from datetime import datetime

# Path references
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")

# Primary King & Snohomish Flood Gauge USGS Station IDs
KING_SNO_RIVER_GAUGES = [
    "12119000",  # Cedar River at Renton
    "12113000",  # Green River at Auburn
    "12149000",  # Snoqualmie River near Carnation
    "12155300",  # Snohomish River at Snohomish
    "12134500",  # Skykomish River near Gold Bar
    "12125200",  # Sammamish River at Bothell
    "12167000"   # Stillaguamish River at Arlington
]

# King and Snohomish School District Fallback Names
KING_SNO_DISTRICTS = [
    "seattle", "edmonds", "everett", "shoreline", "mukilteo", "northshore",
    "bellevue", "renton", "highline", "kent", "issaquah", "lake washington",
    "snoqualmie valley", "riverview", "snohomish", "lake stevens", "marysville",
    "arlington", "stanwood-camano", "monroe", "sultan", "granite falls",
    "mercer island", "tahoma", "auburn"
]

# Regional ACS 5-Year Municipal Baseline Estimates (Fallback matrix for Census API rate limits)
REGIONAL_DEMOGRAPHICS_BASELINE = {
    "snohomish_county_avg": {"income": 100042, "age": 38.5, "owner_pct": 66.8, "renter_pct": 33.2, "remote_pct": 18.4},
    "king_county_avg": {"income": 116259, "age": 37.2, "owner_pct": 57.1, "renter_pct": 42.9, "remote_pct": 24.1},
    "cities": {
        "edmonds": {"income": 112450, "age": 46.2, "owner_pct": 68.4, "renter_pct": 31.6, "remote_pct": 21.8},
        "lynnwood": {"income": 77210, "age": 37.8, "owner_pct": 45.2, "renter_pct": 54.8, "remote_pct": 14.5},
        "mountlake-terrace": {"income": 89450, "age": 38.1, "owner_pct": 56.3, "renter_pct": 43.7, "remote_pct": 17.2},
        "seattle": {"income": 115400, "age": 35.8, "owner_pct": 44.8, "renter_pct": 55.2, "remote_pct": 29.4},
        "bellevue": {"income": 140250, "age": 38.9, "owner_pct": 55.1, "renter_pct": 44.9, "remote_pct": 31.2},
        "everett": {"income": 72400, "age": 36.1, "owner_pct": 43.9, "renter_pct": 56.1, "remote_pct": 12.8},
        "shoreline": {"income": 95800, "age": 40.2, "owner_pct": 62.4, "renter_pct": 37.6, "remote_pct": 20.1},
        "bothell": {"income": 118900, "age": 38.4, "owner_pct": 67.2, "renter_pct": 32.8, "remote_pct": 23.5},
        "kirkland": {"income": 132100, "age": 37.5, "owner_pct": 58.9, "renter_pct": 41.1, "remote_pct": 28.7},
        "redmond": {"income": 150200, "age": 35.2, "owner_pct": 54.2, "renter_pct": 45.8, "remote_pct": 34.6},
        "woodinville": {"income": 128500, "age": 41.1, "owner_pct": 71.4, "renter_pct": 28.6, "remote_pct": 22.9},
        "kenmore": {"income": 114600, "age": 40.0, "owner_pct": 73.1, "renter_pct": 26.9, "remote_pct": 21.0},
        "lake-forest-park": {"income": 131200, "age": 45.1, "owner_pct": 82.5, "renter_pct": 17.5, "remote_pct": 25.4},
        "mukilteo": {"income": 119800, "age": 42.8, "owner_pct": 69.8, "renter_pct": 30.2, "remote_pct": 19.8},
        "snohomish": {"income": 88400, "age": 39.1, "owner_pct": 61.2, "renter_pct": 38.8, "remote_pct": 13.9},
        "lake-stevens": {"income": 102100, "age": 35.4, "owner_pct": 78.4, "renter_pct": 21.6, "remote_pct": 14.1},
        "marysville": {"income": 84500, "age": 36.2, "owner_pct": 68.9, "renter_pct": 31.1, "remote_pct": 10.8},
        "monroe": {"income": 91200, "age": 35.9, "owner_pct": 64.1, "renter_pct": 35.9, "remote_pct": 11.5},
        "renton": {"income": 89100, "age": 36.8, "owner_pct": 51.2, "renter_pct": 48.8, "remote_pct": 16.4},
        "kent": {"income": 76800, "age": 34.9, "owner_pct": 49.5, "renter_pct": 50.5, "remote_pct": 12.1},
        "auburn": {"income": 78900, "age": 35.1, "owner_pct": 54.8, "renter_pct": 45.2, "remote_pct": 11.8},
        "federal-way": {"income": 74200, "age": 36.5, "owner_pct": 53.1, "renter_pct": 46.9, "remote_pct": 13.0},
        "issaquah": {"income": 134800, "age": 38.0, "owner_pct": 63.5, "renter_pct": 36.5, "remote_pct": 27.8},
        "sammamish": {"income": 195200, "age": 40.8, "owner_pct": 86.9, "renter_pct": 13.1, "remote_pct": 35.1},
        "mercer-island": {"income": 170400, "age": 45.6, "owner_pct": 72.8, "renter_pct": 27.2, "remote_pct": 30.5},
        "snoqualmie": {"income": 162100, "age": 36.4, "owner_pct": 81.2, "renter_pct": 18.8, "remote_pct": 26.2},
        "brier": {"income": 126400, "age": 44.5, "owner_pct": 88.1, "renter_pct": 11.9, "remote_pct": 18.9}
    }
}

def slugify(text):
    """Generate a clean URL slug from any city name string."""
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

def clean_city_name(name):
    """Normalize municipal names for cross-dataset matching."""
    if not name or not isinstance(name, str):
        return ""
    return name.lower().replace("city of ", "").replace("town of ", "").strip()

def http_get_raw(url, extra_headers=None, timeout=30):
    """Robust HTTP GET text helper returning raw string output and HTTP status code."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) RealEstateDataBot/1.0",
        "Accept": "application/json, text/plain, */*"
    }
    if extra_headers:
        headers.update(extra_headers)
        
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_bytes = resp.read()
            return resp.status, raw_bytes.decode("utf-8")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else ""
        return e.code, body
    except Exception as e:
        return 0, ""

def http_get_json(url, extra_headers=None, timeout=30):
    """Utility helper for HTTP GET requests returning decoded JSON objects."""
    status, raw_text = http_get_raw(url, extra_headers=extra_headers, timeout=timeout)
    if status == 200 and raw_text and not raw_text.strip().startswith("<"):
        try:
            return json.loads(raw_text)
        except Exception:
            pass
    return None

def save_json(filename, data):
    """Save formatted JSON output to data directory."""
    os.makedirs(DATA_DIR, exist_ok=True)
    target_path = os.path.join(DATA_DIR, filename)
    with open(target_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Successfully generated: {target_path}")

# ==============================================================================
# SCHEMA PRE-PROCESSING ENGINE
# ==============================================================================
def load_city_data():
    """
    Load city_data.json and normalize capitalized keys ('City', 'Latitude',
    'Federal ID', 'OSPI District ID') into a standardized list of dicts.
    """
    if not os.path.exists(CITY_DATA_PATH):
        print(f"Error: {CITY_DATA_PATH} not found.")
        return []
        
    with open(CITY_DATA_PATH, "r", encoding="utf-8") as f:
        raw_data = json.load(f)
        
    raw_list = []
    if isinstance(raw_data, dict):
        for key, details in raw_data.items():
            if isinstance(details, dict):
                item = dict(details)
                item["_raw_key"] = key
                raw_list.append(item)
    elif isinstance(raw_data, list):
        raw_list = raw_data

    normalized = []
    for item in raw_list:
        raw_name = item.get("City") or item.get("name") or item.get("cityName") or item.get("_raw_key") or ""
        if not raw_name:
            continue
            
        slug = slugify(raw_name)
        
        # Coordinates parsing
        lat = item.get("Latitude") or item.get("latitude") or item.get("lat")
        lon = item.get("Longitude") or item.get("longitude") or item.get("lng") or item.get("lon")
        try:
            lat_float = float(lat)
            lon_float = float(lon)
        except (ValueError, TypeError):
            lat_float, lon_float = None, None

        # Census FIPS Place Code parsing ('Federal ID')
        raw_fips = item.get("Federal ID") or item.get("federal_id") or item.get("fips") or ""
        clean_fips = str(raw_fips).strip().strip("'").strip('"')
        if clean_fips and clean_fips != "None" and clean_fips.isdigit():
            clean_fips = clean_fips.zfill(5)
        else:
            clean_fips = ""

        # OSPI District ID parsing ('OSPI District ID')
        raw_ospi = item.get("OSPI District ID") or item.get("ospi_id") or item.get("district_id") or ""
        clean_ospi = str(raw_ospi).strip()
        if clean_ospi == "None":
            clean_ospi = ""

        normalized.append({
            "slug": slug,
            "name": str(raw_name).strip(),
            "latitude": lat_float,
            "longitude": lon_float,
            "federal_id": clean_fips,
            "ospi_id": clean_ospi,
            "school_district": str(item.get("School District") or "").strip()
        })

    print(f"Pre-processed {len(normalized)} normalized city records from city_data.json.")
    return normalized

# ==============================================================================
# 1. DEMOGRAPHICS HARVESTER (US Census ACS 5-Year API with Baseline Matrix)
# ==============================================================================
def harvest_demographics(cities):
    print("Harvesting City-Level Demographics via US Census Bureau ACS 5-Year API...")
    raw_key = os.environ.get("CENSUS_API_KEY", "").strip().strip("'").strip('"')

    census_by_place = {}
    
    # Try querying Census API if key is present
    if raw_key:
        for vintage in ["2022", "2021"]:
            url = f"https://api.census.gov/data/{vintage}/acs/acs5?get=NAME,B19013_001E,B01002_001E,B25003_002E,B25003_003E&for=place:*&in=state:53&key={raw_key}"
            res = http_get_json(url, timeout=20)
            if res and isinstance(res, list) and len(res) >= 2:
                print(f"Successfully retrieved Census ACS 5-Year dataset (Vintage {vintage}).")
                headers = res[0]
                for row in res[1:]:
                    row_dict = dict(zip(headers, row))
                    place_fips = str(row_dict.get("place", "")).zfill(5)
                    census_by_place[place_fips] = row_dict
                break

    output = {}
    for city in cities:
        slug = city["slug"]
        name = city["name"]
        fips = city["federal_id"]
        
        if not slug:
            continue

        c_data = census_by_place.get(fips) if fips and census_by_place else None
        
        def safe_float(val, default=0.0):
            try:
                v = float(val)
                return v if v >= 0 else default
            except (ValueError, TypeError):
                return default

        if c_data:
            income = int(safe_float(c_data.get("B19013_001E")))
            age = safe_float(c_data.get("B01002_001E"))
            owners = safe_float(c_data.get("B25003_002E"))
            renters = safe_float(c_data.get("B25003_003E"))
            total_units = owners + renters
            owner_pct = round((owners / total_units * 100), 1) if total_units > 0 else 0.0
            renter_pct = round((renters / total_units * 100), 1) if total_units > 0 else 0.0
            remote_pct = 18.5  # Regional average fallback
        else:
            # Fallback to ACS regional baseline estimates matrix
            base = REGIONAL_DEMOGRAPHICS_BASELINE["cities"].get(slug)
            if not base:
                base = REGIONAL_DEMOGRAPHICS_BASELINE["snohomish_county_avg"] if "county" in slug or "snohomish" in slug else REGIONAL_DEMOGRAPHICS_BASELINE["king_county_avg"]
            
            income = base.get("income", 95000)
            age = base.get("age", 38.5)
            owner_pct = base.get("owner_pct", 60.0)
            renter_pct = base.get("renter_pct", 40.0)
            remote_pct = base.get("remote_pct", 18.0)

        output[slug] = {
            "name": name,
            "fips_place": fips,
            "median_household_income": income,
            "median_age": age,
            "owner_occupied_pct": owner_pct,
            "renter_occupied_pct": renter_pct,
            "remote_worker_pct": remote_pct,
            "last_updated": datetime.utcnow().isoformat() + "Z"
        }
            
    print(f"Successfully compiled city demographics for {len(output)} cities.")
    if output:
        save_json("city_demographics.json", output)

# ==============================================================================
# 2. WEATHER HARVESTER (Open-Meteo Chunked Batches)
# ==============================================================================
def harvest_weather(cities):
    print("Harvesting Weather Data via Open-Meteo...")
    valid_cities = [c for c in cities if c["latitude"] is not None and c["longitude"] is not None]
    if not valid_cities:
        print("Weather Harvest Warning: No valid city coordinates found.")
        return

    chunk_size = 10
    output = {}
    
    for i in range(0, len(valid_cities), chunk_size):
        chunk = valid_cities[i:i + chunk_size]
        lats = [str(c["latitude"]) for c in chunk]
        lons = [str(c["longitude"]) for c in chunk]
        
        params = {
            "latitude": ",".join(lats),
            "longitude": ",".join(lons),
            "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,uv_index_max",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "timezone": "America/Los_Angeles"
        }
        
        url = f"https://api.open-meteo.com/v1/forecast?{urllib.parse.urlencode(params)}"
        try:
            results = http_get_json(url, timeout=15)
            if results:
                if isinstance(results, dict):
                    results = [results]
                for idx, city in enumerate(chunk):
                    if idx < len(results):
                        res = results[idx]
                        output[city["slug"]] = {
                            "name": city["name"],
                            "last_updated": datetime.utcnow().isoformat() + "Z",
                            "current": res.get("current", {}),
                            "forecast": res.get("daily", {})
                        }
        except Exception as e:
            print(f"Weather Batch Error (Chunk {i}): {e}")
            
    if output:
        print(f"Successfully compiled weather for {len(output)} cities.")
        save_json("city_weather.json", output)

# ==============================================================================
# 3. AMENITIES HARVESTER (Expanded OpenStreetMap Overpass GET Query)
# ==============================================================================
def harvest_amenities(cities):
    print("Harvesting Municipal Amenities via Expanded Puget Sound Overpass Query...")
    valid_cities = [c for c in cities if c["latitude"] is not None and c["longitude"] is not None]
    if not valid_cities:
        return

    bbox = "47.0,-122.6,48.2,-121.8"
    overpass_query = f"""[out:json][timeout:60];(nwr["leisure"="dog_park"]({bbox});nwr["amenity"="cafe"]({bbox});nwr["leisure"="park"]({bbox});nwr["natural"="beach"]({bbox});nwr["shop"="pet"]({bbox});nwr["leisure"="golf_course"]({bbox});nwr["craft"="brewery"]({bbox});nwr["amenity"="pub"]({bbox});nwr["craft"="winery"]({bbox});nwr["shop"="wine"]({bbox}););out center;"""
    
    overpass_endpoints = [
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
        "https://overpass-api.de/api/interpreter",
        "https://lz4.overpass-api.de/api/interpreter"
    ]
    
    nodes = []
    encoded_query = urllib.parse.quote(overpass_query)

    for ep in overpass_endpoints:
        url = f"{ep}?data={encoded_query}"
        res = http_get_json(url, timeout=50)
        if res and isinstance(res, dict) and "elements" in res:
            nodes = res["elements"]
            print(f"Retrieved {len(nodes)} regional amenity nodes from {ep}.")
            break

    if not nodes:
        print("Amenities Harvest Error: Unable to retrieve Overpass nodes across all mirrors.")
        return

    output = {}
    radius_deg = 0.035  # ~2.5 mile spatial buffer around city centroid
    
    for city in valid_cities:
        slug = city["slug"]
        clat = city["latitude"]
        clon = city["longitude"]
        
        counts = {
            "dog_parks": 0,
            "coffee_shops": 0,
            "parks": 0,
            "beaches": 0,
            "pet_stores": 0,
            "golf_courses": 0,
            "breweries_pubs": 0,
            "wineries_wine_shops": 0
        }
        
        for node in nodes:
            nlat = node.get("lat") or node.get("center", {}).get("lat")
            nlon = node.get("lon") or node.get("center", {}).get("lon")
            try:
                nlat = float(nlat)
                nlon = float(nlon)
            except (ValueError, TypeError):
                continue
                
            if abs(nlat - clat) <= radius_deg and abs(nlon - clon) <= radius_deg:
                tags = node.get("tags", {})
                leisure = tags.get("leisure")
                amenity = tags.get("amenity")
                natural = tags.get("natural")
                shop = tags.get("shop")
                craft = tags.get("craft")

                if leisure == "dog_park":
                    counts["dog_parks"] += 1
                elif amenity == "cafe":
                    counts["coffee_shops"] += 1
                elif leisure == "park":
                    counts["parks"] += 1
                elif natural == "beach":
                    counts["beaches"] += 1
                elif shop == "pet":
                    counts["pet_stores"] += 1
                elif leisure == "golf_course":
                    counts["golf_courses"] += 1
                elif craft == "brewery" or amenity == "pub":
                    counts["breweries_pubs"] += 1
                elif craft == "winery" or shop == "wine":
                    counts["wineries_wine_shops"] += 1
                    
        output[slug] = {
            "name": city["name"],
            "amenities": counts,
            "last_updated": datetime.utcnow().isoformat() + "Z"
        }
        
    print(f"Successfully calculated amenities across {len(output)} cities.")
    save_json("city_amenities.json", output)

# ==============================================================================
# 4. ENVIRONMENT HARVESTER (King & Snohomish Flood Gauges)
# ==============================================================================
def harvest_environment(cities):
    print("Harvesting Targeted King & Snohomish River Flood Gauges via USGS...")
    stations_param = ",".join(KING_SNO_RIVER_GAUGES)
    usgs_url = f"https://waterservices.usgs.gov/nwis/iv/?format=json&sites={stations_param}&parameterCd=00060,00065&siteStatus=active"
    
    try:
        res = http_get_json(usgs_url, timeout=20)
        if res:
            time_series = res.get("value", {}).get("timeSeries", [])
            gauge_data = []
            
            for ts in time_series:
                site_name = ts.get("sourceInfo", {}).get("siteName")
                values = ts.get("values", [{}])[0].get("value", [{}])
                current_val = values[-1].get("value") if values else None
                unit = ts.get("variable", {}).get("unit", {}).get("unitCode")
                
                if current_val and current_val != "-999999":
                    gauge_data.append({
                        "site_name": site_name,
                        "reading": current_val,
                        "unit": unit
                    })
                    
            output = {
                "regional_water_gauges": gauge_data,
                "last_updated": datetime.utcnow().isoformat() + "Z"
            }
            save_json("city_environment.json", output)
    except Exception as e:
        print(f"Environment Harvest Error: {e}")

# ==============================================================================
# 5. SCHOOLS HARVESTER (OSPI Numbers & District Filter)
# ==============================================================================
def harvest_schools(cities):
    print("Harvesting OSPI School Data via WA Open Data...")
    
    target_ospi_ids = set()
    target_district_names = set()
    for c in cities:
        if c.get("ospi_id"):
            target_ospi_ids.add(c["ospi_id"])
        if c.get("school_district"):
            target_district_names.add(c["school_district"].lower())
            
    print(f"Targeting {len(target_ospi_ids)} explicit OSPI District IDs and {len(target_district_names)} district names.")

    endpoints = ["wvqy-yp3m", "q4ba-s3jc", "dij7-mbxg"]
    records = None
    
    for ep in endpoints:
        url = f"https://data.wa.gov/resource/{ep}.json?$limit=10000"
        try:
            records = http_get_json(url, timeout=25)
            if records and isinstance(records, list):
                print(f"Connected to OSPI dataset endpoint: {ep} (Retrieved {len(records)} records)")
                break
        except Exception:
            continue
            
    if records:
        school_summary = {}
        for rec in records:
            district_name = rec.get("district_name") or rec.get("districtname") or rec.get("organizationname") or ""
            district_code = str(rec.get("district_code") or rec.get("districtcode") or rec.get("county_district_number") or "").strip()
            
            d_lower = district_name.lower()
            is_match = False
            
            if district_code and district_code in target_ospi_ids:
                is_match = True
            elif d_lower and (d_lower in target_district_names or any(target in d_lower for target in KING_SNO_DISTRICTS)):
                is_match = True
                
            if is_match and district_name:
                if district_name not in school_summary:
                    school_summary[district_name] = {
                        "district_name": district_name,
                        "district_code": district_code,
                        "records_count": 0
                    }
                school_summary[district_name]["records_count"] += 1
            
        output = {
            "districts": school_summary,
            "last_updated": datetime.utcnow().isoformat() + "Z"
        }
        print(f"Successfully grouped school records across {len(school_summary)} local districts.")
        save_json("city_schools.json", output)
    else:
        print("Schools Harvest Error: All OSPI endpoints unreachable.")

# ==============================================================================
# 6. GEOMETRY SIMPLIFICATION & WSDOT BOUNDARY IMPORT
# ==============================================================================
def perpendicular_distance(point, line_start, line_end):
    if line_start == line_end:
        return math.hypot(point[0] - line_start[0], point[1] - line_start[1])
    
    dx = line_end[0] - line_start[0]
    dy = line_end[1] - line_start[1]
    mag = math.hypot(dx, dy)
    if mag == 0.0:
        return 0.0
        
    u = ((point[0] - line_start[0]) * dx + (point[1] - line_start[1]) * dy) / (mag * mag)
    if u < 0.0 or u > 1.0:
        ix = line_start[0] if u < 0.0 else line_end[0]
        iy = line_start[1] if u < 0.0 else line_end[1]
    else:
        ix = line_start[0] + u * dx
        iy = line_start[1] + u * dy
        
    return math.hypot(point[0] - ix, point[1] - iy)

def rdp_simplify(points, epsilon=0.0008):
    if len(points) < 4:
        return points
        
    dmax = 0.0
    index = 0
    end = len(points) - 1
    
    for i in range(1, end):
        d = perpendicular_distance(points[i], points[0], points[end])
        if d > dmax:
            index = i
            dmax = d
            
    if dmax > epsilon:
        rec1 = rdp_simplify(points[:index+1], epsilon)
        rec2 = rdp_simplify(points[index:], epsilon)
        return rec1[:-1] + rec2
    else:
        return [points[0], points[end]]

def simplify_geometry(geometry, epsilon=0.0008):
    g_type = geometry.get("type")
    coords = geometry.get("coordinates", [])
    
    if g_type == "Polygon":
        new_coords = [rdp_simplify(ring, epsilon) for ring in coords]
        return {"type": "Polygon", "coordinates": new_coords}
    elif g_type == "MultiPolygon":
        new_coords = [[rdp_simplify(ring, epsilon) for ring in poly] for poly in coords]
        return {"type": "MultiPolygon", "coordinates": new_coords}
    return geometry

def harvest_boundaries(cities):
    print("Harvesting & Simplifying WA City Boundaries via WSDOT GIS REST...")
    wsdot_url = "https://data.wsdot.wa.gov/arcgis/rest/services/Shared/PoliAdminBndryData/MapServer/1/query?where=1%3D1&outFields=CityName&outSR=4326&f=geojson"
    
    try:
        geojson = http_get_json(wsdot_url, timeout=30)
        if geojson and "features" in geojson:
            target_slugs = {}
            for c in cities:
                cleaned_name = clean_city_name(c["name"])
                if cleaned_name:
                    target_slugs[cleaned_name] = c["slug"]
                    
            simplified_features = []
            
            for feature in geojson["features"]:
                raw_city_name = feature.get("properties", {}).get("CityName", "")
                cleaned_name = clean_city_name(raw_city_name)
                
                if cleaned_name in target_slugs:
                    feature["properties"]["slug"] = target_slugs[cleaned_name]
                    feature["properties"]["name"] = raw_city_name
                    feature["geometry"] = simplify_geometry(feature["geometry"])
                    simplified_features.append(feature)
                    
            print(f"Matched and simplified {len(simplified_features)} city boundaries.")
            output = {
                "type": "FeatureCollection",
                "features": simplified_features,
                "last_updated": datetime.utcnow().isoformat() + "Z"
            }
            save_json("city_boundaries.json", output)
    except Exception as e:
        print(f"Boundaries Harvest Error: {e}")

# ==============================================================================
# MAIN EXECUTION ROUTINE
# ==============================================================================
if __name__ == "__main__":
    print("Starting Sandbox Test Harvest Pipeline...")
    cities = load_city_data()
    
    harvest_demographics(cities)
    harvest_weather(cities)
    harvest_amenities(cities)
    harvest_environment(cities)
    harvest_schools(cities)
    harvest_boundaries(cities)
    
    print("Test Harvest Pipeline Execution Complete.")