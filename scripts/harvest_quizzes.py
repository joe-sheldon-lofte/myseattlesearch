# File: scripts/harvest_quizzes.py
import csv
import json
import requests
import os

CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQONZjmRRou9IqJNV_ZY_8jp7y5pL0tDhuwEqZjCb5ShLhw8alckr2ukPGFD2o7ihJVyRP0gqZtuWkp/pub?gid=0&single=true&output=csv"
DATA_DIR = "data"
OUTPUT_FILE = os.path.join(DATA_DIR, "quizzes.json")

def harvest_quizzes():
    print("Initiating automated quiz configuration pull from Google Sheets...")
    response = requests.get(CSV_URL)
    if response.status_code != 200:
        raise Exception(f"Network endpoint unreachable. Status Code: {response.status_code}")
    
    # 🌟 CRITICAL FIX: Explicitly force UTF-8 text decoding to strip character artifacts
    response.encoding = 'utf-8'
    
    csv_text = response.text.splitlines()
    reader = csv.DictReader(csv_text)
    
    quizzes_db = {}
    
    for row in reader:
        quiz_id = row.get("Quiz ID", "").strip()
        if not quiz_id:
            continue
            
        print(f"Serializing Quiz Configuration ID: {quiz_id} - {row.get('Quiz Name')}")
        
        # Gather indexed questions from Q1 to Q20 gracefully
        questions = []
        for i in range(1, 21):
            q_val = row.get(f"Q{i}", "").strip()
            if q_val:
                questions.append(q_val)
                
        # Gather indexed results routing from R1 to R10 gracefully
        routing = []
        for i in range(1, 11):
            r_val = row.get(f"R{i}", "").strip()
            if r_val:
                routing.append(r_val)
                
        # Inject standard nested block schema contract
        quizzes_db[quiz_id] = {
            "id": int(quiz_id),
            "name": row.get("Quiz Name", "").strip(),
            "webTitle": row.get("Quiz Web Title", "").strip(),
            "introText": row.get("Intro Text", "").strip(),
            "scoringType": row.get("Scoring Type", "").strip(),
            "resultsUrl": row.get("Results URL", "").strip(),
            "webhookUrl": row.get("Webhook URL", "").strip(),
            "emailSubject": row.get("Email Subject", "").strip(),
            "userTags": row.get("User Tags", "").strip(),
            "startDate": row.get("Start Date", "").strip(),
            "endDate": row.get("End Date", "").strip(),
            "questions": questions,
            "routing": routing
        }
        
    os.makedirs(DATA_DIR, ensure_copy=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(quizzes_db, f, indent=4, ensure_ascii=False)
        
    print(f"Compilation pipeline completed successfully! Saved structural asset to: {OUTPUT_FILE}")

if __name__ == "__main__":
    harvest_quizzes()