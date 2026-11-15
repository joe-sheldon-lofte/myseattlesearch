import os
import sys
import subprocess
import traceback

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None

SENTRY_DSN = os.getenv("SENTRY_DSN")
if SENTRY_DSN and sentry_sdk:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        traces_sample_rate=0.0,
        environment="production"
    )
    print("Sentry Error Monitoring Initialized.")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_subscript(script_relative_path: str) -> int:
    path = os.path.join(BASE_DIR, "scripts", "rapid", script_relative_path)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Script not found at expected path: {path}")
    result = subprocess.run([sys.executable, path], check=False)
    return result.returncode


def safe_task(task_name: str, script_name: str, allowed_codes=(0,)) -> int:
    print(f"Starting: {task_name}...")
    try:
        code = run_subscript(script_name)
        if code not in allowed_codes:
            raise RuntimeError(f"Sub-script '{script_name}' exited with code {code}")
        print(f"Completed: {task_name} (exit={code})\n")
        return code
    except Exception as exc:
        print(f"Error during {task_name}: {exc}")
        print(traceback.format_exc())
        if SENTRY_DSN and sentry_sdk:
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("task_name", task_name)
                scope.set_tag("cadence", "rapid")
                sentry_sdk.capture_exception(exc)
        print(f"Skipping {task_name}.\n")
        return 1


def main() -> None:
    print("==================================================")
    print("       MYSEATTLESEARCH RAPID TELEMETRY HARVESTER  ")
    print("==================================================\n")

    safe_task("1. Real-Time Utility Power Outages", "power_outages.py")
    safe_task("2. Active Wildland Fire Telemetry (NIFC WFIGS)", "wildfires.py")
    safe_task("3. NWS Severe Weather Alerts", "weather_alerts.py")
    safe_task("4. USGS Pacific Northwest Seismic Telemetry", "earthquakes.py")
    safe_task("5. FlashAlert PNW School Closures & Delays", "schools.py")

    # Returns 22 when alert states change to trigger deploy-site.yml immediately
    matrix_code = safe_task(
        "6. Master Edge Alert Matrix Compilation",
        "compile_alerts.py",
        allowed_codes=(0, 22)
    )

    print("Rapid telemetry harvesting sequence complete.")
    sys.exit(matrix_code if matrix_code == 22 else 0)


if __name__ == "__main__":
    main()