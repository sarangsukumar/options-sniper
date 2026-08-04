"""
Production F11 intraday feature computation using date-chunked DB reads.
Processes data in monthly chunks to keep memory low and leverage the date index.
Uses 1-minute OHLC data up to 15:15 for each stock and date.
"""
import pandas as pd
import numpy as np
import pymysql
from datetime import datetime, time, timedelta
from dateutil.relativedelta import relativedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import warnings
import os
import time as pytime
warnings.filterwarnings('ignore', category=UserWarning, module='pandas')

print("="*70)
print("F11 INTRADAY FEATURES - PRODUCTION CHUNKED")
print("="*70)

# DB config
DB_CONFIG = {'host': 'localhost', 'user': 'root', 'password': 'root', 'database': 'markets'}
TABLE_NAME = 'scrapdata'
CUTOFF_TIME = time(15, 15)  # Use data up to 15:15

import os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(SCRIPT_DIR, 'f11_intraday_features_all.csv')

# Fetch intraday features ONLY for today
today_str = datetime.now().strftime('%Y-%m-%d')
START_DATE = today_str
END_DATE = today_str
print(f"Forced to fetch intraday features ONLY for today: {START_DATE}")
N_WORKERS = 4  # Parallel workers for groupby computation (set to 1 to disable)


# Logger helper with timestamp
def log(msg, level='INFO'):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{ts}] [{level}] {msg}")

log(f"Configuration: period={START_DATE} to {END_DATE}, chunk=1 week, cutoff=15:15, workers={N_WORKERS}")
log(f"Output file: {OUTPUT_FILE}")

# Generate weekly chunks (Mon-Sun), aligned to calendar weeks
def generate_weekly_chunks(start, end):
    chunks = []
    current = pd.to_datetime(start)
    last = pd.to_datetime(end)
    # Start from the Monday of the week containing start_date
    current = current - timedelta(days=current.weekday())
    while current <= last:
        chunk_end = current + timedelta(days=6)
        if chunk_end > last:
            chunk_end = last
        chunks.append((current.strftime('%Y-%m-%d'), chunk_end.strftime('%Y-%m-%d')))
        current = current + timedelta(days=7)
    return chunks

chunks = generate_weekly_chunks(START_DATE, END_DATE)
log(f"Total weekly chunks to process: {len(chunks)}")
log(f"First chunk: {chunks[0][0]} to {chunks[0][1]}")
log(f"Last chunk:  {chunks[-1][0]} to {chunks[-1][1]}")

# Helper: compute F11 features for a single stock-day DataFrame
def compute_f11_for_stockday(stock_df):
    """stock_df: sorted 1-minute bars for one stock on one date up to 15:15"""
    if len(stock_df) < 30:
        return None
    
    open_price = stock_df['open'].iloc[0]
    high = stock_df['high'].max()
    low = stock_df['low'].min()
    close = stock_df['close'].iloc[-1]
    num_bars = len(stock_df)
    
    if open_price <= 0 or close <= 0 or high <= low:
        return None
    
    closes = stock_df['close'].values
    opens = stock_df['open'].values
    highs = stock_df['high'].values
    lows = stock_df['low'].values
    
    # 1. intraday_return
    intraday_return = (close - open_price) / open_price * 100
    
    # 2. intraday_rsi_9
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-9:]) if len(gains) >= 9 else np.mean(gains) if len(gains) > 0 else 0
    avg_loss = np.mean(losses[-9:]) if len(losses) >= 9 else np.mean(losses) if len(losses) > 0 else 0
    if avg_loss == 0:
        intraday_rsi_9 = 100.0
    else:
        rs = avg_gain / avg_loss
        intraday_rsi_9 = 100 - (100 / (1 + rs))
    
    # 3. intraday_macd (using pandas EWM on numpy array)
    s_close = pd.Series(closes)
    ema12 = s_close.ewm(span=12, adjust=False).mean().iloc[-1]
    ema26 = s_close.ewm(span=26, adjust=False).mean().iloc[-1]
    macd_line = ema12 - ema26
    signal_line = (s_close.ewm(span=12, adjust=False).mean() - s_close.ewm(span=26, adjust=False).mean()).ewm(span=9, adjust=False).mean().iloc[-1]
    intraday_macd = macd_line - signal_line
    
    # 4. intraday_ema_cross
    ema9 = s_close.ewm(span=9, adjust=False).mean().iloc[-1]
    ema21 = s_close.ewm(span=21, adjust=False).mean().iloc[-1]
    intraday_ema_cross = (ema9 - ema21) / ema21 * 100 if ema21 != 0 else 0
    
    # 5. intraday_bb_pct_b
    if len(closes) >= 20:
        s_last20 = pd.Series(closes[-20:])
        bb_mean = s_last20.mean()
        bb_std = s_last20.std()
        bb_upper = bb_mean + 2 * bb_std
        bb_lower = bb_mean - 2 * bb_std
        intraday_bb_pct_b = (close - bb_lower) / (bb_upper - bb_lower) if bb_upper != bb_lower else 0.5
    else:
        intraday_bb_pct_b = 0.5
    
    # 6. intraday_vwap_gap (simple TWAP)
    typical_price = (highs + lows + closes) / 3
    twap = np.mean(typical_price)
    intraday_vwap_gap = (close - twap) / twap * 100 if twap != 0 else 0
    
    # 7. intraday_stoch_k
    if len(closes) >= 9:
        recent_high = np.max(highs[-9:])
        recent_low = np.min(lows[-9:])
        intraday_stoch_k = (close - recent_low) / (recent_high - recent_low) * 100 if recent_high != recent_low else 50
    else:
        intraday_stoch_k = 50
    
    # 8. intraday_range_pos
    intraday_range_pos = (close - low) / (high - low) if high != low else 0.5
    
    # 9. intraday_volume_ratio (proxy)
    intraday_volume_ratio = num_bars / 361.0
    
    # 10. intraday_high_low_ratio
    intraday_high_low_ratio = (high - low) / low * 100
    
    # 11. intraday_volatility
    intraday_volatility = np.std(closes) / open_price * 100
    
    # 12. intraday_twap_crosses
    running_twap = pd.Series(typical_price).expanding().mean()
    diff_sign = np.diff(np.sign(stock_df['close'].values - running_twap.values))
    intraday_twap_crosses = np.sum(diff_sign != 0)
    
    # 13. intraday_roc_last_hour
    bar_seconds = stock_df['bar_seconds'].values
    price_1415 = None
    idx_1415 = np.searchsorted(bar_seconds, 14 * 3600 + 15 * 60, side='left')
    if idx_1415 < len(closes):
        price_1415 = closes[idx_1415]
    intraday_roc_last_hour = (close - price_1415) / price_1415 * 100 if price_1415 is not None and price_1415 > 0 else 0
    
    # 14. intraday_orb_pos (first 30 min: 9:15-9:45)
    orb_mask = bar_seconds <= (9 * 3600 + 45 * 60)
    if np.any(orb_mask):
        orb_high = np.max(highs[orb_mask])
        orb_low = np.min(lows[orb_mask])
        intraday_orb_pos = (close - orb_low) / (orb_high - orb_low) if orb_high != orb_low else 0.5
    else:
        intraday_orb_pos = 0.5
    
    # 15. first_tick_to_1519_pct: (close at 15:19 - first market tick at 09:15) / first tick * 100
    market_open_mask = bar_seconds >= (9 * 3600 + 15 * 60)
    if np.any(market_open_mask):
        first_market_idx = np.argmax(market_open_mask)
        first_tick_price = opens[first_market_idx]
    else:
        first_tick_price = open_price
    first_tick_to_1519_pct = (close - first_tick_price) / first_tick_price * 100 if first_tick_price > 0 else 0
    
    # 16. 1450_to_1519_pct: (close at 15:19 - price at 14:50) / price at 14:50 * 100
    price_1450 = None
    idx_1450 = np.searchsorted(bar_seconds, 14 * 3600 + 50 * 60, side='left')
    if idx_1450 < len(closes):
        price_1450 = closes[idx_1450]
    if price_1450 is not None and price_1450 > 0:
        pct_1450_to_1519 = (close - price_1450) / price_1450 * 100
    else:
        pct_1450_to_1519 = 0
    
    return {
        'Date': stock_df['trade_date'].iloc[0],
        'Stock': stock_df['stock'].iloc[0],
        'open': open_price,
        'high': high,
        'low': low,
        'close': close,
        'num_bars': num_bars,
        'intraday_return': intraday_return,
        'intraday_rsi_9': intraday_rsi_9,
        'intraday_macd': intraday_macd,
        'intraday_ema_cross': intraday_ema_cross,
        'intraday_bb_pct_b': intraday_bb_pct_b,
        'intraday_vwap_gap': intraday_vwap_gap,
        'intraday_stoch_k': intraday_stoch_k,
        'intraday_range_pos': intraday_range_pos,
        'intraday_volume_ratio': intraday_volume_ratio,
        'intraday_high_low_ratio': intraday_high_low_ratio,
        'intraday_volatility': intraday_volatility,
        'intraday_twap_crosses': intraday_twap_crosses,
        'intraday_roc_last_hour': intraday_roc_last_hour,
        'intraday_orb_pos': intraday_orb_pos,
        'first_tick_to_1519_pct': first_tick_to_1519_pct,
        '1450_to_1519_pct': pct_1450_to_1519
    }

# Main loop
log("Starting chunked processing...")
overall_start = pytime.time()

# Resume: load already processed dates from output if it exists
processed_dates = set()
header_written = False
if os.path.exists(OUTPUT_FILE):
    try:
        existing = pd.read_csv(OUTPUT_FILE)
        # Ensure we clean out today's entries if they exist to allow clean overwrites/re-runs
        existing['Date_str'] = existing['Date'].astype(str).str.strip()
        today_match = existing['Date_str'] == today_str
        if today_match.any():
            log(f"Detected {today_match.sum()} existing rows for today ({today_str}) in F11 features CSV. Deleting them to allow a clean overwrite...")
            existing = existing[~today_match].copy()
            existing.drop(columns=['Date_str'], inplace=True, errors='ignore')
            existing.to_csv(OUTPUT_FILE, index=False)
            
        processed_dates = set(existing['Date'].astype(str).unique())
        header_written = True
        log(f"Resuming from existing output: {len(processed_dates)} dates already processed, {len(existing):,} rows")
    except Exception as e:
        log(f"Could not read existing output, starting fresh: {e}", level='WARN')
        os.remove(OUTPUT_FILE)


total_stock_days = 0
chunk_times = []

for chunk_idx, (chunk_start, chunk_end) in enumerate(chunks):
    chunk_start_time = pytime.time()
    chunk_dates = set(pd.date_range(chunk_start, chunk_end).strftime('%Y-%m-%d'))
    
    # Resume check: skip chunk if all its dates are already processed
    if chunk_dates.issubset(processed_dates):
        log(f"Chunk {chunk_idx+1}/{len(chunks)} [{chunk_start} to {chunk_end}] SKIP (already processed)")
        continue
    
    log(f"Chunk {chunk_idx+1}/{len(chunks)} [{chunk_start} to {chunk_end}] START")
    
    try:
        conn = pymysql.connect(**DB_CONFIG)
        
        # Fetch meta for this chunk
        meta_query = f"""
        SELECT DISTINCT date as trade_date, TRIM(BOTH '"' FROM TRIM(BOTH "'" FROM TRIM(stockname))) as stock
        FROM {TABLE_NAME}
        WHERE date BETWEEN %s AND %s
        AND TIME(time) <= %s
        AND isvalid = 'TRUE'
        ORDER BY trade_date, stock
        """
        meta_df = pd.read_sql(meta_query, conn, params=[chunk_start, chunk_end, CUTOFF_TIME.strftime('%H:%M:%S')])
        
        if len(meta_df) == 0:
            conn.close()
            log(f"  No stock-days in this chunk", level='SKIP')
            continue
        
        log(f"  Meta: {len(meta_df)} stock-days to process")
        
        # Fetch all minute bars for this chunk up to 15:15
        data_query = f"""
        SELECT 
            TRIM(BOTH '"' FROM TRIM(BOTH "'" FROM TRIM(stockname))) as stock,
            time as datetime,
            DATE(time) as trade_date,
            TIME(time) as bar_time,
            CAST(open AS DECIMAL(10,2)) as open,
            CAST(high AS DECIMAL(10,2)) as high,
            CAST(low AS DECIMAL(10,2)) as low,
            CAST(close AS DECIMAL(10,2)) as close
        FROM {TABLE_NAME}
        WHERE date BETWEEN %s AND %s
        AND TIME(time) <= %s
        AND isvalid = 'TRUE'
        """
        data_df = pd.read_sql(data_query, conn, params=[chunk_start, chunk_end, CUTOFF_TIME.strftime('%H:%M:%S')])
        conn.close()
        
        if len(data_df) == 0:
            log(f"  No minute bars in this chunk", level='SKIP')
            continue
        
        log(f"  Loaded {len(data_df):,} minute bars")
        
        # Convert bar_time to seconds for vectorized comparisons
        data_df['bar_seconds'] = data_df['bar_time'].dt.total_seconds()
        data_df['trade_date_str'] = data_df['trade_date'].astype(str).str[:10]
        
        # Group by stock and date, compute F11 for each (parallel)
        grouped = [g.sort_values('datetime').reset_index(drop=True) for _, g in data_df.groupby(['stock', 'trade_date_str'])]
        
        chunk_features = []
        if N_WORKERS > 1:
            with ThreadPoolExecutor(max_workers=N_WORKERS) as executor:
                futures = {executor.submit(compute_f11_for_stockday, g): i for i, g in enumerate(grouped)}
                for future in as_completed(futures):
                    f11 = future.result()
                    if f11 is not None:
                        chunk_features.append(f11)
        else:
            for g in grouped:
                f11 = compute_f11_for_stockday(g)
                if f11 is not None:
                    chunk_features.append(f11)
        
        # Append to CSV
        if chunk_features:
            chunk_df = pd.DataFrame(chunk_features)
            chunk_df.to_csv(OUTPUT_FILE, mode='a', index=False, header=not header_written)
            header_written = True
            total_stock_days += len(chunk_features)
            new_dates = set(chunk_df['Date'].astype(str).unique())
            processed_dates.update(new_dates)
            log(f"  Computed {len(chunk_features)} features, total so far: {total_stock_days:,}")
            for d in sorted(list(new_dates)):
                log(f"  --> Inserted data for date: {d}")
        
    except Exception as e:
        log(f"  Chunk failed with error: {str(e)}", level='ERROR')
        continue
    
    chunk_elapsed = pytime.time() - chunk_start_time
    chunk_times.append(chunk_elapsed)
    avg_chunk_time = np.mean(chunk_times[-10:]) if chunk_times else 0
    remaining_chunks = len(chunks) - chunk_idx - 1
    eta_seconds = avg_chunk_time * remaining_chunks
    eta_str = f"{eta_seconds/3600:.1f}h" if eta_seconds > 3600 else f"{eta_seconds/60:.1f}m"
    log(f"  Chunk took {chunk_elapsed:.1f}s | Avg(last10): {avg_chunk_time:.1f}s | ETA: {eta_str}")

overall_elapsed = pytime.time() - overall_start
log(f"DONE")
log(f"Total stock-days: {total_stock_days:,}")
log(f"Output file: {OUTPUT_FILE}")
log(f"Total time: {overall_elapsed:.1f}s ({overall_elapsed/60:.1f} min)")

# Show sample
if total_stock_days > 0 and os.path.exists(OUTPUT_FILE):
    try:
        sample_df = pd.read_csv(OUTPUT_FILE, nrows=10)
        log(f"Sample from {OUTPUT_FILE}:")
        print(sample_df.to_string(index=False))
    except Exception as e:
        log(f"Could not read sample: {e}", level='WARN')

print("="*70)
