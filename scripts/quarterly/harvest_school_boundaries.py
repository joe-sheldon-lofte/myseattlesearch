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
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://gisdata.seattle.gov/",
    "Origin": "https://gisdata.seattle.gov"
}

# --- TIER 1 GIS CATCHMENT ENDPOINTS ---
SEATTLE_CATCHMENT_ENDPOINTS = [
    {
        "grade_level": "Elementary",
        "urls": [
            "https://gisdata.seattle.gov/server/rest/services/SPS/AttendanceAreas/MapServer/0/query",
            "https://services.arcgis.com/ZOyb2R4BAY3knLwq/arcgis/rest/services/Elementary_School_Attendance_Areas/FeatureServer/0/query"
        ],
        "name_fields": ["SPS_ES", "ES_ZONE", "SCHOOL", "ES_NAME", "NAME", "SPS_NAME"]
    },
    {
        "grade_level": "Middle",
        "urls": [
            "https://gisdata.seattle.gov/server/rest/services/SPS/AttendanceAreas/MapServer/1/query",
            "https://services.arcgis.com/ZOyb2R4BAY3knLwq/arcgis/rest/services/Middle_School_Attendance_Areas/FeatureServer/0/query"
        ],
        "name_fields": ["SPS_MS", "MS_ZONE", "SCHOOL", "MS_NAME", "NAME", "SPS_NAME"]
    },
    {
        "grade_level": "High",
        "urls": [
            "https://gisdata.seattle.gov/server/rest/services/SPS/AttendanceAreas/MapServer/2/query",
            "https://services.arcgis.com/ZOyb2R4BAY3knLwq/arcgis/rest/services/High_School_Attendance_Areas/FeatureServer/0/query"
        ],
        "name_fields": ["SPS_HS", "HS_ZONE", "SCHOOL", "HS_NAME", "NAME", "SPS_NAME"]
    }
]

BELLEVUE_CATCHMENT_ENDPOINTS = [
    {
        "grade_level": "Elementary",
        "urls": [
            "https://gis.bellevuewa.gov/arcgis/rest/services/Public/SchoolBoundaries/MapServer/0/query"
        ],
        "name_fields": ["NAME", "SCHOOL_NAME", "SCHNAME", "ATTENDANCE", "SCHOOL"]
    },
    {
        "grade_level": "Middle",
        "urls": [
            "https://gis.bellevuewa.gov/arcgis/rest/services/Public/SchoolBoundaries/MapServer/1/query"
        ],
        "name_fields": ["NAME", "SCHOOL_NAME", "SCHNAME", "ATTENDANCE", "SCHOOL"]
    },
    {
        "grade_level": "High",
        "urls": [
            "https://gis.bellevuewa.gov/arcgis/rest/services/Public/SchoolBoundaries/MapServer/2/query"
        ],
        "name_fields": ["NAME", "SCHOOL_NAME", "SCHNAME", "ATTENDANCE", "SCHOOL"]
    }
]

# --- TIER 2 MACRO DISTRICT BOUNDARY ENDPOINTS ---
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
    """Simplifies school and district names for robust string matching."""
    if not text:
        return ""
    s = text.lower().strip()
    s = re.sub(r"\b(hs|es|ms|elem|middle|high)\b", "", s)
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\b(school|district|no|1|63|public|elementary|middle|high|k8|k5|k12|senior)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()

def load_ospi_metadata():
    """Reads data/ospi_school_data.json to build lookup indexes for schools and districts."""
    print(f"📖 Reading school & district metadata from {OSPI_DATA_JSON}...")
    schools_by_code = {}
    schools_by_name = {}
    districts = {}

    if not os.path.exists(OSPI_DATA_JSON):
        print(f"  ⚠️ Warning: {OSPI_DATA_JSON} not found. Matching will rely solely on GIS feature properties.")
        return schools_by_code, schools_by_name, districts

    try:
        with open(OSPI_DATA_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)

        schools_list = data.get("schools", [])
        districts = data.get("districts", {})

        for s in schools_list:
            code = s.get("school_code")
            sname = s.get("school_name", "")
            dname = s.get("district_name", "")

            if code:
                schools_by_code[code] = s

            clean_sname = normalize_name(sname)
            clean_dname = normalize_name(dname)

            if clean_sname:
                schools_by_name[(clean_sname, clean_dname)] = s
                schools_by_name[(clean_sname, "any")] = s

        print(f"  ✓ Indexed {len(schools_by_code)} individual schools and {len(districts)} school districts.")
    except Exception as e:
        print(f"  ❌ Error reading ospi_school_data.json: {e}")

    return schools_by_code, schools_by_name, districts

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
    Queries an Esri ArcGIS REST endpoint using standard Esri JSON (f=json)
    and converts rings geometry directly into GeoJSON polygons.
    """
    params = {
        "where": "1=1",
        "outFields": "*",
        "outSR": "4326",
        "returnGeometry": "true",
        "f": "json"
    }

    try:
        resp = requests.get(url, headers=HTTP_HEADERS, params=params, timeout=25, verify=False)
        if resp.status_code == 200:
            data = resp.json()
            raw_features = data.get("features", [])
            converted_features = []

            for f in raw_features:
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
    except Exception as e:
        print(f"  ⚠️ Esri fetch exception on {url}: {e}")

    return []

def harvest_catchments(endpoints, district_target_name, schools_by_name):
    """Harvests Tier 1 catchment polygons for a specific school district."""
    catchments_map = {}
    target_dname_norm = normalize_name(district_target_name)

    for ep in endpoints:
        grade_level = ep["grade_level"]
        urls = ep["urls"]
        name_fields = ep["name_fields"]

        features = []
        for u in urls:
            features = fetch_gis_features(u)
            if features:
                break

        print(f"  • {district_target_name} [{grade_level}]: Ingested {len(features)} boundary polygons.")

        for feat in features:
            props = feat.get("properties", {})
            geom = feat.get("geometry", {})

            if not geom or "coordinates" not in geom:
                continue

            raw_name = extract_property(props, name_fields)
            if not raw_name:
                continue

            norm_gis_name = normalize_name(raw_name)
            matched_school = (
                schools_by_name.get((norm_gis_name, target_dname_norm)) or 
                schools_by_name.get((norm_gis_name, "any"))
            )

            # Fallback string containment matching
            if not matched_school:
                for (s_key, d_key), s_data in schools_by_name.items():
                    if d_key in [target_dname_norm, "any"]:
                        if norm_gis_name and (norm_gis_name in s_key or s_key in norm_gis_name):
                            matched_school = s_data
                            break

            if matched_school:
                scode = matched_school["school_code"]
                clean_geom = {
                    "type": geom.get("type", "Polygon"),
                    "coordinates": clean_coordinate_array(geom.get("coordinates", []), precision=5)
                }

                catchments_map[scode] = {
                    "school_code": scode,
                    "school_name": matched_school["school_name"],
                    "district_name": matched_school["district_name"],
                    "district_code": matched_school["district_code"],
                    "grade_level": grade_level,
                    "tier": "Tier 1 (Exact Neighborhood Catchment)",
                    "geometry": clean_geom
                }

    return catchments_map

def harvest_district_polygons(schools_by_name):
    """Harvests Tier 2/3 macro district perimeters from OSPI GIS."""
    print("\n📡 Harvesting State OSPI District Boundaries (Tier 2/3 Perimeters)...")
    raw_features = []

    for url in STATE_DISTRICT_ENDPOINTS:
        raw_features = fetch_gis_features(url)
        if raw_features:
            print(f"  ✓ Ingested {len(raw_features)} state district polygon features.")
            break

    districts_map = {}
    name_fields = ["District_Name", "NAME", "LEANAME", "DIST_NAME", "DISTRICT", "District"]
    county_fields = ["Counties", "COUNTY", "County_Name", "COUNTY_NAME"]

    for feat in raw_features:
        props = feat.get("properties", {})
        geom = feat.get("geometry", {})

        if not geom or "coordinates" not in geom:
            continue

        raw_name = extract_property(props, name_fields)
        raw_county = extract_property(props, county_fields)

        is_target_county = any(c in raw_county for c in ["King", "Snohomish"])
        if not is_target_county:
            continue

        norm_key = normalize_name(raw_name)
        matched_school = schools_by_name.get((norm_key, "any"))

        dcode = matched_school["district_code"] if matched_school else str(props.get("OBJECTID", ""))
        dname = matched_school["district_name"] if matched_school else raw_name

        if dcode:
            clean_geom = {
                "type": geom.get("type", "Polygon"),
                "coordinates": clean_coordinate_array(geom.get("coordinates", []), precision=5)
            }

            districts_map[dcode] = {
                "district_code": dcode,
                "district_name": dname,
                "county": raw_county,
                "state": "WA",
                "geometry": clean_geom
            }

    return districts_map

def main():
    print("==================================================")
    print("   OSPI HYBRID SCHOOL BOUNDARY HARVESTER (V2.4)   ")
    print("==================================================\n")

    os.makedirs(DATA_DIR, exist_ok=True)
    schools_by_code, schools_by_name, known_districts = load_ospi_metadata()

    # --- 1. HARVEST TIER 1 INDIVIDUAL SCHOOL CATCHMENTS ---
    print("\n📡 Ingesting Tier 1 Catchment Boundaries (Seattle & Bellevue)...")
    seattle_catchments = harvest_catchments(SEATTLE_CATCHMENT_ENDPOINTS, "Seattle School District No. 1", schools_by_name)
    bellevue_catchments = harvest_catchments(BELLEVUE_CATCHMENT_ENDPOINTS, "Bellevue School District", schools_by_name)

    all_school_catchments = {**seattle_catchments, **bellevue_catchments}
    print(f"  ✅ Successfully compiled {len(all_school_catchments)} Tier 1 school catchments.")

    # --- 2. HARVEST TIER 2/3 DISTRICT PERIMETERS ---
    district_boundaries = harvest_district_polygons(schools_by_name)
    print(f"  ✅ Successfully compiled {len(district_boundaries)} Tier 2 district perimeters.")

    # --- 3. CONSTRUCT MASTER HYBRID JSON ASSET ---
    master_output = {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "tier1_school_catchments_count": len(all_school_catchments),
            "tier2_district_boundaries_count": len(district_boundaries),
            "coordinate_system": "EPSG:4326 (WGS84)",
            "precision_meters": "~1.1m"
        },
        "school_catchments": all_school_catchments,
        "district_boundaries": district_boundaries,
        "district_lookup_urls": DISTRICT_LOOKUP_URLS
    }

    with open(OUTPUT_BOUNDARIES_JSON, "w", encoding="utf-8") as f:
        json.dump(master_output, f, indent=2, ensure_ascii=False)

    print(f"\n🎉 Boundary harvesting complete!")
    print(f"  • Compiled {len(all_school_catchments)} individual neighborhood school catchments.")
    print(f"  • Compiled {len(district_boundaries)} macro school district perimeters.")
    print(f"  • Indexing {len(DISTRICT_LOOKUP_URLS)} district boundary finder links.")
    print(f"  • Saved master spatial asset to: {OUTPUT_BOUNDARIES_JSON}")

if __name__ == "__main__":
    main()