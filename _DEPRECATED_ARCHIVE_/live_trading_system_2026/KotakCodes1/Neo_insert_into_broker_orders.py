# https://github.com/osparamatrix/ks-orderapi-python

import calendar
import database as database
import random
import traceback
import logging 
from datetime import datetime
import pandas as pd
import os
import pickle
import sys
import psutil # Added for checking running instance
from neo_api_client import NeoAPI
import requests
import base64
import json
import time
import warnings
import pyotp
from contextlib import contextmanager

# --- WARNING SUPPRESSION (For pandas/MySQL) ---
warnings.filterwarnings(
    "ignore", 
    message="pandas only supports SQLAlchemy connectable*", 
    category=UserWarning
)

# --- Aggressive Context Manager to Suppress Console Output ---
@contextmanager
def suppress_stdout():
    """Temporarily redirects stdout (file descriptor 1) to /dev/null."""
    if os.name != 'posix':
        null_dev = os.devnull
        old_stdout = sys.stdout
        with open(null_dev, 'w') as f:
            sys.stdout = f
            try:
                yield
            finally:
                sys.stdout = old_stdout
        return

    old_stdout_fd = os.dup(1)
    
    with open(os.devnull, 'w') as devnull:
        devnull_fd = devnull.fileno()
        
        try:
            os.dup2(devnull_fd, 1)
            yield
        finally:
            os.dup2(old_stdout_fd, 1)
            os.close(old_stdout_fd)
            
# --- Logging Setup (Minimal, adapted from original) ---
logpath = os.path.join(os.getcwd(), "logs")
os.makedirs(logpath, exist_ok=True)
logging.basicConfig(filename='multiuser_broker_orders.log',
                    format='%(asctime)s - %(levelname)s - %(message)s',  
                    filemode='a', datefmt='%d-%b-%y %H:%M:%S') 
logger = logging.getLogger() 
logger.setLevel(logging.INFO) # Set base logging level

def logger_func(logger, message, type):
    if type=="CRITICAL":
        logger.critical(message)
    elif type=="WARNING":
        logger.warning(message)
    else:
        logger.info(message)        

# --- Token Management Functions (Adapted for silent operation) ---

def load_token_data(userid):
    """Loads a token from a file and checks if it's from the same day."""
    filename = f"kotak_token_{userid}.json"
    try:
        with open(filename, 'r') as f:
            data = json.load(f)
            saved_date = data.get('date')
            today_date = datetime.now().strftime("%Y-%m-%d")
            
            if saved_date == today_date:
                return data.get('access_token')
            else:
                return None
    except (FileNotFoundError, json.JSONDecodeError):
        return None

def save_token_data(userid, token):
    """Saves a token and the current date to a file."""
    filename = f"kotak_token_{userid}.json"
    data = {
        'access_token': token,
        'date': datetime.now().strftime("%Y-%m-%d")
    }
    with open(filename, 'w') as f:
        json.dump(data, f)

# --- Script Instance Check (adapted from original code) ---
script_name = os.path.basename(sys.argv[0])
def is_another_instance_running(name):
    current_pid = os.getpid()
    for proc in psutil.process_iter(['pid', 'cmdline']):
        try:
            if proc.pid != current_pid and proc.info['cmdline']:
                if any(name in os.path.basename(arg) for arg in proc.info['cmdline']):
                    return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False

if is_another_instance_running(script_name):
    logger.error(f"Another instance of '{script_name}' is already running. Exiting.")
    exit(1)
else:
    logger.info(f"Starting script: {script_name}")
    print(f"\n--- Starting Multi-User Broker Order Insertion ---\n")

# --- Database Insertion Function (Kept from original) ---
def insert_to_table(tablename, columnames_values):
    import mysql.connector

    mydb = mysql.connector.connect(
    host="localhost",
    user="root",
    password="root",
    database="markets"
    )
    column_names = (",").join(columnames_values.keys())
    mycursor = mydb.cursor()
    
    # Avoid duplicates by checking if order_tag already exists
    order_tag_val = columnames_values.get('order_tag', '')
    if order_tag_val and order_tag_val != 'NA':
        check_sql = f"SELECT count(*) FROM {tablename} WHERE order_tag = '{order_tag_val}'"
        mycursor.execute(check_sql)
        if mycursor.fetchone()[0] > 0:
            print(f"Skipping duplicate order: {order_tag_val}")
            mydb.close()
            return

    #stockname,price,quantity,type,ismarket,orderexecutiontime,cretime,modtime,orderplacetime,orderexecutiondate,isvalid,is_future,algo_type,description
    sql = "INSERT INTO "+tablename+" ("+column_names+") VALUES ('"+("','").join(str(v) for v in columnames_values.values())+"\')"
    print(sql)
    mycursor.execute(sql)

    mydb.commit()
    print(mycursor.rowcount, "record inserted.")
    mydb.close()


# --- Main Logic Function for Executed Orders ---
def append_ExecutedOrders(existing_Orders, user_from_API):
    format_str = '%d-%b-%Y %H:%M:%S'
    data = existing_Orders.get("data", [])
    
    if not data:
        print(f"[{user_from_API}] No executed orders found.")
        return
    
    print(f"[{user_from_API}] Processing {len(data)} potential executed orders...")

    map_executed = {}
    
    for trade in data:
        trdSym =""
        Order_type_fromAPI=""
        try:
            Order_status = trade.get("ordSt")
            trdSym = trade.get("sym")
            Order_type_fromAPI = trade.get("trnsTp")
            Order_qty = trade.get("qty")
            instrument_type = trade.get("it")
            
            if Order_type_fromAPI=="B":
                Order_type_fromAPI="BUY"
            if Order_type_fromAPI=="S":
                Order_type_fromAPI="SELL"
            Order_price = trade.get("avgPrc")
            Order_exe_time = trade.get("ordDtTm")
            Order_tag = trade.get("GuiOrdId")    
            Order_ID = trade.get("nOrdNo")
            segment = trade.get("exSeg")
            
            # Data conversion/parsing
            datetime_obj = datetime.strptime(Order_exe_time, format_str)
            algo_type = Order_tag[:2] if Order_tag else 'NA'
            Order_tag_fromAPI = Order_tag[:18] if Order_tag else 'NA'
            L_M = trade.get("prcTp") # Limit or Market type
            
            # Check for executed F&O Future Stock orders
            if segment=="nse_fo" and instrument_type == "FUTSTK" and Order_status=="complete":
                print(f"[{user_from_API}] Executed Future: {trdSym} - {Order_status}")
                
                # Use a cleaner dictionary structure for insertion
                insert_map = {
                    'type': Order_type_fromAPI,
                    'stockname': trdSym,
                    'price': Order_price,
                    'quantity': Order_qty,
                    # PASS THE RAW DATETIME OBJECTS (will be converted to full DATETIME string by Python/MySQL connector)
                    'orderexecutiontime': datetime_obj, # This now passes the full datetime object
                    'orderexecutiondate': datetime_obj, # This now passes the full datetime object
                    'ismarket': (L_M == 'MKT'), 
                    'is_future': True,
                    'algo_type': algo_type,
                    'USER': user_from_API,
                    'L_M': L_M,
                    'order_tag': Order_tag_fromAPI
                }
                insert_to_table("broker_orders", insert_map)

            # Check for executed F&O Option Stock orders
            elif segment=="nse_fo" and instrument_type in ["OPTSTK", "OPTIDX"] and Order_status=="complete":
                print(f"[{user_from_API}] Executed Option: {trdSym} - {Order_status}")
                
                stockname = trade.get("sym")
                strike_price = float(trade.get("stkPrc", 0))
                option_type = trade.get("optTp")
                
                # Parse order_rank from Order_tag_fromAPI (e.g. TL_1_OPTION_HEDGE -> 1 -> TL_opt_1)
                import re
                rank_match = re.search(r'TL_(\d+)_', Order_tag_fromAPI)
                if rank_match:
                    order_rank = f"TL_opt_{rank_match.group(1)}"
                else:
                    order_rank = "TL_opt_1" # Default fallback

                insert_map = {
                    'stockname': stockname,
                    'expiry_date': datetime_obj.strftime("%Y-%m-%d"),
                    'strike_price': strike_price,
                    'option_type': option_type,
                    'type': Order_type_fromAPI,
                    'quantity': Order_qty,
                    'price': Order_price,
                    'orderexecutiondate': datetime_obj,
                    'orderexecutiontime': datetime_obj,
                    'order_tag': Order_tag_fromAPI,
                    'order_rank': order_rank,
                    'algo_type': 'TL_opt',
                    'USER': user_from_API
                }
                insert_to_table("broker_options_orders", insert_map)
            
        except Exception as e:
            print(f"[{user_from_API}] Error processing executed order {trdSym}: {e}")
            logger_func(logger, f"Error processing executed order {trdSym} for {user_from_API}: {e}", "CRITICAL")
            

# --- MAIN MULTI-USER LOOP ---

# 1. Read list of user IDs to process
user_ids_to_process = []
try:
    with open('User_table.csv', 'r') as file:
        next(file) # Skip header
        for line in file:
            stripped_line = line.strip()
            if stripped_line:
                user_ids_to_process.append(stripped_line)
except FileNotFoundError:
    print("FATAL ERROR: User_table.csv file not found. Exiting.")
    sys.exit(1)
except Exception as e:
    print(f"FATAL ERROR reading User_table.csv: {e}. Exiting.")
    sys.exit(1)

if not user_ids_to_process:
    print("No user IDs found in User_table.csv. Exiting.")
    sys.exit(0)


for userid in user_ids_to_process:
    
    # 2. Load Auth Credentials for the current user
    auth_data = None
    Kotak_user = userid # Fallback
    try:
        auth_df = pd.read_csv("kotak_auth_userid.csv")
        auth_data = auth_df[auth_df['userid'] == userid].iloc[0] # Assumes one entry per user
        
        Kotak_user = auth_data['Kotak_user']
        payload_username = auth_data['payload_username']
        payload_password = auth_data['payload_password']
        consumer_key = auth_data['consumer_key']
        consumer_secret = auth_data['consumer_secret']
        MPIN = int(auth_data['MPIN'])
        password = auth_data['password']
        user_from_API = auth_data.get('user_from_API', Kotak_user)
        
        mobile_number = str(auth_data.get('mobile_number', '')).strip()
        totp_secret = str(auth_data.get('totp_secret', '')).strip()
        
        print(f"\n{'='*25} PROCESSING USER: {userid} ({Kotak_user}) {'='*25}")
        print(f"Credentials loaded for {Kotak_user}.")
        
    except FileNotFoundError:
        print("Error: kotak_auth_userid.csv file not found. Skipping remaining users.")
        break
    except IndexError:
        print(f"Error: User ID '{userid}' not found in kotak_auth_userid.csv. Skipping.")
        continue
    except Exception as e:
        print(f"Error while loading credentials for {userid}: {e}. Skipping.")
        traceback.print_exc()
        continue

    if not mobile_number or not totp_secret or mobile_number == 'ENTER_MOBILE' or totp_secret == 'ENTER_TOTP_SECRET':
        print(f"Error: Missing mobile_number or totp_secret in CSV for {userid}. Skipping.")
        continue

    # 3. Perform V2 TOTP Session Login
    client = None
    login_successful = False
    error_message = ""

    with suppress_stdout():
        try:
            client = NeoAPI(consumer_key=consumer_key, environment='prod', neo_fin_key="neotradeapi")
            totp_code = pyotp.TOTP(totp_secret).now()
            formatted_mobile = mobile_number if mobile_number.startswith('+') else f"+91{mobile_number}"
            
            login_resp = client.totp_login(mobile_number=formatted_mobile, ucc=userid, totp=totp_code)
            if login_resp and 'error' in login_resp:
                raise Exception(f"TOTP Login Error: {login_resp['error']}")
                
            val_resp = client.totp_validate(mpin=str(MPIN))
            if val_resp and 'error' in val_resp:
                raise Exception(f"MPIN Validation Error: {val_resp['error']}")
            
            login_successful = True
        except Exception as e:
            error_message = str(e)

    if login_successful:
        print(f"NEO client session established successfully for {Kotak_user}.")
    else:
        print(f"FATAL: Could not establish NEO client session for {Kotak_user}. Error: {error_message}. Skipping user.")
        continue

    # 5. Fetch Orders and Insert (Core Logic)
    
    try:
        print(f"[{Kotak_user}] Fetching executed orders...")
        existing_Orders = client.order_report()
    except Exception as e:
        print(f"[{Kotak_user}] Error fetching order report: {e}")
        logger_func(logger, f"Error fetching order report for {Kotak_user}: {e}", "CRITICAL")
        continue

    # Process and insert
    append_ExecutedOrders(existing_Orders, user_from_API)

    print(f"{'='*25} FINISHED USER: {userid} {'='*25}\n")
