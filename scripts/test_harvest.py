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

def load_city_data():
    """Load master city taxonomy and coordinates."""
    if not os.path.exists(CITY_DATA_PATH):
        print(f"Error: {CITY_DATA_PATH} not found.")
        return []
    with open(CITY_DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(filename, data):
    """Save formatted JSON output to data directory."""
    os.makedirs(DATA_DIR, exist_ok=True)
    target_path = os.path.join(DATA_DIR, filename)
    with open(target_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Successfully generated: {target_path}")

def http_get_json(url, timeout=20):
    """Utility helper for HTTP GET requests returning JSON."""
    req = urllib.request.Request(url, headers={"User-Agent": "MySeattleSearch/1.0 (RealEstateDataBot)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status == 200:
            return json.loads(resp.read().decode("utf-8"))
    return None

# ==============================================================================
# 1. WEATHER HARVESTER (Open-Meteo Chunked Batches)
# ==============================================================================
def harvest_weather(cities):
    print("Harvesting Weather Data via Open-Meteo...")
    if not cities:
        return
    
    valid_cities = [c for c in cities if "latitude" in c and "longitude" in c]
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
        save_json("city_weather.json", output)

# ==============================================================================
# 2. AMENITIES HARVESTER (Single Spatial Puget Sound Overpass Query)
# ==============================================================================
def harvest_amenities(cities):
    print("Harvesting Municipal Amenities via Puget Sound Overpass Query...")
    if not cities:
        return

    # Bounding box covering Puget Sound region (South King to North Snohomish)
    bbox = "47.0,-122.6,48.2,-121.8"
    overpass_query = f"""
    [out:json][timeout:40];
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
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "MySeattleSearch/1.0"})
    
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            res = json.loads(response.read().decode("utf-8"))
            nodes = res.get("elements", [])
            print(f"Retrieved {len(nodes)} regional amenity nodes.")
            
            output = {}
            radius_deg = 0.03  # ~3km spatial buffer around city center
            
            for city in cities:
                slug = city.get("slug")
                clat = city.get("latitude")
                clon = city.get("longitude")
                
                if not clat or not clon:
                    continue
                    
                counts = {
                    "dog_parks": 0,
                    "coffee_shops": 0,
                    "parks": 0,
                    "beaches": 0,
                    "pet_stores": 0
                }
                
                for node in nodes:
                    nlat = node.get("lat")
                    nlon = node.get("lon")
                    if nlat and nlon:
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
            save_json("city_amenities.json", output)
    except Exception as e:
        print(f"Amenities Harvest Error: {e}")

# ==============================================================================
# 3. ENVIRONMENT HARVESTER (Puget Sound Regional USGS Gauges)
# ==============================================================================
def harvest_environment(cities):
    print("Harvesting Puget Sound Environmental & Water Gauge Metrics via USGS...")
    # Puget Sound bounding box filter
    bbox_url = "https://waterservices.usgs.gov/nwis/iv/?format=json&bBox=-122.6,47.0,-121.8,48.2&parameterCd=00060,00065&siteStatus=active"
    
    try:
        res = http_get_json(bbox_url, timeout=20)
        if res:
            time_series = res.get("value", {}).get("timeSeries", [])
            gauge_data = []
            
            for ts in time_series:
                site_name = ts.get("sourceInfo", {}).get("siteName")
                values = ts.get("values", [{}])[0].get("value", [{}])
                current_val = values[-1].get("value") if values else None
                unit = ts.get("variable", {}).get("unit", {}).get("unitCode")
                
                # Exclude uncalibrated sensor values (-999999)
                if current_val and current_val != "-999999":
                    gauge_data.append({
                        "site_name": site_name,
                        "reading": current_val,
                        "unit": unit
                    })
                    
            output = {
                "regional_water_gauges": gauge_data[:30],
                "last_updated": datetime.utcnow().isoformat() + "Z"
            }
            save_json("city_environment.json", output)
    except Exception as e:
        print(f"Environment Harvest Error: {e}")

# ==============================================================================
# 4. SCHOOLS HARVESTER (OSPI Socrata Endpoint Fallback)
# ==============================================================================
def harvest_schools(cities):
    print("Harvesting OSPI School Data via WA Open Data...")
    endpoints = ["wvqy-yp3m", "q4ba-s3jc", "dij7-mbxg", "f7j6-nk2h"]
    records = None
    
    for ep in endpoints:
        url = f"https://data.wa.gov/resource/{ep}.json?$limit=250"
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
            district = rec.get("district_name") or rec.get("districtname") or rec.get("organizationname") or "Regional District"
            if district not in school_summary:
                school_summary[district] = {
                    "district_name": district,
                    "records_count": 0
                }
            school_summary[district]["records_count"] += 1
            
        output = {
            "districts": school_summary,
            "last_updated": datetime.utcnow().isoformat() + "Z"
        }
        save_json("city_schools.json", output)
    else:
        print("Schools Harvest Error: All OSPI endpoints unreachable.")

# ==============================================================================
# 5. GEOMETRY SIMPLIFICATION & WSDOT BOUNDARY IMPORT
# ==============================================================================
def perpendicular_distance(point, line_start, line_end):
    """Calculate perpendicular distance from a point to a line segment."""
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
    """Pure-Python Ramer-Douglas-Peucker boundary reduction algorithm."""
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
    """Applies RDP simplification across Polygons and MultiPolygons."""
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
    print("Harvesting & Simplifing WA City Boundaries via WSDOT GIS REST...")
    wsdot_url = "https://data.wsdot.wa.gov/arcgis/rest/services/Shared/PoliAdminBndryData/MapServer/1/query?where=1%3D1&outFields=CityName&outSR=4326&f=geojson"
    
    try:
        geojson = http_get_json(wsdot_url, timeout=30)
        if geojson and "features" in geojson:
            target_slugs = {c["name"].lower(): c["slug"] for c in cities if "name" in c}
            simplified_features = []
            
            for feature in geojson["features"]:
                city_name = feature.get("properties", {}).get("CityName", "")
                if city_name.lower() in target_slugs:
                    feature["properties"]["slug"] = target_slugs[city_name.lower()]
                    feature["geometry"] = simplify_geometry(feature["geometry"])
                    simplified_features.append(feature)
                    
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
    print("Starting Hardened Test Harvest Pipeline...")
    cities = load_city_data()
    
    harvest_weather(cities)
    harvest_amenities(cities)
    harvest_environment(cities)
    harvest_schools(cities)
    harvest_boundaries(cities)
    
    print("Test Harvest Pipeline Execution Complete.")