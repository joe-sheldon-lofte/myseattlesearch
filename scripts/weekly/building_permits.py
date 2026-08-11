import os
import json
import urllib.request
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")
PERMITS_PATH = os.path.join(DATA_DIR, "city_permits.json")

def slugify(text):
    if not text: return ""
    text = str(text).lower().strip()
    out = [ch if ch.isalnum() else '-' for ch in text]
    res = "".join(out)
    while '--' in res: res = res.replace('--', '-')
    return res.strip('-')

def http_get_json_simple(url, timeout=20):
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"   ⚠️ Permits GET notice: {e}")
    return None

def main():
    print("🏗️ Harvesting Active Municipal Building Permits...")
    os.makedirs(DATA_DIR, exist_ok=True)
    
    cities = []
    if os.path.exists(CITY_DATA_PATH):
        try:
            with open(CITY_DATA_PATH, "r", encoding="utf-8") as f:
                raw_cities = json.load(f)
            items = raw_cities if isinstance(raw_cities, list) else list(raw_cities.values())
            for item in items:
                name = item.get("City") or item.get("name") or ""
                if name: cities.append({"slug": slugify(name), "name": str(name).strip()})
        except Exception: pass

    permits_by_city = {c["slug"]: {"name": c["name"], "permits": []} for c in cities}
    seattle_url = "https://data.seattle.gov/resource/76t5-zqzr.json?$limit=100&$order=issueddate%20DESC"
    s_permits = http_get_json_simple(seattle_url)

    if s_permits and isinstance(s_permits, list) and "seattle" in permits_by_city:
        for p in s_permits:
            addr = p.get("originaladdress") or p.get("address") or "Seattle, WA"
            lat = float(p["latitude"]) if p.get("latitude") else None
            lon = float(p["longitude"]) if p.get("longitude") else None

            permits_by_city["seattle"]["permits"].append({
                "permit_number": p.get("permitnum"),
                "type": p.get("permittypedesc") or "Construction",
                "description": p.get("description", "Neighborhood Development"),
                "address": addr,
                "latitude": lat,
                "longitude": lon,
                "category": p.get("permitclassmapped", "Single Family / Commercial"),
                "value_usd": p.get("estprojectcost"),
                "issued_date": p.get("issueddate") or datetime.utcnow().strftime("%Y-%m-%d")
            })

    output = {
        "city_permits": permits_by_city,
        "last_updated": datetime.utcnow().isoformat() + "Z"
    }
    with open(PERMITS_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"💾 Saved building permits to {PERMITS_PATH}")

if __name__ == "__main__":
    main()