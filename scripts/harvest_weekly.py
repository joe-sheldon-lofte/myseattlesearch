import os
import sys
import traceback

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def safe_task(task_name, func):
    print(f"🚀 [Weekly Master] Starting: {task_name}...")
    try:
        func()
        print(f"✅ [Weekly Master] Completed: {task_name}\n")
    except Exception as e:
        print(f"❌ [Weekly Master] Error during {task_name}: {e}")
        print(traceback.format_exc())
        print(f"⚠️ Skipping {task_name}.\n")

def run_subscript(script_relative_path):
    path = os.path.join(BASE_DIR, "scripts", "weekly", script_relative_path)
    if os.path.exists(path):
        exit_code = os.system(f"{sys.executable} {path}")
        if exit_code != 0:
            print(f"⚠️ {script_relative_path} exited with status code {exit_code}")
    else:
        print(f"⚠️ Script not found at expected path: {path}")

def harvest_infosparks_stats(): run_subscript("infosparks_stats.py")
def harvest_redfin_stats(): run_subscript("redfin_stats.py")
def harvest_walk_scores(): run_subscript("walk_scores.py")
def harvest_public_safety_hazards(): run_subscript("public_safety_hazards.py")
def harvest_dpa_directory(): run_subscript("dpa_directory.py")
def harvest_yelp_businesses(): run_subscript("yelp_businesses.py")
def harvest_building_permits(): run_subscript("building_permits.py")
def harvest_sports_weekly(): run_subscript("sports_weekly.py")
def harvest_traffic_cameras(): run_subscript("traffic_cameras.py")

def main():
    print("==================================================")
    print("     MYSEATTLESEARCH WEEKLY MASTER HARVESTER      ")
    print("==================================================\n")

    safe_task("1. InfoSparks MLS Macro Stats", harvest_infosparks_stats)
    safe_task("2. Redfin City Market Tracker", harvest_redfin_stats)
    safe_task("3. WalkScore Ratings", harvest_walk_scores)
    safe_task("4. Public Safety, Emergency & NOAA Hazards", harvest_public_safety_hazards)
    safe_task("5. Down Payment Assistance Programs", harvest_dpa_directory)
    safe_task("6. Live Yelp Fusion Business Spotlights", harvest_yelp_businesses)
    safe_task("7. Municipal Building Permits", harvest_building_permits)
    safe_task("8. Sports Weekly Metadata & WebP Logos", harvest_sports_weekly)
    safe_task("9. Multi-Agency Traffic Cameras Mapping", harvest_traffic_cameras)

    print("🎉 Weekly master harvesting sequence complete. Data fresh!")

if __name__ == "__main__":
    main()