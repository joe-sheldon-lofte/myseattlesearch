import os
import re
import time
import requests
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEV_VARS_PATH = os.path.join(BASE_DIR, ".dev.vars")

CITIES_BY_COUNTY = {
    'King': [
        'Algona', 'Auburn', 'Bellevue', 'Black Diamond', 'Bothell', 'Burien', 
        'Carnation', 'Covington', 'Des Moines', 'Duvall', 'Enumclaw', 'Federal Way', 
        'Issaquah', 'Kenmore', 'Kent', 'Kirkland', 'Lake Forest Park', 'Maple Valley', 
        'Medina', 'Mercer Island', 'Newcastle', 'Normandy Park', 'North Bend', 'Pacific', 
        'Redmond', 'Renton', 'Sammamish', 'SeaTac', 'Seattle', 'Shoreline', 'Snoqualmie', 
        'Tukwila', 'Woodinville'
    ],
    'Snohomish': [
        'Arlington', 'Bothell', 'Brier', 'Edmonds', 'Everett', 'Granite Falls', 
        'Lake Stevens', 'Lynnwood', 'Marysville', 'Monroe', 'Mountlake Terrace', 
        'Mukilteo', 'Snohomish', 'Stanwood', 'Sultan'
    ]
}

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

def fetch_hud_table(session, headers, county, city, name_prefix=""):
    data = {
        'fapproval_method': 'NEW',
        'fsorted_by': 'condo_name',
        'fstate': 'WA',
        'fcounty': county,
        'fcondo_id': '',
        'fcondo_name': name_prefix,
        'fcity': city,
        'fzip': '',
        'fstatus_code': 'A',
        'fsearch_type': 'B',
        'fbegin_mo': '',
        'fbegin_dy': '',
        'fbegin_yr': '',
        'fend_mo': '',
        'fend_dy': '',
        'fend_yr': '',
        'came_from': 'oth',
        'in_fhac': 'true',
    }
    for attempt in range(3):
        try:
            res = session.post('https://entp.hud.gov/idapp/html/condo1.cfm', headers=headers, data=data, timeout=15)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, 'html.parser')
            tables = soup.find_all('table')
            target_table = None
            for table in tables:
                if "Condo Name" in table.text or "Property Name" in table.text or "Status" in table.text:
                    target_table = table
                    break
            if not target_table and len(tables) >= 2:
                target_table = tables[-1]
            records = []
            if target_table:
                rows = target_table.find_all('tr')
                headers_list = []
                for idx, row in enumerate(rows):
                    cols = [ele.text.strip() for ele in row.find_all(['td', 'th'])]
                    if not cols:
                        continue
                    if idx == 0 or not headers_list:
                        headers_list = [c.lower().replace(" ", "_") for c in cols]
                        continue
                    if len(cols) == len(headers_list):
                        item = dict(zip(headers_list, cols))
                        item['source_county'] = county
                        records.append(item)
            return records
        except Exception:
            time.sleep(1)
    return []

def main():
    print("🚀 Starting HUD FHA Direct D1 Ingestion...")
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

    hud_session = requests.Session()
    hud_headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.5.2 Safari/605.1.15',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Origin': 'https://entp.hud.gov',
        'Referer': 'https://entp.hud.gov/idapp/html/condlook.cfm',
    }

    try:
        hud_session.get('https://entp.hud.gov/idapp/html/condlook.cfm', headers=hud_headers, timeout=10)
    except Exception as e:
        print(f"⚠️ HUD session init notice: {e}")

    fha_clean_records = []
    seen_ids = set()
    letters_and_digits = [chr(i) for i in range(ord('A'), ord('Z')+1)] + [str(i) for i in range(10)]

    for county, cities in CITIES_BY_COUNTY.items():
        print(f"📡 Querying HUD ENTP for {county} County...")
        for city in cities:
            records = fetch_hud_table(hud_session, hud_headers, county, city, name_prefix="")
            if len(records) >= 25:
                records = []
                for char in letters_and_digits:
                    records.extend(fetch_hud_table(hud_session, hud_headers, county, city, name_prefix=char))
                    time.sleep(0.05)

            for item in records:
                condo_id = item.get("condo_id_/submission", "")
                status = str(item.get("status", "")).upper()
                if condo_id and condo_id not in seen_ids and "APPROVED" in status:
                    seen_ids.add(condo_id)
                    raw_addr = item.get("address", "")
                    clean_addr = raw_addr.split(",")[0].strip() if raw_addr else ""
                    house_num, street_name = normalize_street_address(clean_addr)
                    fha_clean_records.append({
                        "name_norm": normalize_text(item.get("condoname", "")),
                        "house_num": house_num,
                        "street_norm": street_name,
                        "expiration_date": str(item.get("expirationdate", "")).split("\r")[0].strip()
                    })
            time.sleep(0.05)

    print(f"   Retrieved {len(fha_clean_records):,} active HUD approved complexes.")

    matches = {}
    for c in existing_condos:
        b_id = c["building_id"]
        c_house, c_street = normalize_street_address(c.get("address", ""))
        c_name = normalize_text(c.get("name", ""))

        for fha in fha_clean_records:
            addr_match = bool(c_house and c_house == fha["house_num"] and (c_street in fha["street_norm"] or fha["street_norm"] in c_street))
            name_match = bool(len(c_name) > 3 and (c_name in fha["name_norm"] or fha["name_norm"] in c_name))

            if addr_match or name_match:
                matches[b_id] = fha["expiration_date"]
                break

    print(f"⚡ Matched {len(matches):,} complexes to D1 records. Updating D1...")

    execute_d1(d1_session, endpoint, d1_headers, "UPDATE condos SET fha_approved = 0, fha_expiration_date = NULL;")

    statements = []
    for b_id, exp_date in matches.items():
        statements.append(f"""
        UPDATE condos SET 
          fha_approved = 1, 
          fha_expiration_date = {sql_escape(exp_date)},
          updated_utc = CURRENT_TIMESTAMP
        WHERE building_id = {sql_escape(b_id)};
        """)

    batch_size = 100
    for i in range(0, len(statements), batch_size):
        chunk = "\n".join(statements[i:i + batch_size])
        execute_d1(d1_session, endpoint, d1_headers, chunk)

    print(f"✅ Successfully synchronized {len(matches):,} FHA approvals to Cloudflare D1.")

if __name__ == "__main__":
    main()