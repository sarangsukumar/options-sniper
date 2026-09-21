#!/usr/bin/env python3
"""
1_build_v8_dataset.py
---------------------
Builds Model V8 Dataset (09:20 AM Entry -> 09:40 AM Exit).

Data Source: MySQL `scrapdata` Equity Table (NOT futures scrapdata_F1).
Charges: Flat ₹300 per trade commission.

Integrates:
  1. V6 Master Previous Day Features (prev_intraday_vwap_gap, prev_intraday_roc_last_hour,
     prev_intraday_return, positive_arc_ratio, rejection_wick, Gap_Pct).
  2. 09:20 AM Entry Price (p_0920) and 09:40 AM Exit Price (p_0940) fetched directly from MySQL `scrapdata` Equity Table.
  3. Strict 09:15-09:19 morning range (morn_range_pct_0920).
  4. Contract Lot Sizes from historical_lotsize_new.csv.
"""

import os
import sys
import pymysql
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_DIR = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/v8_model'
V6_DATA_FILE = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/v6_pure_0942_1445_scratch/data/short_sell_ml_dataset_v6.csv'
LOTS_FILE = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/config/historical_lotsize_new.csv'
OUTPUT_FILE = os.path.join(BASE_DIR, 'data', 'short_sell_ml_dataset_v8.csv')

def get_db_connection():
    return pymysql.connect(
        host='localhost',
        user='root',
        password='root',
        database='markets',
        autocommit=True
    )

def fetch_stock_v8_equity_ticks(stock):
    """
    Fetch 09:15 to 09:42 ticks for a single stock from scrapdata equity table
    """
    conn = get_db_connection()
    query = f"""
    SELECT 
        stockname,
        date,
        TIME(time) as time_str,
        CAST(price AS DECIMAL(10,2)) as price
    FROM scrapdata
    WHERE stockname = '{stock}'
      AND TIME(time) BETWEEN '09:15:00' AND '09:42:00'
      AND isvalid = 'TRUE';
    """
    df_ticks = pd.read_sql(query, conn)
    conn.close()
    return stock, df_ticks

def main():
    print("===================================================================================")
    print("🚀 BUILDING MODEL V8 DATASET (EQUITY TABLE `scrapdata` | 09:20 -> 09:40 EXIT)")
    print("===================================================================================")
    
    print("\n1. Loading Base V6 Master Feature Dataset...")
    df_v6 = pd.read_csv(V6_DATA_FILE, low_memory=False)
    print(f"   Loaded {len(df_v6):,} master feature records.")
    
    if 'date_str' not in df_v6.columns and 'date' in df_v6.columns:
        df_v6['date_str'] = df_v6['date']
    if 'date_str' not in df_v6.columns and 'short_sell_date' in df_v6.columns:
        df_v6['date_str'] = df_v6['short_sell_date']
        
    df_v6['date_str'] = pd.to_datetime(df_v6['date_str']).dt.strftime('%Y-%m-%d')
    unique_stocks = df_v6['clean_stock'].unique().tolist()
    print(f"   Target trade candidates span {len(unique_stocks)} unique stock tickers.")
    
    print("\n2. Querying MySQL EQUITY `scrapdata` for 09:20 & 09:40 Ticks across all stocks...")
    stock_ticks = {}
    completed = 0
    
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(fetch_stock_v8_equity_ticks, s): s for s in unique_stocks}
        for future in as_completed(futures):
            stock, df_t = future.result()
            stock_ticks[stock] = df_t
            completed += 1
            if completed % 25 == 0 or completed == len(unique_stocks):
                print(f"   Fetched {completed}/{len(unique_stocks)} stocks from equity `scrapdata`...")
                
    print("\n3. Processing Equity 09:20 Entry and 09:40 Exit Prices...")
    records = []
    
    for stock, df_t in stock_ticks.items():
        if len(df_t) == 0:
            continue
            
        df_t['date_str'] = pd.to_datetime(df_t['date']).dt.strftime('%Y-%m-%d')
        grouped = df_t.groupby('date_str')
        
        for d_str, group in grouped:
            # 09:20 Entry Ticks
            p_0920 = None
            t_0920 = group[group['time_str'] == '09:20:00']
            if len(t_0920) > 0:
                p_0920 = float(t_0920['price'].iloc[0])
            else:
                t_fb = group[group['time_str'].isin(['09:21:00', '09:22:00'])]
                if len(t_fb) > 0:
                    p_0920 = float(t_fb['price'].iloc[0])
                    
            # 09:40 Exit Ticks
            p_0940 = None
            t_0940 = group[group['time_str'] == '09:40:00']
            if len(t_0940) > 0:
                p_0940 = float(t_0940['price'].iloc[0])
            else:
                t_fb2 = group[group['time_str'].isin(['09:41:00', '09:42:00', '09:39:00', '09:38:00'])]
                if len(t_fb2) > 0:
                    p_0940 = float(t_fb2['price'].iloc[0])
                    
            # 09:15 to 09:19 morning range
            morn_group = group[group['time_str'] <= '09:19:59']
            morn_range_pct_0920 = 0.0
            if len(morn_group) >= 2:
                p_open_0915 = float(morn_group['price'].iloc[0])
                p_high_0919 = float(morn_group['price'].max())
                p_low_0919 = float(morn_group['price'].min())
                morn_range_pct_0920 = ((p_high_0919 - p_low_0919) / (p_open_0915 + 1e-6)) * 100.0
                
            if p_0920 is not None and p_0940 is not None and p_0920 > 0:
                records.append({
                    'clean_stock': stock,
                    'date_str': d_str,
                    'p_0920': p_0920,
                    'p_0940': p_0940,
                    'morn_range_pct_0920': morn_range_pct_0920
                })
                
    df_prices = pd.DataFrame(records)
    print(f"   Extracted {len(df_prices):,} valid Equity 09:20 -> 09:40 price tick pairs.")
    
    print("\n4. Merging Price Ticks with V6 Master Features...")
    df_merged = pd.merge(
        df_v6,
        df_prices,
        on=['clean_stock', 'date_str'],
        how='inner'
    )
    print(f"   Merged dataset contains {len(df_merged):,} complete trade records.")
    
    # Target & Return Calculation
    df_merged['return_0920_0940_pct'] = ((df_merged['p_0920'] - df_merged['p_0940']) / df_merged['p_0920']) * 100.0
    df_merged['target_v8'] = (df_merged['return_0920_0940_pct'] > 0).astype(int)
    
    # Save output dataset
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    df_merged.to_csv(OUTPUT_FILE, index=False)
    print(f"\n✅ Model V8 Equity Dataset successfully created and saved to:\n   {OUTPUT_FILE}")

if __name__ == '__main__':
    main()
