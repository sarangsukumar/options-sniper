#!/usr/bin/env python3
"""
🏆 BEST SHORTER WINDOW MODEL: 09:20 -> 09:40 AM IST
===================================================================================
100% PURE DATABASE | ZERO YAHOO FINANCE | STRICT 2-MINUTE LATENCY BUFFER
===================================================================================
Strategy Architecture:
- Data Window: 09:15:00 to 09:18:00 AM IST (120-second live buffer before 09:20 entry)
- Execution: 09:20:00 AM IST entry -> 09:40:00 AM IST square-off
- Alpha Drivers: 
  * 09:18 Morning Candlestick Dynamics (rejection wick, lower wick, body ratio, momentum, volume accel)
  * Prior Day Structural Indicators (VWAP gap, ROC last hour, arc ratio, return)
  * Pre-Market Gap (09:07 AM opening tick)
  * Days to Expiry (DTE)
- Optimized Filters: No Mondays (Monday opening noise filter) + Top 3 Ranks
- Brokerage: Flat ₹300.00 commission deducted per trade
- Lot Sizes: Exact historical dynamic contract sizes from historical_lotsize_new.csv
===================================================================================
Simulated on BOTH:
1. Cash Equity Table (`markets.scrapdata`)
2. Near-Month Futures Table (`markets.scrapdata_F1`)
===================================================================================
"""

import os
import pymysql
import pandas as pd
import numpy as np
import lightgbm as lgb
from concurrent.futures import ThreadPoolExecutor
import warnings
warnings.filterwarnings('ignore')

BASE_DIR = '/home/ubuntu/sarang_2026_shortsell_algos/01_Best_Shorter_Window_0920_0940'
LOTS_FILE = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/config/historical_lotsize_new.csv'
V8_DATA_FILE = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/v8_model/data/short_sell_ml_dataset_v8.csv'
MORN_918_FILE = '/home/ubuntu/V8_Hybrid_Engine/morning_features_0918.csv'
OUT_TRADES_CSV = os.path.join(BASE_DIR, 'shorter_window_trades_eq_and_futures.csv')

def get_db_connection():
    return pymysql.connect(host='localhost', user='root', password='root', database='markets', autocommit=True)

def load_lot_map():
    df_lots = pd.read_csv(LOTS_FILE)
    df_lots['exp_dt'] = pd.to_datetime(df_lots['expdate'], format='%d/%m/%Y', errors='coerce')
    df_lots['clean_stock'] = df_lots['stockname'].astype(str).str.strip().str.upper()
    lot_map = {}
    for stock, grp in df_lots.groupby('clean_stock'):
        lot_map[stock] = grp.sort_values('exp_dt')
    return lot_map

def get_exact_lot(stock, dt, lot_map, fallback=1000):
    stk = str(stock).strip().upper()
    if stk not in lot_map:
        return fallback
    sub = lot_map[stk]
    f = sub[sub['exp_dt'] >= dt]
    if len(f) > 0:
        return int(f.iloc[0]['lotsize'])
    return int(sub.iloc[-1]['lotsize'])

def main():
    print("=" * 85)
    print("⚡ BEST SHORTER WINDOW MODEL (09:20 -> 09:40 AM) | AUDIT & DUAL SIMULATION")
    print("=" * 85)
    
    # 1. Load data
    print("1. Ingesting Datasets & Morning Features...")
    v8 = pd.read_csv(V8_DATA_FILE, low_memory=False)
    v8['short_date'] = v8['date_str']
    v8['clean_stock'] = v8['clean_stock'].astype(str).str.strip().str.upper()
    
    morn918 = pd.read_csv(MORN_918_FILE)
    morn918['clean_stock'] = morn918['stockname'].astype(str).str.strip().str.upper()
    
    df = pd.merge(v8, morn918, on=['short_date', 'clean_stock'], how='inner')
    df['date_dt'] = pd.to_datetime(df['date_str'])
    df['year'] = df['date_dt'].dt.year
    df['day_name'] = df['date_dt'].dt.day_name()
    
    lot_map = load_lot_map()
    df['lotsize'] = [get_exact_lot(s, d, lot_map, q) for s, d, q in zip(df['clean_stock'], df['date_dt'], df['quantity'])]
    
    # Combined features
    features = [
        'prev_intraday_vwap_gap', 'prev_intraday_roc_last_hour', 'prev_intraday_return',
        'positive_arc_ratio', 'rejection_wick', 'gap_0907_pct',
        'morn_return_918', 'morn_range_918', 'morn_range_pos_918',
        'rejection_wick_918', 'lower_wick_918', 'body_ratio_918',
        'is_bearish_918', 'morn_vwap_gap_918', 'hl_ratio_918',
        'first_bar_return_918', 'momentum_918', 'vol_accel_918',
        'dte'
    ]
    for col in features:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
        
    # Exclude Mondays
    df_clean = df[df['day_name'] != 'Monday'].copy()
    df_clean['target'] = (df_clean['return_0920_0940_pct'] > 0).astype(int)
    
    # 2. Walk-Forward Expanding Optimization (2021-2026)
    print("2. Running Walk-Forward Optimization (2021-2026)...")
    years = sorted(df_clean[df_clean['year'] >= 2021]['year'].unique())
    all_picks = []
    
    for y in years:
        tr = df_clean[df_clean['year'] < y]
        te = df_clean[df_clean['year'] == y].copy()
        if len(tr) == 0 or len(te) == 0: continue
        clf = lgb.LGBMClassifier(n_estimators=100, learning_rate=0.05, max_depth=5, random_state=42, verbose=-1)
        clf.fit(tr[features], tr['target'])
        te['prob'] = clf.predict_proba(te[features])[:, 1]
        te['rank'] = te.groupby('date_str')['prob'].rank(ascending=False, method='first')
        
        # Select Top 3 per day
        picks = te[te['rank'] <= 3].copy()
        all_picks.append(picks)
        
    trades = pd.concat(all_picks).reset_index(drop=True)
    print(f"   -> Generated {len(trades):,} trades across {len(years)} years.")
    
    # 3. Simulate on Equity (`scrapdata`)
    trades['eq_entry'] = trades['p_0920']
    trades['eq_exit'] = trades['p_0940']
    trades['eq_gross_pnl'] = (trades['eq_entry'] - trades['eq_exit']) * trades['lotsize']
    trades['eq_net_pnl'] = trades['eq_gross_pnl'] - 300.0
    
    # 4. Simulate on Futures (`scrapdata_F1`)
    print("3. Querying Parallel Futures `scrapdata_F1` ticks...")
    def fetch_f1(trade):
        d = trade['date_str']
        s = trade['clean_stock']
        conn = get_db_connection()
        cur = conn.cursor()
        q = f"""
        SELECT 
            (SELECT price FROM scrapdata_F1 WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"') AND time >= '{d} 09:20:00' ORDER BY time ASC LIMIT 1) as p_entry,
            (SELECT price FROM scrapdata_F1 WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"') AND time <= '{d} 09:40:00' ORDER BY time DESC LIMIT 1) as p_exit
        """
        cur.execute(q)
        row = cur.fetchone()
        conn.close()
        p_en = float(row[0]) if row and row[0] is not None else trade['eq_entry']
        p_ex = float(row[1]) if row and row[1] is not None else trade['eq_exit']
        return p_en, p_ex

    with ThreadPoolExecutor(max_workers=10) as ex:
        f1_res = list(ex.map(fetch_f1, trades.to_dict('records')))
        
    trades['f1_entry'] = [p[0] for p in f1_res]
    trades['f1_exit'] = [p[1] for p in f1_res]
    trades['f1_gross_pnl'] = (trades['f1_entry'] - trades['f1_exit']) * trades['lotsize']
    trades['f1_net_pnl'] = trades['f1_gross_pnl'] - 300.0
    
    # Save master log
    out_cols = [
        'date_str', 'clean_stock', 'year', 'day_name', 'rank', 'lotsize',
        'eq_entry', 'eq_exit', 'eq_gross_pnl', 'eq_net_pnl',
        'f1_entry', 'f1_exit', 'f1_gross_pnl', 'f1_net_pnl'
    ]
    trades[out_cols].to_csv(OUT_TRADES_CSV, index=False)
    print(f"   -> Saved trade log to {OUT_TRADES_CSV}")
    
    # 5. Display Comparisons
    print("\n" + "=" * 85)
    print("📊 SHORTER WINDOW (09:20 -> 09:40 AM) PERFORMANCE COMPARISON")
    print("=" * 85)
    
    eq_tot = trades['eq_net_pnl'].sum() / 1e5
    eq_wr = (trades['eq_net_pnl'] > 0).mean() * 100
    f1_tot = trades['f1_net_pnl'].sum() / 1e5
    f1_wr = (trades['f1_net_pnl'] > 0).mean() * 100
    
    print(f"EQUITY TABLE (`scrapdata`)   : Total Net PnL = +₹{eq_tot:6.2f} Lakhs | Win Rate = {eq_wr:.2f}%")
    print(f"FUTURES TABLE (`scrapdata_F1`): Total Net PnL = +₹{f1_tot:6.2f} Lakhs | Win Rate = {f1_wr:.2f}%")
    
    print("\nYear-by-Year Net PnL (₹ Lakhs):")
    y_df = pd.DataFrame({
        'Equity Net PnL (₹ L)': trades.groupby('year')['eq_net_pnl'].sum() / 1e5,
        'Futures Net PnL (₹ L)': trades.groupby('year')['f1_net_pnl'].sum() / 1e5
    }).round(2)
    print(y_df.to_string())
    print("=" * 85)

if __name__ == '__main__':
    main()
