import os
import requests
import json
import sentry_sdk

D1_API_TOKEN = os.getenv("CF_D1_API_TOKEN")
ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID")
DATABASE_ID = os.getenv("CF_DATABASE_TELEMETRY_ID")

# PNW Bounding Box (Approx: Oregon border to Canada, Pacific Coast to Idaho)
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

    url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/d1/database/{DATABASE_ID}/query"
    headers = {
        "Authorization": f"Bearer {D1_API_TOKEN}",
        "Content-Type": "application/json"
    }

    # Prepare batch upsert using SQLite ON CONFLICT
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
    
    statements = []
    for q in quakes:
        statements.append({
            "sql": sql,
            "params": [
                q["id"], q["magnitude"], q["place"], q["time_ms"], q["updated_ms"], q["tz"], 
                q["url"], q["detail"], q["felt"], q["cdi"], q["mmi"], q["alert"], q["status"], 
                q["tsunami"], q["sig"], q["net"], q["code"], q["ids"], q["sources"], q["types"], 
                q["nst"], q["dmin"], q["rms"], q["gap"], q["magType"], q["type"], 
                q["longitude"], q["latitude"], q["depth"]
            ]
        })

    response = requests.post(url, headers=headers, json=statements)
    if response.status_code != 200:
        raise Exception(f"D1 Batch Error: {response.text}")

    print(f"Successfully upserted {len(quakes)} PNW seismic events to D1.")

def main():
    print("Initiating USGS Earthquake Harvester...")
    try:
        quakes = fetch_pnw_earthquakes()
        upsert_to_d1(quakes)
    except Exception as e:
        if os.getenv("SENTRY_DSN"):
            sentry_sdk.capture_exception(e)
        raise e

if __name__ == "__main__":
    main()