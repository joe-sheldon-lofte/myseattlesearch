import os
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))
DATA_DIR = os.path.join(BASE_DIR, "data")
STAGING_DIR = os.path.join(DATA_DIR, "staging")
MASTER_OUT_PATH = os.path.join(DATA_DIR, "all_subdivisions.json")

def build_master_subdivisions():
    print("🚀 Building Master Subdivisions Database...")
    
    king_path = os.path.join(STAGING_DIR, "king_subdivisions.json")
    sno_path = os.path.join(STAGING_DIR, "snohomish_subdivisions.json")
    
    all_subdivisions = []
    
    if os.path.exists(king_path):
        with open(king_path, "r", encoding="utf-8") as f:
            king_data = json.load(f)
            all_subdivisions.extend(king_data)
            print(f"   Loaded {len(king_data)} King County subdivisions.")
            
    if os.path.exists(sno_path):
        with open(sno_path, "r", encoding="utf-8") as f:
            sno_data = json.load(f)
            all_subdivisions.extend(sno_data)
            print(f"   Loaded {len(sno_data)} Snohomish County subdivisions.")
            
    with open(MASTER_OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(all_subdivisions, f, indent=2, ensure_ascii=False)
        
    print(f"🎉 MASTER FILE CREATED! Saved {len(all_subdivisions)} total subdivisions to {MASTER_OUT_PATH}")
    
    # Cleanup staging subdivision files
    for p in [king_path, sno_path]:
        if os.path.exists(p):
            os.remove(p)
            print(f"🧹 Cleaned up staging file: {os.path.basename(p)}")

if __name__ == "__main__":
    build_master_subdivisions()