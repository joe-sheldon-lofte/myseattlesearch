import os
import json
import urllib.request
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
CITY_DATA_PATH = os.path.join(DATA_DIR, "city_data.json")
CITY_BOUNDARIES_PATH = os.path.join(DATA_DIR, "city_boundaries.json")
OUT_PATH = os.path.join(DATA_DIR, "city_traffic_cams.json")

def slugify(text):
    if not text: return ""
    text = str(text).lower().strip()
    out = [ch if ch.isalnum() else '-' for ch in text]
    res = "".join(out)
    while '--' in res: res = res.replace('--', '-')
    return res.strip('-')

def http_get_json_simple(url, timeout=25):
    headers = {"User-Agent": "Mozilla/5.0"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"HTTP GET Error [{url[:60]}...]: {e}")
    return None

def get_geometry_bbox(geometry):
    g_type, coords = geometry.get("type"), geometry.get("coordinates", [])
    all_pts = []
    if g_type == "Polygon":
        for ring in coords: all_pts.extend(ring)
    elif g_type == "MultiPolygon":
        for poly in coords:
            for ring in poly: all_pts.extend(ring)
    if not all_pts: return None
    return (min(pt[1] for pt in all_pts), min(pt[0] for pt in all_pts), max(pt[1] for pt in all_pts), max(pt[0] for pt in all_pts))

def point_in_ring(lat, lon, ring):
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        intersect = ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-12) + xi)
        if intersect: inside = not inside
        j = i
    return inside

def point_in_geometry(lat, lon, geometry):
    g_type, coords = geometry.get("type"), geometry.get("coordinates", [])
    if g_type == "Polygon":
        if coords and point_in_ring(lat, lon, coords[0]):
            return not any(point_in_ring(lat, lon, hole) for hole in coords[1:])
    elif g_type == "MultiPolygon":
        for poly in coords:
            if poly and point_in_ring(lat, lon, poly[0]):
                if not any(point_in_ring(lat, lon, hole) for hole in poly[1:]):
                    return True
    return False

def load_city_boundaries():
    if not os.path.exists(CITY_BOUNDARIES_PATH): return []
    with open(CITY_BOUNDARIES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    indexed = []
    for feat in data.get("features", []):
        props = feat.get("properties", {})
        slug = props.get("slug") or slugify(props.get("name") or "")
        bbox = get_geometry_bbox(feat.get("geometry", {}))
        if slug and bbox:
            indexed.append({"slug": slug, "bbox": bbox, "geometry": feat.get("geometry", {})})
    return indexed

def match_city_for_point(lat, lon, city_boundaries):
    for city in city_boundaries:
        bbox = city["bbox"]
        if bbox[0] <= lat <= bbox[2] and bbox[1] <= lon <= bbox[3]:
            if point_in_geometry(lat, lon, city["geometry"]):
                return city["slug"]
    return None

def main():
    print("📹 Harvesting Live Multi-Agency Traffic Cameras (WSDOT & SDOT)...")
    if not os.path.exists(CITY_DATA_PATH):
        print("ℹ️ city_data.json missing. Skipping traffic cams harvest.")
        return

    with open(CITY_DATA_PATH, "r", encoding="utf-8") as f:
        raw_cities = json.load(f)

    items = raw_cities if isinstance(raw_cities, list) else list(raw_cities.values())
    cities = [{"slug": slugify(it.get("City") or it.get("name") or ""), "name": str(it.get("City") or it.get("name") or "").strip()} for it in items if it.get("City") or it.get("name")]
    
    city_boundaries = load_city_boundaries()
    wsdot_code = os.environ.get("WSDOT_ACCESS_CODE", "").strip().strip("'").strip('"')
    city_map = {c["slug"]: {"name": c["name"], "cameras": []} for c in cities}
    total_found = 0

    # 1. WSDOT Cameras
    if wsdot_code:
        wsdot_url = f"https://wsdot.wa.gov/Traffic/api/HighwayCameras/HighwayCamerasREST.svc/GetCamerasAsJson?AccessCode={wsdot_code}"
        cams = http_get_json_simple(wsdot_url)
        if cams and isinstance(cams, list):
            for cam in cams:
                try:
                    clat = float(cam.get("CameraLocation", {}).get("Latitude"))
                    clon = float(cam.get("CameraLocation", {}).get("Longitude"))
                except (ValueError, TypeError): continue
                    
                cam_id = f"wsdot-{cam.get('CameraID')}"
                title = cam.get("Title") or cam.get("CameraOwner") or "WSDOT Camera"
                matched_slug = match_city_for_point(clat, clon, city_boundaries)
                if matched_slug and matched_slug in city_map:
                    city_map[matched_slug]["cameras"].append({
                        "id": cam_id, "title": title, "agency": "WSDOT",
                        "direction": cam.get("Direction", ""), "latitude": clat, "longitude": clon,
                        "image_url": cam.get("ImageURL", "")
                    })
                    total_found += 1

    # 2. SDOT Cameras
    sdot_res = http_get_json_simple("https://web6.seattle.gov/Travelers/api/Map/GetMapData")
    if sdot_res and isinstance(sdot_res, dict) and "Features" in sdot_res:
        for feat in sdot_res.get("Features", []):
            coords = feat.get("PointCoordinate") or []
            if len(coords) < 2: continue
            clat, clon = float(coords[0]), float(coords[1])
            
            for c_idx, cam in enumerate(feat.get("Cameras") or []):
                cam_id = f"sdot-{cam.get('Id') or c_idx}"
                title = cam.get("Description") or "SDOT Camera"
                img_url = cam.get("ImageUrl", "")
                if img_url and not img_url.startswith("http"):
                    img_url = f"https://www.seattle.gov/trafficers/images/{img_url}"
                    
                matched_slug = match_city_for_point(clat, clon, city_boundaries)
                if matched_slug and matched_slug in city_map:
                    city_map[matched_slug]["cameras"].append({
                        "id": cam_id, "title": title, "agency": "SDOT", "direction": "",
                        "latitude": clat, "longitude": clon, "image_url": img_url
                    })
                    total_found += 1

    output = {
        slug: {"name": details["name"], "camera_count": len(details["cameras"]), "cameras": details["cameras"], "last_updated": datetime.now(timezone.utc).isoformat()}
        for slug, details in city_map.items()
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"💾 Saved {total_found} active live traffic cameras to {OUT_PATH}")

if __name__ == "__main__":
    main()