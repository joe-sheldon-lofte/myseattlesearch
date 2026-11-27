import os
import sys
import json
import requests
import xml.etree.ElementTree as ET

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None

SENTRY_DSN = os.getenv("SENTRY_DSN")
if SENTRY_DSN and sentry_sdk:
    sentry_sdk.init(dsn=SENTRY_DSN, traces_sample_rate=0.0, environment="production")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_PATH = os.path.join(DATA_DIR, "schools.json")

FLASHALERT_URL = "https://www.flashalertnewswire.net/IIN/reportsX/flashnews_xml_emergency.php?RegionID=12&Testing=0"


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
            if report.attrib.get("testing") != "0":
                continue

            op_code = report.attrib.get("operating_code", "")
            if op_code == "7":
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

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"), ensure_ascii=False)
    print(f"✅ Harvested {len(reports)} active school reports -> {OUTPUT_PATH}")


def main():
    try:
        harvest_flashalert()
    except Exception as e:
        print(f"❌ FlashAlert Harvester failed: {e}")
        if SENTRY_DSN and sentry_sdk:
            sentry_sdk.capture_exception(e)
        sys.exit(1)


if __name__ == "__main__":
    main()
