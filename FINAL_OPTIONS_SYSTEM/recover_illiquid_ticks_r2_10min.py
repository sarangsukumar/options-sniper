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

r2_fut = fut_df[(fut_df['year'] >= 2024) & (fut_df['rank'] == 2)].copy()

stocks = tuple(r2_fut['stock'].unique())
stk_str = "', '".join(stocks)
cursor.execute(f"SELECT stock_code, DATE(datetime) as dt, TIME(datetime) as tm, strike_price, `right`, `open`, `close` FROM scrapdata_options WHERE stock_code IN ('{stk_str}') AND `right`='Put'")
all_ticks = cursor.fetchall()
cursor.close()
db.close()

tick_map_close = {}
tick_map_open = {}
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
        tick_map_open[(stk, d_str, t_str, sp)] = px
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

def generate_wide_strikes(buy_price):
    step = get_strike_step(buy_price)
    atm = round(buy_price / step) * step
    return atm + step, atm - (3 * step)

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
                
    return best_px, min_diff

r2_records = []

for _, row in r2_fut.iterrows():
    stock = row['stock']
    buy_date = str(row['date_str'])
    
    if stock not in stk_days: continue
    days = [d for d in stk_days[stock] if d > buy_date]
    if len(days) < 1: continue
    d1_exit = days[0]
    
    sample_strikes = [sp for (s, d, t, sp) in tick_map_close.keys() if s == stock and d == buy_date]
    if not sample_strikes: continue
    price = float(np.median(sample_strikes))
    
    sell_strike, buy_strike = generate_wide_strikes(price)
    lot_size = get_lot_size(stock, buy_date)
    margin = (sell_strike - buy_strike) * lot_size
    lots = min(int(400000 // margin), 20) if margin > 0 else 0
    if lots == 0: continue
    
    se, diff_se = lookup_relaxed_10min(stock, buy_date, sell_strike, "15:26:00", 10)
    be, diff_be = lookup_relaxed_10min(stock, buy_date, buy_strike, "15:26:00", 10)
    sx, diff_sx = lookup_relaxed_10min(stock, d1_exit, sell_strike, "09:25:00", 10)
    bx, diff_bx = lookup_relaxed_10min(stock, d1_exit, buy_strike, "09:25:00", 10)
    
    if None in [se, be, sx, bx]: continue
    
    credit = se - be
    debit = sx - bx
    comm = 400 * lots
    opt_pnl = ((credit - debit) * lot_size * lots) - comm
    
    r2_records.append({
        'date': buy_date,
        'stock': stock,
        'pnl': opt_pnl
    })

df_r2 = pd.DataFrame(r2_records)

tot = len(df_r2)
wins = (df_r2['pnl'] > 0).sum()
wr = (wins / tot) * 100
net = df_r2['pnl'].sum()
avg = net / tot

print("==========================================================================")
print("  RECOVERED RANK 2 (R2) OPTIONS PERFORMANCE AUDIT (RELAXED ±10-MIN WINDOW) ")
print("==========================================================================")
print(f"Total Recovered R2 Option Trades: {tot} Trades (vs 118 in strict baseline)")
print(f"Net Trade Win Rate %:              {wr:.2f}% ({wins} Wins / {tot-wins} Losses)")
print(f"Average Net PnL per Trade:         ₹{avg:,.2f} / trade")
print(f"🏆 TOTAL NET R2 OPTIONS PNL:        ₹{net:,.2f} (~₹{net/100000:.2f} Lakhs)")
print("==========================================================================")
