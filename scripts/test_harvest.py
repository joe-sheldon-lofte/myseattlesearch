import os
import sys
import traceback

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def run_test_subscript(script_relative_path):
    path = os.path.join(BASE_DIR, "scripts", "weekly", script_relative_path)
    print(f"🧪 [Testing] Executing: {script_relative_path}...")
    if os.path.exists(path):
        exit_code = os.system(f"{sys.executable} {path}")
        if exit_code == 0:
            print(f"✅ [Testing] Successfully completed: {script_relative_path}\n")
        else:
            print(f"❌ [Testing] {script_relative_path} failed with exit code {exit_code}\n")
    else:
        print(f"⚠️ [Testing] File not found: {path}\n")

def main():
    print("==================================================")
    print("      TARGETED HOUSING DATA HARVEST TEST RUNNER   ")
    print("==================================================\n")

    run_test_subscript("redfin_stats.py")

    print("🎉 Targeted housing harvest test suite execution complete!")

if __name__ == "__main__":
    main()