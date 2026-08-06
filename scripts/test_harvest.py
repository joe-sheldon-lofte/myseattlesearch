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

KING_SNO_RIVER_GAUGES = [
    "12119000",  # Cedar River at Renton
    "12113000",  # Green River at Auburn
    "12149000",  # Snoqualmie River near Carnation
    "12155300",  # Snohomish River at Snohomish
    "12134500",  # Skykomish River near Gold Bar
    "12125200",  # Sammamish River at Bothell
    "12167000"   # Stillaguamish River at Arlington
]

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

def clean_wsdot_facility_name(raw_name, travel_dir):
    if not raw_name:
        return "Toll Lane"
    
    clean_id = str(raw_name).strip().lower()
    
    wsdot_known_map = {
        "520tp00422": "SR 520 Floating Bridge (Eastbound)",
        "520tp00421": "SR 520 Floating Bridge (Westbound)",
        "099tp03060": "SR 99 Tunnel (Southbound)",
        "099tp03268": "SR 99 Tunnel (Northbound)",
        "509tp02050": "SR 509 Expressway (Southbound)",
        "509tp02051": "SR 509 Expressway (Southbound)",
        "509tp02092": "SR 509 Expressway (Southbound)",
        "509tp02093": "SR 509 Expressway (Southbound)",
    }
    
    if clean_id in wsdot_known_map:
        return wsdot_known_map[clean_id]
        
    if clean_id.startswith("405tp"):
        dir_str = f" ({travel_dir})" if travel_dir else ""
        return f"I-405 Express Toll Lane{dir_str}"
    elif clean_id.startswith("167tp"):
        dir_str = f" ({travel_dir})" if travel_dir else ""
        return f"SR 167 HOT Lane{dir_str}"
        
    return str(raw_name).strip()

# --- TEST MODULE 1: WSDOT LIVE TOLLS, COMMUTE CORRIDORS & REGIONAL INFRASTRUCTURE ---
def test_commute_and_tolls():
    print("🚗 [1/5] Harvesting WSDOT Travel Times, Live Toll Rates & Infrastructure...", flush=True)
    wsdot_code = os.environ.get("WSDOT_ACCESS_CODE", "").strip().strip("'").strip('"')
    
    tolls_data = []
    travel_times_data = []

    if wsdot_code:
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
            
            raw_facility = t.get("TripName") or t.get("LocationName") or t.get("FacilityName") or ""
            travel_dir = t.get("TravelDirection") or t.get("Direction") or ""
            facility_name = clean_wsdot_facility_name(raw_facility, travel_dir)
            
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

# --- TEST MODULE 2: NOAA PUGET SOUND TIDES, AQI & RIVER GAUGES (CONSOLIDATED INTO CITY_WEATHER.JSON) ---
def test_weather_and_environment(cities):
    print("⛅ [2/5] Ingesting NOAA Puget Sound Tides, EPA AirNow AQI & River Gauges into city_weather.json...", flush=True)
    
    # 1. Load existing city_weather.json baseline if present
    weather_data = {}
    if os.path.exists(WEATHER_PATH):
        try:
            with open(WEATHER_PATH, "r", encoding="utf-8") as f:
                weather_data = json.load(f)
        except Exception as e:
            print(f"   ⚠️ Weather load notice: {e}", flush=True)

    # 2. NOAA Harmonic Tide Station Predictions (Capitalized TODAY parameter)
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

    # 3. EPA AirNow Air Quality
    airnow_key = os.environ.get("AIRNOW_API_KEY", "").strip().strip("'").strip('"')
    city_aqi_map = {}
    if airnow_key and cities:
        regional_stations = [
            {"name": "Seattle-Bellevue-Kent Valley", "lat": 47.6062, "lon": -122.3321},
            {"name": "Everett-Marysville-Lynnwood", "lat": 47.9790, "lon": -122.2021},
            {"name": "Tacoma-Puyallup", "lat": 47.2529, "lon": -122.4443}
        ]
        station_data = []
        for st in regional_stations:
            url = f"https://www.airnowapi.org/aq/observation/latLong/current/?format=application/json&latitude={st['lat']}&longitude={st['lon']}&distance=25&API_KEY={airnow_key}"
            obs = http_get_json(url, timeout=10)
            if obs and isinstance(obs, list) and len(obs) > 0:
                primary = obs[0]
                station_data.append({
                    "reporting_area": primary.get("ReportingArea", st["name"]),
                    "aqi": primary.get("AQI", 30),
                    "category": primary.get("Category", {}).get("Name", "Good"),
                    "parameter": primary.get("ParameterName", "PM2.5"),
                    "observed_time": f"{primary.get('DateObserved', '')} {primary.get('HourObserved', '')}:00"
                })

        for c in cities:
            c_slug = c["slug"]
            station = station_data[0] if station_data else {"aqi": 35, "category": "Good", "parameter": "PM2.5", "reporting_area": "Seattle Metro"}
            if c_slug in ["everett", "marysville", "lynnwood", "edmonds", "arlington", "snohomish", "stanwood"] and len(station_data) > 1:
                station = station_data[1]
            elif c_slug in ["tacoma", "auburn", "kent", "federal-way", "pacific", "algona", "milton"] and len(station_data) > 2:
                station = station_data[2]
                
            city_aqi_map[c_slug] = station

    # 4. USGS River Gauges with DateTime Timestamp
    stations_param = ",".join(KING_SNO_RIVER_GAUGES)
    usgs_url = f"https://waterservices.usgs.gov/nwis/iv/?format=json&sites={stations_param}&parameterCd=00060,00065&siteStatus=active"
    gauge_data = []
    
    try:
        res = http_get_json(usgs_url, timeout=12)
        if res and isinstance(res, dict):
            time_series = res.get("value", {}).get("timeSeries", [])
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
        print(f"   ⚠️ USGS River Gauge Harvest Notice: {e}", flush=True)

    # 5. Enrich city_weather.json cleanly
    for c in cities:
        c_slug = c["slug"]
        if c_slug not in weather_data:
            weather_data[c_slug] = {"name": c["name"], "latitude": c["latitude"], "longitude": c["longitude"]}

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
        aqi_info = city_aqi_map.get(c_slug, {"aqi": 35, "category": "Good", "parameter": "PM2.5"})

        weather_data[c_slug]["last_updated"] = datetime.utcnow().isoformat() + "Z"
        weather_data[c_slug]["air_quality"] = {
            "us_aqi": aqi_info.get("aqi", 35),
            "status_label": aqi_info.get("category", "Good"),
            "parameter": aqi_info.get("parameter", "PM2.5"),
            "reporting_area": aqi_info.get("reporting_area", "Seattle Metro")
        }
        weather_data[c_slug]["marine_tides"] = {
            "reference_station": assigned_station.replace("-", " ").title(),
            "today_predictions": city_tides,
            "source": "NOAA CO-OPS Predictions"
        }

    # Attach top-level regional water gauges array
    weather_data["_regional_water_gauges"] = gauge_data

    save_json(WEATHER_PATH, weather_data)

# --- TEST MODULE 3: MULTI-COUNTY BUILDING PERMITS (SEATTLE, KING & SNOHOMISH) ---
def test_building_permits(cities):
    print("🏗️ [3/5] Harvesting Active Municipal Building Permits (Seattle, King, Snohomish)...", flush=True)
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

    # 2. King County Active Permits (ir2i-v33j)
    kc_url = "https://data.kingcounty.gov/resource/ir2i-v33j.json?$limit=200&$order=issued_date%20DESC"
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

    # 3. Snohomish County Open Data Feeds (data.snoco.org)
    snoco_url = "https://data.snoco.org/resource/35f3-f933.json?$limit=200&$order=applied_date%20DESC"
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