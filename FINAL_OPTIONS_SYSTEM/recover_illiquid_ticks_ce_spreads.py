#!/usr/bin/env python3
import mysql.connector
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from backtest_experiment import get_lot_size

db = mysql.connector.connect(host='localhost', user='root', password='root', database='markets')
cursor = db.cursor(dictionary=True)

fut_file = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/historical_models/output/trades_dynamic_threshold.csv'
fut_df = pd.read_csv(fut_file)
fut_df['date_str'] = pd.to_datetime(fut_df['date']).dt.strftime('%Y-%m-%d')
fut_df['rank'] = fut_df.groupby('date').cumcount() + 1
fut_df['year'] = pd.to_datetime(fut_df['date']).dt.year

r1_r3_fut = fut_df[(fut_df['year'] >= 2024) & (fut_df['rank'].isin([1, 3]))].copy()

stocks = tuple(r1_r3_fut['stock'].unique())
stk_str = "', '".join(stocks)
cursor.execute(f"SELECT stock_code, DATE(datetime) as dt, TIME(datetime) as tm, strike_price, `open`, `close` FROM scrapdata_options WHERE stock_code IN ('{stk_str}') AND `right`='Call'")
all_ticks = cursor.fetchall()
cursor.close()
db.close()

tick_map_close = {}
stk_days = {}

for r in all_ticks:
    stk = r['stock_code']
    d_str = str(r['dt'])
    t_str = str(r['tm'])
    sp = float(r['strike_price'])
    cl = float(r['close']) if r['close'] else 0
    op = float(r['open']) if r['open'] else 0
    px = cl if cl > 0 else op
    if px > 0:
        tick_map_close[(stk, d_str, t_str, sp)] = px
    if stk not in stk_days: stk_days[stk] = set()
    stk_days[stk].add(d_str)

for stk in stk_days:
    stk_days[stk] = sorted(list(stk_days[stk]))

def get_strike_step(price):
    if price > 2500: return 50
    if price > 1000: return 20
    if price > 500:  return 10
    if price > 100:  return 5
    if price > 50:   return 2.5
    return 1

def generate_call_spread_strikes(buy_price):
    step = get_strike_step(buy_price)
    atm = round(buy_price / step) * step
    return atm - step, atm + step

def lookup_relaxed_10min(stock, date, strike, target_time_str, window_minutes=10):
    target_dt = datetime.strptime(f"{date} {target_time_str}", "%Y-%m-%d %H:%M:%S")
    best_px = None
    min_diff = float('inf')
    
    for delta in range(-window_minutes, window_minutes + 1):
        curr_dt = target_dt + timedelta(minutes=delta)
        t_str = curr_dt.strftime("%H:%M:%S")
        key = (stock, date, t_str, float(strike))
        if key in tick_map_close:
            diff = abs(delta)
            if diff < min_diff:
                min_diff = diff
                best_px = tick_map_close[key]
                
    return best_px

date_counts = r1_r3_fut.groupby('date_str')['rank'].count().to_dict()

recovered_records = []

for _, row in r1_r3_fut.iterrows():
    stock = row['stock']
    buy_date = str(row['date_str'])
    y = row['year']
    rank = row['rank']
    
    num_trades_today = date_counts.get(buy_date, 1)
    alloc_cap = 200000 if num_trades_today > 1 else 400000
    
    if stock not in stk_days: continue
    days = [d for d in stk_days[stock] if d > buy_date]
    if len(days) < 1: continue
    d1_exit = days[0]
    
    sample_strikes = [sp for (s, d, t, sp) in tick_map_close.keys() if s == stock and d == buy_date]
    if not sample_strikes: continue
    price = float(np.median(sample_strikes))
    
    buy_strike, sell_strike = generate_call_spread_strikes(price)
    lot_size = get_lot_size(stock, buy_date)
    
    be = lookup_relaxed_10min(stock, buy_date, buy_strike, "15:26:00", 10)
    se = lookup_relaxed_10min(stock, buy_date, sell_strike, "15:26:00", 10)
    bx = lookup_relaxed_10min(stock, d1_exit, buy_strike, "09:25:00", 10)
    sx = lookup_relaxed_10min(stock, d1_exit, sell_strike, "09:25:00", 10)
    
    if None in [be, se, bx, sx]: continue
    
    debit_paid = be - se
    margin = (debit_paid * lot_size)
    if margin <= 0: continue
    
    lots = min(int(alloc_cap // margin), 20)
    if lots == 0: continue
    
    credit_received = bx - sx
    comm = 400 * lots
    opt_pnl = ((credit_received - debit_paid) * lot_size * lots) - comm
    
    recovered_records.append({
        'year': y,
        'date': buy_date,
        'stock': stock,
        'rank': f"R{rank}",
        'alloc_cap': alloc_cap,
        'lots': lots,
        'pnl': opt_pnl
    })

df_rec = pd.DataFrame(recovered_records)

tot = len(df_rec)
wins = (df_rec['pnl'] > 0).sum()
wr = (wins / tot) * 100
net = df_rec['pnl'].sum()
avg = net / tot

print("==========================================================================")
print("  RECOVERED BULL CALL SPREAD PERFORMANCE (RELAXED ±10-MIN WINDOW)         ")
print("==========================================================================")
print(f"Total Recovered Option Trades: {tot} Trades")
print(f"Net Trade Win Rate %:              {wr:.2f}% ({wins} Wins / {tot-wins} Losses)")
print(f"Average Net PnL per Trade:         ₹{avg:,.2f} / trade")
print(f"🏆 TOTAL NET BULL CALL PNL:        ₹{net:,.2f} (~₹{net/100000:.2f} Lakhs)")
print("==========================================================================")
