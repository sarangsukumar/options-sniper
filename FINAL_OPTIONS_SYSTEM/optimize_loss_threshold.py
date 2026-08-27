import mysql.connector
import pandas as pd
import numpy as np
from backtest_experiment import get_lot_size

db = mysql.connector.connect(host='localhost', user='root', password='root', database='markets')
cursor = db.cursor(dictionary=True)

def get_strike_step(price):
    if price > 2500: return 50
    if price > 1000: return 20
    if price > 500:  return 10
    if price > 100:  return 5
    if price > 50:   return 2.5
    return 1

def generate_strikes(buy_price):
    step = get_strike_step(buy_price)
    atm = round(buy_price / step) * step
    strikes = [atm + step*i for i in range(2, -7, -1)]
    return strikes[2], strikes[4]

def get_price(cursor, stock, date, strike, mode):
    if mode == 'entry':
        times = ["15:26:00","15:25:00","15:27:00","15:24:00","15:28:00",
                 "09:56:00","09:55:00","09:57:00","09:54:00","09:58:00"]
        col = 'close'
    else:
        times = ["09:29:00","09:28:00","09:30:00","09:27:00","09:31:00",
                 "03:59:00","03:58:00","04:00:00","03:57:00","04:01:00"]
        col = 'open'
    for t in times:
        cursor.execute(
            f"SELECT {col} as px FROM scrapdata_options "
            f"WHERE stock_code=%s AND DATE(datetime)=%s AND TIME(datetime)=%s "
            f"AND strike_price=%s AND `right`='Put' LIMIT 1",
            (stock, date, t, strike)
        )
        r = cursor.fetchone()
        if r and r['px'] and float(r['px']) > 0:
            return float(r['px'])
    return None

def get_trading_days(cursor, stock, start_date):
    cursor.execute(
        "SELECT DISTINCT DATE(datetime) as d FROM scrapdata_options "
        "WHERE stock_code=%s AND DATE(datetime) > %s ORDER BY d ASC LIMIT 5",
        (stock, start_date)
    )
    rows = cursor.fetchall()
    return [str(r['d']) for r in rows]

# Load targets
df_list = []
for y in [2024, 2025, 2026]:
    try:
        df = pd.read_csv(f'experiment_targets_{y}.csv')
        df['target_year'] = y
        df_list.append(df)
    except: pass
targets = pd.concat(df_list)
r1_r3 = targets[(targets['rank_type'].isin(['R1','R3'])) & (targets['buy_price'] != 'UNKNOWN')].copy()

trades_data = []

for _, row in r1_r3.iterrows():
    stock = row['stock']
    buy_date = row['buy_date']
    price = float(row['buy_price'])
    y = row['target_year']
    
    future_dates = get_trading_days(cursor, stock, buy_date)
    if len(future_dates) < 2: continue
    
    day1_exit = future_dates[0]
    day2_exit = future_dates[1]
    
    sell_strike, buy_strike = generate_strikes(price)
    lot_size = get_lot_size(stock, buy_date)
    margin = (sell_strike - buy_strike) * lot_size
    lots = min(int(400000 // margin), 20) if margin > 0 else 0
    if lots == 0: continue
    
    se = get_price(cursor, stock, buy_date, sell_strike, 'entry')
    be = get_price(cursor, stock, buy_date, buy_strike, 'entry')
    sx1 = get_price(cursor, stock, day1_exit, sell_strike, 'exit')
    bx1 = get_price(cursor, stock, day1_exit, buy_strike, 'exit')
    
    if None in [se, be, sx1, bx1]: continue
    
    credit = se - be
    debit1 = sx1 - bx1
    comm = 300 * lots * 2
    pnl1 = ((credit - debit1) * lot_size * lots) - comm
    
    sx2 = get_price(cursor, stock, day2_exit, sell_strike, 'exit')
    bx2 = get_price(cursor, stock, day2_exit, buy_strike, 'exit')
    
    if None in [sx2, bx2]: continue
    debit2 = sx2 - bx2
    pnl2 = ((credit - debit2) * lot_size * lots) - comm
    
    trades_data.append({
        'year': y, 'stock': stock, 'buy_date': buy_date,
        'pnl1': pnl1, 'pnl2': pnl2,
        'margin_used': margin * lots
    })

df_all = pd.DataFrame(trades_data)

print(f"Total fully paired trades: {len(df_all)}")

# Baseline PnL (Close ALL trades at Day 1 09:25)
baseline_pnl = df_all['pnl1'].sum()
print(f"Baseline Portfolio Net PnL (Standard Day 1 Exit for all): ₹{baseline_pnl:,.2f}")

# Grid Search on Loss Thresholds (both absolute ₹ and % of margin)
thresholds = [
    0, -2000, -5000, -10000, -15000, -20000, -25000, -30000, -40000, -50000, -75000, -100000
]

results = []

for th in thresholds:
    # Rule: If Day 1 PnL <= th (i.e. loss is worse than threshold), HOLD to Day 2.
    # Otherwise, close on Day 1 (take pnl1).
    held_trades = df_all[df_all['pnl1'] <= th]
    
    # Calculate strategy PnL under this threshold
    # For trades where pnl1 <= th, use pnl2; else use pnl1
    sim_pnl = np.where(df_all['pnl1'] <= th, df_all['pnl2'], df_all['pnl1']).sum()
    
    benefit = sim_pnl - baseline_pnl
    
    held_count = len(held_trades)
    if held_count > 0:
        rev_count = sum(held_trades['pnl2'] > 0)
        improved_count = sum(held_trades['pnl2'] > held_trades['pnl1'])
        win_rate_on_held = (rev_count / held_count) * 100
        improvement_rate = (improved_count / held_count) * 100
    else:
        rev_count, improved_count, win_rate_on_held, improvement_rate = 0, 0, 0, 0
        
    results.append({
        'Threshold (₹)': f"Loss worse than ₹{abs(th):,}" if th < 0 else "Hold ALL Losses (pnl1 < 0)",
        'Trades Held': held_count,
        'Reversed to WIN': f"{rev_count} ({win_rate_on_held:.1f}%)",
        'Improved PnL': f"{improved_count} ({improvement_rate:.1f}%)",
        'Total Portfolio PnL (₹)': sim_pnl,
        'Net Extra Gain vs Baseline (₹)': benefit
    })

df_res = pd.DataFrame(results)

print("\n" + "="*110)
print("=== OPTIMAL LOSS THRESHOLD OPTIMIZATION FOR DAY 2 HOLD ===")
print("="*110)
print(df_res.to_string(index=False))
print("="*110)
