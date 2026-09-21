import pymysql
import pandas as pd
import numpy as np
import datetime
import os
import time

print("--- MASSIVE 09:20 SCALP EXTRACTOR (ENTRY 09:21, EXIT 09:40) ---")
csv_path = '/home/ubuntu/massive_0920_scalp_dataset.csv'

processed_dates = set()
if os.path.exists(csv_path):
    existing_df = pd.read_csv(csv_path, usecols=['date'])
    processed_dates = set(existing_df['date'].unique())

df_dates = pd.read_csv('/home/ubuntu/github_repo/shortsellmodel940v3/short_sell_ml_dataset_v3.csv.gz', usecols=['short_sell_date'], low_memory=False)
df_dates['date_obj'] = pd.to_datetime(df_dates['short_sell_date'])
all_dates = sorted(df_dates[df_dates['date_obj'] >= '2015-01-01']['date_obj'].dt.strftime('%Y-%m-%d').unique())
dates_to_process = [d for d in all_dates if d not in processed_dates]

db = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)
cur = db.cursor()

for i, d in enumerate(dates_to_process):
    # 09:15 to 09:19 features
    # 09:21 to 09:22 entry (Realistic 2-minute buffer)
    # 09:40 to 09:41 exit (SCALP)
    q_morning = f"""
        SELECT stockname, 
               MIN(CASE WHEN time >= '{d} 09:15:00' THEN price END) as open_price,
               MAX(CASE WHEN time >= '{d} 09:15:00' AND time <= '{d} 09:19:59' THEN high END) as morning_high,
               MIN(CASE WHEN time >= '{d} 09:15:00' AND time <= '{d} 09:19:59' THEN low END) as morning_low,
               MAX(CASE WHEN time >= '{d} 09:19:00' AND time <= '{d} 09:19:59' THEN price END) as morning_close,
               SUM(CASE WHEN time >= '{d} 09:15:00' AND time <= '{d} 09:19:59' THEN volume END) as morning_volume,
               MAX(CASE WHEN time >= '{d} 09:21:00' AND time <= '{d} 09:22:59' THEN price END) as entry_price,
               MAX(CASE WHEN time >= '{d} 09:40:00' AND time <= '{d} 09:41:59' THEN price END) as exit_price
        FROM scrapdata WHERE date = '{d}' GROUP BY stockname
    """
    cur.execute(q_morning)
    rows = cur.fetchall()
    if not rows: continue
    
    df = pd.DataFrame(rows)
    df = df.dropna(subset=['open_price', 'morning_close', 'morning_volume', 'entry_price', 'exit_price'])
    df = df[df['open_price'] > 50.0].copy()
    if df.empty: continue
    
    df['Gap_Pct'] = ((df['open_price'] - df['morning_close']) / df['open_price']) * 100.0 
    df['morning_return'] = ((df['morning_close'] - df['open_price']) / df['open_price']) * 100.0
    df['Daily_Volume_Rank'] = df['morning_volume'].rank(ascending=False, method='min')
    df['Daily_Momentum_Rank'] = df['morning_return'].rank(ascending=False, method='min')
    df['pure_eq_return'] = ((df['entry_price'] - df['exit_price']) / df['entry_price']) * 100.0
    df['target'] = (df['pure_eq_return'] > 0).astype(int)
    df['date'] = d
    
    write_header = not os.path.exists(csv_path)
    df.to_csv(csv_path, mode='a', header=write_header, index=False)
    print(f"[{i+1}/{len(dates_to_process)}] Processed {d} ({len(df)} stocks)")

db.close()
