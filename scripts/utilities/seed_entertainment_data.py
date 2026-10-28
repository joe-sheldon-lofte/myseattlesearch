import os
import sys
import gzip
import json
import requests
import datetime
import time

# ------------------------------------------------------------------------------
# 1. CLOUDFLARE D1 SETUP
# ------------------------------------------------------------------------------
CF_ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID")
CF_DATABASE_ID = os.getenv("CF_DATABASE_ENTERTAINMENT_ID") or os.getenv("CF_DATABASE_ID")
CF_API_TOKEN = os.getenv("CF_API_TOKEN")

if not all([CF_ACCOUNT_ID, CF_DATABASE_ID, CF_API_TOKEN]):
    print("❌ Missing Cloudflare environment variables.")
    sys.exit(1)

D1_API_URL = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/d1/database/{CF_DATABASE_ID}/query"
D1_HEADERS = {
    "Authorization": f"Bearer {CF_API_TOKEN}",
    "Content-Type": "application/json"
}

def execute_d1_batch(sql_statements, batch_size=40):
    if not sql_statements:
        return
    for i in range(0, len(sql_statements), batch_size):
        chunk = sql_statements[i:i + batch_size]
        combined = ";\n".join(chunk) + ";"
        res = requests.post(D1_API_URL, headers=D1_HEADERS, json={"sql": combined}, timeout=30)
        
        if res.status_code != 200:
            print(f"❌ D1 HTTP Error {res.status_code}: {res.text[:200]}")
            continue
            
        data = res.json()
        if not data.get("success"):
            print(f"❌ D1 Query Failed: {data.get('errors')}")

def escape_sql(value):
    if value is None:
        return "NULL"
    clean = str(value).replace("'", "''")
    return f"'{clean}'"

# ------------------------------------------------------------------------------
# 2. TMDB DAILY PERSON HARVEST
# ------------------------------------------------------------------------------
def harvest_top_actors(min_popularity=3.0):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Encoding": "gzip, deflate"
    }

    # Try today, yesterday, and 2 days ago to locate the latest build
    decompressed_data = None
    successful_date = None

    now = datetime.datetime.now(datetime.timezone.utc)
    for days_back in range(3):
        date_str = (now - datetime.timedelta(days=days_back)).strftime("%m_%d_%Y")
        url = f"http://files.tmdb.org/p/exports/person_ids_{date_str}.json.gz"
        print(f"🔍 Checking TMDb export for {date_str} ({url})...")
        
        try:
            res = requests.get(url, headers=headers, timeout=40)
            if res.status_code == 200 and len(res.content) > 1000:
                print(f"✅ Found active export for {date_str}! (Size: {len(res.content) / 1024 / 1024:.2f} MB)")
                decompressed_data = gzip.decompress(res.content).decode("utf-8")
                successful_date = date_str
                break
            else:
                print(f"   ⚠️ Date {date_str} returned HTTP {res.status_code}")
        except Exception as e:
            print(f"   ⚠️ Request error for {date_str}: {e}")

    if not decompressed_data:
        print("❌ Could not download any TMDb person export file.")
        return

    statements = []
    total_parsed = 0
    matched_actors = 0

    print("⚙️ Parsing and filtering actors...")
    for line in decompressed_data.splitlines():
        if not line.strip():
            continue
        total_parsed += 1

        try:
            item = json.loads(line)
        except Exception:
            continue

        # Keep non-adult acting profiles meeting the popularity threshold
        pop = float(item.get("popularity", 0))
        if not item.get("adult") and item.get("known_for_department") == "Acting" and pop >= min_popularity:
            p_id = str(item["id"])
            name = item.get("name", "Unknown")

            statements.append(
                f"INSERT OR IGNORE INTO actors (id, name, tmdb_id, known_for) "
                f"VALUES ('tmdb_{p_id}', {escape_sql(name)}, {escape_sql(p_id)}, 'Acting')"
            )
            matched_actors += 1

    print(f"📊 Parsed {total_parsed:,} total persons.")
    print(f"🎯 Matched {matched_actors:,} actors with popularity >= {min_popularity}.")

    if statements:
        print(f"🚀 Inserting {len(statements):,} records into Cloudflare D1...")
        execute_d1_batch(statements)
        print("✅ Finished inserting actors into D1!")
    else:
        print("⚠️ No actors matched your filter criteria.")

if __name__ == "__main__":
    harvest_top_actors(min_popularity=3.0)