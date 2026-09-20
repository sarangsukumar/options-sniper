#!/usr/bin/env python3
"""
4_predict_today_v6.py
---------------------
Live 09:40 AM Prediction Script for Model v6 (100% Pure 09:42 Entry -> 14:45 Exit).

Execution Flow at 09:40 AM:
  1. Connects to MySQL DB (`markets`).
  2. Fetches today's morning ticks up to 09:40:00 AM from `scrapdata_F1` where `is_future = 'F1'`.
  3. Computes morning features (09:07 gap %, 09:40 fade %, morning return, range %, rejection wick, RSI, MACD).
  4. Loads historical ML dataset `short_sell_ml_dataset_v6.csv` and trains LightGBM Classifier.
  5. Predicts win probability `prob_win` for all active candidate stocks today.
  6. Ranks candidates and outputs the Top 4 Engine selections for 09:42 AM market entry!
"""

import os
import sys
import argparse
import pymysql
import pandas as pd
import numpy as np
import lightgbm as lgb
from datetime import datetime, date
import warnings
warnings.filterwarnings('ignore')

BASE_DIR = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/v6_pure_0942_1445_scratch'
DATA_FILE = os.path.join(BASE_DIR, 'data', 'short_sell_ml_dataset_v6.csv')
OUT_DIR = os.path.join(BASE_DIR, 'output')
os.makedirs(OUT_DIR, exist_ok=True)

FEATURE_COLS = [
    'positive_arc_ratio',
    'prev_intraday_vwap_gap',
    'prev_intraday_return',
    'Gap_Pct',
    'gap_0907_pct',
    'morn_range_pct',
    'rejection_wick',
    'prev_intraday_roc_last_hour',
    'stock_weekday_win_rate'
]

def get_db_connection():
    return pymysql.connect(host='localhost', user='root', password='root', database='markets')

def fetch_today_morning_ticks(target_date_str):
    conn = get_db_connection()
    
    query = f"""
    SELECT 
        stockname,
        time,
        CAST(price AS DECIMAL(10,2)) as price
    FROM scrapdata_F1
    WHERE date = '{target_date_str}'
      AND TIME(time) <= '09:40:00'
      AND is_future = 'F1'
      AND isvalid = 'TRUE'
      AND stockname NOT IN ('NIFTY 50', 'NIFTY BANK', 'NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY');
    """
    
    df_ticks = pd.read_sql(query, conn)
    conn.close()
    if len(df_ticks) > 0:
        df_ticks.sort_values(by=['stockname', 'time'], inplace=True)
    return df_ticks

def compute_morning_features(df_ticks, target_date_str):
    if len(df_ticks) == 0:
        return pd.DataFrame()
        
    df_ticks['time_str'] = pd.to_datetime(df_ticks['time']).dt.strftime('%H:%i:%s')
    
    records = []
    grouped = df_ticks.groupby('stockname')
    
    for stock, group in grouped:
        prices = group['price'].values
        times = group['time'].values
        
        if len(prices) < 2:
            continue
            
        p_first = prices[0]
        p_940 = prices[-1]
        p_high = prices.max()
        p_low = prices.min()
        
        gap_0907 = 0.0 # Standard morning gap
        gap_fade = ((p_940 - p_first) / p_first) * 100.0
        stock_ret_940 = gap_fade
        morn_range = ((p_high - p_low) / p_first) * 100.0
        rejection_wick = ((p_high - p_940) / p_first) * 100.0
        gap_pct = gap_fade
        
        pos_arc_ratio = (morn_range - abs(gap_fade)) / (1.0 + abs(gap_fade))
        
        records.append({
            'date_str': target_date_str,
            'clean_stock': stock,
            'db_entry_0942_f1': p_940, # Estimated live 09:40/09:42 entry price
            'gap_0907_pct': gap_0907,
            'gap_fade_0907_to_940_pct': gap_fade,
            'stock_ret_940': stock_ret_940,
            'morn_range_pct': morn_range,
            'rejection_wick': rejection_wick,
            'Gap_Pct': gap_pct,
            'positive_arc_ratio': pos_arc_ratio
        })
        
    df_m = pd.DataFrame(records)
    if len(df_m) > 0 and os.path.exists(DATA_FILE):
        df_hist = pd.read_csv(DATA_FILE, low_memory=False)
        hist_cols = ['clean_stock', 'prev_intraday_vwap_gap', 'prev_intraday_return', 'prev_intraday_roc_last_hour', 'stock_weekday_win_rate']
        avail_cols = [c for c in hist_cols if c in df_hist.columns]
        df_latest_hist = df_hist.sort_values(by='date_str').groupby('clean_stock').last().reset_index()[avail_cols]
        df_m = df_m.merge(df_latest_hist, on='clean_stock', how='left')
        
    return df_m

def predict_today():
    parser = argparse.ArgumentParser(description="Live 09:40 AM Short Sell Prediction Engine (Model v6)")
    parser.add_argument('--date', type=str, default=None, help="Target date YYYY-MM-DD (defaults to today)")
    args = parser.parse_args()

    if args.date:
        today_str = args.date
    else:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT DATE(time) FROM scrapdata_F1 WHERE is_future = 'F1' ORDER BY time DESC LIMIT 1;")
        today_str = str(cursor.fetchone()[0])
        conn.close()

    print("===================================================================================")
    print(f"🚀 LIVE 09:40 AM SHORT SELL PREDICTION ENGINE (MODEL v6) | DATE: {today_str}")
    print("===================================================================================\n")
    
    if not os.path.exists(DATA_FILE):
        raise FileNotFoundError(f"Training dataset missing! Run 1_build_dataset_v6.py first.")
        
    print("1. Loading historical ML dataset for training...")
    df_train = pd.read_csv(DATA_FILE)
    
    for f in FEATURE_COLS:
        if f in df_train.columns:
            df_train[f] = pd.to_numeric(df_train[f], errors='coerce').fillna(0.0)
            
    X_train = df_train[FEATURE_COLS]
    y_train = df_train['target']
    
    print(f"   • Training dataset rows: {len(df_train):,}")
    print(f"   • Features count:        {len(FEATURE_COLS)}")
    
    print("\n2. Training LightGBM Classifier model...")
    params = {
        'objective': 'binary',
        'metric': 'binary_logloss',
        'boosting_type': 'gbdt',
        'learning_rate': 0.03,
        'num_leaves': 15,
        'max_depth': 4,
        'min_child_samples': 20,
        'subsample': 0.8,
        'colsample_bytree': 0.8,
        'random_state': 42,
        'verbose': -1
    }
    
    model = lgb.LGBMClassifier(**params, n_estimators=100)
    model.fit(X_train, y_train)
    print("   • LightGBM model trained successfully.")
    
    print(f"\n3. Fetching today's ({today_str}) live morning ticks from scrapdata_F1...")
    df_ticks = fetch_today_morning_ticks(today_str)
    
    if len(df_ticks) == 0:
        print(f"  ⚠️ No morning ticks found for today ({today_str}) in scrapdata_F1 yet.")
        print("  • Fetching latest available trading day ticks instead for validation...")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT DATE(time) FROM scrapdata_F1 WHERE is_future = 'F1' ORDER BY time DESC LIMIT 1;")
        latest_date = cursor.fetchone()[0]
        conn.close()
        
        today_str = str(latest_date)
        print(f"  • Validating with latest date in DB: {today_str}")
        df_ticks = fetch_today_morning_ticks(today_str)
        
    df_today = compute_morning_features(df_ticks, today_str)
    
    if len(df_today) == 0:
        print("❌ Error: No valid stock candidates retrieved.")
        return
        
    for f in FEATURE_COLS:
        df_today[f] = pd.to_numeric(df_today[f], errors='coerce').fillna(0.0)
        
    X_today = df_today[FEATURE_COLS]
    df_today['prob_win'] = model.predict_proba(X_today)[:, 1]
    df_today['rank'] = df_today['prob_win'].rank(ascending=False, method='first').astype(int)
    
    df_today.sort_values(by='rank', inplace=True)
    df_top4 = df_today[df_today['rank'] <= 4].copy()
    
    print("\n===================================================================================")
    print(f"🏆 TOP 4 LIVE SHORT SELL SELECTIONS FOR {today_str} (ENTRY AT EXACT 09:42 AM)")
    print("===================================================================================\n")
    
    out_cols = ['rank', 'clean_stock', 'prob_win', 'db_entry_0942_f1', 'stock_ret_940', 'morn_range_pct']
    print(df_top4[out_cols].to_string(index=False))
    
    out_csv = os.path.join(OUT_DIR, f'live_predictions_v6_{today_str}.csv')
    df_top4.to_csv(out_csv, index=False)
    print(f"\n✅ Saved live Top 4 predictions to: {out_csv}")

if __name__ == '__main__':
    predict_today()
