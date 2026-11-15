# File: scripts/quarterly/harvest_ospi_school_data.py

import os
import re
import json
import time
import random
import argparse
import urllib.parse
import urllib3
import requests

# Suppress SSL warnings for public REST endpoints
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Directory Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
STAGING_DIR = os.path.join(DATA_DIR, "staging")
CITY_DATA_JSON = os.path.join(DATA_DIR, "city_data.json")
OUTPUT_JSON = os.path.join(DATA_DIR, "ospi_school_data.json")
REDFIN_CACHE_JSON = os.path.join(STAGING_DIR, "redfin_school_url_cache.json")

# Primary and Fallback OSPI Socrata Endpoints (Data.WA.gov Report Card Assessment Series)
OSPI_ASSESSMENT_ENDPOINTS = [
    "https://data.wa.gov/resource/h5d9-vgwi.json",  # OSPI Report Card Assessment (2024-25)
    "https://data.wa.gov/resource/x73g-mrqp.json"   # OSPI Report Card Assessment (2023-24)
]

# Federal NCES EDGE Public School Characteristics FeatureServer (Compiled from OSPI State Submission)
# Contains Physical Street Address, City, ZIP, Exact Coordinates & Individual School Building Websites
NCES_DIRECTORY_ENDPOINTS = [
    "https://services1.arcgis.com/Ua5sjt3LWTPigjyD/arcgis/rest/services/School_Characteristics_Current/FeatureServer/1/query",
    "https://services1.arcgis.com/Ua5sjt3LWTPigjyD/arcgis/rest/services/School_Characteristics_Current/FeatureServer/0/query",
]

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

# Washington State Assessment Baselines (Statewide Average Met Standard)
STATE_MATH_BASELINE = 40.0
STATE_ELA_BASELINE = 51.0
STATE_SCIENCE_BASELINE = 43.0

NCES_MISSING_TOKENS = {"", "n", "m", "na", "n/a", "null", "none", "-", "missing", "not applicable", "suppressed"}


def is_valid_nces_str(val):
    if val is None:
        return False
    return str(val).strip().lower() not in NCES_MISSING_TOKENS


def format_street_address(raw_addr):
    if not is_valid_nces_str(raw_addr):
        return ""
    s = re.sub(r"\s+", " ", str(raw_addr).strip())
    if s.isupper():
        dirs = {"N", "S", "E", "W", "NE", "NW", "SE", "SW", "PO"}
        ordinals = re.compile(r"^(\d+)(ST|ND|RD|TH)$", re.IGNORECASE)
        formatted = []
        for tok in s.split(" "):
            up = tok.upper().rstrip(",")
            comma = "," if tok.endswith(",") else ""
            if up in dirs:
                formatted.append(up + comma)
            elif ordinals.match(up):
                m = ordinals.match(up)
                formatted.append(f"{m.group(1)}{m.group(2).lower()}{comma}")
            else:
                formatted.append(tok.capitalize())
        return " ".join(formatted)
    return s


def format_city_name(raw_city):
    if not is_valid_nces_str(raw_city):
        return ""
    s = re.sub(r"\s+", " ", str(raw_city).strip())
    if s.isupper():
        return " ".join(w.capitalize() for w in s.split(" "))
    return s


def normalize_school_key(name):
    if not name:
        return ""
    s = str(name).lower().strip()
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"\b(elementary|middle|junior high|jr high|senior high|sr high|high|school|academy|center|program)\b", "", s)
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


def normalize_website_url(raw_url):
    if not is_valid_nces_str(raw_url):
        return ""
    url = str(raw_url).strip()
    if not url or "." not in url or " " in url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    return url


def load_city_district_mappings():
    """
    Dynamically loads city-to-district mappings and fallback district websites from data/city_data.json.
    Supports comma-separated multi-district mappings (e.g., Sammamish).
    """
    print(f"Loading municipal district mappings from {CITY_DATA_JSON}...")
    city_map = {}
    district_web_fallbacks = {}
    
    if not os.path.exists(CITY_DATA_JSON):
        print(f"  Warning: {CITY_DATA_JSON} not found. City district ratings will be empty.")
        return city_map, district_web_fallbacks

    try:
        with open(CITY_DATA_JSON, "r", encoding="utf-8") as f:
            cities_list = json.load(f)

        for item in cities_list:
            city_name = item.get("City", "").strip()
            district_name = item.get("School District", "").strip()
            ospi_id = str(item.get("OSPI District ID", "")).strip()
            web_url = item.get("School Website", "").strip()

            if city_name and (district_name or ospi_id):
                city_map[city_name] = {
                    "district_name": district_name,
                    "ospi_district_id": ospi_id
                }

            if district_name and web_url and district_name not in district_web_fallbacks:
                district_web_fallbacks[district_name] = web_url

        print(f"  Successfully mapped {len(city_map)} cities from city_data.json.")
    except Exception as e:
        print(f"  Error loading city_data.json: {e}")

    return city_map, district_web_fallbacks


def safe_float(val):
    """Safely extracts a numeric float from strings with percentages or comparison characters."""
    if val is None or val == "":
        return None
    s = str(val).strip().lower()
    if s in ["null", "n/a", "suppressed", "s", "*", "none", "-", "count unavailable", "m", "n"]:
        return None
    try:
        clean_str = s.replace("%", "").replace(">", "").replace("<", "").replace(",", "").strip()
        return float(clean_str)
    except (ValueError, TypeError):
        return None


def parse_percentage(val):
    """
    Parses and normalizes test score strings into true 0.0-100.0 percentages.
    Converts decimal rates (e.g., 0.345 -> 34.5%) while preserving whole percentages.
    """
    v = safe_float(val)
    if v is None:
        return None
    if 0.0 < v <= 1.0:
        v = v * 100.0
    return round(v, 1)


def calculate_psai_score(math_pct, ela_pct, science_pct):
    """
    Computes the difficulty-weighted Puget Sound Academic Index (PSAI) on a 0-100 scale,
    dynamically anchoring only to subjects actually tested at the facility.
    """
    active_pairs = []
    if math_pct is not None:
        active_pairs.append((math_pct, STATE_MATH_BASELINE))
    if ela_pct is not None:
        active_pairs.append((ela_pct, STATE_ELA_BASELINE))
    if science_pct is not None:
        active_pairs.append((science_pct, STATE_SCIENCE_BASELINE))

    if not active_pairs:
        return None, None

    multipliers = [score / base for score, base in active_pairs]
    composite_ratio = sum(multipliers) / len(multipliers)
    raw_active_benchmark = sum(base for _, base in active_pairs) / len(active_pairs)
    active_benchmark = round(raw_active_benchmark, 1)

    psai = round(composite_ratio * raw_active_benchmark, 1)
    psai = min(100.0, psai)

    return psai, active_benchmark


def fetch_school_directory_geography():
    """
    Queries the NCES EDGE Public School Characteristics FeatureServer (compiled from OSPI)
    to index physical street addresses, true municipalities, ZIP codes, coordinates,
    and individual school building websites across King & Snohomish counties.
    """
    print("Ingesting NCES / OSPI Physical School Directory, Geocodes & Building Websites...")
    by_code = {}
    by_name = {}
    district_web_lookup = {}

    for endpoint in NCES_DIRECTORY_ENDPOINTS:
        features = []
        offset = 0
        page_size = 1000
        while True:
            params = {
                "where": "LSTATE = 'WA' AND NMCNTY IN ('King County', 'Snohomish County')",
                "outFields": "*",
                "returnGeometry": "true",
                "outSR": "4326",
                "resultOffset": offset,
                "resultRecordCount": page_size,
                "f": "json",
            }
            try:
                resp = requests.get(endpoint, headers=HTTP_HEADERS, params=params, timeout=30, verify=False)
                if resp.status_code != 200:
                    print(f"  Notice: Directory endpoint returned HTTP {resp.status_code} ({endpoint})")
                    break
                payload = resp.json()
                if "error" in payload:
                    print(f"  Notice: Directory query error: {payload['error']}")
                    break
                batch = payload.get("features") or []
                features.extend(batch)
                if not payload.get("exceededTransferLimit") or len(batch) < page_size:
                    break
                offset += len(batch)
            except Exception as e:
                print(f"  Warning: Directory query notice on {endpoint}: {e}")
                break

        if not features:
            continue

        for feat in features:
            raw_attrs = feat.get("attributes") or {}
            geom = feat.get("geometry") or {}
            a = {str(k).upper(): v for k, v in raw_attrs.items()}

            st_schid = str(a.get("ST_SCHID") or "").strip()
            scode = ""
            if st_schid:
                parts = [p.strip() for p in st_schid.split("-") if p.strip()]
                if parts:
                    scode = parts[-1].lstrip("0") or parts[-1]

            st_leaid = str(a.get("ST_LEAID") or "").strip()
            dcode = ""
            if st_leaid:
                dparts = [p.strip() for p in st_leaid.split("-") if p.strip()]
                if dparts:
                    dcode = dparts[-1]

            sch_name = str(a.get("SCH_NAME") or "").strip()
            lea_name = str(a.get("LEA_NAME") or "").strip()
            county_raw = str(a.get("NMCNTY") or "").replace(" County", "").strip()

            street1 = format_street_address(a.get("LSTREET1"))
            street2 = format_street_address(a.get("LSTREET2"))
            address = f"{street1}, {street2}" if (street1 and street2) else street1

            city = format_city_name(a.get("LCITY"))
            zip_raw = str(a.get("LZIP") or "").strip()
            zip_code = zip_raw[:5] if is_valid_nces_str(zip_raw) else ""

            lat = safe_float(a.get("LATCOD"))
            lon = safe_float(a.get("LONCOD"))
            if lat is None and geom.get("y") is not None:
                lat = safe_float(geom.get("y"))
            if lon is None and geom.get("x") is not None:
                lon = safe_float(geom.get("x"))
            if lat is not None:
                lat = round(lat, 6)
            if lon is not None:
                lon = round(lon, 6)

            school_web = normalize_website_url(a.get("WEBSITE"))

            geo_payload = {
                "address": address,
                "city": city,
                "zip": zip_code,
                "latitude": lat,
                "longitude": lon,
                "school_website": school_web,
            }

            if scode and scode not in by_code:
                by_code[scode] = geo_payload

            norm_sch = normalize_school_key(sch_name)
            if norm_sch:
                if dcode:
                    by_name.setdefault((dcode, norm_sch), geo_payload)
                if county_raw:
                    by_name.setdefault((county_raw.lower(), norm_sch), geo_payload)

            if dcode and school_web and f"domain_{dcode}" not in district_web_lookup:
                m_dom = re.match(r"^(https?://[^/]+)", school_web)
                if m_dom and any(tok in m_dom.group(1) for tok in ("wednet", "schools", "org")):
                    district_web_lookup[f"domain_{dcode}"] = m_dom.group(1)
            if lea_name and f"domain_{dcode}" in district_web_lookup:
                district_web_lookup.setdefault(f"domain_{lea_name}", district_web_lookup[f"domain_{dcode}"])

        if by_code:
            print(f"  Indexed physical addresses, coordinates & websites for {len(by_code)} schools from NCES/OSPI.")
            break

    return by_code, by_name, district_web_lookup


class RedfinSchoolResolver:
    """
    Resolves canonical Redfin /school/<id>/... URLs using Redfin's location-autocomplete
    endpoint with persistent local JSON caching so quarterly runs accumulate coverage
    without re-querying already-resolved schools.
    """
    def __init__(self, cache_path, enabled=True):
        self.cache_path = cache_path
        self.enabled = enabled
        self.cache = {}
        self.dirty = False
        self.consecutive_blocks = 0

        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        self.cache = loaded
            except Exception:
                pass

    def save_cache(self):
        if not self.dirty:
            return
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(self.cache, f, indent=2, ensure_ascii=False)
        self.dirty = False

    def resolve(self, school_code, school_name, city_name, county):
        cached_url = self.cache.get(school_code, "")
        if cached_url:
            return {"redfin_url": cached_url, "city": "", "lat": None, "lon": None}

        if not self.enabled or not school_name or self.consecutive_blocks >= 6:
            return {"redfin_url": "", "city": "", "lat": None, "lon": None}

        loc_hint = city_name if city_name else f"{county} County"
        query_str = f"{school_name}, {loc_hint}, WA"
        encoded_query = urllib.parse.quote(query_str)
        endpoint = f"https://www.redfin.com/stingray/do/location-autocomplete?location={encoded_query}&v=2"

        try:
            time.sleep(random.uniform(0.45, 0.85))
            resp = requests.get(endpoint, headers=HTTP_HEADERS, timeout=7, verify=False)
            if resp.status_code in (403, 429):
                self.consecutive_blocks += 1
                if self.consecutive_blocks == 6:
                    print("  Notice: Redfin rate limit reached; preserving cached URLs and continuing directory harvest.")
                return {"redfin_url": "", "city": "", "lat": None, "lon": None}

            if resp.status_code == 200:
                self.consecutive_blocks = 0
                clean_text = resp.text.replace("{}&&", "").strip()
                if clean_text.startswith("{"):
                    data = json.loads(clean_text)
                    payload = data.get("payload") or {}

                    candidates = []
                    exact_match = payload.get("exactMatch")
                    if isinstance(exact_match, dict) and exact_match.get("url"):
                        candidates.append(exact_match)
                    for section in payload.get("sections") or []:
                        for row in section.get("rows") or []:
                            if isinstance(row, dict) and row.get("url"):
                                candidates.append(row)

                    for cand in candidates:
                        url_path = str(cand.get("url") or "")
                        if "/school/" in url_path.lower():
                            full_url = f"https://www.redfin.com{url_path}"
                            self.cache[school_code] = full_url
                            self.dirty = True
                            parsed_city = ""
                            sub_text = str(cand.get("subText") or "")
                            if sub_text:
                                parsed_city = sub_text.split(",")[0].strip()
                            return {
                                "redfin_url": full_url,
                                "city": parsed_city,
                                "lat": safe_float(cand.get("lat")),
                                "lon": safe_float(cand.get("long")),
                            }
        except Exception:
            pass

        return {"redfin_url": "", "city": "", "lat": None, "lon": None}


def sniff_schema_fields(sample_records):
    """Dynamic schema field inspector across Socrata release cycles."""
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

    org_level_key = match_key([r"^org.*level$", r"organizationlevel", r"org_level"]) or "organizationlevel"
    school_code_key = match_key([r"schoolcode", r"school_code", r"buildingcode", r"building_code"]) or "schoolcode"
    school_name_key = match_key([r"schoolname", r"school_name", r"buildingname", r"building_name"]) or "schoolname"
    district_name_key = match_key([r"districtname", r"district_name"]) or "districtname"
    district_code_key = match_key([r"county_district_number", r"countydistrictnumber", r"districtcode", r"district_code"]) or "districtcode"
    county_key = match_key([r"^county$", r"^countyname$", r"^county_name$"]) or "county"
    year_key = match_key([r"schoolyear", r"school_year", r"^year$"]) or "schoolyear"
    subject_key = match_key([r"testsubject", r"^subject$", r"test_subject", r"subjectname", r"contentarea"]) or "testsubject"
    student_group_key = match_key([r"^studentgroup$", r"^student_group$", r"subgroup"]) or "studentgroup"
    student_group_type_key = match_key([r"^studentgrouptype$", r"^student_group_type$"]) or "studentgrouptype"

    score_candidates = []
    for k in all_keys:
        kl = k.lower()
        if any(x in kl for x in ["suppress", "no_score", "not_tested", "alternative", "participation"]):
            continue
        if ("percent" in kl or "pct" in kl) and any(y in kl for y in ["tested", "standard", "consistent", "met", "proficiency"]):
            score_candidates.append(k)

    score_candidates.sort(key=lambda x: (
        0 if "tested" in x.lower() else
        1 if "standard" in x.lower() else
        2 if "consistent" in x.lower() else 3
    ))

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
    """Pages through a Socrata endpoint with resilient county field probing."""
    records = []
    limit = 25000
    offset = 0

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
        print(f"  Schema probe warning on {endpoint}: {e}")

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
            else:
                break
        except Exception:
            break

    return records


def fetch_all_ospi_records():
    """Queries all configured OSPI Report Card Socrata REST endpoints."""
    print("Querying OSPI Assessment Data from Data.WA.gov...")
    all_records = []

    for ep in OSPI_ASSESSMENT_ENDPOINTS:
        print(f"  Ingesting stream: {ep}...")
        ep_records = fetch_ospi_endpoint_records(ep)
        print(f"  Retrieved {len(ep_records)} records from stream.")
        all_records.extend(ep_records)

    print(f"  Compiled {len(all_records)} total assessment records.")
    return all_records


def process_ospi_data(records):
    """Processes raw assessment records into structured school and district maps."""
    schools_map = {}
    districts_map = {}
    school_raw_scores = {}
    district_raw_scores = {}

    if not records:
        return schools_map, districts_map

    schema = sniff_schema_fields(records)
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

    for r in records:
        org_level = str(r.get(k_org, "")).strip().lower()
        scode = str(r.get(k_scode, "")).strip()
        sname = str(r.get(k_sname, "")).strip()
        dname = str(r.get(k_dname, "")).strip()
        dcode = str(r.get(k_dcode, "")).strip()
        county = str(r.get(k_county, "")).strip()
        stype = str(r.get("currentschooltype", r.get("schooltype", r.get("type", "P")))).strip() or "P"

        if org_level == "school" and scode and sname:
            if scode not in schools_map:
                schools_map[scode] = {
                    "school_name": sname,
                    "school_code": scode,
                    "ospi_org_id": str(r.get("schoolorganizationid", r.get("school_org_id", r.get("org_id", "")))).strip(),
                    "district_name": dname,
                    "district_code": dcode,
                    "county": county,
                    "school_type": stype
                }
                school_raw_scores[scode] = {"math": {}, "ela": {}, "science": {}}

        if dname:
            if dname not in districts_map:
                districts_map[dname] = {
                    "district_name": dname,
                    "district_code": dcode,
                    "county": county,
                    "records_count": 0
                }
                district_raw_scores[dname] = {"math": {}, "ela": {}, "science": {}}
            elif dcode and not districts_map[dname]["district_code"]:
                districts_map[dname]["district_code"] = dcode

        # Cohort Filtering
        sgroup = str(r.get(k_sgroup, "")).strip().lower()
        sgrouptype = str(r.get(k_sgrouptype, "")).strip().lower()
        is_all_students = (
            sgroup in ["all students", "all", "total", ""] or 
            sgrouptype in ["all", "federal", ""] or 
            "all students" in sgroup or 
            sgrouptype == ""
        )
        if not is_all_students:
            continue

        pct_met = None
        for sk in score_keys:
            val = r.get(sk)
            if val is not None and str(val).strip() != "":
                parsed = parse_percentage(val)
                if parsed is not None:
                    pct_met = parsed
                    break

        if pct_met is None and k_c_met and k_c_tot:
            c_met = safe_float(r.get(k_c_met))
            c_tot = safe_float(r.get(k_c_tot))
            if c_met is not None and c_tot is not None and c_tot > 0:
                pct_met = parse_percentage(c_met / c_tot)

        if pct_met is None:
            continue

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

        if org_level == "school" and scode in school_raw_scores:
            if syear not in school_raw_scores[scode][subject_key]:
                school_raw_scores[scode][subject_key][syear] = []
            school_raw_scores[scode][subject_key][syear].append(pct_met)

        if org_level == "district" and dname in district_raw_scores:
            if syear not in district_raw_scores[dname][subject_key]:
                district_raw_scores[dname][subject_key][syear] = []
            district_raw_scores[dname][subject_key][syear].append(pct_met)

    def get_latest_subject_score(subj_years_map):
        if not subj_years_map:
            return None
        sorted_years = sorted(subj_years_map.keys(), reverse=True)
        for yr in sorted_years:
            vals = subj_years_map[yr]
            if vals:
                return round(sum(vals) / len(vals), 1)
        return None

    for scode, subjects in school_raw_scores.items():
        schools_map[scode]["latest_math_pct"] = get_latest_subject_score(subjects["math"])
        schools_map[scode]["latest_ela_pct"] = get_latest_subject_score(subjects["ela"])
        schools_map[scode]["latest_science_pct"] = get_latest_subject_score(subjects["science"])

    for dname, subjects in district_raw_scores.items():
        districts_map[dname]["district_math_proficiency"] = get_latest_subject_score(subjects["math"])
        districts_map[dname]["district_ela_proficiency"] = get_latest_subject_score(subjects["ela"])
        districts_map[dname]["district_science_proficiency"] = get_latest_subject_score(subjects["science"])

    for scode, s_data in schools_map.items():
        d_name = s_data["district_name"]
        if d_name in districts_map:
            districts_map[d_name]["records_count"] += 1

    return schools_map, districts_map


def main():
    parser = argparse.ArgumentParser(description="OSPI & NCES Master School Data Harvester.")
    parser.add_argument("--skip-redfin", action="store_true", help="Skip Redfin school URL autocomplete lookups.")
    args = parser.parse_args()

    print("==================================================")
    print("     OSPI MASTER SCHOOL DATA HARVESTER (V6.1)     ")
    print("==================================================")

    os.makedirs(DATA_DIR, exist_ok=True)
    city_mapping, district_web_fallbacks = load_city_district_mappings()

    # Step A: Ingest Physical Street Addresses, Cities, ZIPs, Coordinates & Building Websites
    geo_by_code, geo_by_name, district_web_lookup = fetch_school_directory_geography()

    # Step B: Ingest State Assessment Performance Data
    raw_records = fetch_all_ospi_records()
    if not raw_records:
        print("Error: No OSPI assessment records fetched. Exiting.")
        return

    schools_map, districts_map = process_ospi_data(raw_records)

    total_schools = len(schools_map)
    print(f"\nDiscovered {total_schools} unique public schools across King & Snohomish counties.")
    print("Resolving Geospatial Attributes, Individual Building Websites, Redfin URLs & PSAI Scores...")

    redfin_resolver = RedfinSchoolResolver(REDFIN_CACHE_JSON, enabled=not args.skip_redfin)
    compiled_schools = []

    for idx, (scode, school_data) in enumerate(schools_map.items(), 1):
        norm_scode = scode.lstrip("0") or scode
        norm_sname = normalize_school_key(school_data["school_name"])
        dcode = school_data["district_code"]
        county = school_data["county"]

        geo_info = (
            geo_by_code.get(norm_scode)
            or geo_by_name.get((dcode, norm_sname))
            or geo_by_name.get((county.lower(), norm_sname))
            or {}
        )

        street_address = geo_info.get("address", "")
        city_name = geo_info.get("city", "")
        zip_code = geo_info.get("zip", "")
        lat_coord = geo_info.get("latitude")
        lon_coord = geo_info.get("longitude")

        # Resolve canonical Redfin school URL using actual city & county context
        redfin_info = redfin_resolver.resolve(scode, school_data["school_name"], city_name, county)
        if not city_name and redfin_info.get("city"):
            city_name = redfin_info["city"]
        if lat_coord is None and redfin_info.get("lat") is not None:
            lat_coord = redfin_info["lat"]
        if lon_coord is None and redfin_info.get("lon") is not None:
            lon_coord = redfin_info["lon"]

        # Individual school building website first; district website fallback only if facility has none
        school_web_url = geo_info.get("school_website", "")
        if not school_web_url:
            school_web_url = (
                district_web_fallbacks.get(school_data["district_name"])
                or district_web_lookup.get(f"domain_{dcode}")
                or district_web_lookup.get(f"domain_{school_data['district_name']}")
                or ""
            )

        m_score = school_data.get("latest_math_pct")
        e_score = school_data.get("latest_ela_pct")
        s_score = school_data.get("latest_science_pct")

        psai_score, psai_benchmark = calculate_psai_score(m_score, e_score, s_score)

        school_entry = {
            "school_name": school_data["school_name"],
            "school_code": scode,
            "ospi_org_id": school_data["ospi_org_id"],
            "district_name": school_data["district_name"],
            "district_code": dcode,
            "county": county,
            "address": street_address,
            "city": city_name,
            "zip": zip_code,
            "latitude": lat_coord,
            "longitude": lon_coord,
            "website_url": school_web_url,
            "school_type": school_data["school_type"],
            "redfin_search_url": redfin_info["redfin_url"],
            "psai_score": psai_score,
            "psai_benchmark": psai_benchmark,
            "latest_math_pct": m_score,
            "latest_ela_pct": e_score,
            "latest_science_pct": s_score
        }

        compiled_schools.append(school_entry)
        if idx % 100 == 0 or idx == total_schools:
            redfin_resolver.save_cache()
            print(f"  [Progress] {idx}/{total_schools} schools enriched with addresses, coordinates & websites...")

    redfin_resolver.save_cache()
    compiled_schools.sort(key=lambda s: (s["county"], s["district_name"], s["school_name"]))

    # Step C: Compile District Summaries
    compiled_districts = {}
    for dname, ddata in districts_map.items():
        m_score = ddata.get("district_math_proficiency")
        e_score = ddata.get("district_ela_proficiency")
        s_score = ddata.get("district_science_proficiency")

        if m_score is None or e_score is None or s_score is None:
            dist_schools = [s for s in compiled_schools if s["district_name"] == dname]
            if dist_schools:
                if m_score is None:
                    m_vals = [s["latest_math_pct"] for s in dist_schools if s["latest_math_pct"] is not None]
                    if m_vals:
                        m_score = round(sum(m_vals) / len(m_vals), 1)
                if e_score is None:
                    e_vals = [s["latest_ela_pct"] for s in dist_schools if s["latest_ela_pct"] is not None]
                    if e_vals:
                        e_score = round(sum(e_vals) / len(e_vals), 1)
                if s_score is None:
                    s_vals = [s["latest_science_pct"] for s in dist_schools if s["latest_science_pct"] is not None]
                    if s_vals:
                        s_score = round(sum(s_vals) / len(s_vals), 1)

        psai_score, psai_benchmark = calculate_psai_score(m_score, e_score, s_score)

        dcode = ddata["district_code"]
        district_website = (
            district_web_fallbacks.get(dname)
            or district_web_lookup.get(f"domain_{dcode}")
            or district_web_lookup.get(f"domain_{dname}")
            or ""
        )

        compiled_districts[dname] = {
            "district_name": dname,
            "district_code": dcode,
            "county": ddata["county"],
            "records_count": ddata["records_count"],
            "website_url": district_website,
            "district_math_proficiency": m_score,
            "district_ela_proficiency": e_score,
            "district_science_proficiency": s_score,
            "psai_score": psai_score,
            "psai_benchmark": psai_benchmark
        }

    # Step D: Compile City District Ratings
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
            sci_vals = [d["district_science_proficiency"] for d in matched_dists if d["district_science_proficiency"] is not None]

            math_prof = round(sum(math_vals) / len(math_vals), 1) if math_vals else None
            ela_prof = round(sum(ela_vals) / len(ela_vals), 1) if ela_vals else None
            sci_prof = round(sum(sci_vals) / len(sci_vals), 1) if sci_vals else None

            psai, psai_benchmark = calculate_psai_score(math_prof, ela_prof, sci_prof)
            actual_dname = ", ".join([d["district_name"] for d in matched_dists])
        else:
            math_prof, ela_prof, sci_prof = None, None, None
            psai, psai_benchmark = None, None
            actual_dname = meta["district_name"]

        status = "Active" if psai is not None else "Insufficient Data (Small Student Population)"

        compiled_city_ratings[city_name] = {
            "district_name": actual_dname,
            "district_math_proficiency": math_prof,
            "district_ela_proficiency": ela_prof,
            "district_science_proficiency": sci_prof,
            "custom_score": psai,
            "custom_score_benchmark": psai_benchmark,
            "state_math_baseline": STATE_MATH_BASELINE,
            "state_ela_baseline": STATE_ELA_BASELINE,
            "state_science_baseline": STATE_SCIENCE_BASELINE,
            "status": status
        }

    # Step E: Guardrail & Output
    schools_with_scores = sum(1 for s in compiled_schools if s["psai_score"] is not None)
    if total_schools > 0 and schools_with_scores == 0:
        print("\nWarning: 0 schools computed valid PSAI scores. Aborting write.")
        return

    geo_count = sum(1 for s in compiled_schools if s["latitude"] is not None and s["longitude"] is not None)
    addr_count = sum(1 for s in compiled_schools if s["address"])
    web_count = sum(1 for s in compiled_schools if s["website_url"])
    redfin_count = sum(1 for s in compiled_schools if s["redfin_search_url"])

    master_output = {
        "schools": compiled_schools,
        "districts": compiled_districts,
        "city_district_ratings": compiled_city_ratings
    }

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(master_output, f, indent=2, ensure_ascii=False)

    print(f"\nMaster harvesting complete!")
    print(f"  Compiled {len(compiled_schools)} individual school facilities.")
    print(f"  Addresses populated: {addr_count}/{len(compiled_schools)} | Geocodes: {geo_count}/{len(compiled_schools)} | Websites: {web_count}/{len(compiled_schools)} | Redfin URLs: {redfin_count}/{len(compiled_schools)}")
    print(f"  Compiled {len(compiled_districts)} school districts.")
    print(f"  Saved master dataset to: {OUTPUT_JSON}")


if __name__ == "__main__":
    main()