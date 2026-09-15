import os
import zipfile
import json
import pandas as pd

def is_entity_map(d):
    """
    Checks if a dictionary represents dynamic entities (e.g., city names) 
    by verifying if child entries share identical internal key structures.
    """
    if not isinstance(d, dict) or len(d) < 2:
        return False
    
    dict_values = [v for v in d.values() if isinstance(v, dict)]
    if len(dict_values) >= 2:
        # Measure key overlap across child dictionaries
        first_keys = set(dict_values[0].keys())
        second_keys = set(dict_values[1].keys())
        if len(first_keys.intersection(second_keys)) > 0:
            return True
            
    return False

def extract_schema_paths(obj, parent_key=''):
    paths = set()

    if isinstance(obj, dict):
        if is_entity_map(obj):
            # Dynamic city/entity map detected -> Collapse key
            placeholder_key = f"{parent_key}.{{entity}}" if parent_key else "{entity}"
            for value in obj.values():
                paths.update(extract_schema_paths(value, placeholder_key))
        else:
            # Standard fixed object -> Keep exact keys
            for key, value in obj.items():
                new_key = f"{parent_key}.{key}" if parent_key else key
                paths.update(extract_schema_paths(value, new_key))

    elif isinstance(obj, list):
        array_key = f"{parent_key}[]" if parent_key else "[]"
        if not obj:
            paths.add((array_key, "Empty Array"))
        else:
            for item in obj:
                paths.update(extract_schema_paths(item, array_key))

    else:
        data_type = type(obj).__name__
        paths.add((parent_key, data_type))

    return paths

def process_repository_zip(zip_filename, output_csv_filename):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    zip_filepath = os.path.join(script_dir, zip_filename)
    output_filepath = os.path.join(script_dir, output_csv_filename)

    index_records = []

    with zipfile.ZipFile(zip_filepath, 'r') as zip_ref:
        for file_info in zip_ref.infolist():
            if file_info.filename.endswith('.json') and not file_info.filename.startswith('__MACOSX'):
                with zip_ref.open(file_info) as file:
                    try:
                        data = json.load(file)
                        extracted = extract_schema_paths(data)

                        for field_path, data_type in extracted:
                            index_records.append({
                                "File Name": file_info.filename,
                                "Data Point Path": field_path,
                                "Data Type": data_type
                            })
                    except Exception as e:
                        print(f"Skipping {file_info.filename}: {e}")

    df = pd.DataFrame(index_records).drop_duplicates()
    df.to_csv(output_filepath, index=False)
    print(f"Successfully processed {len(df)} unique schema paths saved to {output_filepath}")

if __name__ == "__main__":
    process_repository_zip("data.zip", "UI_Upgrade_Data_Point_Index_New.csv")