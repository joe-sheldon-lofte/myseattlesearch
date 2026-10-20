# File: scripts/harvest_quarterly.py
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
        traces_sample_rate=0.0,  # 0.0 keeps performance tracing off to save quota
        environment="production"
    )
    print("🛡️ Sentry Error Monitoring Initialized.")
else:
    print("⚠️ SENTRY_DSN environment variable not found. Errors will log to terminal only.")

# --- Pipeline Feature Switches ---
RUN_KING_SUBDIVISIONS = True
RUN_SNOHOMISH_SUBDIVISIONS = True
RUN_BUILD_MASTER_SUBDIVISIONS = True

RUN_KING_CONDOS_HARVEST = True
RUN_KING_CONDOS_TRANSFORM = True
RUN_SNOHOMISH_CONDOS_HARVEST = True
RUN_SNOHOMISH_CONDOS_TRANSFORM = True

RUN_FHA_CONDOS_HARVEST = True
RUN_VA_CONDOS_HARVEST = True
RUN_BUILD_MASTER_CONDOS = True

RUN_OSPI_SCHOOL_DATA = True
RUN_SCHOOL_BOUNDARIES = True

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

# ------------------------------------------------------------------------------
# 2. ENHANCED SAFE_TASK WITH SENTRY ERROR CAPTURE
# ------------------------------------------------------------------------------
def safe_task(task_name, func, county="Regional"):
    print(f"🚀 [Quarterly Pipeline] Starting: {task_name}...")
    try:
        func()
        print(f"✅ [Quarterly Pipeline] Completed: {task_name}\n")
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"❌ [Quarterly Pipeline] Error during {task_name}: {e}")
        print(error_trace)

        # Report to Sentry with contextual metadata
        if SENTRY_DSN:
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("task_name", task_name)
                scope.set_tag("county", county)
                sentry_sdk.capture_exception(e)
                print(f"📡 Exception sent to Sentry for {task_name}")

        print(f"⚠️ Skipping {task_name}. Existing dataset preserved.\n")

# ------------------------------------------------------------------------------
# 3. MASTER RUNNER WITH SENTRY CRON MONITORING
# ------------------------------------------------------------------------------
@monitor(monitor_slug="quarterly-harvest-pipeline")
def main():
    print("==================================================")
    print("     MYSEATTLESEARCH QUARTERLY MASTER HARVESTER   ")
    print("==================================================")

    # Startup Switchboard Audit
    switches = [
        ("1. King Subdivisions", RUN_KING_SUBDIVISIONS),
        ("2. Snohomish Subdivisions", RUN_SNOHOMISH_SUBDIVISIONS),
        ("3. Compile Master Subdivisions", RUN_BUILD_MASTER_SUBDIVISIONS),
        ("4. King Condos Harvest", RUN_KING_CONDOS_HARVEST),
        ("5. King Condos Transform", RUN_KING_CONDOS_TRANSFORM),
        ("6. Snohomish Condos Harvest", RUN_SNOHOMISH_CONDOS_HARVEST),
        ("7. Snohomish Condos Transform", RUN_SNOHOMISH_CONDOS_TRANSFORM),
        ("8. FHA Approved Condos", RUN_FHA_CONDOS_HARVEST),
        ("9. VA Approved Condos", RUN_VA_CONDOS_HARVEST),
        ("10. Compile Master Condos", RUN_BUILD_MASTER_CONDOS),
        ("11. WA OSPI School Data", RUN_OSPI_SCHOOL_DATA),
        ("12. School District GIS Boundaries", RUN_SCHOOL_BOUNDARIES)
    ]

    print("\n⚙️ Pipeline Switchboard Audit:")
    for task_label, is_active in switches:
        status_tag = "🟢 [ACTIVE] ➔ Queued" if is_active else "⚪ [SKIP]"
        print(f"   • {task_label.ljust(35)}: {status_tag}")
    print("==================================================\n")

    # 1. King Subdivisions
    if RUN_KING_SUBDIVISIONS:
        try:
            from quarterly.harvest_king_subdivisions import harvest_king_subdivisions
            safe_task("1. Harvest King County Subdivisions", harvest_king_subdivisions, county="King")
        except Exception as e:
            sentry_sdk.capture_exception(e)

    # 2. Snohomish Subdivisions
    if RUN_SNOHOMISH_SUBDIVISIONS:
        try:
            from quarterly.harvest_snohomish_subdivisions import harvest_snohomish_subdivisions
            safe_task("2. Harvest Snohomish County Subdivisions", harvest_snohomish_subdivisions, county="Snohomish")
        except Exception as e:
            sentry_sdk.capture_exception(e)

    # 3. Compile Subdivisions Master
    if RUN_BUILD_MASTER_SUBDIVISIONS:
        try:
            from quarterly.build_master_subdivisions import build_master_subdivisions
            safe_task("3. Compile Master Subdivisions", build_master_subdivisions)
        except Exception as e:
            sentry_sdk.capture_exception(e)

    # 4. King Condos Harvest
    if RUN_KING_CONDOS_HARVEST:
        try:
            from quarterly.harvest_king_condos import harvest_king_condos
            safe_task("4. Harvest King County Condos", harvest_king_condos, county="King")
        except Exception as e:
            sentry_sdk.capture_exception(e)

    # 5. King Condos Transform
    if RUN_KING_CONDOS_TRANSFORM:
        try:
            from quarterly.transform_king_condos import transform_king_condos
            safe_task("5. Transform King County Condos", transform_king_condos, county="King")
        except Exception as e:
            sentry_sdk.capture_exception(e)

    # 6. Snohomish Condos Harvest
    if RUN_SNOHOMISH_CONDOS_HARVEST:
        try:
            from quarterly.harvest_snohomish_condos import harvest_snohomish_condos
            safe_task("6. Harvest Snohomish County Condos", harvest_snohomish_condos, county="Snohomish")
        except Exception as e:
            sentry_sdk.capture_exception(e)

    # 7. Snohomish Condos Transform
    if RUN_SNOHOMISH_CONDOS_TRANSFORM:
        try:
            from quarterly.transform_snohomish_condos import transform_snohomish_condos
            safe_task("7. Transform Snohomish County Condos", transform_snohomish_condos, county="Snohomish")
        except Exception as e:
            sentry_sdk.capture_exception(e)

    # 8. FHA Approvals
    if RUN_FHA_CONDOS_HARVEST:
        try:
            from quarterly.harvest_fha_condos import harvest_fha_condos
            safe_task("8. Harvest FHA Approved Condos", harvest_fha_condos)
        except Exception as e:
            sentry_sdk.capture_exception(e)

    # 9. VA Approvals
    if RUN_VA_CONDOS_HARVEST:
        try:
            from quarterly.harvest_va_condos import harvest_va_condos
            safe_task("9. Harvest VA Approved Condos", harvest_va_condos)
        except Exception as e:
            sentry_sdk.capture_exception(e)

    # 10. Compile Condos Master
    if RUN_BUILD_MASTER_CONDOS:
        try:
            from quarterly.build_master_condos import build_master_condos
            safe_task("10. Compile Master Condos Database", build_master_condos)
        except Exception as e:
            sentry_sdk.capture_exception(e)

    # 11. OSPI School Academic Metrics
    if RUN_OSPI_SCHOOL_DATA:
        try:
            from quarterly.harvest_ospi_school_data import main as harvest_ospi_school_data
            safe_task("11. Harvest WA OSPI School Data", harvest_ospi_school_data)
        except Exception as e:
            sentry_sdk.capture_exception(e)

    # 12. School District GIS Boundaries
    if RUN_SCHOOL_BOUNDARIES:
        try:
            from quarterly.harvest_school_boundaries import main as harvest_school_boundaries
            safe_task("12. Ingest School District GIS Boundaries", harvest_school_boundaries)
        except Exception as e:
            sentry_sdk.capture_exception(e)

    print("🎉 Quarterly harvester execution completed successfully!")

if __name__ == "__main__":
    main()