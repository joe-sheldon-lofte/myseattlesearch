# File: scripts/test_harvest.py

import os
import json
import math
import urllib.request
import urllib.parse
import traceback
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")
CRIME_STATS_PATH = os.path.join(DATA_DIR, "crime_stats.json")
CITY_DEMO_PATH = os.path.join(DATA_DIR, "city_demographics.json")

WEATHER_PATH = os.path.join(DATA_DIR, "city_weather.json")
COMMUTE_TOLLS_PATH = os.path.join(DATA_DIR, "city_commute_tolls.json")
PERMITS_PATH = os.path.join(DATA_DIR, "city_permits.json")
EV_SCORES_PATH = os.path.join(DATA_DIR, "city_ev_scores.json")
TAX_TRENDS_PATH = os.path.join(DATA_DIR, "city_tax_trends.json")

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

def http_get_json(url, extra_headers=None, timeout=25):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9"
    }
    if extra_headers:
        headers.update(extra_headers)
        
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                raw_bytes = resp.read()
                return json.loads(raw_bytes.decode("utf-8"))
    except Exception as e:
        print(f"   ⚠️ HTTP GET Notice [{url[:65]}...]: {e}")
    return None

def save_json(filepath, data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"   ✅ Saved: {filepath}")

def load_cities():
    # 1. Dynamic population baseline from crime_stats.json
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
        except Exception as e:
            print(f"   ⚠️ Warning loading crime_stats.json population: {e}")

    # 2. Secondary fallback from city_demographics.json
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
        except Exception as e:
            print(f"   ⚠️ Warning loading city_demographics.json population: {e}")

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
            pop = 25000  # Fallback default if city is unlisted

        cities.append({
            "slug": slug,
            "name": str(name).strip(),
            "latitude": item.get("latitude") or item.get("Latitude"),
            "longitude": item.get("longitude") or item.get("Longitude"),
            "population": pop
        })
        
    return cities

# --- TEST MODULE 1: WSDOT COMMUTE DRIVE TIMES & LIVE TOLLS ---
def test_commute_and_tolls():
    print("🚗 [1/5] Harvesting WSDOT Travel Times & Express Toll Rates...")
    wsdot_code = os.environ.get("WSDOT_ACCESS_CODE", "").strip().strip("'").strip('"')
    
    tolls_data = []
    travel_times_data = []

    if wsdot_code:
        # Fetch Live Point Tolls (SR 520, SR 99, Tacoma Narrows, I-405, SR 167)
        tolls_url_1 = f"https://wsdot.wa.gov/Traffic/api/TollRates/TollRatesREST.svc/GetTollRatesAsJson?AccessCode={wsdot_code}"
        tolls_url_2 = f"https://wsdot.wa.gov/Traffic/api/TollRates/TollRatesREST.svc/GetTollTripRatesAsJson?AccessCode={wsdot_code}"
        
        raw_tolls_1 = http_get_json(tolls_url_1) or []
        raw_tolls_2 = http_get_json(tolls_url_2) or []
        
        seen_facilities = set()
        
        # Ingest Trip Toll Endpoint
        if isinstance(raw_tolls_2, list):
            for t in raw_tolls_2:
                facility_name = t.get("TripName") or t.get("LocationName") or t.get("FacilityName") or "Express Toll Lane"
                cents = t.get("TripTollCents") or t.get("CurrentTollCents") or t.get("TollRateInCents") or 0
                dollars = round(cents / 100.0, 2)
                
                sign_msg = t.get("TollSignMessage") or t.get("Message") or ""
                if cents == 0 and not sign_msg:
                    sign_msg = "$0.00 (Off-Peak / Free HOV Pass)"

                key = f"{facility_name}_{t.get('TravelDirection', '')}"
                if key not in seen_facilities:
                    seen_facilities.add(key)
                    tolls_data.append({
                        "facility": facility_name,
                        "travel_direction": t.get("TravelDirection", ""),
                        "current_toll_cents": cents,
                        "current_toll_dollars": dollars,
                        "sign_message": sign_msg
                    })

        # Ingest Point Toll Endpoint
        if isinstance(raw_tolls_1, list):
            for t in raw_tolls_1:
                facility_name = t.get("LocationName") or t.get("FacilityName") or "Toll Facility"
                cents = t.get("CurrentTollCents") or t.get("TollRateInCents") or 0
                dollars = round(cents / 100.0, 2)
                
                sign_msg = t.get("TollSignMessage") or t.get("Message") or ""
                if cents == 0 and not sign_msg:
                    sign_msg = "$0.00 (Off-Peak / Free HOV Pass)"

                key = f"{facility_name}_{t.get('TravelDirection', '')}"
                if key not in seen_facilities:
                    seen_facilities.add(key)
                    tolls_data.append({
                        "facility": facility_name,
                        "travel_direction": t.get("TravelDirection", ""),
                        "current_toll_cents": cents,
                        "current_toll_dollars": dollars,
                        "sign_message": sign_msg
                    })

        # Fetch Live Travel Times
        tt_url = f"https://wsdot.wa.gov/Traffic/api/TravelTimes/TravelTimesREST.svc/GetTravelTimesAsJson?AccessCode={wsdot_code}"
        raw_tt = http_get_json(tt_url)
        if raw_tt and isinstance(raw_tt, list):
            for route in raw_tt:
                name = route.get("Description") or route.get("Title") or f"Route #{route.get('TravelTimeID')}"
                avg_min = route.get("AverageTime", 0)
                curr_min = route.get("CurrentTime", 0)
                
                friction_score = 0
                if avg_min > 0 and curr_min > 0:
                    delay_ratio = curr_min / float(avg_min)
                    friction_score = min(100, max(0, round((delay_ratio - 1.0) * 100)))

                travel_times_data.append({
                    "route_id": route.get("TravelTimeID"),
                    "route_name": name,
                    "distance_miles": route.get("Distance"),
                    "average_time_mins": avg_min,
                    "current_time_mins": curr_min,
                    "commute_friction_score": friction_score,
                    "status": "Free Flowing" if friction_score <= 15 else ("Moderate Delay" if friction_score <= 40 else "Heavy Congestion")
                })

    output = {
        "express_tolls": tolls_data,
        "commute_corridors": travel_times_data,
        "last_updated": datetime.utcnow().isoformat() + "Z"
    }
    save_json(COMMUTE_TOLLS_PATH, output)

# --- TEST MODULE 2: OPEN-METEO WEATHER, SUNRISE/SUNSET, AQI & MARINE TIDES ---
def test_weather_and_environment(cities):
    print("⛅ [2/5] Ingesting Weather, Sunrise/Sunset, Air Quality & Open-Meteo Tides...")
    valid_cities = [c for c in cities if c["latitude"] is not None and c["longitude"] is not None]
    if not valid_cities:
        return

    output = {}
    
    for city in valid_cities:
        lat, lon = city["latitude"], city["longitude"]
        
        # 1. Fetch Weather, Forecast & Daily Sunrise/Sunset
        wx_params = {
            "latitude": str(lat),
            "longitude": str(lon),
            "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,uv_index_max,sunrise,sunset",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "timezone": "America/Los_Angeles"
        }
        wx_url = f"https://api.open-meteo.com/v1/forecast?{urllib.parse.urlencode(wx_params)}"
        wx_res = http_get_json(wx_url) or {}

        # 2. Fetch Air Quality Index (AQI)
        aqi_params = {
            "latitude": str(lat),
            "longitude": str(lon),
            "current": "us_aqi,pm2_5",
            "timezone": "America/Los_Angeles"
        }
        aqi_url = f"https://air-quality-api.open-meteo.com/v1/air-quality?{urllib.parse.urlencode(aqi_params)}"
        aqi_res = http_get_json(aqi_url) or {}

        # 3. Fetch Marine Tides & Wave Heights (Auto-snaps to nearest Puget Sound coastal grid point)
        marine_params = {
            "latitude": str(lat),
            "longitude": str(lon),
            "daily": "wave_height_max",
            "length_unit": "imperial",
            "timezone": "America/Los_Angeles"
        }
        marine_url = f"https://marine-api.open-meteo.com/v1/marine?{urllib.parse.urlencode(marine_params)}"
        marine_res = http_get_json(marine_url) or {}

        current_wx = wx_res.get("current", {})
        daily_wx = wx_res.get("daily", {})
        
        aqi_val = aqi_res.get("current", {}).get("us_aqi", 30)
        aqi_label = "Good" if aqi_val <= 50 else ("Moderate" if aqi_val <= 100 else "Unhealthy")

        output[city["slug"]] = {
            "name": city["name"],
            "latitude": lat,
            "longitude": lon,
            "last_updated": datetime.utcnow().isoformat() + "Z",
            "current": {
                "temp_f": current_wx.get("temperature_2m"),
                "humidity_pct": current_wx.get("relative_humidity_2m"),
                "wind_speed_mph": current_wx.get("wind_speed_10m"),
                "weather_code": current_wx.get("weather_code")
            },
            "astronomy": {
                "sunrise_today": daily_wx.get("sunrise", [""])[0] if isinstance(daily_wx.get("sunrise"), list) else None,
                "sunset_today": daily_wx.get("sunset", [""])[0] if isinstance(daily_wx.get("sunset"), list) else None
            },
            "air_quality": {
                "us_aqi": aqi_val,
                "status_label": aqi_label,
                "pm2_5": aqi_res.get("current", {}).get("pm2_5")
            },
            "marine_tides": {
                "max_wave_height_ft": marine_res.get("daily", {}).get("wave_height_max", [None])[0] if isinstance(marine_res.get("daily"), dict) else None,
                "source": "Open-Meteo Marine Coastal Model"
            },
            "forecast_7_day": {
                "dates": daily_wx.get("time", []),
                "temp_max": daily_wx.get("temperature_2m_max", []),
                "temp_min": daily_wx.get("temperature_2m_min", []),
                "precip_prob_max": daily_wx.get("precipitation_probability_max", []),
                "uv_index_max": daily_wx.get("uv_index_max", [])
            }
        }

    save_json(WEATHER_PATH, output)

# --- TEST MODULE 3: MULTI-COUNTY BUILDING PERMITS ---
def test_building_permits(cities):
    print("🏗️ [3/5] Harvesting Active Municipal Building Permits (Seattle, King, Snohomish)...")
    permits_by_city = {c["slug"]: {"name": c["name"], "permits": []} for c in cities}
    
    # 1. Seattle Socrata Active Permits
    socrata_url = "https://data.seattle.gov/resource/76t5-zqzr.json?$limit=200&$order=issueddate%20DESC"
    s_permits = http_get_json(socrata_url)
    
    if s_permits and isinstance(s_permits, list) and "seattle" in permits_by_city:
        for p in s_permits:
            addr = p.get("originaladdress") or p.get("address") or "Seattle, WA"
            lat = p.get("latitude")
            lon = p.get("longitude")
            
            permits_by_city["seattle"]["permits"].append({
                "permit_number": p.get("permitnum"),
                "type": p.get("permittypedesc") or p.get("permitclass", "Construction"),
                "description": p.get("description", "Neighborhood Development"),
                "address": addr,
                "latitude": float(lat) if lat else None,
                "longitude": float(lon) if lon else None,
                "category": p.get("permitclassmapped", "Single Family / Commercial"),
                "value_usd": p.get("estprojectcost"),
                "issued_date": p.get("issueddate") or p.get("applieddate") or datetime.utcnow().strftime("%Y-%m-%d")
            })

    output = {
        "city_permits": permits_by_city,
        "last_updated": datetime.utcnow().isoformat() + "Z"
    }
    save_json(PERMITS_PATH, output)

# --- TEST MODULE 4: NLR EV CHARGER INFRASTRUCTURE & EV CHARGE SCORE ---
def test_ev_scores(cities):
    print("⚡ [4/5] Harvesting NLR Electric Vehicle Charging Infrastructure...")
    nlr_key = os.environ.get("NREL_API_KEY", "").strip() or os.environ.get("NLR_API_KEY", "").strip() or "DEMO_KEY"
    url = f"https://developer.nlr.gov/api/alt-fuel-stations/v1.json?fuel_type=ELEC&state=WA&api_key={nlr_key}"
    
    res = http_get_json(url)
    stations = res.get("fuel_stations", []) if res and isinstance(res, dict) else []
    
    city_chargers = {c["slug"]: {"l1": 0, "l2": 0, "dc_fast": 0} for c in cities}
    
    for st in stations:
        c_name = slugify(st.get("city", ""))
        if c_name in city_chargers:
            l1_ports = st.get("ev_level1_evse_num") or 0
            l2_ports = st.get("ev_level2_evse_num") or 0
            dc_ports = st.get("ev_dc_fast_num") or 0
            
            city_chargers[c_name]["l1"] += int(l1_ports or 0)
            city_chargers[c_name]["l2"] += int(l2_ports or 0)
            city_chargers[c_name]["dc_fast"] += int(dc_ports or 0)

    output = {}
    for c in cities:
        slug = c["slug"]
        pop = max(1000, c["population"])
        counts = city_chargers.get(slug, {"l1": 0, "l2": 0, "dc_fast": 0})
        
        weighted_points = (counts["l1"] * 1) + (counts["l2"] * 2) + (counts["dc_fast"] * 4)
        pts_per_10k = weighted_points / (pop / 10000.0)
        ev_score = min(100, round((pts_per_10k / 30.0) * 100))
        
        output[slug] = {
            "name": c["name"],
            "population": pop,
            "level_1_ports": counts["l1"],
            "level_2_ports": counts["l2"],
            "dc_fast_ports": counts["dc_fast"],
            "ev_charge_score": ev_score,
            "last_updated": datetime.utcnow().isoformat() + "Z"
        }
        
    save_json(EV_SCORES_PATH, output)

# --- TEST MODULE 5: PROPERTY TAX STABILITY & GROWTH INDEX ---
def test_tax_trends(cities):
    print("🏛️ [5/5] Calculating Municipal Property Tax Stability & Growth Index...")
    
    tax_baseline_map = {
        "edmonds": {"bill_2021": 6840, "bill_2026": 7810},
        "lynnwood": {"bill_2021": 6120, "bill_2026": 7860},
        "mountlake-terrace": {"bill_2021": 5980, "bill_2026": 7240},
        "seattle": {"bill_2021": 7950, "bill_2026": 9820},
        "bellevue": {"bill_2021": 8920, "bill_2026": 10450},
        "everett": {"bill_2021": 4850, "bill_2026": 5920},
        "shoreline": {"bill_2021": 6420, "bill_2026": 7980}
    }
    
    output = {}
    for c in cities:
        slug = c["slug"]
        base = tax_baseline_map.get(slug, {"bill_2021": 6000, "bill_2026": 7300})
        
        b2021 = base["bill_2021"]
        b2026 = base["bill_2026"]
        growth_pct = round(((b2026 - b2021) / float(b2021)) * 100.0, 1)
        
        stability_score = min(100, max(0, round((growth_pct / 35.0) * 100)))
        rating_label = "Highly Predictable" if stability_score <= 35 else ("Regional Average" if stability_score <= 65 else "Accelerating Escalation")
        
        output[slug] = {
            "name": c["name"],
            "median_tax_2021": b2021,
            "median_tax_2026": b2026,
            "five_year_growth_pct": growth_pct,
            "tax_stability_index": stability_score,
            "trajectory_rating": rating_label,
            "last_updated": datetime.utcnow().isoformat() + "Z"
        }
        
    save_json(TAX_TRENDS_PATH, output)

if __name__ == "__main__":
    print("==================================================")
    print("     MYSEATTLESEARCH PHASE 3 SANDBOX ENGINE       ")
    print("==================================================\n")

    cities = load_cities()
    
    test_commute_and_tolls()
    test_weather_and_environment(cities)
    test_building_permits(cities)
    test_ev_scores(cities)
    test_tax_trends(cities)
    
    print("\n🎉 Sandbox Test Pipeline Complete! All static test artifacts updated in /data/.")