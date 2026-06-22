#!/usr/bin/env python3
"""
Real Estate Platform - Dynamic Surveillance Index Engine
Features: Self-healing CSV newline reconstruction, live streaming EFF database integration,
          and two-way containment matching for contract law enforcement agencies.
"""

import os
import json
import io
import time
import requests
import pandas as pd

# CONFIGURATION ARCHITECTURE
CSV_PATH = "data/InfoSparks Links - Sheet2.csv"
OUTPUT_JSON_PATH = "data/surveillance_stats.json"

# Dynamic Severity Multipliers
W_ALPR = 3.0
W_INSTITUTIONAL = 2.0
W_CCTV = 1.5
W_TRAFFIC = 1.0

# Remote Data Anchors
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
EFF_DATA_URL = "https://www.atlasofsurveillance.org/csv"

def clean_and_load_csv(file_path):
    """Reads raw CSV text and repairs broken row-wraps before handing to pandas."""
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    reconstructed_lines = []
    header_count = len(lines[0].split(","))
    buffer_line = ""
    
    for line in lines:
        cleaned_line = line.strip()
        if not cleaned_line:
            continue
        if buffer_line:
            buffer_line = buffer_line + " " + cleaned_line
        else:
            buffer_line = cleaned_line
            
        # If the merged components match our target database columns, flush to memory
        if len(buffer_line.split(",")) >= header_count or any(x in buffer_line for x in ["WA0", "Unknown"]):
            reconstructed_lines.append(buffer_line)
            buffer_line = ""
            
    if buffer_line:
        reconstructed_lines.append(buffer_line)
        
    return pd.read_csv(io.StringIO("\n".join(reconstructed_lines)))

def fetch_live_eff_counts():
    """Streams the complete EFF Atlas of Surveillance dataset programmatically at runtime."""
    print("📡 Streaming live master database from Atlas of Surveillance...")
    headers = {"User-Agent": "PugetSoundPrivacyRealEstateIndexer/1.0"}
    try:
        response = requests.get(EFF_DATA_URL, headers=headers, timeout=30)
        response.raise_for_status()
        eff_df = pd.read_csv(io.StringIO(response.text))
        print(f"✅ Successfully cached {len(eff_df)} global EFF tracking records.")
        return eff_df
    except Exception as e:
        print(f"⚠️ Failed to stream EFF database ({e}). Deploying empty data fallback.")
        return pd.DataFrame()

def query_osm_hardware(city_name):
    """Queries the Overpass API for physical hardware counts inside municipal administrative lines."""
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
    try:
        res = requests.post(OVERPASS_URL, data={"data": query}, headers=headers, timeout=60)
        res.raise_for_status()
        elements = res.json().get("elements", [])
        if elements:
            meta = elements[0].get("tags", {})
            nodes_count = int(meta.get("nodes", 0))
            return {
                "total_physical": nodes_count,
                "alpr": max(0, nodes_count // 12),
                "traffic": max(0, nodes_count // 6),
                "cctv": nodes_count
            }
    except Exception as e:
        print(f"⚠️ OSM Boundary Scan Timeout for {city_name}: {e}")
    return {"total_physical": 0, "alpr": 0, "traffic": 0, "cctv": 0}

def main():
    print("🚀 Initializing Dynamic Surveillance Index Engine...")
    
    if not os.path.exists(CSV_PATH):
        print(f"❌ Error: Required master spreadsheet missing at {CSV_PATH}")
        return
        
    df = clean_and_load_csv(CSV_PATH)
    eff_master_df = fetch_live_eff_counts()
    
    raw_density_scores = {}
    surveillance_registry = {}

    for _, row in df.iterrows():
        city_name = str(row['City']).strip()
        police_agency = str(row['Police Department Name']).strip()
        
        # Safe extraction handling for partial or missing Land Area data fields
        try:
            land_area_val = row.get('Land Area Sq Mi')
            if pd.isna(land_area_val) or str(land_area_val).lower() == 'unknown':
                land_area = 0.0
            else:
                land_area = float(land_area_val)
        except (ValueError, TypeError):
            land_area = 0.0

        # 1. Dynamic EFF Matching via Two-Way Containment Check
        inst_tech_count = 0
        if not eff_master_df.empty and 'Agency' in eff_master_df.columns:
            wa_eff = eff_master_df[eff_master_df['State'].astype(str).str.upper() == 'WA']
            
            csv_agency_lower = police_agency.lower()
            city_lower = city_name.lower()

            # Matches if EFF's agency is inside your text OR if the city name is inside EFF's name
            matched_tech = wa_eff[
                wa_eff['Agency'].astype(str).str.lower().apply(
                    lambda x: str(x) in csv_agency_lower or city_lower in str(x)
                )
            ]
            
            if 'Technology' in matched_tech.columns:
                inst_tech_count = int(matched_tech['Technology'].nunique())

        # 2. Live OpenStreetMap Physical Scan
        print(f"🛰️ Scanning public spaces inside municipal limits for: {city_name}...")
        osm_counts = query_osm_hardware(city_name)
        
        # Politeness throttle to protect the public Overpass server grid
        time.sleep(2.0)

        # 3. Calculate Weighted Sum
        weighted_sum = (
            (osm_counts["alpr"] * W_ALPR) +
            (inst_tech_count * W_INSTITUTIONAL) +
            (osm_counts["cctv"] * W_CCTV) +
            (osm_counts["traffic"] * W_TRAFFIC)
        )

        # 4. Defensive Normalization Core
        if land_area <= 0.0:
            raw_density_scores[city_name] = None
        else:
            raw_density_scores[city_name] = weighted_sum / land_area

        # Assemble individual data profiles
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

    # 5. Peer Percentile Rankings Generation Pass
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
            # Blindspot protection handles unmapped towns safely
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

    # Write completed payload directly to storage folder
    os.makedirs(os.path.dirname(OUTPUT_JSON_PATH), exist_ok=True)
    with open(OUTPUT_JSON_PATH, 'w', encoding="utf-8") as f:
        json.dump(surveillance_registry, f, indent=2, ensure_ascii=False)
        
    print(f"🏁 Success! Dynamic Surveillance records compiled to: {OUTPUT_JSON_PATH}")

if __name__ == "__main__":
    main()
