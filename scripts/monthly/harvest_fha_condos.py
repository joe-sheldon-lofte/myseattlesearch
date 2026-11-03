import os
import json
import time
import requests
from bs4 import BeautifulSoup

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))
DATA_DIR = os.path.join(BASE_DIR, "data")
STAGING_DIR = os.path.join(DATA_DIR, "staging")
OUT_PATH = os.path.join(STAGING_DIR, "fha_condos_raw.json")

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

def fetch_hud_table(session, headers, county, city, name_prefix=""):
    """Queries HUD's ColdFusion server with 3-attempt retry logic for network drops."""
    data = {
        'fapproval_method': 'NEW',
        'fsorted_by': 'condo_name',
        'fstate': 'WA',
        'fcounty': county,
        'fcondo_id': '',
        'fcondo_name': name_prefix,  # Filter by starting character when paginating
        'fcity': city,
        'fzip': '',
        'fstatus_code': 'A',  # Strictly APPROVED only
        'fsearch_type': 'B',  # 'B' = Begins with
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
        except Exception as e:
            if attempt == 2:
                print(f"❌ Error fetching {city} (prefix: '{name_prefix}'), {county}: {e}")
            time.sleep(1)
            
    return []

def harvest_fha_condos():
    print("🚀 Starting HUD FHA Condo Harvester (With Cap Bypass & Retry Logic)...")
    os.makedirs(STAGING_DIR, exist_ok=True)
    
    session = requests.Session()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.5.2 Safari/605.1.15',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Origin': 'https://entp.hud.gov',
        'Referer': 'https://entp.hud.gov/idapp/html/condlook.cfm',
    }
    
    print("📡 Establishing session with HUD FHA server...")
    try:
        session.get('https://entp.hud.gov/idapp/html/condlook.cfm', headers=headers, timeout=10)
    except Exception as e:
        print(f"⚠️ Initial session request failed: {e}")

    all_fha_condos = []
    seen_ids = set()
    
    letters_and_digits = [chr(i) for i in range(ord('A'), ord('Z')+1)] + [str(i) for i in range(10)]
    
    for county, cities in CITIES_BY_COUNTY.items():
        print(f"\nFetching FHA data for {county} County ({len(cities)} cities)...")
        
        for city in cities:
            records = fetch_hud_table(session, headers, county, city, name_prefix="")
            
            # If records hit the 25-record cap, split the query by starting character!
            if len(records) >= 25:
                print(f"   - {city}: Hit 25-record cap! Splitting query by letter prefixes A-Z, 0-9...")
                records = []
                for char in letters_and_digits:
                    sub_records = fetch_hud_table(session, headers, county, city, name_prefix=char)
                    records.extend(sub_records)
                    time.sleep(0.05)
                    
            city_count = 0
            for item in records:
                condo_id = item.get("condo_id_/submission", "")
                if condo_id and condo_id not in seen_ids:
                    seen_ids.add(condo_id)
                    all_fha_condos.append(item)
                    city_count += 1
                    
            if city_count > 0:
                print(f"   - {city}: {city_count} approved FHA condo(s)")
                
            time.sleep(0.1)

    print(f"\nSuccessfully harvested {len(all_fha_condos)} total APPROVED FHA records across all cities.")
    
    with open(OUT_PATH, 'w') as f:
        json.dump(all_fha_condos, f, indent=2)
        
    print(f"💾 Saved to {OUT_PATH}\n")

if __name__ == "__main__":
    harvest_fha_condos()