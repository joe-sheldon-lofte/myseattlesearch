# File: scripts/cms_harvester.py
import os
import json
import datetime
import requests

def find_project_root(start_path):
    """Scans upward to find the project root dynamically to locate the data/ directory."""
    curr = os.path.dirname(os.path.abspath(start_path))
    for _ in range(5):
        if os.path.exists(os.path.join(curr, ".eleventy.js")) or os.path.exists(os.path.join(curr, "package.json")):
            return curr
        parent = os.path.dirname(curr)
        if parent == curr:
            break
        curr = parent
    return os.path.dirname(os.path.dirname(os.path.abspath(start_path)))

BASE_DIR = find_project_root(__file__)
DATA_DIR = os.path.join(BASE_DIR, "data")
DEV_VARS_PATH = os.path.join(BASE_DIR, ".dev.vars")

def load_dev_vars(filepath):
    if not os.path.exists(filepath):
        return
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip().strip("'").strip('"')

load_dev_vars(DEV_VARS_PATH)

def query_d1(account_id, database_id, api_token, sql_query):
    """Executes a SQL query against Cloudflare D1 via the HTTP API."""
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{database_id}/query"
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json"
    }
    payload = {"sql": sql_query}
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        if data.get("success") and data.get("result"):
            return data["result"][0].get("results", [])
        else:
            print(f"   ❌ D1 Query failed: {data.get('errors')}")
            return []
    except Exception as e:
        print(f"   ❌ D1 Request Exception: {e}")
        return []

def format_json_output(rows):
    """Parses nested stringified JSON arrays (images, attachments, cities, etc.) back into native Python lists."""
    formatted_rows = []
    for row in rows:
        formatted_row = {}
        for key, value in row.items():
            if isinstance(value, str) and value.startswith("[") and value.endswith("]"):
                try:
                    formatted_row[key] = json.loads(value)
                except json.JSONDecodeError:
                    formatted_row[key] = value
            else:
                formatted_row[key] = value
        formatted_rows.append(formatted_row)
    return formatted_rows

def get_local_watermarks(filepath):
    """Reads the existing JSON file to determine record count, newest, and oldest timestamps."""
    if not os.path.exists(filepath):
        return {"count": 0, "max_date": None, "min_date": None}
    
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        if not data or not isinstance(data, list):
            return {"count": 0, "max_date": None, "min_date": None}
            
        dates = [r.get("published_at") for r in data if r.get("published_at")]
        if not dates:
            return {"count": len(data), "max_date": None, "min_date": None}
            
        return {
            "count": len(data),
            "max_date": max(dates),
            "min_date": min(dates)
        }
    except Exception:
        return {"count": 0, "max_date": None, "min_date": None}

def sync_table(account_id, database_id, api_token, table_name, active_rules_sql, json_filename):
    """Handles the high-water mark check and payload extraction for a specific D1 table."""
    print(f"   📡 Inspecting {table_name}...")
    filepath = os.path.join(DATA_DIR, json_filename)
    
    # Tier 1: High-Water Mark Pre-Flight
    local_marks = get_local_watermarks(filepath)
    
    preflight_query = f"""
        SELECT 
            COUNT(*) AS total_count, 
            MAX(published_at) AS latest_post,
            MIN(published_at) AS oldest_post
        FROM {table_name} 
        WHERE {active_rules_sql};
    """
    
    preflight_result = query_d1(account_id, database_id, api_token, preflight_query)
    
    if preflight_result:
        d1_count = preflight_result[0].get("total_count", 0)
        d1_max = preflight_result[0].get("latest_post")
        d1_min = preflight_result[0].get("oldest_post")
        
        # Check if D1 metadata exactly matches our local JSON metadata
        if (d1_count == local_marks["count"] and 
            d1_max == local_marks["max_date"] and 
            d1_min == local_marks["min_date"]):
            print(f"      ℹ️ {table_name} unchanged (Count: {d1_count}). Skipping download.")
            return

    # If mismatch (new post, edit, or expiration), fetch the full active payload
    print(f"      ⚡ Change detected in {table_name}. Fetching active rows...")
    full_query = f"SELECT * FROM {table_name} WHERE {active_rules_sql} ORDER BY published_at DESC;"
    rows = query_d1(account_id, database_id, api_token, full_query)
    
    if rows is not None:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(format_json_output(rows), f, indent=2, ensure_ascii=False)
        print(f"      💾 Saved: data/{json_filename} ({len(rows)} records)")
    else:
        print(f"      ⚠️ Warning: Failed to extract rows for {table_name}.")

def main():
    print("🚀 Starting Cloudflare D1 -> SSG JSON Ingestion...")
    os.makedirs(DATA_DIR, exist_ok=True)

    account_id = os.environ.get("CF_ACCOUNT_ID")
    database_id = os.environ.get("CF_DATABASE_CMS_ID")
    api_token = os.environ.get("CF_API_TOKEN")

    if not all([account_id, database_id, api_token]):
        print("❌ Missing Cloudflare D1 credentials (CF_ACCOUNT_ID, CF_DATABASE_CMS_ID, CF_API_TOKEN). Exiting.")
        return

    # 1. Real-Time News (30 days active OR is_evergreen = 1)
    news_rules = """hold_status = 'active' AND is_indexable = 1 AND archive = 0 AND (is_evergreen = 1 OR published_at >= datetime('now', '-30 days'))"""
    sync_table(account_id, database_id, api_token, "real_time_news", news_rules, "cms_news.json")

    # 2. Notebook (180 days active OR is_evergreen = 1)
    notebook_rules = """hold_status = 'active' AND is_indexable = 1 AND archive = 0 AND (is_evergreen = 1 OR published_at >= datetime('now', '-180 days'))"""
    sync_table(account_id, database_id, api_token, "notebook", notebook_rules, "cms_notebook.json")

    # 3. Travel Planning (All Active/Evergreen default)
    travel_rules = """hold_status = 'active' AND is_indexable = 1 AND archive = 0"""
    sync_table(account_id, database_id, api_token, "travel", travel_rules, "cms_travel.json")

    print("✅ D1 Harvester complete.")

if __name__ == "__main__":
    main()