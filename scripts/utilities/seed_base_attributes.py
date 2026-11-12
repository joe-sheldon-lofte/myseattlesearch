import os
import re
import csv
import argparse
import requests

MAX_BATCH_ROWS = 200
MAX_SQL_BYTES = 75000  # Strict safety ceiling below D1's 102,400-byte SQLITE_TOOBIG limit


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


def to_int(val):
    if val is None or val == "":
        return None
    try:
        num = int(float(str(val).strip()))
        return num if num > 0 else None
    except (ValueError, TypeError):
        return None


def to_zero_or_int(val):
    if val is None or val == "":
        return 0
    try:
        return int(float(str(val).strip()))
    except (ValueError, TypeError):
        return 0


def sql_val(val):
    if val is None:
        return "NULL"
    if isinstance(val, (int, float)):
        return str(val)
    escaped = str(val).replace("'", "''")
    return f"'{escaped}'"


def execute_d1_query(session, endpoint, headers, sql_block):
    res = session.post(endpoint, headers=headers, json={"sql": sql_block}, timeout=90)
    data = res.json()
    if not data.get("success"):
        raise RuntimeError(f"D1 Query Failed: {data.get('errors', [])}")
    return data


def parse_king_county(staging_dir):
    parcel_path = os.path.join(staging_dir, "kc-parcel.csv")
    resbldg_path = os.path.join(staging_dir, "kc-resbldg.csv")

    if not os.path.exists(parcel_path) or not os.path.exists(resbldg_path):
        print("⚠️ Missing kc-parcel.csv or kc-resbldg.csv in data/staging/. Skipping King County.")
        return {}

    print("📂 Reading King County kc-parcel.csv...")
    parcels = {}
    mtn_cols = ["MtRainier", "Olympics", "Cascades"]
    water_cols = ["PugetSound", "LakeWashington", "LakeSammamish", "SmallLakeRiverCreek"]

    with open(parcel_path, "r", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        for r in reader:
            maj = str(r.get("Major", "")).strip().zfill(6)
            minr = str(r.get("Minor", "")).strip().zfill(4)
            if maj == "000000" and minr == "0000":
                continue
            pin = f"{maj}{minr}"

            prop_type = (r.get("PropType") or "R").strip()[:1] or "R"
            view_mtn = 1 if any(to_zero_or_int(r.get(c)) > 0 for c in mtn_cols) else 0
            view_wtr = 1 if any(to_zero_or_int(r.get(c)) > 0 for c in water_cols) else 0
            wfnt = to_zero_or_int(r.get("WfntLocation"))

            parcels[pin] = {
                "parcel_number": pin,
                "major_code": maj,
                "minor_code": minr,
                "property_type": prop_type,
                "neighborhood_slug": "unincorporated",
                "situs_address": None,
                "zip_code": None,
                "year_built": None,
                "square_footage": None,
                "lot_sqft": to_int(r.get("SqFtLot")),
                "bedrooms": None,
                "bath_full": None,
                "bath_half": None,
                "building_grade": None,
                "building_condition": None,
                "view_mountain": view_mtn,
                "view_water": view_wtr,
                "waterfront_type": wfnt,
                "assessed_value_total": None,
                "county": "KING",
            }

    print(f"   Loaded {len(parcels):,} King County parcel records.")
    print("📂 Merging King County kc-resbldg.csv...")

    bldg_matched = 0
    with open(resbldg_path, "r", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        for r in reader:
            maj = str(r.get("Major", "")).strip().zfill(6)
            minr = str(r.get("Minor", "")).strip().zfill(4)
            pin = f"{maj}{minr}"
            if pin not in parcels:
                continue

            living = to_int(r.get("SqFtTotLiving"))
            existing_living = parcels[pin]["square_footage"] or 0

            if living and living >= existing_living:
                full_b = to_zero_or_int(r.get("BathFullCount")) + to_zero_or_int(r.get("Bath3qtrCount"))
                half_b = to_zero_or_int(r.get("BathHalfCount"))
                raw_zip = str(r.get("ZipCode") or "").strip()[:5] or None
                raw_addr = str(r.get("Address") or "").strip() or None

                parcels[pin].update({
                    "situs_address": raw_addr or parcels[pin]["situs_address"],
                    "zip_code": raw_zip or parcels[pin]["zip_code"],
                    "year_built": to_int(r.get("YrBuilt")),
                    "square_footage": living,
                    "bedrooms": to_zero_or_int(r.get("Bedrooms")) if r.get("Bedrooms") not in (None, "") else None,
                    "bath_full": full_b if (r.get("BathFullCount") not in (None, "") or r.get("Bath3qtrCount") not in (None, "")) else None,
                    "bath_half": half_b if r.get("BathHalfCount") not in (None, "") else None,
                    "building_grade": to_int(r.get("BldgGrade")),
                    "building_condition": to_int(r.get("Condition")),
                })
                bldg_matched += 1

    print(f"   Merged structural attributes for {bldg_matched:,} King County residential buildings.")
    return parcels


def parse_snohomish_county(staging_dir):
    assessor_path = os.path.join(staging_dir, "snoco-assessor.csv")
    sales_path = os.path.join(staging_dir, "snoco-sales.csv")

    if not os.path.exists(assessor_path):
        print("⚠️ Missing snoco-assessor.csv in data/staging/. Skipping Snohomish County.")
        return {}

    yr_built_map = {}
    if os.path.exists(sales_path):
        with open(sales_path, "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f)
            for r in reader:
                pid = str(r.get("PARCEL_ID") or "").strip().replace("-", "")
                yb = to_int(r.get("YEAR_BUILT"))
                if pid and yb and 1850 <= yb <= 2030:
                    yr_built_map[pid] = yb

    print("📂 Reading Snohomish County snoco-assessor.csv...")
    parcels = {}
    with open(assessor_path, "r", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        for r in reader:
            raw_pid = str(r.get("parcel_number") or r.get("PropId") or "").strip().replace("-", "")
            if not raw_pid:
                continue

            unit = str(r.get("UnitMeas") or "SF").strip().upper()
            raw_size = r.get("SIZE")
            lot_sqft = None
            if raw_size not in (None, ""):
                try:
                    size_float = float(str(raw_size).strip())
                    if size_float > 0:
                        lot_sqft = int(round(size_float * 43560.0)) if unit == "AC" else int(round(size_float))
                except (ValueError, TypeError):
                    pass

            line1 = str(r.get("SitusLine1") or "").strip()
            line2 = str(r.get("SitusLine2") or "").strip()
            addr = f"{line1} {line2}".strip() if line1 else None

            city = str(r.get("SitusCity") or "").strip()
            slug = slugify_neighborhood(city)
            zip_code = str(r.get("SitusZip") or "").strip()[:5] or None

            mkttl = to_int(r.get("MKTTL"))
            if not mkttl:
                lnd = to_zero_or_int(r.get("MKLND"))
                imp = to_zero_or_int(r.get("MKIMP"))
                mkttl = (lnd + imp) if (lnd + imp) > 0 else None

            use_code = str(r.get("UseCode") or "R").strip()[:10] or "R"

            parcels[raw_pid] = {
                "parcel_number": raw_pid,
                "major_code": raw_pid[:6].ljust(6, "0"),
                "minor_code": raw_pid[6:10].ljust(4, "0"),
                "property_type": use_code,
                "neighborhood_slug": slug,
                "situs_address": addr,
                "zip_code": zip_code,
                "year_built": yr_built_map.get(raw_pid),
                "square_footage": None,
                "lot_sqft": lot_sqft,
                "bedrooms": None,
                "bath_full": None,
                "bath_half": None,
                "building_grade": None,
                "building_condition": None,
                "view_mountain": 0,
                "view_water": 0,
                "waterfront_type": 0,
                "assessed_value_total": mkttl,
                "county": "SNOHOMISH",
            }

    print(f"   Loaded {len(parcels):,} Snohomish County parcel records.")
    return parcels


def build_upsert_sql(value_rows):
    return f"""
    INSERT INTO base (
        parcel_number, major_code, minor_code, property_type, neighborhood_slug,
        situs_address, zip_code, year_built, square_footage, lot_sqft,
        bedrooms, bath_full, bath_half, building_grade, building_condition,
        view_mountain, view_water, waterfront_type, assessed_value_total,
        county, latitude, longitude, updated_utc
    ) VALUES
    {",".join(value_rows)}
    ON CONFLICT(parcel_number) DO UPDATE SET
        situs_address = COALESCE(excluded.situs_address, base.situs_address),
        zip_code = COALESCE(excluded.zip_code, base.zip_code),
        neighborhood_slug = CASE
            WHEN base.neighborhood_slug IS NULL OR base.neighborhood_slug = 'unincorporated'
            THEN excluded.neighborhood_slug
            ELSE base.neighborhood_slug
        END,
        year_built = COALESCE(excluded.year_built, base.year_built),
        square_footage = COALESCE(excluded.square_footage, base.square_footage),
        lot_sqft = COALESCE(excluded.lot_sqft, base.lot_sqft),
        bedrooms = COALESCE(excluded.bedrooms, base.bedrooms),
        bath_full = COALESCE(excluded.bath_full, base.bath_full),
        bath_half = COALESCE(excluded.bath_half, base.bath_half),
        building_grade = COALESCE(excluded.building_grade, base.building_grade),
        building_condition = COALESCE(excluded.building_condition, base.building_condition),
        view_mountain = MAX(excluded.view_mountain, COALESCE(base.view_mountain, 0)),
        view_water = MAX(excluded.view_water, COALESCE(base.view_water, 0)),
        waterfront_type = CASE
            WHEN excluded.waterfront_type > 0 THEN excluded.waterfront_type
            ELSE COALESCE(base.waterfront_type, 0)
        END,
        assessed_value_total = COALESCE(excluded.assessed_value_total, base.assessed_value_total),
        county = COALESCE(excluded.county, base.county),
        updated_utc = CURRENT_TIMESTAMP;
    """


def upsert_parcels_to_d1(session, endpoint, headers, records_dict):
    records = list(records_dict.values())
    total = len(records)
    if total == 0:
        print("ℹ️ No records to upsert.")
        return

    print(f"🚀 Streaming {total:,} normalized parcels to Cloudflare D1 'base' (byte ceiling: {MAX_SQL_BYTES:,}B, max rows: {MAX_BATCH_ROWS})...")

    wrapper_overhead = len(build_upsert_sql(["()"]).encode("utf-8"))
    current_rows = []
    current_bytes = wrapper_overhead
    committed = 0

    for p in records:
        row_tuple = (
            f"({sql_val(p['parcel_number'])}, {sql_val(p['major_code'])}, {sql_val(p['minor_code'])}, "
            f"{sql_val(p['property_type'])}, {sql_val(p['neighborhood_slug'])}, {sql_val(p['situs_address'])}, "
            f"{sql_val(p['zip_code'])}, {sql_val(p['year_built'])}, {sql_val(p['square_footage'])}, "
            f"{sql_val(p['lot_sqft'])}, {sql_val(p['bedrooms'])}, {sql_val(p['bath_full'])}, "
            f"{sql_val(p['bath_half'])}, {sql_val(p['building_grade'])}, {sql_val(p['building_condition'])}, "
            f"{sql_val(p['view_mountain'])}, {sql_val(p['view_water'])}, {sql_val(p['waterfront_type'])}, "
            f"{sql_val(p['assessed_value_total'])}, {sql_val(p['county'])}, 0.0, 0.0, CURRENT_TIMESTAMP)"
        )
        row_bytes = len(row_tuple.encode("utf-8")) + 1

        if current_rows and (len(current_rows) >= MAX_BATCH_ROWS or (current_bytes + row_bytes) > MAX_SQL_BYTES):
            execute_d1_query(session, endpoint, headers, build_upsert_sql(current_rows))
            committed += len(current_rows)
            print(f"\r   Committed: {committed:,} / {total:,}", end="", flush=True)
            current_rows = []
            current_bytes = wrapper_overhead

        current_rows.append(row_tuple)
        current_bytes += row_bytes

    if current_rows:
        execute_d1_query(session, endpoint, headers, build_upsert_sql(current_rows))
        committed += len(current_rows)
        print(f"\r   Committed: {committed:,} / {total:,}", end="", flush=True)

    print("\n✅ Phase 1 Base Attribute Seeding Complete.")


def main():
    parser = argparse.ArgumentParser(description="Seed King & Snohomish parcel attributes into Cloudflare D1.")
    parser.add_argument("--snoco-only", action="store_true", help="Skip King County and ingest Snohomish County only.")
    parser.add_argument("--kc-only", action="store_true", help="Skip Snohomish County and ingest King County only.")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    load_dev_vars(base_dir)

    cf_account_id = os.environ.get("CF_ACCOUNT_ID")
    cf_api_token = os.environ.get("CF_D1_API_TOKEN")
    cf_db_id = os.environ.get("CF_DATABASE_PARCELDATA_ID")

    if not all([cf_account_id, cf_api_token, cf_db_id]):
        raise ValueError("Missing Cloudflare D1 credentials in .dev.vars or .env.")

    staging_dir = os.path.join(base_dir, "data", "staging")
    endpoint = f"https://api.cloudflare.com/client/v4/accounts/{cf_account_id}/d1/database/{cf_db_id}/query"
    headers = {
        "Authorization": f"Bearer {cf_api_token}",
        "Content-Type": "application/json"
    }

    session = requests.Session()

    if not args.snoco_only:
        kc_records = parse_king_county(staging_dir)
        upsert_parcels_to_d1(session, endpoint, headers, kc_records)

    if not args.kc_only:
        snoco_records = parse_snohomish_county(staging_dir)
        upsert_parcels_to_d1(session, endpoint, headers, snoco_records)


if __name__ == "__main__":
    main()