"""
IDEAL EXIT TIME EXPERIMENT
==========================
Tests exiting the +1 ITM / -3 OTM spread at various times on Day 1.
We will test:
- 09:15 to 10:00 (every 5 minutes)
- 10:00 to 15:00 (hourly)
- 15:15 (EOD)
"""

import mysql.connector
import pandas as pd
from collections import Counter
from backtest_experiment import get_lot_size

db = mysql.connector.connect(host='localhost', user='root', password='root', database='markets')
cursor = db.cursor(dictionary=True)

def get_real_step(stock, date):
    cursor.execute("SELECT DISTINCT strike_price FROM scrapdata_options WHERE stock_code=%s AND DATE(datetime)=%s AND `right`='Put' ORDER BY strike_price", (stock, date))
    rows = cursor.fetchall()
    if len(rows) < 2: return None
    strikes = sorted([float(r['strike_price']) for r in rows])
    diffs   = [round(strikes[i+1] - strikes[i], 2) for i in range(len(strikes)-1) if strikes[i+1] - strikes[i] > 0]
    if not diffs: return None
    return Counter(diffs).most_common(1)[0][0], strikes

def get_price(stock, date, time_str, strike):
    # Try exact time, if not found try next 2 minutes
    t_obj = pd.to_datetime(time_str)
    times = [(t_obj + pd.Timedelta(minutes=i)).strftime("%H:%M:00") for i in range(3)]
    for t in times:
        cursor.execute("SELECT close FROM scrapdata_options WHERE stock_code=%s AND datetime=%s AND strike_price=%s AND `right`='Put' LIMIT 1", (stock, f"{date} {t}", strike))
        r = cursor.fetchone()
        if r and r['close']: return float(r['close'])
    return None

def get_next_day(stock, date):
    cursor.execute("SELECT MIN(DATE(datetime)) as nd FROM scrapdata_options WHERE stock_code=%s AND DATE(datetime)>%s", (stock, date))
    r = cursor.fetchone()
    return str(r['nd']) if r and r['nd'] else None

df_list = []
for y in range(2024, 2027):
    try: df_list.append(pd.read_csv(f'experiment_targets_{y}.csv'))
    except: pass
targets = pd.concat(df_list, ignore_index=True)
r1r3 = targets[(targets['rank_type'].isin(['R1','R3'])) & (targets['buy_price'] != 'UNKNOWN')]

test_times = [
    "09:16", "09:20", "09:25", "09:30", "09:35", "09:45", "10:00",
    "11:00", "12:00", "13:00", "14:00", "15:00", "15:15"
]
time_results = {t: {'pnl': 0, 'trades': 0} for t in test_times}

for _, row in r1r3.iterrows():
    stock = row['stock']
    date  = row['buy_date']
    price = float(row['buy_price'])

    exit_date = get_next_day(stock, date)
    if not exit_date: continue

    chain_info = get_real_step(stock, date)
    if not chain_info: continue
    step, available_strikes = chain_info

    atm = min(available_strikes, key=lambda x: abs(x - price))
    sell_strike = min(available_strikes, key=lambda x: abs(x - (atm + step)))
    buy_strike  = min(available_strikes, key=lambda x: abs(x - (atm - (step * 3))))

    if sell_strike <= buy_strike: continue

    entry_sell = get_price(stock, date, "15:25", sell_strike)
    entry_buy  = get_price(stock, date, "15:25", buy_strike)
    if None in [entry_sell, entry_buy]: continue
    entry_credit = entry_sell - entry_buy

    lot_size = get_lot_size(stock, date)
    margin = (sell_strike - buy_strike) * lot_size
    if margin <= 0: continue
    lots = max(1, min(int(400000 // margin), 20))

    for t in test_times:
        exit_sell = get_price(stock, exit_date, t, sell_strike)
        exit_buy  = get_price(stock, exit_date, t, buy_strike)
        if None not in [exit_sell, exit_buy]:
            exit_debit = exit_sell - exit_buy
            pnl = ((entry_credit - exit_debit) * lot_size * lots) - (400 * lots)
            time_results[t]['pnl'] += pnl
            time_results[t]['trades'] += 1

print("========================================")
print("  IDEAL EXIT TIME EXPERIMENT RESULTS")
print("========================================")
print(f"{'Exit Time':<12} | {'Total PnL':<15} | {'Trades'}")
print("-" * 40)
for t in test_times:
    r = time_results[t]
    print(f"{t:<12} | ₹{r['pnl']:<14,.2f} | {r['trades']}")
