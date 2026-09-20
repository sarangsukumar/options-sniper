#!/usr/bin/env python3
"""
1_extract_premarket_data.py
---------------------------
Extracts 09:07:00 AM Pre-Market auction ticks from MySQL database tables:
  • Equity Cash table: `scrapdata` (2018–2025)
  • F&O Futures table: `scrapdata_F1` (2025–2026)

Uses 32 parallel worker threads and incremental CSV checkpointing.
"""

import pymysql
import pandas as pd
import numpy as np
import os
import time
from concurrent.futures import ThreadPoolExecutor

BASE_DIR = '/home/ubuntu/v5_from_scratch'
V2_BASE_FILE = '/home/ubuntu/short_sell_simulation_algo/output/short_sell_ml_dataset_v2.csv'
CACHE_FILE = os.path.join(BASE_DIR, 'data', 'premarket_ticks_cache.csv')

def fetch_premarket_for_date(d):
    try:
        conn = pymysql.connect(host='localhost', user='root', password='root', database='markets')
        cursor = conn.cursor()
        
        # Query Equity Cash scrapdata
        q_eq = f"SELECT date, TRIM(BOTH '\"' FROM TRIM(BOTH \"'\" FROM TRIM(stockname))) as clean_stock, CAST(price AS DECIMAL(10,2)) as price_0907 FROM scrapdata WHERE date = '{d}' AND time = '{d} 09:07:00' AND isvalid='TRUE'"
        cursor.execute(q_eq)
        eq_res = cursor.fetchall()
        
        # Query F&O Futures scrapdata_F1
        q_f1 = f"SELECT date, TRIM(BOTH '\"' FROM TRIM(BOTH \"'\" FROM TRIM(stockname))) as clean_stock, CAST(price AS DECIMAL(10,2)) as price_0907 FROM scrapdata_F1 WHERE date = '{d}' AND time = '{d} 09:07:00' AND isvalid='TRUE'"
        cursor.execute(q_f1)
        f1_res = cursor.fetchall()
        
        conn.close()
        
        rows = []
        for r in eq_res:
            if r[2] is not None:
                rows.append({'date_str': str(r[0]), 'clean_stock': str(r[1]), 'price_0907_eq': float(r[2]), 'price_0907_f1': np.nan})
        for r in f1_res:
            if r[2] is not None:
                rows.append({'date_str': str(r[0]), 'clean_stock': str(r[1]), 'price_0907_eq': np.nan, 'price_0907_f1': float(r[2])})
        
        if not rows:
            rows.append({'date_str': d, 'clean_stock': '_NONE_', 'price_0907_eq': np.nan, 'price_0907_f1': np.nan})
            
        return (d, rows)
    except Exception as e:
        return (d, [{'date_str': d, 'clean_stock': '_NONE_', 'price_0907_eq': np.nan, 'price_0907_f1': np.nan}])

def main():
    print("==================================================================")
    print("STEP 1: PRE-MARKET 09:07 AM TICK DATA EXTRACTION")
    print("==================================================================")
    
    print("1. Reading baseline trade dates...")
    df = pd.read_csv(V2_BASE_FILE, low_memory=False)
    df['date_str'] = pd.to_datetime(df['short_sell_date'], format='mixed').dt.strftime('%Y-%m-%d')
    df = df[df['date_str'] >= '2018-01-01'].copy()
    all_dates = sorted(df['date_str'].unique())
    
    processed_dates = set()
    if os.path.exists(CACHE_FILE) and os.path.getsize(CACHE_FILE) > 0:
        try:
            cache_df = pd.read_csv(CACHE_FILE)
            if 'date_str' in cache_df.columns:
                processed_dates = set(cache_df['date_str'].unique())
                print(f" Found existing cache with {len(cache_df):,} ticks across {len(processed_dates)} dates.")
        except Exception as e:
            print(f" Warning reading cache: {e}. Starting fresh.")
            
    dates_to_process = [d for d in all_dates if d not in processed_dates]
    print(f" Total dates: {len(all_dates)} | Cached: {len(processed_dates)} | Remaining: {len(dates_to_process)}")
    
    if dates_to_process:
        batch_size = 100
        for i in range(0, len(dates_to_process), batch_size):
            chunk_dates = dates_to_process[i:i+batch_size]
            chunk_rows = []
            
            with ThreadPoolExecutor(max_workers=32) as executor:
                futures = [executor.submit(fetch_premarket_for_date, d) for d in chunk_dates]
                for f in futures:
                    d, rows = f.result()
                    chunk_rows.extend(rows)
                    
            chunk_df = pd.DataFrame(chunk_rows)
            header_needed = not os.path.exists(CACHE_FILE) or os.path.getsize(CACHE_FILE) == 0
            chunk_df.to_csv(CACHE_FILE, mode='a', index=False, header=header_needed)
            
            curr_processed = min(i + batch_size, len(dates_to_process)) + len(processed_dates)
            print(f"  • Progress: {curr_processed}/{len(all_dates)} dates ({curr_processed/len(all_dates)*100:.1f}%) processed.")
            
    print(f"\n✅ Step 1 complete! Pre-market cache saved at: {CACHE_FILE}")

if __name__ == '__main__':
    main()
