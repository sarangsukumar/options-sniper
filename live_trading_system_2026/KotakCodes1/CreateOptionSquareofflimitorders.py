import calendar
import time
import database as database
import random
import traceback
import logging
from datetime import datetime, time # Import 'time' for setting hours, minutes, seconds
from decimal import Decimal, ROUND_UP, ROUND_DOWN, ROUND_HALF_UP, getcontext
import pandas as pd
import os
import pickle
import sys
import json
import base64
import requests
from neo_api_client import NeoAPI

# TARGET_PROFIT_PER_ORDER will be set dynamically based on input parameter
# --- Base Paths and Configuration ---
BASE_PATH = "/home/ubuntu/KotakCodes1/" # This should point to your main KotakCodes1 directory
CSV_PATH = BASE_PATH # Path for CSV files (assuming kotak_auth_userid.csv is here)

# --- Configure logging ---
now_str = datetime.now().strftime("%d_%m_%Y_%H_%M_%S_%f")
logpath = os.path.join(os.getcwd(), "logs")
os.makedirs(logpath, exist_ok=True) # Ensure logs directory exists
logfilepath = os.path.join(logpath, "create_option_limit_orders_Logs_" + now_str[-6:] + ".log") # Generic log file name

# Create a logger specific to this script
logger = logging.getLogger(__name__)

# Add a file handler
file_handler = logging.FileHandler(logfilepath)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Add a stream handler to output logs to console
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(formatter)
logger.addHandler(stream_handler)

logger.setLevel(logging.INFO) # Set default logging level

def logger_func(logger_obj, message, log_type="INFO"):
    """
    Logs a message with the specified logger object and log type.
    """
    if log_type == "INFO":
        logger_obj.info(message)
    elif log_type == "CRITICAL":
        logger_obj.critical(message)
    elif log_type == "WARNING":
        logger_obj.warning(message)
    else:
        logger_obj.info(message)
    sys.stdout.flush() # Ensure immediate output to console

# --- User ID and Order Type from Command Line Arguments ---
logger_func(logger, "Starting script execution for option limit orders.", "INFO")

if len(sys.argv) < 3:
    logger_func(logger, "Error: User ID and Order Type (AMO/custom) must be provided as command-line arguments. Exiting.", "CRITICAL")
    logger_func(logger, "Usage: python script_name.py <userid> <ordertype>", "INFO")
    sys.exit(1)

userid = sys.argv[1]
order_type_param = sys.argv[2].lower() # Convert to lowercase for consistent comparison
logger_func(logger, f"User ID provided: {userid}", "INFO")
logger_func(logger, f"Order Type parameter provided: {order_type_param}", "INFO")

# --- Dynamic Configuration based on Order Type ---
order_table = ""
TARGET_PROFIT_PERCENTAGE_PER_ORDER = 0 # Changed to percentage
is_future_value = "" # Value for the 'is_future' column in the database

if order_type_param == "amo":
    order_table = "markets.orders_option_AMO"
    TARGET_PROFIT_PERCENTAGE_PER_ORDER = 50 # Set to 20%
    is_future_value = "AMO"
    logger_func(logger, f"Configuration: AMO orders selected. Table: {order_table}, Target Profit Percentage: {TARGET_PROFIT_PERCENTAGE_PER_ORDER}%", "INFO")
elif order_type_param == "custom":
    order_table = "markets.orders_option"
    TARGET_PROFIT_PERCENTAGE_PER_ORDER = 50 # Set to 5%
    is_future_value = "OPTIONS"
    logger_func(logger, f"Configuration: Custom orders selected. Table: {order_table}, Target Profit Percentage: {TARGET_PROFIT_PERCENTAGE_PER_ORDER}%", "INFO")
else:
    logger_func(logger, f"Error: Invalid Order Type '{order_type_param}'. Must be 'AMO' or 'custom'. Exiting.", "CRITICAL")
    sys.exit(1)


# --- Initialize credential variables ---
Kotak_user = None
payload = None
consumer_key = None
consumer_secret = None
MPIN = None
password = None

# --- Load User-Specific Credentials from CSV ---
logger_func(logger, f"Attempting to load credentials from {os.path.join(CSV_PATH, 'kotak_auth_userid.csv')}", "INFO")
try:
    auth_df = pd.read_csv(os.path.join(CSV_PATH, "kotak_auth_userid.csv"))
    auth_data = auth_df[auth_df['userid'] == userid]

    if not auth_data.empty:
        auth_row = auth_data.iloc[0]
        Kotak_user = auth_row['Kotak_user']
        user_from_API = auth_row.get('user_from_API', Kotak_user)
        payload_username = auth_row['payload_username']
        payload_password = auth_row['payload_password']
        payload = f'grant_type=password&username={payload_username}&password={payload_password}'
        consumer_key = auth_row['consumer_key']
        consumer_secret = auth_row['consumer_secret']
        MPIN = int(auth_row['MPIN'])
        password = auth_row['password']
        logger_func(logger, f"Credentials loaded successfully for userid: {userid} ({Kotak_user}, alias: {user_from_API}) from CSV.", "INFO")
    else:
        logger_func(logger, f"Error: User ID '{userid}' not found in kotak_auth_userid.csv. Please check the CSV file. Exiting.", "CRITICAL")
        sys.exit(1)
except FileNotFoundError:
    logger_func(logger, f"Error: kotak_auth_userid.csv not found at {os.path.join(CSV_PATH, 'kotak_auth_userid.csv')}. Please ensure the file exists. Exiting.", "CRITICAL")
    sys.exit(1)
except Exception as e:
    logger_func(logger, f"An error occurred while loading credentials from CSV: {e}", "CRITICAL")
    logger_func(logger, traceback.format_exc(), "CRITICAL")
    sys.exit(1)

# --- Validate that essential credentials are set ---
if not payload or not consumer_key or not consumer_secret or MPIN is None or password is None:
    logger_func(logger, f"Critical credentials (payload, consumer_key, consumer_secret, MPIN, or password) are not fully set for userid: {userid} ({Kotak_user}). Exiting.", "CRITICAL")
    sys.exit(1)

# --- TOTP Authentication ---
mobile_number = str(auth_row.get('mobile_number', '')).strip()
totp_secret = str(auth_row.get('totp_secret', '')).strip()

if not mobile_number or not totp_secret:
    logger_func(logger, "Missing mobile_number or totp_secret in CSV", "CRITICAL")
    sys.exit(1)

import pyotp
try:
    logger_func(logger, "Initializing NeoAPI client and logging in via TOTP...", "INFO")
    client = NeoAPI(consumer_key=consumer_key, environment='prod', neo_fin_key="neotradeapi")
    totp_code = pyotp.TOTP(totp_secret).now()
    formatted_mobile = mobile_number if mobile_number.startswith('+') else f"+91{mobile_number}"
    
    login_resp = client.totp_login(mobile_number=formatted_mobile, ucc=userid, totp=totp_code)
    if login_resp and 'error' in login_resp:
        raise Exception(f"TOTP Login Error: {login_resp['error']}")
        
    val_resp = client.totp_validate(mpin=str(MPIN))
    if val_resp and 'error' in val_resp:
        raise Exception(f"MPIN Validation Error: {val_resp['error']}")
    
    logger_func(logger, f"NEO client logged in successfully via TOTP: {Kotak_user}", "INFO")
except Exception as e:
    logger_func(logger, f"TOTP Login Failed for {Kotak_user}: {e}", "CRITICAL")
    logger_func(logger, traceback.format_exc(), "CRITICAL")
    sys.exit(1)

# --- Database Insertion Function ---
def insert_to_table(tablename, columnames_values):
    """
    Inserts data into the specified database table.
    """
    import mysql.connector

    try:
        mydb = mysql.connector.connect(
            host="localhost",
            user="root",
            password="root",
            database="markets"
        )
        column_names = ", ".join(columnames_values.keys())
        # Use parameterized query to prevent SQL injection and handle data types correctly
        placeholders = ", ".join(["%s"] * len(columnames_values))
        sql = f"INSERT INTO {tablename} ({column_names}) VALUES ({placeholders})"
        
        mycursor = mydb.cursor()
        mycursor.execute(sql, tuple(columnames_values.values()))
        mydb.commit()
        logger_func(logger, f"{mycursor.rowcount} record inserted into {tablename}.", "INFO")

    except mysql.connector.Error as err:
        logger_func(logger, f"MySQL Error: {err}", "CRITICAL")
        logger_func(logger, traceback.format_exc(), "CRITICAL")
    except Exception as e:
        logger_func(logger, f"An unexpected error occurred during database insertion: {e}", "CRITICAL")
        logger_func(logger, traceback.format_exc(), "CRITICAL")
    finally:
        if 'mydb' in locals() and mydb.is_connected():
            mycursor.close()
            mydb.close()

# --- NSE Tick Size and Custom Limit Price Calculation ---
def get_nse_tick_size(price: Decimal) -> Decimal:
    """
    Determines the NSE tick size based on the given price.
    Prices are Decimals.
    """
    # This function is now effectively bypassed for options, as tick_size_d is hardcoded in calculate_limit_price_for_profit
    if price < Decimal('250'):
        return Decimal('0.01')
    elif price < Decimal('1000'): # Covers 250 <= price < 1000
        return Decimal('0.05')
    elif price < Decimal('5000'): # Covers 1000 <= price < 5000
        return Decimal('0.10')
    elif price < Decimal('10000'): # Covers 5000 <= price < 10000
        return Decimal('0.50')
    elif price < Decimal('20000'): # Covers 10000 <= price < 20000
        return Decimal('1.00')
    else: # Covers price >= 20000
        return Decimal('5.00')

def calculate_custom_limit_price(last_day_executed_price: float, targeted_percentage: float) -> float:
    """
    Calculates a custom limit price based on a percentage.
    This function is no longer used for the primary limit price calculation,
    but remains for reference if needed elsewhere.
    """
    try:
        if last_day_executed_price is None or targeted_percentage is None:
            raise TypeError("Inputs cannot be None")

        # Convert inputs to Decimal for precision
        last_price_d = Decimal(str(last_day_executed_price))
        targeted_percentage_d = Decimal(str(targeted_percentage))

        # 1. Determine NSE tick size based on last_day_executed_price
        tick_size_d = get_nse_tick_size(last_price_d)

        # 2. Calculate the initial target limit order price
        price_change_d = last_price_d * (targeted_percentage_d / Decimal('100'))
        initial_limit_price_d = last_price_d + price_change_d

        # 3. Adjust the initial limit price to the relevant NSE tick
        adjusted_to_tick_price_d: Decimal
        if targeted_percentage_d > Decimal('0'): # Price is increasing
            if initial_limit_price_d % tick_size_d == Decimal('0'):
                 adjusted_to_tick_price_d = initial_limit_price_d
            else:
                 adjusted_to_tick_price_d = ((initial_limit_price_d // tick_size_d) + Decimal('1')) * tick_size_d
        elif targeted_percentage_d < Decimal('0'): # Price is decreasing
            adjusted_to_tick_price_d = (initial_limit_price_d // tick_size_d) * tick_size_d
        else: # targeted_percentage_d == 0
            quotient = initial_limit_price_d / tick_size_d
            rounded_quotient = quotient.quantize(Decimal('1'), rounding=ROUND_HALF_UP)
            adjusted_to_tick_price_d = rounded_quotient * tick_size_d
            
        num_tick_decimals = abs(tick_size_d.as_tuple().exponent)
        adjusted_to_tick_price_d = adjusted_to_tick_price_d.quantize(Decimal('0.1') ** num_tick_decimals)

        # 4. Apply the original custom rounding logic (ensure price ends in .x0 or .x5)
        price_str_for_custom_logic = f"{adjusted_to_tick_price_d:.2f}"

        last_digit_char = price_str_for_custom_logic[-1]
        last_digit_int = int(last_digit_char)

        if 0 <= last_digit_int < 5:
            modified_last_digit_char = '0'
        else:  # last_digit_int is 5, 6, 7, 8, or 9
            modified_last_digit_char = '5'

        final_price_str = price_str_for_custom_logic[:-1] + modified_last_digit_char
        final_price_d = Decimal(final_price_str)
        
        return float(final_price_d)

    except TypeError:
        return -55555
    except Exception as e:
        logger_func(logger, f"An unexpected error occurred in calculate_custom_limit_price: {e}", "CRITICAL")
        logger_func(logger, traceback.format_exc(), "CRITICAL")
        return -55555

def calculate_limit_price_for_profit(buyprice: float, target_profit: float, quantity: float) -> float:
    """
    Calculates the sell price (limit price) to achieve a target profit,
    applying fixed NSE tick size (0.05) and custom .x0/.x5 rounding.
    profit = (sellprice - buyprice) * quantity
    sellprice = (profit / quantity) + buyprice
    """
    try:
        if buyprice is None or target_profit is None or quantity is None or quantity == 0:
            raise ValueError("Inputs cannot be None and quantity cannot be zero.")

        buyprice_d = Decimal(str(buyprice))
        target_profit_d = Decimal(str(target_profit))
        quantity_d = Decimal(str(quantity))

        if quantity_d == Decimal('0'):
            logger_func(logger, "Error: Quantity is zero, cannot calculate limit price for profit.", "CRITICAL")
            return -55555

        # Calculate the raw sell price needed for the target profit
        raw_sell_price_d = (target_profit_d / quantity_d) + buyprice_d

        # Apply fixed NSE tick size adjustment for options (0.05)
        tick_size_d = Decimal('0.05') # Hardcoded for stock options
        
        adjusted_to_tick_price_d: Decimal
        # For profit, we want to round up to ensure we meet or exceed the profit target
        if raw_sell_price_d % tick_size_d == Decimal('0'):
            adjusted_to_tick_price_d = raw_sell_price_d
        else:
            adjusted_to_tick_price_d = ((raw_sell_price_d // tick_size_d) + Decimal('1')) * tick_size_d
        
        # Ensure adjusted_to_tick_price_d has a defined number of decimal places
        # For 0.05, exponent is -2, so num_tick_decimals will be 2.
        num_tick_decimals = abs(tick_size_d.as_tuple().exponent)
        adjusted_to_tick_price_d = adjusted_to_tick_price_d.quantize(Decimal('0.1') ** num_tick_decimals)

        # Apply custom rounding logic (ensure price ends in .x0 or .x5)
        price_str_for_custom_logic = f"{adjusted_to_tick_price_d:.2f}"

        last_digit_char = price_str_for_custom_logic[-1]
        last_digit_int = int(last_digit_char)

        if 0 <= last_digit_int < 5:
            modified_last_digit_char = '0'
        else:  # last_digit_int is 5, 6, 7, 8, or 9
            modified_last_digit_char = '5'

        final_price_str = price_str_for_custom_logic[:-1] + modified_last_digit_char
        final_price_d = Decimal(final_price_str)
        
        return float(final_price_d)

    except (ValueError, TypeError) as e:
        logger_func(logger, f"Error in calculate_limit_price_for_profit due to invalid input: {e}", "CRITICAL")
        return -55555
    except Exception as e:
        logger_func(logger, f"An unexpected error occurred in calculate_limit_price_for_profit: {e}", "CRITICAL")
        logger_func(logger, traceback.format_exc(), "CRITICAL")
        return -55555

# --- Function to get previous day's executed option orders ---
def get_all_prev_day_option_orders(algo_type_filter, user_from_API):
    """
    Fetches previous day's executed option orders from markets.broker_orders_option.
    """
    # For custom orders, we need the original transaction type (BUY/SELL)
    # and the executed price from broker_orders_option.
    # We also need strikeprice and optiontype.
    query = f"""
        SELECT
            stockname,
            price,
            quantity,
            type,
            strike_price as strikeprice,
            option_type as optiontype,
            orderexecutiontime,
            order_tag,
            order_rank,
            algo_type
        FROM
            markets.broker_options_orders
        WHERE
            USER = '{user_from_API}'
            AND orderexecutiondate = (SELECT MAX(orderexecutiondate) FROM markets.broker_options_orders WHERE USER = '{user_from_API}')
    """
    logger_func(logger, f"Fetching previous day's completed option orders for user {user_from_API}...", "INFO")
    logger_func(logger, f"DB Query: {query}", "INFO")
    
    df = pd.DataFrame()
    try:
        df = database.dataframe_from_sql(query)
        logger_func(logger, f"Fetched {len(df)} previous day's completed option orders.", "INFO")
    except Exception as e:
        logger_func(logger, f"Error fetching previous day's option orders from database: {e}", "CRITICAL")
        logger_func(logger, traceback.format_exc(), "CRITICAL")
    return df

# --- Function to print table headers for orders_option tables ---
def print_order_table_header(table_name): # Dynamic function name
    """
    Prints the header for the specified orders_option table.
    """
    headers = [
        "id", "stockname", "buyprice", "quantity", "type", "limitprice",
        "strikeprice", "optiontype", "simulationtime", "cretime",
        "modtime", "credate", "isvalid", "is_future", "USER", "order_rank"
    ]
    # Conditionally add 'buy_premium' to headers only for 'markets.orders_option'
    if table_name == "markets.orders_option":
        headers.append("buy_premium")

    header_str = "| " + " | ".join(f"{h:<18}" for h in headers) + " |"
    separator = "+-------------------" * len(headers) + "+"
    logger_func(logger, separator, "INFO")
    logger_func(logger, header_str, "INFO")
    logger_func(logger, separator, "INFO")
    logger_func(logger, f"Displaying header for table: {table_name}", "INFO")


# --- Main Logic for Creating Orders ---

INVALID_LIMIT_PRICE = -55555

# Get the current date and set the time to midnight (00:00:00) for simulationtime
current_date_obj = datetime.now().date()
simulationtime = datetime.combine(current_date_obj, time.min).strftime("%Y-%m-%d %H:%M:%S")
credate = current_date_obj.strftime("%Y-%m-%d")

logger_func(logger, f"Current simulation time set to: {simulationtime}", "INFO")

try:
    logger_func(logger, "Fetching current positions...", "INFO")
    existing_positions = client.positions()
    # logger_func(logger, f"Raw Positions Report: {json.dumps(existing_positions, indent=2)}", "INFO") # Uncomment to see raw API response
except Exception as e:
    logger_func(logger, f"Error fetching positions from API: {e}", "CRITICAL")
    logger_func(logger, traceback.format_exc(), "CRITICAL")
    sys.exit(1)

# Fetch previous day's executed option orders for the current user
last_day_option_orders = get_all_prev_day_option_orders("ANY_ALGO_TYPE", user_from_API) # Algo type filter might be refined later

# --- Safegaurd: Delete existing generated orders for today to prevent duplicates ---
try:
    import mysql.connector
    mydb = mysql.connector.connect(host="localhost", user="root", password="root", database="markets")
    mycursor = mydb.cursor()
    delete_sql = f"DELETE FROM {order_table} WHERE simulationtime >= '{simulationtime}' AND USER = '{user_from_API}'"
    mycursor.execute(delete_sql)
    mydb.commit()
    if mycursor.rowcount > 0:
        logger_func(logger, f"Cleared {mycursor.rowcount} existing orders from {order_table} for {user_from_API} to prevent duplicates.", "INFO")
except Exception as e:
    logger_func(logger, f"Error clearing old orders: {e}", "CRITICAL")
# -----------------------------------------------------------------------------------

if last_day_option_orders.empty:
    logger_func(logger, "No previous day's completed option orders found for this user. No orders will be created.", "INFO")
else:
    logger_func(logger, f"Processing positions to create {order_type_param} square-off orders for options...", "INFO")
    print_order_table_header(order_table) # Changed function call

    # Convert last_day_option_orders DataFrame to a dictionary for easier lookup
    # Key: (stockname, strikeprice, optiontype)
    prev_day_orders_lookup = {}
    for index, row in last_day_option_orders.iterrows():
        key = (row['stockname'], float(row['strikeprice']), row['optiontype'])
        prev_day_orders_lookup[key] = row

    for trade in existing_positions.get("data", []):
        try:
            cfBuyQty = int(trade.get("cfBuyQty", 0))
            flBuyQty = int(trade.get("flBuyQty", 0))
            cfSellQty = int(trade.get("cfSellQty", 0))
            flSellQty = int(trade.get("flSellQty", 0))
            trdSym = trade.get("sym") # Base symbol like 'HINDPETRO'
            instrument_type = trade.get("type") # CHANGED FROM 'it' to 'type'
            segment = trade.get("exSeg") # 'nse_fo'
            lot_size = int(trade.get("lotSz", 1)) # Default to 1 to avoid division by zero

            # Extract option-specific details from the position trade
            position_strike_price = float(trade.get("stkPrc", 0.0))
            position_option_type = trade.get("optTp", "XX")

            total_buy_qty = cfBuyQty + flBuyQty
            total_sell_qty = cfSellQty + flSellQty
            net_qty = total_buy_qty - total_sell_qty

            # Determine the type of square-off order needed
            type_from_position = None
            if net_qty > 0:
                type_from_position = "SELL"
            elif net_qty < 0:
                type_from_position = "BUY"
            
            # Only process if there's a non-zero net quantity and it's an option
            if net_qty != 0 and segment == 'nse_fo' and instrument_type == 'OPTSTK':
                
                # Log the position being considered
                logger_func(logger, f"Considering position for {order_type_param.upper()} order: Symbol={trdSym}, InstrumentType={instrument_type}, Segment={segment}, NetQty={net_qty}, Strike={position_strike_price}, OptionType={position_option_type}", "INFO")

                # Look up the executed price from the previous day's orders
                lookup_key = (trdSym, position_strike_price, position_option_type)
                item_Lastday_fromDB = prev_day_orders_lookup.get(lookup_key)

                if item_Lastday_fromDB is not None:
                    logger_func(logger, f"Found matching previous day's order for lookup key: {lookup_key}", "INFO")
                    # Quantity for order should be absolute value of net_qty, converted to lots
                    quantity_for_order = abs(net_qty) / lot_size
                    logger_func(logger, f"Calculated quantity for {order_type_param.upper()} order: {quantity_for_order} (Net Qty: {net_qty}, Lot Size: {lot_size})", "INFO")

                    if quantity_for_order == 0: # Skip if calculated quantity is zero
                        logger_func(logger, f"Skipping {trdSym} (Net Qty: {net_qty}) - calculated {order_type_param.upper()} order quantity is zero.", "INFO")
                        continue

                    order_tag = item_Lastday_fromDB["order_tag"]
                    last_day_executed_price = float(item_Lastday_fromDB["price"])
                    
                    # Calculate effective target profit based on percentage of total buy value
                    total_buy_value = last_day_executed_price * (quantity_for_order * lot_size)
                    effective_target_profit = (TARGET_PROFIT_PERCENTAGE_PER_ORDER / 100) * total_buy_value

                    # If it's a BUY order (to square off a short position), we want to buy at a lower price for profit.
                    # So, the effective target profit should be negative to reduce the price.
                    if type_from_position == "BUY":
                        effective_target_profit = -effective_target_profit
                    
                    # Log the inputs to calculate_limit_price_for_profit
                    logger_func(logger, f"Calling calculate_limit_price_for_profit with: buyprice={last_day_executed_price}, target_profit={effective_target_profit}, quantity={quantity_for_order * lot_size}", "INFO")

                    limitprice = calculate_limit_price_for_profit(
                        buyprice=last_day_executed_price,
                        target_profit=effective_target_profit,
                        quantity=quantity_for_order * lot_size # Use total contract quantity for profit calculation
                    )
                    
                    logger_func(logger, f"Calculated limit price: {limitprice} (Buy Price: {last_day_executed_price}, Effective Target Profit: {effective_target_profit}, Quantity: {quantity_for_order * lot_size})", "INFO")
                    
                    if limitprice == INVALID_LIMIT_PRICE:
                        logger_func(logger, f"Skipping {order_type_param.upper()} order for {trdSym} (Strike: {position_strike_price}, Type: {position_option_type}) due to invalid calculated limit price.", "WARNING")
                        continue

                    order_rank = item_Lastday_fromDB.get("order_rank", "NA")
                    algo_type = item_Lastday_fromDB.get("algo_type", "TL_opt")

                    # Prepare data for insertion into the selected table
                    data_for_table = {
                        'stockname': trdSym,
                        'buyprice': last_day_executed_price, # Use the executed price from broker_orders_option
                        'quantity': quantity_for_order,
                        'type': type_from_position,
                        'limitprice': None,
                        'limitprice_original': None,
                        'strikeprice': position_strike_price,
                        'optiontype': position_option_type,
                        'simulationtime': simulationtime,
                        'cretime': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        'modtime': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        'credate': credate,
                        'isvalid': 0, # Initially false as the LTP fetcher will activate it at 9:25
                        'is_future': is_future_value, # Dynamically set based on order type
                        'ismarket': 'FALSE', # Force this to be a limit order
                        'USER': user_from_API,
                        'order_rank': order_rank,
                        'algo_type': algo_type
                    }
                    
                    # Conditionally add 'buy_premium' only if order_table is 'markets.orders_option'
                    if order_table == "markets.orders_option":
                        data_for_table['buy_premium'] = total_buy_value
                    
                    # --- Log the dictionary before printing the formatted table row ---
                    logger_func(logger, f"Data to be inserted for {trdSym}: {data_for_table}", "INFO")
                    
                    limit_str = f"{limitprice:.2f}" if limitprice is not None else "NULL"
                    logger_func(logger, f"| 0                  | {trdSym:<18} | {last_day_executed_price:<18.2f} | {quantity_for_order:<18.2f} | {type_from_position:<18} | {limit_str:<18} | {position_strike_price:<18.2f} | {position_option_type:<18} | {simulationtime:<18} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S'):<18} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S'):<18} | {credate:<18} | 0.00               | {is_future_value:<18} | {user_from_API:<18} | {order_rank:<18} | {algo_type:<18} | {total_buy_value:<18.2f} |", "INFO")

                    # --- Database Insertion ---
                    insert_to_table(order_table, data_for_table) # Use dynamic table name
                    logger_func(logger, f"Database insertion for {order_type_param.upper()} order {trdSym} has been executed.", "INFO")

                else:
                    logger_func(logger, f"No previous day's executed option order found for {trdSym} (Strike: {position_strike_price}, Type: {position_option_type}) matching lookup key {lookup_key}. Skipping {order_type_param.upper()} order creation.", "INFO")

            else:
                # Log the position being skipped and its concise details
                logger_func(logger, f"Skipping stock {trdSym}: Not a non-zero net option position (InstrumentType: {instrument_type}, NetQty: {net_qty}, Segment: {segment}).", "INFO")

        except Exception as e:
            logger_func(logger, f"Error processing position for {trdSym}: {e}", "CRITICAL")
            logger_func(logger, traceback.format_exc(), "CRITICAL")
            # Log the full trade object that caused the error for debugging
            logger_func(logger, f"Full trade object causing error: {trade}", "CRITICAL")

logger_func(logger, f"Script finished processing for {order_type_param} option orders.", "INFO")
