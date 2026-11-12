import os
import io
import re
import csv
import hashlib
import zipfile
import datetime
import argparse
from collections import Counter
import requests

MAX_BASE_ROWS = 200
MAX_SALES_ROWS = 150
MAX_SQL_BYTES = 75000  # Strict safety ceiling below D1's 102,400-byte SQLITE_TOOBIG limit
MIN_SALE_PRICE = 50000
SALES_LOOKBACK_DAYS = 730

KC_NON_ARMS_LENGTH_WARNINGS = {
    "7", "8", "9", "11", "12", "13", "14", "15", "16", "18",
    "20", "21", "22", "23", "24", "25", "26", "28", "29", "31",
    "32", "33", "34", "35", "36", "45", "46", "49", "51", "52",
    "53", "54", "59", "60", "61", "62"
}

KC_INSTRUMENT_MAP = {
    "2": "WARRANTY DEED",
    "3": "STATUTORY WARRANTY DEED",
    "4": "SPECIAL WARRANTY DEED",
    "15": "QUITCLAIM DEED",
    "18": "TRUSTEES DEED",
    "22": "EXECUTORS DEED",
    "24": "BARGAIN AND SALE DEED",
    "26": "REAL ESTATE CONTRACT"
}


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


def parse_price(raw_price):
    if raw_price is None:
        return 0
    cleaned = str(raw_price).replace("$", "").replace(",", "").strip()
    if not cleaned:
        return 0
    try:
        return int(float(cleaned))
    except (ValueError, TypeError):
        return 0


def normalize_date(raw_date):
    """Returns (iso_date_str, is_month_only) or (None, False)."""
    if not raw_date:
        return None, False
    s = str(raw_date).strip()

    if s.replace(".", "", 1).isdigit() and len(s.split(".")[0]) >= 12:
        try:
            dt = datetime.datetime.fromtimestamp(float(s) / 1000.0, tz=datetime.timezone.utc)
            return dt.strftime("%Y-%m-%d"), False
        except (ValueError, OSError):
            return None, False

    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10], False

    try:
        dt = datetime.datetime.strptime(s, "%b-%Y")
        return dt.strftime("%Y-%m-01"), True
    except ValueError:
        pass

    parts = s.split(" ")[0].split("/")
    if len(parts) == 3:
        if len(parts[0]) == 4 and parts[0].isdigit():
            y, m, d = parts[0], parts[1].zfill(2), parts[2].zfill(2)
            return f"{y}-{m}-{d}", False
        m, d, y = parts[0].zfill(2), parts[1].zfill(2), parts[2]
        if len(y) == 4 and y.isdigit():
            return f"{y}-{m}-{d}", False

    return None, False


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
        raise RuntimeError(f"D1 Delta Sync Failed: {data.get('errors', [])}")
    return data


def classify_kc_residential_type(prop_type, present_use, minor_code):
    """Maps King County PropType/PresentUse to canonical taxonomy or returns None if non-residential."""
    pt = (prop_type or "").strip().upper()
    pu = to_zero_or_int(present_use)

    if pt == "K" or minor_code == "0000" or pu == 300:
        return "Condo"
    if pu == 29:
        return "Townhouse"
    if pu in {2, 6}:
        return "Single Family"
    if pu in {3, 4, 5}:
        return "Multi-Family"
    if pu in {7, 8, 9}:
        return "Manufactured / Mobile"
    if pt == "R" and pu in {0, 1}:
        return "Vacant Land"
    if pt == "R":
        return "Residential"
    return None


def classify_snoco_residential_type(use_code_raw):
    """Maps Snohomish UseCode to canonical taxonomy or returns None if non-residential."""
    raw = str(use_code_raw or "").strip()
    if not raw:
        return "Residential"
    digits = "".join(ch for ch in raw[:4] if ch.isdigit())
    if not digits:
        return "Residential"
    code = int(digits)
    if code in {110, 111, 112, 113, 114, 115, 116}:
        return "Single Family"
    if code in {117, 118}:
        return "Manufactured / Mobile"
    if 120 <= code <= 129:
        return "Multi-Family"
    if 140 <= code <= 149 or code == 915:
        return "Condo"
    if code in {910, 911, 914}:
        return "Vacant Land"
    return None


def fetch_snohomish_deltas(days_back=35, staging_dir=None):
    """Harvests newly platted and modified residential parcels from Snohomish County Open GIS."""
    print(f"📡 Polling Snohomish County Open GIS (past {days_back} days)...")
    base_url = "https://gis.snoco.org/arcgis/rest/services/Cadastral/Parcels/MapServer/0/query"
    where_clause = f"CORRDATE >= CURRENT_TIMESTAMP - {days_back} AND PARCEL_ID IS NOT NULL"

    normalized = []
    delta_pins = []
    offset = 0
    page_size = 2000

    try:
        while True:
            params = {
                "where": where_clause,
                "outFields": "PARCEL_ID,SITUSLINE1,SITUSCITY,SITUSZIP,USECODE,PLATNAME,GIS_SQ_FT,MKTTL,MKLND,MKIMP",
                "returnGeometry": "false",
                "resultOffset": offset,
                "resultRecordCount": page_size,
                "f": "json"
            }
            res = requests.get(base_url, params=params, timeout=60)
            res.raise_for_status()
            payload = res.json()
            features = payload.get("features", [])
            if not features:
                break

            for f in features:
                attr = f.get("attributes", {})
                raw_pid = str(attr.get("PARCEL_ID") or "").strip().replace("-", "")
                if not raw_pid:
                    continue
                pid = raw_pid.zfill(14) if raw_pid.isdigit() else raw_pid

                plat_name = str(attr.get("PLATNAME") or "").strip() or None
                prop_type = classify_snoco_residential_type(attr.get("USECODE"))

                # Shield newly platted subdivisions even if UseCode is still unimproved
                if not prop_type and not plat_name:
                    continue
                if not prop_type and plat_name:
                    prop_type = "Vacant Land"

                total_val = to_int(attr.get("MKTTL"))
                if not total_val:
                    lnd = to_zero_or_int(attr.get("MKLND"))
                    imp = to_zero_or_int(attr.get("MKIMP"))
                    total_val = (lnd + imp) if (lnd + imp) > 0 else None

                # GIS_SQ_FT is land area -> map strictly to lot_sqft, NEVER square_footage
                lot_size = to_int(attr.get("GIS_SQ_FT"))
                zip_code = str(attr.get("SITUSZIP") or "").strip()[:5] or None
                situs_addr = str(attr.get("SITUSLINE1") or "").strip() or None

                normalized.append({
                    "parcel_number": pid,
                    "major_code": pid[:6].ljust(6, "0"),
                    "minor_code": pid[6:10].ljust(4, "0"),
                    "property_type": prop_type,
                    "situs_address": situs_addr,
                    "zip_code": zip_code,
                    "neighborhood_slug": slugify_neighborhood(attr.get("SITUSCITY")),
                    "complex_or_plat_name": plat_name,
                    "lot_sqft": lot_size,
                    "square_footage": None,
                    "bedrooms": None,
                    "bath_full": None,
                    "bath_half": None,
                    "building_grade": None,
                    "building_condition": None,
                    "year_built": None,
                    "view_mountain": 0,
                    "view_water": 0,
                    "waterfront_type": 0,
                    "assessed_value_total": total_val,
                    "county": "SNOHOMISH"
                })
                if prop_type != "Vacant Land":
                    delta_pins.append(pid)

            if len(features) < page_size:
                break
            offset += page_size

        print(f"   Located {len(normalized):,} modified/new Snohomish residential parcels.")

        # Export modified Snohomish pins so the GLA + Photo/Sketch harvester refreshes them
        if staging_dir and delta_pins:
            os.makedirs(staging_dir, exist_ok=True)
            queue_path = os.path.join(staging_dir, "snoco_delta_queue.txt")
            with open(queue_path, "w", encoding="utf-8") as qf:
                for p in sorted(set(delta_pins)):
                    qf.write(f"{p}\n")
            print(f"   Queued {len(set(delta_pins)):,} Snohomish pins for GLA/media refresh -> {queue_path}")

        return normalized
    except Exception as e:
        print(f"   ⚠️ Snohomish delta query warning: {e}")
        return []


def fetch_king_deltas(session):
    """Downloads King County Assessor weekly update archives and parses residential structural/value deltas."""
    print("📥 Downloading King County Assessor weekly data archives...")
    urls = {
        "parcel": "https://dorcdn.kingcounty.gov/datadownload/Parcel.zip",
        "resbldg": "https://dorcdn.kingcounty.gov/datadownload/ResBldg.zip",
        "rpacct": "https://dorcdn.kingcounty.gov/datadownload/RPAcct_NoName.zip"
    }

    mtn_cols = ["MtRainier", "Olympics", "Cascades"]
    water_cols = ["PugetSound", "LakeWashington", "LakeSammamish", "SmallLakeRiverCreek"]

    # 1. Download & Map Residential Parcels from Parcel.zip
    pin_parcel = {}
    try:
        res_parcel = session.get(urls["parcel"], timeout=120)
        res_parcel.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(res_parcel.content)) as z:
            target = [name for name in z.namelist() if name.lower().endswith('.csv')][0]
            with z.open(target) as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding='utf-8', errors='ignore'))
                for r in reader:
                    maj = str(r.get('Major', '')).strip().zfill(6)
                    minr = str(r.get('Minor', '')).strip().zfill(4)
                    if maj == "000000" and minr == "0000":
                        continue
                    pin = f"{maj}{minr}"

                    prop_type = classify_kc_residential_type(r.get("PropType"), r.get("PresentUse"), minr)
                    if not prop_type:
                        continue

                    view_mtn = 1 if any(to_zero_or_int(r.get(c)) > 0 for c in mtn_cols) else 0
                    view_wtr = 1 if any(to_zero_or_int(r.get(c)) > 0 for c in water_cols) else 0
                    wfnt = to_zero_or_int(r.get("WfntLocation"))

                    pin_parcel[pin] = {
                        "major_code": maj,
                        "minor_code": minr,
                        "property_type": prop_type,
                        "lot_sqft": to_int(r.get("SqFtLot")),
                        "view_mountain": view_mtn,
                        "view_water": view_wtr,
                        "waterfront_type": wfnt,
                    }
        print(f"   Extracted {len(pin_parcel):,} residential parcel records from King County Parcel.zip.")
    except Exception as e:
        print(f"   ⚠️ King County Parcel.zip warning: {e}")

    # 2. Download & Map Situs Address + Structural Attributes from ResBldg.zip
    pin_bldg = {}
    try:
        res_bldg = session.get(urls["resbldg"], timeout=120)
        res_bldg.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(res_bldg.content)) as z:
            target = [name for name in z.namelist() if name.lower().endswith('.csv')][0]
            with z.open(target) as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding='utf-8', errors='ignore'))
                for r in reader:
                    maj = str(r.get('Major', '')).strip().zfill(6)
                    minr = str(r.get('Minor', '')).strip().zfill(4)
                    pin = f"{maj}{minr}"

                    living = to_int(r.get('SqFtTotLiving'))
                    existing = pin_bldg.get(pin)
                    if existing and (existing.get("square_footage") or 0) > (living or 0):
                        continue

                    full_b = to_zero_or_int(r.get('BathFullCount')) + to_zero_or_int(r.get('Bath3qtrCount'))
                    has_full = r.get('BathFullCount') not in (None, "") or r.get('Bath3qtrCount') not in (None, "")
                    half_b = to_zero_or_int(r.get('BathHalfCount'))

                    pin_bldg[pin] = {
                        "situs_address": str(r.get('Address') or '').strip() or None,
                        "zip_code": str(r.get('ZipCode') or '').strip()[:5] or None,
                        "square_footage": living,
                        "bedrooms": to_zero_or_int(r.get('Bedrooms')) if r.get('Bedrooms') not in (None, "") else None,
                        "bath_full": full_b if has_full else None,
                        "bath_half": half_b if r.get('BathHalfCount') not in (None, "") else None,
                        "building_grade": to_int(r.get('BldgGrade')),
                        "building_condition": to_int(r.get('Condition')),
                        "year_built": to_int(r.get('YrBuilt')),
                    }
        print(f"   Extracted {len(pin_bldg):,} residential structures from King County ResBldg.zip.")
    except Exception as e:
        print(f"   ⚠️ King County ResBldg.zip warning: {e}")

    # 3. Download Assessed Values from RPAcct_NoName.zip (Ignore mailing CityState to prevent out-of-state pollution)
    pin_assessed = {}
    try:
        res_rpacct = session.get(urls["rpacct"], timeout=120)
        res_rpacct.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(res_rpacct.content)) as z:
            target = [name for name in z.namelist() if name.lower().endswith('.csv')][0]
            with z.open(target) as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding='utf-8', errors='ignore'))
                for r in reader:
                    maj = str(r.get('Major', '')).strip().zfill(6)
                    minr = str(r.get('Minor', '')).strip().zfill(4)
                    pin = f"{maj}{minr}"
                    if pin not in pin_parcel and pin not in pin_bldg:
                        continue
                    try:
                        land = float(r.get('ApprLandVal') or 0)
                        impr = float(r.get('ApprImprVal') or 0)
                        total_val = int(land + impr)
                        if total_val > 0:
                            pin_assessed[pin] = max(pin_assessed.get(pin, 0), total_val)
                    except (ValueError, TypeError):
                        pass
        print(f"   Extracted {len(pin_assessed):,} assessed valuations from King County RPAcct_NoName.zip.")
    except Exception as e:
        print(f"   ⚠️ King County RPAcct_NoName.zip warning: {e}")

    all_kc_pins = set(pin_parcel.keys()) | set(pin_bldg.keys())
    king_updates = []
    for pin in all_kc_pins:
        p_meta = pin_parcel.get(pin, {})
        b_meta = pin_bldg.get(pin, {})
        maj = p_meta.get("major_code") or pin[:6]
        minr = p_meta.get("minor_code") or pin[6:10]
        prop_type = p_meta.get("property_type") or ("Condo" if minr == "0000" else "Single Family")

        king_updates.append({
            "parcel_number": pin,
            "major_code": maj,
            "minor_code": minr,
            "property_type": prop_type,
            "situs_address": b_meta.get("situs_address"),
            "zip_code": b_meta.get("zip_code"),
            "neighborhood_slug": "unincorporated",
            "complex_or_plat_name": None,
            "lot_sqft": p_meta.get("lot_sqft"),
            "square_footage": b_meta.get("square_footage"),
            "bedrooms": b_meta.get("bedrooms"),
            "bath_full": b_meta.get("bath_full"),
            "bath_half": b_meta.get("bath_half"),
            "building_grade": b_meta.get("building_grade"),
            "building_condition": b_meta.get("building_condition"),
            "year_built": b_meta.get("year_built"),
            "view_mountain": p_meta.get("view_mountain", 0),
            "view_water": p_meta.get("view_water", 0),
            "waterfront_type": p_meta.get("waterfront_type", 0),
            "assessed_value_total": pin_assessed.get(pin),
            "county": "KING"
        })

    print(f"   Compiled {len(king_updates):,} clean King County residential records.")
    return king_updates


def build_base_upsert_sql(value_rows):
    return f"""
    INSERT INTO base (
        parcel_number, major_code, minor_code, property_type, neighborhood_slug,
        situs_address, zip_code, complex_or_plat_name, year_built, square_footage,
        lot_sqft, bedrooms, bath_full, bath_half, building_grade, building_condition,
        view_mountain, view_water, waterfront_type, assessed_value_total,
        county, latitude, longitude, updated_utc
    ) VALUES
    {",".join(value_rows)}
    ON CONFLICT(parcel_number) DO UPDATE SET
        property_type = COALESCE(excluded.property_type, base.property_type),
        situs_address = COALESCE(excluded.situs_address, base.situs_address),
        zip_code = COALESCE(excluded.zip_code, base.zip_code),
        complex_or_plat_name = COALESCE(excluded.complex_or_plat_name, base.complex_or_plat_name),
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


def sync_upserts_to_d1(session, endpoint, headers, updates):
    total = len(updates)
    if total == 0:
        print("ℹ️ No parcel attribute deltas to sync.")
        return

    print(f"🚀 Upserting {total:,} parcels into D1 'base' (byte ceiling: {MAX_SQL_BYTES:,}B, max rows: {MAX_BASE_ROWS})...")
    wrapper_overhead = len(build_base_upsert_sql(["()"]).encode("utf-8"))
    current_rows = []
    current_bytes = wrapper_overhead
    committed = 0

    for item in updates:
        row_tuple = (
            f"({sql_val(item['parcel_number'])}, {sql_val(item['major_code'])}, {sql_val(item['minor_code'])}, "
            f"{sql_val(item['property_type'])}, {sql_val(item['neighborhood_slug'])}, {sql_val(item.get('situs_address'))}, "
            f"{sql_val(item.get('zip_code'))}, {sql_val(item.get('complex_or_plat_name'))}, {sql_val(item.get('year_built'))}, "
            f"{sql_val(item.get('square_footage'))}, {sql_val(item.get('lot_sqft'))}, {sql_val(item.get('bedrooms'))}, "
            f"{sql_val(item.get('bath_full'))}, {sql_val(item.get('bath_half'))}, {sql_val(item.get('building_grade'))}, "
            f"{sql_val(item.get('building_condition'))}, {sql_val(item.get('view_mountain', 0))}, {sql_val(item.get('view_water', 0))}, "
            f"{sql_val(item.get('waterfront_type', 0))}, {sql_val(item.get('assessed_value_total'))}, {sql_val(item['county'])}, "
            f"0.0, 0.0, CURRENT_TIMESTAMP)"
        )
        row_bytes = len(row_tuple.encode("utf-8")) + 1

        if current_rows and (len(current_rows) >= MAX_BASE_ROWS or (current_bytes + row_bytes) > MAX_SQL_BYTES):
            execute_d1_query(session, endpoint, headers, build_base_upsert_sql(current_rows))
            committed += len(current_rows)
            print(f"\r   Committed base rows: {committed:,} / {total:,}", end="", flush=True)
            current_rows = []
            current_bytes = wrapper_overhead

        current_rows.append(row_tuple)
        current_bytes += row_bytes

    if current_rows:
        execute_d1_query(session, endpoint, headers, build_base_upsert_sql(current_rows))
        committed += len(current_rows)
        print(f"\r   Committed base rows: {committed:,} / {total:,}", end="", flush=True)

    print("\n✅ Base delta sync complete.")


def fetch_valid_parcel_keys(session, endpoint, headers):
    print("🔍 Indexing valid parcel_number keys from Cloudflare D1 'base'...")
    valid_pins = set()
    page_size = 100000
    offset = 0

    while True:
        sql = f"SELECT parcel_number FROM base LIMIT {page_size} OFFSET {offset};"
        data = execute_d1_query(session, endpoint, headers, sql)
        rows = data.get("result", [{}])[0].get("results", [])
        if not rows:
            break
        for r in rows:
            valid_pins.add(r["parcel_number"])
        offset += page_size
        print(f"\r   Indexed {len(valid_pins):,} valid parcels...", end="", flush=True)

    print(f"\n   Total valid foreign-key targets: {len(valid_pins):,}")
    return valid_pins


def sync_sales_deltas(session, endpoint, headers, valid_pins):
    """Syncs rolling 24-month sales from King County Real Property Sales.zip and Snohomish ArcGIS Sales."""
    cutoff_date = (datetime.date.today() - datetime.timedelta(days=SALES_LOOKBACK_DAYS)).isoformat()
    month_cutoff = cutoff_date[:7] + "-01"
    print(f"📈 Syncing rolling 24-month sales ledger (cutoff >= {cutoff_date})...")

    transactions = []
    seen_keys = set()

    # 1. King County Weekly Sales Archive
    kc_sales_url = "https://dorcdn.kingcounty.gov/datadownload/Real%20Property%20Sales.zip"
    try:
        res = session.get(kc_sales_url, timeout=120)
        res.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(res.content)) as z:
            target = [name for name in z.namelist() if name.lower().endswith('.csv')][0]
            with z.open(target) as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding='utf-8', errors='ignore'))
                for r in reader:
                    maj = str(r.get("Major", "")).strip().zfill(6)
                    minr = str(r.get("Minor", "")).strip().zfill(4)
                    pin = f"{maj}{minr}"
                    if pin not in valid_pins:
                        continue

                    iso_date, _ = normalize_date(r.get("DocumentDate"))
                    if not iso_date or iso_date < cutoff_date:
                        continue

                    price = parse_price(r.get("SalePrice"))
                    if price < MIN_SALE_PRICE:
                        continue

                    rec_nbr = str(r.get("RecordingNbr") or "").strip()
                    excise_nbr = str(r.get("ExciseTaxNbr") or "").strip() or None
                    if not rec_nbr:
                        rec_nbr = "KC-" + hashlib.sha256(f"{pin}|{iso_date}|{price}|{excise_nbr or ''}".encode("utf-8")).hexdigest()[:16]

                    dedup_key = (pin, iso_date, price, rec_nbr)
                    if dedup_key in seen_keys:
                        continue
                    seen_keys.add(dedup_key)

                    raw_warnings = str(r.get("SaleWarning") or "").strip()
                    warning_tokens = set(raw_warnings.split())
                    has_warning = bool(warning_tokens & KC_NON_ARMS_LENGTH_WARNINGS)
                    inst_code = str(r.get("SaleInstrument") or "").strip()
                    deed_type = KC_INSTRUMENT_MAP.get(inst_code, f"CODE_{inst_code}" if inst_code else "DEED")
                    if inst_code == "15":
                        has_warning = True

                    transactions.append({
                        "parcel_number": pin,
                        "county": "KING",
                        "document_date": iso_date,
                        "sale_price": price,
                        "recording_number": rec_nbr,
                        "excise_tax_number": excise_nbr,
                        "deed_type": deed_type,
                        "sale_warning_code": raw_warnings or None,
                        "is_arms_length": 0 if has_warning else 1,
                        "seller_name": str(r.get("SellerName") or "").strip()[:120] or None,
                        "buyer_name": str(r.get("BuyerName") or "").strip()[:120] or None,
                    })
        print(f"   Parsed {len(transactions):,} King County 24-month sales.")
    except Exception as e:
        print(f"   ⚠️ King County sales sync warning: {e}")

    # 2. Snohomish County Recent Sales ArcGIS FeatureServer
    snoco_sales_url = "https://gis.snoco.org/arcgis/rest/services/Cadastral/Sales/MapServer/0/query"
    snoco_raw = []
    date_price_counts = Counter()
    offset = 0
    page_size = 2000

    try:
        while True:
            params = {
                "where": f"SALE_PRICE >= {MIN_SALE_PRICE} AND PARCEL_ID IS NOT NULL",
                "outFields": "PARCEL_ID,SALE_PRICE,TRNSF_DATE,PROP_CLASS",
                "returnGeometry": "false",
                "resultOffset": offset,
                "resultRecordCount": page_size,
                "f": "json"
            }
            res = session.get(snoco_sales_url, params=params, timeout=60)
            res.raise_for_status()
            features = res.json().get("features", [])
            if not features:
                break

            for feat in features:
                attr = feat.get("attributes", {})
                raw_pin = str(attr.get("PARCEL_ID") or "").strip().replace("-", "")
                if not raw_pin:
                    continue
                pin = raw_pin.zfill(14) if raw_pin.isdigit() else raw_pin
                if pin not in valid_pins:
                    if raw_pin in valid_pins:
                        pin = raw_pin
                    else:
                        continue

                iso_date, is_month_only = normalize_date(attr.get("TRNSF_DATE"))
                if not iso_date:
                    continue
                if iso_date < (month_cutoff if is_month_only else cutoff_date):
                    continue

                price = parse_price(attr.get("SALE_PRICE"))
                if price < MIN_SALE_PRICE:
                    continue

                date_price_counts[(iso_date, price)] += 1
                snoco_raw.append((pin, iso_date, price, attr))

            if len(features) < page_size:
                break
            offset += page_size

        snoco_added = 0
        for pin, iso_date, price, attr in snoco_raw:
            synth_rec = "SNOCO-" + hashlib.sha256(f"{pin}|{iso_date}|{price}".encode("utf-8")).hexdigest()[:16]
            if (pin, iso_date, price, synth_rec) in seen_keys:
                continue
            seen_keys.add((pin, iso_date, price, synth_rec))

            is_multi = date_price_counts[(iso_date, price)] > 1
            prop_class = str(attr.get("PROP_CLASS") or "").strip()
            is_res = classify_snoco_residential_type(prop_class) is not None

            warnings = []
            if is_multi:
                warnings.append("MULTI_PARCEL")
            if not is_res:
                warnings.append(f"NON_RES_CLASS_{prop_class}")

            transactions.append({
                "parcel_number": pin,
                "county": "SNOHOMISH",
                "document_date": iso_date,
                "sale_price": price,
                "recording_number": synth_rec,
                "excise_tax_number": None,
                "deed_type": f"CLASS_{prop_class}" if prop_class else "STATUTORY WARRANTY DEED",
                "sale_warning_code": " ".join(warnings) if warnings else None,
                "is_arms_length": 0 if warnings else 1,
                "seller_name": None,
                "buyer_name": None,
            })
            snoco_added += 1

        print(f"   Parsed {snoco_added:,} Snohomish County 24-month sales.")
    except Exception as e:
        print(f"   ⚠️ Snohomish County sales sync warning: {e}")

    if not transactions:
        print("ℹ️ No sales transactions found to sync.")
        return

    def build_sales_sql(rows):
        return f"""
        INSERT OR IGNORE INTO sales_transactions (
            parcel_number, county, document_date, sale_price,
            recording_number, excise_tax_number, deed_type,
            sale_warning_code, is_arms_length, seller_name,
            buyer_name, created_utc
        ) VALUES
        {",".join(rows)};
        """

    wrapper_overhead = len(build_sales_sql(["()"]).encode("utf-8"))
    current_rows = []
    current_bytes = wrapper_overhead
    committed = 0
    latest_arms_length = {}

    for tx in transactions:
        pin = tx["parcel_number"]
        if tx["is_arms_length"] == 1:
            prev = latest_arms_length.get(pin)
            if not prev or tx["document_date"] > prev[0]:
                latest_arms_length[pin] = (tx["document_date"], tx["sale_price"])

        row_tuple = (
            f"({sql_val(pin)}, {sql_val(tx['county'])}, {sql_val(tx['document_date'])}, "
            f"{sql_val(tx['sale_price'])}, {sql_val(tx['recording_number'])}, {sql_val(tx['excise_tax_number'])}, "
            f"{sql_val(tx['deed_type'])}, {sql_val(tx['sale_warning_code'])}, {sql_val(tx['is_arms_length'])}, "
            f"{sql_val(tx['seller_name'])}, {sql_val(tx['buyer_name'])}, CURRENT_TIMESTAMP)"
        )
        row_bytes = len(row_tuple.encode("utf-8")) + 1

        if current_rows and (len(current_rows) >= MAX_SALES_ROWS or (current_bytes + row_bytes) > MAX_SQL_BYTES):
            execute_d1_query(session, endpoint, headers, build_sales_sql(current_rows))
            committed += len(current_rows)
            print(f"\r   Committed sales: {committed:,} / {len(transactions):,}", end="", flush=True)
            current_rows = []
            current_bytes = wrapper_overhead

        current_rows.append(row_tuple)
        current_bytes += row_bytes

    if current_rows:
        execute_d1_query(session, endpoint, headers, build_sales_sql(current_rows))
        committed += len(current_rows)
        print(f"\r   Committed sales: {committed:,} / {len(transactions):,}", end="", flush=True)

    print("\n🔄 Updating latest arm's-length sale snapshots on 'base'...")
    latest_items = list(latest_arms_length.items())
    upd_stmts = []
    upd_bytes = 0
    upd_committed = 0

    for pin, (dt, pr) in latest_items:
        stmt = (
            f"UPDATE base SET last_sale_date = {sql_val(dt)}, last_sale_price = {sql_val(pr)}, updated_utc = CURRENT_TIMESTAMP "
            f"WHERE parcel_number = {sql_val(pin)} AND (last_sale_date IS NULL OR last_sale_date < {sql_val(dt)});"
        )
        stmt_bytes = len(stmt.encode("utf-8")) + 1
        if upd_stmts and (len(upd_stmts) >= 100 or (upd_bytes + stmt_bytes) > MAX_SQL_BYTES):
            execute_d1_query(session, endpoint, headers, "\n".join(upd_stmts))
            upd_committed += len(upd_stmts)
            print(f"\r   Updated base snapshots: {upd_committed:,} / {len(latest_items):,}", end="", flush=True)
            upd_stmts = []
            upd_bytes = 0
        upd_stmts.append(stmt)
        upd_bytes += stmt_bytes

    if upd_stmts:
        execute_d1_query(session, endpoint, headers, "\n".join(upd_stmts))
        upd_committed += len(upd_stmts)
        print(f"\r   Updated base snapshots: {upd_committed:,} / {len(latest_items):,}", end="", flush=True)

    print("\n✅ Sales ledger delta sync complete.")


def main():
    parser = argparse.ArgumentParser(description="Automated dual-county parcel & sales delta sync for D1.")
    parser.add_argument("--days-back", type=int, default=35, help="Lookback window in days for Snohomish GIS deltas.")
    parser.add_argument("--skip-sales", action="store_true", help="Sync parcel attributes only and skip sales ledger.")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    staging_dir = os.path.join(base_dir, "data", "staging")
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

    # 1. Harvest & Upsert Snohomish County Parcel Deltas
    snohomish_deltas = fetch_snohomish_deltas(days_back=args.days_back, staging_dir=staging_dir)
    sync_upserts_to_d1(session, endpoint, headers, snohomish_deltas)

    # 2. Harvest & Upsert King County Residential Parcel Deltas
    king_deltas = fetch_king_deltas(session)
    sync_upserts_to_d1(session, endpoint, headers, king_deltas)

    # 3. Sync Rolling 24-Month Sales Ledger
    if not args.skip_sales:
        valid_pins = fetch_valid_parcel_keys(session, endpoint, headers)
        sync_sales_deltas(session, endpoint, headers, valid_pins)


if __name__ == "__main__":
    main()