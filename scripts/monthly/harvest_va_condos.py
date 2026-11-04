import os
import re
import time
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEV_VARS_PATH = os.path.join(BASE_DIR, ".dev.vars")

def load_dev_vars():
    if os.path.exists(DEV_VARS_PATH):
        with open(DEV_VARS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

def sql_escape(val):
    if val is None:
        return "NULL"
    escaped = str(val).replace("'", "''")
    return f"'{escaped}'"

def execute_d1(session, endpoint, headers, sql_query):
    response = session.post(endpoint, headers=headers, json={"sql": sql_query}, timeout=45)
    data = response.json()
    if not data.get("success"):
        raise RuntimeError(f"Cloudflare D1 Query Failed: {data.get('errors', [])}")
    return data.get("result", [{}])[0].get("results", [])

def normalize_text(text):
    if not text:
        return ""
    text = str(text).upper()
    text = re.sub(r'\b(CONDOMINIUMS|CONDOMINIUM|CONDO|CONDOS|HOA|ASSOC|ASSOCIATION|THE|LLC|INC|A|BUILDING|BLDG|PHASE|PH)\b', '', text)
    text = re.sub(r'[^A-Z0-9\s]', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def normalize_street_address(address_str):
    if not address_str:
        return "", ""
    addr = str(address_str).upper()
    addr = re.sub(r'\b(UNIT|APT|STE|SUITE|BLDG|#)\b.*$', '', addr).strip()
    replacements = {
        'STREET': 'ST', 'AVENUE': 'AVE', 'ROAD': 'RD', 'DRIVE': 'DR',
        'BOULEVARD': 'BLVD', 'PLACE': 'PL', 'COURT': 'CT', 'LANE': 'LN',
        'NORTH': 'N', 'SOUTH': 'S', 'EAST': 'E', 'WEST': 'W',
        'NORTHEAST': 'NE', 'NORTHWEST': 'NW', 'SOUTHEAST': 'SE', 'SOUTHWEST': 'SW'
    }
    for full, kw in replacements.items():
        addr = re.sub(rf'\b{full}\b', kw, addr)
    addr = re.sub(r'[^A-Z0-9\s]', '', addr)
    addr = re.sub(r'\s+', ' ', addr).strip()
    match = re.match(r'^(\d+)\s+(.*)$', addr)
    if match:
        return match.group(1), match.group(2)
    return "", addr

def main():
    print("🚀 Starting VA LGY Direct D1 Ingestion...")
    load_dev_vars()

    cf_account_id = os.environ.get("CF_ACCOUNT_ID")
    cf_api_token = os.environ.get("CF_D1_API_TOKEN")
    cf_db_id = os.environ.get("CF_DATABASE_PARCELDATA_ID")

    if not all([cf_account_id, cf_api_token, cf_db_id]):
        raise ValueError("Missing Cloudflare D1 environment credentials.")

    endpoint = f"https://api.cloudflare.com/client/v4/accounts/{cf_account_id}/d1/database/{cf_db_id}/query"
    d1_headers = {
        "Authorization": f"Bearer {cf_api_token}",
        "Content-Type": "application/json"
    }
    d1_session = requests.Session()

    print("📡 Loading target complexes from Cloudflare D1 'condos' table...")
    existing_condos = execute_d1(d1_session, endpoint, d1_headers, "SELECT building_id, name, address, city, county FROM condos;")
    print(f"   Located {len(existing_condos):,} complexes in D1.")

    va_session = requests.Session()
    va_headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.5.2 Safari/605.1.15',
        'Accept': 'application/json, text/plain, */*',
        'Referer': 'https://lgy.va.gov/',
    }

    try:
        va_session.get('https://lgy.va.gov/', headers=va_headers, timeout=10)
    except Exception as e:
        print(f"⚠️ VA portal session notice: {e}")

    valid_dispositions = ["ACCEPTED WITHOUT CONDITIONS", "HUD ACCEPTED", "ACCEPTED WITH CONDITIONS"]
    va_clean_records = []

    for county in ['King', 'Snohomish']:
        print(f"📡 Querying VA LGY API for {county} County...")
        params = {
            'approved': 'true',
            'city': '',
            'condoId': '',
            'condoName': '',
            'county': county,
            'stateCode': 'WA',
            'station': '',
        }
        try:
            res = va_session.get('https://lgy.va.gov/lgyhub/api/condos/search', params=params, headers=va_headers, timeout=15)
            res.raise_for_status()
            data = res.json()
            records = data if isinstance(data, list) else data.get('content', data.get('results', []))
            for rec in records:
                if not isinstance(rec, dict):
                    continue
                disp = str(rec.get("dispositionCode", "")).upper()
                if not any(v in disp for v in valid_dispositions):
                    continue
                line1 = str(rec.get("firstLineName", "") or "").strip()
                line2 = str(rec.get("secondLineName", "") or "").strip()
                if re.match(r'^\d+\s+', line2):
                    raw_addr, raw_name = line2, line1
                elif re.match(r'^\d+\s+', line1):
                    raw_addr, raw_name = line1, line2
                else:
                    raw_addr, raw_name = line1, line1
                house_num, street_name = normalize_street_address(raw_addr)
                va_clean_records.append({
                    "name_norm": normalize_text(raw_name),
                    "house_num": house_num,
                    "street_norm": street_name,
                    "disposition": rec.get("dispositionCode", "Approved")
                })
        except Exception as e:
            print(f"❌ Error querying VA records for {county}: {e}")
        time.sleep(1)

    print(f"   Retrieved {len(va_clean_records):,} active VA approved records.")

    matches = {}
    for c in existing_condos:
        b_id = c["building_id"]
        c_house, c_street = normalize_street_address(c.get("address", ""))
        c_name = normalize_text(c.get("name", ""))

        for va in va_clean_records:
            addr_match = bool(c_house and c_house == va["house_num"] and (c_street in va["street_norm"] or va["street_norm"] in c_street))
            name_match = bool(len(c_name) > 3 and (c_name in va["name_norm"] or va["name_norm"] in c_name))

            if addr_match or name_match:
                matches[b_id] = va["disposition"]
                break

    print(f"⚡ Matched {len(matches):,} complexes to D1 records. Updating D1...")

    execute_d1(d1_session, endpoint, d1_headers, "UPDATE condos SET va_approved = 0, va_status = NULL;")

    statements = []
    for b_id, disposition in matches.items():
        statements.append(f"""
        UPDATE condos SET 
          va_approved = 1, 
          va_status = {sql_escape(disposition)},
          updated_utc = CURRENT_TIMESTAMP
        WHERE building_id = {sql_escape(b_id)};
        """)

    batch_size = 100
    for i in range(0, len(statements), batch_size):
        chunk = "\n".join(statements[i:i + batch_size])
        execute_d1(d1_session, endpoint, d1_headers, chunk)

    print(f"✅ Successfully synchronized {len(matches):,} VA approvals to Cloudflare D1.")

if __name__ == "__main__":
    main()