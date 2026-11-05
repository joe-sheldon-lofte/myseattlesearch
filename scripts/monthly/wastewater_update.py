#!/usr/bin/env python3
"""
Monthly Regional Wastewater & Septic Harvester (Live County Feeds)
Pulls directly from King County ArcGIS REST API and Snohomish OnlineRME,
then upserts the monthly deltas into Cloudflare D1 'wastewater' table.
"""

import os
import sys
import json
import time
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup

# ------------------------------------------------------------------------------
# 1. CLOUDFLARE CONFIGURATION (From GitHub Actions Environment)
# ------------------------------------------------------------------------------
CF_ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID")
CF_DATABASE_ID = os.getenv("CF_DATABASE_PARCELDATA_ID")
CF_API_TOKEN = os.getenv("CF_D1_API_TOKEN")

if not all([CF_ACCOUNT_ID, CF_DATABASE_ID, CF_API_TOKEN]):
    print("❌ Missing required Cloudflare environment variables.")
    sys.exit(1)

D1_API_URL = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/d1/database/{CF_DATABASE_ID}/query"
BATCH_SIZE = 100

def sql_escape(val):
    if val is None:
        return "NULL"
    if isinstance(val, (int, float)):
        return str(val)
    clean = str(val).replace("'", "''")
    return f"'{clean}'"

def execute_d1_query(session, sql_query):
    headers = {
        "Authorization": f"Bearer {CF_API_TOKEN}",
        "Content-Type": "application/json"
    }
    max_retries = 3
    backoff = 2.0
    for attempt in range(max_retries):
        try:
            res = session.post(D1_API_URL, headers=headers, json={"sql": sql_query}, timeout=30)
            if res.status_code == 429:
                time.sleep(backoff)
                backoff *= 2
                continue
            return res.json()
        except Exception as e:
            if attempt == max_retries - 1:
                return {"success": False, "errors": [{"message": str(e)}]}
            time.sleep(backoff)
            backoff *= 2

def build_upsert_sql(rows):
    value_strings = []
    for r in rows:
        v = (
            f"({sql_escape(r['parcel_number'])}, {sql_escape(r['county'])}, "
            f"{sql_escape(r['service_type'])}, {sql_escape(r.get('service_subtype'))}, "
            f"{sql_escape(r.get('service_status', 'ACTIVE'))}, {sql_escape(r.get('sewer_provider_name'))}, "
            f"{sql_escape(r.get('has_capacity_charge', 0))}, "
            f"{sql_escape(r.get('oss_permit_number'))}, {sql_escape(r.get('installed_year'))}, "
            f"{sql_escape(r.get('last_inspection_date'))}, {sql_escape(r.get('last_pump_date'))}, "
            f"{sql_escape(r.get('has_asbuilt', 0))}, {sql_escape(r.get('raw_source_data'))})"
        )
        value_strings.append(v)

    return f"""
        INSERT INTO wastewater (
            parcel_number, county, service_type, service_subtype, service_status,
            sewer_provider_name, has_capacity_charge, oss_permit_number, installed_year, 
            last_inspection_date, last_pump_date, has_asbuilt, raw_source_data
        ) VALUES {', '.join(value_strings)}
        ON CONFLICT(parcel_number) DO UPDATE SET
            service_type = excluded.service_type,
            service_subtype = excluded.service_subtype,
            service_status = excluded.service_status,
            sewer_provider_name = excluded.sewer_provider_name,
            has_capacity_charge = excluded.has_capacity_charge,
            oss_permit_number = COALESCE(excluded.oss_permit_number, wastewater.oss_permit_number),
            installed_year = COALESCE(excluded.installed_year, wastewater.installed_year),
            last_inspection_date = COALESCE(excluded.last_inspection_date, wastewater.last_inspection_date),
            last_pump_date = COALESCE(excluded.last_pump_date, wastewater.last_pump_date),
            has_asbuilt = MAX(excluded.has_asbuilt, wastewater.has_asbuilt),
            raw_source_data = excluded.raw_source_data,
            updated_utc = CURRENT_TIMESTAMP;
    """

# ------------------------------------------------------------------------------
# 2. KING COUNTY: LIVE ARCGIS REST HARVESTER
# ------------------------------------------------------------------------------
def harvest_king_county_live(session):
    print("📡 Polling King County ArcGIS REST API for wastewater updates...")
    
    # Official Feature Layer for Parcels with Onsite Sewage Designations
    arcgis_url = "https://services.arcgis.com/Ej0PsM5Aw677QF1W/arcgis/rest/services/SEPTIC_ONSITE_PARCEL_AREA_2682/FeatureServer/0/query"
    
    # Target updates from the last 35 days (covers previous monthly cycle)
    cutoff_date = (datetime.utcnow() - timedelta(days=35)).strftime("%Y-%m-%d")
    
    params = {
        "where": f"EditDate >= DATE '{cutoff_date}' OR EditDate IS NULL",
        "outFields": "PIN,MAJOR,MINOR,ExpExcludeOn,ExcludeOn,ExpSewerConnection,SewerConnection,ExpSewerAgency,CapacityCharge,WastewaterTreatmentType,Comments,EditDate",
        "returnGeometry": "false",
        "resultRecordCount": 2000,
        "f": "json"
    }

    try:
        res = session.get(arcgis_url, params=params, timeout=45)
        data = res.json()
    except Exception as err:
        print(f"⚠️ King County REST query failed: {err}")
        return

    features = data.get("features", [])
    if not features:
        print("ℹ️ No new/modified King County wastewater records in the last 35 days.")
        return

    print(f"📦 Fetched {len(features)} live updates from King County.")
    batch = []
    upserted = 0

    for feat in features:
        attr = feat.get("attributes", {})
        raw_pin = attr.get("PIN") or f"{attr.get('MAJOR', '')}{attr.get('MINOR', '')}"
        pin = str(raw_pin).split(".")[0].replace("-", "").strip().zfill(10)
        if not pin or pin == "0000000000":
            continue

        exclude_text = str(attr.get("ExpExcludeOn") or "").strip().upper()
        ww_type = str(attr.get("WastewaterTreatmentType") or "").strip().upper()
        sewer_conn = str(attr.get("ExpSewerConnection") or "").strip().upper()

        if "OSS" in exclude_text or "SEPTIC" in ww_type or "OSS" in ww_type:
            srv = "SEPTIC"
            sub = None
        elif sewer_conn in ("YES", "1", "TRUE") or "SEWER" in exclude_text or "SEWER" in ww_type:
            srv = "SEWER"
            sub = "PUBLIC_SEWER"
        elif "VACANT" in exclude_text:
            srv = "VACANT"
            sub = None
        else:
            srv = "UNKNOWN"
            sub = None

        cap_charge = 1 if "YES" in str(attr.get("CapacityCharge") or "").upper() else 0
        sewer_agency = attr.get("ExpSewerAgency") if srv == "SEWER" else None

        batch.append({
            "parcel_number": pin,
            "county": "KING",
            "service_type": srv,
            "service_subtype": sub,
            "service_status": "ACTIVE",
            "sewer_provider_name": sewer_agency,
            "has_capacity_charge": cap_charge,
            "has_asbuilt": 0,
            "raw_source_data": json.dumps({
                "Comments": attr.get("Comments"),
                "ExcludeOn": attr.get("ExcludeOn"),
                "EditDate": attr.get("EditDate")
            })
        })

        if len(batch) >= BATCH_SIZE:
            execute_d1_query(session, build_upsert_sql(batch))
            upserted += len(batch)
            batch = []

    if batch:
        execute_d1_query(session, build_upsert_sql(batch))
        upserted += len(batch)

    print(f"✅ King County Live Upsert Complete: {upserted} records.")

# ------------------------------------------------------------------------------
# 3. SNOHOMISH COUNTY: LIVE ONLINERME INSPECTION ACTIVITY HARVESTER
# ------------------------------------------------------------------------------
def harvest_snohomish_live(session):
    print("📡 Polling Snohomish County OnlineRME portal for recent septic activity...")
    
    # OnlineRME Public Activity Log URL for Snohomish County
    activity_url = "https://www.onlinerme.com/Reports/PublicActivity.aspx"
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=35)

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }

    try:
        # 1. Establish session and get viewstate
        get_res = session.get(activity_url, headers=headers, timeout=30)
        soup = BeautifulSoup(get_res.text, "html.parser")
        
        vs_elem = soup.find("input", {"id": "__VIEWSTATE"})
        ev_elem = soup.find("input", {"id": "__EVENTVALIDATION"})
        if not vs_elem:
            print("⚠️ OnlineRME viewstate unavailable. Skipping Snohomish live poll.")
            return

        payload = {
            "__VIEWSTATE": vs_elem["value"],
            "__EVENTVALIDATION": ev_elem["value"] if ev_elem else "",
            "ddlCounty": "Snohomish",
            "txtStartDate": start_dt.strftime("%m/%d/%Y"),
            "txtEndDate": end_dt.strftime("%m/%d/%Y"),
            "btnSubmit": "View Report"
        }

        post_res = session.post(activity_url, data=payload, headers=headers, timeout=45)
        soup_res = BeautifulSoup(post_res.text, "html.parser")
        
        # Parse activity table rows
        rows = soup_res.find_all("tr", {"class": ["GridRow", "GridAltRow"]})
        if not rows:
            print("ℹ️ No recent OnlineRME activity rows returned for Snohomish.")
            return

        print(f"📦 Found {len(rows)} recent OnlineRME records for Snohomish County.")
        batch = []
        upserted = 0

        for r in rows:
            cols = [c.get_text(strip=True) for c in r.find_all("td")]
            if len(cols) < 5:
                continue

            raw_apn = cols[0].replace("-", "").strip()
            # Normalize APN: drop leading zero to match base table convention
            pin = raw_apn.lstrip('0') if raw_apn.startswith('0') else raw_apn
            if len(pin) < 10:
                continue

            permit_num = cols[1] if len(cols) > 1 else None
            system_type = cols[2] if len(cols) > 2 else "SEPTIC"
            event_date = cols[3] if len(cols) > 3 else None  # Inspection or pump date

            batch.append({
                "parcel_number": pin,
                "county": "SNOHOMISH",
                "service_type": "SEPTIC",
                "service_subtype": system_type,
                "service_status": "ACTIVE",
                "oss_permit_number": permit_num,
                "last_inspection_date": event_date,
                "last_pump_date": event_date,
                "has_asbuilt": 1,
                "raw_source_data": json.dumps({"Source": "OnlineRME_Live_Harvester"})
            })

            if len(batch) >= BATCH_SIZE:
                execute_d1_query(session, build_upsert_sql(batch))
                upserted += len(batch)
                batch = []

        if batch:
            execute_d1_query(session, build_upsert_sql(batch))
            upserted += len(batch)

        print(f"✅ Snohomish Live Upsert Complete: {upserted} records.")

    except Exception as err:
        print(f"⚠️ Snohomish OnlineRME poll skipped or failed: {err}")

# ------------------------------------------------------------------------------
# 4. ENTRY POINT
# ------------------------------------------------------------------------------
def main():
    print("==================================================")
    print("  LIVE REGIONAL WASTEWATER & SEPTIC HARVESTER     ")
    print("==================================================\n")
    
    session = requests.Session()
    harvest_king_county_live(session)
    harvest_snohomish_live(session)
    print("\n🎉 Live wastewater sync finished successfully.")

if __name__ == "__main__":
    main()