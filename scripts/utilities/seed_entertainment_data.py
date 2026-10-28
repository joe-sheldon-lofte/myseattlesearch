import os
import gzip
import json
import requests
import datetime

CF_ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID")
CF_DATABASE_ID = os.getenv("CF_DATABASE_ENTERTAINMENT_ID") or os.getenv("CF_DATABASE_ID")
CF_API_TOKEN = os.getenv("CF_API_TOKEN")

D1_API_URL = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/d1/database/{CF_DATABASE_ID}/query"
D1_HEADERS = {"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/json"}

def execute_d1_batch(sql_statements):
    for i in range(0, len(sql_statements), 50):
        chunk = sql_statements[i:i + 50]
        combined = ";\n".join(chunk) + ";"
        requests.post(D1_API_URL, headers=D1_HEADERS, json={"sql": combined})

def harvest_top_actors(min_popularity=8.0):
    # Today's TMDb date format (e.g. 10_28_2026)
    today_str = datetime.datetime.utcnow().strftime("%m_%d_%Y")
    url = f"http://files.tmdb.org/p/exports/person_ids_{today_str}.json.gz"
    
    print(f"Downloading TMDb daily person export for {today_str}...")
    res = requests.get(url, stream=True)
    if res.status_code != 200:
        # Fall back to yesterday if today's 08:00 UTC export hasn't completed yet
        yesterday_str = (datetime.datetime.utcnow() - datetime.timedelta(days=1)).strftime("%m_%d_%Y")
        url = f"http://files.tmdb.org/p/exports/person_ids_{yesterday_str}.json.gz"
        res = requests.get(url, stream=True)

    decompressed = gzip.decompress(res.content).decode("utf-8")
    statements = []
    count = 0

    for line in decompressed.splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        
        # Filter for notable working actors
        if (
            not item.get("adult") 
            and item.get("known_for_department") == "Acting" 
            and float(item.get("popularity", 0)) >= min_popularity
        ):
            p_id = str(item["id"])
            name = item["name"].replace("'", "''")
            dept = item.get("known_for_department", "Acting")

            statements.append(
                f"INSERT OR IGNORE INTO actors (id, name, tmdb_id, known_for) "
                f"VALUES ('tmdb_{p_id}', '{name}', '{p_id}', '{dept}')"
            )
            count += 1

    print(f"Filtered {count} high-popularity actors. Inserting into D1...")
    execute_d1_batch(statements)
    print("✅ Actors table seeded.")