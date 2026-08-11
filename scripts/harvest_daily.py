import os
import sys
import traceback

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def safe_task(task_name, func):
    print(f"🚀 [Daily Master] Starting: {task_name}...")
    try:
        func()
        print(f"✅ [Daily Master] Completed: {task_name}\n")
    except Exception as e:
        print(f"❌ [Daily Master] Error during {task_name}: {e}")
        print(traceback.format_exc())
        print(f"⚠️ Skipping {task_name}.\n")

def run_subscript(script_relative_path):
    path = os.path.join(BASE_DIR, "scripts", "daily", script_relative_path)
    if os.path.exists(path):
        exit_code = os.system(f"{sys.executable} {path}")
        if exit_code != 0:
            print(f"⚠️ {script_relative_path} exited with status code {exit_code}")
    else:
        print(f"⚠️ Script not found at expected path: {path}")

def harvest_daily_sheet_sync(): run_subscript("daily_sheet_sync.py")
def harvest_construction_zones(): run_subscript("construction_zones.py")
def harvest_quizzes_processor(): run_subscript("quizzes_processor.py")

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