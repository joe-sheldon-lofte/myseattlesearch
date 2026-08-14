import os
import sys
import traceback
import sentry_sdk

# ------------------------------------------------------------------------------
# 1. INITIALIZE SENTRY (Testing Environment)
# ------------------------------------------------------------------------------
SENTRY_DSN = os.getenv("SENTRY_DSN")

if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        traces_sample_rate=0.0,  # Pure error monitoring
        environment="testing"
    )
    print("🛡️ Sentry Error Monitoring Initialized (Testing Environment).")
else:
    print("⚠️ SENTRY_DSN environment variable not found. Logging to terminal only.")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ------------------------------------------------------------------------------
# 2. TEST TASK WRAPPER WITH SENTRY ERROR CAPTURE
# ------------------------------------------------------------------------------
def run_test_task(task_name, func):
    """Wraps test function execution and sends errors to Sentry if triggered."""
    print(f"🧪 [Test Harness] Executing: {task_name}...")
    try:
        func()
        print(f"✅ [Test Harness] Successfully completed: {task_name}\n")
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"❌ [Test Harness] Error during {task_name}: {e}")
        print(error_trace)

        if SENTRY_DSN:
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("task_name", task_name)
                scope.set_tag("cadence", "test")
                sentry_sdk.capture_exception(e)
                print(f"📡 Exception sent to Sentry for {task_name}")

        print(f"⚠️ Test task '{task_name}' failed.\n")

def run_test_subscript(script_relative_path):
    """Helper function to run any specific sub-script during ad-hoc testing."""
    path = os.path.join(BASE_DIR, "scripts", script_relative_path)
    if os.path.exists(path):
        exit_code = os.system(f"{sys.executable} {path}")
        if exit_code != 0:
            raise RuntimeError(f"Test sub-script '{script_relative_path}' failed with exit code {exit_code}")
    else:
        raise FileNotFoundError(f"Test script not found at expected path: {path}")

# ------------------------------------------------------------------------------
# 3. CLEAN TEST HARNESS RUNNER
# ------------------------------------------------------------------------------
def main():
    print("==================================================")
    print("      MYSEATTLESEARCH TEST HARVEST RUNNER         ")
    print("==================================================\n")

    # --------------------------------------------------------------------------
    # FUTURE TEST SCRIPTS CAN BE PLACED HERE:
    # --------------------------------------------------------------------------
    # Example 1 (Custom Inline Test Function):
    # def my_experimental_feature():
    #     # Code here...
    #     pass
    # run_test_task("Experimental Feature Test", my_experimental_feature)
    #
    # Example 2 (Run a Sub-Script directly):
    # run_test_task("Targeted Redfin Test", lambda: run_test_subscript("weekly/redfin_stats.py"))
    # --------------------------------------------------------------------------

    print("ℹ️ No active test tasks queued. Test harness initialized cleanly.")
    print("🎉 Test suite run complete!")

if __name__ == "__main__":
    main()