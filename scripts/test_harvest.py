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

def http_get_json(url, extra_headers=None, timeout=15):
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
        print(f"   ⚠️ HTTP GET Notice [{url[:65]}...]: {e}", flush=True)
    return None

def save_json(filepath, data):
    os.makedirs(DATA_DIR, exist_ok=True)
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
        except Exception as e:
            print(f"   ⚠️ Warning loading crime_stats.json population: {e}", flush=True)

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
            print(f"   ⚠️ Warning loading city_demographics.json population: {e}", flush=True)

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
            pop = 25000

        cities.append({
            "slug": slug,
            "name": str(name).strip(),
            "latitude": item.get("latitude") or item.get("Latitude"),
            "longitude": item.get("longitude") or item.get("Longitude"),
            "population": pop
        })
        
    return cities

# --- TEST MODULE 1: WSDOT LIVE TOLLS, COMMUTE CORRIDORS & REGIONAL INFRASTRUCTURE ---
def test_commute_and_tolls():
    print("🚗 [1/5] Harvesting WSDOT Travel Times, Live Toll Rates & Infrastructure...", flush=True)
    wsdot_code = os.environ.get("WSDOT_ACCESS_CODE", "").strip().strip("'").strip('"')
    
    tolls_data = []
    travel_times_data = []

    if wsdot_code:
        # 1. Fetch Dynamic Express Toll Lanes & Point Tolls
        tolls_url_1 = f"https://wsdot.wa.gov/Traffic/api/TollRates/TollRatesREST.svc/GetTollRatesAsJson?AccessCode={wsdot_code}"
        tolls_url_2 = f"https://wsdot.wa.gov/Traffic/api/TollRates/TollRatesREST.svc/GetTollTripRatesAsJson?AccessCode={wsdot_code}"
        
        res_tolls_1 = http_get_json(tolls_url_1)
        res_tolls_2 = http_get_json(tolls_url_2)
        
        raw_tolls = []
        if isinstance(res_tolls_1, list):
            raw_tolls.extend(res_tolls_1)
        elif isinstance(res_tolls_1, dict):
            raw_tolls.extend(res_tolls_1.get("TollRates") or res_tolls_1.get("Tolls") or [])

        if isinstance(res_tolls_2, list):
            raw_tolls.extend(res_tolls_2)
        elif isinstance(res_tolls_2, dict):
            raw_tolls.extend(res_tolls_2.get("Trips") or res_tolls_2.get("TripTollRates") or [])
        
        seen_facilities = set()
        for t in raw_tolls:
            if not isinstance(t, dict):
                continue
            
            facility_name = t.get("TripName") or t.get("LocationName") or t.get("FacilityName") or "Express Toll Corridor"
            travel_dir = t.get("TravelDirection") or t.get("Direction") or ""
            
            cents = 0
            if "Toll" in t and t["Toll"] is not None:
                try:
                    cents = int(round(float(t["Toll"]) * 100))
                except (ValueError, TypeError):
                    cents = 0
            elif "CurrentTollCents" in t and t["CurrentTollCents"] is not None:
                cents = int(t["CurrentTollCents"])
            elif "TripTollCents" in t and t["TripTollCents"] is not None:
                cents = int(t["TripTollCents"])

            dollars = round(cents / 100.0, 2)
            sign_msg = t.get("TollSignMessage") or t.get("Message") or f"${dollars:.2f}"
            if cents == 0 and not sign_msg:
                sign_msg = "$0.00 (Off-Peak / Free HOV Pass)"

            key = f"{facility_name}_{travel_dir}"
            if key not in seen_facilities:
                seen_facilities.add(key)
                tolls_data.append({
                    "facility": facility_name,
                    "travel_direction": travel_dir,
                    "current_toll_cents": cents,
                    "current_toll_dollars": dollars,
                    "sign_message": sign_msg
                })

        # 2. Fetch Travel Times across regional corridors
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

    # Static baseline schedules for full day coverage
    static_schedules = [
        {
            "facility": "SR 520 Floating Bridge",
            "toll_type": "Variable Time-of-Day (24/7 Tolled)",
            "good_to_go_range": "$1.25 - $4.50",
            "pay_by_mail_range": "$3.25 - $6.50",
            "peak_hours_rate": "$4.50 (7-9 AM & 3-6 PM Weekdays)",
            "mid_day_rate": "$3.40",
            "overnight_rate": "$1.25 (11 PM - 5 AM)",
            "hov_rules": "Free for HOV 3+ with registered Flex Pass in HOV mode"
        },
        {
            "facility": "SR 99 Tunnel",
            "toll_type": "Variable Time-of-Day (24/7 Tolled)",
            "good_to_go_range": "$1.20 - $2.70",
            "pay_by_mail_range": "$3.20 - $4.70",
            "peak_hours_rate": "$2.70 (7-9 AM & 3-6 PM Weekdays)",
            "mid_day_rate": "$1.75",
            "overnight_rate": "$1.20 (11 PM - 6 AM)",
            "hov_rules": "No HOV exemption (All vehicles pay active toll)"
        },
        {
            "facility": "Tacoma Narrows Bridge (Eastbound)",
            "toll_type": "Fixed Rate (Eastbound Only)",
            "good_to_go_range": "$5.25",
            "pay_by_mail_range": "$7.25",
            "booth_rate": "$6.25",
            "overnight_rate": "$5.25",
            "hov_rules": "No HOV exemption"
        },
        {
            "facility": "I-405 Express Toll Lanes (Lynnwood to Bellevue)",
            "toll_type": "Dynamic Congestion Pricing",
            "good_to_go_range": "$1.00 - $15.00",
            "pay_by_mail_range": "$3.00 - $17.00",
            "peak_hours_rate": "Dynamic ($1.00 min / $15.00 max based on speed)",
            "mid_day_rate": "Dynamic ($1.00 min)",
            "overnight_rate": "Free / Open to all (8 PM - 5 AM)",
            "hov_rules": "Free for HOV 3+ (HOV 2+ off-peak) with Flex Pass"
        },
        {
            "facility": "SR 167 HOT Lanes (Renton to Auburn)",
            "toll_type": "Dynamic Congestion Pricing",
            "good_to_go_range": "$1.00 - $15.00",
            "pay_by_mail_range": "N/A (Good To Go! Pass Required)",
            "peak_hours_rate": "Dynamic ($1.00 min / $15.00 max)",
            "mid_day_rate": "Dynamic ($1.00 min)",
            "overnight_rate": "Free / Open to all (7 PM - 5 AM)",
            "hov_rules": "Free for HOV 2+ with Flex Pass"
        }
    ]

    # Regional Transit Infrastructure
    static_infrastructure = [
        {"name": "Seattle Colman Dock (Pier 52)", "city": "Seattle", "routes": ["Seattle - Bainbridge Island", "Seattle - Bremerton"], "latitude": 47.6025, "longitude": -122.3383},
        {"name": "Edmonds Ferry Terminal", "city": "Edmonds", "routes": ["Edmonds - Kingston"], "latitude": 47.8131, "longitude": -122.3842},
        {"name": "Mukilteo Ferry Terminal", "city": "Mukilteo", "routes": ["Mukilteo - Clinton"], "latitude": 47.9501, "longitude": -122.3053},
        {"name": "Fauntleroy Ferry Terminal", "city": "Seattle", "routes": ["Fauntleroy - Vashon - Southworth"], "latitude": 47.5233, "longitude": -122.3928},
        {"name": "Point Defiance Ferry Terminal", "city": "Tacoma", "routes": ["Point Defiance - Tahlequah"], "latitude": 47.3060, "longitude": -122.5144}
    ]

    output = {
        "live_express_tolls": tolls_data,
        "static_rate_schedules": static_schedules,
        "transit_infrastructure": static_infrastructure,
        "commute_corridors": travel_times_data,
        "last_updated": datetime.utcnow().isoformat() + "Z"
    }
    save_json(COMMUTE_TOLLS_PATH, output)

# --- TEST MODULE 2: BATCHED OPEN-METEO WEATHER, ASTRONOMY & NOAA PUGET SOUND TIDES ---
def test_weather_and_environment(cities):
    print("⛅ [2/5] Ingesting Weather, Air Quality & NOAA Puget Sound Tides...", flush=True)
    valid_cities = [c for c in cities if c.get("latitude") is not None and c.get("longitude") is not None]
    if not valid_cities:
        return

    # NOAA Station Lookup across Puget Sound
    noaa_stations = {
        "seattle": "9447130",       # Seattle Central Pier 54
        "edmonds": "9447427",       # Edmonds
        "everett": "9447138",       # Everett / Possession Sound
        "tacoma": "9446484",        # Tacoma Commencement Bay
        "des-moines": "9447029",    # Des Moines Marina
        "mukilteo": "9447239"       # Mukilteo
    }

    station_tides_cache = {}
    for st_key, st_id in noaa_stations.items():
        noaa_url = f"https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?date=today&station={st_id}&product=predictions&datum=MLLW&time_zone=lst_ldt&units=english&interval=hilo&format=json"
        res = http_get_json(noaa_url, timeout=8)
        if res and isinstance(res, dict) and "predictions" in res:
            preds = []
            for p in res["predictions"]:
                preds.append({
                    "time": p.get("t"),
                    "height_ft": round(float(p.get("v", 0)), 1),
                    "type": "High" if p.get("type") == "H" else "Low"
                })
            station_tides_cache[st_key] = preds

    chunk_size = 5
    output = {}

    for i in range(0, len(valid_cities), chunk_size):
        chunk = valid_cities[i:i + chunk_size]
        lats_str = ",".join([str(c["latitude"]) for c in chunk])
        lons_str = ",".join([str(c["longitude"]) for c in chunk])

        wx_params = {
            "latitude": lats_str,
            "longitude": lons_str,
            "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,uv_index_max,sunrise,sunset",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "timezone": "America/Los_Angeles"
        }
        wx_url = f"https://api.open-meteo.com/v1/forecast?{urllib.parse.urlencode(wx_params)}"
        wx_res = http_get_json(wx_url, timeout=12) or []
        if isinstance(wx_res, dict):
            wx_res = [wx_res]

        aqi_params = {
            "latitude": lats_str,
            "longitude": lons_str,
            "current": "us_aqi,pm2_5",
            "timezone": "America/Los_Angeles"
        }
        aqi_url = f"https://air-quality-api.open-meteo.com/v1/air-quality?{urllib.parse.urlencode(aqi_params)}"
        aqi_res = http_get_json(aqi_url, timeout=12) or []
        if isinstance(aqi_res, dict):
            aqi_res = [aqi_res]

        marine_params = {
            "latitude": lats_str,
            "longitude": lons_str,
            "daily": "wave_height_max",
            "length_unit": "imperial",
            "timezone": "America/Los_Angeles"
        }
        marine_url = f"https://marine-api.open-meteo.com/v1/marine?{urllib.parse.urlencode(marine_params)}"
        marine_res = http_get_json(marine_url, timeout=12) or []
        if isinstance(marine_res, dict):
            marine_res = [marine_res]

        for idx, city in enumerate(chunk):
            c_slug = city["slug"]
            city_wx = wx_res[idx] if idx < len(wx_res) and isinstance(wx_res[idx], dict) else {}
            city_aqi = aqi_res[idx] if idx < len(aqi_res) and isinstance(aqi_res[idx], dict) else {}
            city_marine = marine_res[idx] if idx < len(marine_res) and isinstance(marine_res[idx], dict) else {}

            current_wx = city_wx.get("current", {})
            daily_wx = city_wx.get("daily", {})

            aqi_val = city_aqi.get("current", {}).get("us_aqi", 30)
            if aqi_val is None:
                aqi_val = 30
            aqi_label = "Good" if aqi_val <= 50 else ("Moderate" if aqi_val <= 100 else "Unhealthy")

            wave_height = None
            if "daily" in city_marine and isinstance(city_marine["daily"], dict):
                wh_list = city_marine["daily"].get("wave_height_max", [])
                if wh_list and len(wh_list) > 0:
                    wave_height = wh_list[0]

            # Route city to nearest NOAA tide station
            assigned_station = "seattle"
            if c_slug in ["edmonds", "shoreline", "woodway", "lynnwood", "mountlake-terrace", "brier"]:
                assigned_station = "edmonds"
            elif c_slug in ["everett", "marysville", "lake-stevens", "mill-creek", "stanwood", "granite-falls"]:
                assigned_station = "everett"
            elif c_slug in ["mukilteo"]:
                assigned_station = "mukilteo"
            elif c_slug in ["des-moines", "burien", "normandy-park", "seatac"]:
                assigned_station = "des-moines"
            elif c_slug in ["federal-way", "milton", "pacific", "algona", "auburn"]:
                assigned_station = "tacoma"

            city_tide_preds = station_tides_cache.get(assigned_station, station_tides_cache.get("seattle", []))

            output[c_slug] = {
                "name": city["name"],
                "latitude": city["latitude"],
                "longitude": city["longitude"],
                "last_updated": datetime.utcnow().isoformat() + "Z",
                "current": {
                    "temp_f": current_wx.get("temperature_2m"),
                    "humidity_pct": current_wx.get("relative_humidity_2m"),
                    "wind_speed_mph": current_wx.get("wind_speed_10m"),
                    "weather_code": current_wx.get("weather_code")
                },
                "astronomy": {
                    "sunrise_today": daily_wx.get("sunrise", [""])[0] if isinstance(daily_wx.get("sunrise"), list) and daily_wx.get("sunrise") else None,
                    "sunset_today": daily_wx.get("sunset", [""])[0] if isinstance(daily_wx.get("sunset"), list) and daily_wx.get("sunset") else None
                },
                "air_quality": {
                    "us_aqi": aqi_val,
                    "status_label": aqi_label,
                    "pm2_5": city_aqi.get("current", {}).get("pm2_5")
                },
                "marine_tides": {
                    "max_wave_height_ft": wave_height,
                    "reference_station": assigned_station.replace("-", " ").title(),
                    "today_predictions": city_tide_preds,
                    "source": "NOAA CO-OPS Predictions & Open-Meteo Coastal Model"
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

# --- TEST MODULE 3: MULTI-COUNTY BUILDING PERMITS (SEATTLE, KING & SNOHOMISH) ---
def test_building_permits(cities):
    print("🏗️ [3/5] Harvesting Active Municipal Building Permits...", flush=True)
    permits_by_city = {c["slug"]: {"name": c["name"], "permits": []} for c in cities}
    
    # 1. Seattle Socrata Permits
    seattle_url = "https://data.seattle.gov/resource/76t5-zqzr.json?$limit=100&$order=issueddate%20DESC"
    s_permits = http_get_json(seattle_url)
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

    # 2. King County & Regional Open Data Feeds
    kc_url = "https://data.kingcounty.gov/resource/y23t-psfq.json?$limit=200&$order=issued_date%20DESC"
    kc_permits = http_get_json(kc_url)
    if kc_permits and isinstance(kc_permits, list):
        for p in kc_permits:
            c_name = slugify(p.get("city") or p.get("site_city") or "")
            if c_name in permits_by_city:
                permits_by_city[c_name]["permits"].append({
                    "permit_number": p.get("permit_number") or p.get("record_id"),
                    "type": p.get("permit_type") or "Building Permit",
                    "description": p.get("description") or "Municipal Project",
                    "address": p.get("address") or f"{c_name.title()}, WA",
                    "latitude": float(p["latitude"]) if p.get("latitude") else None,
                    "longitude": float(p["longitude"]) if p.get("longitude") else None,
                    "category": p.get("category", "Residential / Commercial"),
                    "value_usd": p.get("valuation") or p.get("project_cost"),
                    "issued_date": p.get("issued_date") or datetime.utcnow().strftime("%Y-%m-%d")
                })

    # 3. Snohomish County Open Data Feeds
    snoco_url = "https://data.snohomishcountywa.gov/resource/35f3-f933.json?$limit=200&$order=applied_date%20DESC"
    snoco_permits = http_get_json(snoco_url)
    if snoco_permits and isinstance(snoco_permits, list):
        for p in snoco_permits:
            c_name = slugify(p.get("city") or p.get("jurisdiction") or "")
            if c_name in permits_by_city:
                permits_by_city[c_name]["permits"].append({
                    "permit_number": p.get("permit_num") or p.get("file_number"),
                    "type": p.get("permit_type_desc") or "County Permit",
                    "description": p.get("proj_desc") or "Land Use & Construction",
                    "address": p.get("site_address") or f"{c_name.title()}, WA",
                    "latitude": float(p["latitude"]) if p.get("latitude") else None,
                    "longitude": float(p["longitude"]) if p.get("longitude") else None,
                    "category": p.get("permit_class", "Residential"),
                    "value_usd": p.get("valuation"),
                    "issued_date": p.get("applied_date") or datetime.utcnow().strftime("%Y-%m-%d")
                })

    output = {
        "city_permits": permits_by_city,
        "last_updated": datetime.utcnow().isoformat() + "Z"
    }
    save_json(PERMITS_PATH, output)

# --- TEST MODULE 4: NLR EV CHARGER INFRASTRUCTURE & EV CHARGE SCORE ---
def test_ev_scores(cities):
    print("⚡ [4/5] Harvesting NLR Electric Vehicle Charging Infrastructure...", flush=True)
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
    print("🏛️ [5/5] Calculating Municipal Property Tax Stability & Growth Index...", flush=True)
    
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
    print("==================================================", flush=True)
    print("     MYSEATTLESEARCH PHASE 3 SANDBOX ENGINE       ", flush=True)
    print("==================================================\n", flush=True)

    cities = load_cities()
    
    test_commute_and_tolls()
    test_weather_and_environment(cities)
    test_building_permits(cities)
    test_ev_scores(cities)
    test_tax_trends(cities)
    
    print("\n🎉 Sandbox Test Pipeline Complete! All static test artifacts updated in /data/.", flush=True)