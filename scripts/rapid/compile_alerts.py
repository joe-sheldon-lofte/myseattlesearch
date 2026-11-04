import os
import sys
import re
import json
import math
import boto3
import requests
import datetime
from zoneinfo import ZoneInfo
from botocore.client import Config

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None

# ------------------------------------------------------------------------------
# 1. INITIALIZATION & CREDENTIALS
# ------------------------------------------------------------------------------
SENTRY_DSN = os.getenv("SENTRY_DSN")
if SENTRY_DSN and sentry_sdk:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        traces_sample_rate=0.0,
        environment="production"
    )

R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_ENDPOINT = os.getenv("R2_ENDPOINT_URL")
BUCKET = os.getenv("R2_BUCKET_NAME")

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
    """Normalizes district and org strings for deterministic substring bridging."""
    cleaned = text.lower()
    cleaned = re.sub(r"\b(school district|schools|school|public schools|sd|#\d+)\b", " ", cleaned)
    cleaned = re.sub(r"[^\w\s]", "", cleaned)
    return " ".join(cleaned.split())

def load_canonical_cities():
    """Loads all 59 dynamic municipalities and districts from city_data.json."""
    candidates = [
        os.path.join(BASE_DIR, "_data", "city_data.json"),
        os.path.join(BASE_DIR, "data", "city_data.json")
    ]
    file_path = next((p for p in candidates if os.path.exists(p)), None)
    if not file_path:
        raise FileNotFoundError("Could not locate city_data.json in _data/ or data/.")

    with open(file_path, "r", encoding="utf-8") as f:
        records = json.load(f)

    cities = []
    for entry in records:
        city_name = entry.get("City")
        lat = entry.get("Latitude")
        lon = entry.get("Longitude")
        if not city_name or lat is None or lon is None:
            continue

        raw_districts = entry.get("School District", "")
        district_list = [d.strip() for d in raw_districts.split(",") if d.strip()]

        cities.append({
            "name": city_name,
            "slug": slugify(city_name),
            "lat": float(lat),
            "lon": float(lon),
            "county": entry.get("County", "King"),
            "districts": district_list,
            "normalized_districts": [normalize_name(d) for d in district_list]
        })

    print(f"📍 Loaded {len(cities)} canonical municipalities from {os.path.basename(file_path)}")
    return cities

def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY,
        aws_secret_access_key=R2_SECRET_KEY,
        config=Config(signature_version="s3v4")
    )

def haversine_miles(lat1, lon1, lat2, lon2):
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0)**2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0)**2
    return r * (2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a)))

# ------------------------------------------------------------------------------
# 2. TELEMETRY EXTRACTION
# ------------------------------------------------------------------------------
def fetch_r2_json(s3, key):
    try:
        res = s3.get_object(Bucket=BUCKET, Key=key)
        return json.loads(res["Body"].read().decode("utf-8"))
    except Exception as e:
        print(f"⚠️ Telemetry feed {key} unavailable in R2: {e}")
        return None

def fetch_recent_earthquakes():
    if not (D1_API_TOKEN and ACCOUNT_ID and DATABASE_ID):
        print("⚠️ D1 credentials missing. Skipping seismic check.")
        return []

    url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/d1/database/{DATABASE_ID}/query"
    headers = {
        "Authorization": f"Bearer {D1_API_TOKEN}",
        "Content-Type": "application/json"
    }

    cutoff_time = int((datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=6)).timestamp() * 1000)
    sql = "SELECT id, magnitude, place, latitude, longitude, time_ms FROM earthquakes WHERE time_ms >= ? AND magnitude >= 2.0"
    payload = [{"sql": sql, "params": [cutoff_time]}]

    try:
        res = requests.post(url, headers=headers, json=payload, timeout=10).json()
        if res.get("success") and res.get("result"):
            return res["result"][0].get("results", [])
    except Exception as e:
        print(f"⚠️ D1 seismic query failed: {e}")
        if SENTRY_DSN and sentry_sdk:
            sentry_sdk.capture_exception(e)
    return []

def evaluate_school_decay(report, now_pac):
    """Enforces 12:00 PM cutoff for delays/routes and 4:30 PM for closures."""
    if report.get("is_tomorrow"):
        return True

    eff_str = report.get("effective_date", "")
    try:
        eff_dt = datetime.datetime.fromisoformat(eff_str).astimezone(PACIFIC_TZ)
        if eff_dt.date() > now_pac.date():
            return True
        if eff_dt.date() < now_pac.date():
            return False
    except Exception:
        pass

    op_code = str(report.get("operating_code", ""))
    if op_code in ["2", "3", "4", "5", "6"]:
        if now_pac.hour >= 12:
            return False
    elif op_code == "1":
        if now_pac.hour > 16 or (now_pac.hour == 16 and now_pac.minute >= 30):
            return False

    return True

# ------------------------------------------------------------------------------
# 3. SPATIAL & MUNICIPAL AGGREGATION ENGINE
# ------------------------------------------------------------------------------
def compile_master_alerts():
    cities = load_canonical_cities()
    s3 = get_s3_client()
    now_pac = datetime.datetime.now(PACIFIC_TZ)

    power_data = fetch_r2_json(s3, "telemetry/power_outages.json") or {}
    wildfire_data = fetch_r2_json(s3, "telemetry/wildfires.json") or {}
    schools_data = fetch_r2_json(s3, "telemetry/schools.json") or {}
    earthquakes = fetch_recent_earthquakes()

    total_regional_customers_out = 0
    outages_by_city = {}
    if "cities" in power_data:
        for c_slug, metrics in power_data["cities"].items():
            cust_out = int(metrics.get("customers_affected", 0))
            incidents = int(metrics.get("active_incidents", 0))
            total_regional_customers_out += cust_out
            outages_by_city[c_slug] = cust_out >= 50 or incidents >= 2

    # Global Hazard Flags
    major_blackout = total_regional_customers_out >= 25000
    major_quake = any(
        q.get("magnitude", 0) >= 5.0 and
        46.5 <= q.get("latitude", 0) <= 49.0 and
        -123.5 <= q.get("longitude", 0) <= -121.5
        for q in earthquakes
    )

    wildfires = wildfire_data.get("features", [])
    raw_reports = schools_data.get("reports", [])
    active_school_reports = [r for r in raw_reports if evaluate_school_decay(r, now_pac)]

    alerts_payload = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "global": {
            "critical_grid_failure": major_blackout,
            "seismic_emergency": major_quake,
            "school_emergency": any(r["severity"] == "red" for r in active_school_reports),
            "school_advisory": any(r["severity"] == "amber" for r in active_school_reports),
            "active_alert_count": 0,
            "regional_target_url": "/neighborhood/region/emergency-safety/"
        },
        "neighborhoods": {}
    }

    total_active_alerts = 1 if major_blackout else 0
    if major_quake:
        total_active_alerts += 1

    for city in cities:
        slug = city["slug"]
        lat = city["lat"]
        lon = city["lon"]

        # 1. Power Outages
        p_alert = outages_by_city.get(slug, False)

        # 2. Wildfire Proximity Assessment (< 30 miles OR > 500 acres & < 60 miles)
        w_alert = False
        w_meta = None
        for fire in wildfires:
            coords = fire.get("geometry", {}).get("coordinates", [])
            if len(coords) >= 2:
                f_lon, f_lat = coords[0], coords[1]
                props = fire.get("properties", {})
                acres = float(props.get("DailyAcres", 0) or 0)
                dist = haversine_miles(lat, lon, f_lat, f_lon)
                if dist <= 30.0 or (acres >= 500 and dist <= 60.0):
                    w_alert = True
                    w_meta = {
                        "incident_name": props.get("IncidentName", "Active Wildfire"),
                        "acres": acres,
                        "distance_miles": round(dist, 1)
                    }
                    break

        # 3. Earthquake Proximity Assessment
        eq_alert = False
        eq_meta = None
        for q in earthquakes:
            mag = float(q.get("magnitude", 0))
            dist = haversine_miles(lat, lon, q.get("latitude"), q.get("longitude"))
            if (mag >= 2.5 and dist <= 20.0) or (mag >= 4.0 and dist <= 50.0) or (mag >= 5.5 and dist <= 120.0):
                eq_alert = True
                eq_meta = {
                    "magnitude": mag,
                    "place": q.get("place", "Local Fault"),
                    "distance_miles": round(dist, 1)
                }
                break

        # 4. Schools Municipal-to-District Bridging
        matched_school_reports = []
        for rep in active_school_reports:
            org_norm = normalize_name(rep.get("org_name", ""))
            for d_norm in city["normalized_districts"]:
                if d_norm and (d_norm in org_norm or org_norm in d_norm):
                    matched_school_reports.append(rep)
                    break

        s_level = "optimal"
        if any(r["severity"] == "red" for r in matched_school_reports):
            s_level = "red"
        elif any(r["severity"] == "amber" for r in matched_school_reports):
            s_level = "amber"

        s_alert = s_level != "optimal"

        city_has_alert = p_alert or w_alert or eq_alert or s_alert
        alert_count = sum([p_alert, w_alert, eq_alert, s_alert])
        if city_has_alert:
            total_active_alerts += 1

        alerts_payload["neighborhoods"][slug] = {
            "name": city["name"],
            "has_alert": city_has_alert,
            "alert_count": alert_count,
            "target_url": f"/neighborhood/{slug}/emergency-safety/",
            "power_outage": p_alert,
            "power_outage_label": "Active Power Outage Alert" if p_alert else "No Active Power Outage Alerts",
            "wildfire": w_alert,
            "wildfire_label": "Active Wildfire Alert" if w_alert else "No Active Wildfire Alerts",
            "wildfire_meta": w_meta,
            "earthquake": eq_alert,
            "earthquake_label": "Active Earthquake Alert" if eq_alert else "No Active Earthquake Alerts",
            "earthquake_meta": eq_meta,
            "school": s_alert,
            "school_level": s_level,
            "school_label": "Active School Alert" if s_alert else "No Active School Alerts",
            "school_reports": matched_school_reports
        }

    alerts_payload["global"]["active_alert_count"] = total_active_alerts

    s3.put_object(
        Bucket=BUCKET,
        Key="telemetry/active_alerts.json",
        Body=json.dumps(alerts_payload, separators=(',', ':')),
        ContentType="application/json",
        CacheControl="public, max-age=60, s-maxage=60"
    )
    print(f"✅ Master alert matrix published to R2. Total active alerts: {total_active_alerts}")

def main():
    try:
        compile_master_alerts()
    except Exception as e:
        print(f"❌ Master Alert Matrix Compiler failed: {e}")
        if SENTRY_DSN and sentry_sdk:
            sentry_sdk.capture_exception(e)
        sys.exit(1)

if __name__ == "__main__":
    main()