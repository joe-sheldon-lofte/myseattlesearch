import os
import sys
import traceback
import sentry_sdk

SENTRY_DSN = os.getenv("SENTRY_DSN")
if SENTRY_DSN:
    sentry_sdk.init(dsn=SENTRY_DSN, traces_sample_rate=0.0, environment="production")
    print("🛡️ Sentry Error Monitoring Initialized.")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def safe_task(task_name, func):
    print(f"🚀 [Rapid Master] Starting: {task_name}...")
    try:
        exit_code = func()
        print(f"✅ [Rapid Master] Completed: {task_name}\n")
        return exit_code
    except Exception as e:
        print(f"❌ [Rapid Master] Error during {task_name}: {e}")
        print(traceback.format_exc())
        if SENTRY_DSN:
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("task_name", task_name)
                scope.set_tag("cadence", "rapid")
                sentry_sdk.capture_exception(e)
        return 1

def run_subscript(script_name):
    path = os.path.join(BASE_DIR, "scripts", "rapid", script_name)
    if os.path.exists(path):
        return os.system(f"{sys.executable} {path}") >> 8
    else:
        raise FileNotFoundError(f"Script not found: {path}")

def harvest_power(): return run_subscript("power_outages.py")
def harvest_wildfires(): return run_subscript("wildfires.py")
def harvest_weather(): return run_subscript("weather_alerts.py")
def harvest_earthquakes(): return run_subscript("earthquakes.py")
def harvest_schools(): return run_subscript("schools.py")
def compile_alerts(): return run_subscript("compile_alerts.py")

def main():
    print("==================================================")
    print("       MYSEATTLESEARCH RAPID TELEMETRY HARVESTER  ")
    print("==================================================\n")

    safe_task("1. Real-Time Utility Power Outages", harvest_power)
    safe_task("2. Active Wildland Fire Telemetry", harvest_wildfires)
    safe_task("3. NWS Severe Weather Alerts", harvest_weather)
    safe_task("4. USGS Pacific Northwest Seismic Telemetry", harvest_earthquakes)
    safe_task("5. FlashAlert PNW School Closures & Delays", harvest_schools)
    
    # 6. Matrix Compiler returns 22 if an alert state changed, requiring an SSG rebuild
    matrix_code = safe_task("6. Master Edge Alert Matrix Compilation", compile_alerts)

    print("🎉 Rapid telemetry harvesting sequence complete.")
    sys.exit(matrix_code)

if __name__ == "__main__":
    main()