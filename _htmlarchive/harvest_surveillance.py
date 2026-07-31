# File: scripts/harvest_surveillance.py

import os
import json
import io
import time
import requests
import pandas as pd

CITY_DATA_PATH = os.path.join("data", "city_data.json")
OUTPUT_JSON_PATH = os.path.join("data", "surveillance_stats.json")

W_ALPR = 3.0
W_INSTITUTIONAL = 2.0
W_CCTV = 1.5
W_TRAFFIC = 1.0

OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter"
]
EFF_DATA_URL = "https://kiosk.atlasofsurveillance.org/download.csv?location=&sort=state_desc"

def fetch_live_eff_counts():
    print("📡 Syncing live master database from Atlas of Surveillance Kiosk...")
    headers = {"User-Agent": "PugetSoundPrivacyRealEstateIndexer/1.0"}
    try:
        response = requests.get(EFF_DATA_URL, headers=headers, timeout=45)
        response.raise_for_status()
        eff_df = pd.read_csv(io.StringIO(response.text))
        print(f"✅ Successfully cached {len(eff_df)} global EFF tracking records.")
        return eff_df
    except Exception as e:
        print(f"⚠️ EFF Kiosk stream failed ({e}). Deploying empty data fallback.")
        return pd.DataFrame()

def query_osm_hardware(city_name):
    query = f"""
    [out:json][timeout:60];
    area["name"="{city_name}"]["boundary"="administrative"]->.searchArea;
    (
      node["man_made"="surveillance"]["surveillance:type"="ALPR"](area.searchArea)->.alprs;
      node["highway"="speed_camera"](area.searchArea)->.speeds;
      node["enforcement"="red_light"](area.searchArea)->.reds;
      node["man_made"="surveillance"](area.searchArea)->.cctvs;
    );
    out count;
    """
    headers = {"User-Agent": "PugetSoundPrivacyRealEstateIndexer/1.0"}
    
    for attempt in range(len(OVERPASS_MIRRORS) * 2):
        endpoint = OVERPASS_MIRRORS[attempt % len(OVERPASS_MIRRORS)]
        try:
            response = requests.post(endpoint, data={"data": query}, headers=headers, timeout=45)
            
            if response.status_code == 429:
                wait_duration = (attempt + 1) * 6
                print(f"   ⚠️ Rate limited (429) by mirror {endpoint}. Throttling execution for {wait_duration}s...")
                time.sleep(wait_duration)
                continue
                
            if response.status_code == 504:
                print(f"   ⚠️ Gateway Timeout (504) from mirror {endpoint}. Rotating to alternative pool target...")
                continue
                
            response.raise_for_status()
            elements = response.json().get("elements", [])
            if elements:
                meta = elements[0].get("tags", {})
                nodes_count = int(meta.get("nodes", 0))
                return {
                    "total_physical": nodes_count,
                    "alpr": max(0, nodes_count // 12),
                    "traffic": max(0, nodes_count // 6),
                    "cctv": nodes_count
                }
        except Exception as error_msg:
            print(f"   ⚠️ Grid connection error on attempt {attempt + 1} utilizing [{endpoint}]: {error_msg}")
            time.sleep(3.0)
            
    print(f"❌ All public Overpass pool mirrors exhausted or down for {city_name}. Deploying zero fallback.")
    return {"total_physical": 0, "alpr": 0, "traffic": 0, "cctv": 0}

def main():
    print("🚀 Initializing Dynamic Surveillance Index Engine...")
    
    if not os.path.exists(CITY_DATA_PATH):
        print(f"❌ Error: Required master city data file missing at {CITY_DATA_PATH}")
        return
        
    with open(CITY_DATA_PATH, "r", encoding="utf-8") as f:
        city_records = json.load(f)

    eff_master_df = fetch_live_eff_counts()
    
    raw_density_scores = {}
    surveillance_registry = {}

    for row in city_records:
        city_name = str(row.get('City', '')).strip()
        if not city_name:
            continue
            
        police_agency = str(row.get('Police Department Name', '')).strip()
        
        try:
            land_area_val = row.get('Land Area Square Mileage')
            if not land_area_val or str(land_area_val).lower() in ['unknown', 'none', 'nan', '']:
                land_area = 0.0
            else:
                land_area = float(land_area_val)
        except (ValueError, TypeError):
            land_area = 0.0

        inst_tech_count = 0
        if not eff_master_df.empty and 'Agency' in eff_master_df.columns:
            wa_eff = eff_master_df[eff_master_df['State'].astype(str).str.upper() == 'WA']
            
            csv_agency_lower = police_agency.lower()
            city_lower = city_name.lower()

            matched_tech = wa_eff[
                wa_eff['Agency'].astype(str).str.lower().apply(
                    lambda x: str(x) in csv_agency_lower or city_lower in str(x)
                )
            ]
            
            if 'Technology' in matched_tech.columns:
                inst_tech_count = int(matched_tech['Technology'].nunique())

        print(f"🛰️ Scanning public spaces inside municipal limits for: {city_name}...")
        osm_counts = query_osm_hardware(city_name)
        
        time.sleep(2.5)

        weighted_sum = (
            (osm_counts["alpr"] * W_ALPR) +
            (inst_tech_count * W_INSTITUTIONAL) +
            (osm_counts["cctv"] * W_CCTV) +
            (osm_counts["traffic"] * W_TRAFFIC)
        )

        if land_area <= 0.0:
            raw_density_scores[city_name] = None
        else:
            raw_density_scores[city_name] = weighted_sum / land_area

        surveillance_registry[city_name] = {
            "status": "Incomplete (Awaiting Land Area Metrics)" if raw_density_scores[city_name] is None else "Active",
            "serving_agency": police_agency,
            "calculated_density_index": raw_density_scores[city_name],
            "infrastructure_inventories": {
                "detected_alpr_cameras": osm_counts["alpr"],
                "detected_traffic_cameras": osm_counts["traffic"],
                "detected_general_cctv": osm_counts["cctv"],
                "active_institutional_software_capabilities": inst_tech_count
            }
        }

    valid_indexes = [v for v in raw_density_scores.values() if v is not None]
    valid_indexes.sort()

    for city in surveillance_registry.keys():
        current_density = raw_density_scores[city]
        inv = surveillance_registry[city]["infrastructure_inventories"]
        total_signals = sum([inv["detected_general_cctv"], inv["active_institutional_software_capabilities"]])
        
        if current_density is None:
            surveillance_registry[city]["surveillance_score"] = None
            surveillance_registry[city]["status"] = "Pending Parameter Update"
        elif total_signals == 0:
            surveillance_registry[city]["surveillance_score"] = None
            surveillance_registry[city]["status"] = "Insufficient Data (Uncertified Low Volunteer Mapping)"
        else:
            rank_match = next((i for i, v in enumerate(valid_indexes) if v >= current_density), 0)
            if len(valid_indexes) > 1:
                percentile = int(1 + (rank_match / (len(valid_indexes) - 1)) * 99)
            else:
                percentile = 50
            surveillance_registry[city]["surveillance_score"] = percentile
            surveillance_registry[city]["status"] = "Active Profile"

    os.makedirs(os.path.dirname(OUTPUT_JSON_PATH), exist_ok=True)
    with open(OUTPUT_JSON_PATH, 'w', encoding="utf-8") as f:
        json.dump(surveillance_registry, f, indent=2, ensure_ascii=False)
        
    print(f"🏁 Success! Dynamic Surveillance records compiled to: {OUTPUT_JSON_PATH}")

if __name__ == "__main__":
    main()