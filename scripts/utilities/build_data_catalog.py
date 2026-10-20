# File: scripts/utilities/build_data_catalog.py

import os
import csv
import json
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_CSV = os.path.join(BASE_DIR, "DataPointIndex_Master.csv")

def infer_data_type(val):
    """Infers a clean, human-readable data type from native Python JSON objects."""
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "boolean"
    if isinstance(val, int):
        return "number (int)"
    if isinstance(val, float):
        return "number (float)"
    if isinstance(val, str):
        v = val.strip().lower()
        if v.startswith("http://") or v.startswith("https://"):
            return "string (URL)"
        return "string"
    if isinstance(val, list):
        if val and isinstance(val[0], dict):
            return "array of objects"
        if val:
            return f"array of {infer_data_type(val[0])}s"
        return "array"
    if isinstance(val, dict):
        return "object"
    return type(val).__name__

def format_sample_value(val):
    """Formats live sample values cleanly for safe, single-line CSV presentation."""
    if val is None:
        return ""
    if isinstance(val, (dict, list)):
        serialized = json.dumps(val, ensure_ascii=False)
        return serialized[:80] + ("..." if len(serialized) > 80 else "")
    cleaned = str(val).replace("\r", " ").replace("\n", " ").strip()
    return cleaned[:80] + ("..." if len(cleaned) > 80 else "")

def pick_primary_identifier(keys):
    """
    Selects the most specific primary key or context identifier for record queries.
    building_id and condo_id precede city to prevent complex rosters collapsing to municipal scope.
    """
    candidates = [
        "building_id", "condo_id", "school_code", "district_code", "mls_number", 
        "StepID", "FAQID", "QuestionID", "Review ID", "Program Name", 
        "Facility", "game_id", "station_id", "site_name", "timestamp", "id", "slug", 
        "Date", "City", "city", "CityName", "category", "trigger_key", "name"
    ]
    for candidate in candidates:
        if candidate in keys:
            return candidate
    return list(keys)[0] if keys else "index"

def is_city_key_pattern(key_string):
    """Identifies if a key string matches regional municipal naming conventions."""
    known = [
        "edmonds", "lynnwood", "seattle", "bellevue", "algona", "arlington", "auburn",
        "bothell", "brier", "burien", "everett", "renton", "kirkland", "redmond",
        "shoreline", "mukilteo", "marysville", "lake-stevens", "snohomish", "woodinville"
    ]
    return any(c in str(key_string).lower() for c in known)

def find_first_non_null(records, key):
    """Scans records up to index 100 to extract non-null values for sparse field typing."""
    for item in records[:100]:
        if isinstance(item, dict) and item.get(key) is not None:
            return item[key]
    return None

def catalog_single_file(filename, filepath):
    """
    Parses a JSON file, classifies it into its architectural data pattern,
    and returns an expanded, fully terminal list of coordinate rows.
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return None, f"JSON decode error: {e}"

    rows = []

    # --------------------------------------------------------------------------
    # PATTERN 1: GeoJSON FeatureCollection
    # --------------------------------------------------------------------------
    if isinstance(data, dict) and data.get("type") == "FeatureCollection" and "features" in data:
        features = data.get("features", [])
        if not features or not isinstance(features, list) or not isinstance(features[0], dict):
            return rows, "GeoJSON FeatureCollection (Empty Features Array)"
        
        sample_props = features[0].get("properties", {})
        id_field = pick_primary_identifier(sample_props.keys()) if sample_props else "slug"
        
        for k in sorted(sample_props.keys()):
            val = sample_props.get(k)
            rows.append({
                "File Name": filename,
                "Section": "properties",
                "Data Point Key": k,
                "Access Pattern": "GeoJSON Feature",
                "Match Identifier": f"properties.{id_field} == {{context.{id_field}}}",
                "Universal Path": f"$.features[?(@.properties.{id_field} == '{{{id_field}}}')].properties['{k}']",
                "Data Type": infer_data_type(val),
                "Sample Value": format_sample_value(val),
                "Notes": ""
            })
        return rows, None

    # --------------------------------------------------------------------------
    # PATTERN 2: Flat Record Table (List of Record Dicts)
    # --------------------------------------------------------------------------
    if isinstance(data, list):
        if not data:
            return rows, "Flat Record Array (Empty)"
        if not isinstance(data[0], dict):
            return None, "Array of non-dictionary primitive elements"

        all_keys = []
        for item in data[:50]:
            if isinstance(item, dict):
                for k in item.keys():
                    if k not in all_keys:
                        all_keys.append(k)

        id_field = pick_primary_identifier(all_keys)

        for k in all_keys:
            sample_val = find_first_non_null(data, k)

            # Deep unpack: Record-level nested dictionary (e.g. nextGame)
            if isinstance(sample_val, dict) and sample_val and all(not isinstance(sub_v, (dict, list)) for sub_v in sample_val.values()):
                for sub_k in sorted(sample_val.keys()):
                    sub_v = sample_val[sub_k]
                    rows.append({
                        "File Name": filename,
                        "Section": "root",
                        "Data Point Key": f"{k}.{sub_k}",
                        "Access Pattern": "Record Nested Property",
                        "Match Identifier": f"{id_field} == {{context.{id_field}}}",
                        "Universal Path": f"$[?(@.{id_field} == '{{{id_field}}}')].{k}['{sub_k}']",
                        "Data Type": infer_data_type(sub_v),
                        "Sample Value": format_sample_value(sub_v),
                        "Notes": ""
                    })

            # Deep unpack: Record-level nested array of objects (e.g. recentGames)
            elif isinstance(sample_val, list) and sample_val and isinstance(sample_val[0], dict):
                sub_rec_keys = set()
                for item in sample_val[:25]:
                    if isinstance(item, dict):
                        sub_rec_keys.update(item.keys())
                sub_id = pick_primary_identifier(sub_rec_keys)
                for sub_k in sorted(list(sub_rec_keys)):
                    sub_v = next((item[sub_k] for item in sample_val if isinstance(item, dict) and item.get(sub_k) is not None), None)
                    rows.append({
                        "File Name": filename,
                        "Section": "root",
                        "Data Point Key": f"{k}[].{sub_k}",
                        "Access Pattern": "Record Nested Array Match",
                        "Match Identifier": f"{id_field} == {{context.{id_field}}} -> {sub_id} == {{context.{sub_id}}}",
                        "Universal Path": f"$[?(@.{id_field} == '{{{id_field}}}')].{k}[?(@.{sub_id} == '{{{sub_id}}}')]['{sub_k}']",
                        "Data Type": infer_data_type(sub_v),
                        "Sample Value": format_sample_value(sub_v),
                        "Notes": ""
                    })

            # Standard Record scalar
            else:
                rows.append({
                    "File Name": filename,
                    "Section": "root",
                    "Data Point Key": k,
                    "Access Pattern": "Record Match",
                    "Match Identifier": f"{id_field} == {{context.{id_field}}}",
                    "Universal Path": f"$[?(@.{id_field} == '{{{id_field}}}')]['{k}']",
                    "Data Type": infer_data_type(sample_val),
                    "Sample Value": format_sample_value(sample_val),
                    "Notes": ""
                })
        return rows, None

    # --------------------------------------------------------------------------
    # PATTERNS 3, 4, 5: Dictionary Structures
    # --------------------------------------------------------------------------
    if isinstance(data, dict):
        if not data:
            return rows, "Dictionary (Empty)"

        # Special Case A: H3 Hex Hash Dictionary (e.g. h3_broadband.json)
        sample_keys = list(data.keys())[:10]
        if all(re.match(r'^[0-9a-f]{15}$', str(k).lower()) for k in sample_keys) or "h3" in filename.lower():
            sample_val = next(iter(data.values()))
            rows.append({
                "File Name": filename,
                "Section": "root",
                "Data Point Key": "broadband_providers" if "broadband" in filename else "data",
                "Access Pattern": "Keyed Map Array",
                "Match Identifier": "[h3_hex_id]",
                "Universal Path": "$['{h3_hex_id}'][]",
                "Data Type": infer_data_type(sample_val),
                "Sample Value": format_sample_value(sample_val),
                "Notes": ""
            })
            return rows, None

        # Special Case B: Keyed Map of Arrays (e.g. transit_radar_history.json)
        if len(data) >= 2 and all(isinstance(v, list) for v in data.values()):
            entity_label = "city_slug" if any(is_city_key_pattern(k) for k in sample_keys) else "entity_key"
            list_keys = []
            sample_item = None
            for entity_list in list(data.values())[:10]:
                if isinstance(entity_list, list) and entity_list:
                    for rec in entity_list[:10]:
                        if isinstance(rec, dict):
                            for k in rec.keys():
                                if k not in list_keys:
                                    list_keys.append(k)
                            if sample_item is None:
                                sample_item = rec
            if list_keys:
                id_field = pick_primary_identifier(list_keys)
                for k in sorted(list_keys):
                    sample_val = sample_item.get(k) if sample_item else None
                    rows.append({
                        "File Name": filename,
                        "Section": "root",
                        "Data Point Key": k,
                        "Access Pattern": "Keyed Map Record Match",
                        "Match Identifier": f"[{entity_label}] -> {id_field} == {{context.{id_field}}}",
                        "Universal Path": f"$['{{{entity_label}}}'][?(@.{id_field} == '{{{id_field}}}')]['{k}']",
                        "Data Type": infer_data_type(sample_val),
                        "Sample Value": format_sample_value(sample_val),
                        "Notes": ""
                    })
                return rows, None

        # Special Case C: Flat Singleton (all values primitives, e.g. stats.json)
        all_primitives = all(not isinstance(v, (dict, list)) for v in data.values())
        if all_primitives:
            for k in sorted(data.keys()):
                v = data[k]
                rows.append({
                    "File Name": filename,
                    "Section": "root",
                    "Data Point Key": k,
                    "Access Pattern": "Direct Property",
                    "Match Identifier": "Global (No Match Needed)",
                    "Universal Path": f"$['{k}']",
                    "Data Type": infer_data_type(v),
                    "Sample Value": format_sample_value(v),
                    "Notes": ""
                })
            return rows, None

        # Check for Keyed Entity Map or Partitioned Compound Bundle (e.g. city_weather.json, city_amenities.json)
        dict_keys = [k for k, v in data.items() if isinstance(v, dict)]
        other_keys = [k for k in data.keys() if k not in dict_keys]

        is_uniform_entity_map = False
        if len(dict_keys) >= 2:
            sub_key_sets = [set(data[k].keys()) for k in dict_keys[:10]]
            union_keys = set.union(*sub_key_sets)
            intersection_keys = set.intersection(*sub_key_sets)
            if union_keys and (len(intersection_keys) / len(union_keys)) >= 0.35:
                is_uniform_entity_map = True

        if is_uniform_entity_map:
            entity_label = "city_slug" if any(is_city_key_pattern(k) for k in dict_keys[:10]) else "entity_key"
            entity_keys_union = set()
            for k in dict_keys:
                entity_keys_union.update(data[k].keys())

            for k in sorted(list(entity_keys_union)):
                sample_val = None
                for d in dict_keys:
                    if k in data[d] and data[d][k] is not None:
                        sample_val = data[d][k]
                        break

                # Sub-property is a dictionary of primitive counters (e.g. city_amenities.json -> amenities)
                if isinstance(sample_val, dict) and sample_val and all(not isinstance(sub_v, (dict, list)) for sub_v in sample_val.values()):
                    for sub_k in sorted(sample_val.keys()):
                        sub_v = sample_val[sub_k]
                        rows.append({
                            "File Name": filename,
                            "Section": k,
                            "Data Point Key": f"{k}.{sub_k}",
                            "Access Pattern": "Keyed Map Nested Property",
                            "Match Identifier": f"[{entity_label}]",
                            "Universal Path": f"$['{{{entity_label}}}'].{k}['{sub_k}']",
                            "Data Type": infer_data_type(sub_v),
                            "Sample Value": format_sample_value(sub_v),
                            "Notes": ""
                        })

                # Sub-property is parallel forecast metric arrays (e.g. city_weather.json -> forecast_7_day)
                elif isinstance(sample_val, dict) and sample_val and all(isinstance(sub_v, list) and (not sub_v or not isinstance(sub_v[0], (dict, list))) for sub_v in sample_val.values()):
                    for sub_k in sorted(sample_val.keys()):
                        sub_list = sample_val[sub_k]
                        sub_item = sub_list[0] if sub_list else None
                        item_type = infer_data_type(sub_item)
                        data_type = f"array of {item_type}s" if item_type != "null" else "array"
                        rows.append({
                            "File Name": filename,
                            "Section": k,
                            "Data Point Key": f"{k}.{sub_k}[]",
                            "Access Pattern": "Keyed Map Metric Series",
                            "Match Identifier": f"[{entity_label}]",
                            "Universal Path": f"$['{{{entity_label}}}'].{k}['{sub_k}'][]",
                            "Data Type": data_type,
                            "Sample Value": format_sample_value(sub_list),
                            "Notes": ""
                        })

                # Sub-property is a dictionary containing category arrays (e.g. city_businesses.json -> categories)
                elif isinstance(sample_val, dict) and sample_val and any(isinstance(sub_v, list) for sub_v in sample_val.values()):
                    cat_item_keys = set()
                    sample_item = None
                    for cat_list in sample_val.values():
                        if isinstance(cat_list, list) and cat_list and isinstance(cat_list[0], dict):
                            cat_item_keys.update(cat_list[0].keys())
                            if sample_item is None:
                                sample_item = cat_list[0]
                    if cat_item_keys:
                        id_f = pick_primary_identifier(cat_item_keys)
                        for rec_k in sorted(list(cat_item_keys)):
                            rec_v = sample_item.get(rec_k) if sample_item else None
                            rows.append({
                                "File Name": filename,
                                "Section": k,
                                "Data Point Key": f"{k}.{{category}}[].{rec_k}",
                                "Access Pattern": "Keyed Map Nested Array Match",
                                "Match Identifier": f"[{entity_label}] -> [category] -> {id_f} == {{context.{id_f}}}",
                                "Universal Path": f"$['{{{entity_label}}}'].{k}['{{category}}'][?(@.{id_f} == '{{{id_f}}}')]['{rec_k}']",
                                "Data Type": infer_data_type(rec_v),
                                "Sample Value": format_sample_value(rec_v),
                                "Notes": ""
                            })
                    else:
                        rows.append({
                            "File Name": filename,
                            "Section": "root",
                            "Data Point Key": k,
                            "Access Pattern": "Keyed Map",
                            "Match Identifier": f"[{entity_label}]",
                            "Universal Path": f"$['{{{entity_label}}}']['{k}']",
                            "Data Type": infer_data_type(sample_val),
                            "Sample Value": format_sample_value(sample_val),
                            "Notes": ""
                        })

                # Standard keyed map property
                else:
                    rows.append({
                        "File Name": filename,
                        "Section": "root",
                        "Data Point Key": k,
                        "Access Pattern": "Keyed Map",
                        "Match Identifier": f"[{entity_label}]",
                        "Universal Path": f"$['{{{entity_label}}}']['{k}']",
                        "Data Type": infer_data_type(sample_val),
                        "Sample Value": format_sample_value(sample_val),
                        "Notes": ""
                    })

            # Process standalone sections inside compound files (e.g. _regional_water_gauges in city_weather.json)
            for sec_name in other_keys:
                sec_val = data[sec_name]
                if isinstance(sec_val, list) and sec_val and isinstance(sec_val[0], dict):
                    sec_keys = []
                    for item in sec_val[:25]:
                        if isinstance(item, dict):
                            for sk in item.keys():
                                if sk not in sec_keys:
                                    sec_keys.append(sk)
                    id_field = pick_primary_identifier(sec_keys)
                    for sk in sorted(sec_keys):
                        sample_val = next((item[sk] for item in sec_val if isinstance(item, dict) and item.get(sk) is not None), None)
                        rows.append({
                            "File Name": filename,
                            "Section": sec_name,
                            "Data Point Key": sk,
                            "Access Pattern": "Section Array Match",
                            "Match Identifier": f"{id_field} == {{context.{id_field}}}",
                            "Universal Path": f"$.{sec_name}[?(@.{id_field} == '{{{id_field}}}')]['{sk}']",
                            "Data Type": infer_data_type(sample_val),
                            "Sample Value": format_sample_value(sample_val),
                            "Notes": ""
                        })
                else:
                    rows.append({
                        "File Name": filename,
                        "Section": sec_name,
                        "Data Point Key": sec_name,
                        "Access Pattern": "Direct Property",
                        "Match Identifier": "Global (No Match Needed)",
                        "Universal Path": f"$.{sec_name}",
                        "Data Type": infer_data_type(sec_val),
                        "Sample Value": format_sample_value(sec_val),
                        "Notes": ""
                    })

            return rows, None

        # Standard Multi-Section Compound Bundle (e.g. ospi_school_data.json, infosparks_stats.json, redfin_migration.json, sports_data.json)
        for sec_name, sec_val in data.items():
            
            # Sub-Section A: Array of Records
            if isinstance(sec_val, list):
                if not sec_val:
                    continue
                if isinstance(sec_val[0], dict):
                    sec_keys = []
                    for item in sec_val[:50]:
                        if isinstance(item, dict):
                            for k in item.keys():
                                if k not in sec_keys:
                                    sec_keys.append(k)
                    id_field = pick_primary_identifier(sec_keys)
                    
                    for k in sorted(sec_keys):
                        sample_val = find_first_non_null(sec_val, k)

                        # Deep unpack: Section-level nested dictionary (e.g. sports_data.json -> nextGame)
                        if isinstance(sample_val, dict) and sample_val and all(not isinstance(sub_v, (dict, list)) for sub_v in sample_val.values()):
                            for sub_k in sorted(sample_val.keys()):
                                sub_v = sample_val[sub_k]
                                rows.append({
                                    "File Name": filename,
                                    "Section": sec_name,
                                    "Data Point Key": f"{k}.{sub_k}",
                                    "Access Pattern": "Section Array Nested Property",
                                    "Match Identifier": f"{id_field} == {{context.{id_field}}}",
                                    "Universal Path": f"$.{sec_name}[?(@.{id_field} == '{{{id_field}}}')].{k}['{sub_k}']",
                                    "Data Type": infer_data_type(sub_v),
                                    "Sample Value": format_sample_value(sub_v),
                                    "Notes": ""
                                })

                        # Deep unpack: Section-level nested array of objects (e.g. sports_data.json -> recentGames)
                        elif isinstance(sample_val, list) and sample_val and isinstance(sample_val[0], dict):
                            sub_rec_keys = set()
                            for item in sample_val[:25]:
                                if isinstance(item, dict):
                                    sub_rec_keys.update(item.keys())
                            sub_id = pick_primary_identifier(sub_rec_keys)
                            for sub_k in sorted(list(sub_rec_keys)):
                                sub_v = next((item[sub_k] for item in sample_val if isinstance(item, dict) and item.get(sub_k) is not None), None)
                                rows.append({
                                    "File Name": filename,
                                    "Section": sec_name,
                                    "Data Point Key": f"{k}[].{sub_k}",
                                    "Access Pattern": "Section Nested Array Match",
                                    "Match Identifier": f"{id_field} == {{context.{id_field}}} -> {sub_id} == {{context.{sub_id}}}",
                                    "Universal Path": f"$.{sec_name}[?(@.{id_field} == '{{{id_field}}}')].{k}[?(@.{sub_id} == '{{{sub_id}}}')]['{sub_k}']",
                                    "Data Type": infer_data_type(sub_v),
                                    "Sample Value": format_sample_value(sub_v),
                                    "Notes": ""
                                })

                        # Standard section record scalar
                        else:
                            rows.append({
                                "File Name": filename,
                                "Section": sec_name,
                                "Data Point Key": k,
                                "Access Pattern": "Section Array Match",
                                "Match Identifier": f"{id_field} == {{context.{id_field}}}",
                                "Universal Path": f"$.{sec_name}[?(@.{id_field} == '{{{id_field}}}')]['{k}']",
                                "Data Type": infer_data_type(sample_val),
                                "Sample Value": format_sample_value(sample_val),
                                "Notes": ""
                            })
                else:
                    rows.append({
                        "File Name": filename,
                        "Section": sec_name,
                        "Data Point Key": sec_name,
                        "Access Pattern": "Section Primitive Array",
                        "Match Identifier": "Index Loop",
                        "Universal Path": f"$.{sec_name}[]",
                        "Data Type": f"array of {infer_data_type(sec_val[0])}s",
                        "Sample Value": format_sample_value(sec_val[0]),
                        "Notes": ""
                    })

            # Sub-Section B: Keyed Sub-Map or Sub-Object
            elif isinstance(sec_val, dict):
                if not sec_val:
                    continue

                # Special Case: redfin_migration.json -> data (containing latest_period and metros)
                if sec_name == "data" and "metros" in sec_val and isinstance(sec_val.get("metros"), dict):
                    if "latest_period" in sec_val:
                        rows.append({
                            "File Name": filename,
                            "Section": "data",
                            "Data Point Key": "latest_period",
                            "Access Pattern": "Section Direct Property",
                            "Match Identifier": "Global (No Match Needed)",
                            "Universal Path": "$.data['latest_period']",
                            "Data Type": infer_data_type(sec_val["latest_period"]),
                            "Sample Value": format_sample_value(sec_val["latest_period"]),
                            "Notes": ""
                        })
                    metros_dict = sec_val.get("metros", {})
                    if metros_dict:
                        for dir_k in ["top_inflow", "top_outflow"]:
                            dir_list = next((m[dir_k] for m in metros_dict.values() if isinstance(m, dict) and m.get(dir_k)), [])
                            if dir_list and isinstance(dir_list[0], dict):
                                rec_keys = list(dir_list[0].keys())
                                id_col = "ORIGIN REGION NAME" if "ORIGIN REGION NAME" in rec_keys else ("DESTINATION REGION NAME" if "DESTINATION REGION NAME" in rec_keys else rec_keys[0])
                                for col_k in sorted(rec_keys):
                                    sample_v = dir_list[0].get(col_k)
                                    rows.append({
                                        "File Name": filename,
                                        "Section": f"data.metros.{dir_k}",
                                        "Data Point Key": f"{dir_k}[].{col_k}",
                                        "Access Pattern": "Section Keyed Map Record Match",
                                        "Match Identifier": f"[metro_name] -> {id_col} == {{context.{id_col}}}",
                                        "Universal Path": f"$.data.metros['{{metro_name}}'].{dir_k}[?(@['{id_col}'] == '{{{id_col}}}')]['{col_k}']",
                                        "Data Type": infer_data_type(sample_v),
                                        "Sample Value": format_sample_value(sample_v),
                                        "Notes": ""
                                    })
                    continue

                first_sub_k = next(iter(sec_val))
                first_sub_v = sec_val[first_sub_k]

                # Special Case: infosparks_stats.json -> feeds (meta & data arrays)
                if sec_name == "feeds" and isinstance(first_sub_v, dict) and "meta" in first_sub_v and "data" in first_sub_v:
                    meta_dict = first_sub_v.get("meta", {})
                    for m_k in sorted(meta_dict.keys()):
                        m_v = meta_dict[m_k]
                        rows.append({
                            "File Name": filename,
                            "Section": "feeds.meta",
                            "Data Point Key": f"meta.{m_k}",
                            "Access Pattern": "Section Keyed Map Property",
                            "Match Identifier": "[feed_id]",
                            "Universal Path": f"$.feeds['{{feed_id}}'].meta['{m_k}']",
                            "Data Type": infer_data_type(m_v),
                            "Sample Value": format_sample_value(m_v),
                            "Notes": ""
                        })

                    data_list = first_sub_v.get("data", [])
                    if data_list and isinstance(data_list[0], dict):
                        d_item = data_list[0]
                        rows.append({
                            "File Name": filename,
                            "Section": "feeds.data",
                            "Data Point Key": "data[].Date",
                            "Access Pattern": "Section Keyed Map Record Match",
                            "Match Identifier": "[feed_id] -> Date == {context.Date}",
                            "Universal Path": f"$.feeds['{{feed_id}}'].data[?(@.Date == '{{Date}}')]['Date']",
                            "Data Type": "string",
                            "Sample Value": format_sample_value(d_item.get("Date")),
                            "Notes": ""
                        })
                        geo_sample = next((v for k, v in d_item.items() if k != "Date"), None)
                        rows.append({
                            "File Name": filename,
                            "Section": "feeds.data",
                            "Data Point Key": "data[].{geography}",
                            "Access Pattern": "Section Keyed Map Record Match",
                            "Match Identifier": "[feed_id] -> Date == {context.Date}",
                            "Universal Path": f"$.feeds['{{feed_id}}'].data[?(@.Date == '{{Date}}')]['{{geography}}']",
                            "Data Type": infer_data_type(geo_sample),
                            "Sample Value": format_sample_value(geo_sample),
                            "Notes": ""
                        })
                    continue

                # Standard Keyed Sub-Map (e.g. ospi_school_data.json -> districts, school_boundaries.json -> district_boundaries)
                if isinstance(first_sub_v, dict):
                    sec_entity = "city" if "city" in sec_name.lower() else ("district" if "district" in sec_name.lower() else "entity_key")
                    sub_keys = []
                    for v in list(sec_val.values())[:25]:
                        if isinstance(v, dict):
                            for k in v.keys():
                                if k not in sub_keys:
                                    sub_keys.append(k)
                    
                    for k in sorted(sub_keys):
                        sample_val = next((v[k] for v in sec_val.values() if isinstance(v, dict) and v.get(k) is not None), None)

                        # Deep unpack: geometry object in school_boundaries
                        if k == "geometry" and isinstance(sample_val, dict):
                            for g_k in sorted(sample_val.keys()):
                                g_v = sample_val[g_k]
                                rows.append({
                                    "File Name": filename,
                                    "Section": sec_name,
                                    "Data Point Key": f"geometry.{g_k}",
                                    "Access Pattern": "Section Keyed Map Property",
                                    "Match Identifier": f"[{sec_entity}_key]",
                                    "Universal Path": f"$.{sec_name}['{{{sec_entity}_key}}'].geometry['{g_k}']",
                                    "Data Type": infer_data_type(g_v),
                                    "Sample Value": format_sample_value(g_v),
                                    "Notes": ""
                                })
                        else:
                            rows.append({
                                "File Name": filename,
                                "Section": sec_name,
                                "Data Point Key": k,
                                "Access Pattern": "Section Keyed Map",
                                "Match Identifier": f"[{sec_entity}_key]",
                                "Universal Path": f"$.{sec_name}['{{{sec_entity}_key}}']['{k}']",
                                "Data Type": infer_data_type(sample_val),
                                "Sample Value": format_sample_value(sample_val),
                                "Notes": ""
                            })
                else:
                    for k in sorted(sec_val.keys()):
                        rows.append({
                            "File Name": filename,
                            "Section": sec_name,
                            "Data Point Key": k,
                            "Access Pattern": "Section Direct Property",
                            "Match Identifier": "Global (No Match Needed)",
                            "Universal Path": f"$.{sec_name}['{k}']",
                            "Data Type": infer_data_type(sec_val[k]),
                            "Sample Value": format_sample_value(sec_val[k]),
                            "Notes": ""
                        })

            # Sub-Section C: Direct Primitive on Root
            else:
                rows.append({
                    "File Name": filename,
                    "Section": "root",
                    "Data Point Key": sec_name,
                    "Access Pattern": "Direct Property",
                    "Match Identifier": "Global (No Match Needed)",
                    "Universal Path": f"$.{sec_name}",
                    "Data Type": infer_data_type(sec_val),
                    "Sample Value": format_sample_value(sec_val),
                    "Notes": ""
                })

        return rows, None

    return None, "Unrecognized top-level data structure"

def main():
    print("==================================================")
    print("      MYSEATTLESEARCH DATA CATALOG GENERATOR      ")
    print("==================================================\n")

    if not os.path.exists(DATA_DIR):
        print(f"❌ Error: Data directory not found at {DATA_DIR}")
        return

    json_files = sorted([f for f in os.listdir(DATA_DIR) if f.endswith(".json") and not f.startswith(".")])
    print(f"🔍 Discovered {len(json_files)} JSON datasets in {DATA_DIR}...\n")

    master_records = []
    unrecognized_files = []
    indexed_files_count = 0

    for idx, fname in enumerate(json_files, 1):
        fpath = os.path.join(DATA_DIR, fname)
        rows, notice = catalog_single_file(fname, fpath)

        if rows is None or (not rows and notice):
            print(f"  [{idx}/{len(json_files)}] ⚠️ [UNRECOGNIZED] '{fname}': {notice}")
            unrecognized_files.append((fname, notice))
        else:
            print(f"  [{idx}/{len(json_files)}] ✓ Indexed '{fname}' ({len(rows)} data points)")
            master_records.extend(rows)
            indexed_files_count += 1

    master_records.sort(key=lambda r: (r["File Name"], r["Section"], r["Data Point Key"]))

    csv_columns = [
        "File Name", "Section", "Data Point Key", 
        "Access Pattern", "Match Identifier", "Universal Path", 
        "Data Type", "Sample Value", "Notes"
    ]

    with open(OUTPUT_CSV, "w", encoding="utf-8", newline="") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=csv_columns, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(master_records)

    print("\n==================================================")
    print("DATA CATALOG GENERATION COMPLETE")
    print(f"  • Total Datasets Scanned:       {len(json_files)}")
    print(f"  • Files Successfully Indexed:   {indexed_files_count}")
    print(f"  • Total Terminal Data Points:   {len(master_records)}")
    print(f"  • Master Catalog CSV Saved:     {OUTPUT_CSV}")

    if unrecognized_files:
        print("\n⚠️ Files Requiring Review / Custom Mapping:")
        for uf, reason in unrecognized_files:
            print(f"   • {uf.ljust(32)}: {reason}")
    else:
        print("\n🎉 Zero unmapped structures. All datasets cataloged cleanly!")
    print("==================================================")

if __name__ == "__main__":
    main()