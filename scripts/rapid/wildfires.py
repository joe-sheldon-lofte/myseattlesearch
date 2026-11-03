import os
import io
import json
import datetime
import requests
import boto3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOCAL_OUT = os.path.join(DATA_DIR, "wildfires.json")

# NIFC WFIGS Active Wildland Fire Incident Locations Endpoint
WFIGS_ENDPOINT = (
    "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/"
    "WFIGS_Incident_Locations_Current/FeatureServer/0/query"
)

def load_dev_vars():
    dev_vars_path = os.path.join(BASE_DIR, ".dev.vars")
    if os.path.exists(dev_vars_path):
        with open(dev_vars_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

def fetch_wfigs_wildfires():
    print("📡 Polling NIFC WFIGS for active Pacific Northwest wildfires...")
    params = {
        "where": "POOState = 'WA' OR (Latitude >= 45.5 AND Latitude <= 49.0 AND Longitude >= -124.8 AND Longitude <= -116.9)",
        "outFields": (
            "UniqueFireIdentifier,IncidentName,IncidentSize,DailyAcres,PercentContained,"
            "FireDiscoveryDateTime,ModifiedOnDateTime_dt,POOCounty,POOState,Latitude,Longitude,"
            "IncidentTypeCategory,FireBehaviorGeneral,FireCause"
        ),
        "returnGeometry": "false",
        "outSR": "4326",
        "f": "json"
    }
    headers = {"User-Agent": "MySeattleSearch-Telemetry/1.0"}

    try:
        response = requests.get(WFIGS_ENDPOINT, params=params, headers=headers, timeout=20)
        response.raise_for_status()
        data = response.json()
        features = data.get("features", [])
        print(f"   Located {len(features)} wildland incidents in Washington buffer.")
        return features
    except Exception as e:
        print(f"   ⚠️ NIFC WFIGS API request failure: {e}")
        return []

def format_epoch_ms(epoch_ms):
    if not epoch_ms:
        return None
    try:
        return datetime.datetime.fromtimestamp(epoch_ms / 1000.0, tz=datetime.timezone.utc).isoformat()
    except (ValueError, TypeError, OSError):
        return None

def normalize_incident(attrs):
    acres_raw = attrs.get("IncidentSize") if attrs.get("IncidentSize") is not None else attrs.get("DailyAcres")
    try:
        acres = round(float(acres_raw), 1) if acres_raw is not None else 0.0
    except (ValueError, TypeError):
        acres = 0.0

    pct_contained = attrs.get("PercentContained")
    try:
        containment = int(pct_contained) if pct_contained is not None else None
    except (ValueError, TypeError):
        containment = None

    raw_name = str(attrs.get("IncidentName", "Unnamed Fire")).strip().title()
    fire_id = str(attrs.get("UniqueFireIdentifier") or f"wa_fire_{attrs.get('Latitude')}_{attrs.get('Longitude')}").strip()

    status = "Active"
    if containment == 100:
        status = "Contained"

    return {
        "id": fire_id,
        "name": raw_name,
        "county": (attrs.get("POOCounty") or "").strip().title(),
        "state": attrs.get("POOState", "WA"),
        "status": status,
        "acres": acres,
        "containment_percent": containment,
        "fire_cause": attrs.get("FireCause") or "Under Investigation",
        "fire_behavior": attrs.get("FireBehaviorGeneral") or "Active",
        "discovered_utc": format_epoch_ms(attrs.get("FireDiscoveryDateTime")),
        "updated_utc": format_epoch_ms(attrs.get("ModifiedOnDateTime_dt")),
        "coordinates": {
            "latitude": round(float(attrs.get("Latitude")), 5) if attrs.get("Latitude") else None,
            "longitude": round(float(attrs.get("Longitude")), 5) if attrs.get("Longitude") else None
        }
    }

def main():
    load_dev_vars()
    os.makedirs(DATA_DIR, exist_ok=True)

    features = fetch_wfigs_wildfires()
    incidents = []

    for f in features:
        attrs = f.get("attributes", {})
        coords_valid = attrs.get("Latitude") and attrs.get("Longitude")
        if coords_valid:
            incidents.append(normalize_incident(attrs))

    # Sort descending by burn area
    incidents.sort(key=lambda x: x["acres"], reverse=True)

    payload = {
        "telemetry_type": "active_wildfires",
        "cadence": "rapid",
        "generated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "incident_count": len(incidents),
        "total_acres_burned": round(sum(i["acres"] for i in incidents), 1),
        "incidents": incidents
    }

    raw_json = json.dumps(payload, indent=2, ensure_ascii=False)

    # Local snapshot backup
    with open(LOCAL_OUT, "w", encoding="utf-8") as f_out:
        f_out.write(raw_json)

    # Cloudflare R2 Upload
    r2_access_key = os.environ.get("R2_ACCESS_KEY_ID")
    r2_secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
    r2_endpoint = os.environ.get("R2_ENDPOINT_URL")
    r2_bucket = os.environ.get("R2_BUCKET_NAME", "myseattlesearch-data")

    if all([r2_access_key, r2_secret_key, r2_endpoint, r2_bucket]):
        print(f"🚀 Streaming telemetry to Cloudflare R2: {r2_bucket}/telemetry/wildfires.json...")
        s3 = boto3.client(
            "s3",
            endpoint_url=r2_endpoint,
            aws_access_key_id=r2_access_key,
            aws_secret_access_key=r2_secret_key,
            region_name="auto"
        )
        s3.put_object(
            Bucket=r2_bucket,
            Key="telemetry/wildfires.json",
            Body=raw_json.encode("utf-8"),
            ContentType="application/json",
            CacheControl="public, max-age=300"
        )
        print("✅ Wildfires telemetry committed to R2.")
    else:
        print("⚠️ R2 credentials absent in environment. Stored locally only.")

if __name__ == "__main__":
    main()