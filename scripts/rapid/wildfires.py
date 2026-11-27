import os
import json
import datetime
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOCAL_OUT = os.path.join(DATA_DIR, "wildfires.json")

WFIGS_ENDPOINT = (
    "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/"
    "WFIGS_Incident_Locations_Current/FeatureServer/0/query"
)


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
        return None


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
    status = "Contained" if containment == 100 else "Active"

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
    os.makedirs(DATA_DIR, exist_ok=True)

    features = fetch_wfigs_wildfires()
    if features is None:
        print("⚠️ Preserving existing data/wildfires.json due to upstream API error.")
        return

    incidents = []
    for f in features:
        attrs = f.get("attributes", {})
        if attrs.get("Latitude") and attrs.get("Longitude"):
            incidents.append(normalize_incident(attrs))

    incidents.sort(key=lambda x: x["acres"], reverse=True)

    payload = {
        "telemetry_type": "active_wildfires",
        "cadence": "rapid",
        "generated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "incident_count": len(incidents),
        "total_acres_burned": round(sum(i["acres"] for i in incidents), 1),
        "incidents": incidents
    }

    with open(LOCAL_OUT, "w", encoding="utf-8") as f_out:
        json.dump(payload, f_out, indent=2, ensure_ascii=False)
    print(f"✅ Saved {len(incidents)} wildfire incidents -> {LOCAL_OUT}")


if __name__ == "__main__":
    main()
