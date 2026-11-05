import os
import sys
import traceback
import sentry_sdk

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
def safe_task(task_name, func, county="Regional"):
    print(f"🚀 [Monthly Master] Starting: {task_name}...")
    try:
        func()
        print(f"✅ [Monthly Master] Completed: {task_name}\n")
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"❌ [Monthly Master] Error during {task_name}: {e}")
        print(error_trace)

        if SENTRY_DSN:
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("task_name", task_name)
                scope.set_tag("cadence", "monthly")
                scope.set_tag("county", county)
                sentry_sdk.capture_exception(e)
                print(f"📡 Exception sent to Sentry for {task_name}")

        print(f"⚠️ Skipping {task_name}.\n")

def run_subscript(script_relative_path):
    path = os.path.join(BASE_DIR, "scripts", "monthly", script_relative_path)
    if os.path.exists(path):
        exit_code = os.system(f"{sys.executable} {path}")
        if exit_code != 0:
            raise RuntimeError(f"Sub-script '{script_relative_path}' failed with exit code {exit_code}")
    else:
        raise FileNotFoundError(f"Script not found at expected path: {path}")

# Task Callers
def harvest_census_demographics(): run_subscript("census_demographics.py")
def harvest_osm_amenities(): run_subscript("osm_amenities.py")
def harvest_gis_boundaries(): run_subscript("gis_boundaries.py")
def harvest_redfin_monthly(): run_subscript("redfin_monthly_stats.py")
def harvest_businesses(): run_subscript("harvest_businesses.py")
def harvest_monthly_sheets(): run_subscript("monthly_sheet_sync.py")
def harvest_parcel_deltas(): run_subscript("sync_parcel_deltas.py")
def harvest_fha_condos(): run_subscript("harvest_fha_condos.py")
def harvest_va_condos(): run_subscript("harvest_va_condos.py")
def harvest_wastewater(): run_subscript("wastewater_update.py")

# ------------------------------------------------------------------------------
# 3. MASTER MONTHLY RUNNER
# ------------------------------------------------------------------------------
def main():
    print("==================================================")
    print("     MYSEATTLESEARCH MONTHLY MASTER HARVESTER     ")
    print("==================================================\n")

    safe_task("1. City Demographics & Population (US Census ACS)", harvest_census_demographics)
    safe_task("2. Municipal Amenities (OpenStreetMap Overpass)", harvest_osm_amenities)
    safe_task("3. GIS City Boundaries (WSDOT)", harvest_gis_boundaries)
    safe_task("4. Advanced Redfin Monthly Analytics & Migration", harvest_redfin_monthly)
    safe_task("5. Google Places Local Business Spotlights", harvest_businesses)
    safe_task("6. Utility Directory Ingestion (Google Sheets to D1)", harvest_monthly_sheets)
    safe_task("7. County Parcel Roll Delta Synchronization", harvest_parcel_deltas)
    safe_task("8. FHA Condo Certification Roll (HUD ENTP to D1)", harvest_fha_condos)
    safe_task("9. VA Condo Loan Approval Registry (VA LGY to D1)", harvest_va_condos)
    safe_task("10. Live Wastewater & Septic Harvester (ArcGIS & OnlineRME)", harvest_wastewater, county="Both")

    print("🎉 Monthly master harvesting sequence complete. Database fresh!")

if __name__ == "__main__":
    main()