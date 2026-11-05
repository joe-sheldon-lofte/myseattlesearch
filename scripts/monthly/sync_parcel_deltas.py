import os
import io
import re
import csv
import zipfile
import requests

def load_dev_vars(root_dir):
    for env_name in [".dev.vars", ".env"]:
        dev_vars_path = os.path.join(root_dir, env_name)
        if os.path.exists(dev_vars_path):
            with open(dev_vars_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

def slugify_neighborhood(raw_text):
    if not raw_text:
        return "unincorporated"
    val = str(raw_text).strip().lower()
    # Strip trailing state declarations (e.g. " wa", ", wa", " wa 98101")
    val = re.sub(r'[\s,]+wa(?:\s+\d{5}(?:-\d{4})?)?$', '', val, flags=re.IGNORECASE)
    val = val.rstrip(' ,').strip()
    
    if val in ['federaly', 'federal-y', 'federal y']:
        return 'federal-way'
        
    out = []
    for ch in val:
        if ch.isalnum():
            out.append(ch)
        elif ch in [' ', '-', '_', ',']:
            out.append('-')
    res = "".join(out)
    while '--' in res:
        res = res.replace('--', '-')
    return res.strip('-') or "unincorporated"

def sql_escape(val):
    if val is None:
        return "NULL"
    if isinstance(val, (int, float)):
        return str(val)
    escaped = str(val).replace("'", "''")
    return f"'{escaped}'"

def execute_d1_query(session, endpoint, headers, sql_block):
    res = session.post(endpoint, headers=headers, json={"sql": sql_block}, timeout=60)
    data = res.json()
    if not data.get("success"):
        raise RuntimeError(f"D1 Delta Sync Failed: {data.get('errors', [])}")
    return data

def fetch_snohomish_deltas(days_back=35):
    """Harvests newly platted and modified parcels from Snohomish County Open GIS."""
    print(f"📡 Polling Snohomish County Open GIS (past {days_back} days)...")
    base_url = "https://gis.snoco.org/arcgis/rest/services/Cadastral/Parcels/MapServer/0/query"
    where_clause = f"CORRDATE >= CURRENT_TIMESTAMP - {days_back} AND PARCEL_ID IS NOT NULL"
    params = {
        "where": where_clause,
        "outFields": "PARCEL_ID,SITUSLINE1,SITUSCITY,GIS_SQ_FT,MKTTL,MKLND,MKIMP",
        "returnGeometry": "false",
        "f": "json"
    }
    try:
        res = requests.get(base_url, params=params, timeout=45)
        res.raise_for_status()
        features = res.json().get("features", [])
        print(f"   Located {len(features):,} modified/new Snohomish records.")
        
        normalized = []
        for f in features:
            attr = f.get("attributes", {})
            pid = str(attr.get("PARCEL_ID", "")).strip()
            if not pid:
                continue
            total_val = attr.get("MKTTL") or (int(attr.get("MKLND") or 0) + int(attr.get("MKIMP") or 0))
            normalized.append({
                "parcel_number": pid,
                "situs_address": attr.get("SITUSLINE1"),
                "neighborhood_slug": slugify_neighborhood(attr.get("SITUSCITY")),
                "square_footage": int(float(attr.get("GIS_SQ_FT") or 0)) if attr.get("GIS_SQ_FT") else None,
                "assessed_value_total": int(total_val) if total_val else None,
                "county": "Snohomish"
            })
        return normalized
    except Exception as e:
        print(f"   ⚠️ Snohomish delta query warning: {e}")
        return []

def fetch_king_deltas(days_back=35):
    """Downloads King County Assessor weekly update archives and parses new/updated parcels."""
    print("📥 Downloading King County Assessor weekly data archives...")
    urls = {
        "parcel": "https://dorcdn.kingcounty.gov/datadownload/Parcel.zip",
        "rpacct": "https://dorcdn.kingcounty.gov/datadownload/RPAcct_NoName.zip"
    }
    
    session = requests.Session()
    
    # 1. Download & Map Lot Square Footage from Parcel.zip
    pin_sqft = {}
    try:
        res_parcel = session.get(urls["parcel"], timeout=90)
        res_parcel.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(res_parcel.content)) as z:
            target = [name for name in z.namelist() if name.endswith('.csv')][0]
            with z.open(target) as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding='utf-8', errors='ignore'))
                for r in reader:
                    maj = str(r.get('Major', '')).strip().zfill(6)
                    minr = str(r.get('Minor', '')).strip().zfill(4)
                    pin = f"{maj}{minr}"
                    sqft = r.get('SqFtLot')
                    if sqft:
                        try:
                            pin_sqft[pin] = int(float(sqft))
                        except (ValueError, TypeError):
                            pass
        print(f"   Extracted {len(pin_sqft):,} lot geometry keys from King County.")
    except Exception as e:
        print(f"   ⚠️ King County Parcel.zip warning: {e}")

    # 2. Download and Parse Tax Accounts from RPAcct_NoName.zip
    king_updates = []
    try:
        res_rpacct = session.get(urls["rpacct"], timeout=90)
        res_rpacct.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(res_rpacct.content)) as z:
            target = [name for name in z.namelist() if name.endswith('.csv')][0]
            with z.open(target) as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding='utf-8', errors='ignore'))
                for r in reader:
                    maj = str(r.get('Major', '')).strip().zfill(6)
                    minr = str(r.get('Minor', '')).strip().zfill(4)
                    pin = f"{maj}{minr}"
                    
                    addr = r.get('AddrLine', '').strip() or None
                    city_state = r.get('CityState', '').strip()
                    slug = slugify_neighborhood(city_state)
                    
                    try:
                        land = float(r.get('ApprLandVal') or 0)
                        impr = float(r.get('ApprImprVal') or 0)
                        total_val = int(land + impr) if (land + impr) > 0 else None
                    except (ValueError, TypeError):
                        total_val = None
                        
                    king_updates.append({
                        "parcel_number": pin,
                        "situs_address": addr,
                        "neighborhood_slug": slug,
                        "square_footage": pin_sqft.get(pin),
                        "assessed_value_total": total_val,
                        "county": "King"
                    })
        print(f"   Compiled {len(king_updates):,} active King County parcel records.")
        return king_updates
    except Exception as e:
        print(f"   ⚠️ King County RPAcct_NoName.zip warning: {e}")
        return []

def sync_upserts_to_d1(session, endpoint, headers, updates, batch_size=100):
    if not updates:
        print("ℹ️ No deltas to sync.")
        return

    print(f"🚀 Upserting {len(updates):,} parcels into Cloudflare D1 table 'base'...")
    for i in range(0, len(updates), batch_size):
        chunk = updates[i:i + batch_size]
        statements = []

        for item in chunk:
            pin = sql_escape(item["parcel_number"])
            addr = sql_escape(item.get("situs_address"))
            slug = sql_escape(item.get("neighborhood_slug"))
            sqft = sql_escape(item.get("square_footage"))
            val = sql_escape(item.get("assessed_value_total"))
            county = sql_escape(item.get("county"))

            statements.append(f"""
            INSERT INTO base (parcel_number, situs_address, neighborhood_slug, square_footage, assessed_value_total, county, updated_utc)
            VALUES ({pin}, {addr}, {slug}, {sqft}, {val}, {county}, CURRENT_TIMESTAMP)
            ON CONFLICT(parcel_number) DO UPDATE SET
              situs_address = COALESCE(excluded.situs_address, base.situs_address),
              neighborhood_slug = COALESCE(excluded.neighborhood_slug, base.neighborhood_slug),
              square_footage = COALESCE(excluded.square_footage, base.square_footage),
              assessed_value_total = COALESCE(excluded.assessed_value_total, base.assessed_value_total),
              updated_utc = CURRENT_TIMESTAMP;
            """)

        sql_block = "\n".join(statements)
        execute_d1_query(session, endpoint, headers, sql_block)
        print(f"\r   Committed: {min(i + batch_size, len(updates)):,} / {len(updates):,}", end="", flush=True)

    print("\n✅ Dual-county delta sync complete.")

def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    load_dev_vars(base_dir)

    cf_account_id = os.environ.get("CF_ACCOUNT_ID")
    cf_api_token = os.environ.get("CF_D1_API_TOKEN")
    cf_db_id = os.environ.get("CF_DATABASE_PARCELDATA_ID")

    if not all([cf_account_id, cf_api_token, cf_db_id]):
        raise ValueError("Missing Cloudflare D1 credentials (CF_ACCOUNT_ID, CF_D1_API_TOKEN, CF_DATABASE_PARCELDATA_ID).")

    endpoint = f"https://api.cloudflare.com/client/v4/accounts/{cf_account_id}/d1/database/{cf_db_id}/query"
    headers = {
        "Authorization": f"Bearer {cf_api_token}",
        "Content-Type": "application/json"
    }
    session = requests.Session()

    # 1. Harvest Snohomish County Deltas
    snohomish_deltas = fetch_snohomish_deltas(days_back=35)
    sync_upserts_to_d1(session, endpoint, headers, snohomish_deltas)

    # 2. Harvest King County Deltas
    king_deltas = fetch_king_deltas(days_back=35)
    sync_upserts_to_d1(session, endpoint, headers, king_deltas)

if __name__ == "__main__":
    main()