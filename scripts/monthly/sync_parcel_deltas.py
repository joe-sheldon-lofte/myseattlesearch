import os
import sys
import io
import re
import csv
import time
import zipfile
import sqlite3
import requests

def load_dev_vars(root_dir):
    dev_vars_path = os.path.join(root_dir, ".dev.vars")
    if os.path.exists(dev_vars_path):
        with open(dev_vars_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

def sql_escape(val):
    if val is None:
        return "NULL"
    if isinstance(val, (int, float)):
        return str(val)
    escaped = str(val).replace("'", "''")
    return f"'{escaped}'"

def execute_d1_raw(session, endpoint, headers, sql_chunk):
    response = session.post(endpoint, headers=headers, json={"sql": sql_chunk}, timeout=45)
    data = response.json()
    if not data.get("success"):
        raise RuntimeError(f"D1 Delta Sync Failed: {data.get('errors', [])}")
    return data

def fetch_snohomish_deltas(days_back=35):
    """Queries Snohomish County ArcGIS FeatureServer for recent parcel modifications."""
    print(f"📡 Polling Snohomish County Open GIS for parcels modified in last {days_back} days...")
    
    # Authoritative Snohomish Open Data Feature Service endpoint
    base_url = "https://gis.snoco.org/arcgis/rest/services/Cadastral/Parcels/MapServer/0/query"
    where_clause = f"CORRDATE >= CURRENT_TIMESTAMP - {days_back} AND PARCEL_ID IS NOT NULL"
    
    params = {
        "where": where_clause,
        "outFields": "PARCEL_ID,SITUSLINE1,SITUSCITY,SITUSZIP,GIS_SQ_FT,MKTTL,MKLND,MKIMP,USECODE",
        "returnGeometry": "false",
        "f": "json"
    }
    
    try:
        res = requests.get(base_url, params=params, timeout=30)
        res.raise_for_status()
        features = res.json().get("features", [])
        print(f"   Located {len(features):,} modified Snohomish parcel records.")
        return [f["attributes"] for f in features]
    except Exception as e:
        print(f"   ⚠️ Snohomish delta query notice: {e}")
        return []

def fetch_king_assessor_zips():
    """Fetches King County Assessor weekly update tables directly into memory."""
    print("📥 Downloading King County Assessor update archives...")
    urls = {
        "rpacct": "https://dorcdn.kingcounty.gov/datadownload/RPAcct_NoName.zip",
        "parcel": "https://dorcdn.kingcounty.gov/datadownload/Parcel.zip"
    }
    
    extracted_data = {}
    for key, url in urls.items():
        try:
            res = requests.get(url, timeout=60)
            res.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(res.content)) as z:
                target_csv = [name for name in z.namelist() if name.endswith('.csv')][0]
                extracted_data[key] = z.read(target_csv).decode('utf-8', errors='ignore')
                print(f"   Unpacked {key} extract ({len(extracted_data[key]):,} bytes).")
        except Exception as e:
            print(f"   ⚠️ Failed downloading {key} from King County: {e}")
            extracted_data[key] = None
            
    return extracted_data

def sync_deltas_to_d1(session, endpoint, headers, updates, batch_size=200):
    if not updates:
        print("ℹ️ No deltas detected for synchronization.")
        return

    print(f"🚀 Committing {len(updates):,} updated records to Cloudflare D1...")
    for i in range(0, len(updates), batch_size):
        chunk = updates[i:i + batch_size]
        statements = []

        for item in chunk:
            pin = sql_escape(item["parcel_number"])
            val = sql_escape(item.get("assessed_value_total"))
            addr = sql_escape(item.get("situs_address"))
            sqft = sql_escape(item.get("square_footage"))

            statements.append(f"""
            UPDATE base SET
              assessed_value_total = COALESCE({val}, assessed_value_total),
              situs_address = COALESCE({addr}, situs_address),
              square_footage = COALESCE({sqft}, square_footage),
              updated_utc = CURRENT_TIMESTAMP
            WHERE parcel_number = {pin};
            """)

        sql_block = "\n".join(statements)
        execute_d1_raw(session, endpoint, headers, sql_block)
        print(f"\r   Synchronized: {min(i + batch_size, len(updates)):,} / {len(updates):,}", end="", flush=True)

    print("\n✅ Monthly delta synchronization complete.")

def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    load_dev_vars(base_dir)

    cf_account_id = os.environ.get("CF_ACCOUNT_ID")
    cf_api_token = os.environ.get("CF_D1_API_TOKEN")
    cf_db_id = os.environ.get("CF_DATABASE_PARCELDATA_ID")

    if not all([cf_account_id, cf_api_token, cf_db_id]):
        raise ValueError("Missing Cloudflare D1 credentials.")

    endpoint = f"https://api.cloudflare.com/client/v4/accounts/{cf_account_id}/d1/database/{cf_db_id}/query"
    headers = {
        "Authorization": f"Bearer {cf_api_token}",
        "Content-Type": "application/json"
    }
    session = requests.Session()

    # 1. Harvest Snohomish deltas via API
    snohomish_deltas = fetch_snohomish_deltas(days_back=35)
    normalized_updates = []
    
    for s in snohomish_deltas:
        pid = str(s.get("PARCEL_ID", "")).strip()
        if not pid:
            continue
        total_val = s.get("MKTTL") or (int(s.get("MKLND") or 0) + int(s.get("MKIMP") or 0))
        normalized_updates.append({
            "parcel_number": pid,
            "situs_address": s.get("SITUSLINE1"),
            "square_footage": int(float(s.get("GIS_SQ_FT") or 0)) if s.get("GIS_SQ_FT") else None,
            "assessed_value_total": int(total_val) if total_val else None
        })

    # 2. Push updates to Cloudflare D1
    sync_deltas_to_d1(session, endpoint, headers, normalized_updates)

if __name__ == "__main__":
    main()