# File: scripts/hourly/harvest_weather_hourly.py
import os
import json
import math
import requests
import urllib3
from datetime import datetime, timezone

# Suppress unverified HTTPS request warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Robust Repository Root Path Resolution
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(CURRENT_DIR) == "hourly":
    REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
elif os.path.basename(CURRENT_DIR) == "scripts":
    REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
else:
    REPO_ROOT = os.path.abspath(CURRENT_DIR)

DATA_DIR = os.path.join(REPO_ROOT, "data")
CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")
CRIME_STATS_PATH = os.path.join(DATA_DIR, "crime_stats.json")
CITY_DEMO_PATH = os.path.join(DATA_DIR, "city_demographics.json")
WEATHER_PATH = os.path.join(DATA_DIR, "city_weather.json")

KING_SNO_RIVER_GAUGES = [
    "12119000",  # Cedar River at Renton
    "12113000",  # Green River at Auburn
    "12149000",  # Snoqualmie River near Carnation
    "12155300",  # Snohomish River at Snohomish
    "12134500",  # Skykomish River near Gold Bar
    "12125200",  # Sammamish River at Bothell
    "12167000"   # Stillaguamish River at Arlington
]

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9"
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

def clean_coord(val):
    if val is None:
        return None
    try:
        f = float(str(val).strip())
        return f if not math.isnan(f) else None
    except (ValueError, TypeError):
        return None

def get_uv_label(val):
    if val is None:
        return "Low"
    try:
        f = float(val)
        if f < 3.0: return "Low"
        elif f < 6.0: return "Moderate"
        elif f < 8.0: return "High"
        elif f < 11.0: return "Very High"
        else: return "Extreme"
    except (ValueError, TypeError):
        return "Low"

def get_aqi_category(aqi_val):
    if aqi_val <= 50: return "Good"
    elif aqi_val <= 100: return "Moderate"
    elif aqi_val <= 150: return "Unhealthy for Sensitive Groups"
    elif aqi_val <= 200: return "Unhealthy"
    elif aqi_val <= 300: return "Very Unhealthy"
    return "Hazardous"

def save_json(filepath, data):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"   ✅ Saved: {filepath}", flush=True)

def load_cities():
    crime_pop_map = {}
    if os.path.exists(CRIME_STATS_PATH):
        try:
            with open(CRIME_STATS_PATH, "r", encoding="utf-8") as f:
                raw_crime = json.load(f)
                for city_key, city_info in raw_crime.items():
                    if isinstance(city_info, dict) and "reported_population" in city_info:
                        c_pop = city_info.get("reported_population")
                        if c_pop:
                            crime_pop_map[slugify(city_key)] = int(c_pop)
        except Exception:
            pass

    demo_pop_map = {}
    if os.path.exists(CITY_DEMO_PATH):
        try:
            with open(CITY_DEMO_PATH, "r", encoding="utf-8") as f:
                raw_demo = json.load(f)
                for c_slug, c_data in raw_demo.items():
                    if isinstance(c_data, dict):
                        d_pop = c_data.get("population") or c_data.get("total_population")
                        if d_pop:
                            demo_pop_map[slugify(c_slug)] = int(str(d_pop).replace(",", "").strip())
        except Exception:
            pass

    if not os.path.exists(CITY_DATA_PATH):
        return []
        
    with open(CITY_DATA_PATH, "r", encoding="utf-8") as f:
        raw_cities = json.load(f)
        
    cities = []
    items = raw_cities if isinstance(raw_cities, list) else list(raw_cities.values())
    for item in items:
        name = item.get("City") or item.get("name") or ""
        if not name:
            continue
            
        slug = slugify(name)
        lat = clean_coord(item.get("latitude") or item.get("Latitude"))
        lon = clean_coord(item.get("longitude") or item.get("Longitude"))

        pop = crime_pop_map.get(slug) or demo_pop_map.get(slug)
        if not pop:
            for k in ["population", "Population", "reported_population", "2020 Population", "Est Population"]:
                if item.get(k):
                    try:
                        pop = int(str(item.get(k)).replace(",", "").strip())
                        break
                    except (ValueError, TypeError):
                        pass
        if not pop or pop <= 0:
            pop = 25000

        cities.append({
            "slug": slug,
            "name": str(name).strip(),
            "latitude": lat,
            "longitude": lon,
            "population": pop
        })
    return cities

def harvest_weather_data():
    print("⛅ Harvesting Regional Weather, Tides, Ground UV Index & River Gauges...", flush=True)
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)

    cities = load_cities()
    valid_cities = [c for c in cities if c.get("latitude") is not None and c.get("longitude") is not None]
    
    output = {}

    # 1. Fetch Open-Meteo Weather with Real-Time UV Index (batches of 3)
    chunk_size = 3
    wx_cache = {}
    for i in range(0, len(valid_cities), chunk_size):
        chunk = valid_cities[i:i + chunk_size]
        lats_str = ",".join([str(c["latitude"]) for c in chunk])
        lons_str = ",".join([str(c["longitude"]) for c in chunk])

        wx_params = {
            "latitude": lats_str,
            "longitude": lons_str,
            "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,uv_index",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,uv_index_max,sunrise,sunset",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "timezone": "America/Los_Angeles"
        }
        wx_url = "https://api.open-meteo.com/v1/forecast"
        try:
            res = session.get(wx_url, params=wx_params, timeout=12)
            if res.status_code == 200:
                wx_res = res.json()
                if isinstance(wx_res, dict):
                    wx_res = [wx_res]
                for idx, city in enumerate(chunk):
                    if idx < len(wx_res) and isinstance(wx_res[idx], dict):
                        wx_cache[city["slug"]] = wx_res[idx]
        except Exception as e:
            print(f"   ⚠️ Open-Meteo batch notice: {e}", flush=True)

    # 2. Fetch NOAA Harmonic Tide Predictions
    noaa_stations = {
        "seattle": "9447130",       # Seattle Central Pier 54
        "edmonds": "9447427",       # Edmonds Ferry Pier
        "everett": "9447659",       # Everett Possession Sound
        "tacoma": "9446484",        # Tacoma Commencement Bay
        "des-moines": "9447029"     # Des Moines Marina
    }

    station_tides_cache = {}
    for st_key, st_id in noaa_stations.items():
        noaa_url = f"https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?date=TODAY&station={st_id}&product=predictions&datum=MLLW&time_zone=lst_ldt&units=english&interval=hilo&format=json"
        try:
            res = session.get(noaa_url, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, dict) and "predictions" in data:
                    preds = []
                    for p in data["predictions"]:
                        preds.append({
                            "time": p.get("t"),
                            "height_ft": round(float(p.get("v", 0)), 1),
                            "type": "High" if p.get("type") == "H" else "Low"
                        })
                    station_tides_cache[st_key] = preds
        except Exception as e:
            print(f"   ⚠️ NOAA Tides notice [{st_key}]: {e}", flush=True)

    # 3. Fetch Regional US AQI & PM2.5 (Open-Meteo Air Quality CAMS Engine)
    city_aqi_map = {}
    regional_hubs = [
        {"name": "Seattle-Bellevue-Kent Valley", "lat": 47.6062, "lon": -122.3321},
        {"name": "Everett-Marysville-Lynnwood", "lat": 47.9790, "lon": -122.2021},
        {"name": "Tacoma-Puyallup", "lat": 47.2529, "lon": -122.4443}
    ]
    station_data = []
    aqi_url = "https://air-quality-api.open-meteo.com/v1/air-quality"
    aqi_params = {
        "latitude": ",".join([str(h["lat"]) for h in regional_hubs]),
        "longitude": ",".join([str(h["lon"]) for h in regional_hubs]),
        "current": "us_aqi,pm2_5",
        "timezone": "America/Los_Angeles"
    }
    try:
        aq_res = session.get(aqi_url, params=aqi_params, timeout=12)
        if aq_res.status_code == 200:
            aq_json = aq_res.json()
            if isinstance(aq_json, dict):
                aq_json = [aq_json]
            for idx, hub in enumerate(regional_hubs):
                if idx < len(aq_json) and isinstance(aq_json[idx], dict):
                    curr = aq_json[idx].get("current", {})
                    aqi_num = int(curr.get("us_aqi") or 35)
                    pm_num = round(float(curr.get("pm2_5") or 8.4), 1)
                    station_data.append({
                        "reporting_area": hub["name"],
                        "aqi": aqi_num,
                        "pm2_5": pm_num,
                        "category": get_aqi_category(aqi_num),
                        "parameter": "PM2.5"
                    })
    except Exception as e:
        print(f"   ⚠️ Air Quality service notice: {e}", flush=True)

    for c in valid_cities:
        c_slug = c["slug"]
        station = station_data[0] if station_data else {"aqi": 35, "pm2_5": 8.4, "category": "Good", "parameter": "PM2.5", "reporting_area": "Seattle Metro"}
        if c_slug in ["everett", "marysville", "lynnwood", "edmonds", "arlington", "snohomish", "stanwood", "mukilteo", "mill-creek", "lake-stevens"] and len(station_data) > 1:
            station = station_data[1]
        elif c_slug in ["tacoma", "auburn", "kent", "federal-way", "pacific", "algona", "milton"] and len(station_data) > 2:
            station = station_data[2]
        city_aqi_map[c_slug] = station

    # 4. Fetch USGS River Flood Gauges
    stations_param = ",".join(KING_SNO_RIVER_GAUGES)
    usgs_url = f"https://waterservices.usgs.gov/nwis/iv/?format=json&sites={stations_param}&parameterCd=00060,00065&siteStatus=active"
    gauge_data = []
    try:
        res = session.get(usgs_url, timeout=12)
        if res.status_code == 200:
            res_json = res.json()
            time_series = res_json.get("value", {}).get("timeSeries", [])
            for ts in time_series:
                site_name = ts.get("sourceInfo", {}).get("siteName")
                values = ts.get("values", [{}])[0].get("value", [{}])
                current_val = values[-1].get("value") if values else None
                reading_time = values[-1].get("dateTime") if values else None
                unit = ts.get("variable", {}).get("unit", {}).get("unitCode")
                
                if current_val and current_val != "-999999":
                    gauge_data.append({
                        "site_name": site_name,
                        "reading": current_val,
                        "unit": unit,
                        "reading_time": reading_time
                    })
    except Exception as e:
        print(f"   ⚠️ USGS River Gauge Notice: {e}", flush=True)

    # 5. Assemble Consolidated Payload Across All Valid Cities
    for c in valid_cities:
        c_slug = c["slug"]
        city_wx = wx_cache.get(c_slug, {})
        current_wx = city_wx.get("current", {})
        daily_wx = city_wx.get("daily", {})

        assigned_station = "seattle"
        if c_slug in ["edmonds", "shoreline", "woodway", "lynnwood", "mountlake-terrace", "brier"]:
            assigned_station = "edmonds"
        elif c_slug in ["everett", "marysville", "lake-stevens", "mill-creek", "stanwood", "granite-falls", "mukilteo"]:
            assigned_station = "everett"
        elif c_slug in ["des-moines", "burien", "normandy-park", "seatac"]:
            assigned_station = "des-moines"
        elif c_slug in ["federal-way", "milton", "pacific", "algona", "auburn"]:
            assigned_station = "tacoma"

        city_tides = station_tides_cache.get(assigned_station, station_tides_cache.get("seattle", []))
        aqi_info = city_aqi_map.get(c_slug, {"aqi": 35, "pm2_5": 8.4, "category": "Good", "parameter": "PM2.5", "reporting_area": "Seattle Metro"})

        uv_curr = current_wx.get("uv_index")
        try:
            uv_val = round(float(uv_curr), 1) if uv_curr is not None else 0.0
        except (ValueError, TypeError):
            uv_val = 0.0

        output[c_slug] = {
            "name": c["name"],
            "latitude": c["latitude"],
            "longitude": c["longitude"],
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "current": {
                "temp_f": current_wx.get("temperature_2m"),
                "humidity_pct": current_wx.get("relative_humidity_2m"),
                "wind_speed_mph": current_wx.get("wind_speed_10m"),
                "weather_code": current_wx.get("weather_code"),
                "uv_index": uv_val,
                "uv_label": get_uv_label(uv_val)
            },
            "astronomy": {
                "sunrise_today": daily_wx.get("sunrise", [""])[0] if isinstance(daily_wx.get("sunrise"), list) and daily_wx.get("sunrise") else None,
                "sunset_today": daily_wx.get("sunset", [""])[0] if isinstance(daily_wx.get("sunset"), list) and daily_wx.get("sunset") else None
            },
            "air_quality": {
                "us_aqi": aqi_info.get("aqi", 35),
                "pm2_5": aqi_info.get("pm2_5", 8.4),
                "status_label": aqi_info.get("category", "Good"),
                "parameter": aqi_info.get("parameter", "PM2.5"),
                "reporting_area": aqi_info.get("reporting_area", "Seattle Metro")
            },
            "marine_tides": {
                "reference_station": assigned_station.replace("-", " ").title(),
                "today_predictions": city_tides,
                "source": "NOAA CO-OPS Predictions"
            },
            "forecast_7_day": {
                "dates": daily_wx.get("time", []),
                "temp_max": daily_wx.get("temperature_2m_max", []),
                "temp_min": daily_wx.get("temperature_2m_min", []),
                "precip_prob_max": daily_wx.get("precipitation_probability_max", []),
                "uv_index_max": daily_wx.get("uv_index_max", [])
            }
        }

    output["_regional_water_gauges"] = gauge_data
    save_json(WEATHER_PATH, output)

if __name__ == "__main__":
    harvest_weather_data()