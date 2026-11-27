import os
import sys
import json
import datetime
import requests

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None

SENTRY_DSN = os.getenv("SENTRY_DSN")
if SENTRY_DSN and sentry_sdk:
    sentry_sdk.init(dsn=SENTRY_DSN, traces_sample_rate=0.0, environment="production")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_PATH = os.path.join(DATA_DIR, "weather_alerts.json")


def is_expired(expires_str: str, now_utc: datetime.datetime) -> bool:
    if not expires_str:
        return False
    try:
        exp_dt = datetime.datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=datetime.timezone.utc)
        return exp_dt <= now_utc
    except Exception:
        return False


def fetch_weather_alerts():
    print("Polling NWS for active Severe Weather Alerts in Washington...")
    headers = {"User-Agent": "MySeattleSearch-Telemetry/1.0 (admin@myseattlesearch.com)"}

    res = requests.get("https://api.weather.gov/alerts/active?area=WA", headers=headers, timeout=15)
    res.raise_for_status()
    data = res.json()

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    alerts = []

    for feature in data.get("features", []):
        props = feature.get("properties", {})
        status = (props.get("status") or "").lower()
        msg_type = (props.get("messageType") or "").lower()
        urgency = (props.get("urgency") or "").lower()
        headline = props.get("headline") or ""
        expires = props.get("expires") or ""

        if status != "actual" or msg_type == "cancel" or urgency == "past":
            continue
        if "has been cancelled" in headline.lower() or "has been canceled" in headline.lower():
            continue
        if is_expired(expires, now_utc):
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
            "headline": headline or event_name,
            "description": props.get("description") or "",
            "instruction": props.get("instruction") or "",
            "effective": props.get("effective"),
            "expires": expires,
            "area_desc": props.get("areaDesc") or "",
            "geocode_ugc": props.get("geocode", {}).get("UGC", []),
            "geometry": geom if geom else None
        })

    payload = {
        "generated_utc": now_utc.isoformat(),
        "active_alert_count": len(alerts),
        "alerts": alerts
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"), ensure_ascii=False)
    print(f"Harvested {len(alerts)} active NWS weather alerts -> {OUTPUT_PATH}")


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
