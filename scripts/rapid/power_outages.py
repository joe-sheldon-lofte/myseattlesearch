#!/usr/bin/env python3
"""
Regional Power Outage Ingestion Engine
Fetches live telemetry for SCL, PSE, and SnoPUD, maps incidents spatially to
canonical neighborhoods, and writes the unified snapshot to data/power_outages.json.
"""

import os
import re
import json
import math
import urllib.request
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_PATH = os.path.join(DATA_DIR, "power_outages.json")

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json"
}


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[-\s]+", "-", text)


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return r * (2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a)))


def point_in_ring(lon: float, lat: float, ring: list) -> bool:
    n = len(ring)
    if n < 3:
        return False
    inside = False
    p1x, p1y = ring[0][0], ring[0][1]
    for i in range(1, n + 1):
        p2x, p2y = ring[i % n][0], ring[i % n][1]
        if lat > min(p1y, p2y):
            if lat <= max(p1y, p2y):
                if lon <= max(p1x, p2x):
                    if p1y != p2y:
                        xints = (lat - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or lon <= xints:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside


def point_in_geometry(lon: float, lat: float, geom: dict) -> bool:
    if not geom:
        return False
    gtype = geom.get("type")
    coords = geom.get("coordinates", [])
    if gtype == "Polygon":
        return bool(coords) and point_in_ring(lon, lat, coords[0])
    if gtype == "MultiPolygon":
        return any(poly and point_in_ring(lon, lat, poly[0]) for poly in coords)
    return False


def load_city_spatial_index() -> list:
    city_path = next(
        (p for p in (os.path.join(DATA_DIR, "city_data.json"), os.path.join(BASE_DIR, "_data", "city_data.json")) if os.path.exists(p)),
        None
    )
    bound_path = next(
        (p for p in (os.path.join(DATA_DIR, "city_boundaries.json"), os.path.join(BASE_DIR, "_data", "city_boundaries.json")) if os.path.exists(p)),
        None
    )

    boundaries_by_slug = {}
    if bound_path:
        with open(bound_path, "r", encoding="utf-8") as fb:
            bdata = json.load(fb)
        for feat in bdata.get("features", []):
            slug = feat.get("properties", {}).get("slug")
            if slug:
                boundaries_by_slug[slug] = feat.get("geometry")

    cities = []
    if city_path:
        with open(city_path, "r", encoding="utf-8") as fc:
            cdata = json.load(fc)
        for row in cdata:
            name = row.get("City")
            lat = row.get("Latitude")
            lon = row.get("Longitude")
            if not name or lat is None or lon is None:
                continue
            cslug = slugify(name)
            cities.append({
                "name": name,
                "slug": cslug,
                "lat": float(lat),
                "lon": float(lon),
                "geometry": boundaries_by_slug.get(cslug)
            })
    return cities


def fetch_json(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers=HTTP_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ingest_scl():
    url = "https://utilisocial.io/datacapable/v2/p/SCL/map/events"
    normalized = []
    try:
        events = fetch_json(url)
        event_list = events if isinstance(events, list) else []
        customers = sum(int(e.get("numPeople", 0) or 0) for e in event_list)
        count = len(event_list)

        for ev in event_list:
            lat = ev.get("latitude")
            lon = ev.get("longitude")
            if lat is None or lon is None:
                continue
            rings = ev.get("polygons", {}).get("rings", []) if isinstance(ev.get("polygons"), dict) else []
            geom = {"type": "Polygon", "coordinates": rings} if rings else None
            normalized.append({
                "id": str(ev.get("identifier") or ev.get("id") or ""),
                "provider": "Seattle City Light",
                "provider_code": "SCL",
                "customers_affected": int(ev.get("numPeople", 0) or 0),
                "status": ev.get("status") or "Active",
                "cause": ev.get("cause") or "Under Investigation",
                "est_restoration": None,
                "latitude": float(lat),
                "longitude": float(lon),
                "geometry": geom
            })

        condition = "elevated" if (count > 5 or customers > 1000) else ("localized" if count > 0 else "optimal")
        label = "Elevated Outages" if condition == "elevated" else ("Localized Incidents" if count > 0 else "Grid Optimal")

        return {
            "status": "online",
            "name": "Seattle City Light",
            "provider_code": "SCL",
            "active_incidents": count,
            "customers_affected": customers,
            "status_label": label,
            "grid_condition": condition,
            "events": event_list
        }, normalized
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
        }, normalized


def ingest_pse():
    url = "https://www.pse.com/api/sitecore/OutageMap/AnonymoussMapListView"
    normalized = []
    try:
        data = fetch_json(url)
        incidents = data.get("PseMap", [])
        common = data.get("Common", {})
        count = common.get("OutageCount", len(incidents))
        customers = common.get("CustsOut", 0)
        tallied_customers = 0

        for inc in incidents:
            dp = inc.get("DataProvider", {})
            poi = dp.get("PointOfInterest", {})
            attrs = {a.get("Name"): a.get("Value") for a in dp.get("Attributes", [])}

            raw_cust = str(attrs.get("Customers impacted", "0")).replace(",", "").strip()
            try:
                c_num = int(raw_cust)
            except ValueError:
                c_num = 0
            tallied_customers += c_num

            lat_raw = poi.get("Latitude")
            lon_raw = poi.get("Longitude")
            if lat_raw is None or lon_raw is None:
                continue

            poly_pts = inc.get("Polygon", [])
            ring = []
            for pt in poly_pts:
                try:
                    ring.append([float(pt["Longitude"]), float(pt["Latitude"])])
                except (KeyError, ValueError, TypeError):
                    continue
            geom = {"type": "Polygon", "coordinates": [ring]} if len(ring) >= 3 else None

            normalized.append({
                "id": str(poi.get("Id") or attrs.get("Outage ID") or ""),
                "provider": "Puget Sound Energy",
                "provider_code": "PSE",
                "customers_affected": c_num,
                "status": attrs.get("Status") or "Outage reported",
                "cause": attrs.get("Cause") or "Under investigation",
                "est_restoration": attrs.get("Est. restoration time"),
                "latitude": float(lat_raw),
                "longitude": float(lon_raw),
                "geometry": geom
            })

        if not customers:
            customers = tallied_customers

        condition = "elevated" if (count > 5 or customers > 1000) else ("localized" if count > 0 else "optimal")
        label = "Elevated Outages" if condition == "elevated" else ("Localized Incidents" if count > 0 else "Grid Optimal")

        return {
            "status": "online",
            "name": "Puget Sound Energy",
            "provider_code": "PSE",
            "active_incidents": count,
            "customers_affected": customers,
            "status_label": label,
            "grid_condition": condition,
            "incidents": incidents
        }, normalized
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
        }, normalized


def ingest_snopud():
    url = "https://outage-pmtiles-prod-cntr.whiteplant-5e2d905c.westus2.azurecontainerapps.io/incidents/8/41/88.mvt"
    try:
        req = urllib.request.Request(url, headers=HTTP_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            status_code = resp.getcode()
            content = resp.read()
            count = 0 if status_code == 204 or len(content) == 0 else 1

        return {
            "status": "online",
            "name": "Snohomish County PUD",
            "provider_code": "SNOPUD",
            "active_incidents": count,
            "customers_affected": 0,
            "status_label": "Localized Incidents" if count > 0 else "Grid Optimal",
            "grid_condition": "localized" if count > 0 else "optimal"
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


def map_outages_to_cities(cities: list, incidents: list) -> dict:
    city_map = {}
    for c in cities:
        matched = []
        for inc in incidents:
            ilat, ilon = inc["latitude"], inc["longitude"]
            in_poly = point_in_geometry(ilon, ilat, c.get("geometry"))
            near_center = haversine_miles(c["lat"], c["lon"], ilat, ilon) <= 3.0
            if in_poly or near_center:
                matched.append(inc)

        city_map[c["slug"]] = {
            "active_incidents": len(matched),
            "customers_affected": sum(m["customers_affected"] for m in matched),
            "incidents": matched
        }
    return city_map


def main():
    print(f"[{datetime.now(timezone.utc).isoformat()}] Polling regional utility feeds...")
    scl, scl_incidents = ingest_scl()
    pse, pse_incidents = ingest_pse()
    snopud = ingest_snopud()

    all_incidents = scl_incidents + pse_incidents
    cities = load_city_spatial_index()
    city_outages = map_outages_to_cities(cities, all_incidents)

    payload = {
        "metadata": {
            "updated_utc": datetime.now(timezone.utc).isoformat(),
            "region": "Puget Sound",
            "providers_monitored": ["SCL", "PSE", "SNOPUD"],
            "total_normalized_incidents": len(all_incidents)
        },
        "utilities": {
            "SCL": scl,
            "PSE": pse,
            "SNOPUD": snopud
        },
        "incidents": all_incidents,
        "cities": city_outages
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"), ensure_ascii=False)
    print(f"Saved power outage snapshot -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
