import pandas as pd
import numpy as np
import pymysql
from datetime import datetime, time
import warnings
import os

warnings.filterwarnings('ignore', category=UserWarning, module='pandas')

# DB config 
DB_CONFIG = {'host': 'localhost', 'user': 'root', 'password': 'root', 'database': 'markets'}
TABLE_NAME = 'scrapdata_F1'
CUTOFF_TIME = time(9, 40)

OUTPUT_FILE = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell940_2026/data/live_morning_features.csv'

today_str = datetime.now().strftime('%Y-%m-%d')
print(f"Fetching Live Morning (09:40) Features for today: {today_str}")

def compute_morning_f11(stock_df):
    """stock_df: sorted 1-minute bars up to 09:40"""
    if len(stock_df) < 5:  
        return None
    
    open_price = stock_df['open'].iloc[0]
    high = stock_df['high'].max()
    low = stock_df['low'].min()
    close = stock_df['close'].iloc[-1]
    
    if open_price <= 0 or close <= 0 or high <= low:
        return None
    
    closes = stock_df['close'].values
    opens = stock_df['open'].values
    highs = stock_df['high'].values
    lows = stock_df['low'].values
    
    morning_return = (close - open_price) / open_price * 100
    
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-9:]) if len(gains) >= 9 else np.mean(gains) if len(gains) > 0 else 0
    avg_loss = np.mean(losses[-9:]) if len(losses) >= 9 else np.mean(losses) if len(losses) > 0 else 0
    if avg_loss == 0:
        morning_rsi_9 = 100.0
    else:
        rs = avg_gain / avg_loss
        morning_rsi_9 = 100 - (100 / (1 + rs))
    
    s_close = pd.Series(closes)
    ema12 = s_close.ewm(span=12, adjust=False).mean().iloc[-1]
    ema26 = s_close.ewm(span=26, adjust=False).mean().iloc[-1]
    macd_line = ema12 - ema26
    signal_line = (s_close.ewm(span=12, adjust=False).mean() - s_close.ewm(span=26, adjust=False).mean()).ewm(span=9, adjust=False).mean().iloc[-1]
    morning_macd = macd_line - signal_line
    
    ema9 = s_close.ewm(span=9, adjust=False).mean().iloc[-1]
    ema21 = s_close.ewm(span=21, adjust=False).mean().iloc[-1]
    morning_ema_cross = (ema9 - ema21) / ema21 * 100 if ema21 != 0 else 0
    
    s_close_rolling = s_close.rolling(window=20, min_periods=1)
    std20 = s_close_rolling.std().iloc[-1]
    ma20 = s_close_rolling.mean().iloc[-1]
    if pd.isna(std20) or std20 == 0:
        morning_bb_pct_b = 0.5
    else:
        upper = ma20 + (2 * std20)
        lower = ma20 - (2 * std20)
        morning_bb_pct_b = (close - lower) / (upper - lower)
        
    typical_price = (stock_df['high'] + stock_df['low'] + stock_df['close']) / 3
    vol = np.ones(len(typical_price))
    vwap = np.sum(typical_price * vol) / np.sum(vol)
    morning_vwap_gap = (close - vwap) / vwap * 100
    
    recent_low = s_close.rolling(window=14, min_periods=1).min().iloc[-1]
    recent_high = s_close.rolling(window=14, min_periods=1).max().iloc[-1]
    if recent_high == recent_low:
        morning_stoch_k = 50.0
    else:
        morning_stoch_k = (close - recent_low) / (recent_high - recent_low) * 100
        
    if high == low:
        morning_range_pos = 50.0
    else:
        morning_range_pos = (close - low) / (high - low) * 100
        
    morning_volatility = s_close.pct_change().std() * 100 if len(s_close) > 2 else 0

    return {
        'Date': today_str,
        'Stock': stock_df['stock'].iloc[0],
        'morning_return': morning_return,
        'morning_range': ((high - low) / low) * 100,
        'morning_rsi_9': morning_rsi_9,
        'morning_macd': morning_macd,
        'morning_ema_cross': morning_ema_cross,
        'morning_bb_pct_b': morning_bb_pct_b,
        'morning_vwap_gap': morning_vwap_gap,
        'morning_stoch_k': morning_stoch_k,
        'morning_range_pos': morning_range_pos,
        'morning_volatility': morning_volatility,
        'morning_volume': 1, 
        'morning_momentum': morning_rsi_9 - 50,
        'morning_vol_trend': 1 
    }

def run():
    # 1. Get Candidate Stocks from markets_pnl0325.csv FIRST
    print("Reading Custom Limit Fills from markets_pnl0325.csv to optimize DB query...")
    pnl_path = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/data/markets_pnl0325.csv'
    try:
        pnl_df = pd.read_csv(pnl_path)
        pnl_df['entry_date'] = pd.to_datetime(pnl_df['simulationdate'], format='mixed', dayfirst=True, errors='coerce')
        last_trading_date = pnl_df['entry_date'].max()
        
        recent_fills = pnl_df[(pnl_df['entry_date'] == last_trading_date) & (pnl_df['sell_exec_type'] == 'Custom Limit Fill')]
        valid_candidates = recent_fills['stockname'].str.strip().str.upper().tolist()
        
        if not valid_candidates:
            print("No Custom Limit Fills found for the previous day. Exiting without querying DB.")
            return
            
        print(f"Found {len(valid_candidates)} candidates. Querying scrapdata ONLY for these stocks...")
    except Exception as e:
        print(f"Error reading markets_pnl0325.csv: {e}")
        return

    # 2. Query Scrapdata ONLY for these candidates
    try:
        conn = pymysql.connect(**DB_CONFIG)
        
        cand_strs = ",".join([f"'{s}'" for s in valid_candidates])
        
        data_query = f"""
        SELECT 
            TRIM(BOTH '"' FROM TRIM(BOTH "'" FROM TRIM(stockname))) as stock,
            time as datetime,
            CAST(open AS DECIMAL(10,2)) as open,
            CAST(high AS DECIMAL(10,2)) as high,
            CAST(low AS DECIMAL(10,2)) as low,
            CAST(close AS DECIMAL(10,2)) as close
        FROM {TABLE_NAME}
        WHERE date = %s
        AND TIME(time) BETWEEN '09:15:00' AND %s
        AND stockname IN ({cand_strs})
        AND isvalid='TRUE'
        """
        data_df = pd.read_sql(data_query, conn, params=[today_str, CUTOFF_TIME.strftime('%H:%M:%S')])
        conn.close()
        
        if len(data_df) == 0:
            print(f"No minute bars found for the {len(valid_candidates)} candidates up to 09:40.")
            return
        
        grouped = [g.sort_values('datetime').reset_index(drop=True) for _, g in data_df.groupby('stock')]
        
        features = []
        for g in grouped:
            res = compute_morning_f11(g)
            if res is not None:
                features.append(res)
                
        out_df = pd.DataFrame(features)
        out_df.to_csv(OUTPUT_FILE, index=False)
        print(f"Successfully computed 09:40 morning features for {len(out_df)} candidate stocks -> {OUTPUT_FILE}")
        
    except Exception as e:
        print(f"Error computing morning features: {e}")

if __name__ == "__main__":
    run()
