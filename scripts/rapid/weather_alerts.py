import os
import json
import datetime
import requests
import boto3
from botocore.config import Config
import sentry_sdk

SENTRY_DSN = os.getenv("SENTRY_DSN")
if SENTRY_DSN:
    sentry_sdk.init(dsn=SENTRY_DSN, traces_sample_rate=0.0, environment="production")

def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("R2_ENDPOINT_URL"),
        aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
        config=Config(signature_version="s3v4")
    )

def fetch_weather_alerts():
    print("📡 Polling NWS for active Severe Weather Alerts in Washington...")
    headers = {"User-Agent": "MySeattleSearch-Telemetry/1.0 (admin@myseattlesearch.com)"}
    
    try:
        res = requests.get("https://api.weather.gov/alerts/active?area=WA", headers=headers, timeout=15)
        res.raise_for_status()
        data = res.json()
        
        alerts = []
        for feature in data.get("features", []):
            props = feature.get("properties", {})
            
            # Filter out non-severe/minor advisories to prevent alert fatigue
            severity = props.get("severity", "").lower()
            if severity not in ["extreme", "severe", "moderate"]:
                continue
                
            alerts.append({
                "id": props.get("id"),
                "event": props.get("event", "Weather Alert"),
                "severity": severity,
                "urgency": props.get("urgency"),
                "headline": props.get("headline", ""),
                "description": props.get("description", ""),
                "instruction": props.get("instruction", ""),
                "effective": props.get("effective"),
                "expires": props.get("expires"),
                "geocode_ugc": props.get("geocode", {}).get("UGC", []),
                "polygon": feature.get("geometry", {}).get("coordinates", []) if feature.get("geometry") else []
            })
            
        payload = {
            "generated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "active_alert_count": len(alerts),
            "alerts": alerts
        }
        
        s3 = get_s3_client()
        s3.put_object(
            Bucket=os.getenv("R2_DATA_BUCKET_NAME"),
            Key="telemetry/weather_alerts.json",
            Body=json.dumps(payload, separators=(',', ':')).encode("utf-8"),
            ContentType="application/json",
            CacheControl="public, max-age=300"
        )
        print(f"✅ Harvested {len(alerts)} active severe weather alerts -> telemetry/weather_alerts.json")
        
    except Exception as e:
        print(f"⚠️ NWS Weather API request failure: {e}")
        if SENTRY_DSN:
            sentry_sdk.capture_exception(e)

if __name__ == "__main__":
    fetch_weather_alerts()