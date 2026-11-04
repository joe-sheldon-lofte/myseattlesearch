import os
import sys
import json
import boto3
import requests
import xml.etree.ElementTree as ET
from botocore.client import Config
import sentry_sdk

SENTRY_DSN = os.getenv("SENTRY_DSN")
if SENTRY_DSN:
    sentry_sdk.init(dsn=SENTRY_DSN, traces_sample_rate=0.0, environment="production")

R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_ENDPOINT = os.getenv("R2_ENDPOINT_URL")
BUCKET = os.getenv("R2_BUCKET_NAME")

FLASHALERT_URL = "https://www.flashalertnewswire.net/IIN/reportsX/flashnews_xml_emergency.php?RegionID=12&Testing=0"

def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY,
        aws_secret_access_key=R2_SECRET_KEY,
        config=Config(signature_version="s3v4")
    )

def harvest_flashalert():
    print("📡 Fetching FlashAlert Region 12 Emergency Feed...")
    headers = {"User-Agent": "MySeattleSearch-Telemetry/1.0 (+https://myseattlesearch.com)"}
    res = requests.get(FLASHALERT_URL, headers=headers, timeout=15)
    res.raise_for_status()

    root = ET.fromstring(res.content)
    feed_updated = root.attrib.get("updated", "")
    reports = []

    for category in root.findall(".//emergency_category"):
        cat_name = category.attrib.get("name", "")
        for report in category.findall("emergency_report"):
            # Enforce strict filtration
            if report.attrib.get("testing") != "0":
                continue
            
            op_code = report.attrib.get("operating_code", "")
            if op_code == "7":  # Hard filter on test notices
                continue

            report_id = report.attrib.get("report_id")
            effective_date = report.attrib.get("effective_date", "")
            last_update = report.attrib.get("last_update", "")
            transpo_code = report.attrib.get("transpo_code", "")
            org_id = report.attrib.get("orgid", "")

            detail_el = report.find("detail")
            tomorrow_el = report.find("tomorrow")
            orgname_el = report.find("orgname")

            detail_text = detail_el.text.strip() if detail_el is not None and detail_el.text else ""
            tomorrow_text = tomorrow_el.text.strip() if tomorrow_el is not None and tomorrow_el.text else ""
            org_name = orgname_el.text.strip() if orgname_el is not None and orgname_el.text else ""

            # Operating Severity Tier:
            # Codes 1, 3, 4, 5 = Classroom Impacted (PNW Red)
            # Codes 2, 6 = Ancillary Friction / Snow Routes / Activities (Status Amber)
            severity = "red" if op_code in ["1", "3", "4", "5"] else "amber"

            reports.append({
                "report_id": report_id,
                "org_id": org_id,
                "org_name": org_name,
                "category": cat_name,
                "operating_code": op_code,
                "transpo_code": transpo_code,
                "severity": severity,
                "effective_date": effective_date,
                "last_update": last_update,
                "is_tomorrow": bool(tomorrow_text),
                "detail": detail_text,
                "tomorrow_note": tomorrow_text
            })

    payload = {
        "feed_updated_utc": feed_updated,
        "active_report_count": len(reports),
        "reports": reports
    }

    s3 = get_s3_client()
    s3.put_object(
        Bucket=BUCKET,
        Key="telemetry/schools.json",
        Body=json.dumps(payload, separators=(',', ':')),
        ContentType="application/json",
        CacheControl="public, max-age=60, s-maxage=60"
    )
    print(f"✅ Harvested {len(reports)} active school reports -> telemetry/schools.json")

def main():
    try:
        harvest_flashalert()
    except Exception as e:
        print(f"❌ FlashAlert Harvester failed: {e}")
        if SENTRY_DSN:
            sentry_sdk.capture_exception(e)
        sys.exit(1)

if __name__ == "__main__":
    main()