import csv
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
DEV_VARS_PATH = REPO_ROOT / ".dev.vars"
OUTPUT_CSV_PATH = REPO_ROOT / "data" / "commute_baselines.csv"

HUBS = [
    {"id": "slu", "name": "South Lake Union (Seattle)", "lat": 47.6253, "lon": -122.3375},
    {"id": "bellevue", "name": "Downtown Bellevue", "lat": 47.6101, "lon": -122.2015},
    {"id": "redmond", "name": "Microsoft Redmond Campus", "lat": 47.6423, "lon": -122.1368},
    {"id": "everett", "name": "Boeing Everett Factory", "lat": 47.9253, "lon": -122.2715},
    {"id": "renton", "name": "Boeing Renton Factory", "lat": 47.4915, "lon": -122.2155},
    {"id": "kent", "name": "Kent Valley Logistics Hub", "lat": 47.3809, "lon": -122.2348},
]


def load_tomtom_key() -> str:
    if os.environ.get("TOMTOM_API_KEY"):
        return os.environ["TOMTOM_API_KEY"].strip()

    if DEV_VARS_PATH.exists():
        for raw_line in DEV_VARS_PATH.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            if key.strip() == "TOMTOM_API_KEY":
                return val.strip().strip('"').strip("'")

    raise RuntimeError(f"TOMTOM_API_KEY not found in {DEV_VARS_PATH} or environment variables.")


def resolve_city_data_path() -> Path:
    for candidate in (REPO_ROOT / "data" / "city_data.json", REPO_ROOT / "_data" / "city_data.json"):
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Could not locate city_data.json in data/ or _data/.")


def generate_csv() -> None:
    api_key = load_tomtom_key()
    city_data_path = resolve_city_data_path()

    with city_data_path.open("r", encoding="utf-8") as f:
        city_data = json.load(f)

    print(f"Loaded {len(city_data)} neighborhoods from {city_data_path.relative_to(REPO_ROOT)}")

    columns = ["City"]
    for h in HUBS:
        columns.extend([
            f"{h['id']}_distance_mi",
            f"{h['id']}_drive_offpeak_min",
            f"{h['id']}_transit_offpeak_min",
            f"{h['id']}_return_drive_offpeak_min",
            f"{h['id']}_return_transit_offpeak_min",
        ])

    rows = []
    endpoint = f"https://api.tomtom.com/routing/matrix/2?key={api_key}"

    for idx, city in enumerate(city_data):
        city_name = city.get("City")
        c_lat = city.get("Latitude")
        c_lon = city.get("Longitude")

        row_data = {col: "" for col in columns}
        row_data["City"] = city_name or ""

        if not city_name or c_lat is None or c_lon is None:
            print(f"[{idx + 1}/{len(city_data)}] Skipping {city_name or 'Unknown'} (missing coordinates)")
            rows.append(row_data)
            continue

        print(f"[{idx + 1}/{len(city_data)}] Querying TomTom Matrix v2 for {city_name}...")

        # Index 0 = Neighborhood origin; Indices 1..6 = Employment Hubs (captures both directions in 1 call)
        matrix_points = [{"point": {"latitude": float(c_lat), "longitude": float(c_lon)}}] + [
            {"point": {"latitude": h["lat"], "longitude": h["lon"]}} for h in HUBS
        ]

        payload = {
            "origins": matrix_points,
            "destinations": matrix_points,
            "options": {
                "departAt": "any",
                "routeType": "fastest",
                "traffic": "historical",
                "travelMode": "car",
            },
        }

        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                res_data = json.loads(response.read().decode("utf-8"))

            for cell in res_data.get("data", []):
                o_idx = cell.get("originIndex")
                d_idx = cell.get("destinationIndex")
                summary = cell.get("routeSummary")
                if not summary:
                    continue

                length_m = summary.get("lengthInMeters", 0)
                time_sec = summary.get("travelTimeInSeconds", 0)

                # Outbound: Neighborhood (0) -> Hub (1..6)
                if o_idx == 0 and 1 <= d_idx <= len(HUBS):
                    hub_id = HUBS[d_idx - 1]["id"]
                    row_data[f"{hub_id}_distance_mi"] = round(length_m * 0.000621371, 1)
                    row_data[f"{hub_id}_drive_offpeak_min"] = round(time_sec / 60)
                    row_data[f"{hub_id}_transit_offpeak_min"] = round((time_sec * 1.35) / 60 + 6)

                # Return: Hub (1..6) -> Neighborhood (0)
                elif 1 <= o_idx <= len(HUBS) and d_idx == 0:
                    hub_id = HUBS[o_idx - 1]["id"]
                    row_data[f"{hub_id}_return_drive_offpeak_min"] = round(time_sec / 60)
                    row_data[f"{hub_id}_return_transit_offpeak_min"] = round((time_sec * 1.35) / 60 + 6)

        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as err:
            print(f"  Warning: Matrix request failed for {city_name}: {err}")

        rows.append(row_data)
        time.sleep(0.25)

    OUTPUT_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nSaved {len(rows)} rows to {OUTPUT_CSV_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    generate_csv()