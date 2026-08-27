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

r1_r3 = fut_df[(fut_df['year'] >= 2024) & (fut_df['rank'].isin([1, 3]))].copy()

stocks = tuple(r1_r3['stock'].unique())
stk_str = "', '".join(stocks)

# Only fetch the exact 10-minute window times!
times = ["15:16:00","15:17:00","15:18:00","15:19:00","15:20:00","15:21:00","15:22:00","15:23:00","15:24:00","15:25:00","15:26:00","15:27:00","15:28:00","15:29:00","15:30:00","15:31:00","15:32:00","15:33:00","15:34:00","15:35:00","15:36:00",
         "09:15:00","09:16:00","09:17:00","09:18:00","09:19:00","09:20:00","09:21:00","09:22:00","09:23:00","09:24:00","09:25:00","09:26:00","09:27:00","09:28:00","09:29:00","09:30:00","09:31:00","09:32:00","09:33:00","09:34:00","09:35:00"]
tm_str = "', '".join(times)

cursor.execute(f"SELECT stock_code, DATE(datetime) as dt, TIME(datetime) as tm, strike_price, `open`, `close` FROM scrapdata_options WHERE stock_code IN ('{stk_str}') AND `right`='Call' AND TIME(datetime) IN ('{tm_str}')")
all_ticks = cursor.fetchall()
cursor.close()
db.close()

tmap = {}
stk_days = {}

for r in all_ticks:
    stk = r['stock_code']
    d = str(r['dt'])
    t = str(r['tm'])
    sp = float(r['strike_price'])
    px = float(r['close']) if r['close'] else (float(r['open']) if r['open'] else 0)
    if px > 0:
        tmap[(stk, d, t, sp)] = px
    if stk not in stk_days: stk_days[stk] = set()
    stk_days[stk].add(d)

for stk in stk_days: stk_days[stk] = sorted(list(stk_days[stk]))

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

date_counts = r1_r3.groupby('date_str')['rank'].count().to_dict()
trade_records = []

for _, row in r1_r3.iterrows():
    stk = row['stock']
    buy_date = str(row['date_str'])
    y = row['year']
    rank = row['rank']
    
    num_trades = date_counts.get(buy_date, 1)
    alloc_cap = 200000 if num_trades > 1 else 400000
    
    if stk not in stk_days: continue
    days = [d for d in stk_days[stk] if d > buy_date]
    if len(days) < 1: continue
    d1_exit = days[0]
    
    sample_strikes = [sp for (s, d, t, sp) in tmap.keys() if s == stk and d == buy_date]
    if not sample_strikes: continue
    price = float(np.median(sample_strikes))
    
    buy_strike, sell_strike = generate_call_spread_strikes(price)
    lot_size = get_lot_size(stk, buy_date)
    
    def lookup(date, strike, target_time_str):
        target_dt = datetime.strptime(f"{date} {target_time_str}", "%Y-%m-%d %H:%M:%S")
        best_px = None
        min_diff = float('inf')
        for delta in range(-10, 11):
            curr_dt = target_dt + timedelta(minutes=delta)
            t_str = curr_dt.strftime("%H:%M:%S")
            key = (stk, date, t_str, float(strike))
            if key in tmap:
                diff = abs(delta)
                if diff < min_diff:
                    min_diff = diff
                    best_px = tmap[key]
        return best_px
        
    be = lookup(buy_date, buy_strike, "15:26:00")
    se = lookup(buy_date, sell_strike, "15:26:00")
    bx = lookup(d1_exit, buy_strike, "09:25:00")
    sx = lookup(d1_exit, sell_strike, "09:25:00")
    
    if None in [be, se, bx, sx]: continue
    
    debit_paid = be - se
    margin = (debit_paid * lot_size)
    if margin <= 0: continue
    
    lots = min(int(alloc_cap // margin), 20)
    if lots == 0: continue
    
    credit_received = bx - sx
    pnl = ((credit_received - debit_paid) * lot_size * lots) - (400 * lots)
    
    trade_records.append({'date': buy_date, 'rank': rank, 'pnl': pnl})

df = pd.DataFrame(trade_records)
tot = len(df)
wins = (df['pnl'] > 0).sum()
wr = (wins / tot) * 100 if tot > 0 else 0
net = df['pnl'].sum()
avg = net / tot if tot > 0 else 0

print("==========================================================================")
print("  RECOVERED BULL CALL SPREAD (CE) PERFORMANCE (RELAXED ±10-MIN WINDOW)    ")
print("==========================================================================")
print(f"Total Recovered CE Trades (R1 + R3): {tot} Trades")
print(f"Net Trade Win Rate %:                {wr:.2f}% ({wins} Wins / {tot-wins} Losses)")
print(f"Average Net PnL per Trade:           ₹{avg:,.2f} / trade")
print(f"🏆 TOTAL NET BULL CALL CE PNL:        ₹{net:,.2f} (~₹{net/100000:.2f} Lakhs)")
print("==========================================================================")
