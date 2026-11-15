import os
import sys
import re
import json
import math
import boto3
import requests
import datetime
from zoneinfo import ZoneInfo
from botocore.config import Config

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None

SENTRY_DSN = os.getenv("SENTRY_DSN")
if SENTRY_DSN and sentry_sdk:
    sentry_sdk.init(dsn=SENTRY_DSN, traces_sample_rate=0.0, environment="production")

R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_ENDPOINT = os.getenv("R2_ENDPOINT_URL")
BUCKET = os.getenv("R2_DATA_BUCKET_NAME")

D1_API_TOKEN = os.getenv("CF_D1_API_TOKEN")
ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID")
DATABASE_ID = os.getenv("CF_DATABASE_TELEMETRY_ID")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PACIFIC_TZ = ZoneInfo("America/Los_Angeles")

def slugify(text):
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[-\s]+", "-", text)

def normalize_name(text):
    cleaned = text.lower()
    cleaned = re.sub(r"\b(school district|schools|school|public schools|sd|#\d+)\b", " ", cleaned)
    cleaned = re.sub(r"[^\w\s]", "", cleaned)
    return " ".join(cleaned.split())

def load_canonical_cities():
    candidates = [
        os.path.join(BASE_DIR, "_data", "city_data.json"),
        os.path.join(BASE_DIR, "data", "city_data.json")
    ]
    file_path = next((p for p in candidates if os.path.exists(p)), None)
    if not file_path:
        raise FileNotFoundError("Could not locate city_data.json.")

    with open(file_path, "r", encoding="utf-8") as f:
        records = json.load(f)

    cities = []
    for entry in records:
        city_name = entry.get("City")
        lat = entry.get("Latitude")
        lon = entry.get("Longitude")
        if not city_name or lat is None or lon is None:
            continue
        
        county = entry.get("County", "King").strip().title()
        county_code = "WAC033" if county == "King" else ("WAC061" if county == "Snohomish" else "WAC053")

        raw_districts = entry.get("School District", "")
        district_list = [d.strip() for d in raw_districts.split(",") if d.strip()]

        cities.append({
            "name": city_name,
            "slug": slugify(city_name),
            "lat": float(lat),
            "lon": float(lon),
            "county_code": county_code,
            "normalized_districts": [normalize_name(d) for d in district_list]
        })
    return cities

def get_s3_client():
    return boto3.client("s3", endpoint_url=R2_ENDPOINT, aws_access_key_id=R2_ACCESS_KEY, aws_secret_access_key=R2_SECRET_KEY, config=Config(signature_version="s3v4"))

def haversine_miles(lat1, lon1, lat2, lon2):
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0)**2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0)**2
    return r * (2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a)))

def fetch_r2_json(s3, key):
    try:
        res = s3.get_object(Bucket=BUCKET, Key=key)
        return json.loads(res["Body"].read().decode("utf-8"))
    except:
        return None

def fetch_recent_earthquakes():
    if not (D1_API_TOKEN and ACCOUNT_ID and DATABASE_ID):
        print("⚠️ D1 credentials missing. Skipping seismic check.")
        return []
    url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/d1/database/{DATABASE_ID}/query"
    headers = {"Authorization": f"Bearer {D1_API_TOKEN}", "Content-Type": "application/json"}
    cutoff_time = int((datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=6)).timestamp() * 1000)
    sql = "SELECT magnitude, place, latitude, longitude, time_ms FROM earthquakes WHERE time_ms >= ? AND magnitude >= 2.0"
    try:
        res = requests.post(url, headers=headers, json=[{"sql": sql, "params": [cutoff_time]}], timeout=10).json()
        if res.get("success") and res.get("result"):
            return res["result"][0].get("results", [])
    except:
        pass
    return []

def evaluate_school_decay(report, now_pac):
    if report.get("is_tomorrow"): return True
    eff_str = report.get("effective_date", "")
    try:
        eff_dt = datetime.datetime.fromisoformat(eff_str).astimezone(PACIFIC_TZ)
        if eff_dt.date() > now_pac.date(): return True
        if eff_dt.date() < now_pac.date(): return False
    except: pass

    op = str(report.get("operating_code", ""))
    if op in ["2", "3", "4", "5", "6"] and now_pac.hour >= 12: return False
    if op == "1" and (now_pac.hour > 16 or (now_pac.hour == 16 and now_pac.minute >= 30)): return False
    return True

def point_in_polygon(x, y, poly):
    n = len(poly)
    inside = False
    p1x, p1y = poly[0]
    for i in range(1, n + 1):
        p2x, p2y = poly[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xints = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xints:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside

def compile_master_alerts():
    cities = load_canonical_cities()
    s3 = get_s3_client()
    now_pac = datetime.datetime.now(PACIFIC_TZ)

    prev_alerts = fetch_r2_json(s3, "telemetry/active_alerts.json") or {}
    power_data = fetch_r2_json(s3, "telemetry/power_outages.json") or {}
    wildfire_data = fetch_r2_json(s3, "telemetry/wildfires.json") or {}
    weather_data = fetch_r2_json(s3, "telemetry/weather_alerts.json") or {}
    schools_data = fetch_r2_json(s3, "telemetry/schools.json") or {}
    earthquakes = fetch_recent_earthquakes()

    total_regional_customers_out = 0
    outages_by_city = {}
    if "utilities" in power_data:
        for p_code, p_obj in power_data["utilities"].items():
            cust = int(p_obj.get("customers_affected", 0))
            total_regional_customers_out += cust
            # Simple thresholding until granular polys are implemented
            if cust > 5000:
                for c in cities: outages_by_city[c["slug"]] = True

    major_blackout = total_regional_customers_out >= 25000
    major_quake = any(q.get("magnitude", 0) >= 5.0 and 46.5 <= q.get("latitude", 0) <= 49.0 and -123.5 <= q.get("longitude", 0) <= -121.5 for q in earthquakes)
    wildfires = wildfire_data.get("incidents", [])
    wx_alerts = weather_data.get("alerts", [])
    active_schools = [r for r in schools_data.get("reports", []) if evaluate_school_decay(r, now_pac)]

    alerts_payload = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "global": {
            "critical_grid_failure": major_blackout,
            "seismic_emergency": major_quake,
            "school_emergency": any(r["severity"] == "red" for r in active_schools),
            "school_advisory": any(r["severity"] == "amber" for r in active_schools),
            "regional_target_url": "/neighborhood/region/emergency-safety/"
        },
        "neighborhoods": {}
    }

    total_active_alerts = 1 if major_blackout else 0
    if major_quake: total_active_alerts += 1

    for city in cities:
        slug, lat, lon = city["slug"], city["lat"], city["lon"]
        
        # 1. Power
        p_alert = outages_by_city.get(slug, False)

        # 2. Wildfire
        w_alert = False
        w_meta = None
        for fire in wildfires:
            f_lat, f_lon = fire.get("coordinates", {}).get("latitude"), fire.get("coordinates", {}).get("longitude")
            if f_lat and f_lon:
                acres = float(fire.get("acres", 0))
                dist = haversine_miles(lat, lon, f_lat, f_lon)
                if dist <= 30.0 or (acres >= 500 and dist <= 60.0):
                    w_alert = True
                    w_meta = {"name": fire.get("name"), "acres": acres, "distance": round(dist, 1)}
                    break

        # 3. Earthquake
        eq_alert = False
        eq_meta = None
        for q in earthquakes:
            mag = float(q.get("magnitude", 0))
            dist = haversine_miles(lat, lon, q.get("latitude"), q.get("longitude"))
            if (mag >= 2.5 and dist <= 20.0) or (mag >= 4.0 and dist <= 50.0) or (mag >= 5.5 and dist <= 120.0):
                eq_alert = True
                eq_meta = {"magnitude": mag, "place": q.get("place"), "distance": round(dist, 1)}
                break

        # 4. Schools
        s_reps = []
        for rep in active_schools:
            org = normalize_name(rep.get("org_name", ""))
            if any((d and (d in org or org in d)) for d in city["normalized_districts"]):
                s_reps.append(rep)
        s_level = "red" if any(r["severity"] == "red" for r in s_reps) else ("amber" if s_reps else "optimal")
        s_alert = s_level != "optimal"

        # 5. Weather (NWS)
        wx_alert = False
        wx_meta = []
        for wx in wx_alerts:
            if city["county_code"] in wx.get("geocode_ugc", []):
                polys = wx.get("polygon", [])
                is_hit = False
                if polys:
                    for ring in polys:
                        if point_in_polygon(lon, lat, ring):
                            is_hit = True
                            break
                else:
                    is_hit = True # County-wide alert
                
                if is_hit:
                    wx_alert = True
                    wx_meta.append({"event": wx.get("event"), "severity": wx.get("severity")})

        city_has_alert = p_alert or w_alert or eq_alert or s_alert or wx_alert
        if city_has_alert: total_active_alerts += 1

        alerts_payload["neighborhoods"][slug] = {
            "name": city["name"],
            "has_alert": city_has_alert,
            "power_outage": p_alert,
            "wildfire": w_alert,
            "wildfire_meta": w_meta,
            "earthquake": eq_alert,
            "earthquake_meta": eq_meta,
            "school": s_alert,
            "school_level": s_level,
            "weather": wx_alert,
            "weather_meta": wx_meta
        }

    alerts_payload["global"]["active_alert_count"] = total_active_alerts

    s3.put_object(
        Bucket=BUCKET,
        Key="telemetry/active_alerts.json",
        Body=json.dumps(alerts_payload, separators=(',', ':')),
        ContentType="application/json",
        CacheControl="public, max-age=60"
    )
    print(f"✅ Master alert matrix published to R2. Total active alerts: {total_active_alerts}")

    # Stateful Build Trigger Evaluation
    prev_count = prev_alerts.get("global", {}).get("active_alert_count", 0)
    if total_active_alerts != prev_count:
        print(f"⚠️ Alert state changed ({prev_count} -> {total_active_alerts}). Triggering SSG rebuild.")
        sys.exit(22)
    else:
        # Check if individual city states flipped
        for slug, city_obj in alerts_payload["neighborhoods"].items():
            prev_city = prev_alerts.get("neighborhoods", {}).get(slug, {})
            if city_obj["has_alert"] != prev_city.get("has_alert", False):
                print(f"⚠️ State change in {city_obj['name']}. Triggering SSG rebuild.")
                sys.exit(22)

if __name__ == "__main__":
    compile_master_alerts()