import io
import json
import os
import re
import time
import urllib.parse
import urllib.request
import zipfile


def find_base_dir():
    cur = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        if os.path.exists(os.path.join(cur, "data", "redfin_migration.json")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


BASE_DIR = find_base_dir()
DATA_DIR = os.path.join(BASE_DIR, "data")
MIGRATION_PATH = os.path.join(DATA_DIR, "redfin_migration.json")
OUT_PATH = os.path.join(DATA_DIR, "us_metro_coords.json")

# Geographic centroids for all 50 US states + DC (used for state-level fallback entries)
STATE_CENTROIDS = {
    "AL": (32.8067, -86.7911), "AK": (64.2008, -149.4937), "AZ": (34.0489, -111.0937),
    "AR": (34.7465, -92.2896), "CA": (36.7783, -119.4179), "CO": (39.5501, -105.7821),
    "CT": (41.6032, -73.0877), "DE": (38.9108, -75.5277), "DC": (38.9072, -77.0369),
    "FL": (27.6648, -81.5158), "GA": (32.1656, -82.9001), "HI": (19.8968, -155.5828),
    "ID": (44.0682, -114.7420), "IL": (40.6331, -89.3985), "IN": (40.2672, -86.1349),
    "IA": (41.8780, -93.0977), "KS": (39.0119, -98.4842), "KY": (37.8393, -84.2700),
    "LA": (30.9843, -91.9623), "ME": (45.2538, -69.4455), "MD": (39.0458, -76.6413),
    "MA": (42.4072, -71.3824), "MI": (44.3148, -85.6024), "MN": (46.7296, -94.6859),
    "MS": (32.3547, -89.3985), "MO": (37.9643, -91.8318), "MT": (46.8797, -110.3626),
    "NE": (41.4925, -99.9018), "NV": (38.8026, -116.4194), "NH": (43.1939, -71.5724),
    "NJ": (40.0583, -74.4057), "NM": (34.5199, -105.8701), "NY": (43.2994, -74.2179),
    "NC": (35.7596, -79.0193), "ND": (47.5515, -101.0020), "OH": (40.4173, -82.9071),
    "OK": (35.0078, -97.0929), "OR": (43.8041, -120.5542), "PA": (41.2033, -77.1945),
    "RI": (41.5801, -71.4774), "SC": (33.8361, -81.1637), "SD": (43.9695, -99.9018),
    "TN": (35.5175, -86.5804), "TX": (31.9686, -99.9018), "UT": (39.3210, -111.0937),
    "VT": (44.5588, -72.5778), "VA": (37.4316, -78.6569), "WA": (47.7511, -120.7401),
    "WV": (38.5976, -80.4549), "WI": (43.7844, -88.7879), "WY": (43.0760, -107.2903),
}

# Manual overrides where Redfin uses a regional alias instead of the Census principal city
METRO_ALIASES = {
    "Bay Area, CA": ("San Jose", "CA"),
    "Seattle, WA metro area": ("Seattle", "WA"),
}


def project_to_svg(lat, lon, state=None):
    """Project (lat, lon) onto the 320x200 US continental SVG viewport with AK/HI insets."""
    if state == "AK":
        x = 12.0 + ((lon - (-170.0)) / 40.0) * 22.0
        y = 164.0 + ((71.0 - lat) / 17.0) * 24.0
        return round(max(6.0, min(36.0, x)), 1), round(max(158.0, min(194.0, y)), 1)
    if state == "HI":
        x = 44.0 + ((lon - (-160.5)) / 6.0) * 22.0
        y = 176.0 + ((22.5 - lat) / 3.8) * 16.0
        return round(max(40.0, min(72.0, x)), 1), round(max(172.0, min(195.0, y)), 1)

    x = 40.0 + ((lon - (-124.5)) / 57.5) * 260.0
    y = 26.0 + ((49.0 - lat) / 24.0) * 158.0
    return round(max(36.0, min(302.0, x)), 1), round(max(24.0, min(192.0, y)), 1)


def load_census_cbsa_gazetteer():
    """Download U.S. Census CBSA Gazetteer and index by (normalized_city, state_abbr)."""
    urls = [
        "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2025_Gazetteer/2025_Gaz_cbsa_national.zip",
        "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_cbsa_national.zip",
        "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/2023_Gaz_cbsa_national.zip",
    ]
    raw_zip = None
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "MySeattleSearch-GeoBuilder/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status == 200:
                    raw_zip = resp.read()
                    print(f"Downloaded Census CBSA Gazetteer: {url}")
                    break
        except Exception as e:
            print(f"Gazetteer attempt failed [{url}]: {e}")

    if not raw_zip:
        return {}

    index = {}
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as zf:
        txt_names = [n for n in zf.namelist() if n.endswith(".txt")]
        if not txt_names:
            return {}
        content = zf.read(txt_names[0]).decode("utf-8", errors="replace")

    lines = content.splitlines()
    if not lines:
        return {}

    delim = "|" if "|" in lines[0] else "\t"
    headers = [h.strip() for h in lines[0].split(delim)]
    try:
        name_idx = headers.index("NAME")
        lat_idx = headers.index("INTPTLAT")
        lon_idx = headers.index("INTPTLONG")
    except ValueError:
        return {}

    for line in lines[1:]:
        cols = [c.strip() for c in line.split(delim)]
        if len(cols) <= max(name_idx, lat_idx, lon_idx):
            continue
        raw_name = cols[name_idx]
        # Strip trailing " Metro Area" / " Micro Area"
        clean_name = re.sub(r"\s+(Metro|Micro)\s+Area$", "", raw_name, flags=re.IGNORECASE).strip()
        if "," not in clean_name:
            continue
        cities_part, states_part = clean_name.rsplit(",", 1)
        states_list = [s.strip() for s in states_part.split("-") if s.strip()]
        cities_list = [c.strip() for c in cities_part.split("-") if c.strip()]
        try:
            lat = float(cols[lat_idx])
            lon = float(cols[lon_idx])
        except ValueError:
            continue

        for st in states_list:
            # Index full multi-city string as well as each constituent principal city
            index[(cities_part.strip().lower(), st)] = (lat, lon)
            for c in cities_list:
                index.setdefault((c.lower(), st), (lat, lon))

    return index


def geocode_nominatim(city, state):
    """Fallback geocoder via OpenStreetMap Nominatim structured search."""
    params = urllib.parse.urlencode({
        "city": city,
        "state": state,
        "countrycodes": "us",
        "format": "jsonv2",
        "limit": 1,
    })
    url = f"https://nominatim.openstreetmap.org/search?{params}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "MySeattleSearch-StaticGeoBuilder/1.0 (contact@myseattlesearch.com)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if resp.status == 200:
                results = json.loads(resp.read().decode("utf-8"))
                if results:
                    return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception as e:
        print(f"Nominatim error for {city}, {state}: {e}")
    return None


def main():
    if not os.path.exists(MIGRATION_PATH):
        raise FileNotFoundError(f"Missing {MIGRATION_PATH}")

    with open(MIGRATION_PATH, "r", encoding="utf-8") as f:
        rm = json.load(f)

    metros_dict = rm.get("data", {}).get("metros", {})
    metro_names = set(metros_dict.keys())
    for m_data in metros_dict.values():
        for r in m_data.get("top_inflow", []):
            if r.get("ORIGIN REGION NAME"):
                metro_names.add(r["ORIGIN REGION NAME"].strip())
        for r in m_data.get("top_outflow", []):
            if r.get("DESTINATION REGION NAME"):
                metro_names.add(r["DESTINATION REGION NAME"].strip())

    # Preserve any previously saved coordinates so re-runs are incremental
    existing = {}
    if os.path.exists(OUT_PATH):
        try:
            with open(OUT_PATH, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = {}

    cbsa_index = load_census_cbsa_gazetteer()
    output = {}

    # 1. Store all 50 US states + DC directly inside the same lookup dictionary
    for st, (lat, lon) in sorted(STATE_CENTROIDS.items()):
        x, y = project_to_svg(lat, lon, st)
        output[st] = {
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            "x": x,
            "y": y,
            "type": "state",
        }

    # 2. Resolve all Redfin metro areas
    resolved_gaz = 0
    resolved_nom = 0
    fallback_state = 0

    for name in sorted(metro_names):
        if name in existing and "x" in existing[name] and "y" in existing[name]:
            output[name] = existing[name]
            continue

        if name in METRO_ALIASES:
            city_query, state_code = METRO_ALIASES[name]
        else:
            m = re.match(r"^(.+),\s*([A-Z]{2})$", name)
            if not m:
                continue
            city_query, state_code = m.group(1).strip(), m.group(2).strip()

        coords = cbsa_index.get((city_query.lower(), state_code))
        if not coords and "-" in city_query:
            first_city = city_query.split("-")[0].strip().lower()
            coords = cbsa_index.get((first_city, state_code))

        if coords:
            lat, lon = coords
            resolved_gaz += 1
        else:
            time.sleep(1.1)  # Nominatim usage policy: max 1 req/sec
            nom = geocode_nominatim(city_query, state_code)
            if nom:
                lat, lon = nom
                resolved_nom += 1
                print(f"Nominatim resolved: {name} -> ({lat:.4f}, {lon:.4f})")
            elif state_code in STATE_CENTROIDS:
                lat, lon = STATE_CENTROIDS[state_code]
                fallback_state += 1
                print(f"State-centroid fallback: {name} -> {state_code}")
            else:
                continue

        x, y = project_to_svg(lat, lon, state_code)
        output[name] = {
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            "x": x,
            "y": y,
            "state": state_code,
        }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(
        f"Saved {len(output)} entries ({len(STATE_CENTROIDS)} states + {len(metro_names)} metros) to {OUT_PATH} "
        f"[Census={resolved_gaz}, Nominatim={resolved_nom}, StateFallback={fallback_state}]"
    )


if __name__ == "__main__":
    main()