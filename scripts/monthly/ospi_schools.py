import os
import json
import urllib.request
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")

KING_SNO_DISTRICTS = [
    "seattle", "edmonds", "everett", "shoreline", "mukilteo", "northshore",
    "bellevue", "renton", "highline", "kent", "issaquah", "lake washington",
    "snohomish", "lake stevens", "marysville", "monroe"
]

def main():
    print("🏫 Ingesting OSPI School District Data via WA Open Data...")
    url = "https://data.wa.gov/resource/wvqy-yp3m.json?$limit=10000"
    records = None

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as resp:
            if resp.status == 200:
                records = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"⚠️ OSPI fetch notice: {e}")

    school_summary = {}
    if records and isinstance(records, list):
        for rec in records:
            district_name = rec.get("district_name") or rec.get("districtname") or ""
            district_code = str(rec.get("district_code") or "").strip()
            d_lower = district_name.lower()

            if district_name and any(target in d_lower for target in KING_SNO_DISTRICTS):
                if district_name not in school_summary:
                    school_summary[district_name] = {
                        "district_name": district_name,
                        "district_code": district_code,
                        "records_count": 0
                    }
                school_summary[district_name]["records_count"] += 1

    output = {
        "districts": school_summary,
        "last_updated": datetime.utcnow().isoformat() + "Z"
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "city_schools.json"), "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print("💾 Saved OSPI school district data.")

if __name__ == "__main__":
    main()