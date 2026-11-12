import os
import re
import time
import sqlite3
import asyncio
import argparse
from urllib.parse import urljoin
import httpx
from bs4 import BeautifulSoup

MAX_SQL_BYTES = 75000
D1_FLUSH_EVERY = 50
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


def page_matches_pin(html_text, pin):
    """Verifies the returned HTML actually belongs to the requested parcel number."""
    clean_pin = str(pin).strip()
    if clean_pin in html_text:
        return True
    if len(clean_pin) == 14 and clean_pin.isdigit():
        hyphenated = f"{clean_pin[:6]}-{clean_pin[6:9]}-{clean_pin[9:12]}-{clean_pin[12:14]}"
        if hyphenated in html_text:
            return True
    return False


def normalize_snoco_style(raw_style, prop_type=None):
    if prop_type == "Condo":
        return "Condo"
    if prop_type == "Townhouse":
        return "Townhouse"
    if not raw_style:
        return None
    s = str(raw_style).strip().lower()
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
    if "1" in s or "one" in s or "rambl" in s or "ranch" in s or "single" in s:
        return "1-Story"
    return raw_style.strip()[:40]


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


def extract_structure_actions(html_text, base_url):
    """
    Extracts ASP.NET __doPostBack payloads or direct URLs for 'View Detailed Structure Information'.
    Returns a list of tuples: ('POST', post_url, form_data) or ('GET', target_url, None).
    """
    soup = BeautifulSoup(html_text, "html.parser")
    form = soup.find("form")
    base_form_data = {}
    form_action_url = base_url

    if form:
        action_attr = (form.get("action") or "").strip()
        if action_attr:
            form_action_url = urljoin(base_url, action_attr)
        for inp in form.find_all("input"):
            name = inp.get("name")
            if not name:
                continue
            inp_type = (inp.get("type") or "text").lower()
            if inp_type in ("submit", "button", "image", "reset", "file"):
                continue
            if inp_type in ("checkbox", "radio") and not inp.has_attr("checked"):
                continue
            base_form_data[name] = inp.get("value") or ""

    actions = []
    seen = set()

    for tag in soup.find_all(["a", "input", "button"]):
        txt = (tag.get_text(" ", strip=True) or tag.get("value") or "").lower()
        href = (tag.get("href") or "").strip()
        onclick = (tag.get("onclick") or "").strip()
        combined_js = f"{href} {onclick}"

        if not any(kw in txt or kw in combined_js.lower() for kw in ["detailed structure", "structure information", "structure"]):
            continue

        m = re.search(r'__doPostBack\(\s*[\'"]([^\'"]+)[\'"]\s*,\s*[\'"]([^\'"]*)[\'"]\s*\)', combined_js)
        if m and form:
            target, arg = m.group(1), m.group(2)
            key = ("POST", target, arg)
            if key not in seen:
                seen.add(key)
                payload = dict(base_form_data)
                payload["__EVENTTARGET"] = target
                payload["__EVENTARGUMENT"] = arg
                actions.append(("POST", form_action_url, payload))
        elif tag.name in ("input", "button") and (tag.get("type") or "").lower() == "submit" and tag.get("name") and form:
            btn_name = tag["name"]
            key = ("POST", btn_name, "")
            if key not in seen:
                seen.add(key)
                payload = dict(base_form_data)
                payload[btn_name] = tag.get("value") or "View Detailed Structure Information"
                actions.append(("POST", form_action_url, payload))
        elif href and not href.lower().startswith("javascript:") and not href.startswith("#"):
            full_url = urljoin(base_url, href)
            key = ("GET", full_url, "")
            if key not in seen:
                seen.add(key)
                actions.append(("GET", full_url, None))

    return actions


def parse_structure_html(html_text, prop_type=None, debug_kv=False, pin=""):
    """Parses interior GLA, beds/baths, style, quality, and condition from Aumentum HTML."""
    soup = BeautifulSoup(html_text, "html.parser")
    kv_pairs = {}

    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        if len(cells) >= 2:
            for idx in range(len(cells) - 1):
                label = cells[idx].rstrip(":").strip().lower()
                val = cells[idx + 1].strip()
                if label and val and len(label) <= 55:
                    kv_pairs.setdefault(label, val)

    for tbl in soup.find_all("table"):
        rows = tbl.find_all("tr")
        for r_idx in range(len(rows) - 1):
            headers = [c.get_text(" ", strip=True).rstrip(":").strip().lower() for c in rows[r_idx].find_all(["th", "td"])]
            vals = [c.get_text(" ", strip=True) for c in rows[r_idx + 1].find_all(["th", "td"])]
            if len(headers) == len(vals) and len(headers) >= 2:
                for h, v in zip(headers, vals):
                    if h and v and len(h) <= 55:
                        kv_pairs.setdefault(h, v)

    if debug_kv:
        sample_items = list(kv_pairs.items())[:35]
        print(f"[DEBUG {pin}] Extracted KV pairs ({len(kv_pairs)} total): {sample_items}")

    def find_val(keywords):
        for k, v in kv_pairs.items():
            for kw in keywords:
                if kw in k and v and v.lower() not in {"n/a", "none", "-", "0", "0.00"}:
                    return v
        return None

    gla = None
    raw_gla = find_val([
        "total living area", "finished area", "living area", "gross living",
        "total finished", "above grade", "main floor area", "base area", "sq ft", "square feet"
    ])
    if raw_gla:
        digits = re.sub(r"[^0-9.]", "", raw_gla)
        if digits:
            try:
                val_int = int(float(digits))
                if 150 <= val_int <= 45000:
                    gla = val_int
            except ValueError:
                pass

    if not gla:
        floor_sum = 0
        for k, v in kv_pairs.items():
            if any(fk in k for fk in ["1st floor", "first floor", "2nd floor", "second floor", "upper floor", "finished basement", "bsmt fin", "half story"]):
                digits = re.sub(r"[^0-9.]", "", v)
                if digits:
                    try:
                        val_int = int(float(digits))
                        if 50 <= val_int <= 25000:
                            floor_sum += val_int
                    except ValueError:
                        pass
        if 150 <= floor_sum <= 45000:
            gla = floor_sum

    if not gla:
        m = re.search(
            r"(?:Total Living Area|Living Area|Finished Area|Gross Area)\s*:?\s*([0-9,]{3,6})",
            soup.get_text(" "),
            re.IGNORECASE,
        )
        if m:
            val_int = int(m.group(1).replace(",", ""))
            if 150 <= val_int <= 45000:
                gla = val_int

    year_built = None
    raw_yb = find_val(["year built", "yr built", "effective year"])
    if raw_yb:
        m = re.search(r"(18\d{2}|19\d{2}|20[0-3]\d)", raw_yb)
        if m:
            year_built = int(m.group(1))

    bedrooms = None
    raw_beds = find_val(["bedroom", "beds"])
    if raw_beds:
        m = re.search(r"(\d+)", raw_beds)
        if m:
            bedrooms = int(m.group(1))

    bath_full = None
    bath_half = None
    raw_full = find_val(["full or 3/4", "full bath", "baths full", "3/4 bath", "bathrooms", "baths"])
    if raw_full:
        m_float = re.search(r"(\d+)(?:\.(\d+))?", raw_full)
        if m_float:
            bath_full = int(m_float.group(1))
            if m_float.group(2) and int(m_float.group(2)) > 0:
                bath_half = 1
    raw_half = find_val(["1/2 bath", "half bath", "baths half"])
    if raw_half:
        m_h = re.search(r"(\d+)", raw_half)
        if m_h:
            bath_half = int(m_h.group(1))

    raw_style = find_val(["style", "bldg style", "building style", "story", "stories"])
    style = normalize_snoco_style(raw_style, prop_type)
    grade = normalize_snoco_grade(find_val(["quality", "grade", "construction quality"]))
    condition = normalize_snoco_condition(find_val(["condition", "bldg condition"]))

    return {
        "square_footage": gla,
        "year_built": year_built,
        "bedrooms": bedrooms,
        "bath_full": bath_full,
        "bath_half": bath_half,
        "building_grade": grade,
        "building_condition": condition,
        "building_style": style,
    }


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


async def process_parcel(client, sem, pin, prop_type, debug_html=False):
    # Hit ParcelInfo.aspx directly so IIS issues the cookieless session redirect straight to the parcel
    direct_url = f"https://www.snoco.org/proptax/ParcelInfo.aspx?parcel_number={pin}"
    async with sem:
        await asyncio.sleep(0.05)
        for attempt in range(3):
            try:
                resp = await client.get(direct_url, follow_redirects=True, timeout=30.0)
                final_url = str(resp.url)

                if "proptax" not in final_url.lower():
                    if debug_html:
                        print(f"\n[DEBUG {pin}] Maintenance redirect -> {final_url}")
                    return pin, "MAINTENANCE", None

                if resp.status_code in (429, 503):
                    await asyncio.sleep(2.0 * (attempt + 1))
                    continue
                if resp.status_code != 200:
                    return pin, "ERROR", None

                html_text = resp.text
                if not page_matches_pin(html_text, pin):
                    if debug_html:
                        print(f"\n[DEBUG {pin}] PIN not found in page body at {final_url} (aborting safely)")
                    return pin, "INVALID_PAGE", None

                structure_actions = extract_structure_actions(html_text, final_url)
                best_attrs = parse_structure_html(html_text, prop_type, debug_kv=debug_html, pin=pin)

                if debug_html:
                    print(f"[DEBUG {pin}] Active URL: {final_url} | Structure actions: {len(structure_actions)}")

                for method, target_url, payload in structure_actions[:3]:
                    try:
                        if method == "POST":
                            s_resp = await client.post(
                                target_url,
                                data=payload,
                                headers={"Referer": final_url},
                                follow_redirects=True,
                                timeout=25.0,
                            )
                        else:
                            s_resp = await client.get(
                                target_url,
                                headers={"Referer": final_url},
                                follow_redirects=True,
                                timeout=25.0,
                            )

                        if s_resp.status_code == 200 and "proptax" in str(s_resp.url).lower():
                            s_attrs = parse_structure_html(s_resp.text, prop_type, debug_kv=debug_html, pin=pin)
                            if debug_html:
                                print(f"[DEBUG {pin}] Structure subpage parsed -> {s_attrs}")
                            if (s_attrs.get("square_footage") or 0) >= (best_attrs.get("square_footage") or 0):
                                for k, v in s_attrs.items():
                                    if v is not None:
                                        best_attrs[k] = v
                            else:
                                for k, v in s_attrs.items():
                                    if best_attrs.get(k) is None and v is not None:
                                        best_attrs[k] = v
                    except Exception as sub_err:
                        if debug_html:
                            print(f"[DEBUG {pin}] Subpage error: {sub_err}")
                        continue

                status = "DONE" if best_attrs.get("square_footage") else "NO_STRUCTURE"
                return pin, status, best_attrs
            except (httpx.RequestError, asyncio.TimeoutError):
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

    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, limits=httpx.Limits(max_connections=args.concurrency + 4)) as client:
        chunk_start = 0
        while chunk_start < total:
            batch = targets[chunk_start:chunk_start + D1_FLUSH_EVERY]
            tasks = [
                process_parcel(client, sem, pin, ptype, args.debug_html)
                for pin, ptype in batch
            ]
            results = await asyncio.gather(*tasks)

            maintenance_hits = sum(1 for _, st, _ in results if st == "MAINTENANCE")
            if maintenance_hits >= max(1, len(batch) // 2):
                print("\n⏸️ Snohomish Assessor portal is in maintenance/offline mode. Pausing 60s before retrying batch...")
                await asyncio.sleep(60)
                continue

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
    parser = argparse.ArgumentParser(description="Async Snohomish County Interior GLA, Style & Hedonic Harvester (Attributes Only).")
    parser.add_argument("--concurrency", type=int, default=12, help="Concurrent HTTP workers (default: 12).")
    parser.add_argument("--sales-only", action="store_true", help="Only harvest parcels with recent sales first.")
    parser.add_argument("--queue-file", type=str, default=None, help="Path to delta PIN queue file.")
    parser.add_argument("--limit", type=int, default=None, help="Max parcels to process in this run.")
    parser.add_argument("--debug-html", action="store_true", help="Print parsed KV pairs and structure attributes.")
    args = parser.parse_args()
    asyncio.run(run_harvester(args))


if __name__ == "__main__":
    main()