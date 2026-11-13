import os
import re
import time
import sqlite3
import asyncio
import argparse
from datetime import datetime
from zoneinfo import ZoneInfo
import httpx

MAX_SQL_BYTES = 75000
D1_FLUSH_EVERY = 50
PACIFIC_TZ = ZoneInfo("America/Los_Angeles")
BASE_PORTAL = "https://wa-snohomish.publicaccessnow.com"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/27.0.1 Safari/605.1.15"


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


def execute_d1_sync(endpoint, headers, sql_block, retries=6):
    for attempt in range(retries):
        try:
            res = httpx.post(endpoint, headers=headers, json={"sql": sql_block}, timeout=90.0)
            data = res.json()
            if data.get("success"):
                return data
            err_str = str(data.get("errors", []))
            low_err = err_str.lower()
            if any(tok in low_err for tok in ["busy", "locked", "7429", "overloaded", "too many resources"]):
                wait_s = min(30.0, 4.0 * (attempt + 1))
                print(f"\n⏳ D1 rate/resource window hit (retrying in {wait_s:.0f}s)...")
                time.sleep(wait_s)
                continue
            raise RuntimeError(f"D1 Query Failed: {err_str}")
        except (httpx.RequestError, ValueError):
            if attempt == retries - 1:
                raise
            time.sleep(3.0 * (attempt + 1))
    return {}


def init_checkpoint_db(db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS harvest_log (
            parcel_number TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            gla INTEGER,
            style TEXT,
            updated_utc TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    return conn


def get_completed_pins(conn):
    cur = conn.execute("SELECT parcel_number FROM harvest_log WHERE status IN ('DONE', 'NO_STRUCTURE');")
    return {row[0] for row in cur.fetchall()}


def normalize_snoco_style(raw_style, prop_type=None):
    if prop_type == "Condo":
        return "Condo"
    if prop_type == "Townhouse":
        return "Townhouse"
    if not raw_style:
        return None
    cleaned = re.sub(r'^R\d+\s*:\s*\d*\s*', '', str(raw_style).strip(), flags=re.IGNORECASE).strip()
    s = cleaned.lower()
    if "town" in s:
        return "Townhouse"
    if "condo" in s:
        return "Condo"
    if "split" in s or "tri" in s or "bi-level" in s or "bi level" in s:
        return "Split / Tri-Level"
    if "1.5" in s or "1 1/2" in s or "one and" in s or "cape" in s:
        return "1.5-Story"
    if "2" in s or "two" in s or "2.5" in s or "3" in s or "multi" in s:
        return "2-Story"
    if "1" in s or "one" in s or "rambl" in s or "ranch" in s or "single" in s or "sty" in s:
        return "1-Story"
    return cleaned[:40] if cleaned else None


def normalize_snoco_grade(raw_qual):
    """Maps Snohomish ProVal quality labels/numbers onto King County's 1-13 grade scale."""
    if not raw_qual:
        return None
    s = str(raw_qual).strip().lower()
    if s.isdigit():
        num = int(s)
        return max(1, min(13, num))
    mapping = {
        "low": 4,
        "fair": 5,
        "below average": 6,
        "average": 7,
        "avg": 7,
        "good": 8,
        "above average": 8,
        "very good": 9,
        "excellent": 10,
        "custom": 11,
        "luxury": 12,
        "mansion": 13,
    }
    for k, v in mapping.items():
        if k in s:
            return v
    return None


def normalize_snoco_condition(raw_cond):
    """Maps Snohomish condition labels/numbers onto King County's 1-5 condition scale."""
    if not raw_cond:
        return None
    s = str(raw_cond).strip().lower()
    if s.isdigit():
        num = int(s)
        return max(1, min(5, num))
    if "poor" in s or "unsound" in s:
        return 1
    if "fair" in s:
        return 2
    if "average" in s or "avg" in s:
        return 3
    if "good" in s:
        return 4
    if "very good" in s or "excellent" in s:
        return 5
    return None


def parse_datadisplay_rows(payload):
    """Flattens Aumentum DataDisplay groups[].rows[].values[] into a list of row dicts."""
    rows_out = []
    if not isinstance(payload, dict):
        return rows_out
    for grp in payload.get("groups") or []:
        for row in grp.get("rows") or []:
            row_dict = {}
            for cell in row.get("values") or []:
                col = cell.get("column")
                if col:
                    row_dict[col] = cell.get("value")
                    if cell.get("hyperlink"):
                        row_dict[f"{col}__hyperlink"] = cell.get("hyperlink")
            if row_dict:
                rows_out.append(row_dict)
    return rows_out


def fetch_target_queue(endpoint, headers, staging_dir, completed_pins, queue_file=None, sales_only=False, limit=None):
    """Uses primary-key keyset pagination (zero full-table sort) and caches queue to disk."""
    if queue_file and os.path.exists(queue_file):
        with open(queue_file, "r", encoding="utf-8") as f:
            pins = [line.strip() for line in f if line.strip() and line.strip() not in completed_pins]
        print(f"📋 Loaded {len(pins):,} unharvested Snohomish pins from queue file: {queue_file}")
        return [(p, None) for p in (pins[:limit] if limit else pins)]

    cache_name = "snoco_sales_queue.txt" if sales_only else "snoco_full_queue.txt"
    cache_path = os.path.join(staging_dir, cache_name)
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
        targets = []
        with open(cache_path, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                pin = parts[0].strip()
                ptype = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
                if pin and pin not in completed_pins:
                    targets.append((pin, ptype))
        print(f"📋 Loaded {len(targets):,} remaining Snohomish parcels from cached queue ({cache_name}).")
        return targets[:limit] if limit else targets

    print("🔍 Indexing Snohomish residential parcels via primary-key seek...")
    ordered = []
    seen = set()
    passes = ["AND last_sale_date IS NOT NULL"] if sales_only else [
        "AND last_sale_date IS NOT NULL",
        "AND last_sale_date IS NULL"
    ]
    page_size = 25000

    for sale_filter in passes:
        last_pin = ""
        while True:
            cursor_clause = f"AND parcel_number > {sql_val(last_pin)}" if last_pin else ""
            sql = f"""
            SELECT parcel_number, property_type
            FROM base
            WHERE county = 'SNOHOMISH'
              AND property_type IN ('Single Family', 'Residential', 'Multi-Family', 'Condo', 'Townhouse')
              AND (square_footage IS NULL OR square_footage = 0)
              {sale_filter}
              {cursor_clause}
            ORDER BY parcel_number ASC
            LIMIT {page_size};
            """
            data = execute_d1_sync(endpoint, headers, sql)
            rows = data.get("result", [{}])[0].get("results", [])
            if not rows:
                break
            for r in rows:
                pin = r["parcel_number"]
                last_pin = pin
                if pin not in seen:
                    seen.add(pin)
                    ordered.append((pin, r.get("property_type")))
            print(f"\r   Indexed {len(ordered):,} Snohomish residential parcels...", end="", flush=True)
            time.sleep(0.35)

    print()
    if ordered:
        os.makedirs(staging_dir, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            for p, pt in ordered:
                f.write(f"{p}\t{pt or ''}\n")

    targets = [(p, pt) for p, pt in ordered if p not in completed_pins]
    print(f"🎯 Queued {len(targets):,} Snohomish residential parcels (recent sales prioritized first).")
    return targets[:limit] if limit else targets


def flush_base_updates_to_d1(endpoint, headers, base_updates):
    if not base_updates:
        return

    stmts = []
    curr_bytes = 0
    for pin, a in base_updates:
        stmt = (
            f"UPDATE base SET "
            f"square_footage = COALESCE({sql_val(a['square_footage'])}, square_footage), "
            f"year_built = COALESCE({sql_val(a['year_built'])}, year_built), "
            f"bedrooms = COALESCE({sql_val(a['bedrooms'])}, bedrooms), "
            f"bath_full = COALESCE({sql_val(a['bath_full'])}, bath_full), "
            f"bath_half = COALESCE({sql_val(a['bath_half'])}, bath_half), "
            f"building_grade = COALESCE({sql_val(a['building_grade'])}, building_grade), "
            f"building_condition = COALESCE({sql_val(a['building_condition'])}, building_condition), "
            f"building_style = COALESCE({sql_val(a['building_style'])}, building_style), "
            f"updated_utc = CURRENT_TIMESTAMP "
            f"WHERE parcel_number = {sql_val(pin)};"
        )
        b_len = len(stmt.encode("utf-8")) + 1
        if stmts and (len(stmts) >= 120 or (curr_bytes + b_len) > MAX_SQL_BYTES):
            execute_d1_sync(endpoint, headers, "\n".join(stmts))
            stmts = []
            curr_bytes = 0
        stmts.append(stmt)
        curr_bytes += b_len

    if stmts:
        execute_d1_sync(endpoint, headers, "\n".join(stmts))


async def bootstrap_portal_cookies(client):
    """Initializes AWSALB / ASPXANONYMOUS session cookies on wa-snohomish.publicaccessnow.com."""
    try:
        await client.get(
            f"{BASE_PORTAL}/PropertyInformation/PropertySearch.aspx",
            follow_redirects=True,
            timeout=25.0,
        )
    except Exception:
        pass


async def process_parcel(client, sem, pin, prop_type, debug_html=False):
    today_str = datetime.now(PACIFIC_TZ).strftime("%Y-%m-%d")
    async with sem:
        await asyncio.sleep(0.04)
        for attempt in range(3):
            try:
                # 1. QuickSearch API -> resolve internal Altkey (a)
                qs_url = f"{BASE_PORTAL}/DesktopModules/QuickSearch/API/Module/GetData?_m=470"
                qs_headers = {
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/plain, */*",
                    "ModuleId": "470",
                    "TabId": "38",
                    "Origin": BASE_PORTAL,
                    "Referer": f"{BASE_PORTAL}/PropertyInformation/PropertySearch.aspx",
                }
                qs_resp = await client.post(
                    qs_url,
                    json={"keywords": pin, "page": 1},
                    headers=qs_headers,
                    timeout=20.0,
                )
                if qs_resp.status_code in (429, 503):
                    await asyncio.sleep(2.0 * (attempt + 1))
                    continue
                if qs_resp.status_code != 200:
                    await bootstrap_portal_cookies(client)
                    continue

                qs_json = qs_resp.json()
                items = qs_json.get("items") or []
                if not items:
                    if debug_html:
                        print(f"[DEBUG {pin}] QuickSearch returned 0 items.")
                    return pin, "NO_STRUCTURE", None

                matched_fields = None
                for it in items:
                    flds = it.get("fields") or {}
                    if str(flds.get("ParcelID", "")).strip() == pin or str(flds.get("PrimaryKey", "")).strip() == pin:
                        matched_fields = flds
                        break
                if matched_fields is None:
                    matched_fields = items[0].get("fields") or {}

                altkey = matched_fields.get("Altkey")
                if not altkey:
                    return pin, "NO_STRUCTURE", None

                # 2. Buildings List (_m=694) -> resolve Building ID (b), Style, YearBuilt & daily date token (d)
                summary_ref = f"{BASE_PORTAL}/PropertyInformation/PropertySearch/PropertyAccountSummary.aspx?p={pin}&a={altkey}&m={pin}"
                bldg_list_url = (
                    f"{BASE_PORTAL}/API/DataDisplay/DataSources/GetData"
                    f"?p={pin}&a={altkey}&m={pin}&itemsPerPage=15&page=1&_m=694"
                )
                bl_resp = await client.get(
                    bldg_list_url,
                    headers={
                        "Accept": "application/json, text/plain, */*",
                        "ModuleId": "694",
                        "TabId": "39",
                        "Referer": summary_ref,
                    },
                    timeout=20.0,
                )
                if bl_resp.status_code != 200:
                    if attempt == 2:
                        return pin, "ERROR", None
                    await asyncio.sleep(1.0)
                    continue

                bldg_rows = parse_datadisplay_rows(bl_resp.json())
                if not bldg_rows:
                    if debug_html:
                        print(f"[DEBUG {pin}] Altkey={altkey} | 0 buildings listed in _m=694 (vacant/land).")
                    return pin, "NO_STRUCTURE", None

                total_gla = 0
                total_beds = 0
                total_full_baths = 0
                total_half_baths = 0
                best_style = normalize_snoco_style(None, prop_type)
                best_year_built = None
                best_grade = None
                best_condition = None
                primary_gla = -1

                for brow in bldg_rows[:3]:
                    raw_bname = brow.get("BuildingName")
                    raw_yb = brow.get("YearBuilt")
                    href = brow.get("BuildingName__hyperlink") or ""

                    m_b = re.search(r'[?&]b=(\d+)', href)
                    if not m_b:
                        continue
                    b_id = m_b.group(1)

                    m_d = re.search(r'[?&]d=(\d{4}-\d{2}-\d{2})', href)
                    date_token = m_d.group(1) if m_d else today_str

                    detail_ref = (
                        f"{BASE_PORTAL}/PropertyInformation/PropertySearch/PropertyAccountSummary/BuildingDetail.aspx"
                        f"?b={b_id}&a={altkey}&p={pin}&d={date_token}"
                    )

                    # 3. Improvement Area, Quality & Condition (_m=593)
                    imp_url = (
                        f"{BASE_PORTAL}/API/DataDisplay/DataSources/GetData"
                        f"?b={b_id}&a={altkey}&p={pin}&d={date_token}&itemsPerPage=25&page=1&_m=593"
                    )
                    # 4. Room & Bath Counts (_m=522)
                    room_url = (
                        f"{BASE_PORTAL}/API/DataDisplay/DataSources/GetData"
                        f"?b={b_id}&a={altkey}&p={pin}&d={date_token}&itemsPerPage=25&page=1&_m=522"
                    )

                    imp_resp, room_resp = await asyncio.gather(
                        client.get(
                            imp_url,
                            headers={"Accept": "application/json, text/plain, */*", "ModuleId": "593", "TabId": "105", "Referer": detail_ref},
                            timeout=20.0,
                        ),
                        client.get(
                            room_url,
                            headers={"Accept": "application/json, text/plain, */*", "ModuleId": "522", "TabId": "105", "Referer": detail_ref},
                            timeout=20.0,
                        ),
                    )

                    b_gla = 0
                    b_qual = None
                    b_cond = None
                    b_yb = None

                    if imp_resp.status_code == 200:
                        imp_json = imp_resp.json()
                        for tot in imp_json.get("totals") or []:
                            if tot.get("column") == "FinishedArea":
                                digits = re.sub(r"[^0-9.]", "", str(tot.get("value") or ""))
                                if digits:
                                    b_gla = int(float(digits))

                        imp_rows = parse_datadisplay_rows(imp_json)
                        row_fin_sum = 0
                        for irow in imp_rows:
                            fin_digits = re.sub(r"[^0-9.]", "", str(irow.get("FinishedArea") or ""))
                            fin_val = int(float(fin_digits)) if fin_digits else 0
                            if fin_val > 0:
                                row_fin_sum += fin_val
                                if b_qual is None:
                                    b_qual = normalize_snoco_grade(irow.get("QualityDescr"))
                                if b_cond is None:
                                    b_cond = normalize_snoco_condition(irow.get("ConditionDescr"))
                                if b_yb is None and irow.get("YearBuilt"):
                                    m_y = re.search(r"(18\d{2}|19\d{2}|20[0-3]\d)", str(irow.get("YearBuilt")))
                                    if m_y:
                                        b_yb = int(m_y.group(1))
                        if b_gla == 0 and row_fin_sum > 0:
                            b_gla = row_fin_sum

                    if b_yb is None and raw_yb:
                        m_y = re.search(r"(18\d{2}|19\d{2}|20[0-3]\d)", str(raw_yb))
                        if m_y:
                            b_yb = int(m_y.group(1))

                    if b_gla > 0:
                        total_gla += b_gla
                        if b_gla > primary_gla:
                            primary_gla = b_gla
                            parsed_style = normalize_snoco_style(raw_bname, prop_type)
                            if parsed_style:
                                best_style = parsed_style
                            if b_yb:
                                best_year_built = b_yb
                            if b_qual:
                                best_grade = b_qual
                            if b_cond:
                                best_condition = b_cond

                    if room_resp.status_code == 200:
                        room_rows = parse_datadisplay_rows(room_resp.json())
                        for rrow in room_rows:
                            desc = str(rrow.get("Description") or "").strip().lower()
                            u_digits = re.sub(r"[^0-9]", "", str(rrow.get("Units") or ""))
                            if not u_digits:
                                continue
                            units = int(u_digits)
                            if "bedroom" in desc:
                                total_beds += units
                            elif "full bath" in desc or "3/4 bath" in desc or "three quarter bath" in desc:
                                total_full_baths += units
                            elif "half bath" in desc or "1/2 bath" in desc:
                                total_half_baths += units

                attrs = {
                    "square_footage": total_gla if 150 <= total_gla <= 45000 else None,
                    "year_built": best_year_built,
                    "bedrooms": total_beds if total_beds > 0 else None,
                    "bath_full": total_full_baths if total_full_baths > 0 else None,
                    "bath_half": total_half_baths if total_half_baths > 0 else None,
                    "building_grade": best_grade,
                    "building_condition": best_condition,
                    "building_style": best_style,
                }

                if debug_html:
                    print(f"[DEBUG {pin}] Altkey={altkey} | Parsed -> {attrs}")

                status = "DONE" if attrs["square_footage"] else "NO_STRUCTURE"
                return pin, status, attrs

            except (httpx.RequestError, asyncio.TimeoutError, ValueError):
                if attempt == 2:
                    return pin, "ERROR", None
                await asyncio.sleep(1.5 * (attempt + 1))

    return pin, "ERROR", None


async def run_harvester(args):
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    staging_dir = os.path.join(base_dir, "data", "staging")
    load_dev_vars(base_dir)

    cf_account_id = os.environ.get("CF_ACCOUNT_ID")
    cf_api_token = os.environ.get("CF_D1_API_TOKEN")
    cf_db_id = os.environ.get("CF_DATABASE_PARCELDATA_ID")

    if not all([cf_account_id, cf_api_token, cf_db_id]):
        raise ValueError("Missing Cloudflare D1 credentials in .dev.vars.")

    endpoint = f"https://api.cloudflare.com/client/v4/accounts/{cf_account_id}/d1/database/{cf_db_id}/query"
    headers = {"Authorization": f"Bearer {cf_api_token}", "Content-Type": "application/json"}

    ckpt_path = os.path.join(staging_dir, "snoco_harvest.db")
    ckpt_conn = init_checkpoint_db(ckpt_path)
    completed_pins = get_completed_pins(ckpt_conn)
    print(f"💾 Checkpoint loaded: {len(completed_pins):,} Snohomish parcels already harvested.")

    targets = fetch_target_queue(
        endpoint,
        headers,
        staging_dir,
        completed_pins,
        queue_file=args.queue_file,
        sales_only=args.sales_only,
        limit=args.limit,
    )
    if not targets:
        print("✅ All queued Snohomish parcels are already harvested.")
        return

    sem = asyncio.Semaphore(args.concurrency)
    pending_base = []
    processed = 0
    total = len(targets)

    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        limits=httpx.Limits(max_connections=args.concurrency * 2 + 4),
    ) as client:
        await bootstrap_portal_cookies(client)

        chunk_start = 0
        while chunk_start < total:
            batch = targets[chunk_start:chunk_start + D1_FLUSH_EVERY]
            tasks = [
                process_parcel(client, sem, pin, ptype, args.debug_html)
                for pin, ptype in batch
            ]
            results = await asyncio.gather(*tasks)

            for pin, status, attrs in results:
                processed += 1
                if attrs and any(v is not None for v in attrs.values()):
                    pending_base.append((pin, attrs))
                if status in ("DONE", "NO_STRUCTURE"):
                    ckpt_conn.execute(
                        "INSERT OR REPLACE INTO harvest_log (parcel_number, status, gla, style, updated_utc) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP);",
                        (pin, status, attrs.get("square_footage") if attrs else None, attrs.get("building_style") if attrs else None),
                    )

            ckpt_conn.commit()
            if pending_base:
                await asyncio.to_thread(flush_base_updates_to_d1, endpoint, headers, pending_base)
                pending_base.clear()

            chunk_start += D1_FLUSH_EVERY
            print(f"\r🚀 Snohomish Attributes Harvested: {processed:,} / {total:,}", end="", flush=True)

    print("\n✅ Snohomish County Structural Attributes Harvest Complete.")


def main():
    parser = argparse.ArgumentParser(description="Async Snohomish County JSON API Harvester (Attributes Only).")
    parser.add_argument("--concurrency", type=int, default=12, help="Concurrent HTTP workers (default: 12).")
    parser.add_argument("--sales-only", action="store_true", help="Only harvest parcels with recent sales first.")
    parser.add_argument("--queue-file", type=str, default=None, help="Path to delta PIN queue file.")
    parser.add_argument("--limit", type=int, default=None, help="Max parcels to process in this run.")
    parser.add_argument("--debug-html", action="store_true", help="Print parsed JSON attributes for each parcel.")
    args = parser.parse_args()
    asyncio.run(run_harvester(args))


if __name__ == "__main__":
    main()