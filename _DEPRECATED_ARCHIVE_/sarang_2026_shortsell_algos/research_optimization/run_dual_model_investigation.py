#!/usr/bin/env python3
"""
DUAL MASTER MODEL INVESTIGATION & SIMULATION (EQ vs FUTURES)
============================================================
1. Model 1 (Shorter Window: 09:20 -> 09:40 AM)
   - Combined features (Prior Day VWAP/ROC/Arc + 09:18 Morning Candlestick + Pre-market Gap)
   - No Monday filter
   - Evaluated on Equity (`scrapdata`) AND Futures (`scrapdata_F1`)
2. Model 2 (Longer Window: 09:42 -> 14:45 PM)
   - Hybrid Dual Engine (V6 Mean Reversion + V7 Momentum Sniper)
   - Evaluated on Futures (`scrapdata_F1`) AND Equity (`scrapdata`)
   - 3% Stop Loss
"""

import os
import pymysql
import pandas as pd
import numpy as np
import lightgbm as lgb
from concurrent.futures import ThreadPoolExecutor
import warnings
warnings.filterwarnings('ignore')

LOTS_FILE = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/config/historical_lotsize_new.csv'
V8_DATA_FILE = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/v8_model/data/short_sell_ml_dataset_v8.csv'
MORN_918_FILE = '/home/ubuntu/V8_Hybrid_Engine/morning_features_0918.csv'
V6_V7_DATA_FILE = '/home/ubuntu/v5_from_scratch/data/short_sell_ml_dataset_v5_scratch.csv'

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

# ---------------------------------------------------------
# PART 1: SHORTER WINDOW (09:20 -> 09:40 AM)
# ---------------------------------------------------------
def run_shorter_window_model():
    print("\n" + "=" * 80)
    print("⚡ BUILDING BEST SHORTER WINDOW MODEL (09:20 -> 09:40 AM)")
    print("=" * 80)
    
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
    
    # Combined feature list
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
        
    # Filter Mondays out
    df_clean = df[df['day_name'] != 'Monday'].copy()
    df_clean['target'] = (df_clean['return_0920_0940_pct'] > 0).astype(int)
    
    # Walk-forward validation
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
        
    trades_shorter = pd.concat(all_picks).reset_index(drop=True)
    
    # 1. Equity simulation (`scrapdata`)
    trades_shorter['eq_entry'] = trades_shorter['p_0920']
    trades_shorter['eq_exit'] = trades_shorter['p_0940']
    trades_shorter['eq_gross_pnl'] = (trades_shorter['eq_entry'] - trades_shorter['eq_exit']) * trades_shorter['lotsize']
    trades_shorter['eq_net_pnl'] = trades_shorter['eq_gross_pnl'] - 300.0
    
    print("\n--- SHORTER WINDOW ON EQUITY (`scrapdata`) ---")
    y_eq = trades_shorter.groupby('year')['eq_net_pnl'].sum() / 1e5
    tot_eq = trades_shorter['eq_net_pnl'].sum() / 1e5
    wr_eq = (trades_shorter['eq_net_pnl'] > 0).mean() * 100
    print(f"Total Net PnL (Equity): ₹{tot_eq:.2f} Lakhs | Win Rate: {wr_eq:.2f}%")
    for y, p in y_eq.items():
        print(f"  {y}: ₹{p:.2f} Lakhs")
        
    # 2. Futures simulation (`scrapdata_F1`)
    print("\nQuerying Futures `scrapdata_F1` ticks for Shorter Window (09:20 -> 09:40)...")
    
    def fetch_f1_ticks(trade):
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

    # Run in parallel
    trade_list = trades_shorter.to_dict('records')
    with ThreadPoolExecutor(max_workers=8) as ex:
        f1_prices = list(ex.map(fetch_f1_ticks, trade_list))
        
    trades_shorter['f1_entry'] = [p[0] for p in f1_prices]
    trades_shorter['f1_exit'] = [p[1] for p in f1_prices]
    trades_shorter['f1_gross_pnl'] = (trades_shorter['f1_entry'] - trades_shorter['f1_exit']) * trades_shorter['lotsize']
    trades_shorter['f1_net_pnl'] = trades_shorter['f1_gross_pnl'] - 300.0
    
    print("\n--- SHORTER WINDOW ON FUTURES (`scrapdata_F1`) ---")
    y_f1 = trades_shorter.groupby('year')['f1_net_pnl'].sum() / 1e5
    tot_f1 = trades_shorter['f1_net_pnl'].sum() / 1e5
    wr_f1 = (trades_shorter['f1_net_pnl'] > 0).mean() * 100
    print(f"Total Net PnL (Futures): ₹{tot_f1:.2f} Lakhs | Win Rate: {wr_f1:.2f}%")
    for y, p in y_f1.items():
        print(f"  {y}: ₹{p:.2f} Lakhs")
        
    return trades_shorter

if __name__ == '__main__':
    run_shorter_window_model()
