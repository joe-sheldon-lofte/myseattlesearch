import os
import json
import math
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")
CITY_BOUNDARIES_PATH = os.path.join(DATA_DIR, "city_boundaries.json")
TRANSIT_DATA_PATH = os.path.join(DATA_DIR, "transit_data.json")
TRANSIT_HISTORY_PATH = os.path.join(DATA_DIR, "transit_radar_history.json")
INTERCITY_SUMMARY_PATH = os.path.join(DATA_DIR, "intercity_summary.json")

def slugify(text):
    if not text: return ""
    text = str(text).lower().strip()
    out = [ch if ch.isalnum() else '-' for ch in text]
    res = "".join(out)
    while '--' in res: res = res.replace('--', '-')
    return res.strip('-')

def http_get_json_simple(url, timeout=20):
    headers = {"User-Agent": "Mozilla/5.0"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception:
        pass
    return None

def load_city_boundaries():
    if not os.path.exists(CITY_BOUNDARIES_PATH): return []
    with open(CITY_BOUNDARIES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    indexed = []
    for feat in data.get("features", []):
        props = feat.get("properties", {})
        slug = props.get("slug") or slugify(props.get("name") or "")
        if slug: indexed.append({"slug": slug, "name": props.get("name", ""), "geometry": feat.get("geometry", {})})
    return indexed

def load_city_data():
    if not os.path.exists(CITY_DATA_PATH): return []
    with open(CITY_DATA_PATH, "r", encoding="utf-8") as f:
        raw_data = json.load(f)
    items = raw_data if isinstance(raw_data, list) else list(raw_data.values())
    out = []
    for item in items:
        name = item.get("City") or item.get("name") or ""
        if name:
            out.append({"slug": slugify(name), "name": str(name).strip(), "population": int(item.get("population") or 1000)})
    return out

def main():
    print("🚆 Starting Transit Radar & Intercity Delays Harvester...")
    cities = load_city_data()
    city_boundaries = load_city_boundaries()

    # Harvest OneBusAway Transit Radar
    oba_key = os.environ.get("ONEBUSAWAY_API_KEY", "TEST").strip()
    all_agencies = {"1": "King County Metro", "29": "Sound Transit", "23": "Community Transit"}
    city_map = {c["slug"]: {"name": c["name"], "population": c["population"], "active_vehicles": 0} for c in cities}

    for agency_id in all_agencies:
        oba_url = f"https://api.pugetsound.onebusaway.org/api/where/vehicles-for-agency/{agency_id}.json?key={oba_key}"
        res = http_get_json_simple(oba_url)
        if res and isinstance(res, dict) and res.get("code") == 200:
            v_list = res.get("data", {}).get("list", [])
            for v in v_list:
                loc = v.get("location") or {}
                if loc.get("lat") and loc.get("lon"):
                    # Basic assignment to Seattle region
                    if "seattle" in city_map:
                        city_map["seattle"]["active_vehicles"] += 1

    now_utc = datetime.now(timezone.utc)
    live_output = {}
    for slug, details in city_map.items():
        live_output[slug] = {
            "name": details["name"],
            "active_vehicles": details["active_vehicles"],
            "last_updated": now_utc.isoformat()
        }

    with open(os.path.join(DATA_DIR, "transit_radar_live.json"), "w", encoding="utf-8") as f:
        json.dump(live_output, f, indent=2, ensure_ascii=False)

    # Harvest Intercity Sea-Tac Delays
    intercity = {
        "airports": {
            "seatac_sea": {"name": "Sea-Tac (SEA)", "status": "Normal Operations"},
            "paine_field_pae": {"name": "Paine Field (PAE)", "status": "Normal Operations"}
        },
        "last_updated": now_utc.isoformat()
    }
    faa_data = http_get_json_simple("https://nasstatus.faa.gov/api/airport-status")
    if faa_data and isinstance(faa_data, list):
        for apt in faa_data:
            code = str(apt.get("arpt", "")).upper()
            if code in ["SEA", "PAE"]:
                key = "seatac_sea" if code == "SEA" else "paine_field_pae"
                if apt.get("delay") == "true" or apt.get("delay") is True:
                    intercity["airports"][key]["status"] = "Ground Delay Program"

    with open(INTERCITY_SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump(intercity, f, indent=2, ensure_ascii=False)

    print("✅ Transit Radar & Intercity Delays complete.")

if __name__ == "__main__":
    main()