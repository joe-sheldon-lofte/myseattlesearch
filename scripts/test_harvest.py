import json
import os
import sys
from datetime import datetime, timezone

def get_google_sheets_service():
    """Initializes Google Sheets API client using credentials.json if available."""
    creds_path = "credentials.json"
    if not os.path.exists(creds_path):
        print(f"[WARN] {creds_path} not found. Running in offline test mode.")
        return None
    
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
        creds = service_account.Credentials.from_service_account_file(
            creds_path, scopes=scopes
        )
        service = build("sheets", "v4", credentials=creds)
        print("[SUCCESS] Google Sheets API service initialized.")
        return service
    except Exception as e:
        print(f"[ERROR] Failed to initialize Google Sheets service: {e}")
        return None

def verify_environment_secrets():
    """Audits available secrets without printing sensitive values."""
    secrets_to_check = [
        "CITY_DATA_SHEET_ID",
        "WEBSITE_DATA_SHEET_ID",
        "COMMAND_CENTER_SHEET_ID",
        "CMS_SHEET_ID",
        "QUIZZES_SHEET_ID",
        "GA_GOOGLE_CREDENTIALS",
        "WALK_SCORE_API_KEY",
        "FBI_API_KEY",
        "R2_ACCESS_KEY_ID"
    ]
    
    audit_results = {}
    print("\n--- ENVIRONMENT SECRETS AUDIT ---")
    for secret_name in secrets_to_check:
        is_present = bool(os.environ.get(secret_name))
        audit_results[secret_name] = is_present
        status_symbol = "✓ PRESENT" if is_present else "✗ MISSING"
        print(f"[{status_symbol}] {secret_name}")
    print("---------------------------------\n")
    return audit_results

def harvest_city_video(service, sheet_id):
    """Skeleton placeholder for CityVideo sheet ingestion."""
    print("[INFO] Skeleton: harvest_city_video module ready.")
    return {"status": "skeleton_ready", "record_count": 0, "target_sheet_id_set": bool(sheet_id)}

def harvest_transit_data(service, sheet_id):
    """Skeleton placeholder for TransitData sheet ingestion."""
    print("[INFO] Skeleton: harvest_transit_data module ready.")
    return {"status": "skeleton_ready", "record_count": 0, "target_sheet_id_set": bool(sheet_id)}

def main():
    print("==================================================")
    print("STARTING TEST HARVEST PIPELINE (SANDBOX)")
    print("==================================================")

    # Ensure output data directory exists
    os.makedirs("data", exist_ok=True)

    # Audit secrets environment
    secret_audit = verify_environment_secrets()

    # Initialize Google Sheets API connection
    service = get_google_sheets_service()

    # Sheet ID bindings
    city_data_sheet_id = os.environ.get("CITY_DATA_SHEET_ID")

    # Run sandbox module tests
    city_video_result = harvest_city_video(service, city_data_sheet_id)
    transit_data_result = harvest_transit_data(service, city_data_sheet_id)

    # Compile sandbox telemetry
    telemetry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": "sandbox_test",
        "sheets_api_authenticated": bool(service),
        "secret_audit": secret_audit,
        "modules": {
            "city_video": city_video_result,
            "transit_data": transit_data_result
        }
    }

    # Write status artifact to data/test_status.json
    status_path = os.path.join("data", "test_status.json")
    with open(status_path, "w", encoding="utf-8") as f:
        json.dump(telemetry, f, indent=2)

    print(f"[SUCCESS] Sandbox telemetry written to {status_path}")
    print("==================================================")
    print("TEST HARVEST COMPLETED SUCCESSFULLY")
    print("==================================================")

if __name__ == "__main__":
    main()