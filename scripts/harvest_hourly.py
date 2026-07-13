import pandas as pd
import json
import os
from datetime import datetime

# ==========================================
# CONFIGURATION
# ==========================================
MARKET_DASHBOARD_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQ4Q94pArPoza2zWVI7dZagdcDBhIzdX9wtmrDbgJ_4h1rRr_WFuaMTjTfrJVVGQwbNGGLiSK2zCGnh/pub?gid=701119614&single=true&output=csv"
RATES_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQ4Q94pArPoza2zWVI7dZagdcDBhIzdX9wtmrDbgJ_4h1rRr_WFuaMTjTfrJVVGQwbNGGLiSK2zCGnh/pub?gid=1486733951&single=true&output=csv"

OUTPUT_MARKET_FILE = "data/hourly_market.json"
OUTPUT_RATES_FILE = "data/hourly_rates.json"
SALES_JSON_FILE = "data/sales.json"  # Central real estate repository registry

def harvest_hourly_data():
    print("Fetching Hourly Dashboard & Rates Data...")
    try:
        print(" -> Downloading Market Dashboard...")
        df_market = pd.read_csv(MARKET_DASHBOARD_CSV_URL)
        if 'City' in df_market.columns:
            df_market = df_market.dropna(subset=['City'])
        df_market = df_market.fillna("")
        
        market_records = df_market.to_dict(orient='records')
        os.makedirs(os.path.dirname(OUTPUT_MARKET_FILE), exist_ok=True)
        
        with open(OUTPUT_MARKET_FILE, 'w', encoding='utf-8') as f:
            json.dump(market_records, f, indent=4)
        print(f"✅ Saved {len(market_records)} cities to {OUTPUT_MARKET_FILE}")

        print(" -> Downloading Mortgage Rates...")
        df_rates = pd.read_csv(RATES_CSV_URL)
        df_rates = df_rates.fillna("")
        
        rates_records = df_rates.to_dict(orient='records')
        with open(OUTPUT_RATES_FILE, 'w', encoding='utf-8') as f:
            json.dump(rates_records, f, indent=4)
        print(f"✅ Saved {len(rates_records)} daily rate entries to {OUTPUT_RATES_FILE}")

        # ====================================================================
        # AUTOMATED REAL-TIME DAYS ON MARKET (DOM) CALCULATION STAGE
        # ====================================================================
        print(" -> Analyzing Portfolio Registry for Days on Market (DOM)...")
        if os.path.exists(SALES_JSON_FILE):
            with open(SALES_JSON_FILE, 'r', encoding='utf-8') as f:
                try:
                    sales_data = json.load(f)
                except json.JSONDecodeError:
                    print(f"❌ Error: {SALES_JSON_FILE} contains corrupted or invalid JSON markup structure.")
                    sales_data = None

            if sales_data is not None:
                today_date = datetime.now().date()
                calculated_listings_count = 0
                
                for listing in sales_data:
                    status = listing.get("Status", "").strip()
                    
                    # Rule 1: If the home has closed (Sold), leave the historic spreadsheet DOM completely locked
                    if status == "Sold":
                        continue
                    
                    # Rule 2: For Active or Pending properties, compute real-time DOM variations
                    else:
                        # Safely check your temporary placeholder listing date field
                        start_date_string = listing.get("Selling Date")
                        
                        if start_date_string and str(start_date_string).strip():
                            try:
                                # Parse the string (Expects standard MM/DD/YYYY format such as "4/9/2026")
                                list_date_object = datetime.strptime(str(start_date_string).strip(), "%m/%d/%Y").date()
                                
                                # Run the calendar date delta math execution loops
                                elapsed_days = (today_date - list_date_object).days
                                
                                # Apply values, safeguarding against negative integers if future dates exist
                                listing["DOM"] = max(0, elapsed_days)
                                calculated_listings_count += 1
                            except ValueError:
                                # Fallback changed to "-" if the string entry contains parsing or formatting issues
                                listing["DOM"] = "-"
                        else:
                            # Fallback changed to "-" if the tracking date parameter is completely missing/blank
                            listing["DOM"] = "-"
                
                # Reserialize the modified entries back into the clean JSON target folder
                with open(SALES_JSON_FILE, 'w', encoding='utf-8') as f:
                    json.dump(sales_data, f, indent=4, ensure_ascii=False)
                print(f"✅ Dynamically calibrated live DOM track values for {calculated_listings_count} properties.")
        else:
            print(f"⚠️ Secondary Data Alert: File '{SALES_JSON_FILE}' was not detected. Skipping DOM math stages.")

        print("🎉 Hourly data harvest complete!")
        
    except Exception as e:
        print(f"❌ Error harvesting hourly data: {e}")
        exit(1)

if __name__ == "__main__":
    harvest_hourly_data()