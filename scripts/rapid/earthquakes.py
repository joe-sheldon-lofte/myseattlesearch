import os
import requests

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None

SENTRY_DSN = os.getenv("SENTRY_DSN")
if SENTRY_DSN and sentry_sdk:
    sentry_sdk.init(dsn=SENTRY_DSN, traces_sample_rate=0.0, environment="production")

D1_API_TOKEN = os.getenv("CF_MASTER_API_TOKEN") or os.getenv("CF_D1_API_TOKEN")
ACCOUNT_ID = os.getenv("CF_MASTER_ACCOUNT_ID") or os.getenv("CF_ACCOUNT_ID")
DATABASE_ID = os.getenv("CF_DATABASE_TELEMETRY_ID")

LAT_MIN, LAT_MAX = 45.0, 49.0
LON_MIN, LON_MAX = -125.0, -116.0


def fetch_pnw_earthquakes():
    url = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    data = response.json()

    pnw_quakes = []
    for feature in data.get("features", []):
        coords = feature["geometry"]["coordinates"]
        lon, lat, depth = coords[0], coords[1], coords[2]

        if LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX:
            props = feature["properties"]
            pnw_quakes.append({
                "id": feature["id"],
                "magnitude": props.get("mag", 0.0),
                "place": props.get("place", "Unknown"),
                "time_ms": props.get("time", 0),
                "updated_ms": props.get("updated", 0),
                "tz": props.get("tz"),
                "url": props.get("url"),
                "detail": props.get("detail"),
                "felt": props.get("felt"),
                "cdi": props.get("cdi"),
                "mmi": props.get("mmi"),
                "alert": props.get("alert"),
                "status": props.get("status"),
                "tsunami": props.get("tsunami", 0),
                "sig": props.get("sig"),
                "net": props.get("net"),
                "code": props.get("code"),
                "ids": props.get("ids"),
                "sources": props.get("sources"),
                "types": props.get("types"),
                "nst": props.get("nst"),
                "dmin": props.get("dmin"),
                "rms": props.get("rms"),
                "gap": props.get("gap"),
                "magType": props.get("magType"),
                "type": props.get("type"),
                "longitude": lon,
                "latitude": lat,
                "depth": depth
            })
    return pnw_quakes


def upsert_to_d1(quakes):
    if not quakes:
        print("No PNW earthquakes detected in the last 24 hours.")
        return

    if not all([ACCOUNT_ID, DATABASE_ID, D1_API_TOKEN]):
        raise RuntimeError("Missing Cloudflare D1 credentials (CF_MASTER_ACCOUNT_ID / CF_MASTER_API_TOKEN / CF_DATABASE_TELEMETRY_ID).")

    url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/d1/database/{DATABASE_ID}/query"
    headers = {
        "Authorization": f"Bearer {D1_API_TOKEN}",
        "Content-Type": "application/json"
    }

    sql = """
        INSERT INTO earthquakes (
            id, magnitude, place, time_ms, updated_ms, tz, url, detail, felt,
            cdi, mmi, alert, status, tsunami, sig, net, code, ids, sources,
            types, nst, dmin, rms, gap, magType, type, longitude, latitude, depth
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        ON CONFLICT(id) DO UPDATE SET
            updated_ms = excluded.updated_ms,
            magnitude = excluded.magnitude,
            felt = excluded.felt,
            cdi = excluded.cdi,
            mmi = excluded.mmi,
            alert = excluded.alert,
            status = excluded.status;
    """

    statements = [
        {
            "sql": sql,
            "params": [
                q["id"], q["magnitude"], q["place"], q["time_ms"], q["updated_ms"], q["tz"],
                q["url"], q["detail"], q["felt"], q["cdi"], q["mmi"], q["alert"], q["status"],
                q["tsunami"], q["sig"], q["net"], q["code"], q["ids"], q["sources"], q["types"],
                q["nst"], q["dmin"], q["rms"], q["gap"], q["magType"], q["type"],
                q["longitude"], q["latitude"], q["depth"]
            ]
        }
        for q in quakes
    ]

    response = requests.post(url, headers=headers, json=statements, timeout=20)
    if response.status_code != 200:
        raise Exception(f"D1 Batch Error: {response.text}")

    print(f"Successfully upserted {len(quakes)} PNW seismic events to D1.")


def main():
    print("Initiating USGS Earthquake Harvester...")
    try:
        quakes = fetch_pnw_earthquakes()
        upsert_to_d1(quakes)
    except Exception as e:
        if SENTRY_DSN and sentry_sdk:
            sentry_sdk.capture_exception(e)
        raise e


if __name__ == "__main__":
    main()
