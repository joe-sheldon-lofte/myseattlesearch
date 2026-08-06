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

COMMUTE_TOLLS_PATH = os.path.join(DATA_DIR, "city_commute_tolls.json")
PERMITS_PATH = os.path.join(DATA_DIR, "city_permits.json")

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

def http_get_json(url, extra_headers=None, timeout=12):
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
    except Exception:
        pass
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
        return "Express Toll Lane"
    
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
        
    if "405" in clean_id or clean_id.startswith("405tp"):
        dir_str = f" ({travel_dir})" if travel_dir else ""
        return f"I-405 Express Toll Lane{dir_str}"
    elif "167" in clean_id or clean_id.startswith("167tp"):
        dir_str = f" ({travel_dir})" if travel_dir else ""
        return f"SR 167 HOT Lane{dir_str}"
    elif "520" in clean_id:
        dir_str = f" ({travel_dir})" if travel_dir else ""
        return f"SR 520 Floating Bridge{dir_str}"
    elif "99" in clean_id:
        dir_str = f" ({travel_dir})" if travel_dir else ""
        return f"SR 99 Tunnel{dir_str}"
        
    return str(raw_name).strip()

# --- TEST MODULE 1: WSDOT LIVE TOLLS, COMMUTE CORRIDORS & REGIONAL INFRASTRUCTURE ---
def test_commute_and_tolls():
    print("🚗 [1/2] Harvesting WSDOT Travel Times, Live Toll Rates & Infrastructure...", flush=True)
    wsdot_code = os.environ.get("WSDOT_ACCESS_CODE", "").strip().strip("'").strip('"')
    
    tolls_data = []
    travel_times_data = []

    if wsdot_code:
        # Ingest active trip rates from WSDOT GetTollTripRatesAsJson
        tolls_url = f"https://wsdot.wa.gov/Traffic/api/TollRates/TollRatesREST.svc/GetTollTripRatesAsJson?AccessCode={wsdot_code}"
        res_tolls = http_get_json(tolls_url)
        
        raw_trips = []
        if isinstance(res_tolls, list):
            raw_trips = res_tolls
        elif isinstance(res_tolls, dict):
            raw_trips = res_tolls.get("Trips") or res_tolls.get("TripTollRates") or []
        
        facility_rate_map = {}
        for t in raw_trips:
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

            # Only retain active non-zero toll trip readings to prevent $0.00 duplicates
            if cents > 0:
                key = f"{facility_name}_{travel_dir}"
                if key not in facility_rate_map or cents > facility_rate_map[key]["current_toll_cents"]:
                    facility_rate_map[key] = {
                        "facility": facility_name,
                        "travel_direction": travel_dir,
                        "current_toll_cents": cents,
                        "current_toll_dollars": dollars,
                        "sign_message": sign_msg
                    }

        tolls_data = list(facility_rate_map.values())

        # Ingest WSDOT Corridor Travel Times
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

# --- TEST MODULE 2: MULTI-COUNTY BUILDING PERMITS (SEATTLE, KING & SNOHOMISH) ---
def test_building_permits(cities):
    print("🏗️ [2/2] Harvesting Active Municipal Building Permits...", flush=True)
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

    output = {
        "city_permits": permits_by_city,
        "last_updated": datetime.utcnow().isoformat() + "Z"
    }
    save_json(PERMITS_PATH, output)

if __name__ == "__main__":
    print("==================================================", flush=True)
    print("     MYSEATTLESEARCH PHASE 3 SANDBOX ENGINE       ", flush=True)
    print("==================================================\n", flush=True)

    cities = load_cities()
    
    test_commute_and_tolls()
    test_building_permits(cities)
    
    print("\n🎉 Sandbox Test Pipeline Complete! All active test artifacts updated in /data/.", flush=True)