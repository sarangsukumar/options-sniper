import pandas as pd
import os
import csv
import mysql.connector
from sqlalchemy import create_engine, text, bindparam
from sqlalchemy import text
import numpy as np
from datetime import datetime, timedelta
import time
import shutil
import math # For ceil
import matplotlib.pyplot as plt # Added for plotting
import seaborn as sns # Added for plotting
import gc # For garbage collection

# --- Hardcoded MySQL Configurataion (Connection Details) ---
# IMPORTANT: Update these values with your actual MySQL credentials.
MYSQL_HOST = "localhost"
MYSQL_USER = "root"
MYSQL_PASSWORD = "root"
MYSQL_DATABASE = "markets"
# MYSQL_PRICE_TABLE_NAME will be read from config1.csv

# --- Configuration and Data Loading Functions ---

def load_anomalies_filter(anomalies_filepath):
    """Loads anomaly filter CSV and returns set of (date, stock) tuples."""
    anomalies_set = set()
    try:
        df_anomalies = pd.read_csv(anomalies_filepath)
        for _, row in df_anomalies.iterrows():
            date_str = str(row['date'])
            stock_str = str(row['stock']).strip().upper()
            anomalies_set.add((date_str, stock_str))
        print(f"  [ANOMALIES FILTER] Loaded {len(anomalies_set)} anomaly pairs from '{anomalies_filepath}'.")
    except Exception as e:
        print(f"Warning: Could not load anomalies file '{anomalies_filepath}': {e}")
    return anomalies_set

def read_config(config_filepath=None):
    """Reads the configuration file and returns a dictionary."""
    if config_filepath is None:
        SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
        parent_dir = os.path.dirname(SCRIPT_DIR)
        config_filepath = os.path.join(parent_dir, "config", "config1.csv")
    try:
        df_config = pd.read_csv(config_filepath)
        config = dict(zip(df_config['parameter'], df_config['value']))
        config['simulationstarttime'] = str(config.get('simulationstarttime','0930')).zfill(4)
        config['simulationendtime'] = str(config.get('simulationendtime','1500')).zfill(4)
        config['commission'] = float(config.get('commission', 0.0))
        config['chunksize'] = int(config.get('chunksize', 1000))
        config['orderexecutiontype'] = str(config.get('orderexecutiontype', "MM")).upper()
        config['limitwaittimeforfirstorder'] = int(config.get('limitwaittimeforfirstorder', 5))
        config['limitwaittimeforsecondorder'] = int(config.get('limitwaittimeforsecondorder', 5))
        config['simulationtype'] = str(config.get('simulationtype', "intraday")).lower()
        config['lotsize_input_file'] = str(config.get('lotsize_input_file', ""))
        config['order_price_lookback_minutes'] = int(config.get('order_price_lookback_minutes', 3))
        config['custom_limit_price_second_order_enabled'] = str(config.get('custom_limit_price_second_order_enabled', "no")).lower()
        config['custom_limit_price_percentage'] = float(config.get('custom_limit_price_percentage', 0.0))
        config['custom_limit_buy_price_percentage'] = float(config.get('custom_limit_buy_price_percentage', 0.0))

        config['custom_limit_order_wait_time_second_order'] = int(config.get('custom_limit_order_wait_time_second_order', 5))
        config['custom_limit_sell_start_time'] = str(config.get('custom_limit_sell_start_time', "0916")).zfill(4)
        config['market_order_lookforward_ticks'] = int(config.get('market_order_lookforward_ticks', 2))
        config['calculation_mode'] = str(config.get('calculation_mode', 'LOT')).upper()
        
        # New futuretype parameter
        config['futuretype'] = str(config.get('futuretype', "EQ")).upper()

        # --- NEW: custom_limit_wait_days parameter ---
        config['custom_limit_wait_days'] = int(config.get('custom_limit_wait_days', 1))
        if config['custom_limit_wait_days'] < 1:
            print(f"Warning: 'custom_limit_wait_days' must be 1 or greater. Defaulting to 1.")
            config['custom_limit_wait_days'] = 1
        # --- END NEW ---

        # --- NEW: Price Column Parameters ---
        # ADDED 'high' and 'low' to valid_price_columns
        valid_price_columns = ["price", "open", "high", "low","close"] 
        
        config['buy_limit_price_column'] = str(config.get('buy_limit_price_column', "open")).lower()
        if config['buy_limit_price_column'] not in valid_price_columns:
            print(f"Warning: Invalid 'buy_limit_price_column' ('{config['buy_limit_price_column']}'). Defaulting to 'open'. Valid types are {valid_price_columns}.")
            config['buy_limit_price_column'] = "open"

        config['buy_market_check_column'] = str(config.get('buy_market_check_column', "open")).lower()
        if config['buy_market_check_column'] not in valid_price_columns:
            print(f"Warning: Invalid 'buy_market_check_column' ('{config['buy_market_check_column']}'). Defaulting to 'open'. Valid types are {valid_price_columns}.")
            config['buy_market_check_column'] = "open"

        config['sell_limit_price_column'] = str(config.get('sell_limit_price_column', "price")).lower()
        if config['sell_limit_price_column'] not in valid_price_columns:
            print(f"Warning: Invalid 'sell_limit_price_column' ('{config['sell_limit_price_column']}'). Defaulting to 'price'. Valid types are {valid_price_columns}.")
            config['sell_limit_price_column'] = "price"

        config['sell_market_check_column'] = str(config.get('sell_market_check_column', "price")).lower()
        if config['sell_market_check_column'] not in valid_price_columns:
            print(f"Warning: Invalid 'sell_market_check_column' ('{config['sell_market_check_column']}'). Defaulting to 'price'. Valid types are {valid_price_columns}.")
            config['sell_market_check_column'] = "price"
        # --- END NEW: Price Column Parameters ---


        valid_exec_types = ["MM", "LM", "LL", "ML"]
        if config['orderexecutiontype'] not in valid_exec_types:
            print(f"Warning: Invalid 'orderexecutiontype' ('{config['orderexecutiontype']}') in config. Defaulting to 'MM'. Valid types are {valid_exec_types}.")
            config['orderexecutiontype'] = "MM"

        valid_sim_types = ["intraday", "onedayholding"] # Extend as needed
        if config['simulationtype'] not in valid_sim_types:
            print(f"Warning: Invalid 'simulationtype' ('{config['simulationtype']}'). Defaulting to 'intraday'. Valid types are {valid_sim_types}.")
            config['simulationtype'] = "intraday"

        if config['custom_limit_price_second_order_enabled'] not in ["yes", "no"]:
            print(f"Warning: Invalid 'custom_limit_price_second_order_enabled' ('{config['custom_limit_price_second_order_enabled']}'). Defaulting to 'no'. Must be 'yes' or 'no'.")
            config['custom_limit_price_second_order_enabled'] = "no"

        try:
            datetime.strptime(config['custom_limit_sell_start_time'], "%H%M")
        except ValueError:
            print(f"Warning: Invalid 'custom_limit_sell_start_time' format ('{config['custom_limit_sell_start_time']}'). Expected HHMM. Defaulting to '0916'.")
            config['custom_limit_sell_start_time'] = "0916"

        valid_future_types = ["EQ", "F1", "F2", "F3"]
        if config['futuretype'] not in valid_future_types:
            print(f"Warning: Invalid 'futuretype' ('{config['futuretype']}') in config. Defaulting to 'EQ'. Valid types are {valid_future_types}.")
            config['futuretype'] = "EQ"

        # New graph parameters
        config['graph_aggregation_level'] = str(config.get('graph_aggregation_level', "day")).lower()
        valid_graph_levels = ["day", "month", "quarter"]
        if config['graph_aggregation_level'] not in valid_graph_levels:
            print(f"Warning: Invalid 'graph_aggregation_level' ('{config['graph_aggregation_level']}'). Defaulting to 'day'. Valid types are {valid_graph_levels}.")
            config['graph_aggregation_level'] = "day"

        config['export_graphs_as_pdf'] = str(config.get('export_graphs_as_pdf', "no")).lower()
        if config['export_graphs_as_pdf'] not in ["yes", "no"]:
            print(f"Warning: Invalid 'export_graphs_as_pdf' ('{config['export_graphs_as_pdf']}'). Defaulting to 'no'. Must be 'yes' or 'no'.")
            config['export_graphs_as_pdf'] = "no"

        print("Configuration loaded successfully.")
        return config
    except FileNotFoundError:
        print(f"Error: Configuration file '{config_filepath}' not found.")
        return None
    except ValueError as e:
        print(f"Error: Could not convert a numeric parameter in config1.csv. Please check values. Details: {e}")
        return None
    except Exception as e:
        print(f"Error reading configuration file: {e}")
        return None

def load_and_filter_all_input_data(filepath, lotsize_data_map, chunk_size, anomalies_set=None):
    """
    Loads the entire trade input CSV file, maps lotsizes using vectorized operations,
    filters out invalid/zero lotsizes globally, and yields clean DataFrames of chunk_size.
    """
    try:
        print(f"Loading and pre-filtering entire trade input file '{filepath}'...")
        # Load the whole file
        df = pd.read_csv(filepath, header=None, names=['yyyymmdd_date', 'stockname'])
        
        # Fast vectorized date conversion
        df['yyyymmdd_date'] = df['yyyymmdd_date'].astype(str)
        df['initial_simulationdate'] = pd.to_datetime(df['yyyymmdd_date'], format='%Y%m%d').dt.strftime('%Y-%m-%d')
        
        # Vectorized lotsize mapping
        df['year_month'] = df['initial_simulationdate'].str.slice(0, 4) + df['initial_simulationdate'].str.slice(5, 7)
        df['lookup_key'] = df['year_month'] + df['stockname'].str.strip().str.upper()
        df['lotsize'] = df['lookup_key'].map(lotsize_data_map).fillna(0).astype(float).astype(int)
        
        # Keep only rows with valid lotsize
        initial_len = len(df)
        df = df[df['lotsize'] > 0].copy()
        filtered_len = len(df)
        
        print(f"  [GLOBAL LOTSIZE FILTER] Removed {initial_len - filtered_len} rows with zero/missing lotsize. Remaining valid trades: {filtered_len}.")

        if anomalies_set:
            before_anomaly = len(df)
            df['anomaly_key'] = df['initial_simulationdate'] + '|' + df['stockname'].str.strip().str.upper()
            anomaly_keys = {d + '|' + s for d, s in anomalies_set}
            df = df[~df['anomaly_key'].isin(anomaly_keys)].copy()
            df.drop(columns=['anomaly_key'], inplace=True)
            filtered_len = len(df)
            print(f"  [ANOMALIES FILTER] Removed {before_anomaly - filtered_len} rows. Remaining: {filtered_len}.")

        processed_chunk_df = df[['initial_simulationdate', 'stockname', 'lotsize']]
        
        # Slice into chunks of chunk_size
        num_chunks = math.ceil(filtered_len / chunk_size)
        for i in range(num_chunks):
            start_idx = i * chunk_size
            end_idx = min(start_idx + chunk_size, filtered_len)
            chunk_df = processed_chunk_df.iloc[start_idx:end_idx].copy()
            print(f"Yielding pre-filtered CSV chunk {i+1}/{num_chunks} (clean lines: {len(chunk_df)})...")
            yield chunk_df
            
    except FileNotFoundError:
        print(f"Error: Data file '{filepath}' not found.")
    except ValueError as e:
        print(f"Error converting date in '{filepath}'. Ensure dates are in YYYYMMDD format. Details: {e}")
    except Exception as e:
        print(f"Error reading and filtering CSV file '{filepath}': {e}")

def load_instrument_data(lotsize_filepath):
    """
    Loads lotsize and a comprehensive map of all expiry dates for each instrument.
    Returns two dictionaries:
    1. lotsize_map: maps 'simulationmonthstockname' to 'lotsize'.
    2. all_expiries_map: maps a stock symbol (e.g., "NIFTY") to a sorted
                         list of all its available expiry dates (e.g., ['2024-06-27', '2024-07-25', ...]).
    """
    lotsize_map = {}
    all_expiries_map = {}

    if not lotsize_filepath:
        print("Warning: Lotsize input file path not provided in config.")
        return lotsize_map, all_expiries_map

    try:
        # Use low_memory=False for better type inference on mixed-type columns
        df_lotsize = pd.read_csv(lotsize_filepath, low_memory=False)
        # We need 'stockname' to identify the base instrument for grouping expiries
        required_cols = ['simulationmonthstockname', 'lotsize', 'expdate', 'stockname']
        if not all(col in df_lotsize.columns for col in required_cols):
            print(f"Error: Required columns ('stockname', 'simulationmonthstockname', 'lotsize', 'expdate') not found in '{lotsize_filepath}'.")
            return lotsize_map, all_expiries_map

        # Create Lotsize Map
        df_lotsize['simulationmonthstockname'] = df_lotsize['simulationmonthstockname'].astype(str).str.strip()
        lotsize_map = pd.Series(df_lotsize.lotsize.astype(object).values, index=df_lotsize.simulationmonthstockname).to_dict()

        # Create Comprehensive Expiry Date Map
        df_lotsize['stock_symbol'] = df_lotsize['stockname'].astype(str).str.strip().str.upper()
        df_lotsize['parsed_expdate'] = pd.to_datetime(df_lotsize['expdate'], format='%d/%m/%Y', errors='coerce')
        df_lotsize.dropna(subset=['parsed_expdate'], inplace=True) # Ignore rows with invalid dates
        df_lotsize['expdate_str'] = df_lotsize['parsed_expdate'].dt.strftime('%Y-%m-%d')
        
        # Group by the base stock symbol and create a sorted list of unique expiry dates for each
        expiry_groups = df_lotsize.groupby('stock_symbol')['expdate_str'].unique()
        all_expiries_map = {stock: sorted(list(dates)) for stock, dates in expiry_groups.items()}

        print(f"Lotsize and a map of all Expiry Dates loaded successfully from '{lotsize_filepath}'.")
    except FileNotFoundError:
        print(f"Error: Lotsize file '{lotsize_filepath}' not found.")
    except Exception as e:
        print(f"Error reading instrument data file '{lotsize_filepath}': {e}.")

    return lotsize_map, all_expiries_map

def get_all_trading_dates_from_db(db_engine, price_table_name):
    """Fetches all unique, sorted trading dates from the price data table."""
    if not price_table_name:
        print("Error: Price table name not provided for fetching all trading dates.")
        return []
    try:
        # This query remains unchanged as per user request (no is_future filter here)
        query = text(f"SELECT DISTINCT date FROM {price_table_name} ORDER BY date ASC")
        with db_engine.connect() as connection:
            result = connection.execute(query)
            all_dates = [pd.to_datetime(row[0]).strftime('%Y-%m-%d') for row in result if row[0] is not None]
        print(f"Fetched {len(all_dates)} unique trading dates from '{price_table_name}'.")
        return all_dates
    except Exception as e:
        print(f"Error fetching all trading dates from DB: {e}")
        return []

def get_future_trading_day(current_date_str, all_sorted_trading_dates, days_to_hold=1):
    """
    Finds the Nth future trading day from a sorted list of all trading dates.
    """
    if not all_sorted_trading_dates: return None
    try:
        current_date_index = all_sorted_trading_dates.index(current_date_str)
        future_date_index = current_date_index + days_to_hold
        if 0 <= future_date_index < len(all_sorted_trading_dates):
            return all_sorted_trading_dates[future_date_index]
        else: return None
    except ValueError: return None
    except Exception as e:
        print(f"Error in get_future_trading_day for {current_date_str}: {e}")
        return None

# --- NEW: TickCache Class for in-memory storage ---
class TickCache:
    """
    Manages in-memory storage of tick data for specific (date, stockname) pairs.
    Optimized with fast dictionary lookup and sorted list lookup for O(1) performance.
    Features dynamic FIFO caching capped at 15,000 elements to maximize RAM utilization and SQL bypass.
    """
    def __init__(self):
        self.cache = {}       # Key: (date_str, stockname), Value: DataFrame of ticks
        self.dict_cache = {}  # Key: (date_str, stockname), Value: dict of {hhmm: row_dict}
        self.list_cache = {}  # Key: (date_str, stockname), Value: sorted list of (datetime_obj, row_dict)
        self.key_history = [] # FIFO queue tracking key insertions for rolling eviction

    def get_data(self, date_str, stockname):
        """Retrieves tick data from the cache."""
        key = (date_str, stockname)
        return self.cache.get(key)

    def store_data(self, date_str, stockname, df_ticks):
        """Stores tick data in the cache and builds fast indexing lookup structures."""
        key = (date_str, stockname)
        
        # Track insertion order
        if key not in self.cache:
            self.key_history.append(key)

        self.cache[key] = df_ticks
        
        # Build hhmm column if not present
        if 'hhmm' not in df_ticks.columns:
            df_ticks['hhmm'] = df_ticks['datetime_obj'].dt.strftime('%H%M')
            
        columns = df_ticks.columns.tolist()
        data_dict = {}
        for col in columns:
            data_dict[col] = df_ticks[col].tolist()
            
        hhmm_list = data_dict['hhmm']
        hhmm_map = {}
        for i, hhmm in enumerate(hhmm_list):
            hhmm_map[hhmm] = {col: data_dict[col][i] for col in columns}
        self.dict_cache[key] = hhmm_map
        
        dt_list = data_dict['datetime_obj']
        list_ticks = []
        for i, dt in enumerate(dt_list):
            row_map = {col: data_dict[col][i] for col in columns}
            list_ticks.append((dt, row_map))
        list_ticks.sort(key=lambda x: x[0])
        self.list_cache[key] = list_ticks

        # --- MEMORY PROTECTION ---
        # Cap cache at 15,000 distinct stock-days to optimize 16GB RAM usage.
        # This keeps about 1.5GB of raw tick data warm in memory.
        if len(self.cache) > 15000:
            keys_to_evict = self.key_history[:3000]
            self.key_history = self.key_history[3000:]
            for k in keys_to_evict:
                self.delete_data(k[0], k[1])
            print(f"  [MEMORY PROTECT] Warm Cache exceeded 15,000 items. Evicted oldest 3,000 entries. Current cache size: {len(self.cache)}")

    def delete_data(self, date_str, stockname):
        """Deletes tick data from the cache."""
        key = (date_str, stockname)
        if key in self.cache:
            del self.cache[key]
        if key in self.dict_cache:
            del self.dict_cache[key]
        if key in self.list_cache:
            del self.list_cache[key]
        if key in self.key_history:
            self.key_history.remove(key)

    def get_cached_keys(self):
        """Returns all keys currently in the cache."""
        return list(self.cache.keys())

# --- MODIFIED: load_mysql_data to use TickCache and load 'open' column ---
def load_mysql_data(mysql_price_table_name_from_config, required_date_stock_pairs, db_engine, future_type_value, tick_cache):
    """
    Loads price data for a specific list of (date, stockname) pairs using a SQLAlchemy engine.
    This version uses a raw connection to avoid the 'Connection' object has no attribute 'cursor' error.
    """
    if not mysql_price_table_name_from_config:
        print("Error: MySQL price table name not provided.")
        return

    if not required_date_stock_pairs:
        print("  No required (date, stockname) pairs for MySQL query, skipping DB fetch.")
        return

    # Separate pairs into those already in cache and those needing DB fetch
    needed_from_db = set()
    for date_str, stockname in required_date_stock_pairs:
        if tick_cache.get_data(date_str, stockname) is None:
            needed_from_db.add((date_str, stockname))

    if not needed_from_db:
        print("  All required (date, stockname) pairs already in cache. Skipping DB fetch.")
        return

    # Prepare for fetching from DB
    required_dates_list = sorted(list(set([pair[0] for pair in needed_from_db])))
    required_stocks_list = sorted(list(set([pair[1] for pair in needed_from_db])))

    if not required_dates_list or not required_stocks_list:
        print("  No unique dates or stocks identified for DB fetch from needed_from_db.")
        return
    
    try:
        valid_future_types_for_query = ["EQ", "F1", "F2", "F3"]

        # Partition needed_from_db into batches of 30 pairs to parallelize SQL queries across threads
        needed_list = list(needed_from_db)
        batch_size = 30
        batches = [needed_list[i:i + batch_size] for i in range(0, len(needed_list), batch_size)]

        print(f"Fetching price data concurrently using 4 parallel threads across {len(batches)} batches from MySQL for {len(needed_from_db)} distinct (date, stockname) pairs...")

        def fetch_batch(batch_pairs):
            pairs_list_str = ", ".join([f"('{d}', '{s}')" for d, s in batch_pairs])
            query_parts = [
                f"SELECT stockname, price, open, high, low, close, time, date FROM {mysql_price_table_name_from_config}",
                f"WHERE (date, stockname) IN ({pairs_list_str})"
            ]
            if future_type_value and future_type_value in valid_future_types_for_query:
                query_parts.append(f"AND is_future = '{future_type_value}'")
                
            final_query = " ".join(query_parts)
            # Use raw connection per thread for safe concurrent reading
            conn = db_engine.raw_connection()
            try:
                sub_df = pd.read_sql(final_query, conn)
                return sub_df
            finally:
                conn.close()

        dfs = []
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(fetch_batch, b) for b in batches]
            for fut in futures:
                df_sub = fut.result()
                if df_sub is not None and not df_sub.empty:
                    dfs.append(df_sub)

        if not dfs:
            print(f"  Note: Fetched 0 rows from MySQL for the given criteria.")
            return

        df = pd.concat(dfs, ignore_index=True)
        print(f"  Successfully fetched and consolidated {len(df)} total price rows from MySQL in parallel.")

        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        else:
            print("Error: 'date' column not found in fetched MySQL price data.")
            return

        if 'time' in df.columns:
            df['datetime_obj'] = pd.to_datetime(df['time']) 
        else:
            print("Error: 'time' column (for intraday timestamps) not found in fetched MySQL price data.")
            return
        
        # Ensure 'open', 'high', 'low', 'close' columns exist and are numeric
        for col_name in ["open", "high", "low", "close"]:
            if col_name not in df.columns:
                print(f"Warning: '{col_name}' column not found in fetched MySQL price data. Defaulting to 'price' for '{col_name}' references.")
                df[col_name] = df['price'] # Fallback
            else:
                df[col_name] = pd.to_numeric(df[col_name], errors='coerce')


        # Store fetched data into the cache, grouped by (date, stockname)
        for (date_str, stockname) in needed_from_db:
            specific_df = df[(df['date'] == date_str) & (df['stockname'] == stockname)].copy()
            if not specific_df.empty:
                tick_cache.store_data(date_str, stockname, specific_df)

    except Exception as e:
        print(f"An unexpected error occurred while loading MySQL price data: {e}")
# --- MODIFIED: get_market_price_at_exact_time to explicitly accept 'column_to_fetch' ---
def add_minutes_to_hhmm_str(hhmm_str, minutes_to_add):
    """Adds minutes to a HHMM time string using fast integer math and returns the new HHMM string."""
    if hhmm_str is None: return None
    try:
        h = int(hhmm_str[:2])
        m = int(hhmm_str[2:])
        total_m = h * 60 + m + minutes_to_add
        new_h = (total_m // 60) % 24
        new_m = total_m % 60
        return f"{new_h:02d}{new_m:02d}"
    except Exception:
        return hhmm_str

def get_market_price_with_forward_ticks(simulation_date_str, stock_name, start_time_hhmm_str, forward_ticks, tick_cache, column_to_fetch='price', chunk_count_for_debug="N/A"):
    """
    Looks for a price after a given start time for a specified number of forward ticks (minutes).
    Returns the price and time of the first available tick found within that window using fast sorted list search.
    """
    if start_time_hhmm_str is None:
        return None, None
        
    key = (simulation_date_str, stock_name)
    list_ticks = tick_cache.list_cache.get(key)
    if list_ticks is None:
        price_data_df = tick_cache.get_data(simulation_date_str, stock_name)
        if price_data_df is None or price_data_df.empty:
            return None, None
        tick_cache.store_data(simulation_date_str, stock_name, price_data_df)
        list_ticks = tick_cache.list_cache.get(key)

    if list_ticks:
        try:
            start_time_obj = datetime.strptime(f"{simulation_date_str} {start_time_hhmm_str}", "%Y-%m-%d %H%M")
            end_time_obj = start_time_obj + timedelta(minutes=forward_ticks)
            
            for dt, row_map in list_ticks:
                if start_time_obj <= dt <= end_time_obj:
                    price_val = row_map.get(column_to_fetch)
                    time_val = dt.strftime("%H%M")
                    print(f"  [FINAL MARKET CHECK] Found price {price_val} for {stock_name} at {time_val} on {simulation_date_str} from column '{column_to_fetch}'.")
                    return price_val, time_val
            
            print(f"  [FINAL MARKET CHECK] No ticks found for {stock_name} on {simulation_date_str} between {start_time_hhmm_str} and {end_time_obj.strftime('%H%M')}.")
        except Exception as e:
            print(f"Error (Chunk {chunk_count_for_debug}): Finding price for {stock_name} with forward ticks - {e}")
            
    return None, None

def get_market_price_at_exact_time(simulation_date_str, stock_name, order_exec_time_hhmm_str, tick_cache, column_to_fetch='price', chunk_count_for_debug="N/A"):
    """
    Fetches a price (from a specified column like 'price' or 'open') at an exact given time (HHMM) from the TickCache dict.
    """
    if order_exec_time_hhmm_str is None: return None
    key = (simulation_date_str, stock_name)
    hhmm_map = tick_cache.dict_cache.get(key)
    if hhmm_map is None:
        price_data_df = tick_cache.get_data(simulation_date_str, stock_name)
        if price_data_df is None or price_data_df.empty:
            return None
        tick_cache.store_data(simulation_date_str, stock_name, price_data_df)
        hhmm_map = tick_cache.dict_cache.get(key)

    if hhmm_map and order_exec_time_hhmm_str in hhmm_map:
        price_val = hhmm_map[order_exec_time_hhmm_str].get(column_to_fetch)
        print(f"DEBUG: Fetched {column_to_fetch} for {stock_name} at {simulation_date_str} {order_exec_time_hhmm_str}: {price_val}")
        return price_val
    else:
        print(f"DEBUG: No data found for {stock_name} at {simulation_date_str} {order_exec_time_hhmm_str} for column '{column_to_fetch}'.")
        return None

def generate_time_slots_hhmm(base_hhmm_str, num_minutes, direction="forward"):
    """
    Generates a list of HHMM time strings using fast integer math.
    'forward': starts from the minute *after* base_hhmm_str.
    'backward': starts from the minute *before* base_hhmm_str.
    """
    slots = []
    if base_hhmm_str is None: return slots
    try:
        h = int(base_hhmm_str[:2])
        m = int(base_hhmm_str[2:])
    except ValueError:
        print(f"Error: Invalid base_hhmm_str format '{base_hhmm_str}'. Expected HHMM.")
        return slots

    total_m = h * 60 + m
    for i in range(1, num_minutes + 1):
        if direction == "forward":
            curr_total = total_m + i
        elif direction == "backward":
            curr_total = total_m - i
        else:
            return slots
        curr_h = (curr_total // 60) % 24
        curr_m = curr_total % 60
        slots.append(f"{curr_h:02d}{curr_m:02d}")
    return slots

# --- MODIFIED: get_reference_price_with_lookback to accept 'column_to_fetch' ---
def get_reference_price_with_lookback(simulation_date_str, stock_name, target_time_hhmm,
                                        lookback_minutes, tick_cache, column_to_fetch='price', chunk_count_for_debug="N/A"):
    """
    Tries to get a reference price (from a specified column like 'price' or 'open') at target_time_hhmm.
    If not found, looks back up to lookback_minutes using O(1) dictionary lookups.
    Returns (found_price, actual_time_hhmm_of_price).
    actual_time_hhmm_of_price will be target_time_hhmm if price is found there or if no price is found at all.
    """
    if target_time_hhmm is None:
        return None, None

    key = (simulation_date_str, stock_name)
    hhmm_map = tick_cache.dict_cache.get(key)
    if hhmm_map is None:
        price_data_df = tick_cache.get_data(simulation_date_str, stock_name)
        if price_data_df is None or price_data_df.empty: 
            return None, target_time_hhmm
        tick_cache.store_data(simulation_date_str, stock_name, price_data_df)
        hhmm_map = tick_cache.dict_cache.get(key)

    if hhmm_map:
        if target_time_hhmm in hhmm_map:
            exact_price = hhmm_map[target_time_hhmm].get(column_to_fetch)
            if exact_price is not None:
                print(f"DEBUG: Ref price fetched for {stock_name} at {simulation_date_str} {target_time_hhmm} from column '{column_to_fetch}': {exact_price}")
                return exact_price, target_time_hhmm

        if lookback_minutes > 0:
            backward_slots = generate_time_slots_hhmm(target_time_hhmm, lookback_minutes, direction="backward")
            for lookback_time_hhmm in backward_slots:
                if lookback_time_hhmm in hhmm_map:
                    price = hhmm_map[lookback_time_hhmm].get(column_to_fetch)
                    if price is not None:
                        print(f"DEBUG: Ref price fetched (lookback) for {stock_name} at {simulation_date_str} {lookback_time_hhmm} from column '{column_to_fetch}': {price}")
                        return price, lookback_time_hhmm

    return None, target_time_hhmm

    
# --- MODIFIED: get_limit_order_fill to dynamically use 'price' or 'open' for market price checks ---
def get_limit_order_fill(
    start_date_str, stock_name, order_type, limit_price,
    order_placement_hhmm, wait_minutes, wait_days,
    tick_cache, all_db_trading_dates, config_params,
    chunk_count_for_debug="N/A", is_custom_limit_sell_check=False # New parameter
):
    """
    Checks if a limit order gets filled. Uses hardcoded market hours for multi-day scans.
    Uses 'buy_market_check_column' for BUY orders and 'sell_market_check_column' for SELL orders.
    Market price check starts from the minute *after* the order_placement_hhmm on the first day
    for standard limit orders. For custom limit sell orders, it starts from custom_limit_sell_start_time.
    Returns (fill_price, fill_date, fill_time, last_checked_date, last_checked_time)
    """
    if limit_price is None or pd.isna(limit_price) or tick_cache is None:
        return None, None, None, start_date_str, order_placement_hhmm

    if not all_db_trading_dates:
        wait_days = 1

    scan_dates = []
    try:
        start_idx = all_db_trading_dates.index(start_date_str)
        end_idx = min(start_idx + wait_days, len(all_db_trading_dates))
        scan_dates = all_db_trading_dates[start_idx:end_idx]
    except (ValueError, IndexError):
        scan_dates = [start_date_str]
        wait_days = 1

    if not scan_dates:
        return None, None, None, start_date_str, order_placement_hhmm

    last_checked_date = scan_dates[-1]
    last_checked_time = order_placement_hhmm

    for i, current_scan_date in enumerate(scan_dates):
        is_first_day_of_scan = (i == 0)
        is_last_day_of_scan = (i == len(scan_dates) - 1)

        start_time_for_day = '0915' # Default for intermediate days
        end_time_for_day = '1530'   # Default for intermediate days

        if is_first_day_of_scan:
            if order_type == 'SELL' and is_custom_limit_sell_check: # Use the new parameter
                # If it's a SELL order and this is the custom limit check, start from the configured custom_limit_sell_start_time
                start_time_for_day = config_params.get('custom_limit_sell_start_time')
            else:
                # For BUY orders, or SELL orders when this is NOT the custom limit check, start from the minute AFTER placement
                start_time_for_day = add_minutes_to_hhmm_str(order_placement_hhmm, 1)
            
            # Handle potential None from add_minutes_to_hhmm_str (e.g., if order_placement_hhmm was invalid or adding 1 min pushes past midnight)
            if start_time_for_day is None:
                print(f"Warning: Calculated start_time_for_day is None for {current_scan_date}, {stock_name}. Skipping checks for this day.")
                continue # Skip to the next scan date or end loop

            if len(scan_dates) == 1:
                # If it's also the only day, the end time is relative to the original placement time
                end_time_for_day = add_minutes_to_hhmm_str(order_placement_hhmm, wait_minutes)
            else:
                # If it's the first day of a multi-day scan, end at market close
                end_time_for_day = '1530'
        else: # For subsequent days of a multi-day scan
            start_time_for_day = '0915'
            if is_last_day_of_scan:
                end_time_for_day = add_minutes_to_hhmm_str('0915', wait_minutes)
            else:
                end_time_for_day = '1530'

        # Ensure end_time_for_day doesn't exceed market close (1530)
        market_close_time_obj = datetime.strptime('1530', "%H%M")
        try:
            calculated_end_time_obj = datetime.strptime(end_time_for_day, "%H%M")
            if calculated_end_time_obj > market_close_time_obj:
                end_time_for_day = '1530'
        except ValueError:
            # Fallback if parsing fails
            end_time_for_day = '1530'

        # Ensure start time is not after end time
        try:
            if datetime.strptime(start_time_for_day, "%H%M") > datetime.strptime(end_time_for_day, "%H%M"):
                print(f"Warning: Start time ({start_time_for_day}) is after end time ({end_time_for_day}) for {current_scan_date}, {stock_name}. Skipping day.")
                continue
        except ValueError as e:
            print(f"Error parsing times for {current_scan_date}, {stock_name}: {e}. Skipping day.")
            continue


        try:
            time_slots_to_check = []
            
            current_time_obj = datetime.strptime(start_time_for_day, "%H%M")
            final_time_obj = datetime.strptime(end_time_for_day, "%H%M")

            while current_time_obj <= final_time_obj:
                time_slots_to_check.append(current_time_obj.strftime("%H%M"))
                current_time_obj += timedelta(minutes=1)

        except ValueError as e:
            print(f"Error generating time slots for {current_scan_date}: {e}. Skipping day.")
            continue

        if not time_slots_to_check:
            continue

        last_checked_time = time_slots_to_check[-1] # Update last checked time to the end of this day's scan

        for check_time_hhmm in time_slots_to_check:
            # Determine which column to fetch for the market price check based on order_type
            # Use the new config parameters
            col_for_market_check = config_params['buy_market_check_column'] if order_type == 'BUY' else config_params['sell_market_check_column']

            market_price_at_tick = get_market_price_at_exact_time(
                current_scan_date, stock_name, check_time_hhmm, tick_cache, col_for_market_check, chunk_count_for_debug
            )
            if market_price_at_tick is not None:
                market_price_at_tick = float(market_price_at_tick)
                
                comparison_result = "FAIL"
                if (order_type == 'SELL' and market_price_at_tick >= float(limit_price)) or \
                   (order_type == 'BUY' and market_price_at_tick <= float(limit_price) * (1 - (config['custom_limit_buy_price_percentage'] / 100))):
                    comparison_result = "SUCCESS"
                
                if comparison_result == "SUCCESS":
                    return market_price_at_tick, current_scan_date, check_time_hhmm, current_scan_date, check_time_hhmm

    return None, None, None, last_checked_date, last_checked_time
    
    
def calculate_execution_day_label(sell_start_date, sell_execution_date, all_trading_dates):
    """
    Calculates the execution day number (e.g., 'Day 1', 'Day 2') relative to the sell start date.
    """
    # If the sell never executed, there's no execution day.
    if pd.isna(sell_execution_date) or not sell_start_date:
        return None

    try:
        # Find the index position of the start and execution dates in the master list of trading dates
        start_idx = all_trading_dates.index(sell_start_date)
        exec_idx = all_trading_dates.index(sell_execution_date)

        # The number of days is the difference in index position + 1 (so the first day is "Day 1")
        day_number = exec_idx - start_idx + 1
        return f"Day {day_number}"
    except (ValueError, IndexError):
        # Return None if a date wasn't found in the list, which can happen in edge cases.
        return None    
def get_expiry_for_trade(trade_date, future_type, sorted_expiry_list):
    """
    Finds the F1, F2, or F3 expiry date for a given trade from a sorted list of all expiries.
    """
    if not sorted_expiry_list:
        return None

    # Find the index of the first expiry date that is on or after the trade date (this is the F1 contract)
    f1_index = -1
    for i, exp_date in enumerate(sorted_expiry_list):
        if exp_date >= trade_date:
            f1_index = i
            break
    
    if f1_index == -1:
        # This means there are no expiries left for this stock on or after the trade date
        return None

    # Determine the target index based on the future_type setting
    target_index = f1_index
    if future_type == 'F2':
        target_index += 1
    elif future_type == 'F3':
        target_index += 2
    
    # Check if the target index is valid (i.e., does an F2 or F3 contract exist?)
    if target_index < len(sorted_expiry_list):
        return sorted_expiry_list[target_index]
    else:
        # Return None if F2 or F3 is requested but doesn't exist in the data
        return None

def generate_performance_graphs(df_pnl_valid, output_folder_path, aggregation_level='day', high_resolution_pdf=False):
    """
    Generates and saves various performance graphs based on the PnL data.
    Allows aggregation of x-axis by day, month, or quarter.
    Allows saving as high-resolution PDF.
    """
    if df_pnl_valid.empty or 'pnl' not in df_pnl_valid.columns:
        print("No valid PnL data available for graph generation.")
        return

    print("\n--- Generating Performance Graphs ---")
    
    # Ensure 'datetime_col' is datetime type for plotting
    df_pnl_valid['datetime_col'] = pd.to_datetime(df_pnl_valid['simulationdate'])
    df_pnl_valid = df_pnl_valid.sort_values(by='datetime_col')

    # 1. Daily/Aggregated PnL
    if aggregation_level == 'month':
        df_pnl_valid['period_col'] = df_pnl_valid['datetime_col'].dt.to_period('M').astype(str)
        x_label = 'Month'
    elif aggregation_level == 'quarter':
        df_pnl_valid['period_col'] = df_pnl_valid['datetime_col'].dt.to_period('Q').astype(str)
        x_label = 'Quarter'
    else: # Default to 'day'
        df_pnl_valid['period_col'] = df_pnl_valid['datetime_col'].dt.date.astype(str)
        x_label = 'Date'

    daily_pnl = df_pnl_valid.groupby('period_col')['pnl'].sum().reset_index()
    # Sort by datetime for correct plotting order
    daily_pnl['sort_key'] = pd.to_datetime(daily_pnl['period_col'])
    daily_pnl = daily_pnl.sort_values(by='sort_key').drop(columns='sort_key')

    plt.figure(figsize=(12, 6))
    sns.barplot(x='period_col', y='pnl', data=daily_pnl, palette='viridis')
    plt.title(f'Total PnL by {x_label}')
    plt.xlabel(x_label)
    plt.ylabel('PnL')
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    # Save with appropriate filename and format
    filename_prefix = f"{aggregation_level}_pnl_bar_chart"
    if high_resolution_pdf:
        plt.savefig(os.path.join(output_folder_path, f'{filename_prefix}.pdf'), dpi=300)
        print(f"  Saved {x_label} PnL bar chart to {os.path.join(output_folder_path, f'{filename_prefix}.pdf')} (PDF)")
    else:
        plt.savefig(os.path.join(output_folder_path, f'{filename_prefix}.png'))
        print(f"  Saved {x_label} PnL bar chart to {os.path.join(output_folder_path, f'{filename_prefix}.png')} (PNG)")
    plt.close()

    # 2. Cumulative PnL
    # Calculate cumulative PnL on the original daily data first
    df_pnl_valid['cumulative_pnl'] = df_pnl_valid['pnl'].cumsum()

    # If aggregation is requested, re-sample the cumulative PnL to the end of each period
    if aggregation_level == 'month':
        cumulative_pnl_plot_data = df_pnl_valid.set_index('datetime_col')['cumulative_pnl'].resample('M').last().reset_index()
        x_label_cumulative = 'Month'
    elif aggregation_level == 'quarter':
        cumulative_pnl_plot_data = df_pnl_valid.set_index('datetime_col')['cumulative_pnl'].resample('Q').last().reset_index()
        x_label_cumulative = 'Quarter'
    else: # Default to 'day'
        cumulative_pnl_plot_data = df_pnl_valid[['datetime_col', 'cumulative_pnl']]
        x_label_cumulative = 'Date'

    plt.figure(figsize=(12, 6))
    sns.lineplot(x='datetime_col', y='cumulative_pnl', data=cumulative_pnl_plot_data, marker='o', color='blue')
    plt.title(f'Cumulative PnL Over Time ({x_label_cumulative} Aggregation)')
    plt.xlabel(x_label_cumulative)
    plt.ylabel('Cumulative PnL')
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    # Save with appropriate filename and format
    filename_prefix = f"cumulative_pnl_line_chart_{aggregation_level}"
    if high_resolution_pdf:
        plt.savefig(os.path.join(output_folder_path, f'{filename_prefix}.pdf'), dpi=300)
        print(f"  Saved Cumulative PnL line chart to {os.path.join(output_folder_path, f'{filename_prefix}.pdf')} (PDF)")
    else:
        plt.savefig(os.path.join(output_folder_path, f'{filename_prefix}.png'))
        print(f"  Saved Cumulative PnL line chart to {os.path.join(output_folder_path, f'{filename_prefix}.png')} (PNG)")
    plt.close()

    # 3. PnL Distribution (Histogram)
    plt.figure(figsize=(10, 6))
    sns.histplot(df_pnl_valid['pnl'], bins=50, kde=True, color='green')
    plt.title('Distribution of PnL per Trade')
    plt.xlabel('PnL')
    plt.ylabel('Frequency')
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.tight_layout()
    if high_resolution_pdf:
        plt.savefig(os.path.join(output_folder_path, 'pnl_distribution_histogram.pdf'), dpi=300)
        print(f"  Saved PnL Distribution histogram to {os.path.join(output_folder_path, 'pnl_distribution_histogram.pdf')} (PDF)")
    else:
        plt.savefig(os.path.join(output_folder_path, 'pnl_distribution_histogram.png'))
        print(f"  Saved PnL Distribution histogram to {os.path.join(output_folder_path, 'pnl_distribution_histogram.png')} (PNG)")
    plt.close()

    # 4. Top/Bottom 10 Stocks by PnL
    pnl_by_stock = df_pnl_valid.groupby('stockname')['pnl'].sum().sort_values(ascending=False)
    top_10_stocks = pnl_by_stock.head(10)
    bottom_10_stocks = pnl_by_stock.tail(10)

    plt.figure(figsize=(14, 7))
    sns.barplot(x=top_10_stocks.index, y=top_10_stocks.values, palette='Greens_d')
    plt.title('Top 10 Stocks by Total PnL')
    plt.xlabel('Stock Name')
    plt.ylabel('Total PnL')
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    if high_resolution_pdf:
        plt.savefig(os.path.join(output_folder_path, 'top_10_stocks_pnl.pdf'), dpi=300)
        print(f"  Saved Top 10 Stocks by PnL chart to {os.path.join(output_folder_path, 'top_10_stocks_pnl.pdf')} (PDF)")
    else:
        plt.savefig(os.path.join(output_folder_path, 'top_10_stocks_pnl.png'))
        print(f"  Saved Top 10 Stocks by PnL chart to {os.path.join(output_folder_path, 'top_10_stocks_pnl.png')} (PNG)")
    plt.close()

    if not bottom_10_stocks.empty:
        plt.figure(figsize=(14, 7))
        sns.barplot(x=bottom_10_stocks.index, y=bottom_10_stocks.values, palette='Reds_d')
        plt.title('Bottom 10 Stocks by Total PnL')
        plt.xlabel('Stock Name')
        plt.ylabel('Total PnL')
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
        if high_resolution_pdf:
            plt.savefig(os.path.join(output_folder_path, 'bottom_10_stocks_pnl.pdf'), dpi=300)
            print(f"  Saved Bottom 10 Stocks by PnL chart to {os.path.join(output_folder_path, 'bottom_10_stocks_pnl.pdf')} (PDF)")
        else:
            plt.savefig(os.path.join(output_folder_path, 'bottom_10_stocks_pnl.png'))
            print(f"  Saved Bottom 10 Stocks by PnL chart to {os.path.join(output_folder_path, 'bottom_10_stocks_pnl.png')} (PNG)")
        plt.close()

    print("Performance graph generation complete.")


def calculate_and_save_statistics(df_pnl, df_transactions, output_folder_path, config_params, sim_start_date_overall, sim_end_date_overall, aggregation_level='day', high_resolution_pdf=False):
    """
    Generates a detailed, multi-table performance report as a text file.
    """
    # --- 1. Data Preparation ---
    if df_pnl.empty or df_pnl['pnl'].isna().all():
        print("No successfully completed trades to analyze. Cannot generate statistics report.")
        return

    # Create the main DataFrame for analysis from valid, completed trades
    df_pnl_valid = df_pnl.dropna(subset=['pnl']).copy()
    successfully_completed_trades = len(df_pnl_valid)

    # Add time-based columns for grouping
    df_pnl_valid['datetime_col'] = pd.to_datetime(df_pnl_valid['simulationdate'])
    df_pnl_valid['year'] = df_pnl_valid['datetime_col'].dt.year
    df_pnl_valid['quarter'] = df_pnl_valid['datetime_col'].dt.to_period('Q').astype(str)
    df_pnl_valid['month'] = df_pnl_valid['datetime_col'].dt.to_period('M').astype(str)
    df_pnl_valid['week'] = df_pnl_valid['datetime_col'].dt.to_period('W').astype(str)
    df_pnl_valid['day'] = df_pnl_valid['datetime_col'].dt.date.astype(str)

    # Standardize sell execution types for grouping
    if 'sell_exec_type' in df_pnl_valid.columns:
        df_pnl_valid['sell_exec_type_standard'] = df_pnl_valid['sell_exec_type'].apply(
            lambda x: 'Final Market Fill' if isinstance(x, str) and x.startswith('Final Market Fill') else x
        )

    # --- 2. Build Report Sections ---
    report_parts = []

    # Section 1: Configuration
    df_config = pd.DataFrame(list(config_params.items()), columns=['Parameter', 'Value'])
    report_parts.append("--- CONFIGURATION PARAMETERS ---")
    report_parts.append(df_config.to_string(index=False))

    # Section 2: High-Level Overview
    overall_total_pnl = df_pnl_valid['pnl'].sum()
    overview_data = {
        'Metric': [
            "Simulation Period",
            "Total PnL",
            "Average PnL per Trade",
            "Max PnL (Single Trade)",
            "Min PnL (Single Trade)",
            "Total Completed Trades"
        ],
        'Value': [
            f"{sim_start_date_overall} to {sim_end_date_overall}",
            f"{overall_total_pnl:,.2f}",
            f"{df_pnl_valid['pnl'].mean():,.2f}",
            f"{df_pnl_valid['pnl'].max():,.2f}",
            f"{df_pnl_valid['pnl'].min():,.2f}",
            successfully_completed_trades
        ]
    }
    df_overview = pd.DataFrame(overview_data)
    report_parts.append("\n--- STRATEGY OVERVIEW ---")
    report_parts.append(df_overview.to_string(index=False))

    # Section 3: Overall Profitability (Win-Rate by Time Period)
    def calculate_profitability_stats(df, period_col):
        if period_col not in df.columns: return "N/A"
        period_pnl = df.groupby(period_col)['pnl'].sum()
        profitable_periods = (period_pnl > 0).sum()
        total_periods = len(period_pnl)
        win_rate = (profitable_periods / total_periods * 100) if total_periods > 0 else 0
        return f"{win_rate:.2f}% ({profitable_periods}/{total_periods})"

    profitability_data = {
        'Period': ['Years', 'Quarters', 'Months', 'Weeks', 'Days'],
        'Profitability Rate (% of Periods with Profit)': [
            calculate_profitability_stats(df_pnl_valid, 'year'),
            calculate_profitability_stats(df_pnl_valid, 'quarter'),
            calculate_profitability_stats(df_pnl_valid, 'month'),
            calculate_profitability_stats(df_pnl_valid, 'week'),
            calculate_profitability_stats(df_pnl_valid, 'day')
        ]
    }
    df_profitability = pd.DataFrame(profitability_data)
    report_parts.append("\n--- OVERALL PROFITABILITY BY TIME PERIOD ---")
    report_parts.append(df_profitability.to_string(index=False))

    # Section 4: Successful Sell Execution Breakdown
    report_parts.append("\n--- SUCCESSFUL SELL EXECUTION BREAKDOWN ---")
    if 'sell_exec_type_standard' in df_pnl_valid.columns:
        exec_type_summary = []
        exec_type_groups = df_pnl_valid.groupby('sell_exec_type_standard')
        for name, group in exec_type_groups:
            count = len(group)
            exec_type_summary.append({
                'Execution Type': name,
                'No. of Fills': count,
                '% of Total Fills': f"{(count / successfully_completed_trades * 100):.2f}%",
                'Average PnL': f"{group['pnl'].mean():,.2f}"
            })
        df_exec_summary = pd.DataFrame(exec_type_summary)
        report_parts.append(df_exec_summary.to_string(index=False))

    # Section 5: Failed Sells Breakdown
    report_parts.append("\n--- FAILED TRADE BREAKDOWN ---")
    failed_trades = df_pnl[df_pnl['pnl'].isna()]
    buy_fails = failed_trades[failed_trades['buy_price'].isna()]
    sell_fails = failed_trades[failed_trades['buy_price'].notna()]
    fail_data = {
        "Failure Type": ["Total Failed Trades", "  > BUY Order Failed", "  > SELL Order Failed"],
        "Count": [len(failed_trades), len(buy_fails), len(sell_fails)]
    }
    df_fails = pd.DataFrame(fail_data)
    report_parts.append(df_fails.to_string(index=False))
    if not sell_fails.empty and 'sell_exec_type' in sell_fails.columns:
        report_parts.append("\n  SELL Failure Reasons:")
        sell_fail_reasons = sell_fails['sell_exec_type'].value_counts().reset_index()
        sell_fail_reasons.columns = ['Reason', 'Count']
        report_parts.append(sell_fail_reasons.to_string(index=False))


    # Section 6: Completion Day Breakdown
    report_parts.append("\n--- COMPLETION DAY BREAKDOWN ---")
    if 'completion_day' in df_pnl_valid.columns:
        day_summary = []
        day_groups = df_pnl_valid.groupby('completion_day')
        for name, group in day_groups:
            day_summary.append({
                'Completion Day': name,
                'No. of Trades': len(group),
                'Average PnL': f"{group['pnl'].mean():,.2f}"
            })
        df_day_summary = pd.DataFrame(day_summary)
        report_parts.append(df_day_summary.to_string(index=False))

    # Section 7: Expiry Capping Breakdown
    report_parts.append("\n--- EXPIRY CAPPING ANALYSIS ---")
    if 'expiry_capping_details' in df_pnl_valid.columns:
        capped_trades = df_pnl_valid.dropna(subset=['expiry_capping_details'])
        if not capped_trades.empty:
            capping_data = {
                "Metric": ["No. of Trades Capped by Expiry", "Average PnL of Capped Trades"],
                "Value": [len(capped_trades), f"{capped_trades['pnl'].mean():,.2f}"]
            }
            df_capping = pd.DataFrame(capping_data)
            report_parts.append(df_capping.to_string(index=False))
        else:
            report_parts.append("No trades were capped due to expiry.")
            
    # Section 8: Yearly Deep-Dive Analysis
    report_parts.append("\n--- YEARLY PERFORMANCE DEEP-DIVE ---")
    if 'year' in df_pnl_valid.columns:
        yearly_summary_data = []
        for year, year_data in df_pnl_valid.groupby('year'):
            year_trades = len(year_data)
            
            # Calculate sell execution percentages for the year
            custom_fills = year_data[year_data['sell_exec_type_standard'] == 'Custom Limit Fill'].shape[0]
            fallback_fills = year_data[year_data['sell_exec_type_standard'] == 'Fallback/Standard Limit Fill'].shape[0]
            market_fills = year_data[year_data['sell_exec_type_standard'] == 'Final Market Fill'].shape[0]

            # Calculate completion day percentages for the year
            day1_fills = year_data[year_data['completion_day'] == 'Day 1'].shape[0]
            day2_fills = year_data[year_data['completion_day'] == 'Day 2'].shape[0]
            
            yearly_summary_data.append({
                'Year': year,
                'Avg PnL/Trade': f"{year_data['pnl'].mean():,.2f}",
                'Avg PnL/Day': f"{year_data.groupby('day')['pnl'].sum().mean():,.2f}",
                'Total PnL': f"{year_data['pnl'].sum():,.2f}",
                'Max PnL': f"{year_data['pnl'].max():,.2f}", # Corrected to max
                'Min PnL': f"{year_data['pnl'].min():,.2f}", # Corrected to min
                '% Custom Fill': f"{(custom_fills / year_trades * 100):.1f}",
                '% Fallback Fill': f"{(fallback_fills / year_trades * 100):.1f}",
                '% Market Fill': f"{(market_fills / year_trades * 100):.1f}",
                '% Day 1 Close': f"{(day1_fills / year_trades * 100):.1f}",
                '% Day 2 Close': f"{(day2_fills / year_trades * 100):.1f}",
            })
        df_yearly = pd.DataFrame(yearly_summary_data)
        report_parts.append(df_yearly.to_string(index=False))

    # --- 3. Save the Final Report ---
    report_filepath = os.path.join(output_folder_path, "simulation_summary_report.txt")
    try:
        with open(report_filepath, 'w') as f:
            for part in report_parts:
                f.write(part + "\n\n")
        print(f"Detailed summary report saved to {report_filepath}")
    except Exception as e:
        print(f"Error saving summary report: {e}")

    # --- 4. Generate Performance Graphs ---
    generate_performance_graphs(df_pnl_valid, output_folder_path, aggregation_level, high_resolution_pdf)


def run_simulation(input_csv_filepath):
    overall_start_time = time.time()
    print("Starting Stock Market Simulation...")
    config_params = read_config()
    if not config_params: return
    # --- DEBUG: Print loaded config_params ---
    print(f"DEBUG: Loaded config_params: {config_params}")
    # --- END DEBUG ---
    rundate_str = datetime.now().strftime('%Y%m%d')
    sino = 1
    while True:
        output_folder_path = os.path.join("output", "simulation_results", f"simulation_results_{rundate_str}_{sino}")
        if not os.path.exists(output_folder_path):
            os.makedirs(output_folder_path)
            print(f"Created results folder: {output_folder_path}")
            break
        sino += 1
    # try:
    #     config_df_to_save = pd.DataFrame(list(config_params.items()), columns=['parameter', 'value'])
    #     config_df_to_save.to_csv(os.path.join(output_folder_path, "simulation_config_used.csv"), index=False)
    #     print(f"Saved effective configuration to {output_folder_path}")
    # except Exception as e_copy:
    #     print(f"Warning: Could not save effective config to results folder: {e_copy}")
    orders_input_file = config_params.get('orders_input_file')
    if not orders_input_file:
        print("Error: 'orders_input_file' not specified in config."); return
    lotsize_file = config_params.get('lotsize_input_file')
    lotsize_data_map, all_expiries_map = load_instrument_data(lotsize_file)
    chunk_size_from_config_val = config_params.get('chunksize', 1000)
    order_execution_type = config_params.get('orderexecutiontype', "MM")
    limit_wait_first = config_params.get('limitwaittimeforfirstorder', 5)
    limit_wait_second = config_params.get('limitwaittimeforsecondorder', 5)
    simulation_type = config_params.get('simulationtype', "intraday")
    order_price_lookback = int(config_params.get('order_price_lookback_minutes', 3))
    custom_limit_sell_enabled = config_params.get('custom_limit_price_second_order_enabled', "no").lower() == 'yes'
    custom_limit_sell_percentage = float(config_params.get('custom_limit_price_percentage', 0.0))
    custom_limit_sell_wait_time = int(config_params.get('custom_limit_order_wait_time_second_order', 5))
    custom_sell_start_time_cfg = config_params.get('custom_limit_sell_start_time', "0916")
    market_order_lookforward_ticks = int(config_params.get('market_order_lookforward_ticks', 2))
    future_type_config = config_params.get('futuretype', "EQ")
    custom_limit_wait_days_cfg = int(config_params.get('custom_limit_wait_days', 1))
    # --- NEW: Retrieve the new price column parameters ---
    buy_limit_price_col = config_params.get('buy_limit_price_column')
    buy_market_check_col = config_params.get('buy_market_check_column')
    sell_limit_price_col = config_params.get('sell_limit_price_column')
    sell_market_check_col = config_params.get('sell_market_check_column')
    # --- END NEW ---
    # Retrieve graph parameters
    graph_aggregation_level_cfg = config_params.get('graph_aggregation_level', 'day')
    export_graphs_as_pdf_cfg = config_params.get('export_graphs_as_pdf', 'no').lower() == 'yes'
    engine = None
    engine_string = f"mysql+mysqlconnector://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}/{MYSQL_DATABASE}"
    engine = create_engine(engine_string)
    mysql_price_table = config_params.get('MYSQL_PRICE_TABLE_NAME')
    if not mysql_price_table:
        print("Error: 'mysql_price_table_name' not specified in config1.csv. Cannot proceed."); return
    all_db_trading_dates = []
    if simulation_type != "intraday" or (custom_limit_sell_enabled and custom_limit_wait_days_cfg > 0):
        print("Fetching all trading dates from DB for holding period calculations...")
        all_db_trading_dates = get_all_trading_dates_from_db(engine, mysql_price_table)
        if not all_db_trading_dates:
            print(f"Error: Could not fetch trading dates, which are required for this simulation type. Exiting.")
            return
    tables_to_manage = ['markets_orders', 'markets_transactions', 'markets_pnl']
    print(f"\nPreparing MySQL tables: {', '.join(tables_to_manage)} in database '{MYSQL_DATABASE}'...")
    with engine.connect() as connection:
        with connection.begin():
            for table_name in tables_to_manage:
                try:
                    connection.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
                    print(f"  Table '{table_name}' dropped if it existed.")
                except Exception as e_drop:
                    print(f"  Note: Could not drop table '{table_name}' (may not exist or permission issue): {e_drop}")
    processed_chunk_counter = 0
    all_market_orders_list = []
    all_transactions_list = []
    all_pnl_list = []
    all_shortsell_pnl_list = []
    overall_min_initial_date_str = None
    overall_max_sell_date_str = None
    # Load anomaly filter
    anomalies_file = config_params.get('anomalies_filter_file', 'anomalies_filter.csv')
    anomalies_set = load_anomalies_filter(anomalies_file)

    chunk_iterator = load_and_filter_all_input_data(orders_input_file, lotsize_data_map, chunk_size_from_config_val, anomalies_set)
    # --- NEW: Initialize TickCache ---
    tick_cache = TickCache()
    # --- NEW: Track active (date, stockname) pairs for cache management ---
    # This set will store (initial_sim_date, stockname) for trades that are still "active"
    # meaning their sell leg might still be pending or waiting for a fill across days.
    active_trade_keys = set()
    for current_input_orders_chunk_df in chunk_iterator:
        processed_chunk_counter += 1
        print(f"\n--- Processing CSV Chunk {processed_chunk_counter} ---")
        if current_input_orders_chunk_df is None or current_input_orders_chunk_df.empty:
            print(f"Skipping empty or invalid CSV chunk {processed_chunk_counter}.")
            continue

        market_orders_list_chunk = []
        transactions_list_chunk = []
        pnl_list_chunk = []
        chunk_min_date = current_input_orders_chunk_df['initial_simulationdate'].min()
        if overall_min_initial_date_str is None or chunk_min_date < overall_min_initial_date_str:
            overall_min_initial_date_str = chunk_min_date
        # --- NEW: Determine all (date, stockname) pairs needed for this chunk ---
        # This includes the buy date and all potential sell dates based on custom_limit_wait_days_cfg
        required_date_stock_pairs_for_chunk_load = set()
        # Store a mapping from (initial_sim_date, stockname) to the list of (date, stockname)
        # pairs that might be needed for its processing, for later cache cleanup.
        trade_to_tick_keys_map = {}
        # Initialize initial_effective_wait_days_for_chunk_load here for the scope of the chunk processing
        initial_effective_wait_days_for_chunk_load = custom_limit_wait_days_cfg
        for index, row in enumerate(current_input_orders_chunk_df.to_dict('records')):
            initial_sim_date = row['initial_simulationdate']
            stock = row['stockname']

            # Quick check: if entry date is completely missing from database trading dates, skip immediately
            if initial_sim_date not in all_db_trading_dates:
                continue

            # Determine potential sell dates based on custom_limit_wait_days_cfg
            potential_sell_dates_for_stock = []
            if simulation_type == "onedayholding":
                # Find the index of the initial simulation date in the overall trading dates list
                try:
                    start_idx = all_db_trading_dates.index(initial_sim_date)
                    # First, determine the actual sell_start_date for this trade.
                    # For 'onedayholding', this is typically the next trading day after the initial sim date.
                    sell_start_date_for_trade = get_future_trading_day(initial_sim_date, all_db_trading_dates, 1)
                    if not sell_start_date_for_trade:
                        print(f"Warning: Could not determine sell start date for {stock} on {initial_sim_date}. Skipping.")
                        continue # Skip this trade if sell_start_date cannot be determined
                    # Determine the range of dates for which tick data needs to be held for the sell attempt.
                    # This range starts from 'sell_start_date_for_trade' and extends for 'custom_limit_wait_days_cfg' trading days.
                    # For example, if 'custom_limit_wait_days_cfg' is 1, it will include only 'sell_start_date_for_trade'.
                    # If 'custom_limit_wait_days_cfg' is 2, it will include 'sell_start_date_for_trade' and the next trading day.
                    current_date_for_scan = sell_start_date_for_trade
                    for _ in range(initial_effective_wait_days_for_chunk_load):
                        if current_date_for_scan:
                            potential_sell_dates_for_stock.append(current_date_for_scan)
                            current_date_for_scan_idx = all_db_trading_dates.index(current_date_for_scan)
                            if current_date_for_scan_idx + 1 < len(all_db_trading_dates):
                                current_date_for_scan = all_db_trading_dates[current_date_for_scan_idx + 1]
                            else:
                                current_date_for_scan = None # No more trading days
                        else:
                            break
                except (ValueError, IndexError):
                    try:
                        dt_val = datetime.strptime(initial_sim_date, "%Y-%m-%d")
                        if dt_val.weekday() >= 5:
                            reason = f"Weekend ({dt_val.strftime('%A')})"
                        else:
                            reason = "Market Holiday or date is missing in MySQL price table"
                    except Exception:
                        reason = "Invalid date format or data issue"
                    print(f"Warning: Skipping trade for {stock} on {initial_sim_date}: {reason} (not present in database trading dates).")
                    continue

            # ONLY add dates to MySQL query load list if this trade is fully verified as valid and can run
            required_date_stock_pairs_for_chunk_load.add((initial_sim_date, stock))
            for d in potential_sell_dates_for_stock:
                required_date_stock_pairs_for_chunk_load.add((d, stock))

            # Store the mapping for later cache cleanup
            trade_to_tick_keys_map[(initial_sim_date, stock)] = \
                [(initial_sim_date, stock)] + [(d, stock) for d in potential_sell_dates_for_stock]
            # Add this trade to the active set
            active_trade_keys.add((initial_sim_date, stock))
        if not required_date_stock_pairs_for_chunk_load:
            print(f"No valid (date, stockname) pairs determined for CSV chunk {processed_chunk_counter}. Skipping.")
            continue
        # --- Fetch and cache data for all required (date, stockname) pairs for this chunk ---
        load_mysql_data(mysql_price_table, list(required_date_stock_pairs_for_chunk_load), engine, future_type_config, tick_cache)
        algo_type = config_params.get('algotype')
        target_buy_time_hhmm = config_params.get('simulationstarttime')
        target_sell_time_hhmm = config_params.get('simulationendtime')
        commission_per_round_trip = config_params.get('commission', 0.0)
        for index, row in enumerate(current_input_orders_chunk_df.to_dict('records')): # Iterate through the original input chunk
            initial_sim_date = row['initial_simulationdate']
            stock_name = row['stockname']
            pnl_reference_date = initial_sim_date # This is the date used for PnL reporting
            # Determine buy_leg_date and sell_start_date for this specific trade
            buy_leg_date = initial_sim_date
            sell_start_date_for_trade = initial_sim_date
            if simulation_type == "onedayholding":
                sell_start_date_for_trade = get_future_trading_day(initial_sim_date, all_db_trading_dates, 1)
                if not sell_start_date_for_trade:
                    # This trade was already skipped during the initial date gathering, but a double check.
                    print(f"    Skipping trade for {stock_name} on {initial_sim_date}: Sell start date could not be determined.")
                    # Remove from active_trade_keys if it was added
                    active_trade_keys.discard((initial_sim_date, stock_name))
                    continue
            instrument_expiries = all_expiries_map.get(stock_name.upper())
            expiry_date_str = get_expiry_for_trade(buy_leg_date, future_type_config, instrument_expiries)
            if not expiry_date_str:
                print(f"    [EXPIRY CHECK] ❌ Skipping trade for {stock_name} on {buy_leg_date}: Could not find a valid {future_type_config} expiry date.")
                active_trade_keys.discard((initial_sim_date, stock_name))
                continue
            effective_wait_days = custom_limit_wait_days_cfg
            expiry_capping_info = None
            if simulation_type == 'onedayholding':
                if buy_leg_date > expiry_date_str:
                    print(f"    [EXPIRY CHECK]  bypassed for {stock_name} on {buy_leg_date} (trade is after {future_type_config} expiry {expiry_date_str}).")
                else:
                    if buy_leg_date == expiry_date_str:
                        print(f"    [EXPIRY CHECK] ❌ Skipping trade for {stock_name} on {buy_leg_date}: Trade date is the {future_type_config} expiry date {expiry_date_str}.")
                        active_trade_keys.discard((initial_sim_date, stock_name))
                        continue
                    try:
                        sell_start_index = all_db_trading_dates.index(sell_start_date_for_trade)
                        expiry_index = all_db_trading_dates.index(expiry_date_str)
                        available_days = expiry_index - sell_start_index + 1
                        if available_days < 1:
                            print(f"    [EXPIRY CHECK] ❌ Skipping trade for {stock_name} on {buy_leg_date}: Sell start date {sell_start_date_for_trade} is after expiry {expiry_date_str}.")
                            active_trade_keys.discard((initial_sim_date, stock_name))
                            continue
                        if custom_limit_wait_days_cfg > available_days:
                            print(f"    [EXPIRY CHECK] 📝 For {stock_name}, wait days limited from {custom_limit_wait_days_cfg} to {available_days} due to {future_type_config} expiry on {expiry_date_str}.")
                            effective_wait_days = available_days
                            expiry_capping_info = f"Capped from {custom_limit_wait_days_cfg} to {effective_wait_days}"
                    except (ValueError, IndexError):
                        print(f"    [EXPIRY CHECK] ⚠️ Warning: Could not find dates for {stock_name} in calendar. Expiry logic cannot be applied.")
            if algo_type == "TL":
                # BUY Order - Use 'buy_limit_price_column' for reference
                order_buy_price, actual_buy_placement_time = get_reference_price_with_lookback(
                    buy_leg_date, stock_name, target_buy_time_hhmm, order_price_lookback, tick_cache, column_to_fetch=buy_limit_price_col, chunk_count_for_debug=processed_chunk_counter
                )
                buy_executed_price, buy_executed_time = pd.NA, None
                if order_execution_type in ["MM", "ML"]:
                    buy_executed_price, buy_executed_time = order_buy_price, actual_buy_placement_time
                elif order_execution_type in ["LL", "LM"] and pd.notna(order_buy_price):
                    # For BUY limit order, the limit price reference is still 'order_buy_price' (from 'buy_limit_price_column')
                    # Market price checks for BUY order (first day) use 'buy_market_check_column'
                    fill_price, fill_date, fill_time, _, _ = get_limit_order_fill(buy_leg_date, stock_name, "BUY", order_buy_price, target_buy_time_hhmm,limit_wait_first, 1, tick_cache, all_db_trading_dates, config_params, processed_chunk_counter)
                    if fill_price is not None:
                        buy_executed_price, buy_executed_time = fill_price, fill_time

                # Calculate quantity based on calculation_mode
                if config_params.get('calculation_mode', 'LOT').upper() == 'QTY':
                    ref_price = buy_executed_price if pd.notna(buy_executed_price) else order_buy_price
                    quantity = int(100000 / float(ref_price)) if pd.notna(ref_price) and float(ref_price) > 0 else 0
                else:
                    quantity = row['lotsize']

                market_orders_list_chunk.append({'simulationdate': buy_leg_date, 'simulationtime': actual_buy_placement_time,'stockname': stock_name, 'ordertype': 'BUY', 'quantity': quantity,'order_price': order_buy_price if pd.notna(order_buy_price) else pd.NA})
                transactions_list_chunk.append({'simulationdate': buy_leg_date, 'simulationtime': actual_buy_placement_time,'stockname': stock_name, 'ordertype': 'BUY','order_price_ref': order_buy_price if pd.notna(order_buy_price) else pd.NA,'executed_price': buy_executed_price, 'executed_time': buy_executed_time,'quantity': quantity, 'sell_execution_detail': None, 'execution_day': None, 'expiry_capping_details': None})
                sell_executed_price, sell_executed_date, sell_executed_time = pd.NA, None, None
                sell_exec_detail_message = "Not Executed"
                final_sell_order_ref_price = pd.NA
                current_sell_stage_date = sell_start_date_for_trade
                current_sell_stage_time = target_sell_time_hhmm
                if pd.isna(buy_executed_price):
                    sell_exec_detail_message = "BUY Leg Failed"
                else:
                    is_custom_sell_active = custom_limit_sell_enabled and custom_limit_sell_percentage >= 0
                    if is_custom_sell_active:
                        # Custom SELL limit price is calculated, not read from column
                        custom_sell_target_price = float(buy_executed_price) * (1 + custom_limit_sell_percentage / 100.0)
                        final_sell_order_ref_price = custom_sell_target_price
                        # Market price checks for custom SELL limit order are handled by get_limit_order_fill, which now uses 'sell_market_check_column'
                        fill_price, fill_date, fill_time, last_date, last_time = get_limit_order_fill(current_sell_stage_date, stock_name, "SELL", custom_sell_target_price, custom_sell_start_time_cfg,custom_limit_sell_wait_time, effective_wait_days,tick_cache, all_db_trading_dates, config_params, processed_chunk_counter, is_custom_limit_sell_check=True) # Pass True here
                        if fill_price is not None:
                            sell_executed_price, sell_executed_date, sell_executed_time = fill_price, fill_date, fill_time
                            sell_exec_detail_message = "Custom Limit Fill"
                            # Add to shortsell PnL list
                            if pd.notna(buy_executed_price) and pd.notna(sell_executed_price):
                                gain_pct = (float(sell_executed_price) - float(buy_executed_price)) / float(buy_executed_price) * 100
                                all_shortsell_pnl_list.append({
                                    'simulationdate': sell_executed_date if sell_executed_date else initial_sim_date,
                                    'stockname': stock_name,
                                    'sell_price': float(sell_executed_price),
                                    'executed_time': sell_executed_time,
                                    'overnight_date': initial_sim_date,
                                    'overnight_gainpercentage': gain_pct,
                                    'quantity': quantity,
                                    'ordertype': 'SELL'
                                })
                        else:
                            current_sell_stage_date, current_sell_stage_time = last_date, add_minutes_to_hhmm_str(last_time, 1)
                    if pd.isna(sell_executed_price):
                        # SELL Order - Use 'sell_limit_price_column' for reference (standard limit sell)
                        order_sell_price, actual_placement_time = get_reference_price_with_lookback(
                            current_sell_stage_date, stock_name, current_sell_stage_time, order_price_lookback, tick_cache, column_to_fetch=sell_limit_price_col, chunk_count_for_debug=processed_chunk_counter
                        )
                        if pd.notna(order_sell_price):
                            final_sell_order_ref_price = order_sell_price
                        if order_execution_type in ["LL", "ML"] and pd.notna(order_sell_price):
                            # For SELL limit order, the limit price reference is now 'order_sell_price' (from 'sell_limit_price_column')
                            # Market price checks for standard SELL limit order are handled by get_limit_order_fill, which now uses 'sell_market_check_column'
                            fill_price, fill_date, fill_time, last_date, last_time = get_limit_order_fill(current_sell_stage_date, stock_name, "SELL", order_sell_price, actual_placement_time,limit_wait_second, 1, tick_cache, all_db_trading_dates, config_params, processed_chunk_counter, is_custom_limit_sell_check=False) # Pass False here
                            if fill_price is not None:
                                sell_executed_price, sell_executed_date, sell_executed_time = fill_price, fill_date, fill_time
                                sell_exec_detail_message = "Fallback/Standard Limit Fill"
                            else:
                                current_sell_stage_date, current_sell_stage_time = last_date, add_minutes_to_hhmm_str(last_time, 1)
                        elif order_execution_type in ["MM", "LM"]:
                            sell_executed_price, sell_executed_time = order_sell_price, actual_placement_time
                            sell_executed_date = current_sell_stage_date
                            if pd.notna(sell_executed_price):
                                sell_exec_detail_message = "Standard Market Fill"
                    if pd.isna(sell_executed_price) and current_sell_stage_time:
                        # Final Market Fill: Use 'sell_market_check_column'
                        col_for_final_market_check = sell_market_check_col
                        market_price, market_time = get_market_price_with_forward_ticks(
                            current_sell_stage_date, stock_name, current_sell_stage_time,
                            market_order_lookforward_ticks, tick_cache,
                            column_to_fetch=col_for_final_market_check, # Pass the determined column
                            chunk_count_for_debug=processed_chunk_counter
                        )
                        if market_price is not None:
                            sell_executed_price, sell_executed_date, sell_executed_time = market_price, current_sell_stage_date, market_time
                            final_sell_order_ref_price = market_price
                            sell_exec_detail_message = f"Final Market Fill (at {market_time})"
                        else:
                            sell_exec_detail_message = "Final Market Failed"
                final_sell_tx_date = sell_executed_date if sell_executed_date else sell_start_date_for_trade
                if not sell_executed_date and simulation_type == "onedayholding":
                    # If sell didn't execute, and it's a holding simulation, the "final" date for this trade
                    # is the last possible day it could have been held, or the sell_start_date if no holding applies.
                    final_sell_tx_date = get_future_trading_day(initial_sim_date, all_db_trading_dates, effective_wait_days) or sell_start_date_for_trade
                if final_sell_tx_date and (overall_max_sell_date_str is None or final_sell_tx_date > overall_max_sell_date_str):
                    overall_max_sell_date_str = final_sell_tx_date
                exec_day_label = calculate_execution_day_label(sell_start_date_for_trade, sell_executed_date, all_db_trading_dates)
                market_orders_list_chunk.append({'simulationdate': final_sell_tx_date, 'simulationtime': current_sell_stage_time,'stockname': stock_name, 'ordertype': 'SELL', 'quantity': quantity,'order_price': final_sell_order_ref_price if pd.notna(final_sell_order_ref_price) else pd.NA})
                transactions_list_chunk.append({'simulationdate': final_sell_tx_date, 'simulationtime': current_sell_stage_time,'stockname': stock_name, 'ordertype': 'SELL','order_price_ref': final_sell_order_ref_price if pd.notna(final_sell_order_ref_price) else pd.NA,'executed_price': sell_executed_price, 'executed_time': sell_executed_time,'quantity': quantity, 'sell_execution_detail': sell_exec_detail_message, 'execution_day': exec_day_label, 'expiry_capping_details': expiry_capping_info})
                pnl_list_chunk.append({'simulationdate': pnl_reference_date, 'stockname': stock_name,'buy_price': float(buy_executed_price) if pd.notna(buy_executed_price) else pd.NA,'sell_price': float(sell_executed_price) if pd.notna(sell_executed_price) else pd.NA,'quantity': quantity, 'commission_paid': commission_per_round_trip,'pnl': pd.NA if pd.isna(buy_executed_price) or pd.isna(sell_executed_price) else (float(sell_executed_price) - float(buy_executed_price)) * quantity - commission_per_round_trip,'sell_exec_type': sell_exec_detail_message,'completion_day': exec_day_label if pd.notna(sell_executed_price) else None, 'expiry_capping_details': expiry_capping_info})
            # --- Mark trade as complete ---
            trade_key = (initial_sim_date, stock_name)

        # --- Clean up active trade track keys at the end of the chunk ---
        for index, row in enumerate(current_input_orders_chunk_df.to_dict('records')):
            initial_sim_date = row['initial_simulationdate']
            stock_name = row['stockname']
            trade_key = (initial_sim_date, stock_name)
            if trade_key in active_trade_keys:
                active_trade_keys.remove(trade_key)

        all_market_orders_list.extend(market_orders_list_chunk)
        all_transactions_list.extend(transactions_list_chunk)
        all_pnl_list.extend(pnl_list_chunk)
    print("\n--- All CSV chunks processed. Finalizing data... ---")
    df_market_orders_final = pd.DataFrame(all_market_orders_list)
    df_transactions_final = pd.DataFrame(all_transactions_list)
    df_markets_pnl_final = pd.DataFrame(all_pnl_list)
    expected_market_order_cols = ['simulationdate', 'simulationtime', 'stockname', 'ordertype', 'quantity', 'order_price']
    df_market_orders_final = df_market_orders_final.reindex(columns=expected_market_order_cols)
    expected_transaction_cols = ['simulationdate', 'simulationtime', 'stockname', 'ordertype', 'quantity', 'order_price_ref', 'executed_price', 'executed_time', 'sell_execution_detail', 'execution_day', 'expiry_capping_details']
    df_transactions_final = df_transactions_final.reindex(columns=expected_transaction_cols)
    # --- MODIFIED: Ensure new 'sell_exec_type' column is expected ---
    expected_pnl_cols = ['simulationdate', 'stockname', 'buy_price', 'sell_price', 'quantity', 'commission_paid', 'pnl', 'sell_exec_type', 'completion_day', 'expiry_capping_details']
    df_markets_pnl_final = df_markets_pnl_final.reindex(columns=expected_pnl_cols)
    for df in [df_market_orders_final, df_transactions_final, df_markets_pnl_final]:
        for col in df.columns:
            if df[col].dtype == 'object':
                df[col] = df[col].replace({np.nan: None})
        if 'quantity' in df.columns:
            df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce').astype('Int64')
        for col in ['order_price', 'order_price_ref', 'executed_price', 'buy_price', 'sell_price', 'commission_paid', 'pnl']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

    # --- Drop rows having empty values for buy_price ---
    df_markets_pnl_final = df_markets_pnl_final.dropna(subset=['buy_price'])

    # --- Drop rows where sell_exec_type is 'Final Market Failed' ---
    if 'sell_exec_type' in df_markets_pnl_final.columns:
        initial_len = len(df_markets_pnl_final)
        df_markets_pnl_final = df_markets_pnl_final[df_markets_pnl_final['sell_exec_type'] != 'Final Market Failed']
        dropped_failed = initial_len - len(df_markets_pnl_final)
        if dropped_failed > 0:
            print(f"ℹ Dropped {dropped_failed} rows with 'Final Market Failed' sell execution type.")

    print(f"\nSaving results to CSV files in folder: {output_folder_path}")
    try:
        # Only write markets_pnl.csv
        df_markets_pnl_final.to_csv(os.path.join(output_folder_path, "markets_pnl.csv"), index=False)
        print("CSV file markets_pnl.csv saved successfully.")
        
        # --- Create Filtered PnL for Yesterday's Predictions ---
        try:
            if not df_markets_pnl_final.empty:
                # Get the date being simulated (e.g. 2026-07-14)
                first_row_date = df_markets_pnl_final['simulationdate'].iloc[0]
                sim_dt = pd.to_datetime(first_row_date)
                sim_date_yyyymmdd = sim_dt.strftime("%Y%m%d")
                
                # Load yesterday's predicted stocks
                pred_csv_path = os.path.join(parent_dir, "output", "predictedstocksfortoday.csv")
                predicted_stocks = []
                if os.path.exists(pred_csv_path):
                    with open(pred_csv_path, 'r') as f_pred:
                        reader = csv.reader(f_pred)
                        for row in reader:
                            if len(row) >= 2:
                                if row[0].strip() == sim_date_yyyymmdd:
                                    predicted_stocks.append(row[1].strip().upper())
                    print(f"✔ Found predicted stocks for yesterday ({sim_date_yyyymmdd}) in predictions file: {predicted_stocks}")
                else:
                    print(f"ℹ Note: predictedstocksfortoday.csv does not exist yet at {pred_csv_path}")
                
                # Keep only rows where stockname is in predicted_stocks
                df_filtered = df_markets_pnl_final[df_markets_pnl_final['stockname'].str.strip().str.upper().isin(predicted_stocks)]
                filtered_csv_path = os.path.join(output_folder_path, "markets_pnl_predicted.csv")
                df_filtered.to_csv(filtered_csv_path, index=False)
                print(f"✔ Filtered simulation CSV saved to {filtered_csv_path} with {len(df_filtered)} rows.")
                
                # --- Send Telegram HTML Text Message ---
                try:
                    bot_path = "/home/ubuntu/telegram_bot/New_OrderInfoBot.js"
                    if os.path.exists(bot_path):
                        tg_lines = []
                        tg_lines.append("📊 <b>FUTURES SIMULATION PNL REPORT</b> 📊")
                        tg_lines.append(f"📅 <b>Date</b>: {sim_dt.strftime('%d-%m-%Y')}")
                        tg_lines.append("")
                        
                        if not df_filtered.empty:
                            for _, r in df_filtered.iterrows():
                                stock = r['stockname']
                                buy_p = float(r['buy_price']) if pd.notna(r['buy_price']) else 0.0
                                sell_p = float(r['sell_price']) if pd.notna(r['sell_price']) else 0.0
                                q = int(r['quantity']) if pd.notna(r['quantity']) else 0
                                comm = float(r['commission_paid']) if pd.notna(r['commission_paid']) else 0.0
                                pnl_val = float(r['pnl']) if pd.notna(r['pnl']) else 0.0
                                exec_t = r.get('sell_exec_type', 'N/A')
                                comp_d = r.get('completion_day', 'Day 1')
                                
                                tg_lines.append(f"• <b>{stock}</b>")
                                tg_lines.append(f"  - <b>Buy Price</b>: Rs {buy_p:,.2f} | <b>Sell Price</b>: Rs {sell_p:,.2f} | <b>Qty</b>: {q}")
                                tg_lines.append(f"  - <b>PnL</b>: <b>Rs {pnl_val:,.2f}</b> (Comm: Rs {comm:,.2f})")
                                tg_lines.append(f"  - <b>Exit</b>: {exec_t} ({comp_d})")
                                tg_lines.append("")
                        else:
                            tg_lines.append("ℹ <b>No Trades Simulated</b>: No active predictions matched yesterday's date.")
                        
                        # --- System Ingestion & Append Diagnostics ---
                        import json
                        total_gaps_updated = 0
                        yahoo_gaps = 0
                        icici_gaps = 0
                        skipped_gaps = 0
                        summary_path = os.path.join(parent_dir, "pipeline", "morning_gap_summary.json")
                        if os.path.exists(summary_path):
                            try:
                                with open(summary_path, 'r') as f:
                                    stats = json.load(f)
                                    yahoo_gaps = stats.get("yahoo", 0)
                                    icici_gaps = stats.get("icici", 0)
                                    skipped_gaps = stats.get("skipped", 0)
                                    total_gaps_updated = yahoo_gaps + icici_gaps
                            except Exception as e_sum:
                                print(f"Warning: Failed to read morning gap summary: {e_sum}")

                        tg_lines.append("📈 <b>SYSTEM DIAGNOSTICS</b> 📈")
                        tg_lines.append(f"• <b>Master PnL Appended</b>: <code>{len(df_markets_pnl_final)}</code> rows")
                        if total_gaps_updated > 0 or skipped_gaps > 0:
                            tg_lines.append(f"• <b>Morning Gap Features (Today)</b>:")
                            tg_lines.append(f"  - Total Updated: <code>{total_gaps_updated}</code> stocks")
                            tg_lines.append(f"  - Yahoo Finance: <code>{yahoo_gaps}</code>")
                            tg_lines.append(f"  - ICICI Fallback: <code>{icici_gaps}</code>")
                            tg_lines.append(f"  - Skipped/Failed: <code>{skipped_gaps}</code>")
                        tg_lines.append("")

                        tg_msg = "\n".join(tg_lines)
                        import subprocess
                        subprocess.run(["node", bot_path, tg_msg], check=True, stdout=subprocess.DEVNULL, timeout=15)
                        print("✔ Telegram HTML PnL report sent successfully!")
                    else:
                        print(f"Warning: OrderInfoBot not found at {bot_path}")
                except Exception as e_tg:
                    print(f"Warning: Failed to send Telegram results: {e_tg}")
        except Exception as e_filter:
            print(f"Warning: Failed to create filtered predictions CSV: {e_filter}")
            
        # --- Append to Master PnL Sheet (data/markets_pnl0325.csv) ---
        try:
            master_pnl_path = os.path.join(parent_dir, "data", "markets_pnl0325.csv")
            if os.path.exists(master_pnl_path):
                df_append = df_markets_pnl_final.copy()
                df_append['simulationdate'] = pd.to_datetime(df_append['simulationdate']).dt.strftime('%d-%m-%Y')
                
                print(f"Loading existing Master PnL sheet for duplicate checks...")
                df_master_existing = pd.read_csv(master_pnl_path, dtype=str)
                
                # Get the unique dates we are trying to insert (e.g. ['14-07-2026'])
                dates_to_remove = df_append['simulationdate'].unique()
                
                # Drop rows in existing master sheet matching these simulation dates
                df_master_clean = df_master_existing[~df_master_existing['simulationdate'].isin(dates_to_remove)]
                
                removed_count = len(df_master_existing) - len(df_master_clean)
                if removed_count > 0:
                    print(f"ℹ Removed {removed_count} existing duplicate rows for date(s) {list(dates_to_remove)} from Master PnL.")
                
                # Concat and save
                df_master_final = pd.concat([df_master_clean, df_append], ignore_index=True)
                df_master_final.to_csv(master_pnl_path, index=False)
                print(f"✔ Successfully saved {len(df_append)} simulated rows to {master_pnl_path} (duplicates prevented)!")
            else:
                print(f"Warning: Master PnL sheet not found at {master_pnl_path}")
        except Exception as e_append:
            print(f"Error appending simulated rows to master PnL sheet: {e_append}")
    except Exception as e_csv:
        print(f"Error saving results to CSV files: {e_csv}")
    print(f"\nAttempting to write aggregated output tables to MySQL database: '{MYSQL_DATABASE}'")
    try:
        if not df_market_orders_final.empty:
            df_market_orders_final.to_sql(name='markets_orders', con=engine, if_exists='append', index=False)
            print(f"Aggregated table 'markets_orders' successfully written to MySQL.")
        if not df_transactions_final.empty:
            df_transactions_final.to_sql(name='markets_transactions', con=engine, if_exists='append', index=False)
            print(f"Aggregated table 'markets_transactions' successfully written to MySQL.")
        if not df_markets_pnl_final.empty:
            df_markets_pnl_final.to_sql(name='markets_pnl', con=engine, if_exists='append', index=False)
            print(f"Aggregated table 'markets_pnl' successfully written to MySQL.")
        print("MySQL database operations for aggregated data complete.")
    except Exception as e_sql_final:
        print(f"Error writing aggregated data to MySQL: {e_sql_final}")
    finally:
        if engine:
            engine.dispose()
    overall_end_time = time.time()
    total_duration = overall_end_time - overall_start_time
    print(f"\nStock Market Simulation finished.")
    print(f"Total time taken: {total_duration:.2f} seconds.")

if __name__ == "__main__":
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(SCRIPT_DIR)
    config_path = os.path.join(parent_dir, "config", "config1.csv")
    config = read_config(config_path) # Read config first
    
    run_simulation(input_csv_filepath=config['orders_input_file'])
