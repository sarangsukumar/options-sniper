import asyncio
import datetime
import json
import os
import time
import pandas as pd
from breeze_connect import BreezeConnect
import redis.asyncio as aioredis
import re

# --- Configuration ---
# Your API key and base path. Ensure these are correct.
PRIMARY_APP_KEY = "77059JQ7633PoSc1mk465580B6wp1x04"
PRIMARY_SESSION_FILE = "/home/ubuntu/KotakCodes1/ICICI/icici_session_token/icicisession_amrit.txt"

FALLBACK_APP_KEY = "1f3Pi887R1652C91_76J6808z8191jq~"
FALLBACK_SESSION_FILE = "/home/ubuntu/KotakCodes1/ICICI/icici_session_token/icicisession_manisha.txt"

BASE_PATH = "/home/ubuntu/KotakCodes1/stockscraping-main/"
SCRIP_MASTER_FILE = os.path.join(BASE_PATH, '/home/ubuntu/KotakCodes1/masterfile/ICICImaster.csv')
EXPIRY_DATES_FILE = "/home/ubuntu/KotakCodes1/expiry_dates.txt"

def fetch_today_order_stocks():
    """Fetches unique stock names from markets.orders for today's date."""
    try:
        import mysql.connector
        mydb = mysql.connector.connect(host="localhost", user="root", password="root", database="markets")
        cursor = mydb.cursor()
        query = "SELECT DISTINCT stockname FROM orders WHERE DATE(simulationtime) = CURRENT_DATE()"
        cursor.execute(query)
        rows = cursor.fetchall()
        cursor.close()
        mydb.close()
        stocks = [r[0].strip().upper() for r in rows if r[0]]
        return stocks
    except Exception as e:
        print(f"Error fetching today's order stocks from MySQL: {e}")
        return []


class BreezePythonFetcher:
    """
    A class to fetch last minute futures data from the Breeze API and store it in Redis.
    """
    def __init__(self, redis_url: str = 'redis://localhost'):
        self.api_key, self.session_file, self.session_token = self._read_session_token()
        self.redis_url = redis_url
        
        if not self.session_token:
            raise ValueError("No valid session token found for primary or fallback ICICI account. Aborting.")
            
        self.breeze = BreezeConnect(api_key=self.api_key)
        self.scrip_codes = {}
        self.redis = None
        self.expiry_date = None
        self.stock_list = fetch_today_order_stocks()
        self.summary = {
            "Total": len(self.stock_list),
            "Success": 0,
            "Scrip Not Found": [],
            "No API Data": 0,
            "Error": 0,
            "Initialization Time": 0.0,
            "Fetch and Store Time": 0.0,
            "Overall Time": 0.0
        }
        self.summary_lock = asyncio.Lock()

    def _read_session_token(self):
        """Reads session token from primary (Amrit) or fallback (Manisha)."""
        # 1. Try Primary (Amrit)
        try:
            with open(PRIMARY_SESSION_FILE, 'r') as f:
                token = f.read().strip()
                if token:
                    print(f"Loaded primary ICICI session token (Amrit)")
                    return PRIMARY_APP_KEY, PRIMARY_SESSION_FILE, token
        except FileNotFoundError:
            pass

        # 2. Try Fallback (Manisha)
        try:
            with open(FALLBACK_SESSION_FILE, 'r') as f:
                token = f.read().strip()
                if token:
                    print(f"Loaded fallback ICICI session token (Manisha)")
                    return FALLBACK_APP_KEY, FALLBACK_SESSION_FILE, token
        except FileNotFoundError:
            pass

        print("Error: Neither primary nor fallback ICICI session file could be read.")
        return None, None, None

    def _read_expiry_date(self) -> str:
        """Reads the expiry date from the expiry_dates.txt file."""
        try:
            with open(EXPIRY_DATES_FILE, 'r') as f:
                data = f.read()
                # Use a regular expression to find the date string
                match = re.search(r'const expiryDatesList = "(.*?)";', data)
                if match:
                    # Get the list of dates and find the correct one
                    expiry_dates_list = match.group(1).split(',')
                    return self._get_future_expiry_date(expiry_dates_list)
                else:
                    raise ValueError("Could not find expiryDatesList in the file.")
        except FileNotFoundError:
            print(f"Error: Expiry dates file not found at {EXPIRY_DATES_FILE}")
            raise
        
    def _get_future_expiry_date(self, expiry_dates_list: list) -> str:
        """
        Finds the next available expiry date from the list, similar to the JS code.
        Returns the date in 'YYYY-MM-DD' format.
        """
        today = datetime.datetime.now().date()
        
        # Convert string dates to datetime.date objects for comparison
        expiry_dates = sorted([datetime.datetime.strptime(date, '%Y-%m-%d').date() for date in expiry_dates_list])

        for date in expiry_dates:
            # Check if today's date is in the list or if the date is in the future.
            # Using strftime('%Y-%m-%d') to ensure the format matches the JS code
            if date >= today:
                return date.strftime('%Y-%m-%d')
                
        # If no future date is found, return the last date in the list.
        return expiry_dates[-1].strftime('%Y-%m-%d')

    def initialize_sdk(self):
        """Initializes the Breeze SDK and reads the expiry date."""
        print("Initializing Breeze session...")
        self.breeze.generate_session(api_secret="", session_token=self.session_token)
        print("Breeze session initialized successfully.")
        self.expiry_date = self._read_expiry_date()
        print(f"Using expiry date: {self.expiry_date}")

    async def initialize_redis(self):
        """Connects to Redis."""
        print("Connecting to Redis...")
        self.redis = aioredis.from_url(self.redis_url)
        await self.redis.ping()
        print("Connected to Redis successfully.")

    def load_scrip_codes(self):
        """Loads scrip codes from the CSV file."""
        print(f"Loading scrip codes from {SCRIP_MASTER_FILE}...")
        try:
            df = pd.read_csv(SCRIP_MASTER_FILE)
            df.columns = df.columns.str.strip()
            self.scrip_codes = {
                str(key).strip().upper(): str(value).strip()
                for key, value in pd.Series(df.scripcode.values, index=df.stockcodes).items()
            }
            print(f"Loaded and normalized {len(self.scrip_codes)} scrip code mappings.")
        except FileNotFoundError:
            print(f"Error: Scrip master file not found at {SCRIP_MASTER_FILE}")
            raise
            
    async def fetch_and_store_future(self, stock_name: str):
        """Fetches futures data and stores it in Redis."""
        normalized_stock_name = stock_name.strip().upper()
        scrip_code = self.scrip_codes.get(normalized_stock_name)
        
        if not scrip_code:
            async with self.summary_lock:
                self.summary["Scrip Not Found"].append(stock_name)
            return

        try:
            today_date_str = datetime.datetime.now().strftime('%Y-%m-%d')
            
            data = self.breeze.get_historical_data_v2(
                interval="1minute", 
                from_date=f"{today_date_str}T09:00:00.000Z", 
                to_date=f"{today_date_str}T16:00:00.000Z",
                stock_code=scrip_code,
                exchange_code="NFO",
                product_type="futures",
                expiry_date=f"{self.expiry_date}T07:00:00.000Z",
                right="others",
                strike_price=0
            )

            if data.get('Success') and data['Success']:
                last_tick = data['Success'][-1]
                redis_key = f"LTP:{stock_name}"
                
                # Correctly parse the timestamp
                timestamp = datetime.datetime.strptime(last_tick['datetime'], '%Y-%m-%d %H:%M:%S')
                formatted_timestamp = timestamp.replace(second=0, microsecond=0).strftime('%Y-%m-%d %H:%M:%S.000000')

                redis_value = json.dumps({
                    "timestamp": formatted_timestamp,
                    "ltp": float(last_tick['close']),
                    "source": "ICICI_1minute_futures"
                })
                
                # Store with a 5-minute TTL
                await self.redis.set(redis_key, redis_value, ex=300)
                
                #print(f"[{stock_name}] Successfully fetched. LTP: {float(last_tick['close'])}, Expiry: {self.expiry_date}")
                async with self.summary_lock:
                    self.summary["Success"] += 1
            else:
                print(f"[{stock_name}] No data returned from API. Nothing to store.")
                async with self.summary_lock:
                    self.summary["No API Data"] += 1

        except Exception as e:
            print(f"[{stock_name}] An error occurred: {e}")
            async with self.summary_lock:
                self.summary["Error"] += 1
    
    def print_summary(self):
        """Prints the final execution summary table."""
        print("\n--- Execution Summary ---")
        print("+" + "-"*35 + "+" + "-"*10 + "+")
        print(f"| {'Metric':<34}| {'Count':<9}|")
        print("+" + "-"*35 + "+" + "-"*10 + "+")
        print(f"| {'Total Contracts Processed':<34}| {self.summary['Total']:<9}|")
        print(f"| {'Successful Fetches':<34}| {self.summary['Success']:<9}|")
        print(f"| {'Scrip Not Found':<34}| {len(self.summary['Scrip Not Found']):<9}|")
        print(f"| {'No API Data Received':<34}| {self.summary['No API Data']:<9}|")
        print(f"| {'Errors':<34}| {self.summary['Error']:<9}|")
        print("+" + "-"*35 + "+" + "-"*10 + "+")
        
        print(f"\nTime Metrics:")
        print("+" + "-"*35 + "+" + "-"*10 + "+")
        print(f"| {'Phase':<34}| {'Time (s)':<9}|")
        print("+" + "-"*35 + "+" + "-"*10 + "+")
        print(f"| {'Initialization':<34}| {self.summary['Initialization Time']:.2f}|")
        print(f"| {'Async Fetch & Store':<34}| {self.summary['Fetch and Store Time']:.2f}|")
        print(f"| {'Overall Total':<34}| {self.summary['Overall Time']:.2f}|")
        print("+" + "-"*35 + "+" + "-"*10 + "+")

        if self.summary["Scrip Not Found"]:
            print("\nContracts with missing scrip codes:")
            missing_scrips = self.summary["Scrip Not Found"]
            for i in range(0, len(missing_scrips), 4):
                 print("  ".join(f"{s:<15}" for s in missing_scrips[i:i+4]))

    async def run(self):
        """Main entry point to run the fetcher."""
        start_time_overall = time.time()
        print("--- Starting Python Futures Data Fetcher (Redis) ---")

        try:
            # --- Initialization Group Timing ---
            start_time_init = time.time()
            self.initialize_sdk()
            self.load_scrip_codes()
            await self.initialize_redis()
            self.summary["Initialization Time"] = time.time() - start_time_init

            # --- Async Fetch and Store Group Timing ---
            start_time_fetch = time.time()
            if not self.stock_list:
                print("No stocks found in markets.orders for today. Skipping fetch.")
                return
            print(f"Fetching 1-minute ticks for today's order stocks: {self.stock_list}")
            tasks = [self.fetch_and_store_future(stock) for stock in self.stock_list]
            await asyncio.gather(*tasks)
            self.summary["Fetch and Store Time"] = time.time() - start_time_fetch
            
        except Exception as e:
            print(f"A critical error occurred: {e}")
            
        finally:
            if self.redis:
                await self.redis.close()
                print("Redis connection closed.")
                
            self.summary["Overall Time"] = time.time() - start_time_overall
            self.print_summary()
                
            print("\n--- Script Finished ---")
            print(f"Total Time Taken: {self.summary['Overall Time']:.2f} seconds")


if __name__ == "__main__":
    try:
        fetcher = BreezePythonFetcher()
        asyncio.run(fetcher.run())
    except ValueError as e:
        print(e)
