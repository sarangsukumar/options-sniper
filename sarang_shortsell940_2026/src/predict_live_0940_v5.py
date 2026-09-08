#!/usr/bin/env python3
"""
5_live_prediction_0940_v5.py
----------------------------
Production Daily Live Inference Runner (Model v5).
Runs automatically via cron at 09:40:05 AM every trading day.

CORE ALGORITHM RULE:
  Only evaluates candidates that met 'Custom Limit Fill' in markets_pnl0325.csv
  for the latest trading date.

15 Strictly Leak-Free Features:
  1. Gap_Pct
  2. gap_0907_pct
  3. gap_fade_0907_to_940_pct
  4. stock_ret_940
  5. morn_range_pct
  6. rejection_wick
  7. prev_intraday_return
  8. prev_intraday_rsi_9
  9. prev_intraday_macd
 10. prev_intraday_ema_cross
 11. prev_intraday_bb_pct_b
 12. prev_intraday_vwap_gap
 13. prev_intraday_stoch_k
 14. prev_intraday_range_pos
 15. prev_first_tick_to_1519_pct
"""

import pymysql
import pandas as pd
import numpy as np
import lightgbm as lgb
import requests
import os
import datetime
import warnings
warnings.filterwarnings('ignore')

BASE_DIR = '/home/ubuntu/shortsellmodel940v5'
MODEL_PATH = os.path.join(BASE_DIR, 'models', 'model_v5_lgb.txt')
PNL_PATH = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/data/markets_pnl0325.csv'
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', 'YOUR_CHAT_ID_HERE')

def send_telegram_alert(message):
    if TELEGRAM_BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
        print("\n[Telegram Alert Preview]")
        print(message)
        return
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'Markdown'
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        print("Telegram alert dispatched successfully!")
    except Exception as e:
        print(f"Failed to send Telegram alert: {e}")

def compute_prev_day_indicators(prev_df):
    """Computes prior day intraday indicators from 1-min tick bars."""
    res = {}
    for stock, g in prev_df.groupby('clean_stock'):
        prices = g['price'].astype(float).values
        if len(prices) < 5:
            continue
        open_p = float(prices[0])
        close_p = float(prices[-1])
        high_p = float(prices.max())
        low_p = float(prices.min())
        
        # 1. Return
        ret = (close_p - open_p) / open_p * 100.0 if open_p > 0 else 0.0
        
        # 2. RSI 9
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_g = float(np.mean(gains[-9:])) if len(gains) >= 9 else float(np.mean(gains)) if len(gains) > 0 else 0.0
        avg_l = float(np.mean(losses[-9:])) if len(losses) >= 9 else float(np.mean(losses)) if len(losses) > 0 else 0.0
        rsi9 = 100.0 if avg_l == 0 else 100.0 - (100.0 / (1.0 + (avg_g / avg_l)))
        
        # 3. MACD
        s_close = pd.Series(prices)
        ema12 = float(s_close.ewm(span=12, adjust=False).mean().iloc[-1])
        ema26 = float(s_close.ewm(span=26, adjust=False).mean().iloc[-1])
        macd_val = ema12 - ema26
        
        # 4. EMA Cross
        ema9 = float(s_close.ewm(span=9, adjust=False).mean().iloc[-1])
        ema21 = float(s_close.ewm(span=21, adjust=False).mean().iloc[-1])
        ema_cross = (ema9 - ema21) / ema21 * 100.0 if ema21 > 0 else 0.0
        
        # 5. BB %B
        s_std = float(s_close.rolling(20, min_periods=1).std().iloc[-1])
        s_ma = float(s_close.rolling(20, min_periods=1).mean().iloc[-1])
        bb_pct_b = (close_p - (s_ma - 2*s_std)) / (4*s_std) if s_std > 0 else 0.5
        
        # 6. VWAP Gap
        vwap = float(np.mean(prices))
        vwap_gap = (close_p - vwap) / vwap * 100.0 if vwap > 0 else 0.0
        
        # 7. Stoch K
        r_low = float(s_close.rolling(14, min_periods=1).min().iloc[-1])
        r_high = float(s_close.rolling(14, min_periods=1).max().iloc[-1])
        stoch_k = (close_p - r_low) / (r_high - r_low) * 100.0 if r_high > r_low else 50.0
        
        # 8. Range Pos
        range_pos = (close_p - low_p) / (high_p - low_p) * 100.0 if high_p > low_p else 50.0
        
        # 9. First tick to 15:19 trend
        trend_1519 = (close_p - open_p) / open_p * 100.0 if open_p > 0 else 0.0
        
        res[stock] = {
            'prev_close': close_p,
            'prev_intraday_return': ret,
            'prev_intraday_rsi_9': rsi9,
            'prev_intraday_macd': macd_val,
            'prev_intraday_ema_cross': ema_cross,
            'prev_intraday_bb_pct_b': bb_pct_b,
            'prev_intraday_vwap_gap': vwap_gap,
            'prev_intraday_stoch_k': stoch_k,
            'prev_intraday_range_pos': range_pos,
            'prev_first_tick_to_1519_pct': trend_1519
        }
    return pd.DataFrame.from_dict(res, orient='index').reset_index().rename(columns={'index': 'clean_stock'})

def main():
    today_str = datetime.datetime.now().strftime('%Y-%m-%d')
    print("==================================================================")
    print(f"LIVE INFERENCE RUNNER (MODEL v5) - {today_str} @ 09:40 AM")
    print("==================================================================")
    
    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError(f"Production model file {MODEL_PATH} not found!")
        
    booster = lgb.Booster(model_file=MODEL_PATH)
    
    # 1. Load Custom Limit Candidates from markets_pnl0325.csv
    print(f"1. Reading Custom Limit Fills from: {PNL_PATH}")
    valid_candidates = []
    try:
        pnl_df = pd.read_csv(PNL_PATH)
        pnl_df['entry_date'] = pd.to_datetime(pnl_df['simulationdate'], format='mixed', dayfirst=True, errors='coerce')
        last_trading_date = pnl_df['entry_date'].max()
        
        recent_fills = pnl_df[(pnl_df['entry_date'] == last_trading_date) & (pnl_df['sell_exec_type'].astype(str).str.contains('Custom Limit'))]
        valid_candidates = recent_fills['stockname'].astype(str).str.strip().str.upper().tolist()
        print(f" Found {len(valid_candidates)} Custom Limit candidate stocks for date {last_trading_date.strftime('%Y-%m-%d')}.")
    except Exception as e:
        print(f"⚠️ Error reading markets_pnl0325.csv: {e}")
        
    cand_sql_clause = ""
    if valid_candidates:
        cand_strs = ",".join([f"'{s}'" for s in valid_candidates])
        cand_sql_clause = f" AND TRIM(BOTH '\"' FROM TRIM(BOTH \"'\" FROM TRIM(stockname))) IN ({cand_strs}) "
    
    # 2. Connect to MySQL Database
    conn = pymysql.connect(host='localhost', user='root', password='root', database='markets')
    cursor = conn.cursor()
    
    # Detect previous trading date
    cursor.execute(f"SELECT MAX(date) FROM scrapdata_F1 WHERE date < '{today_str}'")
    prev_date_row = cursor.fetchone()
    prev_date_str = str(prev_date_row[0]) if prev_date_row and prev_date_row[0] else None
    print(f" Identified previous trading date: {prev_date_str}")
    
    # 3. Fetch previous day intraday ticks
    q_prev = f"""
    SELECT TRIM(BOTH '"' FROM TRIM(BOTH "'" FROM TRIM(stockname))) as clean_stock,
           time, CAST(price AS DECIMAL(10,2)) as price
    FROM scrapdata_F1
    WHERE date = '{prev_date_str}' AND isvalid='TRUE' {cand_sql_clause}
    ORDER BY time ASC
    """
    cursor.execute(q_prev)
    df_prev = pd.DataFrame(cursor.fetchall(), columns=['clean_stock', 'time', 'price'])
    
    # 4. Fetch today's 09:07 AM pre-market ticks from BOTH scrapdata and scrapdata_F1
    q_0907_eq = f"SELECT TRIM(BOTH '\"' FROM TRIM(BOTH \"'\" FROM TRIM(stockname))) as clean_stock, CAST(price AS DECIMAL(10,2)) as price_0907_eq FROM scrapdata WHERE date = '{today_str}' AND time = '{today_str} 09:07:00' AND isvalid='TRUE' {cand_sql_clause}"
    cursor.execute(q_0907_eq)
    df_0907_eq = pd.DataFrame(cursor.fetchall(), columns=['clean_stock', 'price_0907_eq'])
    
    q_0907_f1 = f"SELECT TRIM(BOTH '\"' FROM TRIM(BOTH \"'\" FROM TRIM(stockname))) as clean_stock, CAST(price AS DECIMAL(10,2)) as price_0907_f1 FROM scrapdata_F1 WHERE date = '{today_str}' AND time = '{today_str} 09:07:00' AND isvalid='TRUE' {cand_sql_clause}"
    cursor.execute(q_0907_f1)
    df_0907_f1 = pd.DataFrame(cursor.fetchall(), columns=['clean_stock', 'price_0907_f1'])
    
    # 5. Fetch today's morning 09:15-09:40 ticks
    q_morn = f"""
    SELECT TRIM(BOTH '"' FROM TRIM(BOTH "'" FROM TRIM(stockname))) as clean_stock,
           time, CAST(price AS DECIMAL(10,2)) as price
    FROM scrapdata_F1
    WHERE date = '{today_str}' AND time >= '{today_str} 09:15:00' AND time <= '{today_str} 09:40:00' AND isvalid='TRUE' {cand_sql_clause}
    ORDER BY time ASC
    """
    cursor.execute(q_morn)
    df_morn = pd.DataFrame(cursor.fetchall(), columns=['clean_stock', 'time', 'price'])
    conn.close()
    
    if df_morn.empty:
        print(f"⚠️ No morning ticks found in scrapdata_F1 for candidate stocks on date {today_str}.")
        return
        
    # 6. Compute Previous Day Indicators
    df_prev_features = compute_prev_day_indicators(df_prev)
    
    # 7. Compute Morning Indicators
    morn_list = []
    for stock, g in df_morn.groupby('clean_stock'):
        prices = g['price'].astype(float).values
        if len(prices) < 3:
            continue
        open_p = float(prices[0])
        close_p = float(prices[-1])
        high_p = float(prices.max())
        low_p = float(prices.min())
        
        ret_940 = (close_p - open_p) / open_p * 100.0 if open_p > 0 else 0.0
        morn_range = (high_p - low_p) / open_p * 100.0 if open_p > 0 else 0.0
        range_denom = high_p - low_p
        rejection_wick = (high_p - close_p) / range_denom if range_denom > 0 else 0.5
        
        morn_list.append({
            'clean_stock': stock,
            'morning_open': open_p,
            'morning_close': close_p,
            'stock_ret_940': ret_940,
            'morn_range_pct': morn_range,
            'rejection_wick': rejection_wick
        })
        
    df_features = pd.DataFrame(morn_list)
    df_features = df_features.merge(df_prev_features, on='clean_stock', how='inner')
    df_features = df_features.merge(df_0907_eq, on='clean_stock', how='left')
    df_features = df_features.merge(df_0907_f1, on='clean_stock', how='left')
    
    # Engineer premarket unified price & features
    df_features['price_0907_eq'] = pd.to_numeric(df_features['price_0907_eq'], errors='coerce')
    df_features['price_0907_f1'] = pd.to_numeric(df_features['price_0907_f1'], errors='coerce')
    df_features['price_0907_unified'] = df_features['price_0907_f1'].fillna(df_features['price_0907_eq']).fillna(df_features['morning_open'])
    
    df_features['Gap_Pct'] = np.where(
        df_features['prev_close'] > 0,
        ((df_features['morning_open'] - df_features['prev_close']) / df_features['prev_close']) * 100.0,
        0.0
    )
    df_features['gap_0907_pct'] = np.where(
        df_features['prev_close'] > 0,
        ((df_features['price_0907_unified'] - df_features['prev_close']) / df_features['prev_close']) * 100.0,
        df_features['Gap_Pct']
    )
    df_features['gap_fade_0907_to_940_pct'] = np.where(
        df_features['price_0907_unified'] > 0,
        ((df_features['morning_close'] - df_features['price_0907_unified']) / df_features['price_0907_unified']) * 100.0,
        0.0
    )
    
    feature_cols = [
        'Gap_Pct', 'gap_0907_pct', 'gap_fade_0907_to_940_pct',
        'stock_ret_940', 'morn_range_pct', 'rejection_wick',
        'prev_intraday_return', 'prev_intraday_rsi_9', 'prev_intraday_macd',
        'prev_intraday_ema_cross', 'prev_intraday_bb_pct_b', 'prev_intraday_vwap_gap',
        'prev_intraday_stoch_k', 'prev_intraday_range_pos', 'prev_first_tick_to_1519_pct'
    ]
    
    # Fill NaNs & predict probabilities
    X_live = df_features[feature_cols].fillna(0.0)
    df_features['prob_win'] = booster.predict(X_live)
    
    top3 = df_features.sort_values('prob_win', ascending=False).head(3).reset_index(drop=True)
    
    # 8. Build Telegram Alert Message
    msg = f"🔥 *SHORT SELL MODEL v5 HIGH CONVICTION SIGNALS ({today_str})*\n"
    msg += f"⏰ *Entry Time:* 09:42 AM | *Exit Time:* 02:45 PM\n\n"
    
    for idx, row in top3.iterrows():
        msg += f"*{idx+1}. {row['clean_stock']}*\n"
        msg += f"   • Win Prob: `{row['prob_win']*100:.1f}%`\n"
        msg += f"   • 09:40 Price: `₹{row['morning_close']:,.2f}`\n"
        msg += f"   • Pre-Market Fade: `{row['gap_fade_0907_to_940_pct']:+.2f}%`\n"
        msg += f"   • Morning Return: `{row['stock_ret_940']:+.2f}%`\n\n"
        
    msg += "🚀 *Action:* Place Short Sell limit order at 09:42 AM!"
    
    send_telegram_alert(msg)

if __name__ == '__main__':
    main()
