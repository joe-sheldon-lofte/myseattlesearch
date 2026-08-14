import os
import json
import re
import shutil
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))
DATA_DIR = os.path.join(BASE_DIR, "data")
STAGING_DIR = os.path.join(DATA_DIR, "staging")
MASTER_OUT_PATH = os.path.join(DATA_DIR, "all_condos.json")

def organize_staging_directory():
    """Ensures data/staging directory exists and moves any stray raw JSONs inside."""
    os.makedirs(STAGING_DIR, exist_ok=True)
    files_to_stage = [
        "king_county_raw.json", "king_condos.json",
        "snohomish_county_raw.json", "snohomish_condos.json",
        "fha_condos_raw.json", "va_condos_raw.json"
    ]
    
    for filename in files_to_stage:
        old_path = os.path.join(DATA_DIR, filename)
        new_path = os.path.join(STAGING_DIR, filename)
        if os.path.exists(old_path) and not os.path.exists(new_path):
            shutil.move(old_path, new_path)

def cleanup_staging_directory():
    """Deletes temporary staging directory to keep repository completely clean."""
    if os.path.exists(STAGING_DIR):
        shutil.rmtree(STAGING_DIR)
        print("🧹 Cleaned up temporary staging files.")

def normalize_text(text):
    """Strips punctuation and legal filler words for matching."""
    if not text: return ""
    text = str(text).upper()
    text = re.sub(r'\b(CONDOMINIUMS|CONDOMINIUM|CONDO|CONDOS|HOA|ASSOC|ASSOCIATION|THE|LLC|INC|A|BUILDING|BLDG|PHASE|PH)\b', '', text)
    text = re.sub(r'[^A-Z0-9\s]', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def normalize_street_address(address_str):
    """Standardizes street suffixes and extracts house number + street name."""
    if not address_str: return "", ""
    addr = str(address_str).upper()
    
    # Strip unit/apt designations
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

def parse_fha_records():
    """Loads and parses FHA records into normalized match structures."""
    fha_path = os.path.join(STAGING_DIR, "fha_condos_raw.json")
    if not os.path.exists(fha_path): return []
    
    with open(fha_path, 'r') as f:
        raw_fha = json.load(f)
        
    cleaned_fha = []
    for row in raw_fha:
        status = str(row.get("status", "")).strip().title()
        if "APPROVED" not in status.upper():
            continue
            
        raw_addr = row.get("address", "")
        clean_addr = raw_addr.split(",")[0].strip() if raw_addr else ""
        house_num, street_name = normalize_street_address(clean_addr)
        
        cleaned_fha.append({
            "name_norm": normalize_text(row.get("condoname", "")),
            "house_num": house_num,
            "street_norm": street_name,
            "expiration_date": str(row.get("expirationdate", "")).split("\r")[0].strip(),
            "county": row.get("source_county", "")
        })
    return cleaned_fha

def parse_va_records():
    """Loads and parses VA records into normalized match structures."""
    va_path = os.path.join(STAGING_DIR, "va_condos_raw.json")
    if not os.path.exists(va_path): return []
    
    with open(va_path, 'r') as f:
        raw_va = json.load(f)
        
    valid_dispositions = ["ACCEPTED WITHOUT CONDITIONS", "HUD ACCEPTED", "ACCEPTED WITH CONDITIONS"]
    cleaned_va = []
    
    for row in raw_va:
        disp = str(row.get("dispositionCode", "")).upper()
        if not any(v in disp for v in valid_dispositions):
            continue
            
        line1 = str(row.get("firstLineName", "") or "").strip()
        line2 = str(row.get("secondLineName", "") or "").strip()
        
        if re.match(r'^\d+\s+', line2):
            raw_addr, raw_name = line2, line1
        elif re.match(r'^\d+\s+', line1):
            raw_addr, raw_name = line1, line2
        else:
            raw_addr, raw_name = line1, line1
            
        house_num, street_name = normalize_street_address(raw_addr)
        
        cleaned_va.append({
            "name_norm": normalize_text(raw_name),
            "house_num": house_num,
            "street_norm": street_name,
            "disposition": row.get("dispositionCode", "Approved"),
            "county": row.get("source_county", "")
        })
    return cleaned_va

def build_master_condos():
    print("🚀 Building Master Condo Database...\n")
    organize_staging_directory()
    
    current_date_str = datetime.now().strftime("%Y-%m-%d")
    
    king_path = os.path.join(STAGING_DIR, "king_condos.json")
    sno_path = os.path.join(STAGING_DIR, "snohomish_condos.json")
    
    county_condos = []
    if os.path.exists(king_path):
        with open(king_path, 'r') as f:
            for item in json.load(f):
                item["county"] = "King"
                county_condos.append(item)
                
    if os.path.exists(sno_path):
        with open(sno_path, 'r') as f:
            for item in json.load(f):
                item["county"] = "Snohomish"
                county_condos.append(item)
                
    print(f"Loaded {len(county_condos)} total county condo complexes across King & Snohomish.")
    
    fha_records = parse_fha_records()
    va_records = parse_va_records()
    print(f"Loaded {len(fha_records)} Approved FHA records and {len(va_records)} Approved VA records.\n")
    
    master_condos = []
    fha_matches = 0
    va_matches = 0
    
    for condo in county_condos:
        c_house, c_street = normalize_street_address(condo.get("address", ""))
        c_name_norm = normalize_text(condo.get("name", ""))
        
        # 1. Check FHA Match
        fha_approved = False
        fha_exp_date = None
        for fha in fha_records:
            addr_match = (c_house and c_house == fha["house_num"] and (c_street in fha["street_norm"] or fha["street_norm"] in c_street))
            name_match = (len(c_name_norm) > 3 and (c_name_norm in fha["name_norm"] or fha["name_norm"] in c_name_norm))
            
            if addr_match or name_match:
                fha_approved = True
                fha_exp_date = fha["expiration_date"]
                fha_matches += 1
                break
                
        # 2. Check VA Match
        va_approved = False
        va_status = None
        for va in va_records:
            addr_match = (c_house and c_house == va["house_num"] and (c_street in va["street_norm"] or va["street_norm"] in c_street))
            name_match = (len(c_name_norm) > 3 and (c_name_norm in va["name_norm"] or va["name_norm"] in c_name_norm))
            
            if addr_match or name_match:
                va_approved = True
                va_status = va["disposition"]
                va_matches += 1
                break
                
        condo["fha_approved"] = fha_approved
        condo["fha_expiration_date"] = fha_exp_date
        condo["va_approved"] = va_approved
        condo["va_status"] = va_status
        condo["last_updated"] = current_date_str
        
        master_condos.append(condo)
        
    print(f"✅ Successfully cross-referenced:")
    print(f"   - FHA Approved Condos Matched: {fha_matches}")
    print(f"   - VA Approved Condos Matched: {va_matches}")
    
    with open(MASTER_OUT_PATH, 'w') as f:
        json.dump(master_condos, f, indent=2)
        
    print(f"\n🎉 MASTER FILE CREATED! Saved {len(master_condos)} normalized buildings to {MASTER_OUT_PATH}")
    
    cleanup_staging_directory()

if __name__ == "__main__":
    build_master_condos()