import pandas as pd
import requests
import time
from datetime import datetime
import os

CSV_PATH = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/data/yahoo_finance_all_stocks_2015_2026_gap_features.csv'

print("Loading dataset...")
df = pd.read_csv(CSV_PATH)
df['Date'] = pd.to_datetime(df['Date'])

# Find rows from July 7, 2026 onwards where Volume_Change_Pct is 0.0
mask = (df['Date'] >= '2026-07-07') & (df['Volume_Change_Pct'] == 0.0)
target_rows = df[mask]
print(f"Found {len(target_rows)} rows to backfill.")

stocks = target_rows['Stock'].unique()
print(f"Fetching historical volume for {len(stocks)} stocks...")

session = requests.Session()
session.headers.update({'User-Agent': 'Mozilla/5.0'})

for i, stock in enumerate(stocks):
    symbol = "^NSMID_50" if stock == "NIFTY NEXT 50" else f"{stock}.NS"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=3mo"
    
    try:
        res = session.get(url, timeout=10)
        data = res.json()
        
        timestamps = data['chart']['result'][0]['timestamp']
        volumes = data['chart']['result'][0]['indicators']['quote'][0]['volume']
        
        vol_dict = {}
        for t, v in zip(timestamps, volumes):
            dt = datetime.fromtimestamp(t).strftime('%Y-%m-%d')
            vol_dict[dt] = v
            
        # Update dataframe
        stock_mask = mask & (df['Stock'] == stock)
        for idx in df[stock_mask].index:
            date_str = df.at[idx, 'Date'].strftime('%Y-%m-%d')
            
            # Find the date index in timestamps
            try:
                date_idx = [datetime.fromtimestamp(t).strftime('%Y-%m-%d') for t in timestamps].index(date_str)
                if date_idx > 0:
                    vol_today = volumes[date_idx]
                    vol_yesterday = volumes[date_idx - 1]
                    
                    if vol_yesterday and vol_yesterday > 0 and vol_today:
                        change_pct = ((vol_today - vol_yesterday) / vol_yesterday) * 100
                        df.at[idx, 'Volume_Change_Pct'] = round(change_pct, 6)
            except ValueError:
                pass # Date not found in yahoo response

    except Exception as e:
        print(f"Failed to fetch {stock}: {e}")
        
    time.sleep(0.1) # Be nice to Yahoo API

print("\nSaving updated dataset...")
df.to_csv(CSV_PATH, index=False)
print("Backfill completed successfully!")
