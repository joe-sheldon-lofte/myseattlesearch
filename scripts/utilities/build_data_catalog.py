# File: scripts/utilities/build_data_catalog.py

import os
import csv
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_CSV = os.path.join(BASE_DIR, "DataPointIndex_Master.csv")

def infer_data_type(val):
    """Infers the clean, human-readable data type from native Python JSON objects."""
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
    """Selects the most specific primary key or context identifier for record queries."""
    candidates = [
        "school_code", "district_code", "condo_id", "mls_number", 
        "StepID", "FAQID", "QuestionID", "Review ID", "Program Name", 
        "Facility", "id", "slug", "City", "city", "CityName", 
        "category", "trigger_key", "name"
    ]
    for candidate in candidates:
        if candidate in keys:
            return candidate
    return list(keys)[0] if keys else "index"

def catalog_single_file(filename, filepath):
    """
    Parses a JSON file, classifies it into one of 5 architectural data patterns,
    and returns a structured list of coordinate rows.
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

        # Harvest all unique keys across the first 25 records to prevent sparse field omission
        all_keys = []
        for item in data[:25]:
            if isinstance(item, dict):
                for k in item.keys():
                    if k not in all_keys:
                        all_keys.append(k)

        id_field = pick_primary_identifier(all_keys)

        for k in all_keys:
            sample_val = None
            for item in data[:25]:
                if isinstance(item, dict) and item.get(k) is not None:
                    sample_val = item[k]
                    break

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

        # Pattern 3: Flat Singleton (Key-Value Primitive Dictionary)
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

        # Pattern 4: Keyed Entity Map (Uniform dictionary of entity objects)
        all_sub_dicts = all(isinstance(v, dict) for v in data.values())
        if all_sub_dicts:
            sub_key_sets = [set(v.keys()) for v in list(data.values())[:10]]
            if len(sub_key_sets) >= 1:
                union_keys = set.union(*sub_key_sets)
                intersection_keys = set.intersection(*sub_key_sets) if len(sub_key_sets) > 1 else union_keys
                
                # Check for shared property layout across entity instances
                if len(union_keys) > 0 and (len(intersection_keys) / len(union_keys)) >= 0.35:
                    first_key = list(data.keys())[0].lower()
                    entity_label = "city" if any(c in first_key for c in ["edmonds", "seattle", "lynnwood", "bellevue"]) else "entity_key"
                    
                    for k in sorted(list(union_keys)):
                        sample_val = None
                        for v in data.values():
                            if isinstance(v, dict) and v.get(k) is not None:
                                sample_val = v[k]
                                break

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
                    return rows, None

        # Pattern 5: Multi-Section Compound Bundle
        for sec_name, sec_val in data.items():
            # Sub-Section A: Array of Records
            if isinstance(sec_val, list):
                if not sec_val:
                    continue
                if isinstance(sec_val[0], dict):
                    sec_keys = []
                    for item in sec_val[:25]:
                        if isinstance(item, dict):
                            for k in item.keys():
                                if k not in sec_keys:
                                    sec_keys.append(k)

                    id_field = pick_primary_identifier(sec_keys)

                    for k in sec_keys:
                        sample_val = None
                        for item in sec_val[:25]:
                            if isinstance(item, dict) and item.get(k) is not None:
                                sample_val = item[k]
                                break

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
                first_sub_k = next(iter(sec_val))
                first_sub_v = sec_val[first_sub_k]

                if isinstance(first_sub_v, dict):
                    sec_entity = "city" if "city" in sec_name.lower() else ("district" if "district" in sec_name.lower() else "entity_key")
                    sub_keys = []
                    for v in list(sec_val.values())[:25]:
                        if isinstance(v, dict):
                            for k in v.keys():
                                if k not in sub_keys:
                                    sub_keys.append(k)

                    for k in sorted(sub_keys):
                        sample_val = None
                        for v in sec_val.values():
                            if isinstance(v, dict) and v.get(k) is not None:
                                sample_val = v[k]
                                break

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

    # Sort master rows by File Name, Section, and Data Point Key
    master_records.sort(key=lambda r: (r["File Name"], r["Section"], r["Data Point Key"]))

    # Write Master Catalog CSV
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