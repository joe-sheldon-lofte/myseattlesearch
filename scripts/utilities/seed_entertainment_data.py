import os
import sys
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
    print("❌ [Seed Script] Missing required Cloudflare environment variables:")
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
    """Executes a single SQL query against Cloudflare D1 via the REST API with auto-retry."""
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
        time.sleep(0.1)  # Micro-pause to maintain steady D1 rate

def escape_sql(value):
    """Safely escapes strings for SQL insertion."""
    if value is None:
        return "NULL"
    clean = str(value).replace("'", "''")
    return f"'{clean}'"

# ------------------------------------------------------------------------------
# 2. SCHEMA VERIFICATION
# ------------------------------------------------------------------------------
def ensure_schema():
    print("📦 Verifying D1 database schema...")
    schema_stmts = [
        """CREATE TABLE IF NOT EXISTS movies (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            release_year INTEGER,
            director TEXT,
            runtime INTEGER,
            genres TEXT,
            tmdb_id TEXT,
            imdb_id TEXT,
            image_url TEXT
        )""",
        "CREATE INDEX IF NOT EXISTS idx_movies_title ON movies(title)",
        "CREATE INDEX IF NOT EXISTS idx_movies_year ON movies(release_year)",
        "CREATE INDEX IF NOT EXISTS idx_movies_tmdb ON movies(tmdb_id)",

        """CREATE TABLE IF NOT EXISTS shows (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            network TEXT,
            genres TEXT,
            summary TEXT,
            image_url TEXT,
            imdb_id TEXT,
            tmdb_id TEXT
        )""",
        "CREATE INDEX IF NOT EXISTS idx_shows_name ON shows(name)",
        "CREATE INDEX IF NOT EXISTS idx_shows_network ON shows(network)",

        """CREATE TABLE IF NOT EXISTS tv_schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            show_id INTEGER,
            show_name TEXT NOT NULL,
            episode_title TEXT,
            season INTEGER,
            episode_number INTEGER,
            network_callsign TEXT NOT NULL,
            provider TEXT NOT NULL,
            channel_number TEXT NOT NULL,
            air_date TEXT NOT NULL,
            air_time TEXT NOT NULL,
            air_timestamp INTEGER NOT NULL,
            FOREIGN KEY (show_id) REFERENCES shows(id)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_schedule_time ON tv_schedule(air_timestamp)",
        "CREATE INDEX IF NOT EXISTS idx_schedule_provider ON tv_schedule(provider, channel_number)",

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
# 3. FULL BROADCAST TV GUIDE (ALL AVAILABLE US NETWORKS)
# ------------------------------------------------------------------------------
def harvest_full_tv_schedule():
    print("📺 Ingesting Full Broadcast Schedule for All Available US Channels...")
    
    # Purge schedules older than 12 hours ago
    cutoff_ts = int(time.time()) - (12 * 3600)
    execute_d1_query(f"DELETE FROM tv_schedule WHERE air_timestamp < {cutoff_ts};")

    today = datetime.date.today()
    target_dates = [today.isoformat(), (today + datetime.timedelta(days=1)).isoformat()]

    show_stmts = []
    schedule_stmts = []

    for date_str in target_dates:
        url = f"https://api.tvmaze.com/schedule?country=US&date={date_str}"
        print(f"   Fetching US schedule for {date_str}...")
        try:
            res = requests.get(url, timeout=30)
            if res.status_code != 200:
                print(f"   ⚠️ TVmaze returned HTTP {res.status_code} for {date_str}")
                continue
            items = res.json()
        except Exception as e:
            print(f"   ⚠️ Failed fetching schedule for {date_str}: {e}")
            continue

        for item in items:
            show = item.get("show") or {}
            network = show.get("network") or show.get("webChannel") or {}
            network_name = network.get("name") or "Broadcast"

            show_id = show.get("id")
            if not show_id:
                continue

            show_title = show.get("name", "Unknown Title")
            ep_name = item.get("name")
            season = item.get("season") or "NULL"
            number = item.get("number") or "NULL"
            air_time = item.get("airtime") or ""

            try:
                dt = datetime.datetime.fromisoformat(item["airstamp"].replace("Z", "+00:00"))
                air_ts = int(dt.timestamp())
            except Exception:
                air_ts = int(time.time())

            genres = ", ".join(show.get("genres", []))
            image_url = (show.get("image") or {}).get("medium")
            imdb_id = (show.get("externals") or {}).get("imdb")

            show_stmts.append(
                f"INSERT OR IGNORE INTO shows (id, name, network, genres, summary, image_url, imdb_id) "
                f"VALUES ({show_id}, {escape_sql(show_title)}, {escape_sql(network_name)}, {escape_sql(genres)}, "
                f"{escape_sql(show.get('summary'))}, {escape_sql(image_url)}, {escape_sql(imdb_id)})"
            )

            schedule_stmts.append(
                f"INSERT INTO tv_schedule (show_id, show_name, episode_title, season, episode_number, "
                f"network_callsign, provider, channel_number, air_date, air_time, air_timestamp) "
                f"VALUES ({show_id}, {escape_sql(show_title)}, {escape_sql(ep_name)}, {season}, {number}, "
                f"{escape_sql(network_name)}, 'all_broadcast', 'TBD', {escape_sql(date_str)}, "
                f"{escape_sql(air_time)}, {air_ts})"
            )

    print(f"   Writing {len(show_stmts)} shows and {len(schedule_stmts)} schedule items to D1...")
    execute_d1_batch(show_stmts)
    execute_d1_batch(schedule_stmts)
    print("✅ Broadcast schedule ingest complete.\n")

# ------------------------------------------------------------------------------
# 4. TVMAZE BULK SHOWS CATALOG BACKFILL
# ------------------------------------------------------------------------------
def harvest_tvmaze_shows_catalog(max_pages=20):
    """
    Fetches bulk TV shows from TVmaze's paginated directory (250 shows per page).
    Page 0 to 20 covers 5,000 top shows across modern TV history.
    """
    print(f"📺 Backfilling TV Shows catalog from TVmaze (Pages 0 to {max_pages})...")

    for page in range(0, max_pages + 1):
        url = f"https://api.tvmaze.com/shows?page={page}"
        print(f"   Fetching TVmaze shows catalog page {page}...")
        try:
            res = requests.get(url, timeout=30)
            if res.status_code == 404:
                print("   Reached the end of the TVmaze shows catalog.")
                break
            if res.status_code != 200:
                print(f"   ⚠️ TVmaze page {page} returned status {res.status_code}. Sleeping...")
                time.sleep(3)
                continue
            
            shows_data = res.json()
            statements = []
            for show in shows_data:
                show_id = show.get("id")
                if not show_id:
                    continue
                
                network = show.get("network") or show.get("webChannel") or {}
                network_name = network.get("name")
                genres = ", ".join(show.get("genres", []))
                image_url = (show.get("image") or {}).get("medium")
                imdb_id = (show.get("externals") or {}).get("imdb")

                statements.append(
                    f"INSERT OR IGNORE INTO shows (id, name, network, genres, summary, image_url, imdb_id) "
                    f"VALUES ({show_id}, {escape_sql(show.get('name'))}, {escape_sql(network_name)}, "
                    f"{escape_sql(genres)}, {escape_sql(show.get('summary'))}, {escape_sql(image_url)}, {escape_sql(imdb_id)})"
                )

            execute_d1_batch(statements)
            print(f"   Page {page}: Loaded {len(statements)} shows into D1.")
            time.sleep(1.2)  # Respect TVmaze rate guidelines (~20 req/10s)

        except Exception as e:
            print(f"   ❌ Error on TVmaze page {page}: {e}")
            time.sleep(2)

    print("✅ TV Shows catalog backfill complete.\n")

# ------------------------------------------------------------------------------
# 5. 40-YEAR HISTORICAL MOVIES HARVEST (1986–2026)
# ------------------------------------------------------------------------------
def harvest_historical_movies(start_year=1986, end_year=2026):
    print(f"🎬 Harvesting 40-Year Movie Catalog from Wikidata ({start_year} to {end_year})...")
    wdqs_endpoint = "https://query.wikidata.org/sparql"
    headers = {
        "User-Agent": "SeattleSearchEntertainmentBulk/1.0 (contact: admin@myseattlesearch.com)",
        "Accept": "application/sparql-results+json"
    }

    # Loop backward or forward year by year with built-in pauses
    for yr in range(end_year, start_year - 1, -1):
        print(f"   Harvesting movie releases for year {yr}...")
        
        sparql = f"""
        SELECT ?film ?title ?year ?directorName ?duration ?genreName ?tmdbId ?imdbId WHERE {{
          ?film wdt:P31 wd:Q11424;
                wdt:P4947 ?tmdbId;
                wdt:P577 ?releaseDate;
                rdfs:label ?title.
          FILTER(?releaseDate >= "{yr}-01-01T00:00:00Z"^^xsd:dateTime && 
                 ?releaseDate <= "{yr}-12-31T23:59:59Z"^^xsd:dateTime)
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
        LIMIT 2500
        """

        success = False
        for attempt in range(1, 3):
            try:
                res = requests.get(wdqs_endpoint, params={"query": sparql}, headers=headers, timeout=55)
                if res.status_code == 200:
                    bindings = res.json().get("results", {}).get("bindings", [])
                    
                    # Deduplicate in-memory by QID
                    movies_dict = {}
                    for row in bindings:
                        qid = row["film"]["value"].split("/")[-1]
                        if qid not in movies_dict:
                            movies_dict[qid] = {
                                "id": qid,
                                "title": row["title"]["value"],
                                "year": yr,
                                "director": row.get("directorName", {}).get("value"),
                                "runtime": int(float(row["duration"]["value"])) if "duration" in row else None,
                                "genres": row.get("genreName", {}).get("value"),
                                "tmdb_id": row.get("tmdbId", {}).get("value"),
                                "imdb_id": row.get("imdbId", {}).get("value")
                            }

                    stmts = []
                    for m in movies_dict.values():
                        runtime_val = m["runtime"] if m["runtime"] is not None else "NULL"
                        stmts.append(
                            f"INSERT OR IGNORE INTO movies (id, title, release_year, director, runtime, genres, tmdb_id, imdb_id) "
                            f"VALUES ({escape_sql(m['id'])}, {escape_sql(m['title'])}, {m['year']}, "
                            f"{escape_sql(m['director'])}, {runtime_val}, {escape_sql(m['genres'])}, "
                            f"{escape_sql(m['tmdb_id'])}, {escape_sql(m['imdb_id'])})"
                        )

                    execute_d1_batch(stmts)
                    print(f"   ✓ {yr}: Ingested {len(stmts)} titles.")
                    success = True
                    break
                else:
                    print(f"   ⚠️ Wikidata returned HTTP {res.status_code} for {yr}. Retrying...")
                    time.sleep(5)
            except Exception as e:
                print(f"   ⚠️ Error for year {yr} (attempt {attempt}): {e}")
                time.sleep(5)

        if not success:
            print(f"   ❌ Skipped year {yr} due to upstream timeouts.")

        # Respectful pause between year queries to avoid Wikidata 429/504 errors
        time.sleep(2.5)

    print("✅ Historical movie backfill complete.\n")

# ------------------------------------------------------------------------------
# 6. MAIN CONTROLLER
# ------------------------------------------------------------------------------
def main():
    print("==================================================")
    print("    COMPREHENSIVE ENTERTAINMENT BULK INGEST       ")
    print("==================================================\n")
    
    # 1. Setup tables
    ensure_schema()

    # 2. Daily Grid: Ingest full US broadcast lineup for rolling 48 hours
    harvest_full_tv_schedule()

    # 3. TV Shows: Bulk backfill master shows (pages 0 to 20 = ~5,000 top shows)
    harvest_tvmaze_shows_catalog(max_pages=20)

    # 4. Movies: Bulk backfill 40-year history (1986 through 2026)
    harvest_historical_movies(start_year=1986, end_year=2026)

    print("🎉 Bulk ingestion pipeline finished successfully!")

if __name__ == "__main__":
    main()