import mysql.connector
import pandas as pd
import numpy as np

# Database connection
db = mysql.connector.connect(host='localhost', user='root', password='root', database='markets')
cursor = db.cursor(dictionary=True)

# Helper functions
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
    return [atm + step*i for i in range(2, -7, -1)]  # [0]=ATM+2, [1]=ATM+1, [2]=ATM(+1 ITM), [3]=ATM-1, [4]=ATM-2(-2 OTM)

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
        df_list.append(pd.read_csv(f'experiment_targets_{y}.csv'))
    except:
        pass
targets = pd.concat(df_list)
r1_r3 = targets[(targets['rank_type'].isin(['R1','R3'])) & (targets['buy_price'] != 'UNKNOWN')].copy()

# Lot sizes
from backtest_experiment import get_lot_size

print(f"Total R1+R3 Targets loaded: {len(r1_r3)}")

day1_losses = []
reversals = 0
worse_off = 0
same = 0

day1_total_pnl = 0.0
day2_total_pnl_for_losses = 0.0
day1_loss_sum = 0.0

tested_trades = 0
loss_trade_count = 0

for _, row in r1_r3.iterrows():
    stock = row['stock']
    buy_date = row['buy_date']
    price = float(row['buy_price'])
    
    future_dates = get_trading_days(cursor, stock, buy_date)
    if len(future_dates) < 2:
        continue
        
    day1_exit_date = future_dates[0]
    day2_exit_date = future_dates[1]
    
    strikes = generate_strikes(price)
    sell_strike = strikes[2] # +1 ITM
    buy_strike = strikes[4]  # -2 OTM
    
    lot_size = get_lot_size(stock, buy_date)
    margin = (sell_strike - buy_strike) * lot_size
    lots = min(int(400000 // margin), 20) if margin > 0 else 0
    if lots == 0:
        continue
        
    se = get_price(cursor, stock, buy_date, sell_strike, 'entry')
    be = get_price(cursor, stock, buy_date, buy_strike, 'entry')
    sx1 = get_price(cursor, stock, day1_exit_date, sell_strike, 'exit')
    bx1 = get_price(cursor, stock, day1_exit_date, buy_strike, 'exit')
    
    if None in [se, be, sx1, bx1]:
        continue
        
    tested_trades += 1
    credit = se - be
    debit1 = sx1 - bx1
    comm = 300 * lots * 2
    pnl1 = ((credit - debit1) * lot_size * lots) - comm
    
    day1_total_pnl += pnl1
    
    if pnl1 < 0:
        loss_trade_count += 1
        day1_loss_sum += pnl1
        
        # Check Day 2
        sx2 = get_price(cursor, stock, day2_exit_date, sell_strike, 'exit')
        bx2 = get_price(cursor, stock, day2_exit_date, buy_strike, 'exit')
        
        if None in [sx2, bx2]:
            day2_status = "NO_DAY2_DATA"
            pnl2 = pnl1 # fallback
        else:
            debit2 = sx2 - bx2
            pnl2 = ((credit - debit2) * lot_size * lots) - comm
            day2_total_pnl_for_losses += pnl2
            
            if pnl2 > 0:
                reversals += 1
                diff = pnl2 - pnl1
                print(f"REVERSED TO WIN: {buy_date} {stock:<12} Day1 PnL: ₹{pnl1:>9,.2f} -> Day2 PnL: ₹{pnl2:>9,.2f} (Gain: +₹{diff:,.2f})")
            elif pnl2 > pnl1:
                diff = pnl2 - pnl1
                print(f"REDUCED LOSS:   {buy_date} {stock:<12} Day1 PnL: ₹{pnl1:>9,.2f} -> Day2 PnL: ₹{pnl2:>9,.2f} (Recovered: +₹{diff:,.2f})")
            elif pnl2 < pnl1:
                worse_off += 1
                diff = pnl1 - pnl2
                print(f"WORSE LOSS:     {buy_date} {stock:<12} Day1 PnL: ₹{pnl1:>9,.2f} -> Day2 PnL: ₹{pnl2:>9,.2f} (Extra Loss: -₹{diff:,.2f})")
            else:
                same += 1

print("\n" + "="*80)
print("=== HOLDING LOSING TRADES FOR 1 EXTRA DAY (DAY 2 09:25 EXIT) ANALYSIS ===")
print("="*80)
print(f"Total Trades Evaluated: {tested_trades}")
print(f"Losing Trades on Day 1: {loss_trade_count} ({(loss_trade_count/tested_trades)*100:.1f}%)")
print(f"Total Day 1 Losses Sum: ₹{day1_loss_sum:,.2f}")
print(f"\nOf those {loss_trade_count} losing trades, if held until Day 2:")
print(f"1. Fully Reversed to Positive Profit (WIN): {reversals} trades")
print(f"2. Deepened / Max Loss Expanded (WORSE):     {worse_off} trades")
print(f"Total Net PnL of these losing trades if held to Day 2: ₹{day2_total_pnl_for_losses:,.2f}")
net_benefit = day2_total_pnl_for_losses - day1_loss_sum
print(f"Net Financial Impact of Holding to Day 2: {'+₹' if net_benefit >=0 else '-₹'}{abs(net_benefit):,.2f}")
