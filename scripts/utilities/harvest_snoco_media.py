import os
import re
import io
import time
import base64
import sqlite3
import asyncio
import argparse
from datetime import datetime
from zoneinfo import ZoneInfo
import boto3
from botocore.client import Config
import httpx
from PIL import Image, ImageOps

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

MAX_SQL_BYTES = 75000
D1_FLUSH_EVERY = 25
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


def inspect_parcel_media_columns(endpoint, headers):
    """Inspects D1 parcel_media schema so INSERT statements match exact live column names."""
    data = execute_d1_sync(endpoint, headers, "PRAGMA table_info(parcel_media);")
    rows = data.get("result", [{}])[0].get("results", [])
    cols = [r["name"] for r in rows if "name" in r]
    if not cols:
        raise RuntimeError("Table 'parcel_media' not found in D1 database.")
    return cols


def get_r2_client():
    account_id = (os.environ.get("CF_ACCOUNT_ID") or "").strip()
    access_key = (os.environ.get("R2_ALL_ACCESS_KEY_ID") or os.environ.get("R2_ACCESS_KEY_ID") or "").strip()
    secret_key = (os.environ.get("R2_ALL_SECRET_ACCESS_KEY") or os.environ.get("R2_SECRET_ACCESS_KEY") or "").strip()
    bucket_name = (os.environ.get("R2_BUCKET_NAME") or "").strip()
    if not all([account_id, access_key, secret_key, bucket_name]):
        raise ValueError("Missing R2 credentials (CF_ACCOUNT_ID, R2_ALL_ACCESS_KEY_ID, R2_ALL_SECRET_ACCESS_KEY, R2_BUCKET_NAME) in .dev.vars.")
    client = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )
    return client, bucket_name


def init_checkpoint_db(db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS media_harvest_log (
            parcel_number TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            photo_count INTEGER DEFAULT 0,
            sketch_count INTEGER DEFAULT 0,
            updated_utc TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    return conn


def get_completed_pins(conn):
    cur = conn.execute("SELECT parcel_number FROM media_harvest_log WHERE status IN ('DONE', 'NO_MEDIA');")
    return {row[0] for row in cur.fetchall()}


def parse_datadisplay_rows(payload):
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


def fetch_media_queue(endpoint, headers, staging_dir, completed_pins, queue_file=None, sales_only=False, limit=None):
    """Queues Snohomish parcels with verified structures (square_footage > 0), prioritizing recent sales."""
    if queue_file and os.path.exists(queue_file):
        with open(queue_file, "r", encoding="utf-8") as f:
            pins = [line.strip() for line in f if line.strip() and line.strip() not in completed_pins]
        print(f"📋 Loaded {len(pins):,} unharvested Snohomish media pins from queue file: {queue_file}")
        return pins[:limit] if limit else pins

    cache_name = "snoco_media_sales_queue.txt" if sales_only else "snoco_media_full_queue.txt"
    cache_path = os.path.join(staging_dir, cache_name)
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
        with open(cache_path, "r", encoding="utf-8") as f:
            pins = [line.strip() for line in f if line.strip() and line.strip() not in completed_pins]
        print(f"📋 Loaded {len(pins):,} remaining Snohomish parcels from cached media queue ({cache_name}).")
        return pins[:limit] if limit else pins

    print("🔍 Indexing Snohomish parcels with structures (square_footage > 0) via primary-key seek...")
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
            SELECT parcel_number
            FROM base
            WHERE county = 'SNOHOMISH'
              AND square_footage > 0
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
                    ordered.append(pin)
            print(f"\r   Indexed {len(ordered):,} Snohomish structured parcels...", end="", flush=True)
            time.sleep(0.35)

    print()
    if ordered:
        os.makedirs(staging_dir, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            for p in ordered:
                f.write(f"{p}\n")

    targets = [p for p in ordered if p not in completed_pins]
    print(f"🎯 Queued {len(targets):,} Snohomish structured parcels for media harvesting.")
    return targets[:limit] if limit else targets


def convert_b64_to_webp(b64_str):
    """Decodes base64 JPEG/image payload and encodes a 1200px max-edge WebP buffer."""
    if not b64_str or not isinstance(b64_str, str):
        return None, None, None
    cleaned = b64_str.strip()
    if cleaned.startswith("data:") and "," in cleaned:
        cleaned = cleaned.split(",", 1)[1]
    raw_bytes = base64.b64decode(cleaned)
    img = Image.open(io.BytesIO(raw_bytes))
    img = ImageOps.exif_transpose(img)
    if img.width < 80 or img.height < 80:
        return None, None, None
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")
    img.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
    w, h = img.size
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=80, method=6)
    return buf.getvalue(), w, h


def upload_bytes_to_r2(s3_client, bucket_name, r2_key, body_bytes, content_type):
    s3_client.put_object(
        Bucket=bucket_name,
        Key=r2_key,
        Body=body_bytes,
        ContentType=content_type,
        CacheControl="public, max-age=31536000, immutable",
    )


def build_d1_media_statements(pin, media_items, table_cols):
    """Builds DELETE + INSERT SQL statements mapped dynamically to live parcel_media columns."""
    stmts = [f"DELETE FROM parcel_media WHERE parcel_number = {sql_val(pin)} AND county = 'SNOHOMISH';"]
    col_set = set(table_cols)

    for idx, item in enumerate(media_items):
        row_map = {}
        if "parcel_number" in col_set:
            row_map["parcel_number"] = sql_val(pin)
        if "county" in col_set:
            row_map["county"] = sql_val("SNOHOMISH")
        if "media_type" in col_set:
            row_map["media_type"] = sql_val(item["media_type"])
        elif "type" in col_set:
            row_map["type"] = sql_val(item["media_type"])

        if "r2_key" in col_set:
            row_map["r2_key"] = sql_val(item["r2_key"])
        elif "storage_key" in col_set:
            row_map["storage_key"] = sql_val(item["r2_key"])
        elif "key" in col_set:
            row_map["key"] = sql_val(item["r2_key"])

        for url_col in ("public_url", "url", "media_url", "src"):
            if url_col in col_set:
                row_map[url_col] = sql_val(item["public_url"])
                break

        for order_col in ("sort_order", "display_order", "sequence", "position"):
            if order_col in col_set:
                row_map[order_col] = str(idx)
                break

        if "is_primary" in col_set:
            row_map["is_primary"] = "1" if item.get("is_primary") else "0"
        if "mime_type" in col_set:
            row_map["mime_type"] = sql_val(item["mime_type"])
        elif "content_type" in col_set:
            row_map["content_type"] = sql_val(item["mime_type"])
        if "width" in col_set and item.get("width") is not None:
            row_map["width"] = str(item["width"])
        if "height" in col_set and item.get("height") is not None:
            row_map["height"] = str(item["height"])
        if "created_utc" in col_set:
            row_map["created_utc"] = "CURRENT_TIMESTAMP"

        cols_sql = ", ".join(row_map.keys())
        vals_sql = ", ".join(row_map.values())
        stmts.append(f"INSERT INTO parcel_media ({cols_sql}) VALUES ({vals_sql});")

    return stmts


def flush_media_to_d1(endpoint, headers, pending_records, table_cols):
    if not pending_records:
        return

    stmts = []
    curr_bytes = 0
    for pin, media_items in pending_records:
        pin_stmts = build_d1_media_statements(pin, media_items, table_cols)
        block = "\n".join(pin_stmts)
        b_len = len(block.encode("utf-8")) + 1
        if stmts and (len(stmts) >= 120 or (curr_bytes + b_len) > MAX_SQL_BYTES):
            execute_d1_sync(endpoint, headers, "\n".join(stmts))
            stmts = []
            curr_bytes = 0
        stmts.extend(pin_stmts)
        curr_bytes += b_len

    if stmts:
        execute_d1_sync(endpoint, headers, "\n".join(stmts))


async def bootstrap_portal_cookies(client):
    try:
        await client.get(
            f"{BASE_PORTAL}/PropertyInformation/PropertySearch.aspx",
            follow_redirects=True,
            timeout=25.0,
        )
    except Exception:
        pass


async def process_parcel_media(client, s3_client, bucket_name, public_base, sem, pin, debug=False):
    today_str = datetime.now(PACIFIC_TZ).strftime("%Y-%m-%d")
    async with sem:
        await asyncio.sleep(0.05)
        for attempt in range(3):
            try:
                # 1. QuickSearch (_m=470) -> resolve internal Altkey (a)
                qs_url = f"{BASE_PORTAL}/DesktopModules/QuickSearch/API/Module/GetData?_m=470"
                qs_resp = await client.post(
                    qs_url,
                    json={"keywords": pin, "page": 1},
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/plain, */*",
                        "ModuleId": "470",
                        "TabId": "38",
                        "Origin": BASE_PORTAL,
                        "Referer": f"{BASE_PORTAL}/PropertyInformation/PropertySearch.aspx",
                    },
                    timeout=20.0,
                )
                if qs_resp.status_code in (429, 503):
                    await asyncio.sleep(2.0 * (attempt + 1))
                    continue
                if qs_resp.status_code != 200:
                    await bootstrap_portal_cookies(client)
                    continue

                items = qs_resp.json().get("items") or []
                if not items:
                    return pin, "NO_MEDIA", []

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
                    return pin, "NO_MEDIA", []

                # 2. Buildings Grid (_m=694) -> resolve Building ID (b) & daily date token (d)
                summary_ref = f"{BASE_PORTAL}/PropertyInformation/PropertySearch/PropertyAccountSummary.aspx?p={pin}&a={altkey}&m={pin}"
                bl_resp = await client.get(
                    f"{BASE_PORTAL}/API/DataDisplay/DataSources/GetData?p={pin}&a={altkey}&m={pin}&itemsPerPage=15&page=1&_m=694",
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
                        return pin, "ERROR", []
                    await asyncio.sleep(1.0)
                    continue

                bldg_rows = parse_datadisplay_rows(bl_resp.json())
                if not bldg_rows:
                    return pin, "NO_MEDIA", []

                media_records = []
                photo_seq = 0
                sketch_seq = 0

                for brow in bldg_rows[:3]:
                    href = brow.get("BuildingName__hyperlink") or ""
                    m_b = re.search(r"[?&]b=(\d+)", href)
                    if not m_b:
                        continue
                    b_id = m_b.group(1)
                    m_d = re.search(r"[?&]d=(\d{4}-\d{2}-\d{2})", href)
                    date_token = m_d.group(1) if m_d else today_str

                    detail_ref = (
                        f"{BASE_PORTAL}/PropertyInformation/PropertySearch/PropertyAccountSummary/BuildingDetail.aspx"
                        f"?b={b_id}&a={altkey}&p={pin}&d={date_token}"
                    )

                    # 3. Fetch Building Photos (_m=738) & Floorplan Sketches (_m=647) concurrently
                    photo_url = (
                        f"{BASE_PORTAL}/API/ImageControl/Images/GetImages"
                        f"?b={b_id}&a={altkey}&p={pin}&d={date_token}&page=0&_m=738"
                    )
                    sketch_url = (
                        f"{BASE_PORTAL}/API/ImageControl/Images/GetImages"
                        f"?b={b_id}&a={altkey}&p={pin}&d={date_token}&page=0&_m=647"
                    )

                    p_resp, s_resp = await asyncio.gather(
                        client.get(
                            photo_url,
                            headers={"Accept": "application/json, text/plain, */*", "ModuleId": "738", "TabId": "105", "Referer": detail_ref},
                            timeout=25.0,
                        ),
                        client.get(
                            sketch_url,
                            headers={"Accept": "application/json, text/plain, */*", "ModuleId": "647", "TabId": "105", "Referer": detail_ref},
                            timeout=25.0,
                        ),
                    )

                    if p_resp.status_code == 200:
                        p_json = p_resp.json()
                        for img_obj in (p_json.get("images") or [])[:5]:
                            raw_b64 = img_obj.get("value")
                            webp_bytes, w, h = await asyncio.to_thread(convert_b64_to_webp, raw_b64)
                            if webp_bytes:
                                photo_seq += 1
                                r2_key = f"parcels/snohomish/{pin}/photo-{photo_seq}.webp"
                                await asyncio.to_thread(
                                    upload_bytes_to_r2,
                                    s3_client,
                                    bucket_name,
                                    r2_key,
                                    webp_bytes,
                                    "image/webp",
                                )
                                media_records.append({
                                    "media_type": "photo",
                                    "r2_key": r2_key,
                                    "public_url": f"{public_base}/{r2_key}",
                                    "mime_type": "image/webp",
                                    "width": w,
                                    "height": h,
                                    "is_primary": photo_seq == 1,
                                })

                    if s_resp.status_code == 200:
                        s_json = s_resp.json()
                        for sk_obj in (s_json.get("images") or [])[:3]:
                            svg_text = sk_obj.get("value")
                            if isinstance(svg_text, str) and "<svg" in svg_text.lower() and "</svg>" in svg_text.lower():
                                sketch_seq += 1
                                r2_key = f"parcels/snohomish/{pin}/sketch-{sketch_seq}.svg"
                                await asyncio.to_thread(
                                    upload_bytes_to_r2,
                                    s3_client,
                                    bucket_name,
                                    r2_key,
                                    svg_text.encode("utf-8"),
                                    "image/svg+xml",
                                )
                                media_records.append({
                                    "media_type": "sketch",
                                    "r2_key": r2_key,
                                    "public_url": f"{public_base}/{r2_key}",
                                    "mime_type": "image/svg+xml",
                                    "width": None,
                                    "height": None,
                                    "is_primary": False,
                                })

                if debug:
                    print(f"[DEBUG {pin}] Altkey={altkey} | Uploaded {photo_seq} photo(s), {sketch_seq} sketch(es)")

                status = "DONE" if media_records else "NO_MEDIA"
                return pin, status, media_records

            except (httpx.RequestError, asyncio.TimeoutError, ValueError) as e:
                if debug:
                    print(f"[DEBUG {pin}] Attempt {attempt + 1} error: {e}")
                if attempt == 2:
                    return pin, "ERROR", []
                await asyncio.sleep(1.5 * (attempt + 1))

    return pin, "ERROR", []


async def run_media_harvester(args):
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    staging_dir = os.path.join(base_dir, "data", "staging")
    load_dev_vars(base_dir)

    cf_account_id = os.environ.get("CF_ACCOUNT_ID")
    cf_api_token = os.environ.get("CF_D1_API_TOKEN")
    cf_db_id = os.environ.get("CF_DATABASE_PARCELDATA_ID")
    public_base = (os.environ.get("R2_PUBLIC_BASE_URL") or "https://assets.myseattlesearch.com").rstrip("/")

    if not all([cf_account_id, cf_api_token, cf_db_id]):
        raise ValueError("Missing Cloudflare D1 credentials in .dev.vars.")

    endpoint = f"https://api.cloudflare.com/client/v4/accounts/{cf_account_id}/d1/database/{cf_db_id}/query"
    headers = {"Authorization": f"Bearer {cf_api_token}", "Content-Type": "application/json"}

    table_cols = inspect_parcel_media_columns(endpoint, headers)
    s3_client, bucket_name = get_r2_client()

    ckpt_path = os.path.join(staging_dir, "snoco_media_harvest.db")
    ckpt_conn = init_checkpoint_db(ckpt_path)
    completed_pins = get_completed_pins(ckpt_conn)
    print(f"💾 Media checkpoint loaded: {len(completed_pins):,} Snohomish parcels already processed.")

    targets = fetch_media_queue(
        endpoint,
        headers,
        staging_dir,
        completed_pins,
        queue_file=args.queue_file,
        sales_only=args.sales_only,
        limit=args.limit,
    )
    if not targets:
        print("✅ All queued Snohomish structured parcels have already been processed for media.")
        return

    sem = asyncio.Semaphore(args.concurrency)
    pending_d1 = []
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
                process_parcel_media(client, s3_client, bucket_name, public_base, sem, pin, args.debug)
                for pin in batch
            ]
            results = await asyncio.gather(*tasks)

            for pin, status, media_items in results:
                processed += 1
                if media_items:
                    pending_d1.append((pin, media_items))
                if status in ("DONE", "NO_MEDIA"):
                    p_cnt = sum(1 for m in media_items if m["media_type"] == "photo")
                    s_cnt = sum(1 for m in media_items if m["media_type"] == "sketch")
                    ckpt_conn.execute(
                        """
                        INSERT OR REPLACE INTO media_harvest_log
                        (parcel_number, status, photo_count, sketch_count, updated_utc)
                        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP);
                        """,
                        (pin, status, p_cnt, s_cnt),
                    )

            ckpt_conn.commit()
            if pending_d1:
                await asyncio.to_thread(flush_media_to_d1, endpoint, headers, pending_d1, table_cols)
                pending_d1.clear()

            chunk_start += D1_FLUSH_EVERY
            print(f"\r📸 Snohomish Media Harvested: {processed:,} / {total:,}", end="", flush=True)

    print("\n✅ Snohomish County Media Harvest Complete.")


def main():
    parser = argparse.ArgumentParser(description="Async Snohomish County R2 Photo & Vector Sketch Harvester.")
    parser.add_argument("--concurrency", type=int, default=8, help="Concurrent HTTP/R2 workers (default: 8).")
    parser.add_argument("--sales-only", action="store_true", help="Prioritize parcels with recent sales first.")
    parser.add_argument("--queue-file", type=str, default=None, help="Path to delta PIN queue file.")
    parser.add_argument("--limit", type=int, default=None, help="Max parcels to process in this run.")
    parser.add_argument("--debug", action="store_true", help="Print per-parcel R2 upload diagnostics.")
    args = parser.parse_args()
    asyncio.run(run_media_harvester(args))


if __name__ == "__main__":
    main()