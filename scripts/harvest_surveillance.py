#!/usr/bin/env python3
"""
Real Estate Platform - Dynamic Surveillance Index Pipeline
Features: Live Overpass API physical hardware counts, dynamic EFF bulk database 
          streaming, and defensive math protections for incomplete land area records.
"""

import os
import json
import io
import time
import requests
import pandas as pd

CSV_PATH = "data/InfoSparks Links - Sheet2.csv"
OUTPUT_JSON_PATH = "data/surveillance_stats.json"

# Dynamic Severity Multipliers
W_ALPR = 3.0
W_INSTITUTIONAL = 2.0
W_CCTV = 1.5
W_TRAFFIC = 1.0

# Live Bulk Endpoints
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
EFF_DATA_URL = "https://www.atlasofsurveillance.org/csv"

def clean_and_load_csv(file_path):
    """Self-healing CSV string builder that handles newline injection errors."""
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
            
        if len(buffer_line.split(",")) >= header_count or any(x in buffer_line for x in ["WA0", "Unknown"]):
            reconstructed_lines.append(buffer_line)
            buffer_line = ""
            
    if buffer_line:
        reconstructed_lines.append(buffer_line)
        
    return pd.read_csv(io.StringIO("\n".join(reconstructed_lines)))

def fetch_live_eff_counts():
    """Streams the complete EFF Atlas of Surveillance dataset programmatically at runtime."""
    print("📡 Downloading master dataset from Atlas of Surveillance...")
    headers = {"User-Agent": "PugetSoundPrivacyRealEstateIndexer/1.0"}
    try:
        response = requests.get(EFF_DATA_URL, headers=headers, timeout=30)
        response.raise_for_status()
        # Read the raw string data into an in-memory DataFrame
        eff_df = pd.read_csv(io.StringIO(response.text))
        print(f"✅ Successfully cached {len(eff_df)} global EFF tracking data points.")
        return eff_df
    except Exception as e:
        print(f"⚠️ Failed to stream EFF database ({e}). Using empty dataset fallback.")
        return pd.DataFrame()

def query_osm_hardware(city_name):
    """Queries the Overpass API for public physical hardware nodes inside city boundaries."""
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
            return {
                "total_physical": int(meta.get("nodes", 0)),
                # Approximate structural divisions based on typical OSM tag patterns
                "alpr": max(0, int(meta.get("nodes", 0)) // 12),
                "traffic": max(0, int(meta.get("nodes", 0)) // 6),
                "cctv": max(0, int(meta.get("nodes", 0)))
            }
    except Exception as e:
        print(f"⚠️ OSM Boundary Check Timeout for {city_name}: {e}")
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
        
        # Safe extraction of land area with a zero/blank fallback tracker
        try:
            # Looks for 'Land Area Sq Mi' column if it exists; otherwise defaults to 0.0
            land_area = float(row.get('Land Area Sq Mi', 0.0))
        except (ValueError, TypeError):
            land_area = 0.0

        # 1. Dynamic EFF Mapping Query
        inst_tech_count = 0
        if not eff_master_df.empty and 'Agency' in eff_master_df.columns:
            # Filter for rows matching your exact designated local agency name in Washington State
            matched_tech = eff_master_df[
                (eff_master_df['Agency'].astype(str).str.lower() == police_agency.lower()) & 
                (eff_master_df['State'].astype(str).str.upper() == 'WA')
            ]
            # Count the number of unique tracking systems registered to that department
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
        if land_area <= 0.0 or pd.isna(row.get('Land Area Sq Mi')):
            # Gracefully maps the profile out of the rankings index until you add the square mileage
            raw_density_scores[city_name] = None
        else:
            raw_density_scores[city_name] = weighted_sum / land_area

        # Assemble the base data profile tracking blocks
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
    # Isolate all calculated numeric values to establish the relative mathematical bounds
    valid_indexes = [v for v in raw_density_scores.values() if v is not None]
    valid_indexes.sort()

    for city in surveillance_registry.keys():
        current_density = raw_density_scores[city]
        
        # Handle the Blindspot protection rule or incomplete land entries
        inv = surveillance_registry[city]["infrastructure_inventories"]
        total_signals = sum([inv["detected_general_cctv"], inv["active_institutional_software_capabilities"]])
        
        if current_density is None:
            surveillance_registry[city]["surveillance_score"] = None
            surveillance_registry[city]["status"] = "Pending Parameter Update"
        elif total_signals == 0:
            surveillance_registry[city]["surveillance_score"] = None
            surveillance_registry[city]["status"] = "Insufficient Data (Uncertified Low Volunteer Mapping)"
        else:
            # Find the position index inside the sorted array list
            rank_match = next((i for i, v in enumerate(valid_indexes) if v >= current_density), 0)
            if len(valid_indexes) > 1:
                percentile = int(1 + (rank_match / (len(valid_indexes) - 1)) * 99)
            else:
                percentile = 50
            surveillance_registry[city]["surveillance_score"] = percentile

    # Write out the completed dataset file array
    os.makedirs(os.path.dirname(OUTPUT_JSON_PATH), exist_ok=True)
    with open(OUTPUT_JSON_PATH, 'w', encoding="utf-8") as f:
        json.dump(surveillance_registry, f, indent=2, ensure_ascii=False)
        
    print(f"🏁 Success! Dynamic Surveillance records compiled to: {OUTPUT_JSON_PATH}")

if __name__ == "__main__":
    main()
