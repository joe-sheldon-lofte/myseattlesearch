import os
import json
import urllib.request
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")
OUT_PATH = os.path.join(DATA_DIR, "city_demographics.json")

def slugify(text):
    if not text: return ""
    text = str(text).lower().strip()
    out = [ch if ch.isalnum() else '-' for ch in text]
    res = "".join(out)
    while '--' in res: res = res.replace('--', '-')
    return res.strip('-')

def http_get_json(url, timeout=25):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/json"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception:
        pass
    return None

def main():
    print("📈 Ingesting US Census ACS 5-Year Municipal Demographics & Population...")
    if not os.path.exists(CITY_DATA_PATH):
        print("ℹ️ city_data.json missing. Skipping Census demographics.")
        return

    with open(CITY_DATA_PATH, "r", encoding="utf-8") as f:
        raw_cities = json.load(f)

    items = raw_cities if isinstance(raw_cities, list) else list(raw_cities.values())
    cities = []
    for it in items:
        name = it.get("City") or it.get("name") or ""
        fips = str(it.get("Federal ID") or it.get("federal_id") or it.get("fips") or "").strip().strip("'").strip('"')
        if fips and fips.isdigit():
            fips = fips.zfill(5)
        else:
            fips = ""
        if name:
            cities.append({"slug": slugify(name), "name": str(name).strip(), "fips": fips})

    raw_key = os.environ.get("CENSUS_API_KEY", "").strip().strip("'").strip('"')
    census_by_place = {}

    # Query Census ACS 5-Year Data across recent vintages
    vintages = ["2024", "2023", "2022"]
    for vintage in vintages:
        key_param = f"&key={raw_key}" if raw_key else ""
        url = f"https://api.census.gov/data/{vintage}/acs/acs5?get=NAME,B01003_001E,B19013_001E,B01002_001E,B25003_002E,B25003_003E&for=place:*&in=state:53{key_param}"
        res = http_get_json(url)
        if res and isinstance(res, list) and len(res) >= 2:
            headers = res[0]
            for row in res[1:]:
                row_dict = dict(zip(headers, row))
                place_fips = str(row_dict.get("place", "")).strip().zfill(5)
                census_by_place[place_fips] = row_dict
            print(f"   ✅ Fetched ACS {vintage} demographics & population for {len(census_by_place)} WA places.")
            break

    output = {}
    found_count = 0

    for city in cities:
        slug = city["slug"]
        name = city["name"]
        fips = city["fips"]

        c_data = census_by_place.get(fips) if fips else None

        def safe_float(val, default=0.0):
            try:
                v = float(val)
                return v if v >= 0 else default
            except (ValueError, TypeError):
                return default

        if c_data:
            pop = int(safe_float(c_data.get("B01003_001E")))
            income = int(safe_float(c_data.get("B19013_001E")))
            age = safe_float(c_data.get("B01002_001E"))
            owners = safe_float(c_data.get("B25003_002E"))
            renters = safe_float(c_data.get("B25003_003E"))
            total_units = owners + renters
            owner_pct = round((owners / total_units * 100), 1) if total_units > 0 else 0.0
            renter_pct = round((renters / total_units * 100), 1) if total_units > 0 else 0.0
            found_count += 1
        else:
            print(f"   ⚠️ No Census data found for FIPS place {fips} ({name})")
            pop, income, age, owner_pct, renter_pct = None, None, None, None, None

        output[slug] = {
            "name": name,
            "fips_place": fips,
            "population": pop,
            "median_household_income": income,
            "median_age": age,
            "owner_occupied_pct": owner_pct,
            "renter_occupied_pct": renter_pct,
            "last_updated": datetime.now(timezone.utc).isoformat()
        }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"💾 Saved Census demographics & population data ({found_count}/{len(cities)} matched) to {OUT_PATH}")

if __name__ == "__main__":
    main()