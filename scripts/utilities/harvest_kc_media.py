import os
import io
import csv
import time
import zipfile
import sqlite3
import asyncio
import argparse
from urllib.parse import urljoin
import httpx
import boto3
from bs4 import BeautifulSoup
from PIL import Image

MAX_SQL_BYTES = 75000
D1_FLUSH_EVERY = 40
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"


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
            media_count INTEGER DEFAULT 0,
            updated_utc TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    return conn


def get_completed_pins(conn):
    cur = conn.execute("SELECT parcel_number FROM harvest_log WHERE status IN ('DONE', 'NO_MEDIA');")
    return {row[0] for row in cur.fetchall()}


def derive_kc_building_style(row):
    """Derives canonical architectural style from King County ResBldg floor metrics."""
    try:
        stories = float(row.get("Stories") or 0)
    except (ValueError, TypeError):
        stories = 0.0

    def sf(col):
        try:
            return float(row.get(col) or 0)
        except (ValueError, TypeError):
            return 0.0

    f1 = sf("SqFt1stFloor")
    fh = sf("SqFtHalfFloor")
    f2 = sf("SqFt2ndFloor")
    fu = sf("SqFtUpperFloor")
    bsmt = sf("SqFtFinBasement")

    if fh > 0 and f2 == 0 and stories < 1.5:
        return "Split / Tri-Level"
    if 1.0 < stories < 1.5 and bsmt > 0 and f2 == 0:
        return "Split / Tri-Level"
    if 1.4 <= stories < 1.9 or (fh > 0 and f2 == 0):
        return "1.5-Story"
    if stories >= 1.9 or f2 > 0 or fu > 0:
        return "2-Story"
    if stories >= 1.0 or f1 > 0:
        return "1-Story"
    return None


def backfill_kc_styles_from_resbldg(staging_dir, endpoint, headers):
    """Populates base.building_style in bulk from kc-resbldg.csv (or downloads ResBldg.zip)."""
    resbldg_path = os.path.join(staging_dir, "kc-resbldg.csv")
    style_map = {}

    if os.path.exists(resbldg_path):
        print("📂 Reading local kc-resbldg.csv to backfill King County building_style...")
        with open(resbldg_path, "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f)
            for r in reader:
                maj = str(r.get("Major", "")).strip().zfill(6)
                minr = str(r.get("Minor", "")).strip().zfill(4)
                pin = f"{maj}{minr}"
                style = derive_kc_building_style(r)
                if style:
                    style_map[pin] = style
    else:
        print("📥 Downloading ResBldg.zip from King County to backfill building_style...")
        resp = httpx.get("https://dorcdn.kingcounty.gov/datadownload/ResBldg.zip", timeout=120.0)
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            target = [n for n in z.namelist() if n.lower().endswith(".csv")][0]
            with z.open(target) as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8", errors="ignore"))
                for r in reader:
                    maj = str(r.get("Major", "")).strip().zfill(6)
                    minr = str(r.get("Minor", "")).strip().zfill(4)
                    pin = f"{maj}{minr}"
                    style = derive_kc_building_style(r)
                    if style:
                        style_map[pin] = style

    print("🔄 Applying Townhouse/Condo overrides and batch-updating base.building_style...")
    execute_d1_sync(
        endpoint,
        headers,
        "UPDATE base SET building_style = 'Townhouse' WHERE county = 'KING' AND property_type = 'Townhouse' AND building_style IS NULL;",
    )
    execute_d1_sync(
        endpoint,
        headers,
        "UPDATE base SET building_style = 'Condo' WHERE county = 'KING' AND property_type = 'Condo' AND building_style IS NULL;",
    )

    items = list(style_map.items())
    total = len(items)
    stmts = []
    curr_bytes = 0
    committed = 0

    for pin, style in items:
        stmt = (
            f"UPDATE base SET building_style = {sql_val(style)} "
            f"WHERE parcel_number = {sql_val(pin)} AND building_style IS NULL;"
        )
        b_len = len(stmt.encode("utf-8")) + 1
        if stmts and (len(stmts) >= 250 or (curr_bytes + b_len) > MAX_SQL_BYTES):
            execute_d1_sync(endpoint, headers, "\n".join(stmts))
            committed += len(stmts)
            print(f"\r   Updated styles: {committed:,} / {total:,}", end="", flush=True)
            stmts = []
            curr_bytes = 0
        stmts.append(stmt)
        curr_bytes += b_len

    if stmts:
        execute_d1_sync(endpoint, headers, "\n".join(stmts))
        committed += len(stmts)
        print(f"\r   Updated styles: {committed:,} / {total:,}", end="", flush=True)

    print("\n✅ King County building_style backfill complete.")


def parse_kc_media_html(html_text, base_url):
    """Extracts exterior photos and building floorplan sketches from eRealProperty HTML."""
    soup = BeautifulSoup(html_text, "html.parser")
    candidates = []
    seen_urls = set()

    for img in soup.find_all("img"):
        src = (img.get("src") or "").strip()
        if not src:
            continue
        low_src = src.lower()
        alt_txt = (img.get("alt") or img.get("title") or "").lower()

        if any(skip in low_src for skip in ["logo", "icon", "banner", "spacer", "btn", "button", "header", "footer", "kc_logo", "camera"]):
            continue
        if not any(tok in low_src for tok in ["image", "picture", "photo", "sketch", ".jpg", ".jpeg", ".png", ".gif"]):
            continue

        full_url = urljoin(base_url, src)
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        is_sketch = ("sketch" in low_src) or ("sketch" in alt_txt) or ("footprint" in alt_txt) or ("section" in alt_txt)
        media_type = "SKETCH" if is_sketch else "EXTERIOR"
        candidates.append((media_type, full_url))

    return candidates


def encode_webp_bytes(raw_bytes, max_width=1200, quality=82):
    with Image.open(io.BytesIO(raw_bytes)) as im:
        if im.width < 80 or im.height < 80:
            return None
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGB")
        if im.width > max_width:
            ratio = max_width / float(im.width)
            new_h = max(1, int(round(im.height * ratio)))
            im = im.resize((max_width, new_h), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        im.save(out, format="WEBP", quality=quality, method=4)
        return out.getvalue()


def fetch_kc_target_queue(endpoint, headers, staging_dir, completed_pins, sales_only=False, limit=None):
    """Uses primary-key keyset pagination (zero full-table sort) and caches queue to disk."""
    cache_name = "kc_sales_queue.txt" if sales_only else "kc_full_queue.txt"
    cache_path = os.path.join(staging_dir, cache_name)

    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
        with open(cache_path, "r", encoding="utf-8") as f:
            all_pins = [line.strip() for line in f if line.strip()]
        targets = [p for p in all_pins if p not in completed_pins]
        print(f"📋 Loaded {len(targets):,} remaining King County parcels from cached queue ({cache_name}).")
        return targets[:limit] if limit else targets

    print("🔍 Indexing King County residential parcels via primary-key seek (avoids D1 sort overload)...")
    ordered_pins = []
    seen_pins = set()

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
            WHERE county = 'KING'
              AND property_type IN ('Single Family', 'Townhouse', 'Condo', 'Multi-Family', 'Residential')
              AND minor_code != '0000'
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
                if pin not in seen_pins:
                    seen_pins.add(pin)
                    ordered_pins.append(pin)
            print(f"\r   Indexed {len(ordered_pins):,} King County residential parcels...", end="", flush=True)
            time.sleep(0.35)

    print()
    if ordered_pins:
        os.makedirs(staging_dir, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            for p in ordered_pins:
                f.write(f"{p}\n")

    targets = [p for p in ordered_pins if p not in completed_pins]
    print(f"🎯 Queued {len(targets):,} King County parcels for photo & sketch harvesting.")
    return targets[:limit] if limit else targets


def flush_media_to_d1(endpoint, headers, media_rows):
    if not media_rows:
        return

    def build_media_sql(tuples):
        return f"""
        INSERT OR IGNORE INTO parcel_media (
            parcel_number, county, media_type, sequence_num, r2_key, source_url, created_utc
        ) VALUES {",".join(tuples)};
        """

    overhead = len(build_media_sql(["()"]).encode("utf-8"))
    tuples = []
    curr_bytes = overhead

    for m in media_rows:
        t_str = (
            f"({sql_val(m['parcel_number'])}, 'KING', {sql_val(m['media_type'])}, "
            f"{sql_val(m['sequence_num'])}, {sql_val(m['r2_key'])}, {sql_val(m['source_url'])}, CURRENT_TIMESTAMP)"
        )
        b_len = len(t_str.encode("utf-8")) + 1
        if tuples and (len(tuples) >= 150 or (curr_bytes + b_len) > MAX_SQL_BYTES):
            execute_d1_sync(endpoint, headers, build_media_sql(tuples))
            tuples = []
            curr_bytes = overhead
        tuples.append(t_str)
        curr_bytes += b_len

    if tuples:
        execute_d1_sync(endpoint, headers, build_media_sql(tuples))


async def process_kc_parcel(client, sem, s3_client, r2_bucket, pin):
    pic_url = f"https://blue.kingcounty.com/Assessor/eRealProperty/pictures.aspx?ParcelNbr={pin}&View=1"
    detail_url = f"https://blue.kingcounty.com/Assessor/eRealProperty/Detail.aspx?ParcelNbr={pin}"

    async with sem:
        await asyncio.sleep(0.06)
        for attempt in range(3):
            try:
                resp = await client.get(pic_url, follow_redirects=True, timeout=30.0)
                if resp.status_code in (429, 503):
                    await asyncio.sleep(2.0 * (attempt + 1))
                    continue

                candidates = parse_kc_media_html(resp.text, str(resp.url)) if resp.status_code == 200 else []
                if not candidates:
                    det_resp = await client.get(detail_url, follow_redirects=True, timeout=30.0)
                    if det_resp.status_code == 200:
                        candidates = parse_kc_media_html(det_resp.text, str(det_resp.url))

                uploaded_media = []
                seq_counters = {"EXTERIOR": 0, "SKETCH": 0}

                for media_type, img_url in candidates[:8]:
                    try:
                        img_resp = await client.get(img_url, follow_redirects=True, timeout=20.0)
                        if img_resp.status_code != 200 or not img_resp.content:
                            continue
                        webp_bytes = await asyncio.to_thread(encode_webp_bytes, img_resp.content)
                        if not webp_bytes:
                            continue
                        seq_counters[media_type] += 1
                        seq = seq_counters[media_type]
                        r2_key = f"parcels/king/{pin}/{media_type.lower()}-{seq}.webp"
                        await asyncio.to_thread(
                            s3_client.put_object,
                            Bucket=r2_bucket,
                            Key=r2_key,
                            Body=webp_bytes,
                            ContentType="image/webp",
                        )
                        uploaded_media.append({
                            "parcel_number": pin,
                            "media_type": media_type,
                            "sequence_num": seq,
                            "r2_key": r2_key,
                            "source_url": img_url,
                        })
                    except Exception:
                        continue

                status = "DONE" if uploaded_media else "NO_MEDIA"
                return pin, status, uploaded_media
            except (httpx.RequestError, asyncio.TimeoutError):
                if attempt == 2:
                    return pin, "ERROR", []
                await asyncio.sleep(1.5 * (attempt + 1))

    return pin, "ERROR", []


async def run_kc_harvester(args):
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    staging_dir = os.path.join(base_dir, "data", "staging")
    load_dev_vars(base_dir)

    cf_account_id = os.environ.get("CF_ACCOUNT_ID")
    cf_api_token = os.environ.get("CF_D1_API_TOKEN")
    cf_db_id = os.environ.get("CF_DATABASE_PARCELDATA_ID")
    r2_access_key = os.environ.get("R2_ACCESS_KEY_ID")
    r2_secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
    r2_bucket = os.environ.get("R2_BUCKET_NAME")

    if not all([cf_account_id, cf_api_token, cf_db_id, r2_access_key, r2_secret_key, r2_bucket]):
        raise ValueError("Missing Cloudflare D1 or R2 credentials in .dev.vars.")

    endpoint = f"https://api.cloudflare.com/client/v4/accounts/{cf_account_id}/d1/database/{cf_db_id}/query"
    headers = {"Authorization": f"Bearer {cf_api_token}", "Content-Type": "application/json"}

    if not args.skip_style_backfill:
        await asyncio.to_thread(backfill_kc_styles_from_resbldg, staging_dir, endpoint, headers)

    if args.style_only:
        return

    s3_client = boto3.client(
        "s3",
        endpoint_url=f"https://{cf_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=r2_access_key,
        aws_secret_access_key=r2_secret_key,
        region_name="auto",
    )

    ckpt_path = os.path.join(staging_dir, "kc_harvest.db")
    ckpt_conn = init_checkpoint_db(ckpt_path)
    completed_pins = get_completed_pins(ckpt_conn)
    print(f"💾 Checkpoint loaded: {len(completed_pins):,} King County parcels already harvested.")

    targets = fetch_kc_target_queue(endpoint, headers, staging_dir, completed_pins, sales_only=args.sales_only, limit=args.limit)
    if not targets:
        print("✅ All queued King County parcels are already harvested.")
        return

    sem = asyncio.Semaphore(args.concurrency)
    pending_media = []
    processed = 0
    total = len(targets)

    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, limits=httpx.Limits(max_connections=args.concurrency + 4)) as client:
        for chunk_start in range(0, total, D1_FLUSH_EVERY):
            batch = targets[chunk_start:chunk_start + D1_FLUSH_EVERY]
            tasks = [process_kc_parcel(client, sem, s3_client, r2_bucket, pin) for pin in batch]
            results = await asyncio.gather(*tasks)

            for pin, status, uploaded_media in results:
                processed += 1
                if uploaded_media:
                    pending_media.extend(uploaded_media)
                if status in ("DONE", "NO_MEDIA"):
                    ckpt_conn.execute(
                        "INSERT OR REPLACE INTO harvest_log (parcel_number, status, media_count, updated_utc) VALUES (?, ?, ?, CURRENT_TIMESTAMP);",
                        (pin, status, len(uploaded_media)),
                    )

            ckpt_conn.commit()
            if pending_media:
                await asyncio.to_thread(flush_media_to_d1, endpoint, headers, pending_media)
                pending_media.clear()

            print(f"\r🚀 King County Media Harvested: {processed:,} / {total:,}", end="", flush=True)

    print("\n✅ King County Style & Media Harvest Complete.")


def main():
    parser = argparse.ArgumentParser(description="King County Building Style Backfill & Async Photo/Sketch Harvester.")
    parser.add_argument("--concurrency", type=int, default=10, help="Concurrent HTTP workers (default: 10).")
    parser.add_argument("--sales-only", action="store_true", help="Only harvest parcels with recent sales first.")
    parser.add_argument("--skip-style-backfill", action="store_true", help="Skip the bulk ResBldg building_style pass.")
    parser.add_argument("--style-only", action="store_true", help="Only run the bulk building_style backfill.")
    parser.add_argument("--limit", type=int, default=None, help="Max parcels to process in this run.")
    args = parser.parse_args()
    asyncio.run(run_kc_harvester(args))


if __name__ == "__main__":
    main()