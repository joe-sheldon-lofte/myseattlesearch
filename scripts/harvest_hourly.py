import os
import sys
import json
import traceback
import datetime
import boto3
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
    print(f"🚀 [Hourly Master] Starting: {task_name}...")
    try:
        func()
        print(f"✅ [Hourly Master] Completed: {task_name}\n")
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"❌ [Hourly Master] Error during {task_name}: {e}")
        print(error_trace)

        if SENTRY_DSN:
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("task_name", task_name)
                scope.set_tag("cadence", "hourly")
                sentry_sdk.capture_exception(e)
                print(f"📡 Exception sent to Sentry for {task_name}")

        print(f"⚠️ Skipping {task_name}.\n")

def run_subscript(script_relative_path):
    primary_path = os.path.join(BASE_DIR, "scripts", "hourly", script_relative_path)
    fallback_path = os.path.join(BASE_DIR, "scripts", script_relative_path)
    
    target_path = primary_path if os.path.exists(primary_path) else fallback_path

    if os.path.exists(target_path):
        exit_code = os.system(f"{sys.executable} {target_path}")
        if exit_code != 0:
            raise RuntimeError(f"Sub-script '{script_relative_path}' failed with exit status code {exit_code}")
    else:
        raise FileNotFoundError(f"Script not found at expected path: {primary_path}")

# Sub-script execution wrappers
def harvest_weather_hourly(): run_subscript("harvest_weather_hourly.py")
def harvest_transit_intercity(): run_subscript("transit_intercity.py")
def harvest_sports_hourly(): run_subscript("sports_hourly.py")
def harvest_sheets_master_sync(): run_subscript("sheets_master_sync.py")
def harvest_cms_generator(): run_subscript("cms_generator.py")
def harvest_news_rss_wire(): run_subscript("news_rss_wire.py")

# Task 7: Cloudflare R2 Storage Accounting
def run_r2_accounting():
    print("📊 Generating Cloudflare R2 Storage Accounting Metrics...")
    out_dir = "_data"
    os.makedirs(out_dir, exist_ok=True)
    out_f = os.path.join(out_dir, "r2_storage.json")
    r2_payload = {"usedGB": "0.00", "usedBytes": 0, "lastChecked": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    
    r2_access_key = os.environ.get("R2_ACCESS_KEY_ID")
    r2_secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
    r2_endpoint = os.environ.get("R2_ENDPOINT_URL")
    r2_bucket = os.environ.get("R2_BUCKET_NAME")

    if all([r2_access_key, r2_secret_key, r2_endpoint, r2_bucket]):
        try:
            s3_client = boto3.client(
                "s3", endpoint_url=r2_endpoint,
                aws_access_key_id=r2_access_key, aws_secret_access_key=r2_secret_key,
                region_name="auto"
            )
            total_bytes = 0
            paginator = s3_client.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=r2_bucket):
                if 'Contents' in page:
                    for obj in page['Contents']: total_bytes += obj.get('Size', 0)
            r2_payload["usedGB"] = f"{(total_bytes / (1024 ** 3)):.2f}"
            r2_payload["usedBytes"] = total_bytes
        except Exception as e:
            print(f"   ⚠️ R2 Accounting notice: {e}")

    with open(out_f, "w", encoding="utf-8") as f:
        json.dump(r2_payload, f, indent=2)
    print("   ✅ R2 storage metrics saved to _data/r2_storage.json")

# ------------------------------------------------------------------------------
# 3. MASTER HOURLY RUNNER WITH SENTRY CRON MONITORING
# ------------------------------------------------------------------------------
@monitor(
    monitor_slug="hourly-harvest-pipeline",
    monitor_config={
        "schedule": {"type": "crontab", "value": "0 * * * *"},
        "checkin_margin": 180,  # Allows up to 3 hours delay for GitHub queue lag
        "max_runtime": 120,     # Allows up to 2 hours runtime
        "timezone": "America/Los_Angeles"
    }
)
def main():
    print("==================================================")
    print("     MYSEATTLESEARCH HOURLY MASTER HARVESTER      ")
    print("==================================================\n")

    safe_task("1. Weather, Tides, AQI & River Gauges", harvest_weather_hourly)
    safe_task("2. Transit Radar & Intercity Delays", harvest_transit_intercity)
    safe_task("3. Hourly Live Sports Scoreboard", harvest_sports_hourly)
    safe_task("4. Sheets Master Sync & Workbook Downloads", harvest_sheets_master_sync)
    safe_task("5. Headless CMS & Social Auto-Publisher", harvest_cms_generator)
    safe_task("6. Local RSS Real Estate News Wire", harvest_news_rss_wire)
    safe_task("7. Cloudflare R2 Storage Accounting", run_r2_accounting)

    print("🎉 Hourly master harvesting sequence complete. Site data fresh!")

if __name__ == "__main__":
    main()
