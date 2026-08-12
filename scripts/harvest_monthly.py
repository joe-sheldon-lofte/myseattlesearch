import os
import sys
import traceback

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def safe_task(task_name, func):
    print(f"🚀 [Monthly Master] Starting: {task_name}...")
    try:
        func()
        print(f"✅ [Monthly Master] Completed: {task_name}\n")
    except Exception as e:
        print(f"❌ [Monthly Master] Error during {task_name}: {e}")
        print(traceback.format_exc())
        print(f"⚠️ Skipping {task_name}.\n")

def run_subscript(script_relative_path):
    path = os.path.join(BASE_DIR, "scripts", "monthly", script_relative_path)
    if os.path.exists(path):
        exit_code = os.system(f"{sys.executable} {path}")
        if exit_code != 0:
            print(f"⚠️ {script_relative_path} exited with status code {exit_code}")
    else:
        print(f"⚠️ Script not found at expected path: {path}")

def harvest_census_demographics(): run_subscript("census_demographics.py")
def harvest_osm_amenities(): run_subscript("osm_amenities.py")
def harvest_gis_boundaries(): run_subscript("gis_boundaries.py")
def harvest_redfin_monthly(): run_subscript("redfin_monthly_stats.py")

def main():
    print("==================================================")
    print("     MYSEATTLESEARCH MONTHLY MASTER HARVESTER     ")
    print("==================================================\n")

    safe_task("1. City Demographics & Population (US Census ACS)", harvest_census_demographics)
    safe_task("2. Municipal Amenities (OpenStreetMap Overpass)", harvest_osm_amenities)
    safe_task("3. GIS City Boundaries (WSDOT)", harvest_gis_boundaries)
    safe_task("4. Advanced Redfin Monthly Analytics & Migration", harvest_redfin_monthly)

    print("🎉 Monthly master harvesting sequence complete. Data fresh!")

if __name__ == "__main__":
    main()