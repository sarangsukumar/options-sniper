import pymysql
import pandas as pd
import numpy as np
import datetime
import os

print("--- BUILDING FULL UNIVERSE DATASET ---")
print("This script calculates morning features and Daily Rank for ALL stocks in the database.")

db = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)
cur = db.cursor()

# Get all unique dates
cur.execute("SELECT DISTINCT date FROM scrapdata WHERE date >= '2024-01-01' ORDER BY date")
dates = [d['date'] for d in cur.fetchall()]

# We will just do 1 year (2024) as a proof-of-concept because 10 years would take 24+ hours
print(f"Found {len(dates)} dates in 2024. Processing...")

all_records = []

for d in dates:
    print(f"Processing Date: {d}")
    
    # Get all ticks for this day
    q = f"SELECT time, stockname, price, high, low, close, volume FROM scrapdata WHERE date = '{d}'"
    cur.execute(q)
    rows = cur.fetchall()
    
    if not rows: continue
    df = pd.DataFrame(rows)
    df['time_str'] = df['time'].astype(str)
    
    # 09:15 Open
    open_df = df[df['time_str'] >= f"{d} 09:15:00"].groupby('stockname').first().reset_index()
    open_df.rename(columns={'price': 'open_price'}, inplace=True)
    
    # Previous day close (Approximation: if we don't have it, we assume gap is from first tick)
    # To be precise, we just rank by morning volume for now, as volume rank is highly indicative of liquidity
    morn_df = df[(df['time_str'] >= f"{d} 09:15:00") & (df['time_str'] <= f"{d} 09:40:59")]
    vol_agg = morn_df.groupby('stockname')['volume'].sum().reset_index()
    vol_agg.rename(columns={'volume': 'morning_volume'}, inplace=True)
    
    # 09:42 Entry Price
    entry_df = df[df['time_str'] >= f"{d} 09:42:00"].groupby('stockname').first().reset_index()
    entry_df.rename(columns={'price': 'entry_price'}, inplace=True)
    
    # 14:45 Exit Price
    exit_df = df[df['time_str'] >= f"{d} 14:45:00"].groupby('stockname').first().reset_index()
    exit_df.rename(columns={'price': 'exit_price'}, inplace=True)
    
    # Merge them
    day_df = pd.merge(open_df[['stockname', 'open_price']], vol_agg, on='stockname', how='inner')
    day_df = pd.merge(day_df, entry_df[['stockname', 'entry_price']], on='stockname', how='inner')
    day_df = pd.merge(day_df, exit_df[['stockname', 'exit_price']], on='stockname', how='inner')
    
    # Filter out penny stocks < 50 Rs
    day_df = day_df[day_df['open_price'] > 50.0]
    
    # CREATE THE RANK FEATURE
    day_df['Daily_Volume_Rank'] = day_df['morning_volume'].rank(ascending=False, method='min')
    
    # Calculate Target PnL (Short Sell: Entry - Exit)
    day_df['pure_eq_return'] = ((day_df['entry_price'] - day_df['exit_price']) / day_df['entry_price']) * 100.0
    day_df['target'] = (day_df['pure_eq_return'] > 0).astype(int)
    
    day_df['date'] = d
    all_records.append(day_df)

final_df = pd.concat(all_records, ignore_index=True)
out_path = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/recreate_models_from_scratch/full_universe_2024.csv'
final_df.to_csv(out_path, index=False)

print(f"\nSUCCESS! Saved {len(final_df)} rows to {out_path}")
print("You can now train a model with 'Daily_Volume_Rank' as a feature!")
