#!/usr/bin/env python3
"""
King County Wastewater, Sewer & Capacity Charge Ingestion Script
Target Table: wastewater (Cloudflare D1)
Input File:   data/king_wastewater.csv
"""

import csv
import json
import os
import sys
import time
from pathlib import Path
import requests

# ---------------------------------------------------------
# Environment & .dev.vars Loader
# ---------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent

def load_dev_vars():
    candidate_paths = [
        REPO_ROOT / ".dev.vars",
        Path(".dev.vars"),
        Path.cwd() / ".dev.vars"
    ]
    for p in candidate_paths:
        if p.is_file():
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k and k not in os.environ:
                            os.environ[k] = v
            break

load_dev_vars()

CF_ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID")
CF_DATABASE_ID = os.getenv("CF_DATABASE_PARCELDATA_ID") or os.getenv("CF_D1_DATABASE_ID")
PRIMARY_TOKEN = os.getenv("CF_D1_API_TOKEN")
FALLBACK_TOKEN = os.getenv("CF_API_TOKEN")

if not CF_ACCOUNT_ID or not CF_DATABASE_ID or not (PRIMARY_TOKEN or FALLBACK_TOKEN):
    print("❌ Missing required Cloudflare variables in .dev.vars or environment.")
    sys.exit(1)

BATCH_SIZE = 100

CANDIDATE_PATHS = [
    REPO_ROOT / "data" / "king_wastewater.csv",
    Path("data/king_wastewater.csv"),
    Path("/data/king_wastewater.csv"),
    SCRIPT_DIR / "king_wastewater.csv"
]
CSV_FILE_PATH = next((p for p in CANDIDATE_PATHS if p.is_file()), None)
D1_API_URL = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/d1/database/{CF_DATABASE_ID}/query"


# ---------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------
def sql_escape(val):
    if val is None:
        return "NULL"
    if isinstance(val, (int, float)):
        return str(val)
    clean = str(val).replace("'", "''")
    return f"'{clean}'"

def clean_pin(val):
    return str(val).split(".")[0].replace("-", "").strip().zfill(10)

def build_insert_sql(rows):
    value_strings = []
    for r in rows:
        v = (
            f"({sql_escape(r['parcel_number'])}, "
            f"{sql_escape(r['county'])}, "
            f"{sql_escape(r['service_type'])}, "
            f"{sql_escape(r['service_subtype'])}, "
            f"{sql_escape(r['service_status'])}, "
            f"{sql_escape(r['sewer_provider_name'])}, "
            f"{sql_escape(r['has_capacity_charge'])}, "
            f"{sql_escape(r['raw_source_data'])})"
        )
        value_strings.append(v)

    return f"""
    INSERT INTO wastewater (
        parcel_number, county, service_type, service_subtype, service_status,
        sewer_provider_name, has_capacity_charge, raw_source_data
    ) VALUES {', '.join(value_strings)}
    ON CONFLICT(parcel_number) DO UPDATE SET
        service_type = excluded.service_type,
        service_subtype = excluded.service_subtype,
        service_status = excluded.service_status,
        sewer_provider_name = excluded.sewer_provider_name,
        has_capacity_charge = excluded.has_capacity_charge,
        raw_source_data = COALESCE(excluded.raw_source_data, wastewater.raw_source_data),
        updated_utc = CURRENT_TIMESTAMP;
    """

def execute_d1_query(session, token, sql_query):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    max_retries = 5
    backoff = 1.0

    for attempt in range(max_retries):
        try:
            response = session.post(
                D1_API_URL,
                headers=headers,
                json={"sql": sql_query},
                timeout=30
            )
            if response.status_code == 429:
                time.sleep(backoff)
                backoff *= 2
                continue

            return response.status_code, response.json()
        except requests.exceptions.RequestException as err:
            if attempt == max_retries - 1:
                return 500, {"errors": [{"message": str(err)}]}
            time.sleep(backoff)
            backoff *= 2

    return 500, {"errors": [{"message": "Max retries exceeded"}]}

def send_batch(session, token, rows):
    sql = build_insert_sql(rows)
    _, res = execute_d1_query(session, token, sql)

    if res.get("success"):
        return len(rows), 0

    err_str = json.dumps(res.get("errors", []))
    if "FOREIGN KEY" in err_str or "constraint failed" in err_str:
        ok_count = 0
        skip_count = 0
        for single_row in rows:
            single_sql = build_insert_sql([single_row])
            _, s_res = execute_d1_query(session, token, single_sql)
            if s_res.get("success"):
                ok_count += 1
            else:
                skip_count += 1
        return ok_count, skip_count

    print(f"⚠️ Batch Error: {err_str}")
    return 0, len(rows)


# ---------------------------------------------------------
# Main Execution Pipeline
# ---------------------------------------------------------
def main():
    if not CSV_FILE_PATH:
        print("❌ Error: Could not locate 'king_wastewater.csv'.")
        sys.exit(1)

    print(f"📂 Found CSV: {CSV_FILE_PATH}")
    session = requests.Session()

    active_token = PRIMARY_TOKEN or FALLBACK_TOKEN
    test_code, test_res = execute_d1_query(session, active_token, "SELECT 1 AS test;")

    if (test_code in (401, 403) or not test_res.get("success")) and FALLBACK_TOKEN:
        print("⚠️ Primary token unauthenticated. Switching to fallback token...")
        active_token = FALLBACK_TOKEN
        test_code, test_res = execute_d1_query(session, active_token, "SELECT 1 AS test;")
        if not test_res.get("success"):
            print("❌ Authentication failed with both tokens:", test_res.get("errors"))
            sys.exit(1)

    print("✅ Cloudflare D1 authentication successful.")

    batch = []
    total_inserted = 0
    total_skipped = 0
    start_time = time.time()

    with open(CSV_FILE_PATH, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        for row in reader:
            raw_pin = row.get("PIN") or f"{row.get('MAJOR', '')}{row.get('MINOR', '')}"
            pin = clean_pin(raw_pin)

            if not pin or pin == "0000000000":
                continue

            exclude_text = str(row.get("ExpExcludeOn") or row.get("ExcludeOn") or "").strip().upper()
            ww_type = str(row.get("WastewaterTreatmentType") or "").strip().upper()
            sewer_conn = str(row.get("ExpSewerConnection") or row.get("SewerConnection") or "").strip().upper()

            # Service Classification
            if "OSS" in exclude_text or "SEPTIC" in ww_type or "OSS" in ww_type:
                service_type = "SEPTIC"
                subtype = None
            elif sewer_conn in ("YES", "1", "TRUE") or "SEWER" in exclude_text or "SEWER" in ww_type:
                service_type = "SEWER"
                subtype = "PUBLIC_SEWER"
            elif "VACANT" in exclude_text:
                service_type = "VACANT"
                subtype = None
            else:
                service_type = "UNKNOWN"
                subtype = None

            # Capacity Charge (Clean boolean check)
            cap_raw = str(row.get("CapacityCharge") or "").strip().upper()
            cap_charge = 1 if cap_raw in ("YES", "Y", "1", "TRUE") else 0

            # Sewer Agency
            sewer_agency = (row.get("ExpSewerAgency") or row.get("SewerAgency") or "").strip()
            if not sewer_agency or service_type != "SEWER":
                sewer_agency = None

            # Only store raw_source_data if there is an actual unique note
            comments = str(row.get("Comments") or "").strip()
            raw_meta = json.dumps({"Comments": comments}, ensure_ascii=False) if comments else None

            batch.append({
                "parcel_number": pin,
                "county": "KING",
                "service_type": service_type,
                "service_subtype": subtype,
                "service_status": "ACTIVE",
                "sewer_provider_name": sewer_agency,
                "has_capacity_charge": cap_charge,
                "raw_source_data": raw_meta
            })

            if len(batch) >= BATCH_SIZE:
                inserted, skipped = send_batch(session, active_token, batch)
                total_inserted += inserted
                total_skipped += skipped
                batch = []

                if total_inserted % 5000 == 0:
                    elapsed = time.time() - start_time
                    rate = total_inserted / elapsed if elapsed > 0 else 0
                    print(f"🚀 Ingested {total_inserted:,} parcels ({rate:.1f} rows/sec)")

        if batch:
            inserted, skipped = send_batch(session, active_token, batch)
            total_inserted += inserted
            total_skipped += skipped

  

    elapsed = time.time() - start_time
    print("\n🎉 King County Utility & Capacity Ingestion Complete!")
    print(f"Total Parcels Upserted: {total_inserted:,}")
    print(f"Orphan Parcels Skipped (Not in base table): {total_skipped:,}")
    print(f"Total Time: {elapsed / 60:.1f} minutes")

if __name__ == "__main__":
    main()