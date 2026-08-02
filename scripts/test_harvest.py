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

# ==============================================================================
# 1. WEATHER HARVESTER (Open-Meteo Batch)
# ==============================================================================
def harvest_weather(cities):
    print("Harvesting Weather Data via Open-Meteo...")
    if not cities:
        return
    
    lats = [str(c["latitude"]) for c in cities if "latitude" in c and "longitude" in c]
    lons = [str(c["longitude"]) for c in cities if "latitude" in c and "longitude" in c]
    
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
    req = urllib.request.Request(url, headers={"User-Agent": "MySeattleSearch/1.0"})
    
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            results = json.loads(response.read().decode("utf-8"))
            
            # Normalize batch response format (list vs single dict)
            if isinstance(results, dict):
                results = [results]
            
            output = {}
            for idx, city in enumerate(cities):
                if idx < len(results):
                    res = results[idx]
                    output[city["slug"]] = {
                        "name": city["name"],
                        "last_updated": datetime.utcnow().isoformat() + "Z",
                        "current": res.get("current", {}),
                        "forecast": res.get("daily", {})
                    }
            save_json("city_weather.json", output)
    except Exception as e:
        print(f"Weather Harvest Error: {e}")

# ==============================================================================
# 2. AMENITIES HARVESTER (Overpass OSM API)
# ==============================================================================
def harvest_amenities(cities):
    print("Harvesting Municipal Amenities via Overpass API...")
    output = {}
    
    for city in cities[:5]:  # Batching first 5 cities for test verification
        slug = city.get("slug")
        lat = city.get("latitude")
        lon = city.get("longitude")
        
        if not lat or not lon:
            continue
            
        # 3km bounding box around city center
        delta = 0.03
        bbox = f"{lat - delta},{lon - delta},{lat + delta},{lon + delta}"
        
        overpass_query = f"""
        [out:json][timeout:25];
        (
          node["leisure"="dog_park"]({bbox});
          node["amenity"="cafe"]({bbox});
          node["leisure"="park"]({bbox});
          node["natural"="beach"]({bbox});
          node["shop"="pet"]({bbox});
        );
        out count;
        """
        
        url = "https://overpass-api.de/api/interpreter"
        data = urllib.parse.urlencode({"data": overpass_query}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"User-Agent": "MySeattleSearch/1.0"})
        
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                res = json.loads(response.read().decode("utf-8"))
                elements = res.get("elements", [])
                
                counts = {
                    "dog_parks": 0,
                    "coffee_shops": 0,
                    "parks": 0,
                    "beaches": 0,
                    "pet_stores": 0
                }
                
                for el in elements:
                    tags = el.get("tags", {})
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
        except Exception as e:
            print(f"Amenities Harvest Error for {slug}: {e}")
            
    save_json("city_amenities.json", output)

# ==============================================================================
# 3. ENVIRONMENT HARVESTER (USGS Water Gauges)
# ==============================================================================
def harvest_environment(cities):
    print("Harvesting Environmental & Water Gauge Metrics via USGS...")
    url = "https://waterservices.usgs.gov/nwis/iv/?format=json&stateCd=wa&parameterCd=00060,00065&siteStatus=active"
    req = urllib.request.Request(url, headers={"User-Agent": "MySeattleSearch/1.0"})
    
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            res = json.loads(response.read().decode("utf-8"))
            time_series = res.get("value", {}).get("timeSeries", [])
            
            gauge_data = []
            for ts in time_series[:20]:  # Top active gauges
                site_name = ts.get("sourceInfo", {}).get("siteName")
                values = ts.get("values", [{}])[0].get("value", [{}])
                current_val = values[-1].get("value") if values else None
                unit = ts.get("variable", {}).get("unit", {}).get("unitCode")
                
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
# 4. SCHOOLS HARVESTER (OSPI Socrata API)
# ==============================================================================
def harvest_schools(cities):
    print("Harvesting OSPI School Data via WA Open Data...")
    url = "https://data.wa.gov/resource/g2e2-9383.json?$limit=50"
    req = urllib.request.Request(url, headers={"User-Agent": "MySeattleSearch/1.0"})
    
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            records = json.loads(response.read().decode("utf-8"))
            
            school_summary = {}
            for rec in records:
                district = rec.get("district_name", "Unknown")
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
    except Exception as e:
        print(f"Schools Harvest Error: {e}")

# ==============================================================================
# 5. GEOMETRY SIMPLIFICATION (Ramer-Douglas-Peucker Algorithm)
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

def rdp_simplify(points, epsilon):
    """Pure-Python Ramer-Douglas-Peucker boundary reduction algorithm."""
    if len(points) < 3:
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
        rec_results1 = rdp_simplify(points[:index+1], epsilon)
        rec_results2 = rdp_simplify(points[index:], epsilon)
        return rec_results1[:-1] + rec_results2
    else:
        return [points[0], points[end]]

def harvest_boundaries():
    print("Simplifying Boundary Maps via Pure-Python RDP...")
    # Mock boundary structure to test pipeline execution
    sample_polygon = [
        [-122.33, 47.60], [-122.331, 47.601], [-122.332, 47.6015],
        [-122.335, 47.605], [-122.34, 47.61], [-122.33, 47.60]
    ]
    
    simplified = rdp_simplify(sample_polygon, epsilon=0.001)
    
    output = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "Test Boundary"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [simplified]
                }
            }
        ],
        "last_updated": datetime.utcnow().isoformat() + "Z"
    }
    save_json("city_boundaries.json", output)

# ==============================================================================
# MAIN EXECUTION ROUTINE
# ==============================================================================
if __name__ == "__main__":
    print("Starting Test Harvest Pipeline...")
    cities = load_city_data()
    
    harvest_weather(cities)
    harvest_amenities(cities)
    harvest_environment(cities)
    harvest_schools(cities)
    harvest_boundaries()
    
    print("Test Harvest Pipeline Execution Complete.")