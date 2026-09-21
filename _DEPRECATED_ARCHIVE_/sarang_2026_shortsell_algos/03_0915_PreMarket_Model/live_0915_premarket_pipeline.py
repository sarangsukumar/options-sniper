#!/usr/bin/env python3
"""
live_0915_premarket_pipeline.py
----------------------------
Production 09:15 AM IST Live Short-Sell Predictor.
Architecture: Model 09:15 Pre-Market.
"""

import os
import sys
import pymysql
import pandas as pd
import numpy as np
import lightgbm as lgb
from datetime import datetime, date
import warnings
import json
import urllib.request
import urllib.parse

warnings.filterwarnings('ignore')

# Base paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_FILE = '/home/ubuntu/v5_from_scratch/models/model_0915_F1_production.txt'
LOTS_FILE = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/config/historical_lotsize_new.csv'
OUTPUT_CSV = os.path.join(SCRIPT_DIR, 'live_predictions_today_0915.csv')
LEDGER_CSV = os.path.join(SCRIPT_DIR, 'daily_0915_live_ledger.csv')

def get_db_connection():
    return pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)

def load_verified_lot_sizes():
    if not os.path.exists(LOTS_FILE): return {}
    df = pd.read_csv(LOTS_FILE)
    if 'lot_size' not in df.columns: return {}
    df['clean_stock'] = df['stock'].astype(str).str.strip().str.upper()
    return dict(zip(df['clean_stock'], df['lot_size']))

def get_exact_lot(stock, dt, lot_map, fallback=1000):
    return int(lot_map.get(stock, fallback))

def send_telegram_msg(msg):
    # Dummy to console for now, actual implementation depends on bot framework
    print(f"TELEGRAM ALERT: {msg}")

def fetch_live_data(target_date_str, prev_date_str):
    conn = get_db_connection()
    with conn.cursor() as cursor:
        # 1. Fetch prior day ticks
        q_prev = f"""
        SELECT TRIM(BOTH '"' FROM TRIM(BOTH "'" FROM TRIM(stockname))) as clean_stock,
               time, CAST(price AS DECIMAL(10,2)) as price
        FROM scrapdata_F1
        WHERE date = '{prev_date_str}' AND isvalid = 'TRUE'
          AND stockname NOT IN ('NIFTY 50', 'NIFTY BANK', 'NIFTY', 'BANKNIFTY', 'FINNIFTY')
        ORDER BY time ASC
        """
        cursor.execute(q_prev)
        df_prev_ticks = pd.DataFrame(cursor.fetchall())

        # 2. Fetch today's 09:07 pre-market prices
        q_0907 = f"""
        SELECT TRIM(BOTH '"' FROM TRIM(BOTH "'" FROM TRIM(stockname))) as clean_stock,
               CAST(price AS DECIMAL(10,2)) as price_0907
        FROM scrapdata_F1
        WHERE date = '{target_date_str}' AND time = '{target_date_str} 09:07:00' AND isvalid = 'TRUE'
        """
        cursor.execute(q_0907)
        rows_0907 = cursor.fetchall()
        df_0907 = pd.DataFrame(rows_0907)
        if len(df_0907) == 0:
            q_0907_eq = f"""
            SELECT TRIM(BOTH '"' FROM TRIM(BOTH "'" FROM TRIM(stockname))) as clean_stock,
                   CAST(price AS DECIMAL(10,2)) as price_0907
            FROM scrapdata
            WHERE date = '{target_date_str}' AND time = '{target_date_str} 09:07:00' AND isvalid = 'TRUE'
            """
            cursor.execute(q_0907_eq)
            df_0907 = pd.DataFrame(cursor.fetchall())
            
    return df_prev_ticks, df_0907

def compute_features(df_prev_ticks, df_0907, target_date_str):
    map_0907 = dict(zip(df_0907['clean_stock'], df_0907['price_0907'].astype(float))) if len(df_0907) > 0 else {}
    records = []
    
    if len(df_prev_ticks) > 0:
        for stock, grp in df_prev_ticks.groupby('clean_stock'):
            prices = grp['price'].astype(float).values
            if len(prices) < 20: continue
            
            p_0907 = map_0907.get(stock, None)
            if p_0907 is None: continue
            
            open_p, close_p, high_p, low_p = prices[0], prices[-1], prices.max(), prices.min()
            ret = (close_p - open_p) / open_p * 100.0 if open_p > 0 else 0.0
            
            deltas = np.diff(prices)
            gains = np.where(deltas > 0, deltas, 0)
            losses = np.where(deltas < 0, -deltas, 0)
            avg_g = float(np.mean(gains[-9:])) if len(gains) >= 9 else float(np.mean(gains)) if len(gains) > 0 else 0.0
            avg_l = float(np.mean(losses[-9:])) if len(losses) >= 9 else float(np.mean(losses)) if len(losses) > 0 else 0.0
            rsi = 100.0 if avg_l == 0 else 100.0 - (100.0 / (1.0 + (avg_g / avg_l)))
            
            s_close = pd.Series(prices)
            ema12 = s_close.ewm(span=12, adjust=False).mean()
            ema26 = s_close.ewm(span=26, adjust=False).mean()
            macd = float((ema12 - ema26).iloc[-1])
            ema_cross = 1 if float(ema12.iloc[-1]) > float(ema26.iloc[-1]) else 0
            
            s_ma = float(s_close.rolling(20).mean().iloc[-1])
            s_std = float(s_close.rolling(20).std().iloc[-1])
            bb_pct_b = (close_p - (s_ma - 2*s_std)) / (4*s_std) if s_std > 0 else 0.5
            
            vwap = float(np.mean(prices))
            vwap_gap = (close_p - vwap) / vwap * 100.0 if vwap > 0 else 0.0
            
            r_low = float(s_close.rolling(14, min_periods=1).min().iloc[-1])
            r_high = float(s_close.rolling(14, min_periods=1).max().iloc[-1])
            stoch_k = (close_p - r_low) / (r_high - r_low) * 100.0 if r_high > r_low else 50.0
            
            range_pos = (close_p - low_p) / (high_p - low_p) * 100.0 if high_p > low_p else 50.0
            
            gap_pct_true = (p_0907 - close_p) / close_p * 100.0 if close_p > 0 else 0.0
            
            records.append({
                'date_str': target_date_str,
                'clean_stock': stock,
                'Gap_Pct': gap_pct_true,
                'gap_0907_pct': gap_pct_true,
                'prev_intraday_return': ret,
                'prev_intraday_rsi_9': rsi,
                'prev_intraday_macd': macd,
                'prev_intraday_ema_cross': ema_cross,
                'prev_intraday_bb_pct_b': bb_pct_b,
                'prev_intraday_vwap_gap': vwap_gap,
                'prev_intraday_stoch_k': stoch_k,
                'prev_intraday_range_pos': range_pos,
                'prev_first_tick_to_1519_pct': ret
            })
    return pd.DataFrame(records)

def predict_model(df_features):
    print("\n2. Loading LightGBM Model 09:15...")
    model = lgb.Booster(model_file=MODEL_FILE)
    
    features = [
        'Gap_Pct', 'gap_0907_pct', 'prev_intraday_return', 'prev_intraday_rsi_9',
        'prev_intraday_macd', 'prev_intraday_ema_cross', 'prev_intraday_bb_pct_b',
        'prev_intraday_vwap_gap', 'prev_intraday_stoch_k', 'prev_intraday_range_pos',
        'prev_first_tick_to_1519_pct'
    ]
    
    X = df_features[features]
    preds = model.predict(X)
    df_features['prob_win'] = preds
    
    # Sort by probability
    df_ranked = df_features.sort_values('prob_win', ascending=False)
    return df_ranked

def main():
    print("=" * 60)
    print(" 🚀 SARANG 2026: 09:15 PRE-MARKET MASTER ORCHESTRATOR 🚀 ")
    print("=" * 60)
    
    target_dt = pd.to_datetime('today').strftime('%Y-%m-%d')
    # For testing, we use the last available date in DB
    conn = get_db_connection()
    with conn.cursor() as c:
        c.execute("SELECT DISTINCT date FROM scrapdata_F1 ORDER BY date DESC LIMIT 2")
        dts = [r['date'] for r in c.fetchall()]
        target_date_str = str(dts[0])
        prev_date_str = str(dts[1])
        
    print(f"1. Fetching Data for {target_date_str}...")
    df_prev_ticks, df_0907 = fetch_live_data(target_date_str, prev_date_str)
    
    if len(df_0907) == 0:
        print("ERROR: No 09:07 pre-market prices found! Waiting for exchange data...")
        return
        
    df_features = compute_features(df_prev_ticks, df_0907, target_date_str)
    df_ranked = predict_model(df_features)
    
    # Top 4 Trades
    df_plan = df_ranked.head(4).copy()
    print("\n--- FINAL 09:15 PRE-MARKET SHORT SELL PORTFOLIO ---")
    for _, row in df_plan.iterrows():
        print(f" ⭐ {row['clean_stock']:<10} | Win Prob: {row['prob_win']*100:.2f}% | Gap: {row['Gap_Pct']:.2f}%")
        
    # Send Telegram
    msg = f"🚀 <b>09:15 PRE-MARKET ALERTS ({target_date_str})</b>\n\n"
    for _, row in df_plan.iterrows():
        msg += f"🔥 <b>SHORT: {row['clean_stock']}</b>\n"
        msg += f"   • Win Prob: {row['prob_win']*100:.1f}%\n"
        msg += f"   • Pre-Mkt Gap: {row['Gap_Pct']:.2f}%\n\n"
    
    send_telegram_msg(msg)

if __name__ == '__main__':
    main()
