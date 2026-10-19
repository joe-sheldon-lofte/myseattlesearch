# File: scripts/quarterly/harvest_school_boundaries.py

import os
import json
import re
import urllib3
import requests
from datetime import datetime

# Suppress SSL warnings for public REST endpoints
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Directory Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
OSPI_DATA_JSON = os.path.join(DATA_DIR, "ospi_school_data.json")
OUTPUT_BOUNDARIES_JSON = os.path.join(DATA_DIR, "school_boundaries.json")

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*"
}

# --- STATE OSPI DISTRICT BOUNDARY ENDPOINTS ---
STATE_DISTRICT_ENDPOINTS = [
    "https://services8.arcgis.com/rGGrs6HCnw87OFOT/arcgis/rest/services/OSPISchoolDistricts_2025/FeatureServer/0/query",
    "https://gis.ospi.k12.wa.gov/arcgis/rest/services/Public/OSPISchoolDistricts/FeatureServer/0/query"
]

# --- OFFICIAL DISTRICT BOUNDARY LOOKUP URLS ---
DISTRICT_LOOKUP_URLS = {
    "17001": {"name": "Seattle School District No. 1", "url": "https://www.seattleschools.org/enrollment/about-our-schools/school-boundaries/"},
    "17405": {"name": "Bellevue School District", "url": "https://bsd405.org/about/boundaries/"},
    "17414": {"name": "Lake Washington School District", "url": "https://www.lwsd.org/about-us/school-boundaries"},
    "17417": {"name": "Northshore School District", "url": "https://www.nsd.org/about-us/maps-boundaries"},
    "31015": {"name": "Edmonds School District", "url": "https://www.edmonds.wednet.edu/families/enrollment/school-boundaries"},
    "31002": {"name": "Everett School District", "url": "https://www.everettsd.org/Page/3110"},
    "17403": {"name": "Renton School District", "url": "https://www.rentonschools.us/learning-and-teaching/enrollment-registration/school-boundaries"},
    "17401": {"name": "Highline School District", "url": "https://www.highlineschools.org/about/maps-boundaries"},
    "17210": {"name": "Federal Way School District", "url": "https://www.fwps.org/about/district-maps-boundaries"},
    "31006": {"name": "Mukilteo School District", "url": "https://www.mukilteoschools.org/domain/35"},
    "17411": {"name": "Issaquah School District", "url": "https://www.issaquah.wednet.edu/about/maps"},
    "17408": {"name": "Auburn School District", "url": "https://www.auburn.wednet.edu/domain/51"},
    "17415": {"name": "Kent School District", "url": "https://www.kent.k12.wa.us/domain/71"},
    "17409": {"name": "Tahoma School District", "url": "https://www.tahomasd.us/about_us/maps___boundaries"},
    "17410": {"name": "Snoqualmie Valley School District", "url": "https://www.svsd410.org/about-us/maps-boundaries"},
    "31004": {"name": "Lake Stevens School District", "url": "https://www.lkstevens.wednet.edu/domain/48"},
    "31201": {"name": "Snohomish School District", "url": "https://www.sno.wednet.edu/domain/132"},
    "31025": {"name": "Marysville School District", "url": "https://www.msd25.org/page/school-boundaries"},
    "31103": {"name": "Monroe School District", "url": "https://www.monroe.wednet.edu/about/school-boundaries"},
    "31401": {"name": "Stanwood-Camano School District", "url": "https://www.stanwood.wednet.edu/about_us/boundaries"},
    "17407": {"name": "Riverview School District", "url": "https://www.riverview.wednet.edu/page/district-maps-and-boundaries"},
    "17216": {"name": "Enumclaw School District", "url": "https://www.enumclaw.wednet.edu/page/boundaries"},
    "31306": {"name": "Lakewood School District", "url": "https://www.lwsd88.org/about-us/district-map-boundaries"},
    "31332": {"name": "Granite Falls School District", "url": "https://www.gfalls.wednet.edu/about-us/district-map"},
    "31311": {"name": "Sultan School District", "url": "https://www.sultanschools.org/about-us/boundaries"},
    "31330": {"name": "Darrington School District", "url": "https://www.dsd.k12.wa.us/about-us/district-map"},
    "17406": {"name": "Tukwila School District", "url": "https://www.tukwilaschools.org/about-us/district-map"},
    "17402": {"name": "Vashon Island School District", "url": "https://www.vashonsd.org/about-us/district-boundaries"}
}

def normalize_name(text):
    """Simplifies district names for robust string matching."""
    if not text:
        return ""
    s = text.lower().strip()
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\b(school|district|dist|no|sd|k12|public|schools)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()

def load_ospi_district_metadata():
    """Reads data/ospi_school_data.json to build lookup indexes for school districts."""
    print(f"📖 Reading district metadata from {OSPI_DATA_JSON}...")
    districts_by_name = {}
    districts_by_code = {}

    if not os.path.exists(OSPI_DATA_JSON):
        print(f"  ⚠️ Warning: {OSPI_DATA_JSON} not found. Matching will rely solely on GIS feature properties.")
        return districts_by_name, districts_by_code

    try:
        with open(OSPI_DATA_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)

        districts = data.get("districts", {})
        for dname, dinfo in districts.items():
            norm_dname = normalize_name(dname)
            dcode = str(dinfo.get("district_code", "")).strip()

            if norm_dname:
                districts_by_name[norm_dname] = dinfo
            if dcode:
                districts_by_code[dcode] = dinfo

        print(f"  ✓ Indexed {len(districts)} school districts from OSPI master data.")
    except Exception as e:
        print(f"  ❌ Error reading ospi_school_data.json: {e}")

    return districts_by_name, districts_by_code

def clean_coordinate_array(coords, precision=5):
    """
    Recursively rounds latitude/longitude pairs to 5 decimal places (~1.1m ground precision).
    Preserves complete topology without modifying line shapes.
    """
    if not coords:
        return coords
    if isinstance(coords[0], (int, float)):
        return [round(float(c), precision) for c in coords[:2]]
    return [clean_coordinate_array(sub, precision) for sub in coords]

def extract_property(props, keys):
    """Schema-agnostic extractor for GeoJSON/Esri feature properties."""
    for k in keys:
        if k in props and props[k] is not None:
            val = str(props[k]).strip()
            if val != "" and val.lower() != "none":
                return val
    return ""

def fetch_gis_features(url):
    """
    Queries an Esri ArcGIS REST endpoint with handling for GeoJSON (f=geojson)
    and Esri JSON (f=json) ring geometry conversion.
    """
    # 1. Try GeoJSON
    params_geojson = {
        "where": "1=1",
        "outFields": "*",
        "outSR": "4326",
        "returnGeometry": "true",
        "f": "geojson"
    }

    try:
        resp = requests.get(url, headers=HTTP_HEADERS, params=params_geojson, timeout=25, verify=False)
        if resp.status_code == 200:
            data = resp.json()
            features = data.get("features", [])
            if features and "geometry" in features[0] and "coordinates" in features[0]["geometry"]:
                return features
    except Exception:
        pass

    # 2. Fallback to Esri JSON (f=json)
    params_esri = {
        "where": "1=1",
        "outFields": "*",
        "outSR": "4326",
        "returnGeometry": "true",
        "f": "json"
    }

    try:
        resp = requests.get(url, headers=HTTP_HEADERS, params=params_esri, timeout=25, verify=False)
        if resp.status_code == 200:
            data = resp.json()
            features = data.get("features", [])
            converted_features = []

            for f in features:
                attrs = f.get("attributes", {})
                geom = f.get("geometry", {})
                rings = geom.get("rings", [])

                if not rings:
                    continue

                geom_type = "Polygon" if len(rings) == 1 else "MultiPolygon"
                coords = rings if len(rings) == 1 else [rings]

                converted_features.append({
                    "type": "Feature",
                    "properties": attrs,
                    "geometry": {
                        "type": geom_type,
                        "coordinates": coords
                    }
                })

            return converted_features
    except Exception:
        pass

    return []

def harvest_district_polygons(districts_by_name, districts_by_code):
    """Harvests regional district perimeters from OSPI GIS for King and Snohomish counties."""
    print("📡 Ingesting Washington State OSPI District Boundaries...")
    raw_features = []

    for url in STATE_DISTRICT_ENDPOINTS:
        print(f"  • Querying endpoint: {url}...")
        raw_features = fetch_gis_features(url)
        if raw_features:
            print(f"    ✓ Retrieved {len(raw_features)} statewide district polygon features.")
            break

    districts_map = {}
    name_fields = ["District_Name", "NAME", "LEANAME", "DIST_NAME", "DISTRICT", "District"]
    code_fields = ["LEACD", "DIST_CODE", "DISTRICT_CODE", "COUNTY_DIST", "COUNTY_DISTRICT_NUMBER", "DIST_NUM", "GEOID"]
    county_fields = ["Counties", "COUNTY", "County_Name", "COUNTY_NAME"]

    for feat in raw_features:
        props = feat.get("properties", {})
        geom = feat.get("geometry", {})

        if not geom or "coordinates" not in geom:
            continue

        raw_name = extract_property(props, name_fields)
        raw_code = extract_property(props, code_fields)
        raw_county = extract_property(props, county_fields)

        norm_key = normalize_name(raw_name)
        matched_district = districts_by_code.get(raw_code) or districts_by_name.get(norm_key)

        # Fallback substring and token match
        if not matched_district and norm_key:
            gis_tokens = set(norm_key.split())
            for d_norm, d_info in districts_by_name.items():
                d_tokens = set(d_norm.split())
                if gis_tokens and d_tokens and (gis_tokens.issubset(d_tokens) or d_tokens.issubset(gis_tokens)):
                    matched_district = d_info
                    break

        is_target_county = any(c in raw_county for c in ["King", "Snohomish"])
        if not is_target_county and matched_district:
            matched_county = matched_district.get("county", "")
            is_target_county = any(c in matched_county for c in ["King", "Snohomish"])

        if not is_target_county:
            continue

        dcode = (matched_district.get("district_code") if matched_district else "") or raw_code or str(props.get("OBJECTID", ""))
        dname = (matched_district.get("district_name") if matched_district else "") or raw_name

        if dcode:
            clean_geom = {
                "type": geom.get("type", "Polygon"),
                "coordinates": clean_coordinate_array(geom.get("coordinates", []), precision=5)
            }

            districts_map[dcode] = {
                "district_code": dcode,
                "district_name": dname,
                "county": raw_county or (matched_district.get("county") if matched_district else ""),
                "state": "WA",
                "geometry": clean_geom
            }

    return districts_map

def main():
    print("==================================================")
    print("   OSPI SCHOOL DISTRICT BOUNDARY HARVESTER (V4.0) ")
    print("==================================================\n")

    os.makedirs(DATA_DIR, exist_ok=True)
    districts_by_name, districts_by_code = load_ospi_district_metadata()

    district_boundaries = harvest_district_polygons(districts_by_name, districts_by_code)
    print(f"\n  ✅ Successfully compiled {len(district_boundaries)} regional district perimeters.")

    # Guardrail: Prevent overwriting existing asset if remote endpoint returns empty
    MINIMUM_DISTRICTS_THRESHOLD = 25
    if len(district_boundaries) < MINIMUM_DISTRICTS_THRESHOLD:
        print(f"⚠️ Warning: Only compiled {len(district_boundaries)} district boundaries (minimum required: {MINIMUM_DISTRICTS_THRESHOLD}).")
        print(f"⚠️ Aborting file write to preserve existing dataset at {OUTPUT_BOUNDARIES_JSON}.")
        return

    master_output = {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "district_boundaries_count": len(district_boundaries),
            "coordinate_system": "EPSG:4326 (WGS84)",
            "precision_meters": "~1.1m"
        },
        "school_catchments": {},
        "district_boundaries": district_boundaries,
        "district_lookup_urls": DISTRICT_LOOKUP_URLS
    }

    with open(OUTPUT_BOUNDARIES_JSON, "w", encoding="utf-8") as f:
        json.dump(master_output, f, indent=2, ensure_ascii=False)

    print(f"\n🎉 Boundary harvesting complete!")
    print(f"  • Compiled {len(district_boundaries)} macro school district perimeters.")
    print(f"  • Indexed {len(DISTRICT_LOOKUP_URLS)} district boundary finder links.")
    print(f"  • Saved master spatial asset to: {OUTPUT_BOUNDARIES_JSON}")

if __name__ == "__main__":
    main()