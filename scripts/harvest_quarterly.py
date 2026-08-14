import os
import sys
import traceback

# ==============================================================================
# PIPELINE FEATURE TOGGLES (FLIP SWITCHES)
# Set to True to execute, or False to bypass during isolated testing/debugging.
# ==============================================================================
# --- Subdivisions & Construction ---
RUN_KING_SUBDIVISIONS = False
RUN_SNOHOMISH_SUBDIVISIONS = False

# --- Condo Harvesters & Transformers ---
RUN_KING_CONDOS_HARVEST = True
RUN_KING_CONDOS_TRANSFORM = True

RUN_SNOHOMISH_CONDOS_HARVEST = True
RUN_SNOHOMISH_CONDOS_TRANSFORM = True

# --- Federal Approval Harvesters ---
RUN_FHA_CONDOS_HARVEST = True
RUN_VA_CONDOS_HARVEST = True

# --- Master Condo Compiler ---
RUN_BUILD_MASTER_CONDOS = True

# --- School & Boundary Data ---
RUN_OSPI_SCHOOL_DATA = False
RUN_SCHOOL_BOUNDARIES = False

# Add the scripts directory to the path so it can resolve the 'quarterly' folder module
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
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

    # 1. King County Subdivisions
    if RUN_KING_SUBDIVISIONS:
        try:
            from quarterly.harvest_king_subdivisions import harvest_king_subdivisions
            safe_task("1. King County New Construction Subdivisions", harvest_king_subdivisions)
        except ImportError as e:
            print(f"ℹ️ Optional module harvest_king_subdivisions.py skipped: {e}\n")

    # 2. Snohomish County Subdivisions
    if RUN_SNOHOMISH_SUBDIVISIONS:
        try:
            from quarterly.harvest_snohomish_subdivisions import harvest_snohomish_subdivisions
            safe_task("2. Snohomish County New Construction Subdivisions", harvest_snohomish_subdivisions)
        except ImportError as e:
            print(f"ℹ️ Optional module harvest_snohomish_subdivisions.py skipped: {e}\n")

    # 3. King County Condos (Harvest)
    if RUN_KING_CONDOS_HARVEST:
        try:
            from quarterly.harvest_king_condos import harvest_king_condos
            safe_task("3. Harvest King County Condos (Raw)", harvest_king_condos)
        except ImportError as e:
            print(f"❌ Could not import harvest_king_condos.py: {e}\n")
    else:
        print("⏸️ Bypassing King County Condo Harvester\n")

    # 4. King County Condos (Transform)
    if RUN_KING_CONDOS_TRANSFORM:
        try:
            from quarterly.transform_king_condos import transform_king_condos
            safe_task("4. Transform & Geocode King County Condos", transform_king_condos)
        except ImportError as e:
            print(f"❌ Could not import transform_king_condos.py: {e}\n")
    else:
        print("⏸️ Bypassing King County Condo Transformer\n")

    # 5. Snohomish County Condos (Harvest)
    if RUN_SNOHOMISH_CONDOS_HARVEST:
        try:
            from quarterly.harvest_snohomish_condos import harvest_snohomish_condos
            safe_task("5. Harvest Snohomish County Condos (Raw)", harvest_snohomish_condos)
        except ImportError as e:
            print(f"❌ Could not import harvest_snohomish_condos.py: {e}\n")
    else:
        print("⏸️ Bypassing Snohomish County Condo Harvester\n")

    # 6. Snohomish County Condos (Transform)
    if RUN_SNOHOMISH_CONDOS_TRANSFORM:
        try:
            from quarterly.transform_snohomish_condos import transform_snohomish_condos
            safe_task("6. Transform & Map-Match Snohomish County Condos", transform_snohomish_condos)
        except ImportError as e:
            print(f"❌ Could not import transform_snohomish_condos.py: {e}\n")
    else:
        print("⏸️ Bypassing Snohomish County Condo Transformer\n")

    # 7. FHA Condo Approvals Harvester
    if RUN_FHA_CONDOS_HARVEST:
        try:
            from quarterly.harvest_fha_condos import harvest_fha_condos
            safe_task("7. Harvest FHA Approved Condos", harvest_fha_condos)
        except ImportError as e:
            print(f"❌ Could not import harvest_fha_condos.py: {e}\n")
    else:
        print("⏸️ Bypassing FHA Condo Harvester\n")

    # 8. VA Condo Approvals Harvester
    if RUN_VA_CONDOS_HARVEST:
        try:
            from quarterly.harvest_va_condos import harvest_va_condos
            safe_task("8. Harvest VA Approved Condos", harvest_va_condos)
        except ImportError as e:
            print(f"❌ Could not import harvest_va_condos.py: {e}\n")
    else:
        print("⏸️ Bypassing VA Condo Harvester\n")

    # 9. Master Condo Cross-Referencer & Compiler
    if RUN_BUILD_MASTER_CONDOS:
        try:
            from quarterly.build_master_condos import build_master_condos
            safe_task("9. Compile Master Condo Database (all_condos.json)", build_master_condos)
        except ImportError as e:
            print(f"❌ Could not import build_master_condos.py: {e}\n")
    else:
        print("⏸️ Bypassing Master Condo Compiler\n")

    # 10. OSPI Master School Data Harvester
    if RUN_OSPI_SCHOOL_DATA:
        try:
            from quarterly.harvest_ospi_school_data import main as harvest_ospi_main
            safe_task("10. OSPI Public School Assessment Data & Ratings", harvest_ospi_main)
        except ImportError as e:
            print(f"❌ Could not import harvest_ospi_school_data.py: {e}\n")
    else:
        print("⏸️ Bypassing OSPI School Data\n")

    # 11. School Boundaries Harvester
    if RUN_SCHOOL_BOUNDARIES:
        try:
            from quarterly.harvest_school_boundaries import main as harvest_boundaries_main
            safe_task("11. School Catchments & District Spatial Boundaries", harvest_boundaries_main)
        except ImportError as e:
            print(f"❌ Could not import harvest_school_boundaries.py: {e}\n")
    else:
        print("⏸️ Bypassing School Boundaries\n")

    print("🎉 Quarterly harvester execution completed successfully!")

if __name__ == "__main__":
    main()