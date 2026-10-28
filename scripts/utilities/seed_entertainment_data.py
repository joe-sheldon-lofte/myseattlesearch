import os
import sys
import gzip
import json
import time
import datetime
import requests

# ------------------------------------------------------------------------------
# 1. CLOUDFLARE D1 CLIENT & ENVIRONMENT SETUP
# ------------------------------------------------------------------------------
CF_ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID")
CF_DATABASE_ID = os.getenv("CF_DATABASE_ENTERTAINMENT_ID") or os.getenv("CF_DATABASE_ID")
CF_API_TOKEN = os.getenv("CF_API_TOKEN")

if not all([CF_ACCOUNT_ID, CF_DATABASE_ID, CF_API_TOKEN]):
    print("❌ [Actor Seed] Missing required Cloudflare environment variables:")
    print(f"   CF_ACCOUNT_ID: {'✓' if CF_ACCOUNT_ID else 'MISSING'}")
    print(f"   CF_DATABASE_ENTERTAINMENT_ID: {'✓' if CF_DATABASE_ID else 'MISSING'}")
    print(f"   CF_API_TOKEN: {'✓' if CF_API_TOKEN else 'MISSING'}")
    sys.exit(1)

D1_API_URL = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/d1/database/{CF_DATABASE_ID}/query"
D1_HEADERS = {
    "Authorization": f"Bearer {CF_API_TOKEN}",
    "Content-Type": "application/json"
}

def execute_d1_query(sql, params=None, retries=3):
    """Executes a single SQL query against Cloudflare D1 via the REST API with retry."""
    payload = {"sql": sql}
    if params:
        payload["params"] = params

    for attempt in range(1, retries + 1):
        try:
            response = requests.post(D1_API_URL, headers=D1_HEADERS, json=payload, timeout=45)
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    return data.get("result", [])
                print(f"⚠️ D1 execution failure (attempt {attempt}): {data.get('errors')}")
            else:
                print(f"⚠️ D1 HTTP {response.status_code} (attempt {attempt}): {response.text[:200]}")
        except Exception as e:
            print(f"⚠️ D1 request exception (attempt {attempt}): {e}")
        time.sleep(2 * attempt)

    raise RuntimeError(f"D1 Query failed permanently after {retries} attempts.")

def execute_d1_batch(sql_statements, batch_size=40):
    """Batches multiple SQL statements into single D1 calls with throttling."""
    if not sql_statements:
        return
    for i in range(0, len(sql_statements), batch_size):
        chunk = sql_statements[i:i + batch_size]
        combined_sql = ";\n".join(chunk) + ";"
        execute_d1_query(combined_sql)
        time.sleep(0.1)

def escape_sql(value):
    """Safely escapes strings for SQL literal insertion."""
    if value is None:
        return "NULL"
    clean = str(value).replace("'", "''")
    return f"'{clean}'"

# ------------------------------------------------------------------------------
# 2. SCHEMA VERIFICATION
# ------------------------------------------------------------------------------
def ensure_schema():
    print("📦 Verifying D1 actors table schema...")
    schema_stmts = [
        """CREATE TABLE IF NOT EXISTS actors (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            imdb_id TEXT,
            tmdb_id TEXT,
            known_for TEXT,
            image_url TEXT
        )""",
        "CREATE INDEX IF NOT EXISTS idx_actors_name ON actors(name)"
    ]

    for stmt in schema_stmts:
        execute_d1_query(stmt)
    print("✅ Schema verified.\n")

# ------------------------------------------------------------------------------
# 3. TMDB TOP NOTABLE ACTORS HARVEST
# ------------------------------------------------------------------------------
def harvest_top_actors(min_popularity=5.0):
    print(f"🎭 Harvesting Top Notable Persons from TMDb (min_popularity >= {min_popularity})...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Encoding": "gzip, deflate"
    }

    decompressed_data = None
    now = datetime.datetime.now(datetime.timezone.utc)
    for days_back in range(3):
        date_str = (now - datetime.timedelta(days=days_back)).strftime("%m_%d_%Y")
        url = f"https://files.tmdb.org/p/exports/person_ids_{date_str}.json.gz"
        print(f"   Checking TMDb person export for {date_str}...")

        try:
            res = requests.get(url, headers=headers, timeout=45)
            if res.status_code == 200 and len(res.content) > 1000:
                print(f"   ✅ Found active export ({len(res.content) / 1024 / 1024:.2f} MB). Decompressing...")
                decompressed_data = gzip.decompress(res.content).decode("utf-8")
                break
            else:
                print(f"   ⚠️ Export {date_str} returned HTTP {res.status_code}")
        except Exception as e:
            print(f"   ⚠️ Request error for {date_str}: {e}")

    if not decompressed_data:
        print("❌ Could not download TMDb person export file.\n")
        return

    statements = []
    total_parsed = 0
    matched_actors = 0

    print("   Parsing records and filtering by popularity...")
    for line in decompressed_data.splitlines():
        if not line.strip():
            continue
        total_parsed += 1

        try:
            item = json.loads(line)
        except Exception:
            continue

        pop = float(item.get("popularity", 0))
        # Daily person export fields: {"id": int, "name": str, "popularity": float, "adult": bool}
        if not item.get("adult") and pop >= min_popularity:
            p_id = str(item["id"])
            name = item.get("name", "Unknown")

            statements.append(
                f"INSERT OR IGNORE INTO actors (id, name, tmdb_id, known_for) "
                f"VALUES ('tmdb_{p_id}', {escape_sql(name)}, {escape_sql(p_id)}, 'Popularity: {pop:.1f}')"
            )
            matched_actors += 1

    print(f"   Parsed {total_parsed:,} total persons.")
    print(f"   Matched {matched_actors:,} profiles meeting popularity threshold.")

    if statements:
        print(f"   Inserting {len(statements):,} actors into Cloudflare D1...")
        execute_d1_batch(statements, batch_size=50)
        print("✅ Finished inserting actors into D1.\n")
    else:
        print("⚠️ No actors matched your filter criteria.\n")

# ------------------------------------------------------------------------------
# 4. MAIN CONTROLLER
# ------------------------------------------------------------------------------
def main():
    print("==================================================")
    print("          SEED ENTERTAINMENT ACTORS               ")
    print("==================================================")
    print()
    
    ensure_schema()
    harvest_top_actors(min_popularity=5.0)

    print("🎉 Actor ingestion complete!")

if __name__ == "__main__":
    main()