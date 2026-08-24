import calendar
import time as sys_time
import database as database # Assuming used elsewhere in your full script
import random
import traceback
import logging
from datetime import datetime,time
import pandas as pd # Assuming used elsewhere
import os # Assuming used elsewhere
import pickle # Assuming used elsewhere
import sys

import json
def get_trading_setting(key, default=True):
    try:
        with open('/home/ubuntu/KotakCodes1/trading_settings.json', 'r') as f:
            settings = json.load(f)
            return settings.get(key, default)
    except Exception:
        return default

import json # Moved to top
import base64 # Added for dynamic auth header
import requests
import re
import psutil
import pyotp
from neo_api_client import NeoAPI # Assuming used later with the token
import mysql.connector
import math # Import the math module for rounding
from contextlib import contextmanager # <--- ADDED IMPORT
import warnings

warnings.filterwarnings(
    "ignore", 
    message="pandas only supports SQLAlchemy connectable*", 
    category=UserWarning
)

# --- Aggressive Context Manager to Suppress Console Output ---
# Fix for libraries that print directly to the console (like NeoAPI)
@contextmanager
def suppress_stdout():
    """Temporarily redirects stdout (file descriptor 1) to /dev/null."""
    if os.name != 'posix':
        # Fallback for non-Linux/Unix systems (less reliable but safe)
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


# --- Profit Percentage for Auto-Sell Logic ---
PROFIT_PERCENTAGE = 0.02 # Example: 2% profit target

# --- Stock Tick Size ---
# This is a common tick size for many Indian stocks.
# Adjust this value if your brokerage uses a different one.
TICK_SIZE = 0.05

# --- Custom percentage for limit price calculation ---
custom_limit_percentage = 0.12

future_type = "TL" # Default future type
# --- Configure logging to output to console and file ---
temp_now = datetime.now().strftime("%d_%m_%Y %H_%M_%S_%f")
logpath = os.path.join(os.getcwd(), "logs")
# Ensure the logs directory exists
os.makedirs(logpath, exist_ok=True)
# MODIFIED: Using the requested fixed file name 'Neo_main.txt'
logfilepath = os.path.join(logpath, "Neo_main.txt") 

# Create a logger
logger = logging.getLogger()
logger.setLevel(logging.INFO) # Set the base logging level

# Clear existing handlers to avoid duplicate output if script is run multiple times in same process
if logger.handlers:
    for handler in logger.handlers:
        logger.removeHandler(handler)

# Create file handler which logs even debug messages
# MODIFIED: Using the new logfilepath
fh = logging.FileHandler(logfilepath) 
fh.setLevel(logging.INFO)

# Create formatter and add it to the handlers
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%d-%b-%y %H:%M:%S')
fh.setFormatter(formatter)
# REMOVED: Console handler configuration (ch)

# Add the handlers to the logger
logger.addHandler(fh)
# REMOVED: logger.addHandler(ch)

# NEW: Function to replace all print() calls
def log_print(message):
    logger.info(message)
    print(message)
# End of new logging configuration

def send_telegram_failure_alert_async(stockname, transaction_type, limitprice, quantity, error_msg):
    def send_worker():
        try:
            import subprocess
            bot_script = "/home/ubuntu/KotakCodes1/status_Info_bot.js"
            msg = f"⚠️ <b>ORDER PLACEMENT API FAILURE</b>\n"
            msg += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            msg += f"• <b>Stock:</b> {stockname} ({transaction_type})\n"
            msg += f"• <b>Limit Price:</b> ₹{limitprice:.2f}\n"
            msg += f"• <b>Quantity:</b> {quantity}\n"
            msg += f"• <b>Error Details:</b> {error_msg}\n"
            msg += f"------------------------------------\n"
            subprocess.run(['node', bot_script, msg], timeout=10)
        except Exception:
            pass

    import threading
    threading.Thread(target=send_worker, daemon=True).start()


# Get the current script name
script_name = os.path.basename(sys.argv[0])

def is_another_instance_running(name):
    current_pid = os.getpid()
    for proc in psutil.process_iter(['pid', 'cmdline']):
        try:
            # Skip self, check if script name is in cmdline arguments for other procs
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
    logger.info(f"No other instance of '{script_name}' is running. Continuing execution.")
    # --- Rest of your script logic ---
    log_print("\n--- Script's main logic is now running ---")
    log_print("Doing some work...")
    log_print("--- Script has finished its work ---\n")




def load_token_data(userid):
    """Loads a token from a file and checks if it's from the same day."""
    filename = f"kotak_token_{userid}.json"
    try:
        with open(filename, 'r') as f:
            data = json.load(f)
            saved_date = data.get('date')
            today_date = datetime.now().strftime("%Y-%m-%d")
            
            if saved_date == today_date:
                # Token is valid for today
                return data.get('access_token')
            else:
                # Token is expired
                return None
    except (FileNotFoundError, json.JSONDecodeError):
        # No file or invalid JSON
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
# --- END ADDED/MODIFIED FOR TOKEN REUSE ---


def sort_orders(df, sorting_criteria, fund_csv_file=None):
    if df.empty:
        log_print("DataFrame is empty, nothing to sort.")
        return df
    
    is_fund_sorted = any(col == 'fund_sorted' for col, _ in sorting_criteria)
    is_rank1_fundsorted = any(col == 'Rank1_plus_FundSorted' for col, _ in sorting_criteria)
    
    if is_fund_sorted or is_rank1_fundsorted:
        if not fund_csv_file:
            log_print(f"Error: A fund-based sorting strategy requires a CSV file path.")
            return df
        
        try:
            df_funds = pd.read_csv(fund_csv_file)
            fund_symbol_col = 'NSE Symbol' if 'NSE Symbol' in df_funds.columns else 'stockname'
            df_merged = pd.merge(df, df_funds, left_on='stockname', right_on=fund_symbol_col, how='left')
            df_merged['Margin Required (Approx)'] = df_merged['Margin Required (Approx)'].fillna(float('inf'))
            df = df_merged
        except FileNotFoundError:
            log_print(f"Error: The fund CSV file '{fund_csv_file}' was not found.")
            return df
        except Exception as e:
            log_print(f"Error during fund-based sorting: {e}")
            return df
    
    if is_rank1_fundsorted:
        rank1_df = df[df['order_rank'].str.contains(r'TL_1$', na=False) | df['order_rank'].str.contains(r'TL_1_', na=False)]
        remaining_df = df[~(df['order_rank'].str.contains(r'TL_1$', na=False) | df['order_rank'].str.contains(r'TL_1_', na=False))].copy()

        sorted_remaining_df = remaining_df.sort_values(by='Margin Required (Approx)', ascending=True)

        df = pd.concat([rank1_df, sorted_remaining_df], ignore_index=True)
        
    sort_keys = []
    ascending_list = []
    
    if is_fund_sorted:
        sort_keys.append('Margin Required (Approx)')
        ascending_list.append(True)
    
    remaining_criteria = [item for item in sorting_criteria if item[0] not in ['fund_sorted', 'Rank1_plus_FundSorted']]
    for column, ascending in remaining_criteria:
        if column == 'order_rank':
            df['sort_key_order_rank'] = df['order_rank'].apply(
                lambda x: int(re.search(r'TL_(\d+)', str(x)).group(1)) if pd.notnull(x) and re.search(r'TL_(\d+)', str(x)) else float('inf')
            )
            sort_keys.append('sort_key_order_rank')
            ascending_list.append(ascending)
        elif column == 'cretime':
            df['cretime'] = pd.to_datetime(df['cretime'])
            sort_keys.append('cretime')
            ascending_list.append(ascending)
        elif column in df.columns:
            sort_keys.append(column)
            ascending_list.append(ascending)
        else:
            log_print(f"Warning: Column '{column}' not found. Skipping this sort criterion.")

    if not sort_keys:
        log_print("No valid sorting criteria provided. Returning original DataFrame.")
        return df

    sorted_df = df.sort_values(by=sort_keys, ascending=ascending_list)
    
    if 'sort_key_order_rank' in sorted_df.columns:
        sorted_df = sorted_df.drop(columns='sort_key_order_rank')
        
    return sorted_df

def create_expiry_dates_string(filename="expiry_dates.txt"):
    try:
        import os
        script_dir = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(script_dir, filename), 'r') as file:
            for line in file:
                if "const expiryDatesList = \"" in line:
                    start_index = line.find("\"") + 1
                    end_index = line.rfind("\"")
                    expiry_dates_list = line[start_index:end_index]
                    return expiry_dates_list
            log_print("Could not find expiryDatesList in the file.")
            return None
    except FileNotFoundError:
        log_print(f"Error: File not found at {filename}")
        return None
    except Exception as e:
        log_print(f"An error occurred: {e}")
        return None

# --- Example usage of create_expiry_dates_string ---
expiry_dates_list = create_expiry_dates_string()
if expiry_dates_list:
    log_print(f"Expiry dates read from file: {expiry_dates_list}")

# --- User and Type Configuration ---
# MODIFIED: Instead of reading from sys.argv, we define a list of user IDs to process.
user_ids_to_process = []
script_dir = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(script_dir, 'User_table.csv'), 'r') as file:
    # Skip the header row
    next(file)
    # Iterate over the remaining lines
    for line in file:
        # Append the stripped line to the list, handling potential blank lines
        stripped_line = line.strip()
        if stripped_line:
            user_ids_to_process.append(stripped_line)

log_print(user_ids_to_process)
# --- MODIFIED ARGUMENT PARSING ---
order_table = "markets.orders" # Default value
amo_value = "NO"               # Default value
is_market_square_off = False
is_limit_square_off = False

if len(sys.argv) > 1:
    arg1 = sys.argv[1].upper()
    if arg1 == "AMO":
        order_table = "markets.orders_AMO"
        amo_value = "YES"
        log_print(f"INFO: Command-line argument: {sys.argv[1]}. Using specific table: {order_table}")
    elif arg1 == "SQOFF_MARKET":
        is_market_square_off = True
        log_print(f"INFO: Command-line argument is '{sys.argv[1]}'. Running Market Square-off Strategy.")
    elif arg1 == "LIMIT_SQOFF_POSITIONS": # <--- NEW ARGUMENT CHECK
        is_limit_square_off = True
        log_print(f"INFO: Command-line argument is '{sys.argv[1]}'. Running Limit Square-off Management Strategy.")
    else:
        # Fallback to treat the argument as an explicit table name
        order_table = sys.argv[1] 
        log_print(f"INFO: Reading order table name from command-line argument: {order_table}")
else:
    log_print(f"INFO: No command-line argument provided. Using default order table: {order_table}")


# --- FAST EXIT LOGIC ---
if not get_trading_setting("place_future_order", True):
    log_print("MOCK SUCCESS (place_future_order OFF) - Early exit, bypassing Kotak Auth entirely.")
    try:
        import mysql.connector
        mydb = mysql.connector.connect(host="localhost", user="root", password="root", database="markets")
        mycursor = mydb.cursor()
        
        table_to_update = order_table
        mycursor.execute(f"UPDATE {table_to_update} SET isvalid='1.5' WHERE isvalid='TRUE' AND DATE(simulationtime) = CURDATE()")
        mydb.commit()
        log_print(f"Successfully mock-updated {mycursor.rowcount} pending orders in {table_to_update}.")
        mydb.close()
    except Exception as e:
        log_print(f"Error in mock DB update: {e}")
    import sys
    sys.exit(0)
# -----------------------

for userid in user_ids_to_process:
    log_print(f"\n\n{'='*25} PROCESSING USER: {userid} {'='*25}\n")

    # --- Updated Authentication: Load from CSV ---
    try:
        auth_df = pd.read_csv("kotak_auth_userid.csv")
        auth_data = auth_df[auth_df['userid'] == userid]

        if not auth_data.empty:
            auth_row = auth_data.iloc[0]
            Kotak_user = auth_row['Kotak_user']
            payload_username = auth_row['payload_username']
            payload_password = auth_row['payload_password']
            payload = f'grant_type=password&username={payload_username}&password={payload_password}'
            consumer_key = auth_row['consumer_key']
            consumer_secret = auth_row['consumer_secret']
            MPIN = int(auth_row['MPIN'])
            password = auth_row['password']
            user_from_API=auth_row['user_from_API']
            
            # Extract new V2 auth fields
            mobile_number = str(auth_row.get('mobile_number', '')).strip()
            totp_secret = str(auth_row.get('totp_secret', '')).strip()
            
            log_print(f"Credentials loaded successfully for userid: {userid} ({Kotak_user}) from CSV.")
            print(f"Credentials loaded successfully for userid: {userid} ({Kotak_user}) from CSV.")
        else:
            log_print(f"Error: User ID '{userid}' not found in kotak_auth_userid.csv. Skipping this user.")
            continue # Skip to the next user in the list
    except FileNotFoundError:
        log_print("Error: kotak_auth_userid.csv file not found. Exiting.")
        sys.exit(1)
    except Exception as e:
        log_print(f"An error occurred while loading credentials from CSV for user {userid}: {e}")
        traceback.print_exc()
        continue # Skip to the next user in the list

    # --- Validate that essential credentials are set ---
    if not payload or not consumer_key or not consumer_secret or MPIN is None or password is None:
        log_print(f"Critical credentials missing for userid: {userid} ({Kotak_user}). Skipping this user.")
        continue # Skip to the next user in the list

    # --- MODIFIED AUTHENTICATION FLOW WITH TOKEN REUSE ---

    access_token = load_token_data(userid)
    token_was_reused = access_token is not None # <-- Flag to control conditional login
    #log_print("ACCESS Token=",access_token)
    # If no valid token for today was found, generate a new one
    #access_token=None
    if access_token is None:
        log_print("Proceeding to generate a new access token...")
        
        # --- Dynamic Authorization Header Setup ---
        auth_string = f"{consumer_key}:{consumer_secret}"
        encoded_auth_string = base64.b64encode(auth_string.encode('utf-8')).decode('utf-8')

        headers = {
            'Authorization': f'Basic {encoded_auth_string}',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Cookie': 'AWSALB=XYZ; AWSALBCORS=XYZ'
        }

        url = "https://napi.kotaksecurities.com/oauth2/token"
        log_print("Skipping manual token generation; letting NeoAPI handle it.")
        access_token = None
    datetoday=datetime.now().strftime("%d")
    monthtoday=datetime.now().strftime("%m")
    yeartoday=datetime.now().strftime("%Y")
    todaysdate= yeartoday+"-"+monthtoday+"-"+datetoday#2025-01-30

    month_shortname=calendar.month_abbr[int(monthtoday)].upper()
    now=datetime.now().strftime("%d_%m_%Y %H_%M_%S_%f")
    #log_print(now)
    now=now[-6:]
    #log_print(now)

    pickle_path=os.path.join(os.getcwd(),"pickles")

    def logger_func(logger,message,type):
        if type=="INFO":
            logger.info(message)
        elif type=="CRITICAL":
            logger.critical(message)
        elif type=="WARNING":
            logger.warning(message)
        else:
            logger.info(message)


    from datetime import datetime



    def get_expiry_details_caps_month(expiry_dates_list):
        expiry_dates = [datetime.strptime(date, '%Y-%m-%d').date() for date in expiry_dates_list.split(',')]
        today = datetime.now().date()

        for expiry_date in expiry_dates:
            if expiry_date == today:
                return {"date": expiry_date.isoformat(), "month": expiry_date.strftime('%b').upper()}
            elif expiry_date > today:
                return {"date": expiry_date.isoformat(), "month": expiry_date.strftime('%b').upper()}

        first_expiry = expiry_dates[0]
        return {"date": first_expiry.isoformat(), "month": first_expiry.strftime('%b').upper()}

    expiry_details = get_expiry_details_caps_month(expiry_dates_list)
    log_print(f"future expiry date= {expiry_details['date']}, expiry month= {expiry_details['month']}")
    EXPIRY_MONTH=expiry_details['month']





    future_order_count = 1  # Default fallback
    try:
        with open("future_order_count_TL.txt") as f:
            lines = f.read()
            future_order_count = int(lines)
            log_print(f"{future_type} order count = {future_order_count}")
    except Exception as e:
        log_print("Warning: Could not read future_order_count_TL.txt, using default = 1")

    try:
        log_print("Initializing NeoAPI client...")
        # FIX: Suppress client initialization output (****client=...)
        with suppress_stdout():
            client = NeoAPI(consumer_key=consumer_key, environment='prod', neo_fin_key="neotradeapi")
        log_print("****client=" + str(client))
    except Exception as e:
        logger_func(logger,f"For user {userid}: {str(e)}","CRITICAL")
        log_print(traceback.format_exc())
        log_print(f"Error initializing API client for {userid}. Skipping user.")
        continue

    # -------------------------------------------------------------------------------------------------
    # --- NEW V2: TOTP Session Establishment ---
    # -------------------------------------------------------------------------------------------------
    log_print("Attempting V2 TOTP login to establish session...")
    
    if not mobile_number or not totp_secret or mobile_number == 'ENTER_MOBILE' or totp_secret == 'ENTER_TOTP_SECRET':
        log_print(f"Error: Missing mobile_number or totp_secret in CSV for {userid}. Please update the CSV.")
        continue
    
    login_successful = False
    with suppress_stdout():
        try:
            # Initialize client for V2
            client = NeoAPI(consumer_key=consumer_key, environment='prod', neo_fin_key="neotradeapi")
            
            # Generate TOTP using pyotp
            totp_code = pyotp.TOTP(totp_secret).now()
            
            # Add country code to mobile number if not present
            formatted_mobile = mobile_number if mobile_number.startswith('+') else f"+91{mobile_number}"
            
            # Perform TOTP login
            login_resp = client.totp_login(mobile_number=formatted_mobile, ucc=userid, totp=totp_code)
            if login_resp and 'error' in login_resp:
                raise Exception(f"TOTP Login Error: {login_resp['error']}")
                
            # Validate with MPIN
            val_resp = client.totp_validate(mpin=str(MPIN))
            if val_resp and 'error' in val_resp:
                raise Exception(f"MPIN Validation Error: {val_resp['error']}")
            
            login_successful = True
        except Exception as e:
            error_message = str(e)
            
    if login_successful:
        log_print("NEO client session established successfully: user=" + str(Kotak_user) + str(user_from_API))
    else:
        log_print(f"Final failure establishing NEO client session for {userid}. Exception: {error_message if 'error_message' in locals() else 'Unknown'}")
        continue # Skip to the next user in the outer loop
    # -------------------------------------------------------------------------------------------------

    # Initializing df before the try/except block
    df = pd.DataFrame() 
    
    try:
        filter_string="and (isvalid IN ('1', '1.5', '2', 'TRUE')) "
        content=""
        query = f"select o.id id, o.simulationtime simulationtime ,o.stockname stockname,o.type type ,o.limitprice limitprice,o.quantity quantity,o.user user, o.isvalid isvalid,o.ismarket ismarket,o.order_rank order_rank, o.cretime cretime from {order_table} o left join broker_orders b on DATE_FORMAT(o.simulationtime, '%Y-%m-%d')=DATE_FORMAT(b.orderexecutiondate, '%Y-%m-%d') and o.stockname=b.stockname and o.type=b.type and o.user=b.user where (o.isvalid IN ('1', '1.5', '2', 'TRUE')) and DATE_FORMAT(o.simulationtime, '%Y-%m-%d') =DATE('{todaysdate}') and o.is_future='{future_type}' and b.price is null and o.USER='{user_from_API}'"
        #log_print(query)
        if order_table=='markets.orders_AMO':
            query = f""" SELECT o.id, o.simulationtime, o.stockname, o.type, o.limitprice, o.quantity, o.user, o.isvalid, o.ismarket, o.order_rank, o.cretime FROM {order_table} o left join broker_orders b on DATE_FORMAT(o.simulationtime, '%Y-%m-%d')=DATE_FORMAT(b.orderexecutiondate, '%Y-%m-%d') and o.stockname=b.stockname and o.type=b.type and o.user=b.user WHERE (o.isvalid IN ('1', '1.5', '2', 'TRUE')) AND DATE_FORMAT(o.simulationtime, '%Y-%m-%d') = DATE('{todaysdate}') AND o.is_future = '{future_type}' and b.price is null AND o.USER = '{user_from_API}' """

        df=database.dataframe_from_sql(query )
        
        # --- FIX START: Ensure df is a valid DataFrame object ---
        if not isinstance(df, pd.DataFrame):
            log_print(f"WARNING: Database function returned non-DataFrame type: {type(df)}. Initializing as empty DataFrame.")
            df = pd.DataFrame() # Re-initialize as empty DataFrame to prevent iteration errors
        # --- FIX END ---
        
        fund_csv_file = 'Kotak_fund_sorted.csv' # Define this here as it's used for NEELIMA's criteria
        
        if user_from_API in ['NEELIMA', 'RAJULA']:
            sorting_criteria = [('fund_sorted', True)]
            df = sort_orders(df, sorting_criteria)
            log_print(f"Sorting applied for user {user_from_API}: {sorting_criteria}")
            custom_limit_percentage = 0.11
        elif user_from_API == 'MANISHA':
            sorting_criteria = [('order_rank', True), ('cretime', False)]
            
            df = sort_orders(df, sorting_criteria, fund_csv_file=fund_csv_file)
            log_print(f"Sorting applied for user {user_from_API}: {sorting_criteria}")
            custom_limit_percentage = 0.10
        else:
            log_print(f"No specific sorting criteria found for user {user_from_API}. Using default.")
        #print(df)


    except Exception as e:
        logger_func(logger,str(e),"CRITICAL")
        log_print(str(e))
    log_print(str(df))
    log_print("new log amr")





    def findscripcode(token):
         try:
            item_found_conter=0
            dff = pd.read_csv("/home/ubuntu/KotakCodes1/masterfile/kotakneoscripcodemap_historical.csv")
            for index, row in dff.iloc[::-1].iterrows():
                sname = str(row['stockname']).rstrip() if pd.notna(row['stockname']) else ""
                scripcode = str(row['scripcode']).rstrip() if pd.notna(row['scripcode']) else ""
                expmonth = str(row['expmonth']).rstrip() if 'expmonth' in row and pd.notna(row['expmonth']) else ""
                if sname == token:
                    if expmonth == EXPIRY_MONTH or f"26{EXPIRY_MONTH}" in scripcode or f"26{EXPIRY_MONTH}FUT" in scripcode:
                        item_found_conter = 1
                        return scripcode

            if item_found_conter == 0:
                return 0
         except Exception as err:
             log_print("exception in findscripcode: " + str(err))
             return 0

    def find_lot_size(token):
         log_print(token)
         try:
            item_found_conter=0
            dff = pd.read_csv("/home/ubuntu/KotakCodes1/masterfile/kotakneoscripcodemap_historical.csv")
            for index, row in dff.iloc[::-1].iterrows():
                sname = str(row['stockname']).rstrip() if pd.notna(row['stockname']) else ""
                lot_size = row.get('lotsize', row.get('lot_size', 0))
                expmonth = str(row['expmonth']).rstrip() if 'expmonth' in row and pd.notna(row['expmonth']) else ""
                scripcode = str(row['scripcode']).rstrip() if pd.notna(row['scripcode']) else ""
                if sname == token:
                    if expmonth == EXPIRY_MONTH or f"26{EXPIRY_MONTH}" in scripcode or f"26{EXPIRY_MONTH}FUT" in scripcode:
                        if pd.notna(lot_size) and int(float(lot_size)) > 0:
                            item_found_conter = 1
                            return int(float(lot_size))

            if item_found_conter == 0:
                return 0
         except Exception as err:
            log_print("exception in find_lot_size: "+str(err))
            return 0

    def find_expiryday(token):
         try:
            item_found_conter=0
            dff = pd.read_csv("/home/ubuntu/KotakCodes1/masterfile/kotakneoscripcodemap_historical.csv")
            for index, row in dff.iloc[::-1].iterrows():
                sname = row['stockname'].rstrip()
                expiry_day = row['expiry_day']

                if(sname==token):
                    item_found_conter+=1#first occurance is F3
                    if (item_found_conter==3):#meansF1
                        return(int(expiry_day))
            if(item_found_conter==0):
                return(0)
         except Exception as err:
            log_print("exception in expiry day"+str(err))
            return (0)


    def append_OpenOrders(existing_Orders,stocks_in_OpenandClosedOrders):
        data = existing_Orders.get("data", [])
        if not data:
            return

        for trade in data:
            trdSym =""
            Order_type_fromAPI=""

            try:
                Order_status=trade.get("ordSt")
                trdSym = trade.get("sym")
                Order_type_fromAPI=trade.get("trnsTp")
                
                # --- CAPTURE ORDER TAGS AND TIME ---
                Order_tag_original = trade.get("GuiOrdId")
                Order_tag_truncated = Order_tag_original[:2] if Order_tag_original else "NA"
                Order_tag_full = Order_tag_original

                # FIX: Capture the raw time (boeSec is usually milliseconds since epoch)
                boe_sec_str = trade.get("boeSec") 
                try:
                    # Safely convert the string value of boeSec to a numerical timestamp
                    order_time_raw = int(float(boe_sec_str)) if boe_sec_str else 0 # Renamed to order_time_raw for clarity
                except (ValueError, TypeError):
                    order_time_raw = 0
                
                instrument_type = trade.get("it")
                if Order_type_fromAPI=="B":
                    Order_type_fromAPI="BUY"
                if Order_type_fromAPI=="S":
                    Order_type_fromAPI="SELL"
                Order_ID=trade.get("nOrdNo")
                # -----------------------------------

                if not Order_ID or not isinstance(Order_ID, str) or Order_ID.strip() == "":
                    log_print(f"Skipping order due to invalid (empty or non-string) Order_ID found for symbol {trdSym}. Received: '{Order_ID}'")
                    continue

                segment=trade.get("exSeg")
                if (segment=="nse_fo" and instrument_type == "FUTSTK" and (Order_status=="open" or Order_status=="complete")) :
                    
                    # Store 7 elements: [Symbol, Type, ID, Status, Truncated Tag, Full Tag, Raw Time (ms/ns)]
                    orders_to_append = (trdSym, Order_type_fromAPI, Order_ID, Order_status, Order_tag_truncated, Order_tag_full, order_time_raw)

                    stocks_in_OpenandClosedOrders.append(orders_to_append)

            except Exception as e:
                log_print ("amm")
                log_print(str(e))
                log_print("unable to get stockname for symbol "+str(trdSym)+"\n")
                

    def get_all_open_buy_orders(stocks_in_open_and_closed_orders):

        open_buy_orders = {}
    
        # Division factor for seconds conversion: 1,000 (ms) or 1,000,000 (micro) or 1,000,000,000 (nano)
        # Based on persistent error, we suspect the raw value is 1000 times too large (microseconds or nanoseconds).
        # We will try dividing by 1,000,000 (microseconds) or 1,000,000,000 (nanoseconds) based on inspection.
        # Since the value in your earlier logs (1759993443) is 10 digits, it's seconds. If the API returned a 19-digit number, it's nanoseconds.
        # Lets use the safest high divisor: nanoseconds (10^9).
        TIME_CONVERSION_FACTOR = 1000000000.0 # Nanoseconds to Seconds

        for item in stocks_in_open_and_closed_orders:
            # Unpack the 7 elements from the list
            trdSym = item[0]
            order_type_from_api = item[1]
            order_id = item[2]
            order_status = item[3]
            # item[4] is the truncated tag
            order_tag_full = item[5]  # Full GuiOrdId
            order_time_raw = item[6]   # Order Time in raw units

            # Check for open status and BUY type
            if order_status == "open" and order_type_from_api == "BUY":
                
                seconds_since_epoch = 0
                if order_time_raw > 0:
                    # FIX: Divide by the correct factor to get seconds (10^9 = nanoseconds)
                    seconds_since_epoch = order_time_raw / TIME_CONVERSION_FACTOR
                    
                    # Ensure time is not in 1970 by converting the seconds to datetime
                    # If seconds_since_epoch > 31536000 (1 year in seconds), we proceed.
                    # Given the log, the correct value for the order placed on Oct 9, 2025, should be around 1,759,990,000 seconds.
                    
                    # We must check if the original raw value was too small (meaning it was already seconds)
                    # Based on your prior logs, boeSec = 1759981553 (10 digits, actual seconds in 2025). 
                    # The log shows the WRONG field (boeSec) being used. The correct field is likely the 19-digit 'updRecvTm'.
                    # HOWEVER, since we are only using boeSec (10 digits), we should have only divided by 1.
                    
                    # RETHINK: The initial error happened because 10-digit 'boeSec' was treated as MS instead of S. 
                    # The value 1759981553 IS the correct time in seconds since epoch for Oct 9, 2025.
                    # But the log shows the value being 1758233449.53s old. This means the Python environment's current time is wrong,
                    # OR, the code is using the WRONG API field.
                    
                    # We are currently using item[6], which stores boeSec (10 digits).
                    # Let's revert to the simplest fix (no division) as the raw value IS seconds, and check why the time difference is wrong.

                    if len(str(order_time_raw)) > 15:
                         # This handles cases where a 16-19 digit micro/nano second value is accidentally passed.
                         seconds_since_epoch = order_time_raw / 1000000000.0
                    elif len(str(order_time_raw)) > 12:
                         # This handles 13-15 digit millisecond values.
                         seconds_since_epoch = order_time_raw / 1000.0
                    else:
                         # This is the correct 10-digit seconds value (as seen in the API response data)
                         seconds_since_epoch = float(order_time_raw)


                    order_datetime = datetime.fromtimestamp(seconds_since_epoch)
                else:
                    order_datetime = None

                # NEW: Calculate time difference in seconds for the output log
                time_difference_seconds = (datetime.now() - order_datetime).total_seconds() if order_datetime else 0


                open_buy_orders[trdSym] = {
                    "order_id": order_id,
                    "order_tag_full": order_tag_full, 
                    "order_time_raw": order_time_raw,
                    "order_datetime": order_datetime,
                    "order_time_seconds": seconds_since_epoch, # Time in seconds since epoch
                    "time_difference_seconds": time_difference_seconds # NEW: Time difference for comparison
                }

        return open_buy_orders
    def cancel_order_by_id(client, order_id, stockname, max_retries=3):


        import time as sys_time

        action_type = "cancel"
        order_id_for_api = str(order_id)
        cancel_successful = False
        
        log_print(f"\n--- Initiating order {action_type} for {stockname} (Order ID: {order_id}) ---")

        for attempt_count in range(1, max_retries + 1):
            if attempt_count > 1:
                log_print(f"Waiting for 1 second before retrying {action_type}...")
                sys_time.sleep(1)
            try:
                # Suppress internal API log_printing during the cancellation attempt
                with suppress_stdout():
                    cancel_response = client.cancel_order(order_id=order_id_for_api)
                
                log_print(f"API Response ({action_type} attempt {attempt_count}): {cancel_response}")

                if cancel_response and (cancel_response.get('stat') == 'Ok' or cancel_response.get('stCode') == 200):
                    log_print(f"SUCCESS: Order for {stockname} {action_type}led successfully on attempt {attempt_count}.")
                    cancel_successful = True
                    break
                # START MODIFICATION: Handle the specific "order is cancelled" error
                elif cancel_response and 'order is cancelled' in cancel_response.get('errMsg', ''):
                    log_print(f"INFO: Order for {stockname} was already cancelled by the broker system. Treating as SUCCESS.")
                    cancel_successful = True
                    break
                # END MODIFICATION
                elif cancel_response and 'Order is in status' in cancel_response.get('errMsg', ''):
                    # Order is already complete/rejected
                    log_print(f"INFO: Order for {stockname} is already in a final state and cannot be cancelled.")
                    cancel_successful = True
                    break
                else:
                    log_print(f"FAILURE ({action_type} Attempt {attempt_count}): API error - {cancel_response.get('errMsg')}.")

            except Exception as e:
                log_print(f"EXCEPTION ({action_type} Attempt {attempt_count}): A Python exception occurred - {e}")
                if attempt_count == max_retries:
                    log_print(f"Max {max_retries} attempts reached after Python exception.")
        
        return cancel_successful


    # --- MODIFIED FUNCTION TO INCLUDE AVG BUY PRICE ---
    def append_OpenPositions(exising_positions, stocks_in_Positions):
        data = exising_positions.get("data", [])
        if not data:
            return

        for trade in data:
            trdSym = ""
            Order_type_fromAPI = ""
            try:
                cfBuyQty = int(trade.get("cfBuyQty", 0))
                flBuyQty = int(trade.get("flBuyQty", 0))
                cfSellQty = int(trade.get("cfSellQty", 0))
                flSellQty = int(trade.get("flSellQty", 0))
                trdSym = trade.get("sym")
                scripcode = trade.get("trdSym")
                avg_buy_price = float(trade.get("buyAvg", 0.0))

                total_buy_qty = cfBuyQty + flBuyQty
                total_sell_qty = cfSellQty + flSellQty
                net_qty = total_buy_qty - total_sell_qty
                if net_qty > 0:
                    Order_type_fromAPI = "BUY"
                elif net_qty < 0:
                    Order_type_fromAPI = "SELL"
                else:
                    continue # Skip if net quantity is 0

                segment = trade.get("exSeg")
                if segment == "nse_fo" and trade.get('type') == 'FUTSTK':
                    # ADDING avg_buy_price to the tuple
                    positions_to_append = (trdSym, Order_type_fromAPI, net_qty, avg_buy_price)
                    stocks_in_Positions.append(positions_to_append)

            except Exception as e:
                log_print(f"Error in append_OpenPositions for symbol {trdSym}: {e}")
                log_print(traceback.format_exc())

    # NEW FUNCTION: Get executed price from the order report
    def get_latest_executed_buy_price(orders_report_data, stockname):
        
        if not orders_report_data:
            return 0.0

        latest_buy_price = 0.0
        latest_time = 0 # Use 0 as the starting point for comparison (using raw time in nano/micro seconds)

        for order in orders_report_data:
            # 1. Filter for completed BUY orders for the correct symbol
            if (order.get('sym') == stockname and
                order.get('trnsTp') == 'B' and
                order.get('ordSt') == 'complete' and
                int(order.get('fldQty', 0)) > 0): # Ensure it has been filled

                try:
                    # Use updRecvTm (nanoseconds/microseconds) for high-precision time comparison
                    # Fallback to boeSec (seconds) if updRecvTm is not available/invalid
                    # Note: updRecvTm is the long 19-digit number confirmed in your data
                    current_order_time = int(order.get('updRecvTm', order.get('boeSec', 0)))
                except (ValueError, TypeError):
                    current_order_time = 0
                
                # 2. Check if this is the latest completed order so far
                if current_order_time > latest_time:
                    latest_time = current_order_time
                    try:
                        # Use the average price of this latest completed order ID
                        latest_buy_price = float(order.get('avgPrc', 0.0))
                    except (ValueError, TypeError):
                        latest_buy_price = 0.0
                        
        if latest_buy_price > 0.0:
            log_print(f"DEBUG: Using latest executed BUY price from API report for {stockname} at {latest_buy_price} (Time: {latest_time})")

        return latest_buy_price

    def get_executed_buy_price(orders_report_data, stockname):
        """
        Finds the executed price for a completed BUY order for a specific stock.
        Args:
            orders_report_data: The 'data' list from the client.order_report() response.
            stockname: The name of the stock to find the executed price for.
        Returns:
            The average executed price (float) or 0.0 if not found.
        """
        if not orders_report_data:
            return 0.0

        for order in orders_report_data:
            # Check if the order is for the correct stock, is a BUY, and is complete
            if (order.get('sym') == stockname and
                order.get('trnsTp') == 'B' and
                order.get('ordSt') == 'complete'):
                try:
                    # Return the average price if found
                    return float(order.get('avgPrc', 0.0))
                except (ValueError, TypeError):
                    # Handle cases where avgPrc is not a valid number
                    log_print(f"Warning: Could not convert average price '{order.get('avgPrc')}' for {stockname} to float.")
                    return 0.0
        return 0.0
    def market_square_off_positions(client, stocks_in_Positions, userid):
        
        log_print(f"\n{'='*20} MARKET SQUARE OFF LOGIC STARTED for {userid} {'='*20}")
        
        square_off_summary = []
        
        if not stocks_in_Positions:
            log_print("No open positions found to square off.")
            return []

        for position_item in stocks_in_Positions:
            stockname = position_item[0]
            position_type = position_item[1] # "BUY" or "SELL"
            net_qty = abs(position_item[2])
            # avg_buy_price = position_item[3] # Not strictly needed for market order
            
            # Determine transaction type for square-off
            # If position is BUY (long), the square-off order is SELL.
            # If position is SELL (short), the square-off order is BUY.
            square_off_type = "SELL" if position_type == "BUY" else "BUY"
            transaction_type_neo = "S" if square_off_type == "SELL" else "B"
            
            # Ensure we have a quantity to square off
            if net_qty == 0:
                continue

            scripcode = findscripcode(stockname) # Assuming this function is available in the global scope
            lot_size = find_lot_size(stockname) # Assuming this function is available in the global scope

            if not scripcode or not lot_size:
                log_print(f"Could not find scripcode or lot size for {stockname}. Skipping square-off.")
                square_off_summary.append(f"{stockname} - FAILED (Scrip/Lot Size)")
                continue

            quantity = net_qty
            
            # Create a unique tag for the market square-off order
            now_tag = datetime.now().strftime("%d%m%Y%H%M%S%f")[-6:]
            tag = f"SQOFF_{position_type}_{stockname[:4]}_{now_tag}"

            log_print(f"\nPlacing MARKET square-off order for: {stockname}")
            log_print(f"  -> Position Type:   {position_type} (Qty: {quantity})")
            log_print(f"  -> Square-off Type: {square_off_type} (Neo: {transaction_type_neo})")
            log_print(f"  -> Tag:             {tag}")

            try:
                total_attempts = 3
                retry_delay_seconds = 1
                order_action_successful = False
                last_known_response = None
                action_type = "place_market_sqoff"
                
                # Note: Market orders use price="0" and order_type="MKT"
                
                for attempt_count in range(1, total_attempts + 1):
                    if attempt_count > 1:
                        log_print(f"Retrying market square-off for {stockname} in {retry_delay_seconds} seconds... (Attempt {attempt_count}/{total_attempts})")
                        sys_time.sleep(retry_delay_seconds)
                    try:
                        order_response = client.place_order(
                            exchange_segment="nse_fo",
                            product="NRML",
                            price="0",  # Market order price is 0
                            order_type="MKT",
                            quantity=str(quantity),
                            validity="DAY",
                            trading_symbol=scripcode,
                            transaction_type=transaction_type_neo,
                            amo="NO", # Assuming market square off is always intraday/regular market
                            disclosed_quantity="0",
                            market_protection="0",
                            trigger_price="0",
                            tag=tag
                        )
                        last_known_response = order_response
                        log_print(f"API Response ({action_type} attempt {attempt_count}): {order_response}")

                        if order_response and (order_response.get('stat') == 'Ok' or order_response.get('stCode') == 200):
                            log_print(f"SUCCESS: Market square-off for {stockname} ({position_type}) placed successfully.")
                            order_action_successful = True
                            break
                        else:
                            log_print(f"FAILURE ({action_type} Attempt {attempt_count}): API error - {order_response.get('errMsg')}.")
                    except Exception as e:
                        log_print(f"EXCEPTION ({action_type} Attempt {attempt_count}): A Python exception occurred - {e}")
                        last_known_response = {'stCode': 'PYTHON_EXCEPTION', 'errMsg': str(e), 'stat': 'Not_Ok', 'attempt': attempt_count}

                
                if order_action_successful:
                    square_off_summary.append(f"{stockname} ({position_type}) - SUCCESS")
                else:
                    square_off_summary.append(f"{stockname} ({position_type}) - FAILED (API Error/Exception)")

            except Exception as e:
                log_print(f"CRITICAL EXCEPTION during market square-off for {stockname}: {e}")
                square_off_summary.append(f"{stockname} ({position_type}) - FAILED (Critical Exception)")
                
        log_print(f"\n{'='*20} MARKET SQUARE OFF LOGIC FINISHED {'='*20}")
        log_print("\n--- Market Square Off Summary ---")
        for item in square_off_summary:
            log_print(f"* {item}")
        log_print("---------------------------------")
        return square_off_summary


    def limit_square_off_positions_and_manage(client, stocks_in_Positions, userid, open_orders_for_modification):
        
        log_print(f"\n{'='*20} LIMIT SQUARE OFF MANAGEMENT STARTED for {userid} {'='*20}")
        
        square_off_summary = []
        
        if not stocks_in_Positions:
            log_print("No open positions found to square off.")
            return []

        # 1. Fetch all required limit prices from the database in one go
        stock_names = [item[0] for item in stocks_in_Positions if abs(item[2]) > 0]
        if not stock_names:
            log_print("All positions have zero net quantity.")
            return []

        stock_list_str = "', '".join(stock_names)
        
        # Query to fetch the latest 'limitprice' for the stocks in position for the current user.
        # We use markets.orders as the source for the current *target* limit price.
        query = f"""
            SELECT 
                stockname, 
                limitprice 
            FROM markets.orders
            WHERE 
                stockname IN ('{stock_list_str}') 
                
            ORDER BY cretime DESC;
        """
        
        # Assuming 'database.dataframe_from_sql' is available and functional
        try:
            df_prices = database.dataframe_from_sql(query)
            # Use drop_duplicates to ensure only the latest price (due to ORDER BY cretime DESC) is kept for each stock
            db_prices = df_prices.drop_duplicates(subset=['stockname'], keep='first').set_index('stockname')['limitprice'].to_dict()
            log_print(f"Prices fetched from DB: {db_prices}")
        except Exception as e:
            log_print(f"ERROR: Failed to fetch limit prices from database: {e}")
            return []

        # 2. Process each position
        for position_item in stocks_in_Positions:
            stockname = position_item[0]
            position_type = position_item[1] # "BUY" or "SELL"
            net_qty = abs(position_item[2])
            
            if net_qty == 0:
                continue
                
            limitprice = db_prices.get(stockname)

            if limitprice is None or limitprice <= 0:
                log_print(f"Skipping {stockname}: Invalid limit price ({limitprice}) found in database.")
                square_off_summary.append(f"{stockname} - FAILED (Invalid DB Price)")
                continue
                
            # Determine transaction type for square-off
            square_off_type = "SELL" if position_type == "BUY" else "BUY"
            transaction_type_neo = "S" if square_off_type == "SELL" else "B"
            quantity = net_qty
            
            scripcode = findscripcode(stockname) # Assuming global availability
            lot_size = find_lot_size(stockname) # Assuming global availability
            
            if not scripcode or not lot_size:
                log_print(f"Could not find scripcode/lot size for {stockname}. Skipping.")
                square_off_summary.append(f"{stockname} - FAILED (Scrip/Lot Size)")
                continue

            # --- Order Management: Cancel Existing Open Orders ---
            order_to_modify_details = open_orders_for_modification.get(stockname)
            # Check if an open order exists AND if it is the correct type (SQOFF type)
            is_order_to_modify = (order_to_modify_details and
                                  order_to_modify_details["order_type_api"] == square_off_type)
            
            was_cancelled = False
            if is_order_to_modify:
                order_id_to_cancel = order_to_modify_details["order_id"]
                log_print(f"Found open {square_off_type} order (ID: {order_id_to_cancel}) for {stockname}. Attempting cancellation...")
                
                # Use the already defined utility function (needs to be defined in global scope or passed/imported)
                # Assuming 'cancel_order_by_id' is the utility function defined later in your script.
                # We call the *final* utility defined in your provided code
                was_cancelled = cancel_order_by_id(client, order_id_to_cancel, stockname)

                if not was_cancelled:
                    log_print(f"WARNING: Failed to cancel open order for {stockname}. Skipping new order placement to avoid duplicates.")
                    square_off_summary.append(f"{stockname} - FAILED (Cancel Fail)")
                    continue
            # --- End Order Management ---

            # 3. Place the new Limit Square-Off Order
            now_tag = datetime.now().strftime("%d%m%Y%H%M%S%f")[-6:]
            tag = f"LMT_SQOFF_{square_off_type}_{stockname[:4]}_{now_tag}"
            
            log_print(f"\nPlacing new LIMIT square-off order for: {stockname}")
            log_print(f"  -> Position Type:   {position_type} (Qty: {quantity})")
            log_print(f"  -> Square-off Type: {square_off_type} (Neo: {transaction_type_neo})")
            log_print(f"  -> Target Price:    {limitprice}")
            log_print(f"  -> Tag:             {tag}")
            
            try:
                total_attempts = 3
                retry_delay_seconds = 1
                order_action_successful = False
                
                for attempt_count in range(1, total_attempts + 1):
                    if attempt_count > 1:
                        sys_time.sleep(retry_delay_seconds)
                    try:
                        # Place a LIMIT order
                        order_response = client.place_order(
                            exchange_segment="nse_fo",
                            product="NRML",
                            price=str(limitprice), 
                            order_type="L", # LIMIT order type
                            quantity=str(quantity),
                            validity="DAY",
                            trading_symbol=scripcode,
                            transaction_type=transaction_type_neo,
                            amo="NO", 
                            disclosed_quantity="0",
                            market_protection="0",
                            trigger_price="0",
                            tag=tag
                        )
                        
                        if order_response and (order_response.get('stat') == 'Ok' or order_response.get('stCode') == 200):
                            order_action_successful = True
                            break
                        else:
                            log_print(f"FAILURE (Limit Place Attempt {attempt_count}): API error - {order_response.get('errMsg')}.")
                    except Exception as e:
                        log_print(f"EXCEPTION (Limit Place Attempt {attempt_count}): A Python exception occurred - {e}")
                
                if order_action_successful:
                    square_off_summary.append(f"{stockname} ({position_type}) - SUCCESS (New Limit Placed)")
                else:
                    square_off_summary.append(f"{stockname} ({position_type}) - FAILED (Limit Place Fail)")

            except Exception as e:
                log_print(f"CRITICAL EXCEPTION during limit square-off placement for {stockname}: {e}")
                square_off_summary.append(f"{stockname} ({position_type}) - FAILED (Critical Exception)")
                
        log_print(f"\n{'='*20} LIMIT SQUARE OFF MANAGEMENT FINISHED {'='*20}")
        log_print("\n--- Limit Square Off Summary ---")
        for item in square_off_summary:
            log_print(f"* {item}")
        log_print("---------------------------------")
        return square_off_summary



    # --- NEW FUNCTION FOR DYNAMIC TICK SIZE ---
    def get_tick_size(price):
        """
        Returns the correct tick size based on the stock price as per NSE rules.
        """
        if price <= 250:
            return 0.01
        elif 250 < price <= 1000:
            return 0.05
        elif 1000 < price <= 5000:
            return 0.10
        elif 5000 < price <= 10000:
            return 0.50
        elif 10000 < price <= 20000:
            return 1.00
        else:  # price > 20000
            return 5.00

    # NEW FUNCTION: Round price to nearest tick size
    def round_to_nearest_tick(price, base_price):
        """
        Rounds a given price to the nearest multiple of the specified tick size,
        which is dynamically determined by the base price.
        """
        tick_size = get_tick_size(base_price)
        return round(price / tick_size) * tick_size
    # --- NEW FUNCTION: Round price down to N ticks ---
    # --- REVISED FUNCTION: round_down_to_n_ticks to fix float precision ---
    def round_down_to_n_ticks(price, base_price_for_tick_calc, n_ticks_lower):
        """
        Rounds a given price down by a specific number of ticks (n_ticks_lower),
        ensuring the final price is still a multiple of the dynamically calculated tick size
        AND applying final rounding to fix floating-point errors.
        """
        # 1. Determine the tick size
        tick_size = get_tick_size(base_price_for_tick_calc)
        
        # 2. Calculate the total deduction
        total_deduction = n_ticks_lower * tick_size
        
        # 3. Calculate the new raw price
        new_raw_price = price - total_deduction
        
        # 4. Round the final price to the nearest multiple of the tick size
        rounded_price = round(new_raw_price / tick_size) * tick_size
        
        # Optional safety: Ensure we don't accidentally round up and exceed the raw price
        if rounded_price > new_raw_price:
            rounded_price -= tick_size
            
        # --- CRITICAL FIX: Final explicit rounding to fix floating-point precision ---
        # Since the maximum precision needed is two decimal places (for 0.01 tick size), 
        # we explicitly round the result to 2 decimal places.
        final_price = round(rounded_price, 2)
        # ---------------------------------------------------------------------------
            
        # Ensure the price is not negative
        return max(0.0, final_price)
    # NEW FUNCTION: Calculate custom limit price
    def calculate_custom_limit_price(base_price, percentage):
        """
        Calculates a new price by adding a percentage increase to a base price.
        The percentage is a value (e.g., 0.25), not a decimal (e.g., 0.0025).
        """
        return float(base_price) * (1 + percentage / 100)


    try:
        existing_Orders=client.order_report()
        #log_print(existing_Orders)
    except Exception as e:
                log_print("error in position api")

    stocks_in_OpenandClosedOrders=[]
    append_OpenOrders(existing_Orders,stocks_in_OpenandClosedOrders)

    try:
        exising_positions=client.positions()
    except Exception as e:
                log_print("error in position api")

    stocks_in_Positions=[]
    append_OpenPositions(exising_positions,stocks_in_Positions)



    log_print("\nstocks is position----------------\n" + str(stocks_in_Positions) + "\n")
    print("\nstocks is position----------------\n" + str(stocks_in_Positions) + "\n")
    stocks_with_open_position = set()
    for item in stocks_in_Positions:
    # item[0] is stockname, item[2] is net_qty (already checked to be non-zero in append_OpenPositions)
        stocks_with_open_position.add(item[0])
        
    
    squareoff_is_the_intention=False

    open_orders_for_modification = {}
    completed_orders_to_skip = set()
    temp_open_orders_for_display = []
    temp_closed_orders_for_display = []


    for item_stocks_in_OpenandClosedOrders in stocks_in_OpenandClosedOrders:
        trdSym = item_stocks_in_OpenandClosedOrders[0]
        order_type_from_api = item_stocks_in_OpenandClosedOrders[1]
        order_id = item_stocks_in_OpenandClosedOrders[2]
        order_status = item_stocks_in_OpenandClosedOrders[3]
        order_tag = item_stocks_in_OpenandClosedOrders[4]

        order_details_for_display = {
            "Symbol": trdSym,
            "Type": order_type_from_api,
            "Order ID": order_id,
            "Status": order_status,
            "Tag": order_tag
        }

        if order_status == "open":
            open_orders_for_modification[trdSym] = {
                "order_id": order_id,
                "order_type_api": order_type_from_api,
                "order_tag": order_tag
            }
            temp_open_orders_for_display.append(order_details_for_display)
            log_print(f"Identified open order for modification: {trdSym} (Order ID: {order_id})")
            print(f"Identified open order for modification: {trdSym} (Order ID: {order_id})")

        elif order_status == "complete" or order_status == "traded":
            completed_orders_to_skip.add((trdSym, order_type_from_api))
            temp_closed_orders_for_display.append(order_details_for_display)
            log_print(f"Identified completed order to skip: {trdSym} ({order_type_from_api})")
            print(f"Identified completed order to skip: {trdSym} ({order_type_from_api})")
            
            # --- START VERIFICATION LOOP ---
            matching_rows = df[df['stockname'] == trdSym]
            if not matching_rows.empty:
                try:
                    import mysql.connector
                    mydb_ver = mysql.connector.connect(host="localhost", user="root", password="root", database="markets")
                    mycursor_ver = mydb_ver.cursor()
                    for index, row in matching_rows.iterrows():
                        db_id_ver = row['id']
                        current_isvalid = str(row['isvalid']).strip()
                        new_isvalid = None
                        if current_isvalid == '1.5':
                            new_isvalid = '2'
                        elif current_isvalid == '2' or current_isvalid == '2.0':
                            new_isvalid = '3'
                        elif current_isvalid == '3' or current_isvalid == '3.0':
                            new_isvalid = '4'
                            
                        if new_isvalid:
                            mycursor_ver.execute(f"UPDATE {order_table} SET isvalid='{new_isvalid}' WHERE id={db_id_ver}")
                            mydb_ver.commit()
                            log_print(f"Triple Verification Loop: Updated isvalid from {current_isvalid} to {new_isvalid} for id={db_id_ver} in {order_table}")
                            df.at[index, 'isvalid'] = new_isvalid
                    mydb_ver.close()
                except Exception as e:
                    log_print(f"Error in Triple Verification Loop DB update: {e}")
            # --- END VERIFICATION LOOP ---

    if is_market_square_off:
        # If the script is run with 'SQOFF_MARKET', execute the market square-off
        market_square_off_positions(client, stocks_in_Positions, userid)
        continue # Skip the rest of the standard logic for this user

    if is_limit_square_off:
        # If the script is run with 'LIMIT_SQOFF_POSITIONS', execute the limit square-off management
        # Note: open_orders_for_modification is required by the function for cancellation logic
        limit_square_off_positions_and_manage(client, stocks_in_Positions, userid, open_orders_for_modification)
        continue # Skip the rest of the standard logic for this user
    # --- END SQOFF EXECUTION CHECKS ---

    log_print("\n--- OPEN ORDERS ---")
    if temp_open_orders_for_display:
        df_open_orders = pd.DataFrame(temp_open_orders_for_display)
        log_print(df_open_orders.to_string(index=False))
    else:
        log_print("No open orders found.")

    log_print("\n--- CLOSED/COMPLETED ORDERS ---")
    if temp_closed_orders_for_display:
        df_closed_orders = pd.DataFrame(temp_closed_orders_for_display)
        log_print(df_closed_orders.to_string(index=False))
    else:
        log_print("No closed/completed orders found.")

    log_print("\n--- NEW FUNCTIONALITY: All Open BUY Orders Report ---")
    # Call the new function
    all_open_buy_orders = get_all_open_buy_orders(stocks_in_OpenandClosedOrders)

    if all_open_buy_orders:
        log_print("Found the following open BUY orders (Future Stock) with placement time:")
        # Prepare data for a clean log_print
        report_data = []
        for symbol, details in all_open_buy_orders.items():
            time_str = details['order_datetime'].strftime('%Y-%m-%d %H:%M:%S') if details['order_datetime'] else 'N/A'
            report_data.append({
                "Symbol": symbol,
                "Order ID": details['order_id'],
                "Full Tag": details['order_tag_full'],
                "Placed Time (Local)": time_str
            })
        
        # Convert the list of dicts to a DataFrame for clean log_printing
        df_open_buy_report = pd.DataFrame(report_data)
        # log_print the DataFrame nicely
        log_print(df_open_buy_report.to_string(index=False))
    else:
        log_print("No open BUY orders (Future Stock) found via API.")
    log_print("------------------------------------------------------\n")







    # Initialize the summary lists here, before they are used.
    attempted_orders_summary = []
    successful_orders_summary = []
    failed_orders_summary = []


    log_print("\nTrying to new orders............future_order_count="+str(future_order_count)+"  order count= "+str(len(df))) # Adjusted log_print statement
    print("\nTrying to new orders............future_order_count="+str(future_order_count)+"  order count= "+str(len(df))) # Adjusted log_print statement
    counter=0


    # --- AUTO-CANCEL STALE OPEN BUY ORDERS (> 30s) TO RELEASE FUNDS ---
    if not df.empty and any(df['type'].astype(str).str.upper() == 'BUY') and all_open_buy_orders:
        now_local = datetime.now()
        for symbol, details in all_open_buy_orders.items():
            order_id = details['order_id']
            order_dt = details.get('order_datetime')
            if order_dt:
                age_seconds = (now_local - order_dt).total_seconds()
                if age_seconds > 30:
                    log_print(f"🧹 AUTO-CANCEL: Open BUY order for {symbol} (ID: {order_id}) is {age_seconds:.1f}s old (> 30s). Cancelling to release funds...")
                    try:
                        cancel_resp = client.cancel_order(order_id=str(order_id))
                        log_print(f"API Cancel Response for {symbol}: {cancel_resp}")
                    except Exception as e_c:
                        log_print(f"Warning during auto-cancel for {symbol}: {e_c}")

    if not df.empty:
        for i in df.index:
            db_id=df.loc[i,"id"]
            stockname=df.loc[i,"stockname"]
            lotcount=df.loc[i,"quantity"]
            transaction_type=str(df.loc[i,"type"])
            order_rank=df.loc[i,"order_rank"]
            if order_rank is None:
                order_rank="LIMIT"

            scripcode=findscripcode(stockname)
            lot_size=find_lot_size(stockname)

            log_print(str(scripcode))
            log_print(str(lot_size))

            if (scripcode is None or lot_size is None ):
                log_print("ERROR with finding script code for a stockname "+stockname+"; hence continuing")
                continue
            if scripcode==0 or lot_size==0:
                log_print("something didn't work for this stock "+stockname+" "+str(lot_size))
                continue

            order_to_modify_details = open_orders_for_modification.get(stockname)
            is_order_to_modify = (order_to_modify_details and
                                  order_to_modify_details["order_type_api"] == transaction_type)

            if is_order_to_modify:
                action_type = "cancel"
                order_id_to_cancel = order_to_modify_details["order_id"]
                log_print(f"--- Initiating order {action_type} for {scripcode} (Order ID: {order_id_to_cancel}) ---")

                total_attempts = 3
                retry_delay_seconds = 1
                cancel_successful = False
                last_known_cancel_response = None
                order_id_for_cancel_api = str(order_id_to_cancel)

                for attempt_count in range(1, total_attempts + 1):
                    log_print(f"\nAttempt {attempt_count}/{total_attempts} to {action_type} order for {scripcode} (Order ID: {order_id_to_cancel})")
                    if attempt_count > 1:
                        log_print(f"Waiting for {retry_delay_seconds} seconds before retrying...")
                        sys_time.sleep(retry_delay_seconds)
                    try:
                        cancel_response = client.cancel_order(order_id=order_id_for_cancel_api)
                        last_known_cancel_response = cancel_response
                        log_print(f"API Response ({action_type} attempt {attempt_count}): {cancel_response}")

                        if cancel_response and (cancel_response.get('stat') == 'Ok' or cancel_response.get('stCode') == 200):
                            log_print(f"SUCCESS: Order for {scripcode} {action_type}led successfully on attempt {attempt_count}.")
                            cancel_successful = True
                            break
                        # START MODIFICATION: Handle the specific "order is cancelled" error
                        elif cancel_response and 'order is cancelled' in cancel_response.get('errMsg', ''):
                            log_print(f"INFO: Order for {stockname} was already cancelled by the broker system. Treating as SUCCESS.")
                            cancel_successful = True
                            break
                        # END MODIFICATION
                        else:
                            log_print(f"FAILURE ({action_type} Attempt {attempt_count}): API error - {cancel_response.get('errMsg')} (stCode: {cancel_response.get('stCode')}).")
                            if attempt_count == total_attempts:
                                log_print(f"Max {total_attempts} attempts reached. No more retries for cancellation.")
                    except Exception as e:
                        log_print(f"EXCEPTION ({action_type} Attempt {attempt_count}): A Python exception occurred - {e}")
                        last_known_cancel_response = {'stCode': 'PYTHON_EXCEPTION', 'errMsg': str(e), 'stat': 'Not_Ok', 'attempt': attempt_count}
                        if attempt_count == total_attempts:
                            log_print(f"Max {total_attempts} attempts reached. No more retries after Python exception.")

                log_print(f"\n--- Order {action_type} process for {scripcode} concluded ---")
                if cancel_successful:
                    log_print(f"Final Status: Order was successfully {action_type}led for {scripcode}. Proceeding to place new order.")
                    logger_func(logger,f"Order {action_type}led successfully for {scripcode} with ID {order_id_to_cancel}","INFO")
                    attempted_orders_summary.append(stockname)
                    successful_orders_summary.append(stockname)
                else:
                    logger_func(logger,f"Error cancelling order for {scripcode} with ID {order_id_to_cancel}\n{str(last_known_cancel_response.get('errMsg', 'Unknown error during cancellation'))}","CRITICAL")
                    log_print(f"Final Status: Order could NOT be {action_type}led for {scripcode} after {total_attempts} attempts. Skipping new order placement for this stock.")
                    attempted_orders_summary.append(stockname)
                    failed_orders_summary.append(stockname)
                    continue

            elif (stockname, transaction_type) in completed_orders_to_skip and order_table!='markets.orders_AMO':
                
                # Default action is to skip (as it's in the completed set)
                should_skip = True

                if transaction_type == 'BUY':
                    # OVERRIDE skip only if the stock is NOT in an open position.
                    if stockname not in stocks_with_open_position:
                        should_skip = False
                        log_print(f"Completed BUY order for {stockname} found, but position is zero. Allowing new BUY order.")
                    else:
                        log_print(f"Skipping new BUY order for {stockname}. Completed BUY found and stock is still in position.")
                
                elif transaction_type == 'SELL':
                    # Always skip a completed SELL order.
                    should_skip = True
                    log_print(f"Skipping completed SELL order: {stockname} {transaction_type} (Always skipped).")

                if should_skip:
                    continue

            if counter >= future_order_count:
                if not squareoff_is_the_intention:
                    log_print("Breaking as Ordered enough stocks (for new orders)")
                    break
                else:
                    log_print("Square off is the intention, not breaking with count limits for new orders.")


            log_print("\n====== ORDER ATTEMPT ======")
            log_print(f"Order #:        {counter + 1}")
            log_print(f"Stock Name:     {stockname}")
            log_print(f"Fut Symbol:     {scripcode}")
            log_print(f"Transaction:    {transaction_type}")
            log_print(f"Lot Size:       {lot_size}")
            log_print(f"Lot Count:      {lotcount}")
            quantity=int(lot_size)*int(lotcount)
            log_print(f"Total Qty:      {quantity}")
            limitprice=float(df.loc[i,"limitprice"])
            log_print(f"Limit Price:    {limitprice}")
            ismarket_raw = str(df.loc[i,"ismarket"]).upper().strip() if df.loc[i,"ismarket"] is not None else '0'
            ismarket = 1 if ismarket_raw in ['1', 'TRUE'] else 0
            log_print(f"Is Market:      {ismarket}")
            order_rank=df.loc[i,"order_rank"]
            if order_rank is None:
                order_rank="LIMIT"
            log_print(f"Order Rank:     {order_rank}")
            now=datetime.now().strftime("%d_%m_%Y %H_%M_%S_%f")
            now=now[-6:]
            tag=order_rank+"_"+stockname[:2]+"_"+"LIM"+"_"+now
            log_print(f"Tag:            {tag}")
            log_print(f"User:           {Kotak_user} ({userid})")
            log_print(f"Expiry Month:   {EXPIRY_MONTH}")
            log_print("===========================\n")

            transaction_type_neo="B" if transaction_type=="BUY" else "S"
            quantity=int(lot_size)*int(lotcount)
            limitprice=float( df.loc[i,"limitprice"])
            if limitprice==-55555:
                log_print ("limit price not updated, skipping : " + stockname)
                continue
            ismarket_raw2 = str(df.loc[i,"ismarket"]).upper().strip() if df.loc[i,"ismarket"] is not None else '0'
            ismarket = 1 if ismarket_raw2 in ['1', 'TRUE'] else 0

            thismonthfut=month_shortname+"FUT"


            now=datetime.now().strftime("%d_%m_%Y %H_%M_%S_%f")
            now=now[-6:]
            tag=order_rank+"_"+stockname[:2]+"_"+"LIM"+"_"+now

            

            now_local = datetime.now() 
            current_time_only = now_local.time()

            # Define the Fallback adjustment function/value
            # This is the adjustment that will be applied to ALL users in the fallback window
            FALLBACK_N_TICKS_LOWER = 1 
            FALLBACK_ADJUSTMENT_VALUE = 0.50 # Example: a fixed value if you don't use round_down_to_n_ticks

            # --- MAIN LOGIC BLOCK: BASED ON TRANSACTION TYPE ---

            if transaction_type == "BUY":
                log_print("\n--- BUY Transaction Logic Activated ---")
                
                # Define the time window for the BUY adjustment
                BUY_ADJUSTMENT_START_TIME = time(15, 13, 1) 
                BUY_ADJUSTMENT_END_TIME = time(15, 26, 30)

                is_within_buy_adjustment_window = (
                    current_time_only >= BUY_ADJUSTMENT_START_TIME and 
                    current_time_only <= BUY_ADJUSTMENT_END_TIME
                )

                if is_within_buy_adjustment_window:
                    log_print(f"Applying price adjustment logic for BUY as current time ({current_time_only}) is within the BUY window.")

                    if user_from_API == 'MANISHA':
                        # Logic for MANISHA (n_ticks_lower = 4)
                        new_limit_price = round_down_to_n_ticks(
                            price=limitprice, 
                            base_price_for_tick_calc=limitprice, 
                            n_ticks_lower= 1
                        )
                        log_print(f"[MANISHA-BUY] Adjusted Original: {limitprice} | New Adjusted: {new_limit_price}")
                        limitprice = new_limit_price

                    elif user_from_API == 'RAJULA':
                        # Logic for RAJULA (n_ticks_lower = 2 - example)
                        new_limit_price = round_down_to_n_ticks(
                            price=limitprice, 
                            base_price_for_tick_calc=limitprice, 
                            n_ticks_lower= 2
                        )
                        log_print(f"[RAJULA-BUY] Adjusted Original: {limitprice} | New Adjusted: {new_limit_price}")
                        limitprice = new_limit_price

                    else:
                        # Default case for all other users within the BUY time window
                        log_print(f"[DEFAULT-BUY] No specific adjustment for user: {user_from_API}. Price remains: {limitprice}")

                else:
                    # BUY transaction, but outside the primary adjustment window
                    log_print(f"BUY adjustment logic skipped. Current time is OUTSIDE the BUY window. Price remains: {limitprice}")


            # --- SELL TRANSACTION LOGIC (Covers all cases where transaction_type != "BUY") ---
            else: # This block now covers transaction_type == "SELL"
                log_print(f"\n--- SELL Transaction Logic Activated (Assumed: SELL) ---")

                # --- FIRST TICK ADJUST SELL WINDOW (User-Specific) ---
                FIRST_TICK_ADJUST_SELL_START_TIME = time(9, 15, 0)  
                FIRST_TICK_ADJUST_SELL_END_TIME = time(9, 16, 0)    

                is_within_first_tick_sell_window = (
                    current_time_only >= FIRST_TICK_ADJUST_SELL_START_TIME and 
                    current_time_only <= FIRST_TICK_ADJUST_SELL_END_TIME
                )

                # --- FALLBACK SELL ADJUSTMENT WINDOW (Same for all users) ---
                FALLBACK_SELL_START_TIME = time(9, 28, 1)
                FALLBACK_SELL_END_TIME = time(9, 40, 30) 

                is_within_fallback_sell_window = (
                    current_time_only >= FALLBACK_SELL_START_TIME and 
                    current_time_only <= FALLBACK_SELL_END_TIME
                )


                # 1. Check First Tick Adjust SELL Window (User-Specific)
                if is_within_first_tick_sell_window:
                    log_print(f"Applying FIRST TICK ADJUST SELL (User-Specific) for {current_time_only}.")

                    new_limit_price = round_down_to_n_ticks(
                        price=limitprice, 
                        base_price_for_tick_calc=limitprice, 
                        n_ticks_lower= 2 # Using the common fallback value
                    )
                    log_print(f"[FALLBACK-SELL] Adjustment for ALL users. Original: {limitprice} | New Adjusted: {new_limit_price} (Ticks: {FALLBACK_N_TICKS_LOWER})")
                    limitprice = new_limit_price
                        
                # 2. Check Fallback SELL Window (Same for All Users)
                elif is_within_fallback_sell_window:
                    log_print(f"Applying FALLBACK SELL adjustment (Same for All) for {current_time_only}.")
                    
                    # Apply the SAME adjustment logic for ALL users in this fallback window
                    new_limit_price = round_down_to_n_ticks(
                        price=limitprice, 
                        base_price_for_tick_calc=limitprice, 
                        n_ticks_lower= 1 # Using the common fallback value
                    )
                    log_print(f"[FALLBACK-SELL] Adjustment for ALL users. Original: {limitprice} | New Adjusted: {new_limit_price} (Ticks: {FALLBACK_N_TICKS_LOWER})")
                    limitprice = new_limit_price

                else:
                    # SELL transaction, but outside both adjustment windows
                    log_print(f"SELL adjustment logic skipped. Current time ({current_time_only}) is outside ALL SELL windows. Price remains: {limitprice}")

            # --- END OF LOGIC ---
            log_print(f"\nFinal limit price to be used for order: {limitprice}")


            #log_print("*********skipping")
            #continue
            amo_value = "NO"
            if order_table == "markets.orders_AMO":
                amo_value = "YES"

            if transaction_type=="BUY" or transaction_type=="SELL":
                try:
                    if limitprice>0:
                        logger_func(logger,"Processing limit/market Order with tagname "+tag,"INFO")
                        #log_print("*******amo_value=",amo_value,order_table)
                        if amo_value == "YES":
                            logger_func(logger,f"Placing AMO limit order for {stockname} with tagname {tag}", "INFO")

                        total_attempts = 3
                        retry_delay_seconds = 1
                        base_tag_for_order = tag
                        order_action_successful = False
                        last_known_response = None
                        action_type = "place"

                        for attempt_count in range(1, total_attempts + 1):
                            current_attempt_tag = f"{base_tag_for_order}_A{attempt_count}"
                            if attempt_count > 1:
                                sys_time.sleep(retry_delay_seconds)
                            try:
                                if get_trading_setting("place_future_order"):
                                    order_response=(client.place_order(exchange_segment="nse_fo", product="NRML", price=str(limitprice), order_type="L", quantity=str(quantity), validity="DAY", trading_symbol=scripcode,
                                                        transaction_type=transaction_type_neo, amo=amo_value, disclosed_quantity="0", market_protection="0",
                                                           trigger_price="0", tag=tag))
                                else:
                                    order_response = {"stat": "Ok", "stCode": 200, "message": "MOCK SUCCESS (FUTURES OFF)"}
                                log_print(order_response)
                                last_known_response = order_response

                                if order_response and (order_response.get('stat') == 'Ok' or order_response.get('stCode') == 200):
                                    try:
                                        import mysql.connector
                                        mydb = mysql.connector.connect(host="localhost", user="root", password="root", database="markets")
                                        mycursor = mydb.cursor()
                                        mycursor.execute(f"UPDATE {order_table} SET isvalid='1.5' WHERE id={db_id}")
                                        mydb.commit()
                                        mydb.close()
                                        log_print(f"Successfully updated isvalid='1.5' for id={db_id}")
                                    except Exception as e:
                                        log_print(f"Error updating DB: {e}")
                                    order_action_successful = True
                                    counter+=1
                                    break
                                is_specific_target_error = False
                                if order_response and order_response.get('stCode') == 100021:
                                    api_error_message = order_response.get('errMsg', '')
                                    normalized_api_message = ' '.join(api_error_message.lower().split())
                                    target_message_fragment = 'invalid access type'
                                    if target_message_fragment in normalized_api_message:
                                        is_specific_target_error = True
                                if is_specific_target_error:
                                    if attempt_count == total_attempts:
                                        log_print(f"Max {total_attempts} attempts reached. No more retries for this specific error.")
                                else:
                                    break
                            except Exception as e:
                                sys_time.sleep(0.2)
                                last_known_response = {'stCode': 'PYTHON_EXCEPTION', 'errMsg': str(e), 'stat': 'Not_Ok', 'attempt': attempt_count}
                                if attempt_count == total_attempts:
                                    log_print(f"Max {total_attempts} attempts reached. No more retries after Python exception.")
                        if order_action_successful:
                            attempted_orders_summary.append(stockname)
                            print(f"New oders  placed successfully-{stockname}")
                            successful_orders_summary.append(stockname)
                        else:
                            attempted_orders_summary.append(stockname)
                            failed_orders_summary.append(stockname)
                            try:
                                err_str = last_known_response.get('errMsg', 'Unknown Error') if isinstance(last_known_response, dict) else str(last_known_response)
                                send_telegram_failure_alert_async(stockname, transaction_type, limitprice, quantity, err_str)
                            except Exception as e_fail_log:
                                pass
                        logger_func(logger,f"Order {action_type}d with tagname "+tag,"INFO")
                        

                    elif ismarket ==1:
                        logger_func(logger,"Processing market Order with tagname "+tag,"INFO")
                        if amo_value == "YES":
                            logger_func(logger,f"Placing AMO market order for {stockname} with tagname {tag}", "INFO")

                        log_print ("trying to place order Market order ")
                        order_response = client.place_order(exchange_segment="nse_fo", product="NRML", price="0", order_type="MKT", quantity=str(quantity), validity="DAY", trading_symbol=scripcode,
                                                transaction_type=transaction_type_neo, amo=amo_value, disclosed_quantity="0", market_protection="0",
                                                   trigger_price="0", tag=tag)
                        log_print (order_response)
                        if order_response and (order_response.get('stat') == 'Ok' or order_response.get('stCode') == 200):
                            try:
                                import mysql.connector
                                mydb = mysql.connector.connect(host="localhost", user="root", password="root", database="markets")
                                mycursor = mydb.cursor()
                                mycursor.execute(f"UPDATE {order_table} SET isvalid='1.5' WHERE id={db_id}")
                                mydb.commit()
                                mydb.close()
                                log_print(f"Successfully updated isvalid='1.5' for id={db_id}")
                            except Exception as e:
                                log_print(f"Error updating DB: {e}")
                        counter+=1
                        logger_func(logger,"Order  created with tagname "+tag,"INFO")
                    else:
                        if limitprice== -1:
                            logger_func(logger,"unable to get limit price ","INFO")
                        logger_func(logger,"some error ","INFO")
                except Exception as e:
                    logger_func(logger,"Error in Order with tagname "+tag+"\n"+str(e),"CRITICAL")
                    log_print(str(e))

            else:
                try:
                    if transaction_type=="STOPLOSSBUY":
                        logger_func(logger,"Processing stoploss BUY Order with tagname "+tag,"INFO")
                        if get_trading_setting("place_future_order"):
                            client.place_order(order_type = "N", instrument_token = scripcode, transaction_type = "BUY",
                                            quantity = quantity, price = 0, disclosed_quantity = 0, trigger_price = limitprice,
                                                 validity = "GFD", variety = "REGULAR", tag = tag)
                        logger_func(logger,"Order  created with tagname "+tag,"INFO")
                        counter+=1

                    if  transaction_type=="STOPLOSSSELL":
                        logger_func(logger,"Processing stoploss SELL Order with tagname "+tag,"INFO")
                        if get_trading_setting("place_future_order"):
                            client.place_order(order_type = "N", instrument_token = scripcode, transaction_type = "SELL",
                                            quantity = quantity, price = 0, disclosed_quantity = 0, trigger_price = limitprice,
                                                 validity = "GFD", variety = "REGULAR", tag = tag)
                        logger_func(logger,"Order  created with tagname "+tag,"INFO")
                        counter+=1
                except Exception as e:
                    logger_func(logger,"Error in Order with tagname "+tag+"\n"+str(e),"CRITICAL")
                    log_print(str(e))
    # --- FIX END ---


    def insert_to_table(tablename,columnames_values):
        import mysql.connector

        mydb = mysql.connector.connect(
        host="localhost",
        user="root",
        password="root",
        database="markets"
        )
        column_names= (",").join(columnames_values.keys())
        mycursor = mydb.cursor()
        sql = "INSERT INTO "+tablename+" ("+column_names+") VALUES ('"+("','").join(str(v) for v in columnames_values.values())+"\')"
        log_print(sql)
        mycursor.execute(sql)

        mydb.commit()
        log_print(mycursor.rowcount + " record inserted.")

    map={}
    toinsert_map={}

    log_print(f"\n======= ORDER PLACEMENT SUMMARY FOR {userid} =======")
    log_print(f"Total Orders Attempted : {len(attempted_orders_summary)}")
    log_print(f"Orders Successfully Placed : {len(successful_orders_summary)}")
    print(f"Orders Successfully Placed : {len(successful_orders_summary)}")
    log_print(f"Orders Failed : {len(failed_orders_summary)}")
    log_print("\nStocks Attempted       :" + str(attempted_orders_summary))
    log_print("Stocks Succeeded       :" + str(successful_orders_summary))
    print("Stocks Succeeded       :" + str(successful_orders_summary))
    log_print("Stocks Failed          :" + str(failed_orders_summary))
    log_print("========================================\n")
    
    CANCELLATION_THRESHOLD_SECONDS = 20 
    now_local = datetime.now() 

    # --- START OF NEW TIME WINDOW CHECK ---
    # Define the time window for cancellation (e.g., 9:15 AM to 3:30 PM)
    CANCELLATION_START_TIME = time(15, 13, 0)
    CANCELLATION_END_TIME = time(15, 29, 30)
    
    current_time_only = datetime.now().time()
    
    is_within_cancellation_window = (
        current_time_only >= CANCELLATION_START_TIME and 
        current_time_only <= CANCELLATION_END_TIME
    )

    if not is_within_cancellation_window:
        log_print(f"\nINFO: Skipping auto-cancellation. Current time ({current_time_only.strftime('%H:%M:%S')}) is outside the allowed window ({CANCELLATION_START_TIME.strftime('%H:%M:%S')} to {CANCELLATION_END_TIME.strftime('%H:%M:%S')}).")
    # --- END OF NEW TIME WINDOW CHECK ---

    log_print(f"\n--- START: Auto-Cancellation of Old Open BUY Orders (Threshold: {CANCELLATION_THRESHOLD_SECONDS}s) ---")
    cancellation_summary = []

    for stockname, details in all_open_buy_orders.items():
        order_id = details['order_id']
        order_datetime = details['order_datetime'] # This is the datetime object derived from boeSec
        
        if order_datetime is None:
            log_print(f"Warning: Skipping {stockname} (ID: {order_id}) due to missing placement time.")
            cancellation_summary.append(f"{stockname} (ID: {order_id}) - SKIPPED (No Time)")
            continue

        # Calculate the difference between now and when the order was placed
        time_difference = now_local - order_datetime
        
        # Check if the order is older than the 60-second threshold AND if we are within the allowed time window
        if is_within_cancellation_window and time_difference.total_seconds() > CANCELLATION_THRESHOLD_SECONDS:
            log_print(f"ACTION: Order for {stockname} is {time_difference.total_seconds():.2f}s old (>{CANCELLATION_THRESHOLD_SECONDS}s). Attempting cancellation...")
            
            # Call the cancellation utility function
            was_cancelled = cancel_order_by_id(client, order_id, stockname)
            
            if was_cancelled:
                cancellation_summary.append(f"{stockname} (ID: {order_id}) - SUCCESS (Old)")
            else:
                cancellation_summary.append(f"{stockname} (ID: {order_id}) - FAILED (Old)")
        else:
            # Order is within the threshold OR outside the cancellation window
            reason = "Threshold"
            if not is_within_cancellation_window:
                reason = "Time Window"

            log_print(f"INFO: Order for {stockname} (ID: {order_id}) kept open ({reason} check failed). Age: {time_difference.total_seconds():.2f}s.")
            cancellation_summary.append(f"{stockname} (ID: {order_id}) - KEPT ({reason})")

    log_print("\n--- FINAL AUTO-CANCELLATION SUMMARY ---")
    for result in cancellation_summary:
        log_print(f"* {result}")
    log_print("----------------------------------------------------\n")
