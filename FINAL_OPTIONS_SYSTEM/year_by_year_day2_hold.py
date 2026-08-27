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

yearly_data = {2024: [], 2025: [], 2026: []}

for y in [2024, 2025, 2026]:
    try:
        df = pd.read_csv(f'experiment_targets_{y}.csv')
        df_r = df[(df['rank_type'].isin(['R1','R3'])) & (df['buy_price'] != 'UNKNOWN')].copy()
        for _, row in df_r.iterrows():
            stock = row['stock']
            buy_date = row['buy_date']
            price = float(row['buy_price'])
            
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
            
            if pnl1 < 0:
                sx2 = get_price(cursor, stock, day2_exit, sell_strike, 'exit')
                bx2 = get_price(cursor, stock, day2_exit, buy_strike, 'exit')
                if None in [sx2, bx2]: continue
                debit2 = sx2 - bx2
                pnl2 = ((credit - debit2) * lot_size * lots) - comm
                
                yearly_data[y].append({
                    'stock': stock, 'buy_date': buy_date,
                    'pnl1': pnl1, 'pnl2': pnl2,
                    'reversed': pnl2 > 0,
                    'reduced': (pnl2 <= 0 and pnl2 > pnl1),
                    'worse': pnl2 < pnl1
                })
    except Exception as e:
        print(f"Error for {y}: {e}")

print("\n" + "="*85)
print(f"{'Year':<6} | {'Loss Trades':<11} | {'Reversed to WIN':<16} | {'Reduced Loss':<14} | {'Worse Loss':<12} | {'Net Benefit (₹)':<16}")
print("="*85)

for y in [2024, 2025, 2026]:
    trades = yearly_data[y]
    if not trades: continue
    total_l = len(trades)
    rev = sum(1 for t in trades if t['reversed'])
    red = sum(1 for t in trades if t['reduced'])
    wor = sum(1 for t in trades if t['worse'])
    sum1 = sum(t['pnl1'] for t in trades)
    sum2 = sum(t['pnl2'] for t in trades)
    net_diff = sum2 - sum1
    
    print(f"{y:<6} | {total_l:<11} | {rev} ({rev/total_l*100:4.1f}%)       | {red} ({red/total_l*100:4.1f}%)     | {wor} ({wor/total_l*100:4.1f}%)   | {net_diff:>+14,.2f}")

print("="*85)
