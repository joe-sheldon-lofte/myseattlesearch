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

def http_get_json(url, timeout=25):
    """Robust HTTP GET JSON request helper with custom browser User-Agent."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) RealEstateDataBot/1.0"
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                raw_bytes = resp.read()
                return json.loads(raw_bytes.decode("utf-8"))
    except Exception as e:
        print(f"HTTP GET Error [{url}]: {e}")
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
        clean_fips = str(raw_fips).strip()
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
    if normalized:
        print(f"Sample Normalized City [0]: {normalized[0]}")
    return normalized

# ==============================================================================
# 1. DEMOGRAPHICS HARVESTER (US Census ACS 5-Year Municipal API)
# ==============================================================================
def harvest_demographics(cities):
    print("Harvesting City-Level Demographics via US Census Bureau ACS 5-Year API...")
    census_key = os.environ.get("CENSUS_API_KEY", "")
    
    # Target Census ACS Variables: Name, Median Income, Median Age, Owner Occ, Renter Occ, WFH, Total Workers
    variables = "NAME,B19013_001E,B01002_001E,B25003_002E,B25003_003E,B08301_021E,B08301_001E"
    base_url = f"https://api.census.gov/data/2022/acs/acs5?get={variables}&for=place:*&in=state:53"
    if census_key:
        base_url += f"&key={census_key}"

    res = http_get_json(base_url, timeout=25)
    if not res or not isinstance(res, list) or len(res) < 2:
        print("Census API Harvest Warning: No data returned from Census endpoint.")
        return

    headers = res[0]
    data_rows = res[1:]
    
    census_by_place = {}
    for row in data_rows:
        row_dict = dict(zip(headers, row))
        place_fips = str(row_dict.get("place", "")).zfill(5)
        census_by_place[place_fips] = row_dict

    output = {}
    for city in cities:
        slug = city["slug"]
        name = city["name"]
        fips = city["federal_id"]
        
        if not slug:
            continue

        c_data = census_by_place.get(fips) if fips else None
        
        def safe_float(val, default=0.0):
            try:
                v = float(val)
                return v if v >= 0 else default
            except (ValueError, TypeError):
                return default

        if c_data:
            income = safe_float(c_data.get("B19013_001E"))
            age = safe_float(c_data.get("B01002_001E"))
            owners = safe_float(c_data.get("B25003_002E"))
            renters = safe_float(c_data.get("B25003_003E"))
            wfh = safe_float(c_data.get("B08301_021E"))
            workers = safe_float(c_data.get("B08301_001E"))

            total_units = owners + renters
            owner_pct = round((owners / total_units * 100), 1) if total_units > 0 else 0.0
            renter_pct = round((renters / total_units * 100), 1) if total_units > 0 else 0.0
            remote_pct = round((wfh / workers * 100), 1) if workers > 0 else 0.0

            output[slug] = {
                "name": name,
                "fips_place": fips,
                "median_household_income": int(income),
                "median_age": age,
                "owner_occupied_pct": owner_pct,
                "renter_occupied_pct": renter_pct,
                "remote_worker_pct": remote_pct,
                "last_updated": datetime.utcnow().isoformat() + "Z"
            }
            
    print(f"Successfully matched city demographics for {len(output)} cities.")
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
# 3. AMENITIES HARVESTER (Puget Sound Overpass Spatial Query)
# ==============================================================================
def harvest_amenities(cities):
    print("Harvesting Municipal Amenities via Puget Sound Overpass Query...")
    valid_cities = [c for c in cities if c["latitude"] is not None and c["longitude"] is not None]
    if not valid_cities:
        return

    bbox = "47.0,-122.6,48.2,-121.8"
    overpass_query = f"""
    [out:json][timeout:45];
    (
      node["leisure"="dog_park"]({bbox});
      node["amenity"="cafe"]({bbox});
      node["leisure"="park"]({bbox});
      node["natural"="beach"]({bbox});
      node["shop"="pet"]({bbox});
    );
    out body;
    """
    
    url = "https://overpass-api.de/api/interpreter"
    data = urllib.parse.urlencode({"data": overpass_query}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0 RealEstateDataBot/1.0"})
    
    try:
        with urllib.request.urlopen(req, timeout=50) as response:
            res = json.loads(response.read().decode("utf-8"))
            nodes = res.get("elements", [])
            print(f"Retrieved {len(nodes)} regional amenity nodes.")
            
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
                    "pet_stores": 0
                }
                
                for node in nodes:
                    try:
                        nlat = float(node.get("lat"))
                        nlon = float(node.get("lon"))
                    except (ValueError, TypeError):
                        continue
                        
                    if abs(nlat - clat) <= radius_deg and abs(nlon - clon) <= radius_deg:
                        tags = node.get("tags", {})
                        if tags.get("leisure") == "dog_park":
                            counts["dog_parks"] += 1
                        elif tags.get("amenity") == "cafe":
                            counts["coffee_shops"] += 1
                        elif tags.get("leisure") == "park":
                            counts["parks"] += 1
                        elif tags.get("natural") == "beach":
                            counts["beaches"] += 1
                        elif tags.get("shop") == "pet":
                            counts["pet_stores"] += 1
                            
                output[slug] = {
                    "name": city["name"],
                    "amenities": counts,
                    "last_updated": datetime.utcnow().isoformat() + "Z"
                }
            print(f"Successfully calculated amenities across {len(output)} cities.")
            save_json("city_amenities.json", output)
    except Exception as e:
        print(f"Amenities Harvest Error: {e}")

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
    for c in cities:
        if c["ospi_id"]:
            target_ospi_ids.add(c["ospi_id"])
            
    print(f"Targeting {len(target_ospi_ids)} explicit OSPI District IDs from city taxonomy.")

    endpoints = ["wvqy-yp3m", "q4ba-s3jc", "dij7-mbxg"]
    records = None
    
    for ep in endpoints:
        url = f"https://data.wa.gov/resource/{ep}.json?$limit=2000"
        try:
            records = http_get_json(url, timeout=15)
            if records and isinstance(records, list):
                print(f"Connected to OSPI dataset endpoint: {ep}")
                break
        except Exception:
            continue
            
    if records:
        school_summary = {}
        for rec in records:
            district_name = rec.get("district_name") or rec.get("districtname") or rec.get("organizationname") or ""
            district_code = str(rec.get("district_code") or rec.get("districtcode") or rec.get("county_district_number") or "").strip()
            
            is_match = False
            if district_code and district_code in target_ospi_ids:
                is_match = True
            elif district_name and any(target in district_name.lower() for target in KING_SNO_DISTRICTS):
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
    print("Starting Normalized Sandbox Test Harvest Pipeline...")
    cities = load_city_data()
    
    harvest_demographics(cities)
    harvest_weather(cities)
    harvest_amenities(cities)
    harvest_environment(cities)
    harvest_schools(cities)
    harvest_boundaries(cities)
    
    print("Test Harvest Pipeline Execution Complete.")