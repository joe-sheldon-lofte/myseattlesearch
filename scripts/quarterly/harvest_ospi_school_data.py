# File: scripts/quarterly/harvest_ospi_school_data.py

import os
import re
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

# Primary and Fallback OSPI Socrata Endpoints (Data.WA.gov Report Card Assessment Series)
OSPI_ENDPOINTS = [
    "https://data.wa.gov/resource/h5d9-vgwi.json",  # OSPI Report Card Assessment (2024-25)
    "https://data.wa.gov/resource/x73g-mrqp.json"   # OSPI Report Card Assessment (2023-24)
]

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
    """Safely parses percentage strings into floats, handling '80%', '>80%', '<10%', and 'Suppressed'."""
    if val is None or val == "":
        return None
    s = str(val).strip().lower()
    if s in ["null", "n/a", "suppressed", "s", "*", "none", "-", "count unavailable"]:
        return None
    try:
        clean_str = s.replace("%", "").replace(">", "").replace("<", "").replace(",", "").strip()
        v = float(clean_str)
        return round(v, 1)
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
        resp = requests.get(endpoint, headers=HTTP_HEADERS, timeout=4, verify=False)
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

def sniff_schema_fields(sample_records):
    """
    Inspects sample records to dynamically identify exact Socrata field keys across schema variations.
    """
    if not sample_records:
        return {}

    all_keys = set()
    for r in sample_records[:200]:
        all_keys.update(r.keys())

    def match_key(patterns, exclude=None):
        for k in all_keys:
            kl = k.lower()
            if exclude and any(x in kl for x in exclude):
                continue
            if any(re.search(p, kl) for p in patterns):
                return k
        return None

    # Identify metadata fields
    org_level_key = match_key([r"^org.*level$", r"organizationlevel", r"org_level"]) or "organizationlevel"
    school_code_key = match_key([r"schoolcode", r"school_code", r"buildingcode", r"building_code"]) or "schoolcode"
    school_name_key = match_key([r"schoolname", r"school_name", r"buildingname", r"building_name"]) or "schoolname"
    district_name_key = match_key([r"districtname", r"district_name"]) or "districtname"
    district_code_key = match_key([r"county_district_number", r"countydistrictnumber", r"districtcode", r"district_code"]) or "county_district_number"
    county_key = match_key([r"^county$", r"^countyname$", r"^county_name$"]) or "county"
    year_key = match_key([r"schoolyear", r"school_year", r"^year$"]) or "schoolyear"
    subject_key = match_key([r"testsubject", r"^subject$", r"test_subject", r"subjectname", r"contentarea"]) or "testsubject"
    student_group_key = match_key([r"^studentgroup$", r"^student_group$", r"subgroup"]) or "studentgroup"
    student_group_type_key = match_key([r"^studentgrouptype$", r"^student_group_type$"]) or "studentgrouptype"

    # Identify score / percentage fields
    # Prioritizes explicit standard percentage fields, followed by grade level consistency metrics
    score_candidates = []
    for k in all_keys:
        kl = k.lower()
        if any(x in kl for x in ["suppress", "no_score", "not_tested", "alternative", "participation"]):
            continue
        if ("percent" in kl or "pct" in kl) and any(y in kl for y in ["standard", "consistent", "met", "proficiency", "tested"]):
            score_candidates.append(k)

    # Sort candidates so the most specific standard percentage fields come first
    score_candidates.sort(key=lambda x: (
        0 if "standard" in x.lower() else
        1 if "consistent" in x.lower() else
        2 if "met" in x.lower() else 3
    ))

    # Count-based fallbacks (count meeting standard / count expected to test)
    count_met_key = match_key([r"countconsistent", r"countmetstandard", r"count_met_standard", r"countproficient"])
    count_expected_key = match_key([r"countofstudentsexpected", r"countexpectedtotest", r"count_expected", r"totaltested"])

    return {
        "org_level": org_level_key,
        "school_code": school_code_key,
        "school_name": school_name_key,
        "district_name": district_name_key,
        "district_code": district_code_key,
        "county": county_key,
        "year": year_key,
        "subject": subject_key,
        "student_group": student_group_key,
        "student_group_type": student_group_type_key,
        "score_candidates": score_candidates,
        "count_met": count_met_key,
        "count_expected": count_expected_key
    }

def fetch_ospi_endpoint_records(endpoint):
    """
    Pages through a Socrata endpoint with resilient county field probing.
    """
    records = []
    limit = 25000
    offset = 0

    # Probe endpoint to detect exact county field naming
    county_field = "county"
    try:
        probe_resp = requests.get(f"{endpoint}?$limit=1", headers=HTTP_HEADERS, timeout=10, verify=False)
        if probe_resp.status_code == 200:
            sample = probe_resp.json()
            if sample and isinstance(sample, list) and len(sample) > 0:
                keys = sample[0].keys()
                if "county_name" in keys:
                    county_field = "county_name"
                elif "countyname" in keys:
                    county_field = "countyname"
    except Exception as e:
        print(f"  ⚠️ Schema probe warning on {endpoint}: {e}")

    where_clause = f"{county_field} in ('King', 'Snohomish')"

    while True:
        params = {
            "$where": where_clause,
            "$limit": limit,
            "$offset": offset,
            "$order": ":id ASC"
        }

        try:
            resp = requests.get(endpoint, headers=HTTP_HEADERS, params=params, timeout=30, verify=False)
            if resp.status_code == 200:
                chunk = resp.json()
                if not chunk:
                    break
                records.extend(chunk)
                if len(chunk) < limit:
                    break
                offset += limit
            elif resp.status_code == 400 and offset == 0:
                # Fallback: query without $where and filter in Python if Socrata rejects county clause
                print(f"  ⚠️ Socrata $where clause rejected. Switching to unconstrained stream filtering...")
                params.pop("$where", None)
                resp_fallback = requests.get(endpoint, headers=HTTP_HEADERS, params=params, timeout=30, verify=False)
                if resp_fallback.status_code == 200:
                    chunk = resp_fallback.json()
                    filtered_chunk = [
                        r for r in chunk 
                        if str(r.get("county", r.get("county_name", r.get("countyname", "")))).lower() in ["king", "snohomish"]
                    ]
                    records.extend(filtered_chunk)
                break
            else:
                print(f"  ❌ Endpoint returned HTTP {resp.status_code} on {endpoint}")
                break
        except Exception as e:
            print(f"  ❌ Endpoint exception on {endpoint}: {e}")
            break

    return records

def fetch_all_ospi_records():
    """Queries all configured OSPI Report Card Socrata REST endpoints."""
    print("📡 Querying OSPI Assessment Data from Data.WA.gov...")
    all_records = []

    for ep in OSPI_ENDPOINTS:
        print(f"  • Ingesting stream: {ep}...")
        ep_records = fetch_ospi_endpoint_records(ep)
        print(f"    ✓ Retrieved {len(ep_records)} records from stream.")
        all_records.extend(ep_records)

    print(f"  ✅ Completed OSPI data ingestion: {len(all_records)} total assessment records compiled.")
    return all_records

def process_ospi_data(records):
    """Processes raw assessment records into structured school and district maps using dynamic schema mapping."""
    schools_map = {}
    districts_map = {}

    school_raw_scores = {}
    district_raw_scores = {}

    if not records:
        return schools_map, districts_map

    # 1. Dynamic Schema Sniffing
    schema = sniff_schema_fields(records)
    print("\n🔍 Dynamic Field Schema Audit:")
    print(f"   • Org Level:       '{schema['org_level']}'")
    print(f"   • School Code:     '{schema['school_code']}' | Name: '{schema['school_name']}'")
    print(f"   • District Code:   '{schema['district_code']}' | Name: '{schema['district_name']}'")
    print(f"   • Subject Key:     '{schema['subject']}'")
    print(f"   • Student Group:   '{schema['student_group']}'")
    print(f"   • Score Fields:    {schema['score_candidates'][:4]}")

    k_org = schema["org_level"]
    k_scode = schema["school_code"]
    k_sname = schema["school_name"]
    k_dname = schema["district_name"]
    k_dcode = schema["district_code"]
    k_county = schema["county"]
    k_year = schema["year"]
    k_subj = schema["subject"]
    k_sgroup = schema["student_group"]
    k_sgrouptype = schema["student_group_type"]
    score_keys = schema["score_candidates"]
    k_c_met = schema["count_met"]
    k_c_tot = schema["count_expected"]

    matched_scores_count = 0

    for r in records:
        org_level = str(r.get(k_org, "")).strip().lower()
        scode = str(r.get(k_scode, "")).strip()
        sname = str(r.get(k_sname, "")).strip()
        dname = str(r.get(k_dname, "")).strip()
        dcode = str(r.get(k_dcode, "")).strip()
        county = str(r.get(k_county, "")).strip()
        stype = str(r.get("currentschooltype", r.get("schooltype", r.get("type", "P")))).strip() or "P"

        # --- STEP 1: INITIALIZE ENTITIES ---
        if org_level == "school" and scode and sname:
            if scode not in schools_map:
                schools_map[scode] = {
                    "school_name": sname,
                    "school_code": scode,
                    "ospi_org_id": str(r.get("schoolorganizationid", r.get("school_org_id", r.get("org_id", "")))).strip(),
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
            elif dcode and not districts_map[dname]["district_code"]:
                districts_map[dname]["district_code"] = dcode

        # --- STEP 2: COHORT FILTERING ---
        sgroup = str(r.get(k_sgroup, "")).strip().lower()
        sgrouptype = str(r.get(k_sgrouptype, "")).strip().lower()

        # Target overall cohort rows (All Students / Total)
        is_all_students = (
            sgroup in ["all students", "all", "total", ""] or 
            sgrouptype in ["all", "federal", ""] or 
            "all students" in sgroup or 
            sgrouptype == ""
        )
        if not is_all_students:
            continue

        # --- STEP 3: SCORE PARSING ---
        pct_met = None
        for sk in score_keys:
            val = r.get(sk)
            if val is not None and str(val).strip() != "":
                parsed = safe_float(val)
                if parsed is not None:
                    pct_met = parsed
                    break

        # Fallback to counts if percentage is missing
        if pct_met is None and k_c_met and k_c_tot:
            c_met = safe_float(r.get(k_c_met))
            c_tot = safe_float(r.get(k_c_tot))
            if c_met is not None and c_tot is not None and c_tot > 0:
                pct_met = round((c_met / c_tot) * 100.0, 1)

        if pct_met is None:
            continue

        matched_scores_count += 1

        # Subject categorization
        subject_raw = str(r.get(k_subj, "")).strip().lower()
        subject_key = None
        if "math" in subject_raw:
            subject_key = "math"
        elif "ela" in subject_raw or "english" in subject_raw or "reading" in subject_raw:
            subject_key = "ela"
        elif "science" in subject_raw:
            subject_key = "science"

        if not subject_key:
            continue

        syear = str(r.get(k_year, "Unknown")).strip()

        # Accumulate scores for averaging
        if org_level == "school" and scode in school_raw_scores:
            if syear not in school_raw_scores[scode][subject_key]:
                school_raw_scores[scode][subject_key][syear] = []
            school_raw_scores[scode][subject_key][syear].append(pct_met)

        if org_level == "district" and dname in district_raw_scores:
            if syear not in district_raw_scores[dname][subject_key]:
                district_raw_scores[dname][subject_key][syear] = []
            district_raw_scores[dname][subject_key][syear].append(pct_met)

    print(f"   ✓ Extracted and matched {matched_scores_count} valid student proficiency records.")

    # Calculate average annual test scores for school building trends
    for scode, subjects in school_raw_scores.items():
        for sub, years in subjects.items():
            for yr, score_list in years.items():
                if score_list:
                    avg_score = round(sum(score_list) / len(score_list), 1)
                    schools_map[scode]["assessment_trends"][sub].append({
                        "year": yr,
                        "pct_met_standard": avg_score
                    })

    # Calculate average annual test scores for district trends
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
    print("     OSPI MASTER SCHOOL DATA HARVESTER (V4.5)     ")
    print("==================================================")

    os.makedirs(DATA_DIR, exist_ok=True)
    city_mapping = load_city_district_mappings()

    raw_records = fetch_all_ospi_records()
    if not raw_records:
        print("❌ No OSPI assessment records fetched. Exiting.")
        return

    schools_map, districts_map = process_ospi_data(raw_records)

    # --- 1. COMPILE INDIVIDUAL SCHOOL BUILDING RECORDS ---
    total_schools = len(schools_map)
    print(f"\n🚀 Discovered {total_schools} unique public schools across King & Snohomish counties.")
    print("📡 Resolving Redfin URLs & Computing 5-Year PSAI Scores...")

    compiled_schools = []
    sample_printed = False

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

        # Terminal diagnostic print of first verified score calculation
        if not sample_printed and psai_score is not None:
            print(f"\n📊 [Sample Verified Extraction]:")
            print(f"   • School: {school_data['school_name']} ({school_data['district_name']})")
            print(f"   • Math Met: {latest_math}% | ELA Met: {latest_ela}% ➔ PSAI Index: {psai_score}/100\n")
            sample_printed = True

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
        if idx % 100 == 0 or idx == total_schools:
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

        # Fallback calculation: Aggregate individual school building scores if district summary row is absent
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
                if str(d_info.get("district_code")).strip() == ospi_id:
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

    # --- 4. ANTI-WIPEOUT GUARDRAIL & WRITE MASTER UNIFIED JSON ---
    schools_with_scores = sum(1 for s in compiled_schools if s["psai_score"] is not None)
    if total_schools > 0 and schools_with_scores == 0:
        print("\n⚠️ WARNING: 0 schools computed valid PSAI scores.")
        print("⚠️ Aborting file write to preserve existing verified data asset.")
        return

    master_output = {
        "schools": compiled_schools,
        "districts": compiled_districts,
        "city_district_ratings": compiled_city_ratings
    }

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(master_output, f, indent=2, ensure_ascii=False)

    print(f"\n🎉 Master harvesting complete!")
    print(f"  • Compiled {len(compiled_schools)} individual school facilities ({schools_with_scores} with active PSAI ratings).")
    print(f"  • Compiled {len(compiled_districts)} school districts.")
    print(f"  • Compiled {len(compiled_city_ratings)} city-district rating mappings.")
    print(f"  • Saved master dataset to: {OUTPUT_JSON}")

if __name__ == "__main__":
    main()