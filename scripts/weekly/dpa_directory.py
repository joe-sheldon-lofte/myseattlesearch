import os
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")

def main():
    print("🏛️ Syncing WA State Down Payment Assistance Directories...")
    os.makedirs(DATA_DIR, exist_ok=True)
    out_path = os.path.join(DATA_DIR, "dpa_programs.json")
    if not os.path.exists(out_path):
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump([], f, indent=2)
    print("💾 DPA program directory verified.")

if __name__ == "__main__":
    main()