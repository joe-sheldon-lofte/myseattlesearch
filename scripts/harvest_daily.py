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
    print(f"🚀 [Daily Master] Starting: {task_name}...")
    try:
        func()
        print(f"✅ [Daily Master] Completed: {task_name}\n")
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"❌ [Daily Master] Error during {task_name}: {e}")
        print(error_trace)

        if SENTRY_DSN:
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("task_name", task_name)
                scope.set_tag("cadence", "daily")
                sentry_sdk.capture_exception(e)
                print(f"📡 Exception sent to Sentry for {task_name}")

        print(f"⚠️ Skipping {task_name}.\n")

def run_subscript(script_relative_path):
    path = os.path.join(BASE_DIR, "scripts", "daily", script_relative_path)
    if os.path.exists(path):
        exit_code = os.system(f"{sys.executable} {path}")
        if exit_code != 0:
            # Raise exception so safe_task and Sentry capture sub-script failures
            raise RuntimeError(f"Sub-script '{script_relative_path}' failed with exit status code {exit_code}")
    else:
        raise FileNotFoundError(f"Script not found at expected path: {path}")

def harvest_daily_sheet_sync(): run_subscript("daily_sheet_sync.py")
def harvest_construction_zones(): run_subscript("construction_zones.py")
def harvest_quizzes_processor(): run_subscript("quizzes_processor.py")

# ------------------------------------------------------------------------------
# 3. MASTER DAILY RUNNER WITH SENTRY CRON MONITORING
# ------------------------------------------------------------------------------
@monitor(
    monitor_slug="daily-harvest-pipeline",
    monitor_config={
        "schedule": {"type": "crontab", "value": "0 6 * * *"},
        "checkin_margin": 180,  # Allows up to 3 hours delay for GitHub queue lag
        "max_runtime": 120,     # Allows up to 2 hours runtime
        "timezone": "America/Los_Angeles"
    }
)
def main():
    print("==================================================")
    print("       MYSEATTLESEARCH DAILY MASTER HARVESTER     ")
    print("==================================================\n")

    safe_task("1. Daily Sheets Sync (CityData, Stats, TransitData)", harvest_daily_sheet_sync)
    safe_task("2. WSDOT Active Construction & Work Zones", harvest_construction_zones)
    safe_task("3. Daily Polymorphic Quizzes Processor", harvest_quizzes_processor)

    print("🎉 Daily master harvesting sequence complete. Data fresh!")

if __name__ == "__main__":
    main()