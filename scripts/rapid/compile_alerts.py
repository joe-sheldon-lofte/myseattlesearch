import os
import sys
import re
import json
import math
import requests
import datetime
from zoneinfo import ZoneInfo

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None

SENTRY_DSN = os.getenv("SENTRY_DSN")
if SENTRY_DSN and sentry_sdk:
    sentry_sdk.init(dsn=SENTRY_DSN, traces_sample_rate=0.0, environment="production")

D1_API_TOKEN = os.getenv("CF_MASTER_API_TOKEN") or os.getenv("CF_D1_API_TOKEN")
ACCOUNT_ID = os.getenv("CF_MASTER_ACCOUNT_ID") or os.getenv("CF_ACCOUNT_ID")
DATABASE_ID = os.getenv("CF_DATABASE_TELEMETRY_ID")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
PACIFIC_TZ = ZoneInfo("America/Los_Angeles")

# NWS Seattle (SEW) County + Public Forecast Zone UGC mappings
COUNTY_UGC_MAP = {
    "King": {
        "WAC033",
        "WAZ303", "WAZ304", "WAZ305", "WAZ306",
        "WAZ313", "WAZ314", "WAZ315", "WAZ316",
        "WAZ555", "WAZ556", "WAZ558", "WAZ559", "WAZ567", "WAZ568"
    },
    "Snohomish": {
        "WAC061",
        "WAZ302", "WAZ305",
        "WAZ311", "WAZ312", "WAZ313",
        "WAZ507", "WAZ555", "WAZ567"
    },
    "Pierce": {
        "WAC053",
        "WAZ304", "WAZ316",
        "WAZ509", "WAZ559", "WAZ568"
    }
}


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[-\s]+", "-", text)


def normalize_name(text: str) -> str:
    cleaned = text.lower()
    cleaned = re.sub(r"\b(school district|schools|school|public schools|sd|no\.\s*\d+|#\d+)\b", " ", cleaned)
    cleaned = re.sub(r"[^\w\s]", "", cleaned)
    return " ".join(cleaned.split())


def resolve_data_file(filename: str):
    for folder in ("data", "_data"):
        candidate = os.path.join(BASE_DIR, folder, filename)
        if os.path.exists(candidate):
            return candidate
    return None


def load_local_json(filename: str):
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_canonical_cities():
    file_path = resolve_data_file("city_data.json")
    if not file_path:
        raise FileNotFoundError("Could not locate city_data.json in data/ or _data/.")

    with open(file_path, "r", encoding="utf-8") as f:
        records = json.load(f)

    cities = []
    for entry in records:
        city_name = entry.get("City")
        lat = entry.get("Latitude")
        lon = entry.get("Longitude")
        if not city_name or lat is None or lon is None:
            continue

        county = (entry.get("County") or "King").strip().title()
        county_code = "WAC033" if county == "King" else ("WAC061" if county == "Snohomish" else "WAC053")
        ugc_codes = COUNTY_UGC_MAP.get(county, {county_code})

        raw_districts = entry.get("School District", "")
        district_list = [d.strip() for d in raw_districts.split(",") if d.strip()]

        cities.append({
            "name": city_name,
            "slug": slugify(city_name),
            "lat": float(lat),
            "lon": float(lon),
            "county": county,
            "county_code": county_code,
            "ugc_codes": ugc_codes,
            "districts": district_list,
            "normalized_districts": [normalize_name(d) for d in district_list]
        })
    return cities


def load_school_spatial_indexes():
    district_polys_by_norm = {}
    sb_path = resolve_data_file("school_boundaries.json")
    if sb_path:
        with open(sb_path, "r", encoding="utf-8") as f:
            sb = json.load(f)
        for d_code, d_obj in sb.get("district_boundaries", {}).items():
            d_name = d_obj.get("district_name", "")
            norm = normalize_name(d_name)
            if norm:
                district_polys_by_norm[norm] = {
                    "district_code": d_code,
                    "district_name": d_name,
                    "geometry": d_obj.get("geometry")
                }

    schools_by_district_norm = {}
    osd_path = resolve_data_file("ospi_school_data.json")
    if osd_path:
        with open(osd_path, "r", encoding="utf-8") as f:
            osd = json.load(f)
        for s in osd.get("schools", []):
            d_norm = normalize_name(s.get("district_name", ""))
            if not d_norm:
                continue
            schools_by_district_norm.setdefault(d_norm, []).append({
                "school_name": s.get("school_name", ""),
                "district_name": s.get("district_name", ""),
                "district_code": s.get("district_code", ""),
                "latitude": s.get("latitude"),
                "longitude": s.get("longitude")
            })

    return district_polys_by_norm, schools_by_district_norm


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return r * (2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a)))


def fetch_recent_earthquakes():
    if not (D1_API_TOKEN and ACCOUNT_ID and DATABASE_ID):
        print("D1 credentials missing. Skipping seismic check.")
        return []
    url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/d1/database/{DATABASE_ID}/query"
    headers = {"Authorization": f"Bearer {D1_API_TOKEN}", "Content-Type": "application/json"}
    cutoff_time = int((datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=6)).timestamp() * 1000)
    sql = "SELECT id, magnitude, place, latitude, longitude, depth, time_ms FROM earthquakes WHERE time_ms >= ? AND magnitude >= 2.0"
    try:
        res = requests.post(url, headers=headers, json=[{"sql": sql, "params": [cutoff_time]}], timeout=15).json()
        if res.get("success") and res.get("result"):
            return res["result"][0].get("results", [])
    except Exception as exc:
        print(f"D1 seismic query failed: {exc}")
    return []


def evaluate_school_decay(report: dict, now_pac: datetime.datetime) -> bool:
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

    op = str(report.get("operating_code", ""))
    if op in ("2", "3", "4", "5", "6") and now_pac.hour >= 12:
        return False
    if op == "1" and (now_pac.hour > 16 or (now_pac.hour == 16 and now_pac.minute >= 30)):
        return False
    return True


def point_in_ring(lon: float, lat: float, ring: list) -> bool:
    n = len(ring)
    if n < 3:
        return False
    inside = False
    p1x, p1y = ring[0][0], ring[0][1]
    for i in range(1, n + 1):
        p2x, p2y = ring[i % n][0], ring[i % n][1]
        if lat > min(p1y, p2y):
            if lat <= max(p1y, p2y):
                if lon <= max(p1x, p2x):
                    if p1y != p2y:
                        xints = (lat - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or lon <= xints:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside


def point_in_geometry(lon: float, lat: float, geom: dict) -> bool:
    if not geom:
        return False
    gtype = geom.get("type")
    coords = geom.get("coordinates", [])
    if gtype == "Polygon":
        return bool(coords) and point_in_ring(lon, lat, coords[0])
    if gtype == "MultiPolygon":
        return any(poly and point_in_ring(lon, lat, poly[0]) for poly in coords)
    return False


def enrich_school_report(rep: dict, d_norm: str, district_polys: dict, schools_by_dist: dict) -> dict:
    enriched = dict(rep)
    detail_lower = (rep.get("detail") or "").lower()
    org_lower = (rep.get("org_name") or "").lower()
    dist_info = district_polys.get(d_norm, {})

    matched_school = None
    for sch in schools_by_dist.get(d_norm, []):
        sname = sch["school_name"].lower()
        if sname and (sname in org_lower or sname in detail_lower):
            matched_school = sch
            break

    if matched_school:
        enriched["scope"] = "school"
        enriched["school_name"] = matched_school["school_name"]
        enriched["latitude"] = matched_school.get("latitude")
        enriched["longitude"] = matched_school.get("longitude")
        enriched["district_code"] = matched_school.get("district_code") or dist_info.get("district_code")
        enriched["geometry"] = dist_info.get("geometry")
    else:
        enriched["scope"] = "district"
        enriched["district_code"] = dist_info.get("district_code")
        enriched["geometry"] = dist_info.get("geometry")

    return enriched


def compile_master_alerts():
    cities = load_canonical_cities()
    district_polys, schools_by_dist = load_school_spatial_indexes()
    now_pac = datetime.datetime.now(PACIFIC_TZ)

    prev_alerts = load_local_json("active_alerts.json") or {}
    power_data = load_local_json("power_outages.json") or {}
    wildfire_data = load_local_json("wildfires.json") or {}
    weather_data = load_local_json("weather_alerts.json") or {}
    schools_data = load_local_json("schools.json") or {}
    earthquakes = fetch_recent_earthquakes()

    total_regional_customers_out = sum(
        int(u.get("customers_affected", 0) or 0)
        for u in power_data.get("utilities", {}).values()
    )
    power_cities = power_data.get("cities", {})

    major_blackout = total_regional_customers_out >= 25000
    major_quake = any(
        float(q.get("magnitude", 0)) >= 5.0
        and 46.5 <= float(q.get("latitude", 0)) <= 49.0
        and -123.5 <= float(q.get("longitude", 0)) <= -121.5
        for q in earthquakes
    )

    wildfires = wildfire_data.get("incidents", [])
    wx_alerts = weather_data.get("alerts", [])
    active_schools = [r for r in schools_data.get("reports", []) if evaluate_school_decay(r, now_pac)]

    alerts_payload = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "global": {
            "critical_grid_failure": major_blackout,
            "seismic_emergency": major_quake,
            "school_emergency": False,
            "school_advisory": False,
            "weather_emergency": False,
            "regional_target_url": "/region/emergency-safety/"
        },
        "neighborhoods": {}
    }

    seen_global_alert_keys = set()
    if major_blackout:
        seen_global_alert_keys.add("global:major_blackout")
    if major_quake:
        seen_global_alert_keys.add("global:major_quake")

    any_weather_alert = False
    any_school_red = False
    any_school_amber = False

    for city in cities:
        slug, lat, lon = city["slug"], city["lat"], city["lon"]

        # 1. School Closures & Delays
        matched_schools = []
        seen_rep_ids = set()
        for rep in active_schools:
            org_norm = normalize_name(rep.get("org_name", ""))
            for d_norm in city["normalized_districts"]:
                if d_norm and (d_norm in org_norm or org_norm in d_norm):
                    rep_key = rep.get("report_id") or f"{org_norm}_{rep.get('detail', '')[:30]}"
                    if rep_key not in seen_rep_ids:
                        seen_rep_ids.add(rep_key)
                        matched_schools.append(
                            enrich_school_report(rep, d_norm, district_polys, schools_by_dist)
                        )
                        seen_global_alert_keys.add(f"school:{rep_key}")
                    break

        s_level = "red" if any(r.get("severity") == "red" for r in matched_schools) else ("amber" if matched_schools else "optimal")
        s_alert = len(matched_schools) > 0
        if s_level == "red":
            any_school_red = True
        elif s_level == "amber":
            any_school_amber = True

        # 2. Severe Weather Alerts (Polygon-strict when geometry exists; county/zone UGC overlap when absent)
        matched_weather = []
        for wx in wx_alerts:
            alert_ugcs = set(wx.get("geocode_ugc") or [])
            geom = wx.get("geometry")
            if geom:
                is_hit = point_in_geometry(lon, lat, geom)
            else:
                is_hit = bool(city["ugc_codes"] & alert_ugcs)

            if is_hit:
                wx_id = wx.get("id") or f"{wx.get('event', '')}|{wx.get('headline', '')}"
                matched_weather.append({
                    "id": wx.get("id"),
                    "event": wx.get("event"),
                    "severity": wx.get("severity"),
                    "headline": wx.get("headline"),
                    "description": wx.get("description"),
                    "instruction": wx.get("instruction"),
                    "expires": wx.get("expires"),
                    "geometry": geom
                })
                seen_global_alert_keys.add(f"weather:{wx_id}")
        wx_alert = len(matched_weather) > 0
        if wx_alert:
            any_weather_alert = True

        # 3. Power Outages
        c_power = power_cities.get(slug, {})
        matched_power = c_power.get("incidents", [])
        for inc in matched_power:
            pkey = inc.get("id") or f"{inc.get('provider', '')}_{inc.get('latitude', '')}_{inc.get('longitude', '')}"
            seen_global_alert_keys.add(f"power:{pkey}")
        p_alert = len(matched_power) > 0

        # 4. Earthquakes
        matched_quakes = []
        for q in earthquakes:
            mag = float(q.get("magnitude", 0))
            qlat, qlon = float(q.get("latitude", 0)), float(q.get("longitude", 0))
            dist = haversine_miles(lat, lon, qlat, qlon)
            if (mag >= 2.5 and dist <= 20.0) or (mag >= 4.0 and dist <= 50.0) or (mag >= 5.5 and dist <= 120.0):
                qkey = q.get("id") or f"{q.get('place', '')}_{q.get('time_ms', '')}"
                matched_quakes.append({
                    "id": q.get("id"),
                    "magnitude": mag,
                    "place": q.get("place"),
                    "depth": q.get("depth"),
                    "time_ms": q.get("time_ms"),
                    "distance_miles": round(dist, 1),
                    "latitude": qlat,
                    "longitude": qlon
                })
                seen_global_alert_keys.add(f"quake:{qkey}")
        eq_alert = len(matched_quakes) > 0

        # 5. Wildfires
        matched_fires = []
        for fire in wildfires:
            coords = fire.get("coordinates", {})
            flat, flon = coords.get("latitude"), coords.get("longitude")
            if flat is not None and flon is not None:
                acres = float(fire.get("acres", 0) or 0)
                dist = haversine_miles(lat, lon, float(flat), float(flon))
                if dist <= 30.0 or (acres >= 500 and dist <= 60.0):
                    fkey = fire.get("id") or fire.get("name", "")
                    matched_fires.append({
                        "id": fire.get("id"),
                        "name": fire.get("name"),
                        "county": fire.get("county"),
                        "acres": acres,
                        "containment_percent": fire.get("containment_percent"),
                        "distance_miles": round(dist, 1),
                        "latitude": float(flat),
                        "longitude": float(flon)
                    })
                    seen_global_alert_keys.add(f"fire:{fkey}")
        w_alert = len(matched_fires) > 0

        city_has_alert = s_alert or wx_alert or p_alert or eq_alert or w_alert

        alerts_payload["neighborhoods"][slug] = {
            "name": city["name"],
            "has_alert": city_has_alert,
            "school": s_alert,
            "school_level": s_level,
            "school_count": len(matched_schools),
            "school_reports": matched_schools,
            "weather": wx_alert,
            "weather_count": len(matched_weather),
            "weather_alerts": matched_weather,
            "power_outage": p_alert,
            "power_count": len(matched_power),
            "power_customers": int(c_power.get("customers_affected", 0)),
            "power_incidents": matched_power,
            "earthquake": eq_alert,
            "earthquake_count": len(matched_quakes),
            "earthquakes": matched_quakes,
            "wildfire": w_alert,
            "wildfire_count": len(matched_fires),
            "wildfires": matched_fires
        }

    total_active_alerts = len(seen_global_alert_keys)

    alerts_payload["global"]["school_emergency"] = any_school_red
    alerts_payload["global"]["school_advisory"] = any_school_amber
    alerts_payload["global"]["weather_emergency"] = any_weather_alert
    alerts_payload["global"]["active_alert_count"] = total_active_alerts

    os.makedirs(DATA_DIR, exist_ok=True)
    output_path = os.path.join(DATA_DIR, "active_alerts.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(alerts_payload, f, separators=(",", ":"), ensure_ascii=False)
    print(f"Master alert matrix saved -> {output_path}. Total active alerts: {total_active_alerts}")

    # Compare against previous snapshot to trigger deploy-site.yml immediately on any state change
    prev_global = prev_alerts.get("global", {})
    if total_active_alerts != prev_global.get("active_alert_count", 0):
        print("Global alert count changed. Exiting 22 to trigger Eleventy rebuild.")
        sys.exit(22)

    prev_neigh = prev_alerts.get("neighborhoods", {})
    for slug, c_obj in alerts_payload["neighborhoods"].items():
        p_obj = prev_neigh.get(slug, {})
        if (
            c_obj["has_alert"] != p_obj.get("has_alert", False)
            or c_obj["school_count"] != p_obj.get("school_count", 0)
            or c_obj["weather_count"] != p_obj.get("weather_count", 0)
            or c_obj["power_count"] != p_obj.get("power_count", 0)
            or c_obj["earthquake_count"] != p_obj.get("earthquake_count", 0)
            or c_obj["wildfire_count"] != p_obj.get("wildfire_count", 0)
        ):
            print(f"Alert state changed in {c_obj['name']}. Exiting 22 to trigger Eleventy rebuild.")
            sys.exit(22)


def main():
    try:
        compile_master_alerts()
    except SystemExit as se:
        raise se
    except Exception as exc:
        print(f"Master Alert Matrix Compiler failed: {exc}")
        if SENTRY_DSN and sentry_sdk:
            sentry_sdk.capture_exception(exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
