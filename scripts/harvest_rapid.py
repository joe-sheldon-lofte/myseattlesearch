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
# 2. ENHANCED SAFE_TASK WITH SENTRY ERROR CAPTURE
# ------------------------------------------------------------------------------
def safe_task(task_name, func):
    print(f"🚀 [Rapid Master] Starting: {task_name}...")
    try:
        func()
        print(f"✅ [Rapid Master] Completed: {task_name}\n")
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"❌ [Rapid Master] Error during {task_name}: {e}")
        print(error_trace)

        if SENTRY_DSN:
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("task_name", task_name)
                scope.set_tag("cadence", "rapid")
                sentry_sdk.capture_exception(e)
                print(f"📡 Exception sent to Sentry for {task_name}")

        print(f"⚠️ Skipping {task_name}.\n")

def run_subscript(script_relative_path):
    path = os.path.join(BASE_DIR, "scripts", "rapid", script_relative_path)
    if os.path.exists(path):
        exit_code = os.system(f"{sys.executable} {path}")
        if exit_code != 0:
            raise RuntimeError(f"Sub-script '{script_relative_path}' failed with exit code {exit_code}")
    else:
        raise FileNotFoundError(f"Script not found at expected path: {path}")

def harvest_power_outages(): run_subscript("power_outages.py")
def harvest_wildfires(): run_subscript("wildfires.py")
def harvest_rapid_sheets(): run_subscript("rapid_sheet_sync.py")
def harvest_earthquakes(): run_subscript("earthquakes.py")
def harvest_schools(): run_subscript("schools.py")
def compile_alerts(): run_subscript("compile_alerts.py")

# ------------------------------------------------------------------------------
# 3. MASTER RAPID RUNNER WITH SENTRY CRON MONITORING
# ------------------------------------------------------------------------------
@monitor(
    monitor_slug="rapid-harvest-pipeline",
    monitor_config={
        "schedule": {"type": "crontab", "value": "*/15 * * * *"},
        "checkin_margin": 60,
        "max_runtime": 10,
        "timezone": "America/Los_Angeles"
    }
)
def main():
    print("==================================================")
    print("       MYSEATTLESEARCH RAPID TELEMETRY HARVESTER  ")
    print("==================================================\n")

    # Ingestion phase (isolated sub-processes)
    safe_task("1. Real-Time Utility Power Outages", harvest_power_outages)
    safe_task("2. Active Wildland Fire Telemetry (NIFC WFIGS)", harvest_wildfires)
    safe_task("3. High-Frequency Market Dashboard Sync", harvest_rapid_sheets)
    safe_task("4. USGS Pacific Northwest Seismic Telemetry", harvest_earthquakes)
    safe_task("5. FlashAlert PNW School Closures & Delays", harvest_schools)

    # Aggregation phase (must execute last after all feeds write to R2 & D1)
    safe_task("6. Master Edge Alert Matrix Compilation", compile_alerts)

    print("🎉 Rapid telemetry harvesting sequence complete.")

if __name__ == "__main__":
    main()