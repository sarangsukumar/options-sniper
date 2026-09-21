import pymysql
import pandas as pd
import numpy as np
import datetime
import os
import time

print("--- MASSIVE FULL UNIVERSE EXTRACTOR ---")
csv_path = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/recreate_models_from_scratch/massive_universe_dataset.csv'

processed_dates = set()
if os.path.exists(csv_path):
    try:
        existing_df = pd.read_csv(csv_path, usecols=['date'])
        processed_dates = set(existing_df['date'].unique())
        print(f"Resuming... Found {len(processed_dates)} dates already processed.")
    except Exception as e:
        print("Starting fresh CSV.")

# Get dates instantly from existing dataset instead of slow SQL Group By
print("Loading dates...")
df_dates = pd.read_csv('/home/ubuntu/github_repo/shortsellmodel940v3/short_sell_ml_dataset_v3.csv.gz', usecols=['short_sell_date'], low_memory=False)
df_dates['date_obj'] = pd.to_datetime(df_dates['short_sell_date'])
all_dates = sorted(df_dates[df_dates['date_obj'] >= '2015-01-01']['date_obj'].dt.strftime('%Y-%m-%d').unique())

dates_to_process = [d for d in all_dates if d not in processed_dates]
print(f"Dates remaining to process: {len(dates_to_process)}")

db = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)
cur = db.cursor()

for i, d in enumerate(dates_to_process):
    start_t = time.time()
    
    q_morning = f"""
        SELECT stockname, 
               MIN(CASE WHEN time >= '{d} 09:15:00' THEN price END) as open_price,
               MAX(CASE WHEN time >= '{d} 09:15:00' AND time <= '{d} 09:40:59' THEN high END) as morning_high,
               MIN(CASE WHEN time >= '{d} 09:15:00' AND time <= '{d} 09:40:59' THEN low END) as morning_low,
               MAX(CASE WHEN time >= '{d} 09:40:00' AND time <= '{d} 09:40:59' THEN price END) as morning_close,
               SUM(CASE WHEN time >= '{d} 09:15:00' AND time <= '{d} 09:40:59' THEN volume END) as morning_volume,
               MAX(CASE WHEN time >= '{d} 09:42:00' AND time <= '{d} 09:42:59' THEN price END) as entry_price,
               MAX(CASE WHEN time >= '{d} 14:45:00' AND time <= '{d} 14:46:59' THEN price END) as exit_price
        FROM scrapdata 
        WHERE date = '{d}' 
        GROUP BY stockname
    """
    cur.execute(q_morning)
    rows = cur.fetchall()
    
    if not rows: continue
    
    df = pd.DataFrame(rows)
    df = df.dropna(subset=['open_price', 'morning_close', 'morning_volume', 'entry_price', 'exit_price'])
    
    # Clean penny stocks
    df = df[df['open_price'] > 50.0].copy()
    if df.empty: continue
    
    # Calculate Features
    df['Gap_Pct'] = ((df['open_price'] - df['morning_close']) / df['open_price']) * 100.0 
    df['morning_return'] = ((df['morning_close'] - df['open_price']) / df['open_price']) * 100.0
    
    # Calculate Daily Ranks
    df['Daily_Volume_Rank'] = df['morning_volume'].rank(ascending=False, method='min')
    df['Daily_Momentum_Rank'] = df['morning_return'].rank(ascending=False, method='min')
    
    # Target Return (09:42 to 14:45 Short Sell)
    df['pure_eq_return'] = ((df['entry_price'] - df['exit_price']) / df['entry_price']) * 100.0
    df['target'] = (df['pure_eq_return'] > 0).astype(int)
    
    df['date'] = d
    
    # Save append
    write_header = not os.path.exists(csv_path)
    df.to_csv(csv_path, mode='a', header=write_header, index=False)
    
    print(f"[{i+1}/{len(dates_to_process)}] Processed {d} ({len(df)} stocks) in {time.time()-start_t:.2f} seconds.", flush=True)

print("\n--- MASSIVE DATASET GENERATION COMPLETE ---")
db.close()
