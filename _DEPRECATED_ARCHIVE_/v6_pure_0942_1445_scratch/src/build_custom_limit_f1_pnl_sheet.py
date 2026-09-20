#!/usr/bin/env python3
"""
build_custom_limit_f1_pnl_sheet.py
-----------------------------------
Calculates 100% realistic short sell PnL on scrapdata_F1 for all candidate stocks
in markets_pnl0325.csv that met 'Custom Limit Fill' on date T.

Rules:
  1. Candidate Selection: Filter `sell_exec_type == 'Custom Limit Fill'` in markets_pnl0325.csv.
  2. Next Trading Day Execution: Execute trade on the very NEXT trading date (T+1) available in scrapdata_F1.
  3. Entry Price (Short at 09:42 AM):
     - Search 09:42:00 in scrapdata_F1 (is_future = 'F1').
     - Fallbacks if missing: 09:43:00, then 09:44:00.
     - Skip trade if no tick found in [09:42, 09:43, 09:44].
  4. Exit Price (Square off at 14:45 PM):
     - Search 14:45:00 in scrapdata_F1 (is_future = 'F1').
     - Fallbacks if missing: 14:46:00, 14:47:00, 14:44:00, 14:43:00.
     - Skip trade if no tick found in [14:45, 14:46, 14:47, 14:44, 14:43].
  5. Contract Lot Size: Match from historical_lotsize_new.csv.
  6. Commission: Flat ₹500 per trade.
  7. Output File: /home/ubuntu/daily_prediction_sytem_Dynamic_threshold/v6_pure_0942_1445_scratch/output/custom_limit_f1_realistic_pnl_sheet.csv
"""

import os
import pymysql
import pandas as pd
import numpy as np
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_DIR = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/v6_pure_0942_1445_scratch'
MARKETS_PNL = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/data/markets_pnl0325.csv'
LOTS_FILE = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/config/historical_lotsize_new.csv'
OUT_FILE = os.path.join(BASE_DIR, 'output', 'custom_limit_f1_realistic_pnl_sheet.csv')

def fetch_stock_ticks(stk):
    """Fetches target 09:42/43/44 and 14:43/44/45/46/47 ticks for a single stock across all years."""
    conn = pymysql.connect(host='localhost', user='root', password='root', database='markets')
    cursor = conn.cursor()
    query = f"""
        SELECT 
            DATE(time) AS date_str,
            stockname AS clean_stock,
            MAX(CASE WHEN TIME(time) = '09:42:00' THEN CAST(price AS DECIMAL(10,2)) END) AS e_42,
            MAX(CASE WHEN TIME(time) = '09:43:00' THEN CAST(price AS DECIMAL(10,2)) END) AS e_43,
            MAX(CASE WHEN TIME(time) = '09:44:00' THEN CAST(price AS DECIMAL(10,2)) END) AS e_44,
            MAX(CASE WHEN TIME(time) = '14:45:00' THEN CAST(price AS DECIMAL(10,2)) END) AS x_45,
            MAX(CASE WHEN TIME(time) = '14:46:00' THEN CAST(price AS DECIMAL(10,2)) END) AS x_46,
            MAX(CASE WHEN TIME(time) = '14:47:00' THEN CAST(price AS DECIMAL(10,2)) END) AS x_47,
            MAX(CASE WHEN TIME(time) = '14:44:00' THEN CAST(price AS DECIMAL(10,2)) END) AS x_44,
            MAX(CASE WHEN TIME(time) = '14:43:00' THEN CAST(price AS DECIMAL(10,2)) END) AS x_43
        FROM scrapdata_F1
        WHERE stockname = '{stk}'
          AND is_future = 'F1'
          AND isvalid = 'TRUE'
          AND (time LIKE '%09:42:00%' OR time LIKE '%09:43:00%' OR time LIKE '%09:44:00%' 
            OR time LIKE '%14:45:00%' OR time LIKE '%14:46:00%' OR time LIKE '%14:47:00%' 
            OR time LIKE '%14:44:00%' OR time LIKE '%14:43:00%')
        GROUP BY DATE(time), stockname;
    """
    cursor.execute(query)
    res = cursor.fetchall()
    conn.close()

    rows = []
    for row in res:
        d_str = str(row[0])
        stk_clean = str(row[1]).strip().upper()

        # Entry Fallback Logic: 09:42 -> 09:43 -> 09:44
        entry_p = row[2] if row[2] is not None else (row[3] if row[3] is not None else row[4])
        # Exit Fallback Logic: 14:45 -> 14:46 -> 14:47 -> 14:44 -> 14:43
        exit_p = row[5] if row[5] is not None else (
            row[6] if row[6] is not None else (
                row[7] if row[7] is not None else (
                    row[8] if row[8] is not None else row[9]
                )
            )
        )

        if entry_p is not None and exit_p is not None and float(entry_p) > 0 and float(exit_p) > 0:
            rows.append({
                'trade_dt': d_str,
                'clean_stock': stk_clean,
                'entry_price': float(entry_p),
                'exit_price': float(exit_p)
            })
    return rows

def main():
    t_start = time.time()
    print("===================================================================================")
    print("🚀 BUILDING 100% REALISTIC F1 SHORT SELL PNL SHEET FOR ALL CUSTOM LIMIT CANDIDATES")
    print("===================================================================================\n")

    print(f"1. Reading candidate sheet: {MARKETS_PNL}")
    df_raw = pd.read_csv(MARKETS_PNL, low_memory=False)
    custom_df = df_raw[df_raw['sell_exec_type'] == 'Custom Limit Fill'].copy()
    print(f"   Found {len(custom_df):,} 'Custom Limit Fill' candidate records.")

    # Vectorized fast date parsing
    custom_df['sim_dt'] = pd.to_datetime(custom_df['simulationdate'], format='mixed', dayfirst=True, errors='coerce').dt.strftime('%Y-%m-%d')
    custom_df = custom_df.dropna(subset=['sim_dt']).copy()

    # Get distinct market trading dates from scrapdata_F1
    conn = pymysql.connect(host='localhost', user='root', password='root', database='markets')
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT date FROM scrapdata_F1 ORDER BY date ASC;")
    all_trading_dates = np.array([str(r[0]) for r in cursor.fetchall()])
    conn.close()
    print(f"   Fetched {len(all_trading_dates):,} distinct trading dates from scrapdata_F1.")

    # Vectorized next-trading-date matching using np.searchsorted
    sim_dts = custom_df['sim_dt'].values
    idxs = np.searchsorted(all_trading_dates, sim_dts, side='right')
    valid_mask = idxs < len(all_trading_dates)

    custom_df = custom_df[valid_mask].copy()
    custom_df['trade_dt'] = all_trading_dates[idxs[valid_mask]]

    unique_stocks = sorted(custom_df['stockname'].dropna().unique())
    print(f"   Target trade candidates span {len(unique_stocks):,} unique stock tickers.")

    print(f"\n2. Executing Parallel Stock-by-Stock Queries with 20 Workers...")
    db_rows = []
    completed_cnt = 0

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(fetch_stock_ticks, stk): stk for stk in unique_stocks}
        for future in as_completed(futures):
            stk = futures[future]
            try:
                res_rows = future.result()
                db_rows.extend(res_rows)
            except Exception as e:
                print(f"   ⚠️ Error fetching {stk}: {e}")
            completed_cnt += 1
            if completed_cnt % 25 == 0 or completed_cnt == len(unique_stocks):
                print(f"   Completed {completed_cnt}/{len(unique_stocks)} stocks ({len(db_rows):,} valid tick pairs, {time.time()-t_start:.1f}s elapsed)...")

    df_ticks = pd.DataFrame(db_rows)
    print(f"\n   • Total valid F1 tick pairs fetched: {len(df_ticks):,} across all stocks!")

    # Merge candidate trades with F1 ticks
    custom_df['clean_stock'] = custom_df['stockname'].astype(str).str.strip().str.upper()
    df_valid = custom_df.merge(df_ticks, left_on=['trade_dt', 'clean_stock'], right_on=['trade_dt', 'clean_stock'], how='inner')

    print(f"3. Matched {len(df_valid):,} valid candidate trades with scrapdata_F1 entry & exit ticks.")

    # Merge Lot Sizes
    print("4. Merging historical lot sizes and calculating net PnL...")
    df_lots = pd.read_csv(LOTS_FILE)
    df_lots['clean_stock'] = df_lots['stockname'].astype(str).str.strip().str.upper()
    df_lots_stock = df_lots.groupby('clean_stock')['lotsize'].last().reset_index()
    df_valid = df_valid.merge(df_lots_stock, on='clean_stock', how='left')
    df_valid['lot_size'] = df_valid['lotsize'].fillna(1000).astype(int)

    # Compute Returns & PnL
    df_valid['return_pct'] = ((df_valid['entry_price'] - df_valid['exit_price']) / df_valid['entry_price']) * 100.0
    df_valid['gross_pnl_rupees'] = (df_valid['entry_price'] - df_valid['exit_price']) * df_valid['lot_size']
    df_valid['commission_rupees'] = 500.0  # Flat ₹500 per trade
    df_valid['net_pnl_rupees'] = df_valid['gross_pnl_rupees'] - df_valid['commission_rupees']
    df_valid['year'] = pd.to_datetime(df_valid['trade_dt']).dt.year

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)

    # Clean output columns
    out_cols = [
        'sim_dt', 'trade_dt', 'clean_stock', 'entry_price', 'exit_price', 
        'lot_size', 'return_pct', 'gross_pnl_rupees', 'commission_rupees', 
        'net_pnl_rupees', 'year'
    ]
    df_out = df_valid[out_cols].rename(columns={'sim_dt': 'candidate_date', 'trade_dt': 'execution_trade_date'})
    df_out.to_csv(OUT_FILE, index=False)

    print("\n===================================================================================")
    print("🏆 SUMMARY RESULTS: 100% REALISTIC F1 SHORT SELL BASELINE PNL SHEET")
    print("===================================================================================")
    print(f"• Total Candidates ('Custom Limit Fill'):   {len(custom_df):,}")
    print(f"• Total Valid Executed F1 Trades:          {len(df_out):,}")
    print(f"• Total Gross Profit:                     ₹{df_out['gross_pnl_rupees'].sum()/1e7:.5f} Crore")
    print(f"• Total Commission Deduction (₹500/trade): ₹{df_out['commission_rupees'].sum()/1e5:.2f} Lakhs")
    print(f"• OVERALL NET SUM PNL:                    ₹{df_out['net_pnl_rupees'].sum()/1e7:.5f} Crore (₹{df_out['net_pnl_rupees'].sum():,.2f})")
    print(f"• Overall Win Rate:                       {(df_out['net_pnl_rupees'] > 0).mean()*100:.2f}%")
    print(f"• Average Net PnL per Trade:              ₹{df_out['net_pnl_rupees'].mean():,.2f}\n")

    print("📅 YEAR-BY-YEAR BREAKDOWN:")
    for yr in sorted(df_out['year'].unique()):
        ydf = df_out[df_out['year'] == yr]
        net_sum = ydf['net_pnl_rupees'].sum()
        wr = (ydf['net_pnl_rupees'] > 0).mean() * 100
        print(f"  {yr}:  {len(ydf):5d} trades | Win Rate: {wr:5.2f}% | NET PNL: ₹ {net_sum/1e7:8.4f} Cr (₹{net_sum:12,.2f})")

    print(f"\n✅ Sheet successfully built in {time.time()-t_start:.2f}s and saved to: {OUT_FILE}")

if __name__ == '__main__':
    main()
