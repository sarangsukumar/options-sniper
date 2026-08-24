import base64
import calendar
import database as database
import json
import logging
import os
import pandas as pd
import pickle
import random
import requests
import sys
import time
import traceback

from datetime import datetime, time as dt_time
from decimal import Decimal, ROUND_UP
from neo_api_client import NeoAPI
from contextlib import contextmanager
import warnings
import pyotp

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

    # Linux/Unix-specific aggressive suppression:
    old_stdout_fd = os.dup(1)
    
    with open(os.devnull, 'w') as devnull:
        devnull_fd = devnull.fileno()
        
        try:
            os.dup2(devnull_fd, 1)
            yield
        finally:
            os.dup2(old_stdout_fd, 1)
            os.close(old_stdout_fd)

# --- Token Management Functions ---

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
        
def logger_func(logger, message, type):
    # This remains as a utility function, assuming logger setup elsewhere
    if type=="CRITICAL":
        logger.critical(message)
    elif type=="WARNING":
        logger.warning(message)
    else:
        logger.info(message)


# --- Setup (Reads command line arguments) ---
if len(sys.argv) < 3:
    print("Usage: python script.py <ALGO_TYPE> <MODE: AMO or CUSTOM>")
    sys.exit(1)

selected_algo_type = sys.argv[1]
mode = sys.argv[2].upper()

if mode not in ["AMO", "CUSTOM"]:
    print("Error: Mode must be either 'AMO' or 'CUSTOM'")
    sys.exit(1)

custom_limit_percentage = 0 if mode == "CUSTOM" else 8
USER_TABLE_FILE = "Users_to_sqoff.csv" if mode == "CUSTOM" else "User_table.csv"
TABLE_NAME = "orders" if mode == "CUSTOM" else "orders_AMO"
originalPriceColumnName = 'price' if mode == "CUSTOM" else 'buy_price'

try:
    user_df = pd.read_csv(USER_TABLE_FILE)
    user_ids = user_df['userid'].dropna().tolist()
    print(f"Reading user IDs from {USER_TABLE_FILE}...")
except Exception as e:
    print(f"Error reading user list from {USER_TABLE_FILE}: {e}")
    sys.exit(1)

# Basic Logger setup (needed for logger_func)
logging.basicConfig(filename='sqoff_orders.log',
                    format='%(asctime)s - %(levelname)s - %(message)s',  
                    filemode='a', datefmt='%d-%b-%y %H:%M:%S') 
logger = logging.getLogger() 
logger.setLevel(logging.INFO)

def round_to_nearest_tick(price):
    price = float(price)
    if price < 250:
        tick_size = 0.01
    elif 251 <= price <= 1000:
        tick_size = 0.05
    elif 1001 <= price <= 5000:
        tick_size = 0.10
    elif 5001 <= price <= 10000:
        tick_size = 0.50
    elif 10001 <= price <= 20000:
        tick_size = 1.00
    else:
        tick_size = 5.00

    return round(round(price / tick_size) * tick_size, 2)


for userid in user_ids:
    print(f"\n================= Processing user: {userid} =================")
    
    # 1. Load Auth Credentials
    Kotak_user = userid
    try:
        auth_df = pd.read_csv("kotak_auth_userid.csv")
        auth_data = auth_df[auth_df['userid'] == userid]

        if not auth_data.empty:
            auth_row = auth_data.iloc[0]
            Kotak_user = auth_row['Kotak_user']
            payload_username = auth_row['payload_username']
            payload_password = auth_row['payload_password']
            consumer_key = auth_row['consumer_key']
            consumer_secret = auth_row['consumer_secret']
            MPIN = int(auth_row['MPIN'])
            password = auth_row['password']
            user_from_API = auth_row.get('user_from_API', Kotak_user)
            
            mobile_number = str(auth_row.get('mobile_number', '')).strip()
            totp_secret = str(auth_row.get('totp_secret', '')).strip()
            print(f"Credentials loaded for {Kotak_user}.")
        else:
            print(f"User ID '{userid}' not found in kotak_auth_userid.csv. Skipping.")
            continue
    except Exception as e:
        print(f"Error loading credentials for {userid}: {e}")
        traceback.print_exc()
        continue

    if not mobile_number or not totp_secret or mobile_number == 'ENTER_MOBILE' or totp_secret == 'ENTER_TOTP_SECRET':
        print(f"Error: Missing mobile_number or totp_secret in CSV for {userid}. Skipping.")
        continue

    # 2. Perform V2 TOTP Session Login
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
        print(f"Logged in successfully as: {user_from_API}")
    else:
        print(f"Authentication/session failed for {userid}. Error: {error_message}. Skipping.")
        continue
    if user_from_API=='RAJULA' and  mode == "CUSTOM":
            custom_limit_percentage=0.05


    def calculate_custom_limit_price(base_price, percentage):
        return round(float(base_price) * (1 + percentage / 100), 1)

    def insert_to_table(tablename, columnames_values):
        import mysql.connector
        mydb = mysql.connector.connect(host="localhost", user="root", password="root", database="markets")
        column_names = (", ").join(columnames_values.keys())
        placeholders = ", ".join(['%s'] * len(columnames_values))
        sql = f"INSERT INTO {tablename} ({column_names}) VALUES ({placeholders})"
        mycursor = mydb.cursor()
        mycursor.execute(sql, list(columnames_values.values()))
        mydb.commit()

    def get_orders_by_algo_and_type(user_from_API, algo_type, side_type):
        try:
            query = f"""
                SELECT stockname, price, quantity, algo_type, type, orderexecutiontime, order_tag
                FROM broker_orders
                WHERE USER='{user_from_API}' AND algo_type='{algo_type}' AND type='{side_type}' AND orderexecutiondate = (
                    SELECT MAX(orderexecutiondate)
                    FROM broker_orders
                    WHERE USER='{user_from_API}' AND algo_type='{algo_type}'
                )
            """
            df = database.dataframe_from_sql(query)
            print(f"Broker orders for algo_type='{algo_type}' and type='{side_type}':\n{df}\n")
            return df
        except Exception as e:
            print("Error fetching broker orders:", e)
            return pd.DataFrame()

    try:
        exising_positions = client.positions()
        if not exising_positions.get("data"):
            print(f"No positions found for user '{user_from_API}' from API.")
            continue
        else:
            filtered_positions = [pos for pos in exising_positions["data"] if pos.get("type") == "FUTSTK"]
            print(f"Fetched {len(filtered_positions)} FUTSTK positions from API for user '{user_from_API}'")
            
            # --- New: Create a dictionary for efficient position lookup ---
            positions_dict = {
                pos.get('sym'): pos for pos in filtered_positions if pos.get('sym')
            }
            # --- End New ---

            for pos in filtered_positions:
                net_qty = int(pos.get('cfBuyQty', 0)) + int(pos.get('flBuyQty', 0)) - int(pos.get('cfSellQty', 0)) - int(pos.get('flSellQty', 0))
                print(f"Position -> stockname: {pos.get('sym')}, qty: {net_qty}, type: {pos.get('type')}")
    except Exception as e:
        print("Error fetching positions")
        traceback.print_exc()
        continue

    map = {}
    simulationtime = datetime.combine(datetime.now().date(), dt_time.min).strftime("%Y-%m-%d %H:%M:%S")
    last_day_orders = get_orders_by_algo_and_type(user_from_API, selected_algo_type, 'BUY')

    if last_day_orders.empty:
        print(f"No matching broker orders found for user '{user_from_API}'. Skipping AMO creation.")
        continue

    # --- Start of the fix: Group and aggregate orders ---
    last_day_orders['price'] = pd.to_numeric(last_day_orders['price'])
    last_day_orders['quantity'] = pd.to_numeric(last_day_orders['quantity'])

    grouped_orders = last_day_orders.groupby('stockname').apply(
        lambda x: pd.Series({
            'total_quantity': x['quantity'].sum(),
            'weighted_price': (x['price'] * x['quantity']).sum() / x['quantity'].sum(),
            'algo_type': x['algo_type'].iloc[0],
            'order_tag': x['order_tag'].iloc[0]
        })
    ).reset_index()

    print(f"Consolidated broker orders for user '{user_from_API}':\n{grouped_orders}\n")
    # --- End of the fix ---
    
    # --- New: Use a single loop with dictionary lookup ---
    for _, item in grouped_orders.iterrows():
        stock_name = item["stockname"]
        
        # Check if the stock exists in the positions dictionary
        if stock_name in positions_dict:
            trade = positions_dict[stock_name]
            try:
                cfBuyQty = int(trade.get("cfBuyQty"))
                flBuyQty = int(trade.get("flBuyQty"))
                cfSellQty = int(trade.get("cfSellQty"))
                flSellQty = int(trade.get("flSellQty"))
                trdSym = trade.get("sym")
                scripcode = trade.get("trdSym")

                # Calculate the net quantity (open position) in contracts/shares
                net_qty = (cfBuyQty + flBuyQty) - (cfSellQty + flSellQty)
                lot_size = int(trade.get("lotSz"))
                
                # Check for valid segment and non-zero quantity
                segment = trade.get("exSeg")
                if segment == 'nse_fo' and net_qty != 0:
                    # Determine the type of the square-off order
                    type_from_position = "SELL" if net_qty > 0 else "BUY" if net_qty < 0 else None
                    if not type_from_position:
                        continue
                        
                    # *** FIX APPLIED HERE ***
                    # Calculate the quantity of lots to square off using the *net_qty* from the position API.
                    # abs() is used to handle net short positions (negative net_qty)
                    quantity = abs(net_qty) / lot_size if lot_size else 0
                    quantity = int(quantity) 
                    
                    limitprice = calculate_custom_limit_price(item["weighted_price"], custom_limit_percentage)
                    rounded_limitprice = round_to_nearest_tick(limitprice)
                    order_tag = item["order_tag"]
                    order_rank = order_tag.split('__')[0] if order_tag else "XXXX"
                    
                    map[trdSym] = {
                        'type': type_from_position,
                        'stockname': trdSym,
                        originalPriceColumnName: item["weighted_price"],
                        'limitprice': rounded_limitprice,
                        'quantity': quantity,
                        'simulationtime': simulationtime,
                        'ismarket': "0",
                        'is_future': item["algo_type"],
                        'isvalid': "TRUE",
                        'USER': user_from_API,
                        'order_rank': order_rank
                    }
                    
                    # Only insert the order if the calculated quantity is greater than 0
                    if quantity > 0:
                        insert_to_table(TABLE_NAME, map[trdSym])
                        print(f"Inserted order for {trdSym} into table '{TABLE_NAME}' with net position of {quantity} lot(s) at rounded limit price: {rounded_limitprice}")
                    else:
                        print(f"Skipping insertion: Calculated quantity for {trdSym} is zero after lot conversion.")

                else:
                    print(f"Skipping: Invalid segment or zero net quantity for {trdSym}")
            except Exception as e:
                print(f"Error processing order for {stock_name}:", e)
        else:
            print(f"Skipping: No matching position found for {stock_name}")
        # --- End New ---
