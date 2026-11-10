import os
import sys
import gzip
import json
import time
import heapq
import datetime
import requests

# ------------------------------------------------------------------------------
# 1. CLOUDFLARE D1 CLIENT SETUP
# ------------------------------------------------------------------------------
CF_ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID")
CF_DATABASE_ID = os.getenv("CF_DATABASE_ENTERTAINMENT_ID") or os.getenv("CF_DATABASE_ID")
CF_API_TOKEN = os.getenv("CF_API_TOKEN")

if not all([CF_ACCOUNT_ID, CF_DATABASE_ID, CF_API_TOKEN]):
    print("❌ [Weekly Entertainment] Missing Cloudflare D1 environment variables.")
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

def parse_duration(val):
    if not val:
        return None
    try:
        cleaned = "".join(ch for ch in str(val) if ch.isdigit() or ch == ".")
        return int(float(cleaned)) if cleaned else None
    except (ValueError, TypeError):
        return None

# ------------------------------------------------------------------------------
# 2. SCHEMA VERIFICATION
# ------------------------------------------------------------------------------
def ensure_schema():
    print("📦 Verifying entertainment and rankings schema...")
    schema_stmts = [
        """CREATE TABLE IF NOT EXISTS rankings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            media_type TEXT NOT NULL,
            tmdb_id TEXT NOT NULL,
            rank INTEGER NOT NULL,
            popularity REAL NOT NULL,
            title TEXT NOT NULL,
            updated_at INTEGER NOT NULL,
            UNIQUE(media_type, rank)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_rankings_lookup ON rankings(media_type, rank)",
        "CREATE INDEX IF NOT EXISTS idx_rankings_tmdb ON rankings(tmdb_id)"
    ]
    for stmt in schema_stmts:
        execute_d1_query(stmt)
    print("✅ Schema verified.\n")

# ------------------------------------------------------------------------------
# 3. TMDB POPULARITY RANKINGS INGESTION (TOP 250)
# ------------------------------------------------------------------------------
def fetch_tmdb_export(file_prefix):
    """Downloads and decompresses the latest available TMDb daily export."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)",
        "Accept-Encoding": "gzip, deflate"
    }
    now = datetime.datetime.now(datetime.timezone.utc)
    for days_back in range(3):
        date_str = (now - datetime.timedelta(days=days_back)).strftime("%m_%d_%Y")
        url = f"https://files.tmdb.org/p/exports/{file_prefix}_{date_str}.json.gz"
        try:
            res = requests.get(url, headers=headers, timeout=45)
            if res.status_code == 200 and len(res.content) > 1000:
                print(f"   ✓ Downloaded {file_prefix} for {date_str} ({len(res.content) / 1024 / 1024:.2f} MB)")
                return gzip.decompress(res.content).decode("utf-8")
        except Exception as e:
            print(f"   ⚠️ Could not fetch {file_prefix} for {date_str}: {e}")
    return None

def update_tmdb_rankings(top_n=250):
    print(f"🏆 Harvesting Weekly TMDb Popularity Rankings (Top {top_n})...")
    timestamp = int(time.time())

    categories = [
        {"type": "movie", "prefix": "movie_ids", "title_key": "original_title"},
        {"type": "tv", "prefix": "tv_series_ids", "title_key": "original_name"},
        {"type": "actor", "prefix": "person_ids", "title_key": "name"}
    ]

    for cat in categories:
        media_type = cat["type"]
        raw_data = fetch_tmdb_export(cat["prefix"])
        if not raw_data:
            print(f"❌ Failed to obtain export for {media_type}. Skipping.")
            continue

        def parse_generator():
            for line in raw_data.splitlines():
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                    if not item.get("adult"):
                        pop = float(item.get("popularity", 0))
                        tmdb_id = str(item.get("id"))
                        title = item.get(cat["title_key"]) or item.get("name") or "Unknown"
                        yield (pop, tmdb_id, title)
                except Exception:
                    continue

        # Extract the highest popularity scores in a single streaming pass
        top_items = heapq.nlargest(top_n, parse_generator(), key=lambda x: x[0])
        print(f"   Processing top {len(top_items)} {media_type} items...")

        # Purge existing rankings for this category
        execute_d1_query(f"DELETE FROM rankings WHERE media_type = '{media_type}';")

        rankings_stmts = []
        actor_sync_stmts = []

        for idx, (pop, tmdb_id, title) in enumerate(top_items, start=1):
            rankings_stmts.append(
                f"INSERT INTO rankings (media_type, tmdb_id, rank, popularity, title, updated_at) "
                f"VALUES ('{media_type}', {escape_sql(tmdb_id)}, {idx}, {pop}, {escape_sql(title)}, {timestamp})"
            )
            # Ensure trending actors exist in the primary actors table
            if media_type == "actor":
                actor_sync_stmts.append(
                    f"INSERT OR IGNORE INTO actors (id, name, tmdb_id, known_for) "
                    f"VALUES ('tmdb_{tmdb_id}', {escape_sql(title)}, {escape_sql(tmdb_id)}, 'Trending Rank #{idx}')"
                )

        execute_d1_batch(rankings_stmts)
        if actor_sync_stmts:
            execute_d1_batch(actor_sync_stmts)

        print(f"✅ Updated top {len(top_items)} {media_type} rankings in D1.")

    print("🎉 All weekly rankings successfully refreshed.\n")

# ------------------------------------------------------------------------------
# 4. RECENT & NEW THEATRICAL/STREAMING RELEASES HARVEST
# ------------------------------------------------------------------------------
def harvest_recent_movie_releases():
    """Queries Wikidata for movies released in the last 60 days to keep the catalog fresh."""
    today = datetime.date.today()
    start_date = (today - datetime.timedelta(days=60)).isoformat()
    current_year = today.year

    print(f"🎬 Checking for newly released movies since {start_date}...")
    wdqs_endpoint = "https://query.wikidata.org/sparql"
    headers = {
        "User-Agent": "SeattleSearchWeeklyMaintenance/1.0 (contact: admin@myseattlesearch.com)",
        "Accept": "application/sparql-results+json"
    }

    sparql = f"""
    SELECT ?film ?title ?year ?directorName ?duration ?genreName ?tmdbId ?imdbId WHERE {{
      ?film wdt:P31 wd:Q11424;
            wdt:P4947 ?tmdbId;
            wdt:P577 ?releaseDate;
            rdfs:label ?title.
      FILTER(?releaseDate >= "{start_date}T00:00:00Z"^^xsd:dateTime)
      FILTER(LANG(?title) = "en")
      BIND(YEAR(?releaseDate) AS ?year)

      OPTIONAL {{ 
        ?film wdt:P57 ?director. 
        ?director rdfs:label ?directorName. 
        FILTER(LANG(?directorName) = "en") 
      }}
      OPTIONAL {{ 
        ?film wdt:P136 ?genre. 
        ?genre rdfs:label ?genreName. 
        FILTER(LANG(?genreName) = "en") 
      }}
      OPTIONAL {{ ?film wdt:P2047 ?duration. }}
      OPTIONAL {{ ?film wdt:P345 ?imdbId. }}
    }}
    LIMIT 1000
    """

    try:
        res = requests.get(wdqs_endpoint, params={"query": sparql}, headers=headers, timeout=50)
        if res.status_code != 200:
            print(f"⚠️ Wikidata returned HTTP {res.status_code}")
            return

        bindings = res.json().get("results", {}).get("bindings", [])
        movies_dict = {}

        for row in bindings:
            qid = row["film"]["value"].split("/")[-1]
            if qid not in movies_dict:
                duration_val = parse_duration(row.get("duration", {}).get("value"))
                movies_dict[qid] = {
                    "id": qid,
                    "title": row["title"]["value"],
                    "year": int(row.get("year", {}).get("value", current_year)),
                    "director": row.get("directorName", {}).get("value"),
                    "runtime": duration_val,
                    "genres": row.get("genreName", {}).get("value"),
                    "tmdb_id": row.get("tmdbId", {}).get("value"),
                    "imdb_id": row.get("imdbId", {}).get("value")
                }

        stmts = []
        for m in movies_dict.values():
            runtime_val = m["runtime"] if m["runtime"] is not None else "NULL"
            stmts.append(
                f"INSERT OR REPLACE INTO movies (id, title, release_year, director, runtime, genres, tmdb_id, imdb_id) "
                f"VALUES ({escape_sql(m['id'])}, {escape_sql(m['title'])}, {m['year']}, "
                f"{escape_sql(m['director'])}, {runtime_val}, {escape_sql(m['genres'])}, "
                f"{escape_sql(m['tmdb_id'])}, {escape_sql(m['imdb_id'])})"
            )

        if stmts:
            execute_d1_batch(stmts)
            print(f"✅ Upserted {len(stmts)} recent movie titles into D1.\n")
        else:
            print("✓ Movie catalog is already up to date.\n")

    except Exception as e:
        print(f"⚠️ Error harvesting recent movies: {e}\n")

# ------------------------------------------------------------------------------
# 5. ENTRY POINT
# ------------------------------------------------------------------------------
def main():
    print("==================================================")
    print("    WEEKLY ENTERTAINMENT & RANKINGS HARVESTER     ")
    print("==================================================")
    print()

    ensure_schema()
    update_tmdb_rankings(top_n=250)
    harvest_recent_movie_releases()

    print("🎉 Weekly entertainment maintenance complete!")

if __name__ == "__main__":
    main()