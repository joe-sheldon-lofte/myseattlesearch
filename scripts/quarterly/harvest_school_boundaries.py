# File: scripts/quarterly/harvest_school_boundaries.py

import os
import json
import urllib3
import requests
from datetime import datetime

# Suppress SSL warnings for public REST endpoints
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Directory Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
OSPI_DATA_JSON = os.path.join(DATA_DIR, "ospi_school_data.json")
OUTPUT_GEOJSON = os.path.join(DATA_DIR, "school_boundaries.json")

# Primary and Backup GIS REST Endpoints for WA School District Boundaries
GIS_ENDPOINTS = [
    {
        "name": "OSPI Official State Boundary Service 2025",
        "url": "https://services8.arcgis.com/rGGrs6HCnw87OFOT/arcgis/rest/services/OSPISchoolDistricts_2025/FeatureServer/0/query",
        "name_field": "District_Name",
        "county_field": "Counties"
    },
    {
        "name": "OSPI Public GIS Feature Server (Fallback)",
        "url": "https://gis.ospi.k12.wa.gov/arcgis/rest/services/Public/OSPISchoolDistricts/FeatureServer/0/query",
        "name_field": "District_Name",
        "county_field": "Counties"
    }
]

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

def load_known_districts():
    """Reads data/ospi_school_data.json to build a reference map of district names to OSPI IDs."""
    print(f"📖 Reading existing district IDs from {OSPI_DATA_JSON}...")
    known_districts = {}

    if not os.path.exists(OSPI_DATA_JSON):
        print(f"  ⚠️ Warning: {OSPI_DATA_JSON} not found. District mapping will rely solely on GIS metadata.")
        return known_districts

    try:
        with open(OSPI_DATA_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)

        districts = data.get("districts", {})
        for d_name, d_info in districts.items():
            code = str(d_info.get("district_code", "")).strip()
            county = d_info.get("county", "")
            known_districts[d_name.lower().strip()] = {
                "district_name": d_name,
                "district_code": code,
                "county": county
            }

        print(f"  ✓ Successfully indexed {len(known_districts)} school districts from ospi_school_data.json.")
    except Exception as e:
        print(f"  ❌ Error reading ospi_school_data.json: {e}")

    return known_districts

def clean_coordinate_array(coords, precision=5):
    """
    Recursively rounds latitude/longitude pairs to a fixed precision (5 decimal places ~ 1.1m precision).
    Preserves complete topology without modifying line shapes.
    """
    if not coords:
        return coords
    if isinstance(coords[0], (int, float)):
        return [round(float(c), precision) for c in coords[:2]]
    return [clean_coordinate_array(sub, precision) for sub in coords]

def fetch_gis_geojson(endpoint_meta):
    """Queries an ArcGIS FeatureServer endpoint and returns GeoJSON features."""
    url = endpoint_meta["url"]
    print(f"📡 Querying boundary endpoint: {endpoint_meta['name']}...")

    params = {
        "where": "1=1",
        "outFields": "*",
        "outSR": "4326",  # WGS84 Spatial Reference
        "f": "geojson"
    }

    try:
        resp = requests.get(url, headers=HTTP_HEADERS, params=params, timeout=30, verify=False)
        if resp.status_code == 200:
            data = resp.json()
            features = data.get("features", [])
            print(f"  ✓ Retrieved {len(features)} total state polygon features.")
            return features
        else:
            print(f"  ⚠️ Endpoint returned status code {resp.status_code}.")
    except Exception as e:
        print(f"  ❌ Connection exception on {url}: {e}")

    return []

def main():
    print("==================================================")
    print("   OSPI SCHOOL BOUNDARY HARVESTER (V1.0)          ")
    print("==================================================\n")

    os.makedirs(DATA_DIR, exist_ok=True)
    known_districts = load_known_districts()

    raw_features = []
    active_endpoint = None

    for ep in GIS_ENDPOINTS:
        raw_features = fetch_gis_geojson(ep)
        if raw_features:
            active_endpoint = ep
            break

    if not raw_features:
        print("❌ Failed to retrieve polygon boundary data from all configured GIS endpoints. Exiting.")
        return

    name_field = active_endpoint["name_field"]
    county_field = active_endpoint["county_field"]

    compiled_features = []
    matched_count = 0

    print("\n🚀 Filtering & Optimizing Geometries for King & Snohomish Counties...")

    for feat in raw_features:
        props = feat.get("properties", {})
        geom = feat.get("geometry", {})

        if not geom or "coordinates" not in geom:
            continue

        raw_name = str(props.get(name_field, "")).strip()
        raw_county = str(props.get(county_field, "")).strip()

        # Check if feature belongs to King or Snohomish county
        is_target_county = any(c in raw_county for c in ["King", "Snohomish"])
        
        # Check against known district names
        normalized_key = raw_name.lower().strip()
        matched_info = known_districts.get(normalized_key)

        if not matched_info:
            # Try appending 'School District' if omitted
            if "district" not in normalized_key:
                matched_info = known_districts.get(f"{normalized_key} school district")

        if is_target_county or matched_info:
            district_code = matched_info["district_code"] if matched_info else str(props.get("OBJECTID", ""))
            official_name = matched_info["district_name"] if matched_info else raw_name
            county_name = matched_info["county"] if matched_info else raw_county

            # Clean and round coordinates to 5 decimal places (~1.1m ground precision)
            clean_geometry = {
                "type": geom.get("type", "Polygon"),
                "coordinates": clean_coordinate_array(geom.get("coordinates", []), precision=5)
            }

            feature_entry = {
                "type": "Feature",
                "id": district_code,
                "properties": {
                    "district_code": district_code,
                    "district_name": official_name,
                    "county": county_name,
                    "state": "WA"
                },
                "geometry": clean_geometry
            }

            compiled_features.append(feature_entry)
            if matched_info:
                matched_count += 1

    compiled_features.sort(key=lambda f: (f["properties"]["county"], f["properties"]["district_name"]))

    geojson_output = {
        "type": "FeatureCollection",
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "total_districts": len(compiled_features),
            "matched_ospi_districts": matched_count,
            "coordinate_system": "EPSG:4326 (WGS84)",
            "precision_meters": "~1.1m"
        },
        "features": compiled_features
    }

    with open(OUTPUT_GEOJSON, "w", encoding="utf-8") as f:
        json.dump(geojson_output, f, indent=2, ensure_ascii=False)

    print(f"\n🎉 Boundary harvesting complete!")
    print(f"  • Processed {len(compiled_features)} boundary polygon features.")
    print(f"  • Matched {matched_count} districts with ospi_school_data.json keys.")
    print(f"  • Saved GeoJSON spatial dataset to: {OUTPUT_GEOJSON}")

if __name__ == "__main__":
    main()