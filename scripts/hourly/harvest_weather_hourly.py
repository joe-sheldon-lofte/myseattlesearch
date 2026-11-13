# File: scripts/hourly/harvest_weather_hourly.py
import os
import re
import json
import math
import requests
import urllib3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

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

PACIFIC_TZ = ZoneInfo("America/Los_Angeles")
DATA_DIR = os.path.join(REPO_ROOT, "data")
CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")
CRIME_STATS_PATH = os.path.join(DATA_DIR, "crime_stats.json")
CITY_DEMO_PATH = os.path.join(DATA_DIR, "city_demographics.json")

# Decoupled Output Files (Strictly Lowercase)
WEATHER_PATH = os.path.join(DATA_DIR, "city_weather.json")
RIVER_GAUGES_PATH = os.path.join(DATA_DIR, "river_gauges.json")
MOUNTAIN_PASSES_PATH = os.path.join(DATA_DIR, "weather_mountain_passes.json")

KING_SNO_RIVER_GAUGES = [
    "12119000",  # Cedar River at Renton
    "12113000",  # Green River at Auburn
    "12149000",  # Snoqualmie River near Carnation
    "12155300",  # Snohomish River at Snohomish
    "12134500",  # Skykomish River near Gold Bar
    "12125200",  # Sammamish River at Bothell
    "12167000"   # Stillaguamish River at Arlington
]

TARGET_MOUNTAIN_PASSES = [
    {
        "slug": "crystal-greenwater-sr-410",
        "name": "Crystal to Greenwater SR 410",
        "highway": "SR 410",
        "wsdot_match": ["crystal", "greenwater"],
        "fallback_elevation_ft": 2600,
        "latitude": 46.9936,
        "longitude": -121.5036,
    },
    {
        "slug": "chinook-pass-sr-410",
        "name": "Chinook Pass SR 410",
        "highway": "SR 410",
        "wsdot_match": ["chinook"],
        "fallback_elevation_ft": 5430,
        "latitude": 46.8718,
        "longitude": -121.5150,
    },
    {
        "slug": "snoqualmie-pass-i-90",
        "name": "Snoqualmie Pass I-90",
        "highway": "I-90",
        "wsdot_match": ["snoqualmie"],
        "fallback_elevation_ft": 3022,
        "latitude": 47.4204,
        "longitude": -121.4138,
    },
    {
        "slug": "stevens-pass-us-2",
        "name": "Stevens Pass US 2",
        "highway": "US 2",
        "wsdot_match": ["stevens"],
        "fallback_elevation_ft": 4061,
        "latitude": 47.7462,
        "longitude": -121.0859,
    },
    {
        "slug": "north-cascade-hwy-sr-20",
        "name": "North Cascade Hwy SR 20",
        "highway": "SR 20",
        "wsdot_match": ["north cascade", "sr 20", "washington pass"],
        "fallback_elevation_ft": 5477,
        "latitude": 48.5165,
        "longitude": -120.7357,
    },
]

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9"
}


def load_local_env():
    for env_name in [".dev.vars", ".env"]:
        env_path = os.path.join(REPO_ROOT, env_name)
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            except Exception:
                pass


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


def safe_float(val, digits=None):
    if val is None or val == "" or str(val).strip() == "-999999":
        return None
    try:
        f = float(str(val).strip())
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, digits) if digits is not None else f
    except (ValueError, TypeError):
        return None


def normalize_gauge_name(raw_name):
    """Converts 'CEDAR RIVER AT RENTON, WA' -> 'Cedar River at Renton'."""
    if not raw_name:
        return ""
    cleaned = re.sub(r",\s*(WA|WASHINGTON)\s*$", "", str(raw_name).strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    lower_words = {"at", "near", "nr", "of", "by", "above", "below", "and", "in", "on", "to"}
    parts = cleaned.split(" ")
    out = []
    for idx, w in enumerate(parts):
        lw = w.lower()
        if idx > 0 and lw in lower_words:
            out.append("near" if lw == "nr" else lw)
        else:
            out.append(w.capitalize())
    return " ".join(out)


def get_uv_label(val):
    if val is None:
        return None
    try:
        f = float(val)
        if math.isnan(f):
            return None
        if f < 3.0:
            return "Low"
        elif f < 6.0:
            return "Moderate"
        elif f < 8.0:
            return "High"
        elif f < 11.0:
            return "Very High"
        else:
            return "Extreme"
    except (ValueError, TypeError):
        return None


def get_aqi_category(aqi_val):
    if aqi_val is None:
        return None
    try:
        v = int(aqi_val)
        if v <= 50:
            return "Good"
        elif v <= 100:
            return "Moderate"
        elif v <= 150:
            return "Unhealthy for Sensitive Groups"
        elif v <= 200:
            return "Unhealthy"
        elif v <= 300:
            return "Very Unhealthy"
        return "Hazardous"
    except (ValueError, TypeError):
        return None


def format_tide_clock(raw_t):
    """Formats '2026-11-12 14:34' -> ('2026-11-12', '2:34 PM')."""
    if not raw_t:
        return "", ""
    parts = str(raw_t).strip().split(" ")
    date_part = parts[0]
    time_part = parts[1] if len(parts) > 1 else ""
    try:
        dt = datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %H:%M")
        return date_part, dt.strftime("%-I:%M %p")
    except Exception:
        return date_part, time_part


def save_json(filepath, data):
    if not data:
        print(f"   ⚠️ Skipped overwriting {filepath} (empty upstream response).", flush=True)
        return
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


def harvest_river_gauges(session, local_now):
    """Fetches live USGS discharge/stage, seasonal daily medians, and NOAA NWPS flood thresholds."""
    stations_param = ",".join(KING_SNO_RIVER_GAUGES)
    live_by_site = {}

    # 1. Live Instantaneous Values (00060 = Discharge cfs, 00065 = Gage Height ft)
    iv_url = (
        f"https://waterservices.usgs.gov/nwis/iv/"
        f"?format=json&sites={stations_param}&parameterCd=00060,00065&siteStatus=active"
    )
    try:
        res = session.get(iv_url, timeout=15)
        if res.status_code == 200:
            time_series = res.json().get("value", {}).get("timeSeries", [])
            for ts in time_series:
                src_info = ts.get("sourceInfo", {})
                site_codes = src_info.get("siteCode") or []
                site_id = site_codes[0].get("value") if site_codes else None
                if not site_id:
                    continue

                var_codes = ts.get("variable", {}).get("variableCode") or []
                param_cd = var_codes[0].get("value") if var_codes else ""
                values = (ts.get("values") or [{}])[0].get("value") or []
                latest = values[-1] if values else {}
                val_num = safe_float(latest.get("value"), 2 if param_cd == "00065" else 1)
                reading_time = latest.get("dateTime")

                entry = live_by_site.setdefault(site_id, {
                    "site_id": site_id,
                    "raw_name": src_info.get("siteName") or "",
                    "name": normalize_gauge_name(src_info.get("siteName") or ""),
                    "discharge_cfs": None,
                    "gage_height_ft": None,
                    "reading_time": None,
                })
                if val_num is not None:
                    if param_cd == "00060":
                        entry["discharge_cfs"] = val_num
                    elif param_cd == "00065":
                        entry["gage_height_ft"] = val_num
                    if reading_time and (not entry["reading_time"] or reading_time > entry["reading_time"]):
                        entry["reading_time"] = reading_time
    except Exception as e:
        print(f"   ⚠️ USGS Live Gauge Notice: {e}", flush=True)

    # 2. Seasonal Historical Percentiles (USGS Daily Statistics RDB for today's month/day)
    stats_by_site = {}
    stat_url = (
        f"https://waterservices.usgs.gov/nwis/stat/"
        f"?format=rdb&sites={stations_param}&statReportType=daily&statTypeCd=p25,p50,p75&parameterCd=00060"
    )
    try:
        s_res = session.get(stat_url, timeout=18)
        if s_res.status_code == 200:
            header_cols = None
            target_month = local_now.month
            target_day = local_now.day
            for raw_line in s_res.text.splitlines():
                if not raw_line or raw_line.startswith("#"):
                    continue
                cols = raw_line.split("\t")
                if header_cols is None:
                    if "site_no" in cols and "month_nu" in cols:
                        header_cols = cols
                    continue
                if cols[0].endswith("s") or cols[0].endswith("n"):
                    continue
                if len(cols) < len(header_cols):
                    continue
                row = dict(zip(header_cols, cols))
                try:
                    m_nu = int(row.get("month_nu", 0))
                    d_nu = int(row.get("day_nu", 0))
                except ValueError:
                    continue
                if m_nu == target_month and d_nu == target_day:
                    s_no = row.get("site_no", "").strip()
                    if s_no:
                        stats_by_site[s_no] = {
                            "p25_cfs": safe_float(row.get("p25_va"), 1),
                            "normal_discharge_cfs": safe_float(row.get("p50_va"), 1),
                            "p75_cfs": safe_float(row.get("p75_va"), 1),
                        }
    except Exception as e:
        print(f"   ⚠️ USGS Seasonal Stats Notice: {e}", flush=True)

    # 3. NOAA NWPS Official Flood Categories & Action/Flood Stages
    flood_by_site = {}
    for site_id in KING_SNO_RIVER_GAUGES:
        nwps_url = f"https://api.water.noaa.gov/nwps/v1/gauges/{site_id}"
        try:
            n_res = session.get(nwps_url, timeout=10)
            if n_res.status_code == 200:
                n_json = n_res.json()
                cats = (n_json.get("flood") or {}).get("categories") or {}

                def _stage_num(cat_key):
                    node = cats.get(cat_key)
                    if isinstance(node, dict):
                        return safe_float(node.get("stage"), 2)
                    return safe_float(node, 2)

                obs_cat = ((n_json.get("status") or {}).get("observed") or {}).get("floodCategory")
                fcst_cat = ((n_json.get("status") or {}).get("forecast") or {}).get("floodCategory")
                flood_by_site[site_id] = {
                    "nws_lid": n_json.get("lid"),
                    "action_stage_ft": _stage_num("action"),
                    "minor_flood_ft": _stage_num("minor"),
                    "moderate_flood_ft": _stage_num("moderate"),
                    "major_flood_ft": _stage_num("major"),
                    "observed_category": obs_cat,
                    "forecast_category": fcst_cat,
                }
        except Exception:
            pass

    # 4. Merge & Compute Contextual Statuses (Strictly None when baseline/threshold feeds are unavailable)
    merged_gauges = []
    for site_id in KING_SNO_RIVER_GAUGES:
        live = live_by_site.get(site_id)
        if not live:
            continue

        st = stats_by_site.get(site_id, {})
        fl = flood_by_site.get(site_id, {})

        q_cfs = live.get("discharge_cfs")
        h_ft = live.get("gage_height_ft")
        norm_cfs = st.get("normal_discharge_cfs")
        p25_cfs = st.get("p25_cfs")
        p75_cfs = st.get("p75_cfs")

        pct_of_normal = None
        flow_status = None
        if q_cfs is not None and norm_cfs is not None and norm_cfs > 0:
            pct_of_normal = round((q_cfs / norm_cfs) * 100)
            if p25_cfs is not None and p75_cfs is not None:
                if q_cfs < p25_cfs:
                    flow_status = "Below Normal"
                elif q_cfs > p75_cfs:
                    flow_status = "Elevated"
                else:
                    flow_status = "Normal"
            else:
                if pct_of_normal < 75:
                    flow_status = "Below Normal"
                elif pct_of_normal > 135:
                    flow_status = "Elevated"
                else:
                    flow_status = "Normal"

        action_ft = fl.get("action_stage_ft")
        minor_ft = fl.get("minor_flood_ft")
        moderate_ft = fl.get("moderate_flood_ft")
        major_ft = fl.get("major_flood_ft")
        has_stage_thresholds = any(v is not None for v in (action_ft, minor_ft, moderate_ft, major_ft))

        flood_status = None
        if h_ft is not None and has_stage_thresholds:
            if major_ft is not None and h_ft >= major_ft:
                flood_status = "Major Flood"
            elif moderate_ft is not None and h_ft >= moderate_ft:
                flood_status = "Moderate Flood"
            elif minor_ft is not None and h_ft >= minor_ft:
                flood_status = "Minor Flood"
            elif action_ft is not None and h_ft >= action_ft:
                flood_status = "Action Stage"
            else:
                flood_status = "Normal"
        elif fl.get("observed_category"):
            raw_cat = str(fl["observed_category"]).strip().lower()
            if raw_cat in ("no_flooding", "low_threshold"):
                flood_status = "Normal"
            elif raw_cat != "none":
                flood_status = raw_cat.replace("_", " ").title()

        merged_gauges.append({
            "site_id": site_id,
            "slug": slugify(live["name"]),
            "name": live["name"],
            "discharge_cfs": q_cfs,
            "gage_height_ft": h_ft,
            "normal_discharge_cfs": norm_cfs,
            "p25_discharge_cfs": p25_cfs,
            "p75_discharge_cfs": p75_cfs,
            "pct_of_normal": pct_of_normal,
            "flow_status": flow_status,
            "action_stage_ft": action_ft,
            "minor_flood_ft": minor_ft,
            "moderate_flood_ft": moderate_ft,
            "major_flood_ft": major_ft,
            "flood_status": flood_status,
            "reading_time": live.get("reading_time"),
        })

    return merged_gauges


def harvest_mountain_passes(session):
    """Combines live WSDOT Mountain Pass conditions with 11-day Open-Meteo summit snowfall forecasts."""
    wsdot_key = (os.environ.get("WSDOT_ACCESS_CODE") or "").strip()
    wsdot_records = []

    if wsdot_key:
        wsdot_url = (
            "https://www.wsdot.wa.gov/Traffic/api/MountainPassConditions/"
            "MountainPassConditionsREST.svc/GetMountainPassConditionsAsJson"
        )
        try:
            w_res = session.get(wsdot_url, params={"AccessCode": wsdot_key}, timeout=15)
            if w_res.status_code == 200:
                payload = w_res.json()
                if isinstance(payload, list):
                    wsdot_records = payload
            else:
                print(f"   ⚠️ WSDOT Mountain Pass API returned HTTP {w_res.status_code}", flush=True)
        except Exception as e:
            print(f"   ⚠️ WSDOT Mountain Pass API error: {type(e).__name__}", flush=True)
    else:
        print("   ⚠️ WSDOT_ACCESS_CODE not set; using Open-Meteo summit forecasts only.", flush=True)

    # Fetch 11-Day Alpine & Snowfall Forecasts from Open-Meteo for all 5 passes in one batch
    pass_wx_map = {}
    try:
        om_params = {
            "latitude": ",".join(str(p["latitude"]) for p in TARGET_MOUNTAIN_PASSES),
            "longitude": ",".join(str(p["longitude"]) for p in TARGET_MOUNTAIN_PASSES),
            "elevation": ",".join(str(round(p["fallback_elevation_ft"] * 0.3048, 1)) for p in TARGET_MOUNTAIN_PASSES),
            "current": "temperature_2m,weather_code,wind_speed_10m,snowfall",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,snowfall_sum",
            "forecast_days": 11,
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "timezone": "America/Los_Angeles",
        }
        om_res = session.get("https://api.open-meteo.com/v1/forecast", params=om_params, timeout=15)
        if om_res.status_code == 200:
            om_json = om_res.json()
            if isinstance(om_json, dict):
                om_json = [om_json]
            for idx, p_cfg in enumerate(TARGET_MOUNTAIN_PASSES):
                if idx < len(om_json) and isinstance(om_json[idx], dict):
                    pass_wx_map[p_cfg["slug"]] = om_json[idx]
    except Exception as e:
        print(f"   ⚠️ Open-Meteo Alpine Forecast notice: {e}", flush=True)

    passes_output = []
    for p_cfg in TARGET_MOUNTAIN_PASSES:
        matched_wsdot = None
        for rec in wsdot_records:
            p_name = str(rec.get("MountainPassName") or "").lower()
            if any(tok in p_name for tok in p_cfg["wsdot_match"]):
                matched_wsdot = rec
                break

        om_data = pass_wx_map.get(p_cfg["slug"], {})
        om_curr = om_data.get("current") or {}
        om_daily = om_data.get("daily") or {}

        # Skip appending pass only if BOTH WSDOT and Open-Meteo failed completely
        if not matched_wsdot and not om_data:
            continue

        elev_ft = p_cfg["fallback_elevation_ft"]
        wsdot_temp = None
        weather_cond = ""
        wsdot_updated = None
        travel_advisory = None
        restrictions_list = []

        if matched_wsdot:
            road_cond = str(matched_wsdot.get("RoadCondition") or "").strip()
            weather_cond = str(matched_wsdot.get("WeatherCondition") or "").strip()
            wsdot_temp = safe_float(matched_wsdot.get("TemperatureInFahrenheit"), 0)
            if wsdot_temp is not None:
                wsdot_temp = int(wsdot_temp)
            if matched_wsdot.get("ElevationInFeet"):
                try:
                    elev_ft = int(matched_wsdot["ElevationInFeet"])
                except (ValueError, TypeError):
                    pass

            r1 = matched_wsdot.get("RestrictionOne") or {}
            r2 = matched_wsdot.get("RestrictionTwo") or {}
            r1_dir = str(r1.get("TravelDirection") or "").strip()
            r1_text = str(r1.get("RestrictionText") or "").strip()
            r2_dir = str(r2.get("TravelDirection") or "").strip()
            r2_text = str(r2.get("RestrictionText") or "").strip()

            for d_lbl, r_txt in ((r1_dir, r1_text), (r2_dir, r2_text)):
                if d_lbl or r_txt:
                    restrictions_list.append({
                        "direction": d_lbl,
                        "text": r_txt if r_txt else "No restrictions",
                    })

            travel_advisory = bool(matched_wsdot.get("TravelAdvisoryActive"))
            wsdot_updated = matched_wsdot.get("DateUpdated")

            combined_status_text = f"{road_cond} {r1_text} {r2_text}".lower()
            if "season" in combined_status_text and "clos" in combined_status_text:
                pass_status = "Seasonal Closure"
            elif "clos" in combined_status_text:
                pass_status = "Temporary Closure"
            elif any(k in combined_status_text for k in ["chain", "traction", "prohibited", "closed"]):
                pass_status = "Restrictions Active"
            else:
                pass_status = "Open"

            is_seasonal_closure = pass_status == "Seasonal Closure"
            if road_cond:
                display_road_cond = road_cond
            elif is_seasonal_closure:
                display_road_cond = "Closed for the season"
            else:
                display_road_cond = "Data not available from WSDOT at this time"
        else:
            pass_status = None
            is_seasonal_closure = False
            display_road_cond = "Data not available from WSDOT at this time"

        # Use WSDOT roadside temp when open & valid; fall back cleanly to Open-Meteo summit sensor during seasonal closure or WSDOT outage
        effective_temp = wsdot_temp
        temp_source = "WSDOT Roadside" if wsdot_temp is not None else None
        if is_seasonal_closure or effective_temp is None:
            om_t = safe_float(om_curr.get("temperature_2m"), 0)
            if om_t is not None:
                effective_temp = int(om_t)
                temp_source = "Open-Meteo Summit"
            else:
                effective_temp = None
                temp_source = None

        clean_weather_cond = (
            weather_cond
            if weather_cond and weather_cond.lower() not in ("none published", "unknown", "pass closed")
            else None
        )

        raw_snow = om_daily.get("snowfall_sum") or []
        snowfall_in = [round(float(v), 1) if v is not None else None for v in raw_snow]

        passes_output.append({
            "slug": p_cfg["slug"],
            "name": p_cfg["name"],
            "highway": p_cfg["highway"],
            "elevation_ft": elev_ft,
            "latitude": p_cfg["latitude"],
            "longitude": p_cfg["longitude"],
            "pass_status": pass_status,
            "is_seasonal_closure": is_seasonal_closure,
            "travel_advisory_active": travel_advisory,
            "road_condition": display_road_cond,
            "restrictions": restrictions_list,
            "current": {
                "temp_f": effective_temp,
                "temp_source": temp_source,
                "roadside_weather": clean_weather_cond,
                "summit_weather_code": om_curr.get("weather_code"),
                "summit_wind_mph": om_curr.get("wind_speed_10m"),
            },
            "forecast_11_day": {
                "dates": om_daily.get("time", []),
                "weather_code": om_daily.get("weather_code", []),
                "temp_max": om_daily.get("temperature_2m_max", []),
                "temp_min": om_daily.get("temperature_2m_min", []),
                "precip_prob_max": om_daily.get("precipitation_probability_max", []),
                "snowfall_in": snowfall_in,
            },
            "wsdot_updated": wsdot_updated,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        })

    return passes_output


def harvest_weather_data():
    load_local_env()
    local_now = datetime.now(PACIFIC_TZ)
    today_local_str = local_now.strftime("%Y-%m-%d")
    begin_tide_str = local_now.strftime("%Y%m%d")

    print("⛅ Harvesting 11-Day Weather, 7-Day AQI, 11-Day Tides, River Baselines & Mountain Passes...", flush=True)
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)

    cities = load_cities()
    valid_cities = [c for c in cities if c.get("latitude") is not None and c.get("longitude") is not None]

    # 1. Fetch Open-Meteo 11-Day Weather & UV Index (batches of 3)
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
            "forecast_days": 11,
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "timezone": "America/Los_Angeles"
        }
        try:
            res = session.get("https://api.open-meteo.com/v1/forecast", params=wx_params, timeout=14)
            if res.status_code == 200:
                wx_res = res.json()
                if isinstance(wx_res, dict):
                    wx_res = [wx_res]
                for idx, city in enumerate(chunk):
                    if idx < len(wx_res) and isinstance(wx_res[idx], dict):
                        wx_cache[city["slug"]] = wx_res[idx]
        except Exception as e:
            print(f"   ⚠️ Open-Meteo batch notice: {e}", flush=True)

    # 2. Fetch NOAA 11-Day Harmonic Tide Predictions (range=264 hours from local midnight)
    noaa_stations = {
        "seattle": "9447130",       # Seattle Central Pier 54
        "edmonds": "9447427",       # Edmonds Ferry Pier
        "everett": "9447659",       # Everett Possession Sound
        "tacoma": "9446484",        # Tacoma Commencement Bay
        "des-moines": "9447029"     # Des Moines Marina
    }

    station_tides_cache = {}
    for st_key, st_id in noaa_stations.items():
        noaa_url = (
            f"https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
            f"?begin_date={begin_tide_str}&range=264&station={st_id}"
            f"&product=predictions&datum=MLLW&time_zone=lst_ldt&units=english&interval=hilo&format=json"
        )
        try:
            res = session.get(noaa_url, timeout=12)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, dict) and "predictions" in data:
                    preds = []
                    for p in data["predictions"]:
                        raw_t = p.get("t", "")
                        d_str, clock_str = format_tide_clock(raw_t)
                        preds.append({
                            "date": d_str,
                            "time": raw_t,
                            "time_formatted": clock_str,
                            "height_ft": round(float(p.get("v", 0)), 1),
                            "type": "High" if p.get("type") == "H" else "Low"
                        })
                    station_tides_cache[st_key] = preds
        except Exception as e:
            print(f"   ⚠️ NOAA Tides notice [{st_key}]: {e}", flush=True)

    # 3. Fetch Regional US AQI & PM2.5 Current + 7-Day Daily Forecast (Open-Meteo CAMS)
    city_aqi_map = {}
    regional_hubs = [
        {"name": "Seattle-Bellevue-Kent Valley", "lat": 47.6062, "lon": -122.3321},
        {"name": "Everett-Marysville-Lynnwood", "lat": 47.9790, "lon": -122.2021},
        {"name": "Tacoma-Puyallup", "lat": 47.2529, "lon": -122.4443}
    ]
    station_data = []
    aqi_params = {
        "latitude": ",".join([str(h["lat"]) for h in regional_hubs]),
        "longitude": ",".join([str(h["lon"]) for h in regional_hubs]),
        "current": "us_aqi,pm2_5",
        "hourly": "us_aqi,pm2_5",
        "forecast_days": 7,
        "timezone": "America/Los_Angeles"
    }
    try:
        aq_res = session.get("https://air-quality-api.open-meteo.com/v1/air-quality", params=aqi_params, timeout=14)
        if aq_res.status_code == 200:
            aq_json = aq_res.json()
            if isinstance(aq_json, dict):
                aq_json = [aq_json]
            for idx, hub in enumerate(regional_hubs):
                if idx < len(aq_json) and isinstance(aq_json[idx], dict):
                    curr = aq_json[idx].get("current", {})
                    raw_aqi = safe_float(curr.get("us_aqi"))
                    aqi_num = int(round(raw_aqi)) if raw_aqi is not None else None
                    pm_num = safe_float(curr.get("pm2_5"), 1)

                    hr_block = aq_json[idx].get("hourly") or {}
                    hr_times = hr_block.get("time") or []
                    hr_aqi = hr_block.get("us_aqi") or []
                    hr_pm = hr_block.get("pm2_5") or []
                    daily_peaks = {}
                    for h_i, ts_str in enumerate(hr_times):
                        d_key = str(ts_str).split("T")[0]
                        a_val = safe_float(hr_aqi[h_i]) if h_i < len(hr_aqi) else None
                        p_val = safe_float(hr_pm[h_i], 1) if h_i < len(hr_pm) else None
                        bucket = daily_peaks.setdefault(d_key, {"aqi_max": None, "pm_max": None})
                        if a_val is not None:
                            int_a = int(round(a_val))
                            bucket["aqi_max"] = int_a if bucket["aqi_max"] is None else max(bucket["aqi_max"], int_a)
                        if p_val is not None:
                            bucket["pm_max"] = p_val if bucket["pm_max"] is None else max(bucket["pm_max"], p_val)

                    f_dates = sorted(daily_peaks.keys())
                    f_aqi_max = [daily_peaks[d]["aqi_max"] for d in f_dates]
                    f_pm_max = [daily_peaks[d]["pm_max"] for d in f_dates]
                    f_labels = [get_aqi_category(val) for val in f_aqi_max]

                    station_data.append({
                        "reporting_area": hub["name"],
                        "aqi": aqi_num,
                        "pm2_5": pm_num,
                        "category": get_aqi_category(aqi_num),
                        "parameter": "PM2.5" if (aqi_num is not None or pm_num is not None) else None,
                        "forecast_7_day": {
                            "dates": f_dates,
                            "us_aqi_max": f_aqi_max,
                            "pm2_5_max": f_pm_max,
                            "status_label": f_labels,
                        }
                    })
    except Exception as e:
        print(f"   ⚠️ Air Quality service notice: {e}", flush=True)

    for c in valid_cities:
        c_slug = c["slug"]
        station = station_data[0] if station_data else {}
        if c_slug in ["everett", "marysville", "lynnwood", "edmonds", "arlington", "snohomish", "stanwood", "mukilteo", "mill-creek", "lake-stevens"] and len(station_data) > 1:
            station = station_data[1]
        elif c_slug in ["tacoma", "auburn", "kent", "federal-way", "pacific", "algona", "milton"] and len(station_data) > 2:
            station = station_data[2]
        city_aqi_map[c_slug] = station

    # 4. Assemble Pure City-Keyed Weather JSON (data/city_weather.json)
    output = {}
    has_any_weather = False
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

        city_tides_11d = station_tides_cache.get(assigned_station, station_tides_cache.get("seattle", []))
        today_tides = [t for t in city_tides_11d if t.get("date") == today_local_str]
        aqi_info = city_aqi_map.get(c_slug, {})

        uv_val = safe_float(current_wx.get("uv_index"), 1)
        temp_val = current_wx.get("temperature_2m")
        d_dates = daily_wx.get("time", [])
        if temp_val is not None or d_dates:
            has_any_weather = True

        d_codes = daily_wx.get("weather_code", [])
        d_tmax = daily_wx.get("temperature_2m_max", [])
        d_tmin = daily_wx.get("temperature_2m_min", [])
        d_precip = daily_wx.get("precipitation_probability_max", [])
        d_uv = daily_wx.get("uv_index_max", [])

        output[c_slug] = {
            "name": c["name"],
            "latitude": c["latitude"],
            "longitude": c["longitude"],
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "current": {
                "temp_f": temp_val,
                "humidity_pct": current_wx.get("relative_humidity_2m"),
                "wind_speed_mph": current_wx.get("wind_speed_10m"),
                "weather_code": current_wx.get("weather_code"),
                "uv_index": uv_val,
                "uv_label": get_uv_label(uv_val)
            },
            "astronomy": {
                "sunrise_today": daily_wx.get("sunrise", [None])[0] if isinstance(daily_wx.get("sunrise"), list) and daily_wx.get("sunrise") else None,
                "sunset_today": daily_wx.get("sunset", [None])[0] if isinstance(daily_wx.get("sunset"), list) and daily_wx.get("sunset") else None
            },
            "air_quality": {
                "us_aqi": aqi_info.get("aqi"),
                "pm2_5": aqi_info.get("pm2_5"),
                "status_label": aqi_info.get("category"),
                "parameter": aqi_info.get("parameter"),
                "reporting_area": aqi_info.get("reporting_area"),
                "forecast_7_day": aqi_info.get("forecast_7_day", {"dates": [], "us_aqi_max": [], "pm2_5_max": [], "status_label": []})
            },
            "marine_tides": {
                "reference_station": assigned_station.replace("-", " ").title(),
                "predictions_11_day": city_tides_11d,
                "today_predictions": today_tides,
                "source": "NOAA CO-OPS Predictions"
            },
            "forecast_11_day": {
                "dates": d_dates,
                "weather_code": d_codes,
                "temp_max": d_tmax,
                "temp_min": d_tmin,
                "precip_prob_max": d_precip,
                "uv_index_max": d_uv
            },
            "forecast_7_day": {
                "dates": d_dates[:7],
                "weather_code": d_codes[:7],
                "temp_max": d_tmax[:7],
                "temp_min": d_tmin[:7],
                "precip_prob_max": d_precip[:7],
                "uv_index_max": d_uv[:7]
            }
        }

    if has_any_weather:
        save_json(WEATHER_PATH, output)
    else:
        print(f"   ⚠️ Skipped overwriting {WEATHER_PATH} (no live weather data returned).", flush=True)

    # 5. Harvest & Save River Gauges with Seasonal Baselines + Flood Stages (data/river_gauges.json)
    gauges = harvest_river_gauges(session, local_now)
    save_json(RIVER_GAUGES_PATH, gauges)

    # 6. Harvest & Save Mountain Pass Conditions + 11-Day Snowfall Forecasts (data/weather_mountain_passes.json)
    passes = harvest_mountain_passes(session)
    save_json(MOUNTAIN_PASSES_PATH, passes)


if __name__ == "__main__":
    harvest_weather_data()