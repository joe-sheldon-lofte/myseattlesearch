import os
import sys
import time
import datetime
import requests

# ------------------------------------------------------------------------------
# 1. CONFIGURATION & CLOUDFLARE D1 CLIENT
# ------------------------------------------------------------------------------
CF_ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID")
CF_DATABASE_ID = os.getenv("CF_DATABASE_ENTERTAINMENT_ID") or os.getenv("CF_DATABASE_ID")
CF_API_TOKEN = os.getenv("CF_API_TOKEN")

if not all([CF_ACCOUNT_ID, CF_DATABASE_ID, CF_API_TOKEN]):
    print("❌ [Entertainment Seed] Missing one or more required Cloudflare environment variables:")
    print(f"   CF_ACCOUNT_ID: {'✓' if CF_ACCOUNT_ID else 'MISSING'}")
    print(f"   CF_DATABASE_ENTERTAINMENT_ID: {'✓' if CF_DATABASE_ID else 'MISSING'}")
    print(f"   CF_API_TOKEN: {'✓' if CF_API_TOKEN else 'MISSING'}")
    sys.exit(1)

D1_API_URL = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/d1/database/{CF_DATABASE_ID}/query"
D1_HEADERS = {
    "Authorization": f"Bearer {CF_API_TOKEN}",
    "Content-Type": "application/json"
}

def execute_d1_query(sql, params=None):
    """Executes a single SQL query against Cloudflare D1 via REST API."""
    payload = {"sql": sql}
    if params:
        payload["params"] = params

    response = requests.post(D1_API_URL, headers=D1_HEADERS, json=payload, timeout=30)
    if response.status_code != 200:
        raise RuntimeError(f"D1 API error ({response.status_code}): {response.text}")
    
    data = response.json()
    if not data.get("success"):
        errors = data.get("errors", [])
        raise RuntimeError(f"D1 Query Execution Failed: {errors}")
    return data.get("result", [])

def execute_d1_batch(sql_statements):
    """Executes multiple raw SQL queries bundled together in single network calls."""
    if not sql_statements:
        return
    # Chunk statements into batches of 40 to stay well under Cloudflare request body thresholds
    chunk_size = 40
    for i in range(0, len(sql_statements), chunk_size):
        chunk = sql_statements[i:i + chunk_size]
        combined_sql = ";\n".join(chunk) + ";"
        execute_d1_query(combined_sql)

def escape_sql(value):
    """Helper to safely escape single quotes for SQL string literals."""
    if value is None:
        return "NULL"
    clean = str(value).replace("'", "''")
    return f"'{clean}'"

# ------------------------------------------------------------------------------
# 2. SCHEMA VERIFICATION
# ------------------------------------------------------------------------------
def ensure_schema():
    print("📦 Verifying D1 table schemas...")
    schema_sql = """
    CREATE TABLE IF NOT EXISTS movies (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        release_year INTEGER,
        director TEXT,
        runtime INTEGER,
        genres TEXT,
        tmdb_id TEXT,
        imdb_id TEXT,
        image_url TEXT
    );
    CREATE TABLE IF NOT EXISTS shows (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        network TEXT,
        genres TEXT,
        summary TEXT,
        image_url TEXT,
        imdb_id TEXT,
        tmdb_id TEXT
    );
    CREATE TABLE IF NOT EXISTS tv_schedule (
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
    );
    CREATE TABLE IF NOT EXISTS actors (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        imdb_id TEXT,
        tmdb_id TEXT,
        known_for TEXT,
        image_url TEXT
    );
    """
    for stmt in [s.strip() for s in schema_sql.split(";") if s.strip()]:
        execute_d1_query(stmt)
    print("✅ Schema verified.\n")

# ------------------------------------------------------------------------------
# 3. TVMAZE PUGET SOUND BROADCAST HARVEST
# ------------------------------------------------------------------------------
def harvest_tv_guide():
    print("📺 Ingesting Puget Sound TV Guide (TVmaze)...")

    station_map = {
        "NBC": {"callsign": "KING 5", "ota": "5.1"},
        "CBS": {"callsign": "KIRO 7", "ota": "7.1"},
        "ABC": {"callsign": "KOMO 4", "ota": "4.1"},
        "FOX": {"callsign": "FOX 13", "ota": "13.1"}
    }

    # Purge schedules older than 12 hours ago
    cutoff_ts = int(time.time()) - (12 * 3600)
    execute_d1_query(f"DELETE FROM tv_schedule WHERE air_timestamp < {cutoff_ts};")

    today = datetime.date.today()
    target_dates = [today.isoformat(), (today + datetime.timedelta(days=1)).isoformat()]

    show_stmts = []
    schedule_stmts = []

    for date_str in target_dates:
        url = f"https://api.tvmaze.com/schedule?country=US&date={date_str}"
        try:
            res = requests.get(url, timeout=20)
            if res.status_code != 200:
                print(f"⚠️ TVmaze returned HTTP {res.status_code} for date {date_str}")
                continue
            schedule_json = res.json()
        except Exception as e:
            print(f"⚠️ Failed calling TVmaze API for {date_str}: {e}")
            continue

        for item in schedule_json:
            show = item.get("show") or {}
            network = show.get("network") or {}
            network_name = network.get("name")

            if network_name in station_map:
                cfg = station_map[network_name]
                show_id = show.get("id")
                show_title = show.get("name", "Unknown")
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
                    f"{escape_sql(cfg['callsign'])}, 'ota', {escape_sql(cfg['ota'])}, {escape_sql(date_str)}, "
                    f"{escape_sql(air_time)}, {air_ts})"
                )

    print(f"Writing {len(show_stmts)} shows and {len(schedule_stmts)} schedule items to D1...")
    execute_d1_batch(show_stmts)
    execute_d1_batch(schedule_stmts)
    print("✅ TV Guide ingest complete.\n")

# ------------------------------------------------------------------------------
# 4. WIKIDATA MOVIE CATALOG HARVEST
# ------------------------------------------------------------------------------
def harvest_wikidata_movies(start_year=2021, end_year=2026):
    print(f"🎬 Harvesting Wikidata movies ({start_year} to {end_year})...")
    wdqs_endpoint = "https://query.wikidata.org/sparql"
    headers = {
        "User-Agent": "SeattleSearchEntertainmentSeed/1.0 (contact: admin@myseattlesearch.com)",
        "Accept": "application/sparql-results+json"
    }

    total_added = 0

    for yr in range(start_year, end_year + 1):
        print(f"   Fetching release year {yr} from Wikidata...")
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
        LIMIT 1500
        """

        try:
            res = requests.get(wdqs_endpoint, params={"query": sparql}, headers=headers, timeout=50)
            if res.status_code != 200:
                print(f"   ⚠️ Wikidata returned {res.status_code} for {yr}")
                continue
            
            bindings = res.json().get("results", {}).get("bindings", [])
            print(f"   Received {len(bindings)} records for {yr}.")

            # Deduplicate by film QID
            movies_dict = {}
            for row in bindings:
                film_qid = row["film"]["value"].split("/")[-1]
                if film_qid not in movies_dict:
                    movies_dict[film_qid] = {
                        "id": film_qid,
                        "title": row["title"]["value"],
                        "year": yr,
                        "director": row.get("directorName", {}).get("value"),
                        "runtime": int(float(row["duration"]["value"])) if "duration" in row else None,
                        "genres": row.get("genreName", {}).get("value"),
                        "tmdb_id": row.get("tmdbId", {}).get("value"),
                        "imdb_id": row.get("imdbId", {}).get("value")
                    }

            statements = []
            for m in movies_dict.values():
                runtime_val = m["runtime"] if m["runtime"] is not None else "NULL"
                statements.append(
                    f"INSERT OR IGNORE INTO movies (id, title, release_year, director, runtime, genres, tmdb_id, imdb_id) "
                    f"VALUES ({escape_sql(m['id'])}, {escape_sql(m['title'])}, {m['year']}, "
                    f"{escape_sql(m['director'])}, {runtime_val}, {escape_sql(m['genres'])}, "
                    f"{escape_sql(m['tmdb_id'])}, {escape_sql(m['imdb_id'])})"
                )

            execute_d1_batch(statements)
            total_added += len(statements)
            time.sleep(2)  # Respect Wikimedia rate guidelines

        except Exception as e:
            print(f"   ❌ Error fetching year {yr}: {e}")

    print(f"✅ Finished Wikidata seed. Processed ~{total_added} unique movie records.\n")

# ------------------------------------------------------------------------------
# 5. MAIN ENTRYPOINT
# ------------------------------------------------------------------------------
def main():
    print("==================================================")
    print("    ENTERTAINMENT DATA INITIAL SEED SCRIPT       ")
    print("==================================================\n")
    ensure_schema()
    harvest_tv_guide()
    harvest_wikidata_movies(start_year=2021, end_year=2026)
    print("🎉 All entertainment tables seeded successfully!")

if __name__ == "__main__":
    main()