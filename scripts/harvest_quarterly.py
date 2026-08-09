import os
import sys
import traceback

# ==============================================================================
# PIPELINE FEATURE TOGGLES (FLIP SWITCHES)
# Set to True to execute, or False to bypass during isolated testing/debugging.
# ==============================================================================
RUN_CONDO_HARVEST = False
RUN_SUBDIVISION_HARVEST = True

# Ensure scripts directory is in Python path for clean module imports
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

def safe_task(task_name, func):
    print(f"🚀 [Quarterly Pipeline] Starting: {task_name}...")
    try:
        func()
        print(f"✅ [Quarterly Pipeline] Completed: {task_name}\n")
    except Exception as e:
        print(f"❌ [Quarterly Pipeline] Error during {task_name}: {e}")
        print(traceback.format_exc())
        print(f"⚠️ Skipping {task_name}. Existing dataset preserved.\n")

def main():
    print("==================================================")
    print("     MYSEATTLESEARCH QUARTERLY MASTER HARVESTER   ")
    print("==================================================\n")

    # 1. Condo Complex Harvester Switch
    if RUN_CONDO_HARVEST:
        try:
            from harvest_condos import harvest_condo_buildings
            safe_task("1. Master Condo Complex Directory", harvest_condo_buildings)
        except ImportError as e:
            print(f"❌ Could not import harvest_condos.py: {e}\n")
    else:
        print("⏸️ [Quarterly Pipeline] Bypassing Condo Harvest (RUN_CONDO_HARVEST = False)\n")

    # 2. New Subdivision Harvester Switch
    if RUN_SUBDIVISION_HARVEST:
        try:
            from harvest_subdivisions import harvest_new_subdivisions
            safe_task("2. New Construction Subdivisions", harvest_new_subdivisions)
        except ImportError as e:
            print(f"❌ Could not import harvest_subdivisions.py: {e}\n")
    else:
        print("⏸️ [Quarterly Pipeline] Bypassing Subdivision Harvest (RUN_SUBDIVISION_HARVEST = False)\n")

    print("🎉 Quarterly harvester execution completed successfully!")

if __name__ == "__main__":
    main()