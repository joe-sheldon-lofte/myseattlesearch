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
        traces_sample_rate=0.0,
        environment="production"
    )
    print("🛡️ Sentry Error Monitoring Initialized.")
else:
    print("⚠️ SENTRY_DSN environment variable not found. Logging to terminal only.")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ------------------------------------------------------------------------------
# 2. ISOLATED SUBPROCESS RUNNER WITH SENTRY ERROR CAPTURE
# ------------------------------------------------------------------------------
def safe_task(task_name, func, county="Regional"):
    print(f"🚀 [Quarterly Master] Starting: {task_name}...")
    try:
        func()
        print(f"✅ [Quarterly Master] Completed: {task_name}\n")
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"❌ [Quarterly Master] Error during {task_name}: {e}")
        print(error_trace)

        if SENTRY_DSN:
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("task_name", task_name)
                scope.set_tag("cadence", "quarterly")
                scope.set_tag("county", county)
                sentry_sdk.capture_exception(e)
                print(f"📡 Exception sent to Sentry for {task_name}")

        print(f"⚠️ Skipping {task_name}. Existing dataset preserved.\n")

def run_subscript(script_relative_path):
    path = os.path.join(BASE_DIR, "scripts", "quarterly", script_relative_path)
    if os.path.exists(path):
        exit_code = os.system(f"{sys.executable} {path}")
        if exit_code != 0:
            raise RuntimeError(f"Sub-script '{script_relative_path}' failed with exit code {exit_code}")
    else:
        raise FileNotFoundError(f"Script not found at expected path: {path}")

# Task Callers (Editorial Sheets, Academic Telemetry & District Geometries)
def harvest_quarterly_sheets(): run_subscript("quarterly_sheet_sync.py")
def harvest_ospi_schools(): run_subscript("harvest_ospi_school_data.py")
def harvest_school_boundaries(): run_subscript("harvest_school_boundaries.py")

# ------------------------------------------------------------------------------
# 3. MASTER QUARTERLY RUNNER (Jan, Apr, Jul, Oct 3rd @ 2:09 AM PT)
# ------------------------------------------------------------------------------
@monitor(
    monitor_slug="quarterly-harvest-pipeline",
    monitor_config={
        "schedule": {"type": "crontab", "value": "9 2 3 1,4,7,10 *"},
        "checkin_margin": 240,
        "max_runtime": 180,
        "timezone": "America/Los_Angeles"
    }
)
def main():
    print("==================================================")
    print("     MYSEATTLESEARCH QUARTERLY MASTER HARVESTER   ")
    print("==================================================\n")

    # 1. Quarterly Editorial Overrides & Municipal Sheet Sync
    safe_task("1. Ingest Quarterly Editorial Overrides (Google Sheets to D1)", harvest_quarterly_sheets)

    # 2. Washington OSPI Academic Performance
    safe_task("2. Harvest WA OSPI School Data", harvest_ospi_schools)

    # 3. School District GIS Boundaries
    safe_task("3. Ingest School District GIS Boundaries", harvest_school_boundaries)

    print("🎉 Quarterly master harvesting sequence complete. Intelligence fresh!")

if __name__ == "__main__":
    main()