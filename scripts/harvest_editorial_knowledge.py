import json
import os
import re

def slugify(text):
    """Normalizes city names into clean, lowercase slugs (e.g., 'Lake Forest Park' -> 'lake-forest-park')."""
    if not text:
        return ""
    s = str(text).lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    return s

def load_json_file(filepath):
    """Safely loads a JSON file, returning None if not found or unparseable."""
    if not os.path.exists(filepath):
        print(f"Warning: File not found -> {filepath}")
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return None

def build_normalized_dict(data):
    """Converts a dict with Title Case or Slug keys into a uniform dictionary keyed by slugified city names."""
    if not isinstance(data, dict):
        return {}
    normalized = {}
    for key, value in data.items():
        slug = slugify(key)
        if slug:
            normalized[slug] = value
    return normalized

def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base_dir, "data")
    output_filepath = os.path.join(data_dir, "master_city_knowledge.json")

    # Primary driver dataset
    raw_city_data = load_json_file(os.path.join(data_dir, "city_data.json")) or []

    # Secondary datasets
    businesses_raw = load_json_file(os.path.join(base_dir, "city_businesses.json")) or load_json_file(os.path.join(data_dir, "city_businesses.json")) or {}
    walk_scores_raw = load_json_file(os.path.join(data_dir, "walk_transit_bike_scores.json")) or {}
    demographics_raw = load_json_file(os.path.join(data_dir, "city_demographics.json")) or {}
    climate_raw = load_json_file(os.path.join(data_dir, "climate_comfort.json")) or {}
    safety_raw = load_json_file(os.path.join(data_dir, "public_safety_emergency.json")) or {}
    schools_raw = load_json_file(os.path.join(data_dir, "school_ratings.json")) or {}
    ev_scores_raw = load_json_file(os.path.join(data_dir, "city_ev_scores.json")) or {}
    amenities_raw = load_json_file(os.path.join(data_dir, "city_amenities.json")) or {}
    surveillance_raw = load_json_file(os.path.join(data_dir, "surveillance_stats.json")) or {}

    # Normalize lookup maps to slugified keys
    businesses = build_normalized_dict(businesses_raw)
    walk_scores = build_normalized_dict(walk_scores_raw)
    demographics = build_normalized_dict(demographics_raw)
    climate = build_normalized_dict(climate_raw)
    safety = build_normalized_dict(safety_raw)
    schools = build_normalized_dict(schools_raw)
    ev_scores = build_normalized_dict(ev_scores_raw)
    amenities = build_normalized_dict(amenities_raw)
    surveillance = build_normalized_dict(surveillance_raw)

    master_knowledge = {}

    for entry in raw_city_data:
        city_name = entry.get("City")
        if not city_name:
            continue

        slug = slugify(city_name)

        # Process health hazards string into a clean list
        hazards_str = entry.get("Health Hazards", "")
        hazards_list = [h.strip() for h in hazards_str.split(",") if h.strip()] if hazards_str else []

        # Extract top Yelp business recommendations
        city_biz_data = businesses.get(slug, {}).get("categories", {})
        top_yelp = {}
        if city_biz_data:
            for cat, items in city_biz_data.items():
                if isinstance(items, list) and items:
                    top_yelp[cat] = [
                        {
                            "name": b.get("name"),
                            "location": b.get("location"),
                            "rating": b.get("rating"),
                            "review_count": b.get("review_count"),
                            "category": b.get("category")
                        }
                        for b in items[:3]
                    ]

        # Extract dataset sub-objects
        demo_data = demographics.get(slug, {})
        walk_data = walk_scores.get(slug, {})
        climate_data = climate.get(slug, {})
        safety_data = safety.get(slug, {})
        school_data = schools.get(slug, {})
        ev_data = ev_scores.get(slug, {})
        amenity_data = amenities.get(slug, {}).get("amenities", {})
        surv_data = surveillance.get(slug, {})

        # Extract expanded mobility scores (Walk, Transit, Bike)
        transit_obj = walk_data.get("transit") or {}
        bike_obj = walk_data.get("bike") or {}

        master_knowledge[slug] = {
            "name": city_name,
            "slug": slug,
            "county": entry.get("County"),
            "region": entry.get("News Region"),
            "is_north_sound": entry.get("North Sound") == "x",
            "coordinates": {
                "latitude": entry.get("Latitude"),
                "longitude": entry.get("Longitude")
            },
            "population": entry.get("FallbackPopulation"),
            "land_area_sq_miles": entry.get("Land Area Square Mileage"),
            "demographics": {
                "median_income": demo_data.get("median_household_income"),
                "median_age": demo_data.get("median_age"),
                "owner_occupied_pct": demo_data.get("owner_occupied_pct"),
                "renter_occupied_pct": demo_data.get("renter_occupied_pct"),
                "remote_worker_pct": demo_data.get("remote_worker_pct")
            },
            "mobility": {
                "walkscore": walk_data.get("walkscore"),
                "walk_description": walk_data.get("description"),
                "transit_score": transit_obj.get("score"),
                "transit_description": transit_obj.get("description"),
                "transit_summary": transit_obj.get("summary"),
                "bike_score": bike_obj.get("score"),
                "bike_description": bike_obj.get("description")
            },
            "climate": {
                "weather_station": climate_data.get("assigned_weather_station"),
                "summer_high_f": climate_data.get("metrics", {}).get("average_summer_high_f"),
                "winter_low_f": climate_data.get("metrics", {}).get("average_winter_low_f"),
                "annual_rainfall_inches": climate_data.get("metrics", {}).get("annual_rainfall_inches"),
                "annual_sunny_days": climate_data.get("metrics", {}).get("annual_sunny_days"),
                "microclimate_summary": climate_data.get("microclimate_summary")
            },
            "civic_and_safety": {
                "police_dept": entry.get("Police Department Name"),
                "fire_dept": entry.get("Fire Department Name"),
                "wsrb_rating": entry.get("FD WSRB Rating"),
                "nearest_hospital": safety_data.get("emergency_medical", {}).get("nearest_hospital_facility"),
                "hospital_distance_miles": safety_data.get("emergency_medical", {}).get("distance_proximity_miles"),
                "hospital_cms_stars": safety_data.get("emergency_medical", {}).get("cms_hospital_quality_rating"),
                "surveillance_score": surv_data.get("surveillance_score")
            },
            "schools": {
                "district_name": entry.get("School District") or school_data.get("district_name"),
                "math_proficiency": school_data.get("district_math_proficiency"),
                "ela_proficiency": school_data.get("district_ela_proficiency"),
                "custom_score": school_data.get("custom_score")
            },
            "ev_charging": {
                "level_2_ports": ev_data.get("level_2_ports"),
                "dc_fast_ports": ev_data.get("dc_fast_ports"),
                "ev_charge_score": ev_data.get("ev_charge_score")
            },
            "amenities": amenity_data,
            "health_hazards": hazards_list,
            "verified_yelp_businesses": top_yelp
        }

    # Output master compiled JSON dataset
    with open(output_filepath, "w", encoding="utf-8") as f:
        json.dump(master_knowledge, f, indent=2, ensure_ascii=False)

    print(f"Successfully compiled master knowledge base for {len(master_knowledge)} cities to {output_filepath}")

if __name__ == "__main__":
    main()