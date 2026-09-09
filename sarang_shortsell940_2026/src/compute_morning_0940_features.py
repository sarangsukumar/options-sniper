import pandas as pd
import numpy as np
import pymysql
from datetime import datetime, time
import warnings
import os

warnings.filterwarnings('ignore')

DB_CONFIG = {'host': 'localhost', 'user': 'root', 'password': 'root', 'database': 'markets'}
OUTPUT_FILE = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell940_2026/data/live_morning_features.csv'
PNL_PATH = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/data/markets_pnl0325.csv'

def compute_prev_day_indicators(df_prev):
    res = {}
    for stock, g in df_prev.groupby('clean_stock'):
        prices = g['price'].astype(float).values
        if len(prices) < 5:
            continue
            
        open_p = float(prices[0])
        close_p = float(prices[-1])
        high_p = float(prices.max())
        low_p = float(prices.min())
        
        ret = (close_p - open_p) / open_p * 100.0 if open_p > 0 else 0.0
        
        s_close = pd.Series(prices)
        deltas = s_close.diff()
        gains = deltas.where(deltas > 0, 0.0)
        losses = -deltas.where(deltas < 0, 0.0)
        avg_gain = gains.rolling(9, min_periods=1).mean().iloc[-1]
        avg_loss = losses.rolling(9, min_periods=1).mean().iloc[-1]
        rs = avg_gain / avg_loss if avg_loss > 0 else 100.0
        rsi9 = 100.0 - (100.0 / (1.0 + rs)) if avg_loss > 0 else 100.0
        
        ema12 = s_close.ewm(span=12, adjust=False).mean().iloc[-1]
        ema26 = s_close.ewm(span=26, adjust=False).mean().iloc[-1]
        macd_line = ema12 - ema26
        signal_line = (s_close.ewm(span=12, adjust=False).mean() - s_close.ewm(span=26, adjust=False).mean()).ewm(span=9, adjust=False).mean().iloc[-1]
        macd_val = macd_line - signal_line
        
        ema9 = s_close.ewm(span=9, adjust=False).mean().iloc[-1]
        ema21 = s_close.ewm(span=21, adjust=False).mean().iloc[-1]
        ema_cross = (ema9 - ema21) / ema21 * 100.0 if ema21 > 0 else 0.0
        
        s_std = float(s_close.rolling(20, min_periods=1).std().iloc[-1])
        s_ma = float(s_close.rolling(20, min_periods=1).mean().iloc[-1])
        bb_pct_b = (close_p - (s_ma - 2*s_std)) / (4*s_std) if s_std > 0 else 0.5
        
        vwap = float(np.mean(prices))
        vwap_gap = (close_p - vwap) / vwap * 100.0 if vwap > 0 else 0.0
        
        r_low = float(s_close.rolling(14, min_periods=1).min().iloc[-1])
        r_high = float(s_close.rolling(14, min_periods=1).max().iloc[-1])
        stoch_k = (close_p - r_low) / (r_high - r_low) * 100.0 if r_high > r_low else 50.0
        
        range_pos = (close_p - low_p) / (high_p - low_p) * 100.0 if high_p > low_p else 50.0
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

def run():
    today_str = datetime.now().strftime('%Y-%m-%d')
    print(f"Fetching Live Morning (09:40) Model v5 Features for today: {today_str}")
    
    # 1. Load Custom Limit Candidates
    valid_candidates = []
    try:
        pnl_df = pd.read_csv(PNL_PATH)
        pnl_df['entry_date'] = pd.to_datetime(pnl_df['simulationdate'], format='mixed', dayfirst=True, errors='coerce')
        last_trading_date = pnl_df['entry_date'].max()
        recent_fills = pnl_df[(pnl_df['entry_date'] == last_trading_date) & (pnl_df['sell_exec_type'].astype(str).str.contains('Custom Limit'))]
        valid_candidates = recent_fills['stockname'].astype(str).str.strip().str.upper().tolist()
    except Exception as e:
        print(f"⚠️ Error reading markets_pnl0325.csv: {e}")

    cand_sql_clause = ""
    if valid_candidates:
        cand_strs = ",".join([f"'{s}'" for s in valid_candidates])
        cand_sql_clause = f" AND TRIM(BOTH '\"' FROM TRIM(BOTH \"'\" FROM TRIM(stockname))) IN ({cand_strs}) "

    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()

    cursor.execute(f"SELECT MAX(date) FROM scrapdata_F1 WHERE date < '{today_str}'")
    prev_date_row = cursor.fetchone()
    prev_date_str = str(prev_date_row[0]) if prev_date_row and prev_date_row[0] else None

    # Fetch prev day
    q_prev = f"""
    SELECT TRIM(BOTH '"' FROM TRIM(BOTH "'" FROM TRIM(stockname))) as clean_stock,
           time, CAST(price AS DECIMAL(10,2)) as price
    FROM scrapdata_F1
    WHERE date = '{prev_date_str}' AND isvalid='TRUE' {cand_sql_clause}
    ORDER BY time ASC
    """
    cursor.execute(q_prev)
    df_prev = pd.DataFrame(cursor.fetchall(), columns=['clean_stock', 'time', 'price'])

    # Fetch 09:07 premarket
    q_0907_eq = f"SELECT TRIM(BOTH '\"' FROM TRIM(BOTH \"'\" FROM TRIM(stockname))) as clean_stock, CAST(price AS DECIMAL(10,2)) as price_0907_eq FROM scrapdata WHERE date = '{today_str}' AND time = '{today_str} 09:07:00' AND isvalid='TRUE' {cand_sql_clause}"
    cursor.execute(q_0907_eq)
    df_0907_eq = pd.DataFrame(cursor.fetchall(), columns=['clean_stock', 'price_0907_eq'])

    q_0907_f1 = f"SELECT TRIM(BOTH '\"' FROM TRIM(BOTH \"'\" FROM TRIM(stockname))) as clean_stock, CAST(price AS DECIMAL(10,2)) as price_0907_f1 FROM scrapdata_F1 WHERE date = '{today_str}' AND time = '{today_str} 09:07:00' AND isvalid='TRUE' {cand_sql_clause}"
    cursor.execute(q_0907_f1)
    df_0907_f1 = pd.DataFrame(cursor.fetchall(), columns=['clean_stock', 'price_0907_f1'])

    # Fetch morning 09:15-09:40
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
        print(f"⚠️ No morning ticks found in scrapdata_F1 for date {today_str}.")
        return

    df_prev_features = compute_prev_day_indicators(df_prev)

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

    df_features['Date'] = today_str
    df_features.rename(columns={'clean_stock': 'Stock'}, inplace=True)
    df_features.to_csv(OUTPUT_FILE, index=False)
    print(f"Successfully computed 09:40 Model v5 features for {len(df_features)} stocks -> {OUTPUT_FILE}")

if __name__ == "__main__":
    run()
