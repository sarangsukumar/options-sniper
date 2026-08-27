#!/usr/bin/env python3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from datetime import datetime, timedelta

from backtest_experiment import get_lot_size

fut_file = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/historical_models/output/trades_dynamic_threshold.csv'
fut_df = pd.read_csv(fut_file)
fut_df['date_str'] = pd.to_datetime(fut_df['date']).dt.strftime('%Y-%m-%d')
fut_df['rank'] = fut_df.groupby('date').cumcount() + 1
fut_df['year'] = pd.to_datetime(fut_df['date']).dt.year

r1_r3 = fut_df[(fut_df['year'] >= 2024) & (fut_df['rank'].isin([1, 3]))].copy()

# Load CE ticks from CSV
ticks_df = pd.read_csv('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/FINAL_OPTIONS_SYSTEM/all_ce_ticks_10m.csv')
tmap = {}
stk_days = {}
strike_dict = {}

for _, r in ticks_df.iterrows():
    stk = str(r['stock_code'])
    d = str(r['dt'])
    t_str = str(r['tm'])
    sp = float(r['strike_price'])
    cl = float(r['close']) if not pd.isna(r['close']) else 0
    op = float(r['open']) if not pd.isna(r['open']) else 0
    px = cl if cl > 0 else op
    if px > 0:
        tmap[(stk, d, t_str, sp)] = px
        if (stk, d) not in strike_dict: strike_dict[(stk, d)] = set()
        strike_dict[(stk, d)].add(sp)
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
    
    if (stk, buy_date) not in strike_dict: continue
    sample_strikes = list(strike_dict[(stk, buy_date)])
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
            # Format time correctly to match CSV dump (HH:MM:SS)
            if len(t_str) == 7: t_str = "0" + t_str
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
