import os
import json
import urllib.request
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")

def slugify(text):
    if not text: return ""
    text = str(text).lower().strip()
    out = [ch if ch.isalnum() else '-' for ch in text]
    res = "".join(out)
    while '--' in res: res = res.replace('--', '-')
    return res.strip('-')

def main():
    print("📈 Ingesting US Census ACS 5-Year Municipal Demographics & Population...")
    raw_key = os.environ.get("CENSUS_API_KEY", "").strip().strip("'").strip('"')

    if not raw_key:
        print("⚠️ CENSUS_API_KEY is missing from environment secrets. Skipping Census fetch.")
        return

    if not os.path.exists(CITY_DATA_PATH):
        print("ℹ️ city_data.json missing. Skipping demographics harvest.")
        return

    with open(CITY_DATA_PATH, "r", encoding="utf-8") as f:
        raw_cities = json.load(f)

    items = raw_cities if isinstance(raw_cities, list) else list(raw_cities.values())
    census_by_place = {}

    for vintage in ["2024", "2023", "2022"]:
        url = f"https://api.census.gov/data/{vintage}/acs/acs5?get=NAME,B19013_001E,B01002_001E,B25003_002E,B25003_003E,B01003_001E&for=place:*&in=state:53&key={raw_key}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                if resp.status == 200:
                    rows = json.loads(resp.read().decode("utf-8"))
                    if len(rows) >= 2:
                        headers = rows[0]
                        for row in rows[1:]:
                            r_dict = dict(zip(headers, row))
                            place_fips = str(r_dict.get("place", "")).zfill(5)
                            census_by_place[place_fips] = r_dict
                        print(f"   ✅ Fetched ACS {vintage} demographics & population for {len(census_by_place)} WA places.")
                        break
        except Exception as e:
            print(f"   ⚠️ Census vintage {vintage} fetch notice: {e}")

    output = {}
    for item in items:
        raw_name = item.get("City") or item.get("name") or ""
        if not raw_name: continue
        slug = slugify(raw_name)
        fips = str(item.get("Federal ID") or item.get("fips") or "").strip().zfill(5)

        c_data = census_by_place.get(fips)
        if c_data:
            try:
                income = int(float(c_data.get("B19013_001E") or 0))
                age = float(c_data.get("B01002_001E") or 0.0)
                owners = float(c_data.get("B25003_002E") or 0)
                renters = float(c_data.get("B25003_003E") or 0)
                pop = int(float(c_data.get("B01003_001E") or 0))
                tot = owners + renters
                owner_pct = round((owners / tot * 100), 1) if tot > 0 else 0.0
                renter_pct = round((renters / tot * 100), 1) if tot > 0 else 0.0
            except Exception as parse_err:
                print(f"   ⚠️ Error parsing Census data for {raw_name} (FIPS {fips}): {parse_err}")
                income, age, owner_pct, renter_pct, pop = 0, 0.0, 0.0, 0.0, 0
        else:
            print(f"   ⚠️ No Census data found for FIPS place {fips} ({raw_name})")
            income, age, owner_pct, renter_pct, pop = 0, 0.0, 0.0, 0.0, 0

        output[slug] = {
            "name": raw_name,
            "fips_place": fips,
            "population": pop,
            "median_household_income": income,
            "median_age": age,
            "owner_occupied_pct": owner_pct,
            "renter_occupied_pct": renter_pct,
            "last_updated": datetime.utcnow().isoformat() + "Z"
        }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "city_demographics.json"), "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print("💾 Saved Census demographics & population data to data/city_demographics.json")

if __name__ == "__main__":
    main()