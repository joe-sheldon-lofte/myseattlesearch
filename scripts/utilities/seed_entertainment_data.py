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
    print("❌ Missing required Cloudflare environment variables.")
    sys.exit(1)

D1_API_URL = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/d1/database/{CF_DATABASE_ID}/query"
D1_HEADERS = {
    "Authorization": f"Bearer {CF_API_TOKEN}",
    "Content-Type": "application/json"
}

def execute_d1_query(sql, params=None, retries=3):
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

def execute_d1_batch(sql_statements, batch_size=50):
    if not sql_statements:
        return
    for i in range(0, len(sql_statements), batch_size):
        chunk = sql_statements[i:i + batch_size]
        combined_sql = ";\n".join(chunk) + ";"
        execute_d1_query(combined_sql)
        time.sleep(0.1)

def escape_sql(value):
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
        "CREATE INDEX IF NOT EXISTS idx_actors_name ON actors(name)",
        "CREATE INDEX IF NOT EXISTS idx_actors_tmdb ON actors(tmdb_id)",
        "CREATE INDEX IF NOT EXISTS idx_actors_imdb ON actors(imdb_id)"
    ]
    for stmt in schema_stmts:
        execute_d1_query(stmt)
    print("✅ Schema verified.\n")

# ------------------------------------------------------------------------------
# 3. HARVEST ACTORS VIA WIKIDATA (WITH IMDB ID & IMAGE URL)
# ------------------------------------------------------------------------------
def harvest_wikidata_actors(limit=10000):
    """
    Pulls prominent film actors from Wikidata who have both TMDb and IMDb IDs,
    along with their Wikimedia Commons headshots.
    """
    print(f"🌐 Harvesting up to {limit:,} notable actors with IMDb IDs & photos from Wikidata...")
    wdqs_endpoint = "https://query.wikidata.org/sparql"
    headers = {
        "User-Agent": "SeattleSearchEntertainmentHub/1.0 (contact: admin@myseattlesearch.com)",
        "Accept": "application/sparql-results+json"
    }

    # Query prominent actors ordered by sitelinks (Wikipedia notoriety)
    sparql = f"""
    SELECT ?person ?personLabel ?tmdbId ?imdbId ?image WHERE {{
      ?person wdt:P106 wd:Q33999;       # Occupation: Actor
              wdt:P4947 ?tmdbId;         # Has TMDb Person ID
              wdt:P345 ?imdbId;          # Has IMDb ID
              wikibase:sitelinks ?sitelinks.
      FILTER(?sitelinks > 25)            # High cultural prominence threshold
      OPTIONAL {{ ?person wdt:P18 ?image. }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}
    ORDER BY DESC(?sitelinks)
    LIMIT {limit}
    """

    try:
        res = requests.get(wdqs_endpoint, params={"query": sparql}, headers=headers, timeout=60)
        if res.status_code != 200:
            print(f"⚠️ Wikidata returned HTTP {res.status_code}")
            return

        bindings = res.json().get("results", {}).get("bindings", [])
        print(f"✅ Received {len(bindings):,} actor profiles from Wikidata.")

        statements = []
        for row in bindings:
            qid = row["person"]["value"].split("/")[-1]
            name = row.get("personLabel", {}).get("value", "Unknown")
            tmdb_id = row.get("tmdbId", {}).get("value")
            imdb_id = row.get("imdbId", {}).get("value")
            image_url = row.get("image", {}).get("value")

            statements.append(
                f"INSERT OR REPLACE INTO actors (id, name, imdb_id, tmdb_id, known_for, image_url) "
                f"VALUES ({escape_sql(qid)}, {escape_sql(name)}, {escape_sql(imdb_id)}, "
                f"{escape_sql(tmdb_id)}, 'Acting', {escape_sql(image_url)})"
            )

        print(f"Writing {len(statements):,} actors into D1...")
        execute_d1_batch(statements)
        print("✅ Finished inserting Wikidata actors into D1.\n")

    except Exception as e:
        print(f"❌ Wikidata actor harvest failed: {e}\n")

# ------------------------------------------------------------------------------
# 4. MAIN CONTROLLER
# ------------------------------------------------------------------------------
def main():
    print("==================================================")
    print("       SEED ACTORS: IMDB + IMAGES + TMDB          ")
    print("==================================================")
    print()

    ensure_schema()
    harvest_wikidata_actors(limit=10000)

    print("🎉 Ingestion complete!")

if __name__ == "__main__":
    main()