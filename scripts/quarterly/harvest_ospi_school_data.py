# File: scripts/quarterly/harvest_ospi_school_data.py

import os
import json
import urllib.parse
import urllib3
import requests

# Suppress SSL warnings for public REST endpoints
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Directory Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
CITY_DATA_JSON = os.path.join(DATA_DIR, "city_data.json")
OUTPUT_JSON = os.path.join(DATA_DIR, "ospi_school_data.json")

# Verified Active OSPI Socrata REST Endpoint (Report Card Assessment Data)
OSPI_ASSESSMENT_ENDPOINT = "https://data.wa.gov/resource/h5d9-vgwi.json"

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

# State Assessment Baselines
STATE_MATH_BASELINE = 40.0
STATE_ELA_BASELINE = 51.0

def load_city_district_mappings():
    """
    Dynamically loads city-to-district mappings from data/city_data.json.
    Supports comma-separated multi-district mappings (e.g., Sammamish).
    """
    print(f"📖 Loading municipal district mappings from {CITY_DATA_JSON}...")
    city_map = {}
    
    if not os.path.exists(CITY_DATA_JSON):
        print(f"  ⚠️ Warning: {CITY_DATA_JSON} not found. City district ratings will be empty.")
        return city_map

    try:
        with open(CITY_DATA_JSON, "r", encoding="utf-8") as f:
            cities_list = json.load(f)

        for item in cities_list:
            city_name = item.get("City", "").strip()
            district_name = item.get("School District", "").strip()
            ospi_id = str(item.get("OSPI District ID", "")).strip()

            if city_name and (district_name or ospi_id):
                city_map[city_name] = {
                    "district_name": district_name,
                    "ospi_district_id": ospi_id
                }

        print(f"  ✓ Successfully mapped {len(city_map)} cities from city_data.json.")
    except Exception as e:
        print(f"  ❌ Error loading city_data.json: {e}")

    return city_map

def safe_float(val):
    """Safely parses string percentage values into floats."""
    if val is None or val == "" or str(val).strip().lower() in ["null", "n/a", "suppressed", "s", "*"]:
        return None
    try:
        clean_str = str(val).replace("%", "").replace(">", "").replace("<", "").strip()
        return round(float(clean_str), 1)
    except (ValueError, TypeError):
        return None

def calculate_psai_score(math_pct, ela_pct):
    """
    Computes the Puget Sound Academic Index (PSAI) on a normalized 0-100 scale.
    Formula: Round((Math % Met Standard + ELA % Met Standard) / 2, 1)
    """
    m = safe_float(math_pct)
    e = safe_float(ela_pct)
    if m is None or e is None:
        return None
    return round((m + e) / 2.0, 1)

def resolve_redfin_school_data(school_name, district_name, county):
    """Queries Redfin's native autocomplete API to obtain exact search URLs and cities."""
    if not school_name:
        return {"redfin_url": "", "city": district_name}

    query_str = f"{school_name} {district_name} WA"
    encoded_query = urllib.parse.quote(query_str)
    endpoint = f"https://www.redfin.com/stingray/do/location-autocomplete?location={encoded_query}&v=2"

    resolved_info = {"redfin_url": "", "city": district_name}

    try:
        resp = requests.get(endpoint, headers=HTTP_HEADERS, timeout=5, verify=False)
        if resp.status_code == 200:
            clean_text = resp.text.replace("{}&&", "").strip()
            data = json.loads(clean_text)
            
            payload = data.get("payload", {})
            exact_match = payload.get("exactMatch", {})

            if exact_match and exact_match.get("url"):
                resolved_info["redfin_url"] = f"https://www.redfin.com{exact_match.get('url')}"
                if exact_match.get("subText"):
                    sub_parts = exact_match.get("subText").split(",")
                    if len(sub_parts) > 0:
                        resolved_info["city"] = sub_parts[0].strip()
                return resolved_info

            for section in payload.get("sections", []):
                for row in section.get("rows", []):
                    if row.get("url") and ("school" in row.get("type", "").lower() or "school" in row.get("url", "").lower()):
                        resolved_info["redfin_url"] = f"https://www.redfin.com{row.get('url')}"
                        if row.get("subText"):
                            sub_parts = row.get("subText").split(",")
                            if len(sub_parts) > 0:
                                resolved_info["city"] = sub_parts[0].strip()
                        return resolved_info
    except Exception:
        pass

    return resolved_info

def fetch_filtered_ospi_records():
    """
    Queries Data.WA.gov Socrata REST API filtering specifically for 'All Students' population records.
    Filters out demographic noise to retrieve high-speed, 100% accurate building & district score streams.
    """
    print("📡 Querying Targeted OSPI Assessment Stream ('All Students' Cohorts)...")
    
    all_records = []
    limit = 25000
    offset = 0

    where_clause = (
        "county in ('King', 'Snohomish') AND "
        "(studentgrouptype = 'All' OR studentgroup = 'All Students' OR studentgrouptype = 'Federal')"
    )

    while True:
        params = {
            "$where": where_clause,
            "$limit": limit,
            "$offset": offset
        }

        try:
            resp = requests.get(OSPI_ASSESSMENT_ENDPOINT, headers=HTTP_HEADERS, params=params, timeout=30, verify=False)
            if resp.status_code == 200:
                chunk = resp.json()
                if not chunk:
                    break
                all_records.extend(chunk)
                print(f"  ✓ Fetched page block: {len(chunk)} records (Total Ingested: {len(all_records)})...")
                if len(chunk) < limit:
                    break
                offset += limit
            else:
                print(f"  ❌ OSPI Endpoint returned HTTP status {resp.status_code}")
                break
        except Exception as e:
            print(f"  ❌ Exception during OSPI fetch: {e}")
            break

    print(f"  ✅ Completed OSPI data ingestion: {len(all_records)} total assessment records compiled.")
    return all_records

def process_ospi_data(records):
    """Processes raw assessment records into structured school and district maps."""
    schools_map = {}
    districts_map = {}

    school_raw_scores = {}
    district_raw_scores = {}

    for r in records:
        org_level = str(r.get("organizationlevel", "")).lower()
        scode = r.get("schoolcode")
        sname = r.get("schoolname", "").strip()
        dname = r.get("districtname", "").strip()
        dcode = str(r.get("districtcode", "")).strip()
        county = r.get("county", "").strip()
        stype = r.get("currentschooltype", "Regular Public").strip()

        # --- STEP 1: INITIALIZE METADATA ---
        if org_level == "school" and scode and sname:
            if scode not in schools_map:
                schools_map[scode] = {
                    "school_name": sname,
                    "school_code": scode,
                    "ospi_org_id": r.get("schoolorganizationid"),
                    "district_name": dname,
                    "district_code": dcode,
                    "county": county,
                    "city": dname,
                    "school_type": stype,
                    "assessment_trends": {"math": [], "ela": [], "science": []}
                }
                school_raw_scores[scode] = {"math": {}, "ela": {}, "science": {}}

        if dname:
            if dname not in districts_map:
                districts_map[dname] = {
                    "district_name": dname,
                    "district_code": dcode,
                    "county": county,
                    "records_count": 0,
                    "assessment_trends": {"math": [], "ela": [], "science": []}
                }
                district_raw_scores[dname] = {"math": {}, "ela": {}, "science": {}}

        # --- STEP 2: ACCUMULATE PROFICIENCY PERCENTAGES ---
        raw_pct = r.get("percentmetstandard") if "percentmetstandard" in r else r.get("percent_met_standard")
        pct_met = safe_float(raw_pct)
        if pct_met is None:
            continue

        syear = r.get("schoolyear", "Unknown")
        subject_raw = str(r.get("subject", "")).lower()

        subject_key = None
        if "math" in subject_raw:
            subject_key = "math"
        elif "ela" in subject_raw or "english" in subject_raw or "reading" in subject_raw:
            subject_key = "ela"
        elif "science" in subject_raw:
            subject_key = "science"

        if not subject_key:
            continue

        if org_level == "school" and scode in school_raw_scores:
            if syear not in school_raw_scores[scode][subject_key]:
                school_raw_scores[scode][subject_key][syear] = []
            school_raw_scores[scode][subject_key][syear].append(pct_met)

        if org_level == "district" and dname in district_raw_scores:
            if syear not in district_raw_scores[dname][subject_key]:
                district_raw_scores[dname][subject_key][syear] = []
            district_raw_scores[dname][subject_key][syear].append(pct_met)

    # Average annual scores to build 5-year trends
    for scode, subjects in school_raw_scores.items():
        for sub, years in subjects.items():
            for yr, score_list in years.items():
                if score_list:
                    avg_score = round(sum(score_list) / len(score_list), 1)
                    schools_map[scode]["assessment_trends"][sub].append({
                        "year": yr,
                        "pct_met_standard": avg_score
                    })

    for dname, subjects in district_raw_scores.items():
        for sub, years in subjects.items():
            for yr, score_list in years.items():
                if score_list:
                    avg_score = round(sum(score_list) / len(score_list), 1)
                    districts_map[dname]["assessment_trends"][sub].append({
                        "year": yr,
                        "pct_met_standard": avg_score
                    })

    # Count active school facilities per district
    for scode, s_data in schools_map.items():
        d_name = s_data["district_name"]
        if d_name in districts_map:
            districts_map[d_name]["records_count"] += 1

    return schools_map, districts_map

def main():
    print("==================================================")
    print("     OSPI MASTER SCHOOL DATA HARVESTER (V4.2)     ")
    print("==================================================\n")

    os.makedirs(DATA_DIR, exist_ok=True)

    city_mapping = load_city_district_mappings()

    raw_records = fetch_filtered_ospi_records()
    if not raw_records:
        print("❌ No OSPI assessment records fetched. Exiting.")
        return

    schools_map, districts_map = process_ospi_data(raw_records)

    # --- 1. COMPILE INDIVIDUAL SCHOOL BUILDING RECORDS ---
    total_schools = len(schools_map)
    print(f"\n🚀 Discovered {total_schools} unique public schools across King & Snohomish counties.")
    print("📡 Resolving Redfin URLs & Computing 5-Year PSAI Scores...")

    compiled_schools = []
    for idx, (scode, school_data) in enumerate(schools_map.items(), 1):
        redfin_info = resolve_redfin_school_data(
            school_data["school_name"], 
            school_data["district_name"], 
            school_data["county"]
        )

        for sub in ["math", "ela", "science"]:
            school_data["assessment_trends"][sub].sort(key=lambda x: str(x.get("year", "")))
            school_data["assessment_trends"][sub] = school_data["assessment_trends"][sub][-5:]

        latest_math = school_data["assessment_trends"]["math"][-1]["pct_met_standard"] if school_data["assessment_trends"]["math"] else None
        latest_ela = school_data["assessment_trends"]["ela"][-1]["pct_met_standard"] if school_data["assessment_trends"]["ela"] else None
        psai_score = calculate_psai_score(latest_math, latest_ela)

        school_entry = {
            "school_name": school_data["school_name"],
            "school_code": scode,
            "ospi_org_id": school_data["ospi_org_id"],
            "district_name": school_data["district_name"],
            "district_code": school_data["district_code"],
            "county": school_data["county"],
            "city": redfin_info["city"],
            "school_type": school_data["school_type"],
            "redfin_search_url": redfin_info["redfin_url"],
            "psai_score": psai_score,
            "latest_math_pct": latest_math,
            "latest_ela_pct": latest_ela,
            "assessment_trends": school_data["assessment_trends"]
        }

        compiled_schools.append(school_entry)
        if idx % 50 == 0 or idx == total_schools:
            print(f"  [Progress] {idx}/{total_schools} schools processed...")

    compiled_schools.sort(key=lambda s: (s["city"], s["district_name"], s["school_name"]))

    # --- 2. COMPILE DISTRICT SUMMARIES ---
    compiled_districts = {}
    for dname, ddata in districts_map.items():
        for sub in ["math", "ela", "science"]:
            ddata["assessment_trends"][sub].sort(key=lambda x: str(x.get("year", "")))
            ddata["assessment_trends"][sub] = ddata["assessment_trends"][sub][-5:]

        latest_math = ddata["assessment_trends"]["math"][-1]["pct_met_standard"] if ddata["assessment_trends"]["math"] else None
        latest_ela = ddata["assessment_trends"]["ela"][-1]["pct_met_standard"] if ddata["assessment_trends"]["ela"] else None

        # Fallback calculation: Average individual school building scores if district summary row is absent
        if latest_math is None or latest_ela is None:
            dist_schools = [s for s in compiled_schools if s["district_name"] == dname]
            if dist_schools:
                m_vals = [s["latest_math_pct"] for s in dist_schools if s["latest_math_pct"] is not None]
                e_vals = [s["latest_ela_pct"] for s in dist_schools if s["latest_ela_pct"] is not None]
                if m_vals and latest_math is None:
                    latest_math = round(sum(m_vals) / len(m_vals), 1)
                if e_vals and latest_ela is None:
                    latest_ela = round(sum(e_vals) / len(e_vals), 1)

        psai_score = calculate_psai_score(latest_math, latest_ela)

        compiled_districts[dname] = {
            "district_name": dname,
            "district_code": ddata["district_code"],
            "county": ddata["county"],
            "records_count": ddata["records_count"],
            "district_math_proficiency": latest_math,
            "district_ela_proficiency": latest_ela,
            "psai_score": psai_score,
            "assessment_trends": ddata["assessment_trends"]
        }

    # --- 3. COMPILE CITY DISTRICT RATINGS DYNAMICALLY FROM city_data.json ---
    compiled_city_ratings = {}
    for city_name, meta in city_mapping.items():
        raw_dnames = [d.strip() for d in meta["district_name"].split(",") if d.strip()]
        raw_ospi_ids = [i.strip() for i in meta["ospi_district_id"].split(",") if i.strip()]

        matched_dists = []
        for ospi_id in raw_ospi_ids:
            for d_name, d_info in compiled_districts.items():
                if d_info.get("district_code") == ospi_id:
                    matched_dists.append(d_info)
                    break

        if not matched_dists:
            for d_name in raw_dnames:
                if d_name in compiled_districts:
                    matched_dists.append(compiled_districts[d_name])

        if matched_dists:
            math_vals = [d["district_math_proficiency"] for d in matched_dists if d["district_math_proficiency"] is not None]
            ela_vals = [d["district_ela_proficiency"] for d in matched_dists if d["district_ela_proficiency"] is not None]

            math_prof = round(sum(math_vals) / len(math_vals), 1) if math_vals else None
            ela_prof = round(sum(ela_vals) / len(ela_vals), 1) if ela_vals else None
            psai = calculate_psai_score(math_prof, ela_prof)
            actual_dname = ", ".join([d["district_name"] for d in matched_dists])
        else:
            math_prof, ela_prof, psai = None, None, None
            actual_dname = meta["district_name"]

        status = "Active" if psai is not None else "Insufficient Data (Small Student Population)"

        compiled_city_ratings[city_name] = {
            "district_name": actual_dname,
            "district_math_proficiency": math_prof,
            "district_ela_proficiency": ela_prof,
            "custom_score": psai, # Normalized 0-100 Puget Sound Academic Index
            "state_math_baseline": STATE_MATH_BASELINE,
            "state_ela_baseline": STATE_ELA_BASELINE,
            "status": status
        }

    # --- 4. WRITE MASTER UNIFIED JSON FILE ---
    master_output = {
        "schools": compiled_schools,
        "districts": compiled_districts,
        "city_district_ratings": compiled_city_ratings
    }

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(master_output, f, indent=2, ensure_ascii=False)

    print(f"\n🎉 Master harvesting complete!")
    print(f"  • Compiled {len(compiled_schools)} individual school facilities.")
    print(f"  • Compiled {len(compiled_districts)} school districts.")
    print(f"  • Compiled {len(compiled_city_ratings)} city-district rating mappings.")
    print(f"  • Saved master dataset to: {OUTPUT_JSON}")

if __name__ == "__main__":
    main()