#!/usr/bin/env python3
import mysql.connector
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from backtest_experiment import get_lot_size

db = mysql.connector.connect(host='localhost', user='root', password='root', database='markets')
cursor = db.cursor(dictionary=True)

df_list = []
for y in [2024, 2025, 2026]:
    try:
        t = pd.read_csv(f'experiment_targets_{y}.csv')
        t['year'] = y
        df_list.append(t)
    except: pass
targets = pd.concat(df_list)
r1_missing = targets[(targets['rank_type'] == 'R1') & (targets['buy_price'] == 'UNKNOWN')].copy()
r1_missing['date_str'] = pd.to_datetime(r1_missing['buy_date']).dt.strftime('%Y-%m-%d')

# Get Category 2 stocks
cursor.execute("SELECT DISTINCT stock_code FROM scrapdata_options")
fno_stocks = set(r['stock_code'] for r in cursor.fetchall())

cat2_missing = r1_missing[r1_missing['stock'].isin(fno_stocks)].copy()

cat2_stocks = tuple(cat2_missing['stock'].unique())
stk_str = "', '".join(cat2_stocks)
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

# Relaxed 10-minute window lookup function
def lookup_relaxed_10min(stock, date, strike, target_time_str, window_minutes=10):
    target_dt = datetime.strptime(f"{date} {target_time_str}", "%Y-%m-%d %H:%M:%S")
    best_px = None
    min_diff = float('inf')
    
    # Generate list of time strings in window
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

recovered_cat2 = []

for _, row in cat2_missing.iterrows():
    stock = row['stock']
    buy_date = str(row['date_str'])
    
    if stock not in stk_days: continue
    days = [d for d in stk_days[stock] if d > buy_date]
    if len(days) < 1: continue
    d1_exit = days[0]
    
    # Estimate stock price from surrounding strikes in DB
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
    max_drift = max(diff_se, diff_be, diff_sx, diff_bx)
    
    recovered_cat2.append({
        'date': buy_date,
        'stock': stock,
        'sell_strike': sell_strike,
        'buy_strike': buy_strike,
        'pnl': opt_pnl,
        'max_time_drift_mins': max_drift
    })

df_rec = pd.DataFrame(recovered_cat2)

print("==========================================================================")
print("  RECOVERED CATEGORY 2 R1 TRADES (RELAXED ±10-MINUTE WINDOW LOOKUP)        ")
print("==========================================================================")
print(f"Total Category 2 Missing R1 Trades Audited: {len(cat2_missing)} Trades")
print(f"Successfully Recovered Trades (within ±10 mins): {len(df_rec)} Trades ({(len(df_rec)/len(cat2_missing))*100:.1f}%) 🚀")

if len(df_rec) > 0:
    wins = (df_rec['pnl'] > 0).sum()
    wr = (wins / len(df_rec)) * 100
    net_pnl = df_rec['pnl'].sum()
    avg_pnl = net_pnl / len(df_rec)
    print(f"  • Recovered Trades Win Rate: {wr:.2f}% ({wins} Wins / {len(df_rec)-wins} Losses)")
    print(f"  • Recovered Trades Avg PnL:  ₹{avg_pnl:,.2f} / trade")
    print(f"  • APPROXIMATE ADDED NET PROFIT: ₹{net_pnl:,.2f} (~₹{net_pnl/100000:.2f} Lakhs)")
    print(f"  • Average Time Drift: {df_rec['max_time_drift_mins'].mean():.1f} minutes away from 15:26/09:25")

print("==========================================================================")
