# File: scripts/harvest_quizzes.py
import csv
import json
import requests
import os

CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQONZjmRRou9IqJNV_ZY_8jp7y5pL0tDhuwEqZjCb5ShLhw8alckr2ukPGFD2o7ihJVyRP0gqZtuWkp/pub?gid=0&single=true&output=csv"
DATA_DIR = "data"
OUTPUT_FILE = os.path.join(DATA_DIR, "quizzes.json")

def harvest_quizzes():
    print("Initiating flat-column data harvest pull from Google Sheets...")
    response = requests.get(CSV_URL)
    if response.status_code != 200:
        raise Exception(f"Network endpoint unreachable. Status Code: {response.status_code}")
    
    response.encoding = 'utf-8'
    csv_text = response.text.splitlines()
    reader = csv.DictReader(csv_text)
    
    quizzes_db = {}
    
    for row in reader:
        quiz_id = row.get("Quiz ID", "").strip()
        if not quiz_id:
            continue
            
        print(f"Serializing Quiz ID: {quiz_id} - {row.get('Quiz Name')}")
        
        try:
            rank_value = int(row.get("Rank", "0").strip() or 0)
        except ValueError:
            rank_value = 0
        
        # Harvest Unrolled Questions
        questions = []
        for i in range(1, 21):
            q_text = row.get(f"Q{i} Text", "").strip()
            q_bucket = row.get(f"Q{i} Bucket", "").strip()
            if q_text:
                questions.append({
                    "text": q_text,
                    "bucket": q_bucket
                })
                
        # Harvest Unrolled Results Slots
        routing = []
        for j in range(1, 11):
            r_key = row.get(f"R{j} Key", "").strip()
            r_url = row.get(f"R{j} URL", "").strip()
            if r_key or r_url:
                routing.append({
                    "key": r_key,
                    "url": r_url,
                    "heading": row.get(f"R{j} Heading", "").strip(),
                    "subheading": row.get(f"R{j} Subheading", "").strip(),
                    "details": row.get(f"R{j} Details", "").strip(),
                    "additionalDetails": row.get(f"R{j} Additional Details", "").strip()
                })
                
        quizzes_db[quiz_id] = {
            "id": int(quiz_id),
            "name": row.get("Quiz Name", "").strip(),
            "webTitle": row.get("Quiz Web Title", "").strip(),
            "introText": row.get("Intro Text", "").strip(),
            "scoringType": row.get("Scoring Type", "").strip(),
            "requiredFields": row.get("Required Fields", "").strip(),
            "rank": rank_value,
            "quizImage": row.get("Quiz Image", "").strip(), # 🌟 New Explicit Image Property Map
            "showInCatalog": row.get("Show In Catalog", "").strip(),
            "startDate": row.get("Start Date", "").strip(),
            "endDate": row.get("End Date", "").strip(),
            "webhookUrl": row.get("Webhook URL", "").strip(),
            "emailSubject": row.get("Email Subject", "").strip(),
            "userTags": row.get("User Tags", "").strip(),
            "questions": questions,
            "routing": routing
        }
        
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(quizzes_db, f, indent=4, ensure_ascii=False)
        
    print(f"Compilation finished! Local schema saved to: {OUTPUT_FILE}")

if __name__ == "__main__":
    harvest_quizzes()