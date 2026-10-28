def harvest_targeted_years(years=[2021, 2016, 2013]):
    print(f"🎬 Backfilling missed years: {years}...")
    wdqs_endpoint = "https://query.wikidata.org/sparql"
    headers = {
        "User-Agent": "SeattleSearchEntertainmentBulk/1.0 (contact: admin@myseattlesearch.com)",
        "Accept": "application/sparql-results+json"
    }

    for yr in years:
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
        LIMIT 2500
        """

        try:
            res = requests.get(wdqs_endpoint, params={"query": sparql}, headers=headers, timeout=55)
            if res.status_code == 200:
                bindings = res.json().get("results", {}).get("bindings", [])
                
                movies_dict = {}
                for row in bindings:
                    qid = row["film"]["value"].split("/")[-1]
                    if qid not in movies_dict:
                        # Safe duration parsing
                        raw_duration = row.get("duration", {}).get("value")
                        duration_val = None
                        if raw_duration:
                            digits = "".join(ch for ch in str(raw_duration) if ch.isdigit() or ch == ".")
                            try:
                                duration_val = int(float(digits)) if digits else None
                            except ValueError:
                                duration_val = None

                        movies_dict[qid] = {
                            "id": qid,
                            "title": row["title"]["value"],
                            "year": yr,
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
                        f"INSERT OR IGNORE INTO movies (id, title, release_year, director, runtime, genres, tmdb_id, imdb_id) "
                        f"VALUES ({escape_sql(m['id'])}, {escape_sql(m['title'])}, {m['year']}, "
                        f"{escape_sql(m['director'])}, {runtime_val}, {escape_sql(m['genres'])}, "
                        f"{escape_sql(m['tmdb_id'])}, {escape_sql(m['imdb_id'])})"
                    )

                execute_d1_batch(stmts)
                print(f"   ✓ {yr}: Successfully ingested {len(stmts)} titles.")
                time.sleep(2.5)
            else:
                print(f"   ⚠️ Wikidata returned HTTP {res.status_code} for {yr}")
        except Exception as e:
            print(f"   ❌ Error on year {yr}: {e}")

    print("✅ Targeted year recovery complete.\n")