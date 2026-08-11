# File: scripts/harvest_quarterly.py

import os
import sys
import traceback

# ==============================================================================
# PIPELINE FEATURE TOGGLES (FLIP SWITCHES)
# Set to True to execute, or False to bypass during isolated testing/debugging.
# ==============================================================================
RUN_KING_SUBDIVISIONS = True
RUN_SNOHOMISH_SUBDIVISIONS = True
RUN_KING_CONDOS = False
RUN_SNOHOMISH_CONDOS = False
RUN_OSPI_SCHOOL_DATA = True
RUN_SCHOOL_BOUNDARIES = True

# Ensure scripts and quarterly subfolder are in Python path for clean module imports
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUARTERLY_SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts", "quarterly")

if QUARTERLY_SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, QUARTERLY_SCRIPTS_DIR)

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

    # 1. King County Subdivisions
    if RUN_KING_SUBDIVISIONS:
        try:
            from harvest_king_subdivisions import harvest_king_subdivisions
            safe_task("1. King County New Construction Subdivisions", harvest_king_subdivisions)
        except ImportError as e:
            print(f"❌ Could not import harvest_king_subdivisions.py: {e}\n")
    else:
        print("⏸️ [Quarterly Pipeline] Bypassing King Subdivisions (RUN_KING_SUBDIVISIONS = False)\n")

    # 2. Snohomish County Subdivisions
    if RUN_SNOHOMISH_SUBDIVISIONS:
        try:
            from harvest_snohomish_subdivisions import harvest_snohomish_subdivisions
            safe_task("2. Snohomish County New Construction Subdivisions", harvest_snohomish_subdivisions)
        except ImportError as e:
            print(f"❌ Could not import harvest_snohomish_subdivisions.py: {e}\n")
    else:
        print("⏸️ [Quarterly Pipeline] Bypassing Snohomish Subdivisions (RUN_SNOHOMISH_SUBDIVISIONS = False)\n")

    # 3. King County Condos
    if RUN_KING_CONDOS:
        try:
            from harvest_king_condos import harvest_king_condos
            safe_task("3. King County Condo Complexes", harvest_king_condos)
        except ImportError as e:
            print(f"❌ Could not import harvest_king_condos.py: {e}\n")
    else:
        print("⏸️ [Quarterly Pipeline] Bypassing King Condos (RUN_KING_CONDOS = False)\n")

    # 4. Snohomish County Condos
    if RUN_SNOHOMISH_CONDOS:
        try:
            from harvest_snohomish_condos import harvest_snohomish_condos
            safe_task("4. Snohomish County Condo Complexes", harvest_snohomish_condos)
        except ImportError as e:
            print(f"❌ Could not import harvest_snohomish_condos.py: {e}\n")
    else:
        print("⏸️ [Quarterly Pipeline] Bypassing Snohomish Condos (RUN_SNOHOMISH_CONDOS = False)\n")

    # 5. OSPI Master School Data Harvester
    if RUN_OSPI_SCHOOL_DATA:
        try:
            from harvest_ospi_school_data import main as harvest_ospi_main
            safe_task("5. OSPI Public School Assessment Data & Ratings", harvest_ospi_main)
        except ImportError as e:
            print(f"❌ Could not import harvest_ospi_school_data.py: {e}\n")
    else:
        print("⏸️ [Quarterly Pipeline] Bypassing OSPI School Data (RUN_OSPI_SCHOOL_DATA = False)\n")

    # 6. School Boundaries Harvester
    if RUN_SCHOOL_BOUNDARIES:
        try:
            from harvest_school_boundaries import main as harvest_boundaries_main
            safe_task("6. School Catchments & District Spatial Boundaries", harvest_boundaries_main)
        except ImportError as e:
            print(f"❌ Could not import harvest_school_boundaries.py: {e}\n")
    else:
        print("⏸️ [Quarterly Pipeline] Bypassing School Boundaries (RUN_SCHOOL_BOUNDARIES = False)\n")

    print("🎉 Quarterly harvester execution completed successfully!")

if __name__ == "__main__":
    main()