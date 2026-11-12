import os
import csv
import hashlib
import datetime
import argparse
from collections import Counter
import requests

MAX_BATCH_ROWS = 150
MAX_SQL_BYTES = 75000  # Strict safety ceiling below D1's 102,400-byte SQLITE_TOOBIG limit
MIN_SALE_PRICE = 50000
LOOKBACK_DAYS = 730    # Rolling 24-month window

# King County Assessor SaleWarning codes indicating non-arm's-length or distorted sales
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


def get_cutoff_date(days_back=LOOKBACK_DAYS):
    cutoff = datetime.date.today() - datetime.timedelta(days=days_back)
    return cutoff.isoformat()


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

    # Handle Unix epoch milliseconds (common in ArcGIS REST CSV exports)
    if s.replace(".", "", 1).isdigit() and len(s.split(".")[0]) >= 12:
        try:
            dt = datetime.datetime.fromtimestamp(float(s) / 1000.0, tz=datetime.timezone.utc)
            return dt.strftime("%Y-%m-%d"), False
        except (ValueError, OSError):
            return None, False

    # Handle ISO strings (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10], False

    # Handle MMM-YYYY (e.g., "Oct-2025", "Feb-2026")
    try:
        dt = datetime.datetime.strptime(s, "%b-%Y")
        return dt.strftime("%Y-%m-01"), True
    except ValueError:
        pass

    # Handle MM/DD/YYYY or YYYY/MM/DD
    parts = s.split(" ")[0].split("/")
    if len(parts) == 3:
        if len(parts[0]) == 4 and parts[0].isdigit():
            y, m, d = parts[0], parts[1].zfill(2), parts[2].zfill(2)
            return f"{y}-{m}-{d}", False
        m, d, y = parts[0].zfill(2), parts[1].zfill(2), parts[2]
        if len(y) == 4 and y.isdigit():
            return f"{y}-{m}-{d}", False

    return None, False


def is_snoco_residential_class(prop_class_str):
    """Checks WA DOR residential property use codes (110-129 single/multi 2-4, 140-149 condos)."""
    if not prop_class_str:
        return True
    digits = "".join(ch for ch in prop_class_str if ch.isdigit())
    if not digits:
        return True
    code = int(digits)
    if code == 119:  # Manufactured home park (commercial/land-lease)
        return False
    return (110 <= code <= 129) or (140 <= code <= 149)


def ensure_dedup_index(session, endpoint, headers):
    sql = """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_sales_dedup
    ON sales_transactions(parcel_number, document_date, sale_price, recording_number);
    """
    execute_d1_query(session, endpoint, headers, sql)


def fetch_valid_parcel_keys(session, endpoint, headers):
    print("🔍 Indexing existing parcel_number keys from Cloudflare D1 'base'...")
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


def parse_king_sales(staging_dir, valid_pins, cutoff_date):
    sales_path = os.path.join(staging_dir, "kc-sales.csv")
    if not os.path.exists(sales_path):
        print("⚠️ Missing kc-sales.csv in data/staging/. Skipping King County sales.")
        return []

    print(f"📂 Parsing King County kc-sales.csv (date >= {cutoff_date}, price >= ${MIN_SALE_PRICE:,})...")
    transactions = []
    seen_keys = set()

    with open(sales_path, "r", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
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
            has_disqualifying_warning = bool(warning_tokens & KC_NON_ARMS_LENGTH_WARNINGS)

            inst_code = str(r.get("SaleInstrument") or "").strip()
            deed_type = KC_INSTRUMENT_MAP.get(inst_code, f"CODE_{inst_code}" if inst_code else "DEED")
            if inst_code == "15":  # Quitclaim deed
                has_disqualifying_warning = True

            is_arms_length = 0 if has_disqualifying_warning else 1

            seller = str(r.get("SellerName") or "").strip()[:120] or None
            buyer = str(r.get("BuyerName") or "").strip()[:120] or None

            transactions.append({
                "parcel_number": pin,
                "county": "KING",
                "document_date": iso_date,
                "sale_price": price,
                "recording_number": rec_nbr,
                "excise_tax_number": excise_nbr,
                "deed_type": deed_type,
                "sale_warning_code": raw_warnings or None,
                "is_arms_length": is_arms_length,
                "seller_name": seller,
                "buyer_name": buyer,
            })

    print(f"   Prepared {len(transactions):,} valid King County sales records.")
    return transactions


def parse_snohomish_sales(staging_dir, valid_pins, cutoff_date):
    sales_path = os.path.join(staging_dir, "snoco-sales.csv")
    if not os.path.exists(sales_path):
        print("⚠️ Missing snoco-sales.csv in data/staging/. Skipping Snohomish County sales.")
        return []

    month_cutoff = cutoff_date[:7] + "-01"
    print(f"📂 Parsing Snohomish County snoco-sales.csv (date >= {cutoff_date}, price >= ${MIN_SALE_PRICE:,})...")
    raw_rows = []
    date_price_counts = Counter()

    with open(sales_path, "r", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        for r in reader:
            raw_pin = str(r.get("PARCEL_ID") or "").strip().replace("-", "")
            if not raw_pin:
                continue
            pin = raw_pin.zfill(14) if raw_pin.isdigit() else raw_pin
            if pin not in valid_pins:
                if raw_pin in valid_pins:
                    pin = raw_pin
                else:
                    continue

            iso_date, is_month_only = normalize_date(r.get("TRNSF_DATE"))
            if not iso_date:
                continue
            effective_cutoff = month_cutoff if is_month_only else cutoff_date
            if iso_date < effective_cutoff:
                continue

            price = parse_price(r.get("SALE_PRICE"))
            if price < MIN_SALE_PRICE:
                continue

            date_price_counts[(iso_date, price)] += 1
            raw_rows.append((pin, iso_date, price, r))

    transactions = []
    seen_keys = set()

    for pin, iso_date, price, r in raw_rows:
        synth_rec = "SNOCO-" + hashlib.sha256(f"{pin}|{iso_date}|{price}".encode("utf-8")).hexdigest()[:16]
        if synth_rec in seen_keys:
            continue
        seen_keys.add(synth_rec)

        is_multi_parcel = date_price_counts[(iso_date, price)] > 1
        prop_class = str(r.get("PROP_CLASS") or "").strip()
        is_residential = is_snoco_residential_class(prop_class)

        warnings = []
        if is_multi_parcel:
            warnings.append("MULTI_PARCEL")
        if not is_residential:
            warnings.append(f"NON_RES_CLASS_{prop_class}")

        warning_code = " ".join(warnings) if warnings else None
        is_arms_length = 0 if warnings else 1

        transactions.append({
            "parcel_number": pin,
            "county": "SNOHOMISH",
            "document_date": iso_date,
            "sale_price": price,
            "recording_number": synth_rec,
            "excise_tax_number": None,
            "deed_type": f"CLASS_{prop_class}" if prop_class else "STATUTORY WARRANTY DEED",
            "sale_warning_code": warning_code,
            "is_arms_length": is_arms_length,
            "seller_name": None,
            "buyer_name": None,
        })

    print(f"   Prepared {len(transactions):,} valid Snohomish County sales records.")
    return transactions


def build_insert_sql(value_rows):
    return f"""
    INSERT OR IGNORE INTO sales_transactions (
        parcel_number, county, document_date, sale_price,
        recording_number, excise_tax_number, deed_type,
        sale_warning_code, is_arms_length, seller_name,
        buyer_name, created_utc
    ) VALUES
    {",".join(value_rows)};
    """


def insert_sales_and_update_base(session, endpoint, headers, transactions):
    total = len(transactions)
    if total == 0:
        print("ℹ️ No sales transactions to ingest.")
        return

    print(f"🚀 Inserting {total:,} sales transactions into Cloudflare D1 'sales_transactions' (byte ceiling: {MAX_SQL_BYTES:,}B, max rows: {MAX_BATCH_ROWS})...")
    latest_arms_length = {}

    wrapper_overhead = len(build_insert_sql(["()"]).encode("utf-8"))
    current_rows = []
    current_bytes = wrapper_overhead
    committed = 0

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

        if current_rows and (len(current_rows) >= MAX_BATCH_ROWS or (current_bytes + row_bytes) > MAX_SQL_BYTES):
            execute_d1_query(session, endpoint, headers, build_insert_sql(current_rows))
            committed += len(current_rows)
            print(f"\r   Committed sales: {committed:,} / {total:,}", end="", flush=True)
            current_rows = []
            current_bytes = wrapper_overhead

        current_rows.append(row_tuple)
        current_bytes += row_bytes

    if current_rows:
        execute_d1_query(session, endpoint, headers, build_insert_sql(current_rows))
        committed += len(current_rows)
        print(f"\r   Committed sales: {committed:,} / {total:,}", end="", flush=True)

    print("\n🔄 Updating latest arm's-length sale snapshots on 'base' table...")
    latest_items = list(latest_arms_length.items())
    total_updates = len(latest_items)

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
            print(f"\r   Updated base snapshots: {upd_committed:,} / {total_updates:,}", end="", flush=True)
            upd_stmts = []
            upd_bytes = 0

        upd_stmts.append(stmt)
        upd_bytes += stmt_bytes

    if upd_stmts:
        execute_d1_query(session, endpoint, headers, "\n".join(upd_stmts))
        upd_committed += len(upd_stmts)
        print(f"\r   Updated base snapshots: {upd_committed:,} / {total_updates:,}", end="", flush=True)

    print("\n✅ Phase 2 Sales Ledger Ingestion Complete.")


def main():
    parser = argparse.ArgumentParser(description="Ingest King & Snohomish sales into Cloudflare D1.")
    parser.add_argument("--snoco-only", action="store_true", help="Skip King County and ingest Snohomish County sales only.")
    parser.add_argument("--kc-only", action="store_true", help="Skip Snohomish County and ingest King County sales only.")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    load_dev_vars(base_dir)

    cf_account_id = os.environ.get("CF_ACCOUNT_ID")
    cf_api_token = os.environ.get("CF_D1_API_TOKEN")
    cf_db_id = os.environ.get("CF_DATABASE_PARCELDATA_ID")

    if not all([cf_account_id, cf_api_token, cf_db_id]):
        raise ValueError("Missing Cloudflare D1 credentials in .dev.vars or .env.")

    cutoff_date = get_cutoff_date(LOOKBACK_DAYS)
    print(f"📅 Applying rolling 24-month cutoff: {cutoff_date}")

    staging_dir = os.path.join(base_dir, "data", "staging")
    endpoint = f"https://api.cloudflare.com/client/v4/accounts/{cf_account_id}/d1/database/{cf_db_id}/query"
    headers = {
        "Authorization": f"Bearer {cf_api_token}",
        "Content-Type": "application/json"
    }

    session = requests.Session()
    ensure_dedup_index(session, endpoint, headers)
    valid_pins = fetch_valid_parcel_keys(session, endpoint, headers)

    all_sales = []
    if not args.snoco_only:
        all_sales.extend(parse_king_sales(staging_dir, valid_pins, cutoff_date))
    if not args.kc_only:
        all_sales.extend(parse_snohomish_sales(staging_dir, valid_pins, cutoff_date))

    insert_sales_and_update_base(session, endpoint, headers, all_sales)


if __name__ == "__main__":
    main()