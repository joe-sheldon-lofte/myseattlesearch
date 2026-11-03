#!/usr/bin/env python3
"""
Regional Power Outage Ingestion Engine
Fetches live telemetry for SCL, PSE, and SnoPUD, normalizes schemas,
and uploads the unified snapshot directly to Cloudflare R2.
"""

import os
import sys
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone

try:
    import boto3
    from botocore.config import Config
except ImportError:
    print("Error: boto3 is required. Run 'pip install boto3'.", file=sys.stderr)
    sys.exit(1)

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json"
}


def fetch_json(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers=HTTP_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ingest_scl():
    url = "https://utilisocial.io/datacapable/v2/p/SCL/map/events"
    try:
        events = fetch_json(url)
        event_list = events if isinstance(events, list) else []
        customers = sum(e.get("numPeople", 0) for e in event_list)
        count = len(event_list)

        if count > 5 or customers > 1000:
            condition = "elevated"
            label = "Elevated Outages"
        elif count > 0:
            condition = "localized"
            label = "Localized Incidents"
        else:
            condition = "optimal"
            label = "Grid Optimal"

        return {
            "status": "online",
            "name": "Seattle City Light",
            "provider_code": "SCL",
            "active_incidents": count,
            "customers_affected": customers,
            "status_label": label,
            "grid_condition": condition,
            "events": event_list
        }
    except Exception as err:
        return {
            "status": "degraded",
            "name": "Seattle City Light",
            "provider_code": "SCL",
            "active_incidents": 0,
            "customers_affected": 0,
            "status_label": "Telemetry Synchronizing",
            "grid_condition": "unknown",
            "error": str(err)
        }


def ingest_pse():
    url = "https://www.pse.com/api/sitecore/OutageMap/AnonymoussMapListView"
    try:
        data = fetch_json(url)
        incidents = data.get("PseMap", [])
        common = data.get("Common", {})
        count = common.get("OutageCount", len(incidents))

        # 1. Check top-level aggregate
        customers = common.get("CustsOut", 0)

        # 2. If aggregate is missing/zero, sum across incident DataProvider attributes
        if not customers and incidents:
            tally = 0
            for inc in incidents:
                attrs = inc.get("DataProvider", {}).get("Attributes", [])
                for attr in attrs:
                    if attr.get("Name") == "Customers impacted":
                        raw_val = str(attr.get("Value", "0")).replace(",", "").strip()
                        try:
                            tally += int(raw_val)
                        except ValueError:
                            pass
            customers = tally

        if count > 5 or customers > 1000:
            condition = "elevated"
            label = "Elevated Outages"
        elif count > 0:
            condition = "localized"
            label = "Localized Incidents"
        else:
            condition = "optimal"
            label = "Grid Optimal"

        return {
            "status": "online",
            "name": "Puget Sound Energy",
            "provider_code": "PSE",
            "active_incidents": count,
            "customers_affected": customers,
            "status_label": label,
            "grid_condition": condition,
            "incidents": incidents
        }
    except Exception as err:
        return {
            "status": "degraded",
            "name": "Puget Sound Energy",
            "provider_code": "PSE",
            "active_incidents": 0,
            "customers_affected": 0,
            "status_label": "Telemetry Synchronizing",
            "grid_condition": "unknown",
            "error": str(err)
        }


def ingest_snopud():
    url = "https://outage-pmtiles-prod-cntr.whiteplant-5e2d905c.westus2.azurecontainerapps.io/incidents/8/41/88.mvt"
    try:
        req = urllib.request.Request(url, headers=HTTP_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            status_code = resp.getcode()
            content = resp.read()
            count = 0 if status_code == 204 or len(content) == 0 else 1
            customers = 0

        condition = "localized" if count > 0 else "optimal"
        label = "Localized Incidents" if count > 0 else "Grid Optimal"

        return {
            "status": "online",
            "name": "Snohomish County PUD",
            "provider_code": "SNOPUD",
            "active_incidents": count,
            "customers_affected": customers,
            "status_label": label,
            "grid_condition": condition
        }
    except Exception as err:
        return {
            "status": "degraded",
            "name": "Snohomish County PUD",
            "provider_code": "SNOPUD",
            "active_incidents": 0,
            "customers_affected": 0,
            "status_label": "Telemetry Synchronizing",
            "grid_condition": "unknown",
            "error": str(err)
        }


def upload_to_r2(payload_bytes: bytes):
    endpoint_url = os.environ.get("R2_ENDPOINT_URL")
    account_id = os.environ.get("CF_ACCOUNT_ID")
    access_key = os.environ.get("R2_ACCESS_KEY_ID")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
    bucket_name = os.environ.get("R2_DATA_BUCKET_NAME")

    if not endpoint_url:
        if account_id:
            endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"
        else:
            raise ValueError("Missing endpoint configuration: provide either R2_ENDPOINT_URL or CF_ACCOUNT_ID.")

    if not all([access_key, secret_key, bucket_name]):
        raise ValueError("Missing required R2 credentials: R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, or R2_DATA_BUCKET_NAME.")

    s3_client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
        region_name="auto"
    )

    s3_client.put_object(
        Bucket=bucket_name,
        Key="telemetry/power_outages.json",
        Body=payload_bytes,
        ContentType="application/json",
        CacheControl="public, max-age=180"
    )
    print(f"Successfully uploaded snapshot to R2: {bucket_name}/telemetry/power_outages.json")


def main():
    print(f"[{datetime.now(timezone.utc).isoformat()}] Polling regional utility feeds...")
    scl = ingest_scl()
    pse = ingest_pse()
    snopud = ingest_snopud()

    payload = {
        "metadata": {
            "updated_utc": datetime.now(timezone.utc).isoformat(),
            "region": "Puget Sound",
            "providers_monitored": ["SCL", "PSE", "SNOPUD"]
        },
        "utilities": {
            "SCL": scl,
            "PSE": pse,
            "SNOPUD": snopud
        }
    }

    serialized = json.dumps(payload, indent=2).encode("utf-8")
    upload_to_r2(serialized)


if __name__ == "__main__":
    main()