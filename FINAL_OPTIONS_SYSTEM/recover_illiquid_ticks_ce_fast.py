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

date_counts = r1_r3.groupby('date_str')['rank'].count().to_dict()

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

trade_records = []

for date_str, group in r1_r3.groupby('date_str'):
    num_trades = len(group)
    alloc_cap = 200000 if num_trades > 1 else 400000
    
    for _, row in group.iterrows():
        stk = row['stock']
        rank = row['rank']
        y = row['year']
        
        cursor.execute("SELECT DATE(datetime) as dt, TIME(datetime) as tm, strike_price, close, open FROM scrapdata_options WHERE stock_code=%s AND datetime >= %s AND datetime <= DATE_ADD(%s, INTERVAL 3 DAY) AND `right`='Call'", (stk, date_str, date_str))
        rows = cursor.fetchall()
        if not rows: continue
        
        tmap = {}
        dates = set()
        for r in rows:
            d = str(r['dt'])
            t = str(r['tm'])
            sp = float(r['strike_price'])
            cl = float(r['close']) if r['close'] else 0
            op = float(r['open']) if r['open'] else 0
            px = cl if cl > 0 else op
            if px > 0: tmap[(d, t, sp)] = px
            dates.add(d)
            
        sorted_dates = sorted(list(dates))
        if date_str not in sorted_dates: continue
        idx = sorted_dates.index(date_str)
        if idx + 1 >= len(sorted_dates): continue
        d1_exit = sorted_dates[idx + 1]
        
        sample_strikes = [sp for (d, t, sp) in tmap.keys() if d == date_str]
        if not sample_strikes: continue
        price = float(np.median(sample_strikes))
        
        buy_strike, sell_strike = generate_call_spread_strikes(price)
        lot_size = get_lot_size(stk, date_str)
        
        def lookup_relaxed_10min(date, strike, target_time_str, window_minutes=10):
            target_dt = datetime.strptime(f"{date} {target_time_str}", "%Y-%m-%d %H:%M:%S")
            best_px = None
            min_diff = float('inf')
            for delta in range(-window_minutes, window_minutes + 1):
                curr_dt = target_dt + timedelta(minutes=delta)
                t_str = curr_dt.strftime("%H:%M:%S")
                key = (date, t_str, float(strike))
                if key in tmap:
                    diff = abs(delta)
                    if diff < min_diff:
                        min_diff = diff
                        best_px = tmap[key]
            return best_px
            
        be = lookup_relaxed_10min(date_str, buy_strike, "15:26:00", 10)
        se = lookup_relaxed_10min(date_str, sell_strike, "15:26:00", 10)
        bx = lookup_relaxed_10min(d1_exit, buy_strike, "09:25:00", 10)
        sx = lookup_relaxed_10min(d1_exit, sell_strike, "09:25:00", 10)
        
        if None in [be, se, bx, sx]: continue
        
        debit_paid = be - se
        margin = (debit_paid * lot_size)
        if margin <= 0: continue
        
        lots = min(int(alloc_cap // margin), 20)
        if lots == 0: continue
        
        credit_received = bx - sx
        pnl = ((credit_received - debit_paid) * lot_size * lots) - (400 * lots)
        
        trade_records.append({
            'date': date_str,
            'year': y,
            'rank': f"R{rank}",
            'pnl': pnl
        })

cursor.close()
db.close()

df = pd.DataFrame(trade_records)
tot = len(df)
wins = (df['pnl'] > 0).sum()
wr = (wins / tot) * 100
net = df['pnl'].sum()
avg = net / tot

print("==========================================================================")
print("  RECOVERED BULL CALL SPREAD (CE) PERFORMANCE (RELAXED ±10-MIN WINDOW)    ")
print("==========================================================================")
print(f"Total Recovered CE Trades (R1 + R3): {tot} Trades")
print(f"Net Trade Win Rate %:                {wr:.2f}% ({wins} Wins / {tot-wins} Losses)")
print(f"Average Net PnL per Trade:           ₹{avg:,.2f} / trade")
print(f"🏆 TOTAL NET BULL CALL CE PNL:        ₹{net:,.2f} (~₹{net/100000:.2f} Lakhs)")
print("==========================================================================")
