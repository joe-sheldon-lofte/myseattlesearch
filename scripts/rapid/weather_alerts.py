import os
import sys
import json
import datetime
import requests
import boto3
from botocore.config import Config

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None

SENTRY_DSN = os.getenv("SENTRY_DSN")
if SENTRY_DSN and sentry_sdk:
    sentry_sdk.init(dsn=SENTRY_DSN, traces_sample_rate=0.0, environment="production")


def get_s3_client():
    endpoint_url = os.getenv("R2_ENDPOINT_URL")
    account_id = os.getenv("CF_ACCOUNT_ID")
    if not endpoint_url and account_id:
        endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
        config=Config(signature_version="s3v4"),
        region_name="auto"
    )


def fetch_weather_alerts():
    print("Polling NWS for active Severe Weather Alerts in Washington...")
    headers = {"User-Agent": "MySeattleSearch-Telemetry/1.0 (admin@myseattlesearch.com)"}
    bucket_name = os.getenv("R2_DATA_BUCKET_NAME") or os.getenv("R2_BUCKET_NAME")

    res = requests.get("https://api.weather.gov/alerts/active?area=WA", headers=headers, timeout=15)
    res.raise_for_status()
    data = res.json()

    alerts = []
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        status = (props.get("status") or "").lower()
        msg_type = (props.get("messageType") or "").lower()
        if status != "actual" or msg_type == "cancel":
            continue

        severity = (props.get("severity") or "").lower()
        event_name = props.get("event") or "Weather Alert"
        is_significant = severity in ("extreme", "severe", "moderate") or any(
            k in event_name.lower() for k in ("warning", "watch", "advisory")
        )
        if not is_significant:
            continue

        geom = feature.get("geometry")
        alerts.append({
            "id": props.get("id"),
            "event": event_name,
            "severity": severity,
            "urgency": props.get("urgency"),
            "headline": props.get("headline") or event_name,
            "description": props.get("description") or "",
            "instruction": props.get("instruction") or "",
            "effective": props.get("effective"),
            "expires": props.get("expires"),
            "area_desc": props.get("areaDesc") or "",
            "geocode_ugc": props.get("geocode", {}).get("UGC", []),
            "geometry": geom if geom else None
        })

    payload = {
        "generated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "active_alert_count": len(alerts),
        "alerts": alerts
    }

    s3 = get_s3_client()
    s3.put_object(
        Bucket=bucket_name,
        Key="telemetry/weather_alerts.json",
        Body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        ContentType="application/json",
        CacheControl="public, max-age=300"
    )
    print(f"Harvested {len(alerts)} active NWS weather alerts -> {bucket_name}/telemetry/weather_alerts.json")


def main():
    try:
        fetch_weather_alerts()
    except Exception as exc:
        print(f"NWS Weather Alert Harvester failed: {exc}")
        if SENTRY_DSN and sentry_sdk:
            sentry_sdk.capture_exception(exc)
        sys.exit(1)


if __name__ == "__main__":
    main()