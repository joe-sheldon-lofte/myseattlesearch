import os
import sys
import traceback
import sentry_sdk
from sentry_sdk.crons import monitor

# ------------------------------------------------------------------------------
# 1. INITIALIZE SENTRY (Global Process Handler)
# ------------------------------------------------------------------------------
SENTRY_DSN = os.getenv("SENTRY_DSN")

if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        traces_sample_rate=0.0,  # Pure error monitoring (saves quota)
        environment="production"
    )
    print("🛡️ Sentry Error Monitoring Initialized.")
else:
    print("⚠️ SENTRY_DSN environment variable not found. Logging to terminal only.")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ------------------------------------------------------------------------------
# 2. ENHANCED SAFE_TASK WITH SENTRY ERROR CAPTURE
# ------------------------------------------------------------------------------
def safe_task(task_name, func):
    print(f"🚀 [Weekly Master] Starting: {task_name}...")
    try:
        func()
        print(f"✅ [Weekly Master] Completed: {task_name}\n")
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"❌ [Weekly Master] Error during {task_name}: {e}")
        print(error_trace)

        if SENTRY_DSN:
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("task_name", task_name)
                scope.set_tag("cadence", "weekly")
                sentry_sdk.capture_exception(e)
                print(f"📡 Exception sent to Sentry for {task_name}")

        print(f"⚠️ Skipping {task_name}.\n")

def run_subscript(script_relative_path):
    path = os.path.join(BASE_DIR, "scripts", "weekly", script_relative_path)
    if os.path.exists(path):
        exit_code = os.system(f"{sys.executable} {path}")
        if exit_code != 0:
            # Raise exception so safe_task and Sentry capture sub-script failures
            raise RuntimeError(f"Sub-script '{script_relative_path}' failed with exit status code {exit_code}")
    else:
        raise FileNotFoundError(f"Script not found at expected path: {path}")

def harvest_infosparks_stats(): run_subscript("infosparks_stats.py")
def harvest_redfin_stats(): run_subscript("redfin_stats.py")
def harvest_walk_scores(): run_subscript("walk_scores.py")
def harvest_public_safety_hazards(): run_subscript("public_safety_hazards.py")
def harvest_dpa_directory(): run_subscript("dpa_directory.py")
def harvest_yelp_businesses(): run_subscript("yelp_businesses.py")
def harvest_building_permits(): run_subscript("building_permits.py")
def harvest_sports_weekly(): run_subscript("sports_weekly.py")
def harvest_traffic_cameras(): run_subscript("traffic_cameras.py")

# ------------------------------------------------------------------------------
# 3. MASTER WEEKLY RUNNER WITH SENTRY CRON MONITORING
# ------------------------------------------------------------------------------
@monitor(
    monitor_slug="weekly-harvest-pipeline",
    monitor_config={
        "schedule": {"type": "crontab", "value": "0 8 * * 0"},
        "checkin_margin": 240,  # Allows up to 4 hours delay for GitHub queue lag
        "max_runtime": 180,     # Allows up to 3 hours runtime
        "timezone": "America/Los_Angeles"
    }
)
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